"""TrendAnalyzerAgent — 収集シグナルを構造化トレンドへ変換する.

Market Lens `backend/services/trend/analyzer.py` から移植（import パスのみ変更:
`services.data_fetcher` → `services.data.data_fetcher`）。

LLM 呼び出しは `anthropic_client.propose_trends`（forced tool-use、api_cost 記録つき）。
`related_tickers` の証券コードは ticker master で検証し、無効なものは落とす。
Anthropic キー未設定時は LLM を呼ばず `_MOCK_TREND_SEEDS`（事前構造化済み）を返す。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import cast

from backend.models.trend_tracking import ImpactHorizon, LifecycleStage, RelatedTicker, Trend
from backend.services.anthropic_client import anthropic_client
from backend.services.data import data_fetcher
from backend.services.jst_time import JST

logger = logging.getLogger(__name__)

_MIN_SCORE = 0.0
_MAX_MOMENTUM = 100.0
_MAX_TRENDS = 12

_SYSTEM_HINT = (
    "あなたは日本株の投資リサーチャーです。以下のニュース見出しとセクター騰落から、"
    "投資判断に有用な「トレンド」を 5〜10 件抽出してください。無関係な一般ニュース・広告・"
    "重複は除外し、各トレンドに関連する日本株の証券コードを related_tickers に入れてください"
    "（証券コードは 4 桁数字またはそれに準ずるもの。確信が持てない銘柄は入れない）。"
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


async def _valid_codes_async() -> dict[str, str]:
    try:
        master = await data_fetcher._get_ticker_master()
    except Exception:  # noqa: BLE001 — master 取得失敗時は検証をスキップ（全採用）
        logger.warning("トレンド分析: ticker master 取得に失敗（related_tickers 検証をスキップ）", exc_info=True)
        return {}
    return {t.code: t.name for t in master}


def _build_prompt(headlines: list[str], sector_notes: list[str]) -> str:
    parts = [_SYSTEM_HINT, "", "## ニュース見出し"]
    parts += [f"- {h}" for h in headlines] or ["- （なし）"]
    parts += ["", "## セクター騰落"]
    parts += [f"- {n}" for n in sector_notes] or ["- （なし）"]
    return "\n".join(parts)


def _coerce_related(raw: object, valid: dict[str, str]) -> list[RelatedTicker]:
    if not isinstance(raw, list):
        return []
    out: list[RelatedTicker] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = str(item.get("ticker", "")).strip().upper().removesuffix(".T")
        rationale = str(item.get("correlation_rationale", "")).strip()
        if not code or not rationale:
            continue
        if valid and code not in valid:
            continue  # master にある有効コードのみ採用
        name = valid.get(code) or str(item.get("name", "")).strip() or code
        out.append(RelatedTicker(ticker=code, name=name, correlation_rationale=rationale))
    return out


def _coerce_trends(raw: object, valid: dict[str, str], now_iso: str, date_key: str) -> list[Trend]:
    if not isinstance(raw, list):
        return []
    trends: list[Trend] = []
    for i, item in enumerate(raw[:_MAX_TRENDS], start=1):
        if not isinstance(item, dict):
            continue
        stage = str(item.get("lifecycle_stage", "")).strip().upper()
        horizon = str(item.get("impact_horizon", "")).strip().upper()
        if stage not in {"EMERGING", "EXPANDING", "PEAK", "DECLINING"}:
            stage = "EMERGING"
        if horizon not in {"SHORT", "MID", "LONG"}:
            horizon = "MID"
        theme = str(item.get("theme_name", "")).strip()
        summary = str(item.get("summary", "")).strip()
        if not theme or not summary:
            continue
        try:
            sentiment = _clamp(float(cast("float", item.get("sentiment_score", 0.0))), -1.0, 1.0)
            momentum = _clamp(float(cast("float", item.get("momentum_score", 50.0))), _MIN_SCORE, _MAX_MOMENTUM)
        except (TypeError, ValueError):
            continue
        raw_keywords = item.get("keywords")
        keywords = (
            [str(k).strip() for k in raw_keywords if str(k).strip()][:8] if isinstance(raw_keywords, list) else []
        )
        trends.append(
            Trend(
                trend_id=f"trend-{date_key}-{i:02d}",
                timestamp=now_iso,
                theme_name=theme,
                summary=summary,
                lifecycle_stage=cast("LifecycleStage", stage),
                sentiment_score=sentiment,
                momentum_score=momentum,
                impact_horizon=cast("ImpactHorizon", horizon),
                related_tickers=_coerce_related(item.get("related_tickers"), valid),
                keywords=keywords,
            )
        )
    return trends


async def analyze(headlines: list[str], sector_notes: list[str]) -> list[Trend]:
    """収集シグナルを LLM で構造化トレンドへ変換する（キー未設定時はモック）."""
    now = datetime.now(JST)
    now_iso = now.isoformat(timespec="seconds")
    date_key = now.strftime("%Y%m%d")

    if not anthropic_client.is_configured:
        return mock_trends(now_iso, date_key)

    prompt = _build_prompt(headlines, sector_notes)
    raw = await anthropic_client.propose_trends(prompt=prompt)
    valid = await _valid_codes_async()
    return _coerce_trends(raw.get("trends"), valid, now_iso, date_key)


# 事前構造化済みのモックトレンド（Anthropic キー未設定時）。`collector._MOCK_SIGNALS` と対。
_MOCK_TREND_SEEDS: tuple[dict[str, object], ...] = (
    {
        "theme_name": "次世代半導体パッケージング",
        "summary": "CoWoS 供給逼迫と次世代チップレット技術の進展に伴い、関連装置・部材メーカーへの受注拡大期待。",
        "lifecycle_stage": "EXPANDING",
        "sentiment_score": 0.72,
        "momentum_score": 84.0,
        "impact_horizon": "MID",
        "keywords": ["チップレット", "先端パッケージング", "後工程", "CoWoS"],
        "related": [
            ("6920", "レーザーテック", "マスクブランクス検査装置の需要に直結"),
            ("6857", "アドバンテスト", "先端パッケージ品の検査工程で需要増"),
            ("6146", "ディスコ", "ダイシング・グラインディング装置の後工程比率上昇"),
        ],
    },
    {
        "theme_name": "AI データセンター電力・液冷",
        "summary": "生成 AI 向けデータセンターの電力密度上昇で、受変電設備と液冷ソリューションの需要が急伸。",
        "lifecycle_stage": "EMERGING",
        "sentiment_score": 0.6,
        "momentum_score": 78.0,
        "impact_horizon": "LONG",
        "keywords": ["データセンター", "液冷", "受変電", "電力インフラ"],
        "related": [
            ("6501", "日立製作所", "送配電・受変電設備で恩恵"),
            ("6503", "三菱電機", "パワー半導体・受変電で需要増"),
        ],
    },
    {
        "theme_name": "防衛関連の中期成長",
        "summary": "防衛費増額の継続方針を背景に、装備品・関連部材メーカーの受注残が積み上がる見通し。",
        "lifecycle_stage": "EXPANDING",
        "sentiment_score": 0.45,
        "momentum_score": 62.0,
        "impact_horizon": "LONG",
        "keywords": ["防衛費増額", "装備品", "受注残"],
        "related": [
            ("7011", "三菱重工業", "防衛セグメントの受注拡大"),
            ("7012", "川崎重工業", "航空・防衛の受注増"),
        ],
    },
    {
        "theme_name": "インバウンド消費の高水準",
        "summary": (
            "訪日客数が過去最高圏で推移し、百貨店・鉄道・ホテル・化粧品に追い風。"
            "円安一服でも高付加価値消費は底堅い。"
        ),
        "lifecycle_stage": "PEAK",
        "sentiment_score": 0.35,
        "momentum_score": 55.0,
        "impact_horizon": "SHORT",
        "keywords": ["インバウンド", "訪日客", "百貨店", "免税"],
        "related": [
            ("3099", "三越伊勢丹HD", "都心店の免税売上が牽引"),
            ("9202", "ANAHD", "国際線旅客需要の回復"),
        ],
    },
)


def mock_trends(now_iso: str, date_key: str) -> list[Trend]:
    """Anthropic キー未設定時の事前構造化済みモックトレンド一覧を返す."""
    out: list[Trend] = []
    for i, seed in enumerate(_MOCK_TREND_SEEDS, start=1):
        related = [
            RelatedTicker(ticker=c, name=n, correlation_rationale=r)
            for c, n, r in cast("list[tuple[str, str, str]]", seed["related"])
        ]
        out.append(
            Trend(
                trend_id=f"trend-{date_key}-{i:02d}",
                timestamp=now_iso,
                theme_name=cast("str", seed["theme_name"]),
                summary=cast("str", seed["summary"]),
                lifecycle_stage=cast("LifecycleStage", seed["lifecycle_stage"]),
                sentiment_score=cast("float", seed["sentiment_score"]),
                momentum_score=cast("float", seed["momentum_score"]),
                impact_horizon=cast("ImpactHorizon", seed["impact_horizon"]),
                related_tickers=related,
                keywords=cast("list[str]", seed["keywords"]),
            )
        )
    return out
