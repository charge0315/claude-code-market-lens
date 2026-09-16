"""外部 API キー設定 / LLM プロバイダ選択 API.

キーの生値は GET で絶対に返さない（末尾4文字のマスク表示のみ）。更新は `.env` への
永続化のみ行い、実行中の backend / celery worker・beat への反映は再起動が必要
（`Settings` は起動時に一度だけ読み込む frozen 設定のため、`services/config_store.py`
参照）。`/llm-providers` は機能（stock_pick/portfolio_signal/eod_review/trend_analyzer）
ごとに公式（決定を左右する）プロバイダとシャドウ（比較用チャレンジャー、複数併用可）
プロバイダを選択する設定で、同じく `.env` 永続化・再起動反映方式に揃える。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.models.common import ApiResponse
from backend.models.settings import (
    ApiKeysResponse,
    ApiKeyStatus,
    ApiKeysUpdateRequest,
    FeatureProviderSetting,
    LLMProviderOption,
    LLMProviderSettingsResponse,
    LLMProviderUpdateRequest,
)
from backend.services import config_store

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _status_response(*, restart_required: bool) -> ApiResponse[ApiKeysResponse]:
    rows = [ApiKeyStatus(**row) for row in config_store.get_api_key_status()]
    return ApiResponse.ok(ApiKeysResponse(keys=rows, restart_required=restart_required))


@router.get("/api-keys", response_model=ApiResponse[ApiKeysResponse], summary="外部APIキーの設定状況")
async def get_api_keys() -> ApiResponse[ApiKeysResponse]:
    """マスク済みの現在の設定状況を返す（生値は含まない）."""
    return _status_response(restart_required=False)


@router.patch(
    "/api-keys",
    response_model=ApiResponse[ApiKeysResponse],
    summary="外部APIキーを更新（.envへ永続化。反映にはbackend/celeryの再起動が必要）",
)
async def update_api_keys(req: ApiKeysUpdateRequest) -> ApiResponse[ApiKeysResponse]:
    """指定されたフィールドだけ `.env` を更新する（None のフィールドは変更しない）."""
    updates: dict[str, str] = {}
    for field, value in req.model_dump().items():
        if value is None:
            continue
        env_name = config_store.env_name_for_field(field)
        if env_name is not None:
            updates[env_name] = value.strip()

    if not updates:
        raise HTTPException(status_code=400, detail="更新するキーが指定されていません")

    try:
        config_store.update_env_keys(updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _status_response(restart_required=True)


def _llm_provider_response(*, restart_required: bool) -> ApiResponse[LLMProviderSettingsResponse]:
    features = [FeatureProviderSetting(**row) for row in config_store.get_llm_provider_settings()]
    providers = [LLMProviderOption(**row) for row in config_store.get_llm_provider_options()]
    return ApiResponse.ok(
        LLMProviderSettingsResponse(features=features, available_providers=providers, restart_required=restart_required)
    )


@router.get(
    "/llm-providers",
    response_model=ApiResponse[LLMProviderSettingsResponse],
    summary="機能ごとのLLMプロバイダ設定（公式/シャドウ）の現在値",
)
async def get_llm_providers() -> ApiResponse[LLMProviderSettingsResponse]:
    """機能ごとの現在の公式/シャドウプロバイダ設定と、選択可能なプロバイダ一覧を返す."""
    return _llm_provider_response(restart_required=False)


@router.patch(
    "/llm-providers",
    response_model=ApiResponse[LLMProviderSettingsResponse],
    summary="1機能ぶんのLLMプロバイダ設定を更新（.envへ永続化。反映にはbackend/celeryの再起動が必要）",
)
async def update_llm_providers(req: LLMProviderUpdateRequest) -> ApiResponse[LLMProviderSettingsResponse]:
    """指定機能の公式/シャドウプロバイダを更新する（`None` のフィールドは変更しない）."""
    if req.primary_provider is None and req.shadow_providers is None:
        raise HTTPException(status_code=400, detail="更新する項目が指定されていません")

    updates = config_store.env_updates_for_llm_provider(
        req.feature, primary_provider=req.primary_provider, shadow_providers=req.shadow_providers
    )
    try:
        config_store.update_env_keys(updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _llm_provider_response(restart_required=True)
