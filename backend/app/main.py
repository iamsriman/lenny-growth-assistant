from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.routes import artifacts, chat, health, knowledge, sessions
from app.api.routes import config as config_routes
from app.config import settings
from app.db.session import db_scope, dispose_db, init_db
from app.llm.base import LLMError
from app.logging_config import configure_logging, new_request_id, request_id_var, session_id_var
from app.rag.ingest import ingest_path
from app.rag.retriever import get_index, refresh_index

log = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level, settings.log_format)
    log.info("starting", extra={"component": "api", "version": __version__,
                                "provider": settings.llm_provider,
                                "environment": settings.environment})
    # Boot must not hard-fail on a cold database — the health endpoint should
    # be able to tell the operator what is wrong.
    try:
        await init_db()
        async with db_scope() as db:
            size = await refresh_index(db)
            if size == 0:
                log.info("index empty, running first-boot ingestion",
                         extra={"component": "ingest"})
                report = await ingest_path(db, settings.transcripts_dir)
                log.info("first-boot ingestion done",
                         extra={"component": "ingest", **report.as_dict()})
    except Exception as exc:  # noqa: BLE001
        log.error("startup degraded: database or ingestion unavailable",
                  extra={"component": "api", "error": str(exc)})
    yield
    await dispose_db()
    log.info("stopped", extra={"component": "api"})


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Grounded product & growth assistant over Lenny's Podcast transcripts. "
            "Answers cite transcripts, essays follow an encoded Ship 30 for 30 skill, "
            "and artifacts render in a sandboxed viewer."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or new_request_id()
        request_id_var.set(rid)
        session_id_var.set("-")
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled request error",
                          extra={"component": "api", "path": request.url.path})
            raise
        took = (time.perf_counter() - started) * 1000
        response.headers["x-request-id"] = rid
        if request.url.path not in ("/health",):
            log.info("request", extra={"component": "api", "method": request.method,
                                       "path": request.url.path,
                                       "status": response.status_code,
                                       "took_ms": round(took, 1)})
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            body = {"code": detail.get("code", "http_error"),
                    "message": detail.get("message", "Request failed."),
                    "remediation": detail.get("remediation")}
        else:
            body = {"code": "http_error", "message": str(detail), "remediation": None}
        body["request_id"] = request_id_var.get()
        return JSONResponse(status_code=exc.status_code, content={"error": body})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": {
            "code": "validation_error",
            "message": "The request body failed validation.",
            "remediation": "Check the field list in `detail`.",
            "request_id": request_id_var.get(),
            "detail": {"fields": [{"loc": list(e["loc"]), "msg": e["msg"]}
                                  for e in exc.errors()]},
        }})

    @app.exception_handler(LLMError)
    async def llm_error(request: Request, exc: LLMError):
        return JSONResponse(status_code=503, content={"error": {
            "code": f"provider_{exc.kind}",
            "message": str(exc),
            "remediation": "Switch provider in the model menu or check the backend logs.",
            "request_id": request_id_var.get(),
            "detail": {"provider": exc.provider},
        }})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        return JSONResponse(status_code=500, content={"error": {
            "code": "internal_error",
            "message": "The server hit an unexpected error.",
            "remediation": "Search the logs for this request_id.",
            "request_id": request_id_var.get(),
        }})

    for module in (health, sessions, chat, artifacts, knowledge, config_routes):
        app.include_router(module.router)

    @app.get("/", tags=["health"])
    async def root() -> dict:
        return {"name": settings.app_name, "version": __version__,
                "docs": "/docs", "health": "/health/ready",
                "knowledge_chunks": get_index().size}

    return app


app = create_app()
