"""FastAPI application entrypoint with lifespan background task and exception handlers."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from veltrix.api.container import get_container
from veltrix.api.errors import (
    AuthenticationError,
    ForbiddenError,
    ServiceUnavailableError,
    ValidationError,
    authentication_error_handler,
    forbidden_error_handler,
    service_unavailable_handler,
    validation_error_handler,
)
from veltrix.api.routes import router
from veltrix.core.logging import get_logger, setup_logging
from veltrix.data.db import init_app_db

logger = get_logger("main")


async def run_ingestion_background_task(app: FastAPI) -> None:
    """Background task running document ingestion on startup.

    Sets app.state.ready = True once ingestion completes.
    """
    from veltrix.ingestion.pipeline import IngestionPipeline

    container = get_container()
    logger.info("Starting background ingestion task...")

    try:
        init_app_db(container.settings.APP_DB_PATH)
        pipeline = IngestionPipeline(container.settings)
        result = await pipeline.run()

        if result.chunks_created > 0 or result.skipped:
            app.state.ready = True
            logger.info(
                "Background ingestion completed successfully. Service is ready.",
                chunks_indexed=result.chunks_created,
                skipped=result.skipped,
            )
        else:
            logger.error("Ingestion produced 0 chunks. Service remains unready.")
            app.state.ready = False
    except Exception as e:
        logger.error("Background ingestion failed", error=str(e))
        app.state.ready = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager.

    Initializes databases and kicks off asynchronous ingestion without blocking startup.
    """
    container = get_container()
    setup_logging(container.settings.LOG_LEVEL)
    logger.info("Initializing Veltrix PeopleOps Assistant service...")

    # Initialize app database
    init_app_db(container.settings.APP_DB_PATH)

    # Server listens immediately; ingestion runs in background task
    app.state.ready = False
    task = asyncio.create_task(run_ingestion_background_task(app))

    yield

    # Clean shutdown
    if not task.done():
        task.cancel()
    logger.info("Service shutdown completed.")


def create_app() -> FastAPI:
    """Factory creating and configuring the FastAPI instance."""
    app = FastAPI(
        title="Veltrix PeopleOps Assistant",
        description="Production-grade HR Q&A and Leave Management Service",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Register custom exception handlers
    app.add_exception_handler(AuthenticationError, authentication_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ForbiddenError, forbidden_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ServiceUnavailableError, service_unavailable_handler)  # type: ignore[arg-type]

    @app.exception_handler(RequestValidationError)
    async def pydantic_validation_handler(_request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": exc.errors()})

    app.include_router(router)
    return app


app = create_app()
