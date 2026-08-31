from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.agent_service import AgentService
from backend.app.api import router
from backend.app.observability import create_langfuse_client
from backend.app.storage import ChatRepository
from backend.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    repository = ChatRepository(settings)
    repository.init_db()
    langfuse = create_langfuse_client(settings)

    app.state.settings = settings
    app.state.repository = repository
    app.state.langfuse = langfuse
    app.state.agent_service = AgentService(settings, repository, langfuse)

    try:
        yield
    finally:
        if langfuse is not None:
            # Langfuse batches export events. On a long-running FastAPI process
            # this is only needed during graceful shutdown.
            langfuse.shutdown()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="EXANTE scenario trainer with SQLite and sqlite-vec memory.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix=settings.api_prefix)
