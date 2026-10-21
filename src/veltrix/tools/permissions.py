"""Leave permission check functions strictly enforcing Section 3.1 & 6.1 rules."""

from veltrix.core.logging import get_logger
from veltrix.domain.models import RequestContext

logger = get_logger("permissions")

# Fixed refusal message required by Section 6.1 & 7.3:
# "When the requester is not allowed to see another employee's data, give the same fixed refusal message whether that employee exists or not."
FORBIDDEN_EMPLOYEE_MESSAGE = "I can't share information about that employee."


def can_view_employee_leave(
    requester: RequestContext,
    target_employee_id: str,
    direct_report_ids: set[str] | None = None,
) -> bool:
    """Check if requester is allowed to view target employee's leave data.

    Permissions from Section 3.1 & 6.1:
    - employee: reads self only
    - manager: reads self and direct reports (target.manager_id == requester.employee_id)
    - hr: reads any ONE employee
    """
    target = target_employee_id.strip()
    req_id = requester.employee_id.strip()

    # Self is always allowed for all roles
    if target == req_id:
        return True

    # Employee role can only read self
    if requester.role == "employee":
        return False

    # Manager can read self plus direct reports
    if requester.role == "manager":
        reports = direct_report_ids or set()
        return target in reports

    # HR can read any one employee
    return requester.role == "hr"


def can_manage_team_leave(requester: RequestContext) -> bool:
    """Check if requester is allowed to call get_team_leave (Managers only)."""
    return requester.role == "manager"


def can_modify_leave(requester: RequestContext, target_employee_id: str) -> bool:
    """Check if requester can apply or cancel leave.

    Writes are strictly for the requester themselves, across all roles.
    """
    return requester.employee_id.strip() == target_employee_id.strip()
