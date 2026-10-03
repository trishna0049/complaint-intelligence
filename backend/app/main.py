from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.classifier import get_classifier
from app.ai.sentiment import load_sentiment
from app.api.routes import router
from app.config import get_settings
from app.db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    # Warm the models so the first complaint isn't slow.
    get_classifier()
    load_sentiment()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Complaint Intelligence API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)
    return app


app = create_app()
