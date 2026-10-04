from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ai.classifier import get_classifier
from app.ai.llm import LLMError
from app.ai.sentiment import load_sentiment
from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.redis import close_redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Warm the models so the first complaint isn't slow. The schema is managed by Alembic (not created here).
    get_classifier()
    load_sentiment()
    yield
    await dispose_engine()
    await close_redis()


def create_app() -> FastAPI:
    get_settings().check_production()
    app = FastAPI(title="Complaint Intelligence API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization"],
        allow_credentials=True,  # the refresh-token cookie
    )
    app.include_router(api_router)

    @app.exception_handler(LLMError)
    async def _llm_error(_: Request, exc: LLMError) -> JSONResponse:
        logging.getLogger("app.llm").warning("LLM call failed: %s (%s)", exc.code, exc.message)
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        return JSONResponse(
            {"detail": {"code": exc.code, "message": exc.message}}, status_code=exc.status, headers=headers
        )

    return app


app = create_app()
