"""Security test suite validating zero document leakage using planted canary strings.

Enforces Non-Negotiable #2:
A document the requester may not read is NEVER sent to the LLM.
Filter in the retrieval query itself (pre-filter), AND assert again before prompt construction.
Never reveal that restricted documents exist.
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from veltrix.domain.models import RequestContext
from veltrix.ingestion.chunker import Chunk
from veltrix.retrieval.chroma_store import ChromaVectorStore
from veltrix.retrieval.embedder import FakeEmbedder
from veltrix.retrieval.retriever import HybridRetriever
from veltrix.retrieval.scope import build_scope


class SpyLLMRecorder:
    """Spy recorder logging every prompt or text sent to the LLM."""

    def __init__(self) -> None:
        self.recorded_texts: list[str] = []

    def record_prompt(self, text: str) -> None:
        self.recorded_texts.append(text)

    def contains(self, canary: str) -> bool:
        return any(canary in text for text in self.recorded_texts)


@pytest.fixture
def populated_security_env(tmp_path: Path):
    """Set up an isolated SQLite and Chroma store with planted canary strings across roles and regions."""
    test_app_db = tmp_path / "security_app.db"
    test_chroma = tmp_path / "security_chroma"

    from veltrix.data.db import init_app_db

    init_app_db(test_app_db)

    vector_store = ChromaVectorStore(persist_dir=test_chroma)
    embedder = FakeEmbedder(dimension=384)

    # Canaries
    HR_CANARY = "CANARY_HR_SECRET_SALARY_BAND_XYZ987"
    MANAGER_CANARY = "CANARY_MANAGER_PIP_CRITERIA_MGR456"
    US_CANARY = "CANARY_US_ONLY_BENEFITS_401K_USA123"
    EMPLOYEE_GLOBAL_CANARY = "CANARY_ALL_EMPLOYEES_PUBLIC_INFO_PUB001"

    chunks = [
        # 1. HR restricted document (access_rank=2)
        Chunk(
            chunk_id="HR_DOC_c001",
            doc_id="POL-HR-CONFIDENTIAL",
            text=f"Confidential executive compensation: {HR_CANARY}",
            embedded_text=f"HR > Comp\n\nConfidential executive compensation: {HR_CANARY}",
            locator="1. Executive Compensation",
            token_count=30,
            metadata={
                "doc_id": "POL-HR-CONFIDENTIAL",
                "doc_type": "policy",
                "title": "HR Confidential Policy",
                "locator": "1. Executive Compensation",
                "token_count": 30,
                "authority_rank": 5,
                "access_rank": 2,  # HR only
                "effective_int": 20260101,
                "effective_date": "2026-01-01",
                "region_GLOBAL": True,
                "region_IN": True,
                "region_US": True,
                "region_DE": True,
            },
        ),
        # 2. Manager restricted document (access_rank=1)
        Chunk(
            chunk_id="MGR_DOC_c001",
            doc_id="POL-MGR-PERF",
            text=f"Manager PIP guidelines: {MANAGER_CANARY}",
            embedded_text=f"Manager > Guidelines\n\nManager PIP guidelines: {MANAGER_CANARY}",
            locator="2. Performance Reviews",
            token_count=30,
            metadata={
                "doc_id": "POL-MGR-PERF",
                "doc_type": "handbook",
                "title": "Manager Handbook",
                "locator": "2. Performance Reviews",
                "token_count": 30,
                "authority_rank": 5,
                "access_rank": 1,  # Managers
                "effective_int": 20260101,
                "effective_date": "2026-01-01",
                "region_GLOBAL": True,
                "region_IN": True,
                "region_US": True,
                "region_DE": True,
            },
        ),
        # 3. US only document (access_rank=0, region_US=True, region_IN=False)
        Chunk(
            chunk_id="US_DOC_c001",
            doc_id="ADD-BENEFITS-US",
            text=f"US 401k match details: {US_CANARY}",
            embedded_text=f"US Benefits > 401k\n\nUS 401k match details: {US_CANARY}",
            locator="1. 401k",
            token_count=30,
            metadata={
                "doc_id": "ADD-BENEFITS-US",
                "doc_type": "addendum",
                "title": "US Benefits Addendum",
                "locator": "1. 401k",
                "token_count": 30,
                "authority_rank": 5,
                "access_rank": 0,  # All employees
                "effective_int": 20260101,
                "effective_date": "2026-01-01",
                "region_GLOBAL": False,
                "region_IN": False,
                "region_US": True,
                "region_DE": False,
            },
        ),
        # 4. Global all-employee document (access_rank=0, region_GLOBAL=True)
        Chunk(
            chunk_id="PUB_DOC_c001",
            doc_id="POL-LEAVE-GLOBAL",
            text=f"Public global leave policy: {EMPLOYEE_GLOBAL_CANARY}",
            embedded_text=f"Global Leave > Rules\n\nPublic global leave policy: {EMPLOYEE_GLOBAL_CANARY}",
            locator="1. Leave",
            token_count=30,
            metadata={
                "doc_id": "POL-LEAVE-GLOBAL",
                "doc_type": "policy",
                "title": "Global Leave Policy",
                "locator": "1. Leave",
                "token_count": 30,
                "authority_rank": 5,
                "access_rank": 0,  # All
                "effective_int": 20260101,
                "effective_date": "2026-01-01",
                "region_GLOBAL": True,
                "region_IN": True,
                "region_US": True,
                "region_DE": True,
            },
        ),
    ]

    # Populate SQLite app.db
    conn = sqlite3.connect(test_app_db)
    with conn:
        for c in chunks:
            m = c.metadata
            conn.execute(
                """
                INSERT INTO chunks (
                    chunk_id, doc_id, doc_type, title, text, embedded_text, locator,
                    token_count, authority_rank, access_rank, effective_int, effective_date,
                    region_GLOBAL, region_IN, region_US, region_DE
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    c.chunk_id,
                    c.doc_id,
                    m["doc_type"],
                    m["title"],
                    c.text,
                    c.embedded_text,
                    c.locator,
                    c.token_count,
                    m["authority_rank"],
                    m["access_rank"],
                    m["effective_int"],
                    m["effective_date"],
                    m["region_GLOBAL"],
                    m["region_IN"],
                    m["region_US"],
                    m["region_DE"],
                ),
            )
    conn.close()

    # Populate Chroma
    import asyncio

    embeddings = embedder.embed_texts([c.embedded_text for c in chunks])
    asyncio.run(vector_store.add_chunks(chunks, embeddings))

    retriever = HybridRetriever(
        vector_store=vector_store, embedder=embedder, app_db_path=test_app_db
    )
    canaries = {
        "hr": HR_CANARY,
        "manager": MANAGER_CANARY,
        "us": US_CANARY,
        "public": EMPLOYEE_GLOBAL_CANARY,
    }
    return retriever, canaries


