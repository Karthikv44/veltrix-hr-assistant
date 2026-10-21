# Reference Repository Analysis: `catalog-mcp`

## 1. Directory Layout & Organization
The reference repository `catalog-mcp` follows a standard modern Python package layout:
```text
catalog-mcp/
├── .env.example
├── .gitignore
├── .gitlab-ci.yml
├── .pre-commit-config.yaml
├── .python-version
├── Dockerfile
├── docker-compose.yaml
├── pyproject.toml
├── uv.lock
├── src/
│   └── catalog_mcp_server/
│       ├── __init__.py
│       ├── main.py
│       ├── registry.py
│       ├── psk.py
│       ├── client/
│       ├── config/
│       ├── models/
│       ├── tools/
│       └── utils/
├── tests/
│   ├── conftest.py
│   └── test_*.py
└── scripts/
```
**Adaptation for Veltrix PeopleOps**:
As specified in prompt Section 1 and Section 5, we adopt this clean `src/`-based structure, tailored for our HR Assistant:
`src/veltrix/{api, core, domain, ingestion, retrieval, llm, orchestration, tools, data}`.

## 2. Packaging and `pyproject.toml` Conventions
- **Package Manager**: Exclusively `uv` (`uv add`, `uv sync`, `uv run`, `uv lock`).
- **Build Backend**: `uv_build` (or `hatchling` / standard PEP 621 build backend for uv).
- **Python Version**: Specified via `requires-python = ">=3.12"` and `.python-version` (Python 3.12).
- **Dependency Groups**: Runtime dependencies under `[project.dependencies]`, test and development tooling under `[dependency-groups] dev` (`pytest`, `pytest-asyncio`, `pytest-cov`, `httpx`, `ruff`, `hypothesis`).

## 3. Configuration Handling
- Configuration uses strongly typed models (`pydantic-settings.BaseSettings`) reading from environment variables with `.env` fallback.
- In `catalog-mcp`, settings are centralized in a config module and instantiated once as an immutable or injected container.
- For Veltrix, all environment variables specified in TASK.pdf (`CORPUS_DIR`, `MANIFEST_PATH`, `DB_PATH`, `APP_TODAY`, `LLM_PROVIDER`, etc.) are declared in `veltrix.core.config.Settings`.

## 4. Linting, Typing, and Code Quality Tooling
- **Linter & Formatter**: `ruff` with strict rules (E, F, W, I, B, UP, SIM, C4) configured in `pyproject.toml`.
- Line length: 100-120 characters (120 in reference repo; 100 for clean terminal display).
- Strict typing and docstring standards across domain and orchestration modules.

## 5. Test Layout and Fixtures
- Tests reside in `tests/` with modular organization:
  - `tests/unit/`: fast unit tests for domain logic, precedence, date parsing, token counting.
  - `tests/integration/`: API contract, database transactions, Chroma retrieval, proposed/confirm flow.
  - `tests/security/`: access control matrices, canary injection leakage tests, PII scrubbing verification.
  - `tests/fixtures/`: programmatic document builders (PDF, DOCX, Markdown, HTML, synthetic scan) and DB builders.
- Global fixtures in `conftest.py` provide mock clients, test database sessions, and clock controls.

## 6. Makefile Targets
The reference project relies on automated task execution. For Veltrix PeopleOps:
- `make test`: runs `uv run pytest` (required by TASK.pdf).
- `make lint`: runs `uv run ruff check src tests`.
- `make format`: runs `uv run ruff format src tests`.
- `make check`: runs lint + test gates.
- `make run`: starts the server on port 8000.

## 7. Dockerfile and Compose Conventions
- **Multi-stage build**:
  1. Base stage copying `uv` binary from official `astral-sh/uv` image.
  2. Final stage on `python:3.12-slim` with system apt dependencies (`tesseract-ocr`, `libtesseract-dev`).
  3. Pre-downloading embedding models (`fastembed`) and BPE cache (`tiktoken`) during build into cache directories so container can run fully offline.
- **Compose**:
  - Service named `app` mapping port 8000:8000.
  - Volume mount `./data:/app/data` (read-only safe or mounted to allow testing fresh data).
  - Health check polling `http://localhost:8000/health` returning 200 once ready.

## 8. Logging and Error-Handling Style
- Structured JSON logging using `structlog`.
- Log context enriched with request IDs, employee IDs, routes, token counts, and latencies.
- **PII Scrubbing**: Strict processor scrubbing emails, phones, and names before serializing logs. No raw user message text in logs.
- Centralized exception handlers converting domain exceptions into standardized API responses or HTTP status codes.

## 9. Precedence & Architecture Deviations (ADR Tracking)
Whenever TASK.pdf or Veltrix requirements diverge from `catalog-mcp`, an Architecture Decision Record (ADR) is created in `docs/adr/`.
1. **ADR 0001**: Vector Store Selection & Hybrid Search (Embedded Chroma + in-process BM25 + RRF).
2. **ADR 0002**: Database Access (Standard Library `sqlite3` with Repository Pattern & `BEGIN IMMEDIATE` instead of ORM).
3. **ADR 0003**: Ingestion Pipeline Architecture (Deterministic table/holiday extraction with LLM fallback).
