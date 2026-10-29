# Development Log — AO-03

## Overview

Project AO-03: "The incident is resolved; nobody knows why"
Goal: Provide deterministic, evidence-backed Root Cause Analysis (RCA) answering:
_"What most likely caused this incident, and what evidence proves it?"_

---

## 2026-10-28 — Initial Setup & Architectural Foundation

### 1. Workspace Inspection Findings

- The workspace root `E:\Hackmitten3.0` was inspected prior to initialization and found completely empty.
- No organizer telemetry (logs, metrics, traces, configs, deployments, fault injection harness) was provided.
- Strict constraint adhered: No fabricated organizer data. Future organizer data must be ingesta-compatible via generic ingestion adapters.

### 2. Architectural Design Decisions

- **Deterministic Core as Ground Truth**: The RCA scoring engine relies on deterministic telemetry evidence.
- **LLM as Summarizer / Explainer Only**: The LLM receives an explicit, verified `InvestigationPacket` containing strictly referenced Evidence IDs. All LLM findings are labeled `"HYPOTHESIS — NOT A VERIFIED FINDING"`.
- **Insufficient Evidence Guarantee**: If data is incomplete or below confidence threshold, the system explicitly returns `UNKNOWN / INSUFFICIENT EVIDENCE`.
- **Dual-Storage Strategy**: PostgreSQL/Supabase schema provided (`migrations/001_initial_schema.sql`) alongside zero-setup embedded SQLite storage.
- **Separated Demo Fixtures**: Synthetic/demo records are isolated under `app/ingestion/demo_fixtures.py` and strictly tagged with `source_type="SYNTHETIC_DEMO"`.

---

## 2026-10-28 — Phase 2: Engine Implementation & Full End-to-End Verification

### 1. Normalized Internal Evidence Model

- Extended `NormalizedEvidence` with first-class support for:
  `id`, `incident_id`, `source_type`, `timestamp`, `service` (with `service_id` alias), `severity`, `event_type`, `message`, `summary`, `trace_id`, `span_id`, `parent_span_id`, `request_id`, `deployment_id`, `configuration_id`, `metric_name`, `metric_value`, `source_file`, `source_record`, `redacted`, `anomaly_score`, `details`, and `metadata`.
- Added `EvidenceCorrelation` model to capture explicit causal relationships between evidence items with human-readable rationale.

### 2. Universal Ingestion Pipeline

- Implemented `GenericTelemetryIngestor` in `app/ingestion/generic_adapter.py`.
- Supports JSON arrays/objects, JSONL line-delimited records, and CSV text.
- Added `SchemaMapping` for flexible column mapping from future organizer formats.
- Implemented graceful error isolation: malformed records are recorded in `IngestionReport.errors` without crashing the entire batch (`PARTIAL_SUCCESS`).

### 3. Multi-Factor Deterministic Correlation & Scoring Engine

- Implemented all 9 correlation mechanisms in `app/engine/correlation.py`:
  1. Time proximity ($\Delta t \le 180\text{s}$)
  2. Same service co-occurrence
  3. Distributed trace / request match (`trace_id` / `request_id`)
  4. Span parent-child hierarchy (`span_id == parent_span_id`)
  5. Topological dependency propagation
  6. Error / trace fault cascade
  7. Deployment proximity
  8. Configuration drift proximity
  9. Metric anomaly / error surge co-occurrence
- Implemented 8-factor weighted scoring termed strictly **"Evidence Score"** (never probability):
  Temporal Precedence (15%), Dependency Relevance (15%), Anomaly Magnitude (15%), Error Surge (15%), Trace Correlation (10%), Deployment Proximity (10%), Configuration Proximity (10%), Blast Radius (10%).
- Implemented direct causal evidence gating: zero causal signals force score to 0.0.

### 4. Insufficient & Conflicting Evidence Guardrails

- If no telemetry exists $\rightarrow$ `UNKNOWN / INSUFFICIENT EVIDENCE`.
- If top candidate evidence score $< 0.35$ $\rightarrow$ `UNKNOWN / INSUFFICIENT EVIDENCE`.
- If two independent candidates have nearly identical ambiguous scores with no causal link $\rightarrow$ `UNKNOWN / INSUFFICIENT EVIDENCE`.

### 5. Dependency Graph & Trace Inference

