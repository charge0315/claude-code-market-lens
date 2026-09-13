"""Alpha Forge API.

AI 銘柄ピック & 継続学習トレーディング支援端末のバックエンド（ポート 8002）。
再利用元 Market Lens の `backend/main.py` を踏襲しつつ、Alpha Forge のルーターを載せる。
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 引数なし load_dotenv() は uvicorn --reload の子プロセス経由だと検索起点を外すことがある。
# 実行方法に関わらず常にリポジトリルート直下の .env を読むため明示パスを渡す（Market Lens 踏襲）。
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from backend.config import settings  # noqa: E402
from backend.models.health import LivenessResponse  # noqa: E402
from backend.routers.eval import router as eval_router  # noqa: E402
from backend.routers.health import router as health_router  # noqa: E402
from backend.routers.inference import router as inference_router  # noqa: E402
from backend.routers.ledger import router as ledger_router  # noqa: E402
from backend.routers.market import router as market_router  # noqa: E402
from backend.routers.notify import router as notify_router  # noqa: E402
from backend.routers.notify import ws_router as notify_ws_router  # noqa: E402
from backend.routers.picks import router as picks_router  # noqa: E402
from backend.routers.portfolio import router as portfolio_router  # noqa: E402
from backend.routers.registry import router as registry_router  # noqa: E402
from backend.routers.settings import router as settings_router  # noqa: E402
from backend.routers.stock import router as stock_router  # noqa: E402
from backend.routers.trend import router as trend_router  # noqa: E402
from backend.services.db.database import dispose_db, init_db  # noqa: E402
from backend.services.security_headers import register_security_headers  # noqa: E402
from backend.services.task_registry import close_redis_client  # noqa: E402

logger = logging.getLogger(__name__)

_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """起動時に DB スキーマ前提を整え、終了時に接続を解放する."""
    await init_db()
    logger.info("Alpha Forge API started (port=%d)", settings.backend_port)
    yield
    await dispose_db()
    await close_redis_client()
    logger.info("Alpha Forge API shutdown")


app = FastAPI(
    title="Alpha Forge API",
    version=_VERSION,
    description=(
        "日本株の AI 銘柄ピック（中長期 / 短期）と継続学習ループを提供する分析支援 API。"
        "出力は分析結果・参考情報であり、投資助言ではない。ブローカー発注は一切行わない。"
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_security_headers(app)

# `/health` は監視 / 起動スクリプトが直接叩く。ブラウザからは Next.js の /api プロキシ
# 経由でしか到達できないため、同じ router を /api/system 配下にも重ねてマウントする。
app.include_router(health_router)
app.include_router(health_router, prefix="/api/system")
app.include_router(picks_router)
app.include_router(trend_router)
app.include_router(ledger_router)
app.include_router(eval_router)
app.include_router(registry_router)
app.include_router(inference_router)
app.include_router(portfolio_router)
app.include_router(notify_router)
app.include_router(notify_ws_router)
app.include_router(stock_router)
app.include_router(market_router)
app.include_router(settings_router)


@app.get("/api/health", response_model=LivenessResponse, tags=["health"], summary="Liveness check")
async def liveness() -> LivenessResponse:
    """API プロセス自体の生存確認（依存先は見ない）."""
    return LivenessResponse(status="ok", version=_VERSION)
