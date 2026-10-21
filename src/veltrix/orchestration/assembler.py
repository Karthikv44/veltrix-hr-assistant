"""Response assembly and route invariant validation strictly implementing Section 8.1."""

from veltrix.api.schemas import ChatResponse, CitationSchema, ToolCallSchema
from veltrix.core.ids import generate_request_id
from veltrix.core.logging import get_logger
from veltrix.core.pii import sanitize_text_for_user
from veltrix.domain.models import Citation, RouteName, ToolCallRecord

logger = get_logger("assembler")


class Assembler:
    """Validates TASK.pdf Section 8.1 route invariants and constructs the final ChatResponse.

    Invariants:
    - rag: citations >= 1, tool_calls == 0
    - tool: citations == 0, tool_calls >= 1
    - hybrid: citations >= 1, tool_calls >= 1
    - clarify: citations == 0, tool_calls == 0
    - no_answer: citations == 0, tool_calls == 0
    - refuse: citations == 0, tool_calls == 0
    """

    @staticmethod
    def derive_and_validate_route(
        intended_route: RouteName,
        citations: list[Citation],
        tool_calls: list[ToolCallRecord],
    ) -> RouteName:
        """Derive or enforce the exact route based on citations and tool_calls invariants."""
        has_citations = len(citations) > 0
        has_tools = len(tool_calls) > 0

        # Special routes that must have empty citations and empty tool_calls
        if intended_route in ["refuse", "clarify", "no_answer", "tool"]:
            return intended_route

        if has_citations and has_tools:
            return "hybrid"
        if has_citations and not has_tools:
            return "rag"
        if not has_citations and has_tools:
            return "tool"

        # If neither citations nor tools were produced for an intended RAG query
        if intended_route == "rag" and not has_citations:
            return "no_answer"

        return intended_route

    @classmethod
    def assemble_response(
        cls,
        answer: str,
        intended_route: RouteName,
        citations: list[Citation] | None = None,
        tool_calls: list[ToolCallRecord] | None = None,
        pending_confirmation: bool = False,
        allowed_doc_ids: set[str] | None = None,
    ) -> ChatResponse:
        """Construct validated ChatResponse adhering to personal data masking and route invariants."""
        active_citations = list(citations or [])
        active_tools = list(tool_calls or [])

        # Filter citations: never cite a document the requester is not allowed to read
        if allowed_doc_ids is not None:
            active_citations = [c for c in active_citations if c.doc_id in allowed_doc_ids]

        # Deduplicate citations
        dedup_cites: dict[tuple[str, str], Citation] = {}
        for c in active_citations:
            dedup_cites[(c.doc_id, c.locator)] = c
        unique_citations = list(dedup_cites.values())

        # Derive final route
        final_route = cls.derive_and_validate_route(intended_route, unique_citations, active_tools)

        # Enforce empty citations for non-document routes
        if final_route in ["tool", "clarify", "no_answer", "refuse"]:
            unique_citations = []

        # Enforce empty tool_calls for non-tool routes
        if final_route in ["rag", "clarify", "no_answer", "refuse"]:
            active_tools = []

        # Sanitize answer text (mask emails, redact phones)
        sanitized_answer = sanitize_text_for_user(answer)

        # Convert citations to API schema
        citation_schemas = [
            CitationSchema(doc_id=c.doc_id, locator=c.locator) for c in unique_citations
        ]

        # Convert tool calls to API schema
        tool_schemas = [
            ToolCallSchema(name=t.name, args=t.args, status=t.status) for t in active_tools
        ]

        return ChatResponse(
            request_id=generate_request_id(),
            answer=sanitized_answer,
            route=final_route,
            citations=citation_schemas,
            tool_calls=tool_schemas,
            pending_confirmation=pending_confirmation,
        )