- Added `infer_dependencies_from_traces` to discover caller $\rightarrow$ callee edges directly from trace spans.
- Enriched `get_incident_graph` with suspected root, affected, upstream, and downstream classifications.

### 6. Verification & Test Suite

- Built 9 dedicated test scenarios in `tests/test_scenarios.py`.
- All 24 unit and integration tests passing (`pytest tests/ -v`).
- All 12 REST API endpoints verified live against the running Flask application.

---

## 2026-10-28 — Phase 3: Connected SRE Dashboard, Proof Chain & Acceptance

### 1. Connected Investigation Flow

- Completed full integration across all layers:
  `Dashboard -> Select Incident -> Investigate -> Evidence Collection -> Correlation -> Root Cause Ranking -> Evidence Proof -> Timeline -> Service Dependency Graph -> AI Hypothesis -> Alternative Causes -> Evaluation`.
- Single data layer: Local SQLite at `data/ao03_telemetry.db` (with dual-storage support for Supabase). Zero disconnected or fake mock UI elements.

### 2. UI Ground-Truth Alignment: "Evidence Before Explanation"

- Repositioned the AI Hypothesis panel strictly below deterministic evidence ranking and candidate proof drawers.
- Updated disclaimer banner across templates, LLM prompts, and engines to:
  `"AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING"`.
- Implemented expandable evidence drawers showing the full verification chain:
  `CLAIM -> EVIDENCE -> SOURCE (Timestamp, Service, Type, Trace ID, Commit/Config ID, Metadata)`.
- Added Chart.js "Why This Cause?" score attribution chart showing weights and mathematical factor contributions.
- Built interactive SVG service dependency graph with root, affected, and upstream node badges and click-to-filter capability.
- Added dedicated Contradicting Evidence section.

### 3. Evaluation & Benchmarking

- Added Evaluation tab in dashboard calculating real evidence coverage (100%) and mean investigation latency (~140ms).
- Honestly reports `Ground truth not loaded` for Top-1 / Top-3 / MRR until labeled ground-truth datasets are imported.

### 4. Security & Redaction

- Implemented `EvidenceValidator.redact_sensitive_data` stripping Bearer tokens, authorization headers, passwords, secrets, and JWTs.
- Created `.gitignore` preventing accidental commitment of `.env` or local telemetry databases.

### 5. Automated Demo & Acceptance Verification

- Created `scripts/demo_check.py` validating all 13 pipeline stages:
  Database -> Dataset -> Ingestion -> Evidence -> Correlation -> Ranking -> Timeline -> Graph -> LLM -> Evidence Validation -> API Endpoints -> End-to-End Investigation -> Unknown Scenario.
- All 24 automated pytest tests passing (`pytest tests/ -v`).
- Verified live on local instance at `http://127.0.0.1:5000/`.

---

## 2026-10-28 — Phase 4: Role-Based Access Control (RBAC) & Authentication (Step 1)

### 1. Three Core Roles Enforced

- **`ADMIN`**: Complete administrative authority, user provisioning, role alteration, audit log review, telemetry ingestion, and demo fixture resets.
- **`INCIDENT_RESPONDER` (SRE)**: Operational access to investigations, deterministic RCA triggering, graph topologies, chronological timeline, and read-only telemetry. User/role management and telemetry tampering are blocked.
- **`VIEWER` (Auditor)**: Read-only access to dashboard summaries, incident lists, RCA outputs, and timelines. Raw telemetry payloads are sanitized/restricted; triggering new RCA runs and admin routes return `403 Forbidden`.

### 2. Authentication & Session Infrastructure

- Added `User` and `AuditLog` domain models (`app/models/user.py`, `app/models/audit.py`).
- Implemented secure password hashing via `werkzeug.security` (scrypt key derivation) with zero plaintext storage.
- Added session handling (`app/auth/session.py`) utilizing signed, HTTP-only server cookies.
- Added reusable backend authorization decorators (`app/auth/decorators.py`):
  - `@login_required` (emits `401 Unauthorized` on missing session).
  - `@role_required(*roles)` (emits `403 Forbidden` and records `UNAUTHORIZED_ACCESS` audit event).

### 3. Database & Storage Architecture Integrity

- Retained local SQLite as the active database (`data/ao03_telemetry.db`).
- Added `users` and `audit_logs` tables to `SqliteStorage` with automatic schema creation and demo seeding:
  - `admin` (`ADMIN`)
  - `sre_responder` (`INCIDENT_RESPONDER`)
  - `auditor_viewer` (`VIEWER`)
