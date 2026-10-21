# Veltrix PeopleOps Assistant - Implementation Progress

## Overall Status: IN PROGRESS (Milestone M0)

| Milestone | Description | Status | Ruff Gate | Pytest Gate |
|---|---|---|---|---|
| M0 | Scaffolding, config, logging, tokens, clock, DI container | Completed | Passed | Passed (8 tests) |
| M1 | Docker, FastAPI skeleton, health lifecycle, identity/session, LLM gateway | In Progress | Pending | Pending |
| M2 | Ingestion pipeline, document loaders, OCR, tables, holiday extraction, Chroma index | Planned | - | - |
| M3 | Scoped retrieval, pre-filters, BM25 + dense RRF, packer, eligibility assertions | Planned | - | - |
| M4 | Precedence resolver, claim extractor, composer, citations, RAG/refuse routes | Planned | - | - |
| M5 | Tools (`apply_leave`, etc.), workdays, dates, permissions, 2-step confirm flow | Planned | - | - |
| M6 | Hybrid pipeline, future balances, PII masking, injection defenses, log audit | Planned | - | - |
| M7 | Mutated corpus tests, integration test suite, evaluation script, README, DESIGN.md | Planned | - | - |

---

## Must-Pass Checks Checklist
- [ ] **Must-Pass 1**: `docker compose up` starts service, `/health` 200 within 10 min (503 prior to ingestion), zero manual steps.
- [ ] **Must-Pass 2**: Ineligible documents NEVER sent to LLM (pre-filter in query + assert before prompt).
- [ ] **Must-Pass 3**: Zero leave data leakage across roles (`X-Employee-Id` driven, no LLM bypass).
- [ ] **Must-Pass 4**: LLM context budget <= 3,000 corpus tokens (tiktoken `cl100k_base`), enforced in gateway and logged.
- [ ] **Must-Pass 5**: Service works on mutated corpus without hardcoded facts.

---

## Recent Activity
- Analyzed `docs/TASK.pdf` requirements and cataloged edge cases.
- Analyzed reference repository `catalog-mcp` and generated `docs/REFERENCE_ANALYSIS.md`.
- Evaluated ChromaDB capabilities and authored `docs/adr/0001-vector-store.md`.
- Authored initial `docs/PLAN.md` and `docs/ASSUMPTIONS.md`.
