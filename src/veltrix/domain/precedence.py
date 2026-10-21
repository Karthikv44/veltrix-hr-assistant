"""Deterministic precedence resolver and claim models implementing Section 5 rules in pure Python."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from veltrix.core.logging import get_logger

logger = get_logger("precedence")

# Authority hierarchy: policy / addendum / memo / handbook / calendar > faq / wiki
AUTHORITY_TIER = {
    "policy": 5,
    "addendum": 5,
    "memo": 5,
    "handbook": 5,
    "calendar": 5,
    "faq": 1,
    "wiki": 1,
}

ResolutionStatus = Literal["winner", "conflict", "no_answer"]


@dataclass(frozen=True)
class PolicyClaim:
    """Structured claim extracted from a document chunk."""

    group_id: str  # Semantic rule group, e.g. "volunteer_days" or "sick_leave_days"
    doc_id: str
    doc_type: str
    regions: tuple[str, ...]
    effective_date: str  # YYYY-MM-DD
    locator: str
    value: str  # Normalized value, e.g. "3" or "25 days"
    unit: str = "days"
    conditions: str = ""
    raw_text: str = ""

    @property
    def authority_rank(self) -> int:
        return AUTHORITY_TIER.get(self.doc_type.lower(), 1)

    @property
    def effective_int(self) -> int:
        return int(self.effective_date.replace("-", ""))

    def is_region_specific(self) -> bool:
        """True if document is scoped to specific regions rather than GLOBAL."""
        return "GLOBAL" not in [r.upper() for r in self.regions]


@dataclass(frozen=True)
class PrecedenceDecision:
    """Outcome of resolving competing claims for a rule."""

    group_id: str
    status: ResolutionStatus
    winning_claim: PolicyClaim | None
    conflicting_claims: list[PolicyClaim]
    upcoming_claim: PolicyClaim | None = None
    reason: str = ""


class PrecedenceResolver:
    """Pure-Python deterministic precedence resolver implementing TASK.pdf Section 5.1 & 5.2.

    Rules in order:
    1. Eligibility: role may read access_level, region match or GLOBAL, effective_date <= reference_date.
    2. Authority: policy/addendum/memo/handbook/calendar > faq/wiki.
    3. Scope: specific regions > GLOBAL.
    4. Recency: later effective_date wins.
    5. Unresolved conflict: If tests still do not decide and values differ, return CONFLICT with both claims.
       Equal values are not a conflict.
    6. Upcoming changes: Mention future-dated claims only if they would WIN on their effective date.
    """

    @staticmethod
    def is_claim_eligible(claim: PolicyClaim, user_region: str, reference_date: date) -> bool:
        """Check if claim is eligible for the user on reference_date."""
        regions = [r.upper() for r in claim.regions]
        if "GLOBAL" not in regions and user_region.upper() not in regions:
            return False

        ref_int = reference_date.year * 10000 + reference_date.month * 100 + reference_date.day
        return claim.effective_int <= ref_int

    @classmethod
    def resolve_claims_at_date(
        cls,
        claims: list[PolicyClaim],
        user_region: str,
        eval_date: date,
    ) -> tuple[PolicyClaim | None, list[PolicyClaim], str]:
        """Run the resolution cascade over claims effective on or before eval_date.

        Returns: (winning_claim, conflicting_claims, reason)
        """
        eligible = [c for c in claims if cls.is_claim_eligible(c, user_region, eval_date)]
        if not eligible:
            return None, [], "No eligible claims"

        if len(eligible) == 1:
            return eligible[0], [], "Single eligible claim"

        # 1. Authority filter
        max_authority = max(c.authority_rank for c in eligible)
        after_authority = [c for c in eligible if c.authority_rank == max_authority]
        if len(after_authority) == 1:
            return after_authority[0], [], "Won on authority"

        # 2. Scope filter (specific regions > GLOBAL)
        has_specific_scope = any(c.is_region_specific() for c in after_authority)
        if has_specific_scope:
            after_scope = [c for c in after_authority if c.is_region_specific()]
        else:
            after_scope = after_authority

        if len(after_scope) == 1:
            return after_scope[0], [], "Won on scope"

        # 3. Recency filter (later effective_date wins)
        max_effective = max(c.effective_int for c in after_scope)
        after_recency = [c for c in after_scope if c.effective_int == max_effective]
        if len(after_recency) == 1:
            return after_recency[0], [], "Won on recency"

        # 4. Tie-break: if values are identical, they agree (not a conflict)
        unique_values = {c.value.strip().lower() for c in after_recency}
        if len(unique_values) == 1:
            # Deterministic pick by doc_id
            winner = sorted(after_recency, key=lambda x: x.doc_id)[0]
            return winner, [], "Tied on identical values"

        # 5. Unresolved conflict: return both values
        return None, after_recency, "Unresolved conflict: differing values with same precedence"

    @classmethod
    def resolve(
        cls,
        group_id: str,
        all_claims: list[PolicyClaim],
        user_region: str,
        reference_date: date,
    ) -> PrecedenceDecision:
        """Resolve current winner and project upcoming changes strictly per Section 5."""
        # 1. Resolve currently effective claim
        winner, conflicts, reason = cls.resolve_claims_at_date(
            all_claims, user_region, reference_date
        )

        if conflicts:
            return PrecedenceDecision(
                group_id=group_id,
                status="conflict",
                winning_claim=None,
                conflicting_claims=conflicts,
                reason=reason,
            )

        if not winner:
            return PrecedenceDecision(
                group_id=group_id,
                status="no_answer",
                winning_claim=None,
                conflicting_claims=[],
                reason=reason,
            )

        # 2. Upcoming changes check:
        # For every readable, region-matching future-dated claim, re-run resolver at that claim's effective date.
        # Mention it only if it would win.
        upcoming_winner: PolicyClaim | None = None
        ref_int = reference_date.year * 10000 + reference_date.month * 100 + reference_date.day

        future_candidates = [
            c
            for c in all_claims
            if c.effective_int > ref_int
            and (
                "GLOBAL" in [r.upper() for r in c.regions]
                or user_region.upper() in [r.upper() for r in c.regions]
            )
        ]

        # Sort future candidates chronologically
        future_candidates.sort(key=lambda x: x.effective_int)

        for future_claim in future_candidates:
            # Parse future date
            f_year = int(future_claim.effective_date[:4])
            f_month = int(future_claim.effective_date[5:7])
            f_day = int(future_claim.effective_date[8:10])
            f_date = date(f_year, f_month, f_day)

            # Re-run resolver over all claims effective by then
            f_winner, _f_conflicts, _ = cls.resolve_claims_at_date(all_claims, user_region, f_date)
            if (
                f_winner
                and f_winner.doc_id == future_claim.doc_id
                and f_winner.value.strip().lower() != winner.value.strip().lower()
            ):
                upcoming_winner = f_winner
                break

        return PrecedenceDecision(
            group_id=group_id,
            status="winner",
            winning_claim=winner,
            conflicting_claims=[],
            upcoming_claim=upcoming_winner,
            reason=reason,
        )