- Implemented delegation stubs in `SupabaseStorage` pointing to `self.fallback`, keeping the Supabase adapter fully compatible and ready for Step 2.

### 4. Immutable Security Audit Logging

- Implemented `app/auth/audit.py` recording `LOGIN`, `LOGOUT`, `FAILED_LOGIN`, `UNAUTHORIZED_ACCESS`, `RUN_RCA`, `CREATE_USER`, `UPDATE_ROLE`, and `INGEST_TELEMETRY`.
- Strict sanitization guardrail scrubs passwords, tokens, API keys, and secrets from audit metadata before writing to disk.

### 5. Frontend & UI Integration

- Created `app/static/js/auth.js` for session checking, login modal handling, quick demo role switching, user profile badge, and dynamic navigation tab toggles.
- Built Tab 5 in `index.html`: Admin User Management (provisioning, role switching, disabling accounts) and Security Audit Log table with action filters.
- Added CSS styling in `app/static/css/style.css` for auth cards, quick demo credentials buttons, and role badges.

### 6. Automated Testing & Verification

- Created `tests/test_rbac.py` with 11 comprehensive tests validating unauthenticated blocking, admin management, responder access, responder restrictions, viewer access, viewer bypass prevention, telemetry redaction, session invalidation, password hashing, and audit logging.
- Pytest test suite expanded from 24 to 35 tests: **35/35 PASSED** (`pytest tests/ -v`).
- System acceptance test suite: **13/13 PASSED** (`scripts/demo_check.py`).

---

## 2026-10-28 — Phase 5: Supabase PostgreSQL Storage Integration (Step 2)

### 1. Unified Dual-Backend Storage Architecture

- Enhanced storage abstraction in `app/storage/base.py` and implemented full PostgreSQL PostgREST operations in `app/storage/supabase_adapter.py`.
- Strict database backend selection via `DATABASE_BACKEND=supabase` or `DATABASE_BACKEND=sqlite` (with fallback to `STORAGE_BACKEND`).
- Strictly enforced non-silent failure: When `DATABASE_BACKEND=supabase`, storage raises `ConnectionError` on authentication failure (401/403) or missing credentials, preventing silent reversion to SQLite.
- SQLite remains available as an explicitly selectable offline/testing database (`DATABASE_BACKEND=sqlite`).

### 2. PostgreSQL Schema Definition & RLS

- Created `supabase/migrations/001_initial_schema.sql` (and synchronized `migrations/001_initial_schema.sql`).
- Defines all 10 core tables: `services`, `dependencies`, `incidents`, `evidence`, `candidates`, `analysis_runs`, `timeline_events`, `evaluation_ground_truth`, `users`, and `audit_logs`.
- Established foreign key cascades, performance indexes, and PostgreSQL Row Level Security (RLS) policies.

### 3. Data Migration Utility & Parity Audit

- Created `scripts/migrate_sqlite_to_supabase.py` using idempotent PostgREST upserts (`Prefer: resolution=merge-duplicates`).
- Automated data parity validation comparing row counts across SQLite and Supabase for all 10 entities.

### 4. Diagnostics & Credential Protection

- Added `/api/diagnostic` and enhanced `/api/health` to expose active database backend, connection health, and masked project URL without exposing API keys or secrets.
- Enforced credential hygiene: `.env` is git-ignored, all secrets are kept out of source code, tests, and documentation.
- Created `tests/test_supabase.py` with 6 automated tests verifying environment loading, credential protection, connection validation, non-silent failure, backend selection, and JSONB payload mapping.
- All 42 pytest tests pass (`pytest tests/ -v`).

---

## 2026-10-28 — Phase 6: Step 3 Final Hackathon Hardening & Demo Readiness

### 1. Complete End-to-End Workflow Verification

- Verified full pipeline from User Login $\rightarrow$ Dashboard $\rightarrow$ Incident Registry $\rightarrow$ Selection $\rightarrow$ Evidence Retrieval $\rightarrow$ Correlation $\rightarrow$ Candidate Ranking $\rightarrow$ Timeline $\rightarrow$ Service Graph $\rightarrow$ AI Hypothesis $\rightarrow$ Persist Results $\rightarrow$ Return to Overview.
- All telemetry and dashboard statistics dynamically reflect actual remote Supabase PostgreSQL storage (zero mock or hardcoded statistics).

