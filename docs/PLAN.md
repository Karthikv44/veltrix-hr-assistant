# Implementation Plan: Veltrix PeopleOps Assistant

## Core Priorities
1. **The Five Must-Pass Checks**:
   - `docker compose up` starts service, `/health` 200 within 10m (503 prior to ingestion completion), zero manual steps.
   - Zero leakage: Ineligible documents NEVER sent to LLM (pre-filter in vector store + BM25, assert before prompt).
   - Zero leave leakage: Permission checks inside tool code using `X-Employee-Id`, never LLM args. Identity/role/region only from DB.
   - Context budget: `<= 3,000` tokens corpus text (tiktoken `cl100k_base`), enforced in LLM gateway, logged on every call.
   - Corpus independence: System operates generically on mutated corpus; no hardcoded facts/dates/ids/numbers.
2. **Correctness & Precedence**:
   - Strict deterministic resolver: Authority > Scope > Recency. Unresolved ties yield CONFLICT with both citations.
   - Upcoming changes evaluated at their effective date; mentioned only if winning.
   - Dual-LLM privilege separation: Tool proposal step sees no corpus text; corpus reasoning step cannot call tools.
3. **Robustness & Extensibility**:
   - Clean architecture, Strategy, Factory, Repository, Facade, Command, State Machine, Specification.
   - One new format or one new tool requires only one class + one registration line.

---

## Architecture Overview
```text
           [ Client / User ]
                  │ (HTTP POST /chat, X-Employee-Id)
                  ▼
          ┌───────────────┐
          │   FastAPI     │
          │  Controllers  │
          └───────┬───────┘
                  │ RequestContext (DB-verified)
                  ▼
          ┌───────────────┐
          │ Orchestrator  │
          └───────┬───────┘
     ┌────────────┼─────────────┐
     ▼            ▼             ▼
┌─────────┐ ┌───────────┐ ┌───────────┐
│ Router  │ │RagService │ │LeaveServ. │
└────┬────┘ └─────┬─────┘ └─────┬─────┘
     │            ▼             ▼
     │      ┌───────────┐ ┌───────────┐
     │      │ Retriever │ │   Tools   │
     │      │ Scope/RRF │ │Repository │
     │      └─────┬─────┘ └───────────┘
     │            │
     ▼            ▼
 ┌──────────────────────┐
 │     LLM Gateway      │ (<= 3000 corpus tokens guard,
 └──────────┬───────────┘  logging, caching, timeout)
            ▼
     [ LLM Providers ]
```

---

## Milestones & Work Breakdown

### Milestone M0: Foundations & Project Scaffolding
- Setup `pyproject.toml`, `uv.lock`, dependencies (FastAPI, uvicorn, pydantic, pydantic-settings, structlog, tiktoken, chromadb, fastembed, rank_bm25, PyMuPDF, python-docx, pdfplumber, beautifulsoup4, lxml, markdown-it-py, pytesseract, Pillow, python-dateutil).
- Core modules: `config.py`, `logging.py` (with PII filter), `tokens.py` (tiktoken budget calculator), `clock.py` (`APP_TODAY` abstraction), `ids.py`.
- Base composition root (`api/container.py`) and Makefile targets (`make test`, `make lint`, `make format`).

### Milestone M1: Docker, Identity & Health Lifecycle
- Multi-stage `Dockerfile` with system dependencies (`tesseract-ocr`), cached models/BPE, and `docker-compose.yml`.
- FastAPI app lifecycle (`lifespan` with background ingestion task).
- `/health` endpoint returning 503 during ingestion, 200 `{"status": "ok"}` on completion.
- Identity & security middleware / dependencies: `X-Employee-Id` validation (401), session ownership binding in SQLite (403).
- LLM Gateway with strict corpus-token guard (`<= 3000` tokens) and tests.