@pytest.mark.asyncio
async def test_employee_in_cannot_see_manager_hr_or_us_canaries(populated_security_env) -> None:
    """Assert an Indian employee (role=employee, region=IN) NEVER retrieves HR, Manager, or US canaries."""
    retriever, canaries = populated_security_env
    spy = SpyLLMRecorder()

    ctx = RequestContext(employee_id="E9001", role="employee", region="IN")
    scope = build_scope(ctx, reference_date=date(2026, 6, 1))

    # Query intentionally probing sensitive terms
    res = await retriever.retrieve("compensation review 401k policy", scope=scope)
    spy.record_prompt(res.packed_evidence)

    # 1. Assert HR canary never leaked
    assert not spy.contains(canaries["hr"]), "CRITICAL LEAK: HR canary leaked to employee!"
    # 2. Assert Manager canary never leaked
    assert not spy.contains(canaries["manager"]), (
        "CRITICAL LEAK: Manager canary leaked to employee!"
    )
    # 3. Assert US region canary never leaked to IN employee
    assert not spy.contains(canaries["us"]), "CRITICAL LEAK: US canary leaked to IN employee!"
    # 4. Assert public global canary IS retrieved
    assert spy.contains(canaries["public"])


@pytest.mark.asyncio
async def test_manager_cannot_see_hr_canary(populated_security_env) -> None:
    """Assert a Manager (role=manager, region=IN) can see manager data, but NEVER HR confidential data."""
    retriever, canaries = populated_security_env
    spy = SpyLLMRecorder()

    ctx = RequestContext(employee_id="M5001", role="manager", region="IN")
    scope = build_scope(ctx, reference_date=date(2026, 6, 1))

    res = await retriever.retrieve("executive compensation performance reviews", scope=scope)
    spy.record_prompt(res.packed_evidence)

    assert not spy.contains(canaries["hr"]), "CRITICAL LEAK: HR canary leaked to manager!"
    assert spy.contains(canaries["manager"])


@pytest.mark.asyncio
async def test_hr_can_see_all_roles(populated_security_env) -> None:
    """Assert HR role can access documents across all access tiers."""
    retriever, canaries = populated_security_env
    spy = SpyLLMRecorder()

    ctx = RequestContext(employee_id="H1001", role="hr", region="IN")
    scope = build_scope(ctx, reference_date=date(2026, 6, 1))

    res = await retriever.retrieve("executive compensation performance reviews", scope=scope)
    spy.record_prompt(res.packed_evidence)

    assert spy.contains(canaries["hr"])
    assert spy.contains(canaries["manager"])