### 2. LLM Provider Independence & Safety Guardrails

- Reinforced the core prompt constraint: `"EVIDENCE BEFORE EXPLANATION: All explanations must be strictly anchored in verified telemetry evidence."`
- Verified graceful fallback: When the local Ollama instance is unavailable, the system defaults to the deterministic template provider (`app/llm/heuristic_provider.py`) without crashing, displaying `"LLM explanation unavailable — deterministic evidence analysis is still available"`.
- Verified that all cited evidence references are validated post-generation via `EvidenceValidator.validate_llm_hypothesis` to strip hallucinations.
- All outputs display the mandatory header: `"AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING"`.

### 3. Evaluation Page Honesty

- Updated the Ground-Truth Benchmark view (`app/templates/index.html` and `app/static/js/app.js`) to display `"Pending organizer ground truth"` for Top-1, Top-3, MRR, and Unknown metrics while keeping measured metrics (Evidence Coverage, Latency) real and verified.

### 4. Full Automated Acceptance & Verification

- Ran automated test suite: **42/42 PASSED** (`python -m pytest tests/ -v`).
- Ran system demo acceptance suite: **13/13 PASSED** (`python scripts/demo_check.py`).
- Performed live HTTP E2E tests against local server at `http://127.0.0.1:5000`: Verified login, diagnostics, incident registry, telemetry, deterministic RCA, unknown scenario handling, RBAC restrictions, and logout.
- Queried remote Supabase instance and verified live counts: `services`: 6, `dependencies`: 5, `incidents`: 4, `evidence`: 17, `candidates`: 6, `timeline_events`: 16, `analysis_runs`: 55, `users`: 3, `audit_logs`: 38.

---

## 2026-10-28 — Phase 7: Frontend Auth Synchronization & Connection Resilience

### 1. Root Cause Identification for "Zeros and API Connection Error"

- **Auth Session Modal Suppression**: On initial page load, `GET /api/auth/me` returns HTTP 200 with `{ "authenticated": false, "user": null }`. The frontend code checked `res.ok` (which was `true` on 200) and unconditionally called `hideLoginModal()`, concealing the login dialog from unauthenticated users.
- **Unauthenticated Fetch Race Condition**: Simultaneously, `App.init()` fired `loadStats()` and `loadIncidents()`. Because no session cookie existed yet, protected endpoints returned HTTP 401 Unauthorized.
  - `loadStats()` defaulted `undefined` statistics to `0`, displaying 0s on all dashboard summary cards.
  - `loadIncidents()` received an error JSON object; attempting to spread `[...this.allIncidents]` threw `TypeError: this.allIncidents is not iterable`, triggering the catch block banner `"Error connecting to incidents API"`.
- **Post-Login Partial Refresh**: Upon authenticating, only `loadDashboard()` was called, leaving investigation dropdowns and evidence explorers unpopulated until manual navigation.
- **Supabase PostgREST Connection Latency**: Individual REST requests created brand new TCP/TLS handshakes with a tight 5s timeout, occasionally triggering `ReadTimeoutError` during bursts of sequential queries.

### 2. Solutions Implemented

- **Explicit Auth State Handling**: Updated `Auth.checkAuth()` to verify `data.authenticated && data.user`. If unauthenticated, it keeps `currentUser = null` and explicitly displays `showLoginModal()`.
- **Robust Error & Auth States**:
  - `loadStats()` now checks `res.ok`. On 401, it sets cards to `—` rather than overwriting with zeros.
  - `loadIncidents()` checks `res.ok` and `Array.isArray(data)`. On 401, it renders a friendly `"AUTHENTICATION REQUIRED"` banner with an inline Sign In button.
- **Centralized Data Refresh**: Introduced `App.loadAllData()`, which atomically updates dashboard statistics, incident registries, service filters, investigation dropdowns, and evidence explorers upon login or role switch.
- **Session Credentials & Cache Busting**: Explicitly added `credentials: 'same-origin'` to all frontend `fetch()` requests and added `?v=1.0.1` cache-busting query strings to all `<script>` tags in `app/templates/index.html`.
- **Supabase Adapter Connection Pooling**: Updated `SupabaseStorage` to utilize a persistent `requests.Session()` with HTTP Keep-Alive connection reuse, dropping query latency from ~3.2s to 0.3s (10x speedup) and increasing timeout to a resilient 15s.

