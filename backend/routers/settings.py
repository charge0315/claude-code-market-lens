"""外部 API キー設定 API.

キーの生値は GET で絶対に返さない（末尾4文字のマスク表示のみ）。更新は `.env` への
永続化のみ行い、実行中の backend / celery worker・beat への反映は再起動が必要
（`Settings` は起動時に一度だけ読み込む frozen 設定のため、`services/config_store.py`
参照）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.models.common import ApiResponse
from backend.models.settings import ApiKeysResponse, ApiKeyStatus, ApiKeysUpdateRequest
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
