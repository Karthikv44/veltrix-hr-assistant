"""Extensible tool registry mapping tool names to callable tool definitions."""

from collections.abc import Callable
from typing import Any

from veltrix.api.errors import VeltrixError
from veltrix.core.logging import get_logger

logger = get_logger("tool_registry")


class ToolNotFoundError(VeltrixError):
    """Raised when an unregistered tool is requested."""


class ToolRegistry:
    """Registry maintaining tool implementations and metadata."""

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, func: Callable[..., Any]) -> None:
        """Register a tool callable under a unique tool name."""
        self._tools[name] = func
        logger.debug("Registered tool in tool registry", tool_name=name)

    def get(self, name: str) -> Callable[..., Any]:
        """Fetch registered tool callable."""
        if name not in self._tools:
            raise ToolNotFoundError(f"Tool '{name}' is not registered.")
        return self._tools[name]

    def has_tool(self, name: str) -> bool:
        return name in self._tools


# Global default tool registry
tool_registry = ToolRegistry()
