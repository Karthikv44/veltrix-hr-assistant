"""Unit tests verifying the precedence engine and Section 5.2 worked example."""

from datetime import date

from veltrix.domain.precedence import PolicyClaim, PrecedenceResolver


def get_worked_example_claims() -> list[PolicyClaim]:
    """Claims from TASK.pdf Section 5.2 worked example:

    Document              Type      Regions  Effective date  Volunteer days
    Global policy v1      policy    GLOBAL   2025-01-01      2
    Global policy v2      policy    GLOBAL   2026-04-01      3
    Employee FAQ          faq       GLOBAL   2026-05-01      2
    Germany addendum      addendum  DE       2025-06-01      5
    Global policy v3      policy    GLOBAL   2027-01-01      4
    """
    return [
        PolicyClaim(
            group_id="volunteer_days",
            doc_id="POL-GLOBAL-V1",
            doc_type="policy",
            regions=("GLOBAL",),
            effective_date="2025-01-01",
            locator="Section 3",
            value="2",
        ),
        PolicyClaim(
            group_id="volunteer_days",
            doc_id="POL-GLOBAL-V2",
            doc_type="policy",
            regions=("GLOBAL",),
            effective_date="2026-04-01",
            locator="Section 3",
            value="3",
        ),
        PolicyClaim(
            group_id="volunteer_days",
            doc_id="FAQ-EMPLOYEE",
            doc_type="faq",
            regions=("GLOBAL",),
            effective_date="2026-05-01",
            locator="Q: Volunteer days",
            value="2",
        ),
        PolicyClaim(
            group_id="volunteer_days",
            doc_id="ADD-GERMANY",
            doc_type="addendum",
            regions=("DE",),
            effective_date="2025-06-01",
            locator="Section 2",
            value="5",
        ),
        PolicyClaim(
            group_id="volunteer_days",
            doc_id="POL-GLOBAL-V3",
            doc_type="policy",
            regions=("GLOBAL",),
            effective_date="2027-01-01",
            locator="Section 3",
            value="4",
        ),
    ]


def test_worked_example_india_employee() -> None:
    """India employee at 2026-09-15:

    The Germany addendum is not for their region, and v3 is not yet effective.
    The FAQ loses on authority. v1 and v2 tie on authority and scope, and v2 wins on recency.
    Answer: 3 days, with a mention that v3 raises it to 4 from 2027-01-01.
    """
    claims = get_worked_example_claims()
    ref_date = date(2026, 9, 15)

    decision = PrecedenceResolver.resolve(
        group_id="volunteer_days",
        all_claims=claims,
        user_region="IN",
        reference_date=ref_date,
    )

    assert decision.status == "winner"
    assert decision.winning_claim is not None
    assert decision.winning_claim.doc_id == "POL-GLOBAL-V2"
    assert decision.winning_claim.value == "3"
    assert decision.reason == "Won on recency"

    # Upcoming change
    assert decision.upcoming_claim is not None
    assert decision.upcoming_claim.doc_id == "POL-GLOBAL-V3"
    assert decision.upcoming_claim.value == "4"
    assert decision.upcoming_claim.effective_date == "2027-01-01"


def test_worked_example_germany_employee() -> None:
    """Germany employee at 2026-09-15:

    The Germany addendum wins on scope.
    v3 is not mentioned, because the addendum would still win on scope in 2027.
    Answer: 5 days.
    """
    claims = get_worked_example_claims()
    ref_date = date(2026, 9, 15)

    decision = PrecedenceResolver.resolve(
        group_id="volunteer_days",
        all_claims=claims,
        user_region="DE",
        reference_date=ref_date,
    )

    assert decision.status == "winner"
    assert decision.winning_claim is not None
    assert decision.winning_claim.doc_id == "ADD-GERMANY"
    assert decision.winning_claim.value == "5"
    assert decision.reason == "Won on scope"

    # v3 must NOT be mentioned because addendum still wins on scope in 2027
    assert decision.upcoming_claim is None


def test_worked_example_past_date_query() -> None:
    """India employee asking about 2025-08-01: only v1 is eligible. Answer: 2 days."""
    claims = get_worked_example_claims()
    ref_date = date(2025, 8, 1)

    decision = PrecedenceResolver.resolve(
        group_id="volunteer_days",
        all_claims=claims,
        user_region="IN",
        reference_date=ref_date,
    )

    assert decision.status == "winner"
    assert decision.winning_claim is not None
    assert decision.winning_claim.doc_id == "POL-GLOBAL-V1"
    assert decision.winning_claim.value == "2"


def test_unresolved_conflict_differing_values() -> None:
    """Same date, same authority, same scope, differing values -> CONFLICT."""
    claims = [
        PolicyClaim(
            group_id="parental_leave",
            doc_id="POL-PARENTAL",
            doc_type="policy",
            regions=("GLOBAL",),
            effective_date="2026-01-01",
            locator="Section 1",
            value="12 weeks",
        ),
        PolicyClaim(
            group_id="parental_leave",
            doc_id="SUMMARY-PARENTAL",
            doc_type="policy",
            regions=("GLOBAL",),
            effective_date="2026-01-01",
            locator="Page 1",
            value="16 weeks",
        ),
    ]

    decision = PrecedenceResolver.resolve(
        group_id="parental_leave",
        all_claims=claims,
        user_region="IN",
        reference_date=date(2026, 6, 1),
    )

    assert decision.status == "conflict"
    assert decision.winning_claim is None
    assert len(decision.conflicting_claims) == 2
    doc_ids = {c.doc_id for c in decision.conflicting_claims}
    assert doc_ids == {"POL-PARENTAL", "SUMMARY-PARENTAL"}


def test_equal_values_not_a_conflict() -> None:
    """Same date, authority, scope, identical values -> resolves cleanly (not a conflict)."""
    claims = [
        PolicyClaim(
            group_id="sick_days",
            doc_id="POL-SICK-A",
            doc_type="policy",
            regions=("GLOBAL",),
            effective_date="2026-01-01",
            locator="Section 1",
            value="10 days",
        ),
        PolicyClaim(
            group_id="sick_days",
            doc_id="POL-SICK-B",
            doc_type="policy",
            regions=("GLOBAL",),
            effective_date="2026-01-01",
            locator="Page 1",
            value="10 days",
        ),
    ]

    decision = PrecedenceResolver.resolve(
        group_id="sick_days",
        all_claims=claims,
        user_region="IN",
        reference_date=date(2026, 6, 1),
    )

    assert decision.status == "winner"
    assert decision.winning_claim is not None
    assert decision.winning_claim.value == "10 days"
