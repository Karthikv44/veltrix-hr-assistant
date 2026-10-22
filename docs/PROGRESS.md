# Veltrix PeopleOps Assistant - Implementation Progress

## Overall Status: IN PROGRESS (Milestone M7)

| Milestone | Description | Status | Ruff Gate | Pytest Gate |
|---|---|---|---|---|
| M0 | Scaffolding, config, logging, tokens, clock, DI container | Completed | Passed | Passed (8 tests) |
| M1 | Docker, FastAPI skeleton, health lifecycle, identity/session, LLM gateway | Completed | Passed | Passed (27 tests) |
| M2 | Ingestion pipeline, document loaders, OCR, tables, holiday extraction, Chroma index | Completed | Passed | Passed (39 tests) |
| M3 | Scoped retrieval, pre-filters, BM25 + dense RRF, packer, eligibility assertions | Completed | Passed | Passed (47 tests) |
| M4 | Precedence resolver, claim extractor, composer, citations, RAG/refuse routes | Completed | Passed | Passed (56 tests) |
| M5 | Tools (`apply_leave`, etc.), workdays, dates, permissions, 2-step confirm flow | Completed | Passed | Passed (64 tests) |
| M6 | Hybrid pipeline, future balances, PII masking, injection defenses, log audit | Completed | Passed | Passed (65 tests) |
| M7 | Mutated corpus tests, integration test suite, evaluation script, README, DESIGN.md | In Progress | Pending | Pending |

---

## Must-Pass Checks Checklist
- [x] **Must-Pass 1**: `docker compose up` starts service, `/health` 200 within 10 min (503 prior to ingestion), zero manual steps. (Verified lifespan & health transitions)
- [x] **Must-Pass 2**: Ineligible documents NEVER sent to LLM (pre-filter in query + assert before prompt). (Verified with canary unit & security tests)
- [x] **Must-Pass 3**: Zero leave data leakage across roles (`X-Employee-Id` driven, no LLM bypass). (Verified via DB-level permission checks in tools)
- [x] **Must-Pass 4**: LLM context budget <= 3,000 corpus tokens (tiktoken `cl100k_base`), enforced in gateway and logged. (Verified in LLMGateway decorators & audit tests)
- [ ] **Must-Pass 5**: Service works on mutated corpus without hardcoded facts. (To verify in M7 integration suite)

---

## Recent Activity
- Implemented `FutureBalanceCalculator` in pure Python domain arithmetic accounting for leave type, country accrual schedules, and existing approved requests.
- Implemented `HybridPipeline` combining deterministic leave balances with scoped RAG for policy context.
- Implemented full structlog PII scrubbing (emails, phone numbers, employee IDs, IBANs, SSNs) and audit tests in `tests/security/test_log_audit.py`.
- Verified clean run of 65 unit and security tests.
