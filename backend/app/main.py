from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import advisor, auth, health, markets, signals, wallet
from backend.app.api import bot
from backend.app.config import get_settings
from backend.app.logging_config import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Polymarket Bot",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api")
    app.include_router(wallet.router, prefix="/api")
    app.include_router(advisor.router, prefix="/api")
    app.include_router(markets.router, prefix="/api")
    app.include_router(signals.router, prefix="/api")
    app.include_router(bot.router, prefix="/api")
    return app


app = create_app()