---

## 2026-10-28 — Phase 8: Master Stabilization, Full-Stack Repair, Performance Optimization & Acceptance

### 1. Critical Issue A & B: Unauthenticated Gate & Role-Isolated History State Machine

- **Unauthenticated Gate Screen**: Added `#tab-unauthenticated` in `app/templates/index.html`. Unauthenticated visitors are greeted with a clear authentication gate with zero protected requests dispatched and zero metric leakage.
- **Role-Isolated Centralized Navigation Controller**: Implemented `Navigation` in `app/static/js/app.js` with strictly enforced `PERMITTED_TABS` for `ADMIN`, `INCIDENT_RESPONDER`, and `VIEWER`.
- **HTML5 History API & Single Routing**: Integrated `history.pushState`, `popstate`, and clean hash routes (`#/dashboard`, `#/investigation`, `#/explorer`, `#/evaluation`, `#/admin`). Browser Back and Forward cleanly navigate between valid permitted views without switching roles or resetting to Admin Home.
- **One-Click Event Delegation**: Replaced brittle element-level tab bindings with single event delegation on `.nav-tabs` to guarantee instant first-click navigation regardless of child icon clicks or in-flight requests.
- **Dynamic Action Restrictions**:
  - `ADMIN`: Full access to all tabs, user management, audit logs, data reset, demo loading, and telemetry ingestion.
  - `INCIDENT_RESPONDER`: Full access to investigation, evidence, timeline, graph, RCA, and audit trail; blocked from user management (403) and data reset (403). Non-admin users on `#tab-admin` are cleanly redirected to `#tab-dashboard`.
  - `VIEWER`: Strictly read-only; blocked from RCA execution (403), telemetry ingestion (403), user management (403), and raw unredacted evidence inspection (403).

### 2. Critical Issue C & D: Frontend Race Conditions & Debounce Protection

- **Investigation Parallelization**: Converted sequential waterfall in `selectIncident()` into `Promise.all([fetchIncident, fetchEvidence, fetchGraph, fetchRCA])` with `AbortController` cancellation for fast tab switching.
- **Debounce Guard on RCA**: Added `isAnalyzing` debounce flag in `investigation.js` to disable the "Run RCA Analysis" button during execution and display spinner text ("Analyzing..."), preventing duplicate submissions.
- **HTTP Error Semantics**: Differentiated 401 (Authentication required), 403 (Forbidden), 404 (Not found), and 5xx. Zero silent empty fallbacks.

### 3. Critical Issue F: Performance Bottleneck Elimination

- **Evidence Count Aggregation**: Declared and implemented `get_evidence_count()` in `BaseStorage`, `SupabaseStorage`, and `SqliteStorage`. Replaced the previous 1000-row table scan in `/api/stats` with a PostgREST `Prefer: count=exact` header.
- **Batch Analysis Runs Mapping**: Declared and implemented `get_latest_analysis_runs_map()` to batch fetch the most recent analysis run across all incidents in a single query, eliminating the N+1 loop in `/api/incidents` and `/api/evaluation`.
- **Batch Candidate Pre-fetching**: Declared and implemented `get_all_candidates()` to batch retrieve candidate causes across all incidents in one query, cutting `/api/evaluation` round-trips from 8 sequential queries down to 2.
- **Performance Measurement Results**:
  - `/api/incidents`: Reduced from **2561.9 ms** to **909.7 ms** (**64.5% reduction**).
  - `/api/evaluation`: Reduced from **5197.0 ms** to **1305.5 ms** (**74.9% reduction**).
  - `/api/incidents/INC-2026-001/evidence`: Reduced from **1497.4 ms** to **704.5 ms** (**53.0% reduction**).
  - `/api/diagnostic`: **2.7 ms** (Status: 200).

### 4. Comprehensive Full-Stack Verification

