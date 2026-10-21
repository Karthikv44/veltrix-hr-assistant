"""Unit tests for assembler route invariants and personal data sanitation."""

from veltrix.domain.models import Citation, ToolCallRecord
from veltrix.orchestration.assembler import Assembler


def test_assembler_rag_route_invariant() -> None:
    citations = [Citation(doc_id="POL-LEAVE", locator="Section 1")]
    res = Assembler.assemble_response(
        answer="You have 20 days annual leave.",
        intended_route="rag",
        citations=citations,
        tool_calls=[],
    )
    assert res.route == "rag"
    assert len(res.citations) == 1
    assert len(res.tool_calls) == 0


def test_assembler_tool_route_invariant() -> None:
    tool_calls = [
        ToolCallRecord(name="get_leave_balance", args={"leave_type": "annual"}, status="success")
    ]
    # Intended tool route must have empty citations
    res = Assembler.assemble_response(
        answer="Balance is 15 days.",
        intended_route="tool",
        citations=[Citation(doc_id="CAL-HOL", locator="p. 1")],  # Should be stripped
        tool_calls=tool_calls,
    )
    assert res.route == "tool"
    assert len(res.citations) == 0
    assert len(res.tool_calls) == 1


def test_assembler_refuse_route_invariant() -> None:
    res = Assembler.assemble_response(
        answer="I cannot fulfill that request.",
        intended_route="refuse",
        citations=[Citation(doc_id="DOC1", locator="p. 1")],  # Should be stripped
        tool_calls=[ToolCallRecord(name="test", args={}, status="error")],  # Should be stripped
    )
    assert res.route == "refuse"
    assert len(res.citations) == 0
    assert len(res.tool_calls) == 0


def test_assembler_sanitizes_emails_in_answer() -> None:
    res = Assembler.assemble_response(
        answer="Contact hr@veltrix.example or support@company.org for help.",
        intended_route="no_answer",
    )
    assert "h***@veltrix.example" in res.answer
    assert "s***@company.org" in res.answer
    assert "hr@veltrix.example" not in res.answer
