"""FastAPI dependencies for identity, request context, and service readiness."""

from fastapi import Header, Request

from veltrix.api.container import Container, get_container
from veltrix.api.errors import AuthenticationError, ServiceUnavailableError
from veltrix.data.repositories import EmployeeRepository
from veltrix.domain.models import RequestContext


def get_app_container() -> Container:
    """Dependency to retrieve the application container."""
    return get_container()


def verify_ready(request: Request) -> None:
    """Dependency ensuring the ingestion background task has completed."""
    if not getattr(request.app.state, "ready", False):
        raise ServiceUnavailableError("Ingestion in progress. Service is initializing.")


def get_request_context(
    request: Request,
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
) -> RequestContext:
    """Extract and verify employee identity from X-Employee-Id header against database.

    Enforces:
    - 401 if header is missing or empty.
    - 401 if employee_id does not exist in veltrix.db employees table.
    - Identity, role, and region originate strictly from the database.
    """
    if not x_employee_id or not x_employee_id.strip():
        raise AuthenticationError("Missing X-Employee-Id header.")

    container = get_app_container()
    repo = EmployeeRepository(str(container.settings.DB_PATH))
    emp = repo.get_by_id(x_employee_id.strip())

    if not emp:
        raise AuthenticationError(f"Employee '{x_employee_id}' not found.")

    return RequestContext(
        employee_id=emp.employee_id,
        role=emp.role,
        region=emp.region,
    )
