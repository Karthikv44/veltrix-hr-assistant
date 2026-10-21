"""Domain models and data structures for Veltrix PeopleOps Assistant."""

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

Role = Literal["employee", "manager", "hr"]
RouteName = Literal["rag", "tool", "hybrid", "clarify", "no_answer", "refuse"]
LeaveType = Literal["annual", "sick"]
LeaveStatus = Literal["pending", "approved", "cancelled"]
ToolStatus = Literal["pending_confirmation", "success", "error"]


@dataclass(frozen=True)
class Employee:
    """Employee record as loaded from the database."""

    employee_id: str
    full_name: str
    email: str
    phone: str
    region: str
    join_date: str
    level: str
    role: Role
    manager_id: str | None = None


@dataclass(frozen=True)
class RequestContext:
    """Security and identity context extracted from X-Employee-Id and database."""

    employee_id: str
    role: Role
    region: str


@dataclass(frozen=True)
class LeaveBalance:
    """Current remaining leave balance for an employee."""

    employee_id: str
    leave_type: LeaveType
    balance_days: float


@dataclass(frozen=True)
class LeaveRequest:
    """Leave request record from the database."""

    request_id: str
    employee_id: str
    leave_type: LeaveType
    start_date: str
    end_date: str
    working_days: int
    status: LeaveStatus
    created_at: str


@dataclass(frozen=True)
class Citation:
    """Citation referencing a corpus document and locator."""

    doc_id: str
    locator: str

    def to_dict(self) -> dict[str, str]:
        return {"doc_id": self.doc_id, "locator": self.locator}


@dataclass(frozen=True)
class ToolCallRecord:
    """Record of a tool call executed or proposed during request processing."""

    name: str
    args: dict[str, Any]
    status: ToolStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "args": self.args,
            "status": self.status,
        }


@dataclass(frozen=True)
class Holiday:
    """Public holiday record extracted during ingestion."""

    doc_id: str
    date: date
    name: str
    kind: str  # 'public' | 'optional'
    region: str
