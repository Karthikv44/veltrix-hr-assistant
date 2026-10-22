"""Base definitions and interfaces for tools."""

from dataclasses import dataclass
from typing import Any, Protocol

from veltrix.domain.models import RequestContext


@dataclass(frozen=True)
class ToolDefinition:
    """Metadata describing an executable tool."""

    name: str
    description: str
    parameters: dict[str, Any]


class Tool(Protocol):
    """Protocol for tools that can be executed by the assistant."""

    name: str
    description: str

    async def execute(self, ctx: RequestContext, **kwargs: Any) -> dict[str, Any]:
        """Execute the tool within the verified security RequestContext."""
        ...