### Milestone M2: Ingestion Engine & Holiday Extraction
- Extensible Loader Registry: PDF, DOCX, Markdown, HTML, Scanned/OCR (Tesseract).
- Text cleaning: header/footer stripping, boilerplate removal, metadata table stripping.
- Section-based chunker with token bounds (250-350 target, 450 hard cap), hierarchical context headers (`Title > Section`).
- Deterministic holiday table extractor for `calendar` documents into `app.db` with structured fallback.
- Ingestion pipeline: hashing corpus + manifest for idempotent indexing into embedded Chroma and `app.db`.

### Milestone M3: Scoped Retrieval & Security Defense-in-Depth
- `RetrievalScope` builder with strict boolean flags (`region_X`, `access_rank`, `effective_int`).
- Dense search via Chroma pre-filter + BM25 lexical search over eligible IDs only.
- Reciprocal Rank Fusion (RRF) and doc_id grouping (top 2 chunks per doc).
- Evidence Packer (greedy, diversity-aware, strictly <= 2800 tokens).
- Pre-prompt guard: `assert_all_eligible(chunks, scope)`.
- Security unit tests with canary strings ensuring zero document leakage.

### Milestone M4: Precedence Engine, Claim Extractor & RAG Route
- Pure Python precedence resolver (`domain/precedence.py`): Authority > Scope > Recency, tie-breaks, conflict detection.
- Worked example unit tests (TASK.pdf Section 5.2 exactly reproduced).
- Upcoming changes projection test at future effective dates.
- LLM claim extractor and answer composer.
- Assembler validating citations, invariants, routes `rag`, `no_answer`, `refuse`.

### Milestone M5: Leave Tools, Workdays & Two-Step Write State Machine
- Tools: `get_leave_balance`, `list_leave_requests`, `get_team_leave`, `apply_leave`, `cancel_leave`.
- Working days calculation: Mon-Fri excluding holidays from winning regional calendar.
- Date phrase resolution: Monday start, "next week", "next Friday" (relative to `APP_TODAY`).
- Two-step confirmation state machine (propose with dry run -> pending_confirmation -> atomic execute on clear confirm).
- Concurrency and transaction safety (`BEGIN IMMEDIATE` in SQLite).
- Permission enforcement: employee self, manager direct reports, HR single employee. Disallowed response: "I can't share information about that employee."

### Milestone M6: Hybrid Orchestration, Future Accruals & PII Masking
- Hybrid route coordinating RAG and leave data.
- Future leave balance projection (Python arithmetic, not LLM).
- PII masking layer (emails as `r***@veltrix.example`, phones suppressed, disallowed employee names suppressed).
- Prompt injection defenses (corpus treated purely as data).
- Log audit test suite verifying no PII leaks into logs.

### Milestone M7: Integration, Corpus Mutation, Benchmarks & Final Docs
- Mutated corpus test: programmatic modification of policies/holidays and automated verification that answers change.
- End-to-end integration tests covering all routes, status codes, and edge cases.
- `scripts/eval_queries.py` and `scripts/mutate_corpus.py`.
- Documentation deliverables: `README.md`, `DESIGN.md` (<= 2 pages), final ADRs.
- Clean Docker Compose verification.

---

## Risk Analysis & Mitigations
| Risk | Severity | Mitigation Strategy |
|---|---|---|
| Ingestion exceeds 10m Docker startup | Critical | Pre-download embedding model & BPE cache in Docker build; CPU-optimized ONNX runtime; compute hashes to skip re-indexing. |
| Ineligible document leaks into prompt | Critical | Multi-tier filter: Chroma scalar pre-filter + BM25 subset scoring + explicit pre-prompt assert `assert_all_eligible`. Spy LLM tests. |
| Non-deterministic LLM precedence choices | High | LLM only extracts claims and group associations; deterministic Python code resolves precedence and selects winners. |
| Database concurrency / double-spend in leave | High | Explicit `BEGIN IMMEDIATE` transactions in SQLite; compare-and-swap status and atomic balance adjustments. |
| PII leakage in logs or responses | High | Structlog scrubbing filter; strict regex masking for emails/phones; placeholder replacement `[[E1001]]` for names. |
