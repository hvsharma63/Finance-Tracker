import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    accounts,
    auth,
    budgets,
    categories,
    imports,
    investments,
    reconciliation,
    reports,
    system,
    transactions,
)
from app.core.config import get_settings
from app.core.db import session_factory
from app.core.errors import AppError, app_error_handler
from app.core.security import SecurityMiddleware
from app.services.ledger.seed import seed_defaults

log = logging.getLogger("finance")


@asynccontextmanager
async def lifespan(_: FastAPI):
    with session_factory()() as db:
        seed_defaults(db)
        if get_settings().document_retention_days > 0:
            from app.services.imports.retention import purge_old_documents

            purge_old_documents(db)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Finance Tracker API", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.add_middleware(SecurityMiddleware)
    if settings.cors_origin_list:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                           allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
                           allow_headers=["Content-Type", "X-Requested-With"])
    app.add_exception_handler(AppError, app_error_handler)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errs = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error",
                                                                "message": "Invalid request", "details": errs}})

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        # Never echo internals or financial data back to the client.
        log.exception("Unhandled error: %s", exc.__class__.__name__)
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error",
                                                                "message": "Internal error", "details": None}})

    for r in (system.health_router, auth.router, accounts.router, transactions.router, categories.router,
              imports.router, imports.profiles_router, reconciliation.router, reports.router, investments.router,
              budgets.router, system.router):
        app.include_router(r, prefix="/api")
    return app


app = create_app()
