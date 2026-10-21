# Assumptions & Decisions Ledger

This document tracks all design decisions, interpretations, and assumptions made during implementation. It directly informs the README Assumptions section.

## 1. Reference Dates & Time
- **Default Reference Date**: If `APP_TODAY` environment variable is set, use its value as today's date (`YYYY-MM-DD`). If not set, fall back to the system's local calendar date.
- **Past Date Questions**: If a user asks about a specific past date (e.g., "What was the sick leave allowance in 2025?"), the reference date shifts to the requested date for policy eligibility and precedence resolution.
- **Year-Only Past Queries**: For year-only questions without a specific day (e.g. "What were the policies in 2025?"), resolve at both `YYYY-01-01` and `YYYY-12-31`. If policy values changed mid-year, report both periods.

## 2. Ingestion & Document Precedence
- **Manifest as Source of Truth**: `manifest.json` provides the authoritative `doc_id`, `doc_type`, `regions`, `effective_date`, and `access_level`. Any metadata table or header inside a document is stripped during chunking. If internal document metadata contradicts the manifest, log a warning and adhere strictly to the manifest.
- **Holiday Treatment**: Only standard public holidays listed in the applicable calendar for an employee's region are deducted from working days. Optional, floating, or restricted holidays (if flagged as such) are not auto-deducted unless requested; this is recorded in holiday extraction.
- **Conflict Handling**: If two or more eligible documents with the same authority, scope, and effective date provide differing values for the same rule, the system returns `CONFLICT`, reporting both values and citing both documents without arbitrarily choosing one.

## 3. Leave Rules & Tools
- **Calendar Reference Date for Working Days**: The calendar document applied to compute working days for leave applications is resolved using `APP_TODAY` as the reference date for the requester's region. If calendars conflict or cannot be resolved, the application is rejected with a clear error reason.
- **Calendar Citations in Tool Route**: Per TASK.pdf Section 8.1, route `tool` responses have an empty `citations` list. A configuration flag `CITE_CALENDAR_IN_TOOL_ROUTE` (default: `False`) controls whether the holiday calendar used to compute working days is cited in `tool` route responses.
- **Leave Accrual Projections**: Tools only return current balance. Any inquiry regarding future balances (e.g., "How many days will I have in December?") is handled via the assistant using Python arithmetic (combining current balance + monthly accrual rules from documents - pending/approved leaves) and explicitly shows the math.

## 4. Security & Access Control
- **Identity Trust Boundary**: The `X-Employee-Id` header is the sole authenticated source of identity. Role (`employee`, `manager`, `hr`) and region (`IN`, `US`, `DE`) are loaded directly from the database table `employees`. Any claims in message prompts (e.g. "I am the HR director") are strictly ignored.
- **Fixed Refusal Message**: When an employee requests leave data for a person they are not authorized to view, the system returns the uniform message: `"I can't share information about that employee."` regardless of whether the target ID exists, preventing user enumeration.
- **PII Scrubbing**: Logs never contain employee names, emails, or phone numbers (only employee IDs). Answers mask email addresses (`first char + *** + @domain`) and never include phone numbers.

## 5. Routes and Two-Step Confirmations
- **Strict Route Invariants**:
  - `rag`: >= 1 citations, 0 tool_calls.
  - `tool`: 0 citations, >= 1 tool_calls.
  - `hybrid`: >= 1 citations, >= 1 tool_calls.
  - `clarify`: 0 citations, 0 tool_calls.
  - `no_answer`: 0 citations, 0 tool_calls.
  - `refuse`: 0 citations, 0 tool_calls.
- **Confirmation State**: Write actions (`apply_leave`, `cancel_leave`) are strictly two-step. The first request validates the parameters and sets `pending_confirmation: true` with status `pending_confirmation`. Execution occurs only on an affirmative confirmation ("yes", "confirm", "go ahead") on the immediate next turn. Any parameter change produces a revised proposal; any other prompt clears the proposal.
