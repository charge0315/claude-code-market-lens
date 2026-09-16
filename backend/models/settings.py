"""外部 API キー設定のスキーマ.

GET では生値を絶対に返さない（末尾4文字のみのマスク表示）。更新は `.env` への
永続化のみ行い、実行中プロセス（backend / celery worker・beat）への反映はしない
（`Settings` は起動時に一度だけ読み込む frozen 設定のため。反映には各プロセスの
再起動が必要 — `services/config_store.py` 参照）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ApiKeyField = str


class ApiKeyStatus(BaseModel):
    """1 つの外部 API キーの設定状況（生値は含まない）."""

    model_config = ConfigDict(frozen=True)

    key: ApiKeyField
    label: str
    configured: bool
    masked_value: str | None = None


class ApiKeysResponse(BaseModel):
    """設定画面向けの外部 API キー一覧応答."""

    model_config = ConfigDict(frozen=True)

    keys: list[ApiKeyStatus]
    restart_required: bool = False


class ApiKeysUpdateRequest(BaseModel):
    """`PUT /api/settings/api-keys` のリクエストボディ.

    各フィールドは `None` なら変更しない、空文字なら未設定に戻す。
    """

    model_config = ConfigDict(frozen=True)

    anthropic_api_key: str | None = Field(default=None)
    openai_api_key: str | None = Field(default=None)
    gemini_api_key: str | None = Field(default=None)
    jquants_api_key: str | None = Field(default=None)


LLMFeatureId = Literal["stock_pick", "portfolio_signal", "eod_review", "trend_analyzer"]
LLMProviderId = Literal["anthropic", "openai", "gemini"]


class LLMProviderOption(BaseModel):
    """選択肢として提示する1プロバイダ（APIキー設定状況・既定モデル・モデルプリセットつき）."""

    model_config = ConfigDict(frozen=True)

    value: LLMProviderId
    label: str
    configured: bool
    default_model: str
    model_presets: list[str]


class FeatureProviderSetting(BaseModel):
    """1機能ぶんの現在の公式/シャドウプロバイダ設定と、プロバイダごとの使用モデル."""

    model_config = ConfigDict(frozen=True)

    feature: LLMFeatureId
    label: str
    primary_provider: LLMProviderId
    shadow_providers: list[LLMProviderId]
    # プロバイダごとに実際に使われるモデル（機能×プロバイダの個別上書き、無ければプロバイダ既定値）。
    models: dict[LLMProviderId, str]


class LLMProviderSettingsResponse(BaseModel):
    """`GET/PATCH /api/settings/llm-providers` の応答."""

    model_config = ConfigDict(frozen=True)

    features: list[FeatureProviderSetting]
    available_providers: list[LLMProviderOption]
    restart_required: bool = False


class LLMProviderUpdateRequest(BaseModel):
    """`PATCH /api/settings/llm-providers` のリクエストボディ（1機能ぶんの更新）.

    各フィールドは `None` なら変更しない。`models` は変更したいプロバイダぶんのみ含めればよい
    （例: `{"anthropic": "claude-opus-5"}`）。値を空文字にすると上書きを解除しプロバイダの
    既定モデルへ戻す。
    """

    model_config = ConfigDict(frozen=True)

    feature: LLMFeatureId
    primary_provider: LLMProviderId | None = Field(default=None)
    shadow_providers: list[LLMProviderId] | None = Field(default=None)
    models: dict[LLMProviderId, str] | None = Field(default=None)