- **Automated Regression Suite**: **42/42 PASSED** (`python -m pytest tests/ -v`).
- **System Acceptance Suite**: **13/13 PASSED** (`python scripts/demo_check.py`).
- **Live Multi-Role Verification Suite**: **ALL SCENARIOS PASSED** (`scratch/verify_all_scenarios.py`):
  - Scenario A: Fresh unauthenticated user blocked with 401 across all 8 protected endpoints.
  - Scenario B: Admin login, stats, user management, audit logs, and RCA confirmed.
  - Scenario C: Incident Responder permitted investigation verified; admin endpoints return 403; role remains strictly `INCIDENT_RESPONDER`.
  - Scenario D: Viewer read-only verified; sensitive payloads redacted; state-changing endpoints return 403.
  - Scenario E: Logout invalidates session cookie; subsequent requests return 401.
- **Live Database Integrity**: Supabase PostgreSQL tables verified intact:
  - `services`: 9
  - `incidents`: 7
  - `candidates`: 3
  - `evidence`: 24
  - `users`: 4 (including verified test account)
  - `audit_logs`: 129 (immutable trail of all verified actions)

---

## 2026-10-28 — Phase 9: Every-Tab Audit, Navbar State Synchronization & UI Polish

### 1. Navbar Identity & Session State Synchronization

- **Root Cause**: When an API request returned HTTP 401 Unauthorized (e.g., during session expiration or unauthenticated browsing), the UI rendered an inline "Authentication Required" card, but `Auth.currentUser` and `#user-profile-badge` were not synchronously cleared. Consequently, the navbar could retain a stale `admin` badge and Logout button while the page indicated unauthenticated state.
- **Fix**:
  - Added `Auth.handleUnauthorized()` in `app/static/js/auth.js` to synchronously set `currentUser = null`, clear username and role spans, hide `#user-profile-badge`, display `#btn-show-login`, hide `#nav-btn-admin`, invoke `Navigation.showUnauthenticatedGate()`, and pop up the login modal with a toast notification.
  - Linked all 401 responses in `app.js` (`loadStats`, `loadIncidents`, `loadEvaluation`, `loadServicesList`), `explorer.js` (`loadEvidence`), and `investigation.js` (`populateIncidentsDropdown`, `selectIncident`, `executeRCA`) directly to `Auth.handleUnauthorized()`.
  - Removed stale initial `active` class on `#nav-btn-dashboard` in `app/templates/index.html` so no tab is erroneously highlighted when `#tab-unauthenticated` is active.

### 2. Dark Theme Form & Input Polish

- **Root Cause**: Inputs in the login modal and user provisioning form had class `filter-input`, which was undefined in `app/static/css/style.css`, causing browsers to render jarring default white inputs that clashed with the TraceWise dark aesthetic.
- **Fix**: Added comprehensive dark theme input styling in `style.css` for `.form-input` and `.filter-input`, including deep-dark backgrounds (`rgba(10, 11, 15, 0.92)`), subtle borders (`rgba(255, 255, 255, 0.14)`), white high-contrast text, sleek inner shadows, orange focus rings (`box-shadow: 0 0 0 3px rgba(255, 97, 41, 0.25)`), and muted placeholders.

### 3. Every-Tab Full Audit Matrix Verification

- Created and executed `scratch/test_every_tab_and_control.py` covering 54 discrete test assertions across all 5 tabs and 3 roles:
  - **Diagnostic & Security**: Public diagnostic is healthy on Supabase with zero leaked secrets.
  - **Auth Cycle**: Unauthenticated access blocked (401), invalid credentials rejected, session intact.
  - **Tab 1 (Dashboard)**: Real Supabase statistics, incident registry, service topology.
  - **Tab 2 (Investigation)**: Incident details, evidence, SVG dependency graph, chronological timeline, deterministic RCA on `INC-2026-001` (Score: 0.917), honest unknown on `INC-2026-002` (`INSUFFICIENT_EVIDENCE`).
  - **Tab 3 (Evidence Explorer)**: Raw telemetry list, deep evidence inspection for Admin.
  - **Tab 4 (Evaluation & Benchmark)**: Real benchmark ground-truth view and coverage calculation.
  - **Tab 5 (Admin & Audit)**: User provisioning, role update, status disabling, security audit trail.
  - **Role Restrictions**: SRE Responder strictly blocked (403) from user admin and demo reset; Viewer strictly blocked (403) from RCA execution, deep evidence inspection, user admin, and ingestion.
  - **Logout Cycle**: Session invalidated, subsequent calls return 401.
- **Outcome**: **54/54 CHECKS PASSED** (100% pass rate).
- **Regression Tests**: **42/42 pytest tests passed**, **13/13 demo checks passed**.
