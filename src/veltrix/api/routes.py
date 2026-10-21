"""FastAPI routes for /health and /chat endpoints."""

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from veltrix.api.container import Container, get_container
from veltrix.api.deps import get_request_context
from veltrix.api.errors import ForbiddenError
from veltrix.api.schemas import ChatRequest, ChatResponse, HealthResponse
from veltrix.core.ids import generate_request_id
from veltrix.data.sessions import SessionManager, SessionOwnershipConflict
from veltrix.domain.models import RequestContext

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> JSONResponse:
    """Health check endpoint.

    Returns HTTP 200 {"status": "ok"} only when ingestion has finished.
    Until then, returns HTTP 503.
    """
    is_ready = getattr(request.app.state, "ready", False)
    if is_ready:
        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ok"})
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "not_ready"})


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    ctx: RequestContext = Depends(get_request_context),
    container: Container = Depends(get_container),
) -> ChatResponse:
    """Chat endpoint for answering policy queries and executing leave tools.

    Validates:
    - 400: Handled by FastAPI Pydantic validation if payload is missing or invalid.
    - 401: Handled by get_request_context if X-Employee-Id is missing or unknown.
    - 403: Handled by SessionManager if session_id is owned by another employee.
    """
    session_mgr = SessionManager(str(container.settings.APP_DB_PATH))

    try:
        session_mgr.bind_and_verify_session(payload.session_id, ctx.employee_id)
    except SessionOwnershipConflict as e:
        raise ForbiddenError(str(e)) from e

    # For M1 skeleton: return a valid refuse response for off-topic/placeholder
    # Full orchestrator will be attached in M4/M5
    return ChatResponse(
        request_id=generate_request_id(),
        answer="I am the Veltrix PeopleOps Assistant. How can I help you today?",
        route="refuse",
        citations=[],
        tool_calls=[],
        pending_confirmation=False,
    )
