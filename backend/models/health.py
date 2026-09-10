"""ヘルスチェックのスキーマ."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LivenessResponse(BaseModel):
    """API プロセス自体の生存確認（依存先は見ない軽量応答）."""

    model_config = ConfigDict(frozen=True)

    status: str
    version: str


class HealthCheckResponse(BaseModel):
    """DB / Redis 疎通を含む依存先ヘルスチェック応答.

    いずれかが `error` なら呼び出し側ルーターが 503 を返す。未認証エンドポイントの
    ため、レスポンスには正常/異常のみを含め生の例外文言は載せない（Market Lens 踏襲）。
    """

    model_config = ConfigDict(frozen=True)

    status: str
    checks: dict[str, str]
