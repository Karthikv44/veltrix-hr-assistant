"""Tools package exposing LeaveTools and ToolRegistry."""

from veltrix.tools.base import Tool, ToolDefinition
from veltrix.tools.leave import LeaveTools
from veltrix.tools.permissions import (
    FORBIDDEN_EMPLOYEE_MESSAGE,
    can_manage_team_leave,
    can_modify_leave,
    can_view_employee_leave,
)
from veltrix.tools.registry import ToolNotFoundError, ToolRegistry, tool_registry

__all__ = [
    "FORBIDDEN_EMPLOYEE_MESSAGE",
    "LeaveTools",
    "Tool",
    "ToolDefinition",
    "ToolNotFoundError",
    "ToolRegistry",
    "can_manage_team_leave",
    "can_modify_leave",
    "can_view_employee_leave",
    "tool_registry",
]
