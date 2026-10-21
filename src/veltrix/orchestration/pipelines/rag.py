"""RAG pipeline coordinating retrieval, extraction, deterministic precedence, and composition."""

from datetime import date

from veltrix.core.logging import get_logger
from veltrix.domain.models import Citation, RequestContext
from veltrix.domain.precedence import PolicyClaim, PrecedenceDecision, PrecedenceResolver
from veltrix.orchestration.composer import AnswerComposer
from veltrix.orchestration.extractor import ClaimExtractor
from veltrix.retrieval.retriever import HybridRetriever
from veltrix.retrieval.scope import build_scope

logger = get_logger("rag_pipeline")


class RagPipeline:
    """Executes full RAG workflow under strict scope and deterministic precedence resolution."""

    def __init__(
        self,
        retriever: HybridRetriever,
        extractor: ClaimExtractor,
        composer: AnswerComposer,
    ) -> None:
        self.retriever = retriever
        self.extractor = extractor
        self.composer = composer

    async def execute(
        self,
        query: str,
        ctx: RequestContext,
        reference_date: date,
    ) -> tuple[str, list[Citation], str]:
        """Execute RAG retrieval and precedence-based answer composition.

        Returns:
            (answer_text, citations_list, route)
        """
        # 1. Build security scope (search without scope is impossible)
        scope = build_scope(ctx, reference_date)

        # 2. Hybrid retrieve (dense Chroma + BM25, fused via RRF, grouped by doc_id)
        retrieval_result = await self.retriever.retrieve(query, scope)

        if not retrieval_result.chunks:
            # In-scope question but no eligible documents cover it
            answer = (
                "The documents do not cover this question. "
                "Please reach out to the PeopleOps team at h***@veltrix.example for assistance."
            )
            return answer, [], "no_answer"

        # 3. Extract claims from packed evidence
        extracted_claims = await self.extractor.extract_claims(
            query=query,
            packed_evidence=retrieval_result.packed_evidence,
            chunks=retrieval_result.chunks + retrieval_result.upcoming_chunks,
        )

        # 4. Resolve precedence deterministically in Python per claim group
        # Group claims by group_id
        grouped_claims: dict[str, list[PolicyClaim]] = {}
        for c in extracted_claims:
            grouped_claims.setdefault(c.group_id, []).append(c)

        decisions: list[PrecedenceDecision] = []
        for gid, c_list in grouped_claims.items():
            decision = PrecedenceResolver.resolve(
                group_id=gid,
                all_claims=c_list,
                user_region=ctx.region,
                reference_date=reference_date,
            )
            decisions.append(decision)

        # 5. Compose answer and citations
        answer, citations = await self.composer.compose_rag_answer(
            query=query,
            decisions=decisions,
            packed_evidence=retrieval_result.packed_evidence,
            chunks=retrieval_result.chunks,
        )

        route = "rag" if citations else "no_answer"
        return answer, citations, route
