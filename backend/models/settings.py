"""外部 API キー設定のスキーマ.

GET では生値を絶対に返さない（末尾4文字のみのマスク表示）。更新は `.env` への
永続化のみ行い、実行中プロセス（backend / celery worker・beat）への反映はしない
（`Settings` は起動時に一度だけ読み込む frozen 設定のため。反映には各プロセスの
再起動が必要 — `services/config_store.py` 参照）。
"""

from __future__ import annotations

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
    gemini_api_key: str | None = Field(default=None)
    jquants_api_key: str | None = Field(default=None)
