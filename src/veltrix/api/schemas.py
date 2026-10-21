"""Pydantic schemas matching the TASK.pdf API contract."""

from typing import Any, Literal

from pydantic import BaseModel, Field

RouteType = Literal["rag", "tool", "hybrid", "clarify", "no_answer", "refuse"]
ToolCallStatusType = Literal["pending_confirmation", "success", "error"]


class ChatRequest(BaseModel):
    """Request payload for POST /chat."""

    session_id: str = Field(..., min_length=1, description="Client-chosen session identifier")
    message: str = Field(..., min_length=1, description="User prompt message")


class CitationSchema(BaseModel):
    """Citation identifying a document and locator."""

    doc_id: str
    locator: str


class ToolCallSchema(BaseModel):
    """Tool call descriptor in API responses."""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: ToolCallStatusType


class ChatResponse(BaseModel):
    """Response payload for POST /chat matching TASK.pdf section 9.1 exactly."""

    request_id: str
    answer: str
    route: RouteType
    citations: list[CitationSchema] = Field(default_factory=list)
    tool_calls: list[ToolCallSchema] = Field(default_factory=list)
    pending_confirmation: bool = False


class HealthResponse(BaseModel):
    """Response payload for GET /health."""

    status: str
