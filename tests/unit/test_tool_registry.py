"""Unit tests for tool registry extensibility and tool definitions."""

from typing import Any

import pytest

from veltrix.domain.models import RequestContext
from veltrix.tools.registry import ToolNotFoundError, ToolRegistry


class FakeCustomTool:
    """A fake custom tool demonstrating registry extensibility."""

    name = "custom_calculator_tool"
    description = "Performs safe custom calculation."

    async def execute(self, ctx: RequestContext, **kwargs: Any) -> dict[str, Any]:
        val = kwargs.get("val", 0)
        return {"status": "success", "result": val * 2}


@pytest.mark.asyncio
async def test_tool_registry_extensibility() -> None:
    """Acceptance test: Adding a new tool requires only a new class plus one registration line."""
    registry = ToolRegistry()
    tool_instance = FakeCustomTool()

    # One registration line
    registry.register(tool_instance.name, tool_instance.execute)

    assert registry.has_tool("custom_calculator_tool")
    retrieved_func = registry.get("custom_calculator_tool")

    ctx = RequestContext(employee_id="E1001", role="employee", region="IN")
    res = await retrieved_func(ctx, val=21)
    assert res == {"status": "success", "result": 42}


def test_tool_registry_missing_tool() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        registry.get("non_existent_tool")
