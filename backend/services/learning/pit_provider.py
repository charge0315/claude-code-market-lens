"""Point-in-time（時点整合）ファンダメンタル特徴量のデータソース抽象（🆕 P29）.

`plans/03_システム設計` §3.7.2。日次スナップショット収集（`pit_snapshot_service.py`）は
`PitFundamentalProvider` にのみ依存し、具体的なデータソース（Vault frontmatter / 四季報等）を
知らない。四季報が `SHIKIHO_ENABLED=true` で有効化された際は `ShikihoProvider` を実装して
追加するだけで済み、スキーマ変更もモデル再設計も不要（`pit_fundamental_snapshots.source` /
`extra` 列で吸収する設計、§1.8）。

`PitFundamentalRecord` に入るのは数値・enum の構造化フィールドのみ（プロンプトインジェクション
対策の原則を ML パイプラインにも一貫させる。CLAUDE.md「外部由来テキストは frontmatter のみ」）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from backend.services.vault.brand_notes_service import BrandNote, get_brand_note


@dataclass(frozen=True)
class PitFundamentalRecord:
    """1 銘柄分の PIT ファンダメンタル値（`pit_fundamental_snapshots` の列にそのまま対応）."""

    code: str
    source: str
    data_as_of: str | None
    per_forecast: float | None
    pbr: float | None
    roe: float | None
    equity_ratio: float | None
    dividend_yield_forecast: float | None
    eps_forecast: float | None
    bps: float | None
    market_cap_oku: float | None
    shares_outstanding: int | None
    last_earnings_date: str | None
    last_earnings_type: str | None
    sector33: str | None
    sector17: str | None
    scale_cat: str | None
    market: str | None


class PitFundamentalProvider(Protocol):
    """PIT ファンダメンタル値の取得元 1 つ分（Vault frontmatter / 四季報 等）."""

    source_id: str

    async def fetch(self, code: str) -> PitFundamentalRecord | None:
        """指定銘柄の当日分の値を返す（未整備・失敗時は `None`、フェイルソフト）."""
        ...


class VaultFrontmatterProvider:
    """`services/vault/brand_notes_service.get_brand_note` をそのまま写す第 1 実装."""

    source_id = "vault_frontmatter"

    async def fetch(self, code: str) -> PitFundamentalRecord | None:
        note = await get_brand_note(code)
        if note is None:
            return None
        return _from_brand_note(note, source=self.source_id)


def _from_brand_note(note: BrandNote, *, source: str) -> PitFundamentalRecord:
    return PitFundamentalRecord(
        code=note.code,
        source=source,
        data_as_of=note.data_as_of or note.close_date,
        per_forecast=note.per_forecast,
        pbr=note.pbr,
        roe=note.roe,
        equity_ratio=note.equity_ratio,
        dividend_yield_forecast=note.dividend_yield_forecast,
        eps_forecast=note.eps_forecast,
        bps=note.bps,
        market_cap_oku=note.market_cap_oku,
        shares_outstanding=note.shares_outstanding,
        last_earnings_date=note.last_earnings_date,
        last_earnings_type=note.last_earnings_type,
        sector33=note.sector33,
        sector17=note.sector17,
        scale_cat=note.scale_cat,
        market=note.market,
    )


# 優先順で試す既定プロバイダ列（🔧 四季報有効化後は `ShikihoProvider()` をこのタプルの先頭に
# 追加するだけでよい。`pit_snapshot_service.collect_fundamental_snapshots` は先頭から順に
# 試し、最初に `None` でない結果を採用する — `pit_fundamental_snapshots` は 1 営業日 1 銘柄
# 1 行のみ持つ設計のため、値のフィールド単位マージはしない）。
DEFAULT_PROVIDERS: tuple[PitFundamentalProvider, ...] = (VaultFrontmatterProvider(),)
