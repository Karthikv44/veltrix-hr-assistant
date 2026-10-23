"""Answer composition from resolved precedence decisions and evidence."""

import json

from pydantic import BaseModel, Field

from veltrix.core.logging import get_logger
from veltrix.core.pii import sanitize_text_for_user
from veltrix.domain.models import Citation
from veltrix.domain.precedence import PrecedenceDecision
from veltrix.ingestion.chunker import Chunk
from veltrix.llm.base import LLMMessage, LLMRequest
from veltrix.llm.gateway import LLMGateway

logger = get_logger("composer")


class UsedCitation(BaseModel):
    """Schema for a citation used in an answer."""

    doc_id: str = Field(..., description="The document ID from the passage header")
    locator: str = Field(default="", description="The section or page locator")


class ComposerOutput(BaseModel):
    """Schema for composed answer and citations."""

    answer: str
    used_citations: list[UsedCitation] = Field(default_factory=list)


COMPOSITION_SYSTEM_PROMPT = """You are the Veltrix PeopleOps Assistant.
Formulate a helpful, clear, and professional response to the employee's question based strictly on the provided policy decision and evidence.

Guidelines:
1. State the authoritative policy rule clearly.
2. If there is an upcoming change mentioned in the decision, mention it clearly (e.g. "Note: Global policy v3 will increase this to 4 days effective from 2027-01-01.").
3. If there is a policy conflict, state both conflicting values and their respective documents objectively without picking one.
4. Output a JSON object matching this schema:
{
  "answer": "Clear human-readable answer",
  "used_citations": [
    {"doc_id": "DOC_ID", "locator": "LOCATOR"}
  ]
}
Only cite documents that directly support your claims.
"""


class AnswerComposer:
    """Composes natural-language responses backed by precedence decisions and citations."""

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    async def compose_rag_answer(
        self,
        query: str,
        decisions: list[PrecedenceDecision],
        packed_evidence: str,
        chunks: list[Chunk],
    ) -> tuple[str, list[Citation]]:
        """Compose answer from decisions and evidence."""
        # 1. Deterministic format of decision context
        decisions_summary: list[str] = []
        authoritative_citations: list[Citation] = []

        for d in decisions:
            if d.status == "winner" and d.winning_claim:
                w = d.winning_claim
                authoritative_citations.append(Citation(doc_id=w.doc_id, locator=w.locator))
                summary = f"Rule '{d.group_id}': Active value is '{w.value}' (Authority: {w.doc_type}, Doc: {w.doc_id}, Locator: {w.locator})."
                if d.upcoming_claim:
                    u = d.upcoming_claim
                    authoritative_citations.append(Citation(doc_id=u.doc_id, locator=u.locator))
                    summary += f" Upcoming change: '{u.value}' effective from {u.effective_date} (Doc: {u.doc_id}, Locator: {u.locator})."
                decisions_summary.append(summary)

            elif d.status == "conflict":
                summary = f"Rule '{d.group_id}': UNRESOLVED CONFLICT between:"
                for c in d.conflicting_claims:
                    authoritative_citations.append(Citation(doc_id=c.doc_id, locator=c.locator))
                    summary += f"\n- {c.doc_id} ({c.locator}): '{c.value}'"
                decisions_summary.append(summary)

        if not decisions_summary and not packed_evidence.strip():
            # No eligible documents
            return (
                "The available documents do not cover this question. Please contact the PeopleOps team at h***@veltrix.example for assistance.",
                [],
            )

        user_content = (
            f"Question: {query}\n\n"
            f"Resolved Policy Decisions:\n" + "\n".join(decisions_summary) + "\n\n"
            f"Corpus Evidence Passages:\n{packed_evidence}"
        )

        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=COMPOSITION_SYSTEM_PROMPT),
                LLMMessage(role="user", content=user_content),
            ],
            corpus_text=packed_evidence,
            temperature=0.0,
            response_schema=ComposerOutput,
        )

        try:
            resp = await self.gateway.complete(request)
            raw = resp.content.strip()
            if raw.startswith("```"):
                lines = raw.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw = "\n".join(lines).strip()

            parsed = json.loads(raw)
            raw_answer = parsed.get("answer", "")
            raw_cites = parsed.get("used_citations", [])

            # Deduplicate citations and ensure validity
            valid_doc_ids = {c.doc_id for c in chunks}
            citations_dict: dict[tuple[str, str], Citation] = {}

            # Add authoritative decision citations first
            for ac in authoritative_citations:
                citations_dict[(ac.doc_id, ac.locator)] = ac

            for rc in raw_cites:
                if isinstance(rc, dict):
                    doc_id = rc.get("doc_id", "").strip()
                    locator = rc.get("locator", "").strip()
                elif hasattr(rc, "doc_id"):
                    doc_id = getattr(rc, "doc_id", "").strip()
                    locator = getattr(rc, "locator", "").strip()
                else:
                    continue
                if doc_id in valid_doc_ids and locator:
                    citations_dict[(doc_id, locator)] = Citation(doc_id=doc_id, locator=locator)

            final_answer = sanitize_text_for_user(raw_answer)
            return final_answer, list(citations_dict.values())

        except Exception as e:
            logger.warning(
                "LLM answer composition failed, falling back to deterministic synthesis",
                error=str(e),
            )
            # Safe deterministic fallback
            text_lines = ["Based on company policies:"]
            for s in decisions_summary:
                text_lines.append(f"- {s}")
            fallback_answer = sanitize_text_for_user("\n".join(text_lines))
            return fallback_answer, authoritative_citations
