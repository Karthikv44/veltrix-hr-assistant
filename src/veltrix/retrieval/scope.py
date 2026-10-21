"""Retrieval scope builder and pre-filters enforcing access control and region matching."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from veltrix.api.errors import VeltrixError
from veltrix.core.logging import get_logger
from veltrix.domain.models import RequestContext
from veltrix.ingestion.chunker import Chunk

logger = get_logger("scope")

ROLE_ACCESS_RANK = {
    "employee": 0,
    "manager": 1,
    "hr": 2,
}


class ScopeViolationError(VeltrixError):
    """Raised when an ineligible document or chunk is detected before prompt construction."""


@dataclass(frozen=True)
class RetrievalScope:
    """Security and eligibility boundary for document retrieval.

    Search without a scope is impossible by signature.
    """

    employee_id: str
    role: str
    region: str
    reference_date: date
    role_rank: int
    ref_int: int  # YYYYMMDD
    all_known_regions: tuple[str, ...] = ("IN", "US", "DE")

    def to_chroma_where(self, upcoming: bool = False) -> dict[str, Any]:
        """Build scalar ChromaDB 'where' filter adhering to Section 6.2.

        Dense query pre-filter:
        access_rank <= role_rank AND (region_GLOBAL OR region_<user_region>) AND effective_int <= ref_int
        (or effective_int > ref_int for upcoming changes).
        """
        conditions: list[dict[str, Any]] = [
            {"access_rank": {"$lte": self.role_rank}},
        ]

        # Region condition: region_GLOBAL == True OR region_<user_region> == True
        region_key = f"region_{self.region.upper()}"
        conditions.append(
            {
                "$or": [
                    {"region_GLOBAL": {"$eq": True}},
                    {region_key: {"$eq": True}},
                ]
            }
        )

        # Date condition
        if upcoming:
            conditions.append({"effective_int": {"$gt": self.ref_int}})
        else:
            conditions.append({"effective_int": {"$lte": self.ref_int}})

        return {"$and": conditions}

    def is_chunk_eligible(self, chunk: Chunk, allow_upcoming: bool = False) -> bool:
        """Predicate checking if a chunk is strictly eligible for this scope."""
        m = chunk.metadata
        chunk_access = m.get("access_rank", 0)
        if chunk_access > self.role_rank:
            return False

        # Region check
        is_global = bool(m.get("region_GLOBAL", False))
        matches_region = bool(m.get(f"region_{self.region.upper()}", False))
        if not (is_global or matches_region):
            return False

        # Effective date check
        effective_int = m.get("effective_int", 0)
        if allow_upcoming:
            return effective_int > self.ref_int
        return effective_int <= self.ref_int


def build_scope(
    requester: RequestContext,
    reference_date: date,
    all_known_regions: tuple[str, ...] = ("IN", "US", "DE"),
) -> RetrievalScope:
    """Factory to construct a verified RetrievalScope from a RequestContext and reference date."""
    role_rank = ROLE_ACCESS_RANK.get(requester.role.lower(), 0)
    ref_int = reference_date.year * 10000 + reference_date.month * 100 + reference_date.day

    return RetrievalScope(
        employee_id=requester.employee_id,
        role=requester.role.lower(),
        region=requester.region.upper(),
        reference_date=reference_date,
        role_rank=role_rank,
        ref_int=ref_int,
        all_known_regions=all_known_regions,
    )


def assert_all_eligible(
    chunks: list[Chunk], scope: RetrievalScope, allow_upcoming: bool = False
) -> None:
    """Defense in depth: strictly assert every chunk to be included in prompt is eligible under scope.

    A violation raises ScopeViolationError and logs doc_id and employee_id only.
    """
    for chunk in chunks:
        if not scope.is_chunk_eligible(chunk, allow_upcoming=allow_upcoming):
            logger.error(
                "Access control violation detected before prompt construction",
                doc_id=chunk.doc_id,
                employee_id=scope.employee_id,
            )
            raise ScopeViolationError(
                f"Security assertion failed: doc_id '{chunk.doc_id}' is ineligible for employee '{scope.employee_id}'"
            )
