"""機能別プロバイダ設定（`backend.config.settings`）から実際のクライアントを解決する.

`resolve_feature_provider()` が「公式（決定を左右する）プロバイダ」を、
`resolve_shadow_providers()` が「シャドウ（比較表示専用のチャレンジャー）プロバイダ群」を返す。
どちらも `is_configured=False`（APIキー未設定）のプロバイダは除外し、呼び出し元が
既存のフェイルソフト方針（未設定機能は静かにスキップ）をそのまま踏襲できるようにする。
"""

from __future__ import annotations

from backend.config import settings
from backend.services.llm.provider import LLMProvider
from backend.services.llm.types import FeatureId, ProviderId


def get_provider(provider_id: ProviderId) -> LLMProvider:
    """プロバイダ ID からシングルトンクライアントを返す."""
    # 循環 import 回避のため関数内 import（各クライアントモジュールは `backend.config` に依存する）。
    from backend.services.anthropic_client import anthropic_client
    from backend.services.gemini_client import gemini_client
    from backend.services.openai_client import openai_client

    providers: dict[ProviderId, LLMProvider] = {
        "anthropic": anthropic_client,
        "openai": openai_client,
        "gemini": gemini_client,
    }
    return providers[provider_id]


_PRIMARY_SETTINGS_FIELD: dict[FeatureId, str] = {
    "stock_pick": "llm_provider_stock_pick",
    "portfolio_signal": "llm_provider_portfolio_signal",
    "eod_review": "llm_provider_eod_review",
    "trend_analyzer": "llm_provider_trend_analyzer",
    "note_publish": "llm_provider_note_publish",
    "news_sentiment": "llm_provider_news_sentiment",
}

_SHADOW_SETTINGS_FIELD: dict[FeatureId, str] = {
    "stock_pick": "llm_shadow_providers_stock_pick",
    "portfolio_signal": "llm_shadow_providers_portfolio_signal",
    "eod_review": "llm_shadow_providers_eod_review",
    "trend_analyzer": "llm_shadow_providers_trend_analyzer",
}


def resolve_feature_provider(feature: FeatureId) -> LLMProvider:
    """指定機能の「公式（決定を左右する）プロバイダ」を返す（未設定チェックは呼び出し元）."""
    provider_id = getattr(settings, _PRIMARY_SETTINGS_FIELD[feature])
    return get_provider(provider_id)


def resolve_shadow_providers(feature: FeatureId) -> list[LLMProvider]:
    """指定機能の「シャドウ（比較用チャレンジャー）プロバイダ群」を返す.

    主プロバイダと重複するもの、および `is_configured=False`（APIキー未設定）のものは
    自動で除外する（設定ミス・キー未設定時に本体機能へ影響させないため）。
    """
    primary_id = getattr(settings, _PRIMARY_SETTINGS_FIELD[feature])
    shadow_ids: list[str] = getattr(settings, _SHADOW_SETTINGS_FIELD[feature])
    resolved: list[LLMProvider] = []
    for provider_id in shadow_ids:
        if provider_id == primary_id:
            continue
        if provider_id not in ("anthropic", "openai", "gemini"):
            continue
        provider = get_provider(provider_id)  # type: ignore[arg-type]
        if provider.is_configured:
            resolved.append(provider)
    return resolved


# 機能×プロバイダごとのモデル上書きフィールド名（`backend/config.py` 参照）。
_MODEL_OVERRIDE_FIELD: dict[tuple[FeatureId, ProviderId], str] = {
    ("stock_pick", "anthropic"): "llm_model_stock_pick_anthropic",
    ("stock_pick", "openai"): "llm_model_stock_pick_openai",
    ("stock_pick", "gemini"): "llm_model_stock_pick_gemini",
    ("portfolio_signal", "anthropic"): "llm_model_portfolio_signal_anthropic",
    ("portfolio_signal", "openai"): "llm_model_portfolio_signal_openai",
    ("portfolio_signal", "gemini"): "llm_model_portfolio_signal_gemini",
    ("eod_review", "anthropic"): "llm_model_eod_review_anthropic",
    ("eod_review", "openai"): "llm_model_eod_review_openai",
    ("eod_review", "gemini"): "llm_model_eod_review_gemini",
    ("trend_analyzer", "anthropic"): "llm_model_trend_analyzer_anthropic",
    ("trend_analyzer", "openai"): "llm_model_trend_analyzer_openai",
    ("trend_analyzer", "gemini"): "llm_model_trend_analyzer_gemini",
    ("note_publish", "anthropic"): "llm_model_note_publish_anthropic",
    ("note_publish", "openai"): "llm_model_note_publish_openai",
    ("note_publish", "gemini"): "llm_model_note_publish_gemini",
    ("news_sentiment", "anthropic"): "llm_model_news_sentiment_anthropic",
    ("news_sentiment", "openai"): "llm_model_news_sentiment_openai",
    ("news_sentiment", "gemini"): "llm_model_news_sentiment_gemini",
}

# プロバイダの既定モデル（機能×プロバイダの上書きが空文字のときのフォールバック先）。
_PROVIDER_DEFAULT_MODEL_FIELD: dict[ProviderId, str] = {
    "anthropic": "anthropic_model",
    "openai": "openai_model",
    "gemini": "gemini_model",
}


def resolve_model(feature: FeatureId, provider_id: ProviderId) -> str:
    """指定機能×プロバイダで実際に使うモデルIDを返す（個別上書き優先、無ければプロバイダ既定値）."""
    override = getattr(settings, _MODEL_OVERRIDE_FIELD[(feature, provider_id)])
    if override:
        return str(override)
    return str(getattr(settings, _PROVIDER_DEFAULT_MODEL_FIELD[provider_id]))
