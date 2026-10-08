"""FastAPI application entry point."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import AppError, app_error_handler, unhandled_handler
from app.core.utils import new_id
from app.db.mongo import close, ensure_indexes

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await ensure_indexes()
    log.info("API ready, environment=%s", settings.environment)
    yield
    await close()


app = FastAPI(
    title="AI Analysis Team",
    version="1.0.0",
    description=(
        "Company hosted analysis team of Business, Technical and QA analysts. "
        "Every generated artifact requires human approval; approving a parent "
        "approves its current descendant versions through a recorded cascade."
    ),
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-Id"],
)


@app.middleware("http")
async def correlation(request: Request, call_next):
    """Structured logs carry a correlation id and never raw content (NFR-11)."""
    correlation_id = request.headers.get("x-correlation-id") or new_id()[:12]
    request.state.correlation_id = correlation_id
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Correlation-Id"] = correlation_id
    log.info("%s %s -> %s in %sms correlation=%s", request.method, request.url.path,
             response.status_code, duration_ms, correlation_id)
    return response


app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_handler)


@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready", tags=["system"])
async def ready() -> JSONResponse:
    from app.db.mongo import get_client

    try:
        await get_client().admin.command("ping")
        return JSONResponse({"status": "ready", "database": "ok"})
    except Exception as exc:
        return JSONResponse({"status": "degraded", "database": str(exc)},
                            status_code=503)


app.include_router(api_router, prefix=settings.api_prefix)
