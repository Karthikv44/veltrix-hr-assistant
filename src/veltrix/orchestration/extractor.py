"""Claim extraction schemas and LLM-driven structured extractor."""

import json

from pydantic import BaseModel, Field

from veltrix.core.logging import get_logger
from veltrix.domain.precedence import PolicyClaim
from veltrix.ingestion.chunker import Chunk
from veltrix.llm.base import LLMMessage, LLMRequest
from veltrix.llm.gateway import LLMGateway

logger = get_logger("extractor")


class ExtractedClaimSchema(BaseModel):
    """Schema for a single claim extracted by LLM."""

    group_id: str = Field(
        ..., description="Semantic rule group, e.g. 'annual_leave_allowance', 'working_hours'"
    )
    doc_id: str = Field(..., description="The document ID from the passage header")
    locator: str = Field(..., description="The locator from the passage header")
    value: str = Field(..., description="Specific numeric or policy value stated in the passage")
    unit: str = Field(
        default="days", description="Unit if applicable, e.g. 'days', 'hours', 'weeks'"
    )
    conditions: str = Field(
        default="", description="Any eligibility conditions, tenure, or tier mentioned"
    )


class ClaimExtractionOutput(BaseModel):
    """Structured extraction output containing extracted claims."""

    claims: list[ExtractedClaimSchema] = Field(default_factory=list)


EXTRACTION_SYSTEM_PROMPT = """You are a precise data extraction specialist for company policies.
Analyze the provided document passages and extract specific factual policy rules, allowances, and requirements.

Group rules that govern the SAME policy topic under the same group_id (e.g. 'annual_leave_allowance', 'volunteer_leave', 'probation_period', 'working_hours').
Strictly output a JSON object matching this schema:
{
  "claims": [
    {
      "group_id": "rule_name",
      "doc_id": "EXACT_DOC_ID_FROM_HEADER",
      "locator": "EXACT_LOCATOR_FROM_HEADER",
      "value": "extracted value or rule statement",
      "unit": "days/hours/etc",
      "conditions": "any specific conditions"
    }
  ]
}

Only extract claims explicitly stated in the evidence. If a passage does not mention rules relevant to the query, omit it.
"""


class ClaimExtractor:
    """Extracts semantic policy claims from packed corpus evidence using the LLM Gateway."""

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    async def extract_claims(
        self,
        query: str,
        packed_evidence: str,
        chunks: list[Chunk],
    ) -> list[PolicyClaim]:
        """Extract claims from packed evidence text."""
        if not packed_evidence.strip() or not chunks:
            return []

        chunk_meta_map = {c.doc_id: c.metadata for c in chunks}

        user_content = f"Question: {query}\n\nEvidence:\n{packed_evidence}"
        request = LLMRequest(
            messages=[
                LLMMessage(role="system", content=EXTRACTION_SYSTEM_PROMPT),
                LLMMessage(role="user", content=user_content),
            ],
            corpus_text=packed_evidence,
            temperature=0.0,
            response_schema=ClaimExtractionOutput,
        )

        try:
            response = await self.gateway.complete(request)
            raw_json = response.content

            # Parse JSON with fallback for markdown code fences
            clean_json = raw_json.strip()
            if clean_json.startswith("```"):
                lines = clean_json.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_json = "\n".join(lines).strip()

            data = json.loads(clean_json)
            extracted_list = data.get("claims", [])
        except Exception as e:
            logger.warning(
                "LLM claim extraction failed, falling back to empty claims", error=str(e)
            )
            return []

        claims: list[PolicyClaim] = []
        for raw in extracted_list:
            doc_id = raw.get("doc_id", "").strip()
            meta = chunk_meta_map.get(doc_id, {})

            # Derive regions from metadata
            regions_list = []
            if meta.get("region_GLOBAL"):
                regions_list.append("GLOBAL")
            for reg in ["IN", "US", "DE"]:
                if meta.get(f"region_{reg}") and "GLOBAL" not in regions_list:
                    regions_list.append(reg)
            if not regions_list:
                regions_list = ["GLOBAL"]

            claim = PolicyClaim(
                group_id=raw.get("group_id", "general").strip(),
                doc_id=doc_id,
                doc_type=meta.get("doc_type", "policy"),
                regions=tuple(regions_list),
                effective_date=meta.get("effective_date", "2026-01-01"),
                locator=raw.get("locator", "p. 1").strip(),
                value=raw.get("value", "").strip(),
                unit=raw.get("unit", "days").strip(),
                conditions=raw.get("conditions", "").strip(),
            )
            claims.append(claim)

        return claims
