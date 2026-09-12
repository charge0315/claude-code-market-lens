"""銘柄ナレッジノート（Obsidian Vault の ``Tickers/<コード>_<銘柄名>.md``）から
構造化データのみを読み出すサービス.

Market Lens `backend/services/brand_notes_service.py` から移植。変更点:
- 読み込み先を ``settings.brand_notes_dir`` → ``settings.resolved_brand_notes_dir``
  （未指定なら ``<VAULT_ROOT>/Tickers`` を導出）に変更。
- 四季報スタブ期間中は、この frontmatter の財務指標が fundamental 特徴量の主データ源になる
  （`plans/00_調査サマリ` §2.3、`SHIKIHO_ENABLED=false`）。

ノート本文にはスクレイピング由来のニュース見出し・四季報記事・投資メモなど外部由来の
生テキストが含まれるが、本サービスは **YAML フロントマターの構造化フィールドだけ** を
抽出して返す（プロンプトインジェクション対策。CLAUDE.md「外部由来テキストは frontmatter のみ」）。

ファイル未整備・パース失敗・ディレクトリ不在のいずれも例外を送出せず ``None`` を返す
（フェイルソフト）。全銘柄分（数千ファイル）存在しうるため TTL 付きインメモリキャッシュで
再読込を抑える。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from backend.config import settings

logger = logging.getLogger(__name__)

# ノートは日次スクレイピングで更新されるため、長すぎない TTL とする。
_CACHE_TTL_SECONDS = 900.0

# frontmatter で「未取得」を表すプレースホルダ（小文字で比較する）。
_PLACEHOLDER_VALUES = frozenset({"---", "--", "-", "", "n/a", "na", "null", "none", "tbd"})

# 先頭の YAML frontmatter だけを取り出す。区切りは「行頭〜行末が --- だけの行」に限定し、
# 値中の "---"（例: ``fiscal_year_end: "---"``）で誤って切らないようにする。
_FRONTMATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n", re.DOTALL)


@dataclass(frozen=True)
class BrandNote:
    """銘柄ナレッジノートから抽出した構造化情報（本文の生テキストは一切含まない）.

    フィールド名は frontmatter のキー名にそのまま揃える（LLM プロンプト・tool_result に
    そのまま載るため意味が自明な名前を優先）。
    """

    code: str
    name: str | None
    name_en: str | None
    security_type: str | None
    market: str | None
    sector33: str | None
    sector17: str | None
    scale_cat: str | None
    fiscal_year_end: str | None
    listing_date: str | None
    last_earnings_date: str | None
    last_earnings_type: str | None
    close_date: str | None
    data_as_of: str | None
    close_price: float | None
    market_cap_oku: float | None
    per_forecast: float | None
    pbr: float | None
    roe: float | None
    equity_ratio: float | None
    dividend_yield_forecast: float | None
    bps: float | None
    eps_forecast: float | None
    dividend_forecast: float | None
    shares_outstanding: int | None

    def to_prompt_dict(self) -> dict[str, object]:
        """``None`` を除いた構造化 dict を返す（LLM プロンプト・tool_result 埋め込み用）."""
        raw: dict[str, object | None] = {
            "code": self.code,
            "name": self.name,
            "name_en": self.name_en,
            "security_type": self.security_type,
            "market": self.market,
            "sector33": self.sector33,
            "sector17": self.sector17,
            "scale_cat": self.scale_cat,
            "fiscal_year_end": self.fiscal_year_end,
            "listing_date": self.listing_date,
            "last_earnings_date": self.last_earnings_date,
            "last_earnings_type": self.last_earnings_type,
            "close_date": self.close_date,
            "data_as_of": self.data_as_of,
            "close_price": self.close_price,
            "market_cap_oku": self.market_cap_oku,
            "per_forecast": self.per_forecast,
            "pbr": self.pbr,
            "roe": self.roe,
            "equity_ratio": self.equity_ratio,
            "dividend_yield_forecast": self.dividend_yield_forecast,
            "bps": self.bps,
            "eps_forecast": self.eps_forecast,
            "dividend_forecast": self.dividend_forecast,
            "shares_outstanding": self.shares_outstanding,
        }
        return {key: value for key, value in raw.items() if value is not None}


# code -> (expires_at, BrandNote | None)。「見つからなかった」結果も TTL 付きでキャッシュし、
# 未整備の銘柄について毎回ディレクトリ走査するのを防ぐ。
_cache: dict[str, tuple[float, BrandNote | None]] = {}


def clear_cache() -> None:
    """インメモリキャッシュを空にする（主にテスト用・ノートディレクトリ差し替え時）."""
    _cache.clear()


async def get_brand_note(code: str) -> BrandNote | None:
    """指定コードの銘柄ナレッジノートを読み、構造化情報を返す（未整備・失敗時は ``None``）."""
    normalized = code.strip()
    if not normalized:
        return None

    now = time.monotonic()
    cached = _cache.get(normalized)
    if cached is not None and cached[0] > now:
        return cached[1]

    note = await asyncio.to_thread(_load_brand_note, normalized)
    _cache[normalized] = (now + _CACHE_TTL_SECONDS, note)
    return note


async def get_raw_note_content(code: str) -> tuple[str, str] | None:
    """指定コードの銘柄ナレッジノートを **本文込みで** 生テキストのまま返す（UI 表示専用）.

    ⚠️ この関数の戻り値は絶対に LLM プロンプトへ渡さないこと。本モジュールの他の関数
    （`get_brand_note`）が frontmatter のみを抽出するのは CLAUDE.md のプロンプトインジェクション
    防御原則のためであり、その原則は「LLM への入力」を対象にしたものであって「ユーザー本人への
    画面表示」には適用されない（ユーザーは自分自身の Vault ノートを読む権利がある）。
    呼び出し先は必ず UI 表示（銘柄詳細のポップアップ等）に限定すること。

    戻り値は `(note_title, full_markdown_text)`。ノート未整備・読み込み失敗時は `None`。
    """
    normalized = code.strip()
    if not normalized:
        return None

    def _load() -> tuple[str, str] | None:
        path = _find_note_path(normalized)
        if path is None:
            return None
        try:
            return path.stem, path.read_text(encoding="utf-8")
        except OSError:
            return None

    return await asyncio.to_thread(_load)


def _load_brand_note(code: str) -> BrandNote | None:
    """同期でノートファイルを探索・パースする（``asyncio.to_thread`` から呼ばれる）."""
    try:
        path = _find_note_path(code)
        if path is None:
            return None
        text = path.read_text(encoding="utf-8")
        frontmatter = _extract_frontmatter(text)
        if frontmatter is None:
            return None
        return _build_note(code, frontmatter)
    except Exception:
        # ディレクトリ不在・権限エラー・不正 YAML・想定外の型など、原因を問わずフェイルソフト。
        logger.warning("銘柄ナレッジノートの読み込みに失敗しました: %s", code, exc_info=True)
        return None


def _find_note_path(code: str) -> Path | None:
    """``<コード>_*.md`` に前方一致するノートファイルのパスを返す（無ければ ``None``）.

    ファイル名の銘柄名部分は可変（例: ``1301_極洋.md``）なため glob で引く。複数該当時は
    ソート順で先頭を採用し、呼び出しごとの決定性を保つ。
    """
    notes_dir = settings.resolved_brand_notes_dir
    if not notes_dir.is_dir():
        return None
    matches = sorted(notes_dir.glob(f"{code}_*.md"))
    return matches[0] if matches else None


def _extract_frontmatter(text: str) -> dict[str, object] | None:
    """ファイル先頭の YAML frontmatter を dict として返す（無い・不正なら ``None``）."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return None
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _build_note(code: str, frontmatter: dict[str, object]) -> BrandNote:
    """frontmatter dict を型変換して ``BrandNote`` に詰める."""
    fm_code = _coerce_str(frontmatter.get("code"))
    return BrandNote(
        code=fm_code or code,
        name=_coerce_str(frontmatter.get("name")),
        name_en=_coerce_str(frontmatter.get("name_en")),
        security_type=_coerce_str(frontmatter.get("security_type")),
        market=_coerce_str(frontmatter.get("market")),
        sector33=_coerce_str(frontmatter.get("sector33")),
        sector17=_coerce_str(frontmatter.get("sector17")),
        scale_cat=_coerce_str(frontmatter.get("scale_cat")),
        fiscal_year_end=_coerce_str(frontmatter.get("fiscal_year_end")),
        listing_date=_coerce_str(frontmatter.get("listing_date")),
        last_earnings_date=_coerce_str(frontmatter.get("last_earnings_date")),
        last_earnings_type=_coerce_str(frontmatter.get("last_earnings_type")),
        close_date=_coerce_str(frontmatter.get("close_date")),
        data_as_of=_coerce_str(frontmatter.get("data_as_of")),
        close_price=_coerce_float(frontmatter.get("close_price")),
        market_cap_oku=_coerce_float(frontmatter.get("market_cap_oku")),
        per_forecast=_coerce_float(frontmatter.get("per_forecast")),
        pbr=_coerce_float(frontmatter.get("pbr")),
        roe=_coerce_float(frontmatter.get("roe")),
        equity_ratio=_coerce_float(frontmatter.get("equity_ratio")),
        dividend_yield_forecast=_coerce_float(frontmatter.get("dividend_yield_forecast")),
        bps=_coerce_float(frontmatter.get("bps")),
        eps_forecast=_coerce_float(frontmatter.get("eps_forecast")),
        dividend_forecast=_coerce_float(frontmatter.get("dividend_forecast")),
        shares_outstanding=_coerce_int(frontmatter.get("shares_outstanding")),
    )


def _is_placeholder(value: str) -> bool:
    return value.strip().lower() in _PLACEHOLDER_VALUES


def _coerce_str(value: object) -> str | None:
    """空・プレースホルダ（``---`` 等）は ``None`` に正規化した文字列を返す."""
    if value is None:
        return None
    text = str(value).strip()
    return None if _is_placeholder(text) else text


def _coerce_float(value: object) -> float | None:
    """数値・数値文字列を ``float`` に、プレースホルダや変換不能値は ``None`` にする."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if _is_placeholder(text):
        return None
    try:
        return float(text.replace(",", "").replace("%", ""))
    except ValueError:
        return None


def _coerce_int(value: object) -> int | None:
    """整数・整数文字列を ``int`` に、それ以外は ``None`` にする."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    coerced = _coerce_float(value)
    return int(coerced) if coerced is not None else None
