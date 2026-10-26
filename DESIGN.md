# Veltrix PeopleOps Assistant - Design Document

## 1. Document Ingestion, Tables, and Scanned OCR
- **Loader Registry**: Keyed by file extension (`.pdf`, `.docx`, `.md`, `.html`, `.csv`). Adding a new format requires only a new subclass of `BaseLoader` registered with `@LoaderRegistry.register(".ext")`.
- **In-Document Table Extraction & Cleaning**:
  - Word documents (`.docx`) are iterated sequentially across body elements (paragraphs and tables) to retain table placement.
  - PDF tables are extracted via `pdfplumber` into Markdown tables, avoiding table fragmentation.
  - In-document metadata headers (Document ID, Scope, Authority, Effective Date) are automatically detected and stripped from body text to prevent hallucinated chunk noise.
  - Holiday tables (`CAL-HOL-*`) are detected and parsed deterministically into SQLite `holidays` table (`date`, `name`, `type`, `region`), enabling calendar math.
- **Scanned Document OCR**:
  - `PyMuPDF` detects whether a PDF page has a text layer. If raw page text is below 50 characters, the page is rendered as an image at 300 DPI and processed through Tesseract OCR (`pytesseract`) with PIL preprocessing (`memo_hybrid_work_update.pdf`).

## 2. Chunking, Embedding, and Retrieval Architecture
- **Chunking with Structural Headers**:
  - Documents are chunked hierarchically (`DocumentChunker`) with token size $\le 400$ tokens (`cl100k_base`) and 50-token overlap.
  - Every chunk prepends document context (`[Document: <title> (<doc_id>) | Section: <heading>]`) to ensure isolated chunks retain document semantics.
- **Dense Vector Search**:
  - ChromaDB embedded `PersistentClient` in cosine space with precomputed embeddings from FastEmbed (`bge-small-en-v1.5`).
  - Chroma telemetry is disabled. Re-indexing is idempotent based on a SHA-256 hash of manifest and file contents.
- **Lexical BM25 Search**:
  - In-process BM25 (`rank_bm25`) indexing SQLite chunks strictly scoped to the employee's accessible universe.
- **Hybrid Fusion & Pre-filters**:
  - Retrieval enforces scalar pre-filtering in Chroma (`access_rank <= employee_rank`, region matching) combined with lexical BM25.
  - Reciprocal Rank Fusion (RRF with $k=60$) merges rankings.
  - Doc-level deduplication limits chunks to at most 2 per document.
  - Greedy packer fits chunks into the 3,000-token LLM context budget (leaving a 200-token buffer).
- **LLM Gateway & Provider Support**:
  - The current implementation supports exclusively the Google Gemini client (`GeminiClient`).
  - `LLMGateway` enforces a hard limit of $\le 3,000$ corpus tokens per request, implements in-memory caching, exponential backoff retries, and latency tracking.

## 3. Section 5 Precedence Engine
- **Deterministic Python Precedence (`PrecedenceResolver`)**:
  - Evaluates chunks based on 3 strict tiers:
    1. **Authority Rank**: `policy (4) > addendum (3) > memo (2) > guide/faq (1)`.
    2. **Scope**: Regional document (`IN`, `US`, `DE`) overrides `GLOBAL` unless marked `mandatory_override: true` or `prohibits_regional_overrides: true`.
    3. **Recency**: Evaluated strictly by `effective_date`. If two policies have different effective dates, future policies are only mentioned if they take effect after `APP_TODAY`.
- **Conflict Management**:
  - If two documents of equal authority conflict without a clear precedence resolution, both are cited with their respective dates and conflicting clauses noted for HR clarification.

## 4. Access Control and Security Enforcement
- **Document Read Permissions**:
  - Enforced in `src/veltrix/retrieval/scope.py` and asserted in `src/veltrix/retrieval/retriever.py` via `assert_all_eligible()`.
  - Ineligible documents are NEVER queried or passed to prompt assembly. No titles or IDs of restricted documents are ever revealed to unauthorized employees.
- **Leave Data Permissions**:
  - Zero LLM bypass: `X-Employee-Id` from HTTP headers is resolved against SQLite `veltrix.db` for role and region.
  - Tools (`get_leave_balance`, `list_leave_requests`, `get_team_leave`, `apply_leave`, `cancel_leave`) enforce permissions inside Python code:
    - Employees can only view/modify their own leave.
    - Managers can only view leave of direct reports.
    - HR / Admins have regional or global visibility.
- **PII Scrubbing**:
  - `src/veltrix/core/pii.py` scrubs SSNs, phone numbers, email addresses, and account numbers from all JSON logs and responses.
  - Verified by comprehensive log audit tests (`tests/security/test_log_audit.py`).

## 5. Failure Modes Found and Fixed
1. **ChromaDB Metadata List Filter Limitation**: Chroma embedded collections cannot filter on list properties (e.g. `regions: ["IN", "GLOBAL"]`). Fixed by flattening regions into scalar flags (`region_IN`, `region_GLOBAL`) and indexing chunks in SQLite for BM25.
2. **Relative Date Resolution**: Standard libraries resolve "next Friday" ambiguously. Built custom `resolve_date_phrase()` using `APP_TODAY` ensuring "next Friday" is always the first Friday after `today`.
3. **Session Deserialization in Async Handlers**: Fixed session state persistence in SQLite `app.db` with pending proposal tracking.

## 6. Scaling to 10,000 Documents
- **What Breaks**:
  1. *In-process BM25*: Loading 100,000+ chunks into RAM for `rank_bm25` will cause memory pressure and high startup latency.
  2. *Single-Worker Chroma*: Chroma embedded does not support multi-worker concurrency.
- **Production Architecture at Scale**:
  1. Replace in-process BM25 and embedded Chroma with a distributed hybrid search engine (e.g. OpenSearch / Elasticsearch with dense vector plugins or Qdrant/Weaviate cluster).
  2. Offload document ingestion to background task workers (Celery/Temporal) streaming chunk events into the index rather than startup batch processing.
  3. Introduce Redis for distributed session caching and proposal locks.
