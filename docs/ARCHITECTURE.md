# Architecture Specification — TraceWise AO-03

## 1. System Vision & Core Product Philosophy

> **"Evidence Before Explanation"**

TraceWise AO-03 solves the critical SRE post-incident challenge: _"The incident is resolved; nobody knows why."_
Rather than relying on ungrounded generative LLM guesses, TraceWise implements a **strictly deterministic, evidence-backed Root Cause Analysis pipeline**. Every claim is proven by concrete telemetry, and AI is employed solely as an explanation summarizer of pre-validated evidence.

```
+-----------------------------------------------------------------------------------------+
|                                    TraceWise AO-03                                      |
+-----------------------------------------------------------------------------------------+
|                                                                                         |
|  +--------------------+       +----------------------+       +-----------------------+  |
|  |   Heterogeneous    |       |  Generic Ingestion   |       |  Normalized Telemetry |  |
|  | Telemetry Sources  | ----> |       Adapters       | ----> |    Storage Layer      |  |
|  | (Logs, Metrics,    |       | (JSON / JSONL / CSV) |       | (SQLite / PostgreSQL) |  |
|  |  Traces, Configs)  |       +----------------------+       +-----------------------+  |
|  +--------------------+                                                  |              |
|                                                                          v              |
|  +-----------------------------------------------------------------------------------+  |
|  |                            DETERMINISTIC RCA ENGINE                               |  |
|  |                                                                                   |  |
|  |   1. Topology Graph & Trace-Inferred Dependencies (NetworkX DAG)                  |  |
|  |   2. Multi-Factor Evidence Correlation (9 Correlation Channels)                   |  |
|  |   3. Dynamic Candidate Cause Generation (Derived from Evidence)                   |  |
|  |   4. Deterministic Evidence Scoring (8-Factor Weighted Formula)                   |  |
|  |   5. Insufficient / Conflicting Evidence Guardrails (< 0.35 -> UNKNOWN)           |  |
|  |   6. Chronological Incident Timeline Generation                                   |  |
|  +-----------------------------------------------------------------------------------+  |
|                                         |                                               |
|                                         v                                               |
|  +-----------------------------------------------------------------------------------+  |
|  |                     EVIDENCE VALIDATION & REDACTION LAYER                         |  |
|  |                                                                                   |  |
|  |   - Secret Redaction: API keys, bearer tokens, passwords scrubbed                 |  |
|  |   - Ground-Truth Integrity: Only verified Evidence IDs reach LLM packet           |  |
|  +-----------------------------------------------------------------------------------+  |
|                                         |                                               |
|                                         v                                               |
|  +-----------------------------------------------------------------------------------+  |
|  |                        BOUNDED LLM EXPLANATION LAYER                              |  |
|  |                                                                                   |  |
|  |   - Local Ollama LLM with Offline Heuristic Fallback                               |  |
|  |   - Strict Output Header: "AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING"     |  |
|  |   - Hallucination Gating: Any ungrounded evidence ID citation is stripped         |  |
|  +-----------------------------------------------------------------------------------+  |
|                                         |                                               |
|                                         v                                               |
|  +-----------------------------------------------------------------------------------+  |
|  |                       SRE OPERATIONAL DASHBOARD (UI)                              |  |
|  |                                                                                   |  |
|  |   [Dashboard] -> [Investigate] -> [Evidence Proof] -> [Attribution Chart]        |  |
|  |   -> [Timeline] -> [Topology DAG] -> [AI Hypothesis] -> [Evaluation]              |  |
|  +-----------------------------------------------------------------------------------+  |
|                                                                                         |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Ingestion & Storage Architecture

### Multi-Format Generic Ingestor

Implemented in `app/ingestion/generic_adapter.py`:

- Parses raw JSON arrays, JSON objects, line-delimited JSON (JSONL), and CSV spreadsheets with automatic header sniffing.
- `SchemaMapping`: Translates custom organizer telemetry keys (e.g. `@timestamp`, `service_name`, `req_id`) into the standardized internal `NormalizedEvidence` contract.
- Graceful error isolation: Malformed individual records do not abort batch ingestion (`PARTIAL_SUCCESS`).

### Dual-Storage Adapter Pattern

Implemented in `app/storage/`:

- `BaseStorage`: Abstract storage interface defining contracts for incidents, services, dependencies, evidence, candidates, and analysis runs.
- `SqliteStorage` (`app/storage/sqlite_adapter.py`): Zero-setup local relational storage at `data/ao03_telemetry.db`.
- `SupabaseStorage` (`app/storage/supabase_adapter.py`): Managed PostgreSQL integration via Supabase REST API and raw SQL migration (`migrations/001_initial_schema.sql`).

---

## 3. Deterministic RCA & Scoring Engine

### 9 Multi-Factor Correlation Rules

1. **Time Proximity**: Events co-occurring within a 180s sliding causal window.
2. **Service Co-occurrence**: Correlating error spikes with local changes on the same service node.
3. **Trace / Request Linkage**: Correlating spans sharing exact `trace_id` or `request_id`.
4. **Parent-Child Span Propagation**: Tracing caller-callee latency cascades.
5. **Topological Dependency Propagation**: Tracing faults along upstream/downstream graph edges.
6. **Fault Propagation / Cascade**: Correlating child service failures with parent timeouts.
7. **Deployment Proximity**: Linking service errors to recent release commits.
8. **Configuration Drift Proximity**: Linking runtime anomalies to recent config alterations.
9. **Metric Anomaly & Error Surge**: Synchronized z-score metric spikes and HTTP 5xx log surges.

### 8-Factor Deterministic Scoring Formula

Every candidate cause is scored on an **Evidence Score** scale $[0.0, 1.0]$:
$$\text{Evidence Score} = \sum_{i=1}^{8} w_i \times s_i$$

- **Temporal Precedence** ($w_1 = 0.15$): Did the cause precede observed downstream failures?
- **Dependency Relevance** ($w_2 = 0.15$): Is the candidate topologically connected to affected services?
- **Anomaly Magnitude** ($w_3 = 0.15$): Statistical severity (p99 latency / resource saturation).
- **Error Surge** ($w_4 = 0.15$): Volume of associated error logs.
- **Trace Correlation** ($w_5 = 0.10$): Distributed trace spans directly proving execution path failure.
- **Deployment Proximity** ($w_6 = 0.10$): Release deployed within causal window.
- **Configuration Proximity** ($w_7 = 0.10$): Config change deployed within causal window.
- **Blast Radius** ($w_8 = 0.10$): Breadth of upstream affected services.

_Causal Gating Rule_: If a candidate has zero causal indicators, its score is hard-clamped to `0.0`.

### Insufficient & Conflicting Evidence Guardrails

- If no telemetry records exist: returns `status = "INSUFFICIENT_EVIDENCE"`.
- If top candidate evidence score $< 0.35$: returns `UNKNOWN / INSUFFICIENT EVIDENCE` without forcing a false cause.
- If two independent root services have near-identical ambiguous scores without causal precedence: returns `UNKNOWN / INSUFFICIENT EVIDENCE`.

---

## 4. Chronological Timeline & Topological DAG

### Timeline Engine (`app/engine/timeline.py`)

- Sorts normalized evidence chronologically.
- Enriches every event with its source type, severity, and exact database `evidence_id` reference.
- Ensures the user can click any event in the UI to inspect the underlying raw record.

### Service Dependency DAG (`app/engine/dependency_graph.py`)

- Powered by NetworkX directed graph representation.
- Automatically infers undeclared service dependencies from distributed trace spans (parent span service $\rightarrow$ child span service).
- Emits topological graph payload classifying nodes as `is_root`, `is_affected`, `is_upstream`, and `is_downstream`.

---

## 5. Security & LLM Grounding Guardrails

### Sensitive Data Redaction (`EvidenceValidator.redact_sensitive_data`)

Before any telemetry or summary is presented to the LLM or external interfaces:

- Bearer tokens are scrubbed (`Bearer [REDACTED]`).
- Authorization headers are sanitized (`Authorization: [REDACTED]`).
- Passwords, secrets, and API keys are redacted (`password=[REDACTED]`).
- JWT tokens are replaced with `[REDACTED_JWT]`.

### Grounded Investigation Packet

- The LLM receives only a pre-filtered `InvestigationPacket` containing verified `NormalizedEvidence` records for the specific incident.
- LLM outputs are checked by `EvidenceValidator.validate_llm_hypothesis`.
- Any cited evidence ID not present in the incident's active evidence set is rejected as a hallucination.
- All LLM hypotheses carry the mandatory prominent banner:
  **"AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING"**.

---

## 6. Frontend Presentation Architecture

- **Stack**: Vanilla HTML5, modern CSS3 (Custom Properties, dark SRE observability theme), and Vanilla ES6+ JavaScript.
- **Zero Heavy Frameworks**: No React, Vue, or Angular bloat.
- **Visual Evidence Flow**:
  1. Top stats bar (6 real-time metrics).
  2. Incident Registry with real-time multi-criteria filtering (search, severity, status, service, sort).
  3. Investigation View:
     - Root Cause Candidate selector & Score Attribution Bar Chart (Chart.js).
     - **Evidence Proof Drawer**: Every claim displays its `CLAIM -> EVIDENCE -> SOURCE` chain.
     - Separate Contradicting Evidence section.
     - Interactive Clickable Chronological Timeline.
     - Interactive SVG Service Dependency Graph with node selection and evidence cross-linking.
     - AI Hypothesis Card with clickable cited evidence chips.
  4. Evidence Explorer: Searchable raw records with full JSON modal inspection.
  5. Evaluation & Benchmark: Honest display of benchmark coverage, investigation latency, and ground-truth readiness.

---

## 7. Role-Based Access Control (RBAC) & Security Architecture

### Authentication & Session Lifecycle

- **Session Transport**: Flask server-side session signed with `SECRET_KEY`, transmitted via HTTP-only, SameSite secure cookies.
- **Credential Storage**: Passwords are never stored in plaintext. Hashing is performed using `werkzeug.security.generate_password_hash` with modern scrypt / pbkdf2 key derivation.
- **Seeded Demo Accounts**:
  - `admin`: Role `ADMIN`, password set via `ADMIN_DEFAULT_PASSWORD` (default: `Admin!Pass2026`).
  - `sre_responder`: Role `INCIDENT_RESPONDER`, password set via `SRE_DEFAULT_PASSWORD` (default: `Sre!Pass2026`).
  - `auditor_viewer`: Role `VIEWER`, password set via `VIEWER_DEFAULT_PASSWORD` (default: `Viewer!Pass2026`).

### Backend Authorization Helpers & Decorators

- `@login_required`: Verifies active user session. Returns `401 Unauthorized` (`{"error": "Authentication required"}`) for unauthenticated requests.
- `@role_required(*allowed_roles)`: Verifies role membership against allowed roles. Returns `403 Forbidden` (`{"error": "Action forbidden: Your role (X) does not have permission..."}`) and automatically emits an `UNAUTHORIZED_ACCESS` audit event.

### Role Permission Matrix

| Operation / Endpoint                           | Minimum Role         | Enforced Route                                                                                                        |
| ---------------------------------------------- | -------------------- | --------------------------------------------------------------------------------------------------------------------- |
| View Dashboard / Incidents / Timeline / Graph  | `VIEWER`             | `GET /api/stats`, `GET /api/incidents/*`                                                                              |
| View Filtered Evidence Summaries               | `VIEWER`             | `GET /api/evidence` (Sanitized payload)                                                                               |
| Inspect Raw Telemetry Record                   | `INCIDENT_RESPONDER` | `GET /api/evidence/<id>`                                                                                              |
| Run Root Cause Analysis (Deterministic + LLM)  | `INCIDENT_RESPONDER` | `POST /api/incidents/<id>/analyze`                                                                                    |
| Ingest Production Telemetry                    | `ADMIN`              | `POST /api/ingest`                                                                                                    |
| Load Synthetic Demo Fixtures / Reset Telemetry | `ADMIN`              | `POST /api/demo/load`, `POST /api/demo/reset`                                                                         |
| User Provisioning & Role Management            | `ADMIN`              | `GET /api/admin/users`, `POST /api/admin/users`, `PUT /api/admin/users/<id>/role`, `PUT /api/admin/users/<id>/status` |
| Security Audit Trail Inspection                | `ADMIN`              | `GET /api/admin/audit-logs`                                                                                           |

### Telemetry Protection & Redaction Flow

1. **Raw Telemetry Storage**: Telemetry records are stored locally with strict read-only access.
2. **Viewer Sanitization**: When a `VIEWER` accesses the evidence endpoint, the backend redacts raw payload attributes (`details`) into a generic status banner: `{"status": "restricted", "message": "Raw telemetry payload restricted for role: VIEWER"}`.
3. **LLM Redaction**: Prior to LLM prompt serialization, `EvidenceValidator.redact_sensitive_data` scrubs all bearer tokens, authorization headers, passwords, and API keys.

### Security Audit Logging

Security-critical operations trigger immutable audit entries persisted in the `audit_logs` table:

- **Attributes**: `id`, `timestamp`, `user_id`, `role`, `action`, `resource_type`, `resource_id`, `result`, `metadata`.
- **Monitored Actions**: `LOGIN`, `LOGOUT`, `FAILED_LOGIN`, `UNAUTHORIZED_ACCESS`, `RUN_RCA`, `INGEST_TELEMETRY`, `CREATE_USER`, `UPDATE_ROLE`, `UPDATE_STATUS`.
- **Sanitization Guardrail**: The audit logger strictly strips keys matching `password`, `secret`, `token`, `bearer`, or `key` from all log metadata.

### Security Limitations & Roadmap

- _Current State_: Dual-storage backend supporting local SQLite and Supabase PostgreSQL with server-enforced Flask RBAC and immutable audit logging.
- _Production Roadmap_: Migration to OAuth2 / OIDC SSO provider, token rotation, rate limiting, and mTLS for telemetry ingestion agents.

---

## 8. Supabase PostgreSQL Storage Architecture (Step 2)

### Dual-Storage Architecture

TraceWise employs a clean abstraction pattern where [`BaseStorage`](file:///e:/Hackmitten3.0/app/storage/base.py) defines the universal storage contract implemented by both [`SqliteStorage`](file:///e:/Hackmitten3.0/app/storage/sqlite_adapter.py) and [`SupabaseStorage`](file:///e:/Hackmitten3.0/app/storage/supabase_adapter.py).

```
                      ┌────────────────────────┐
                      │    Flask API Routes    │
                      └───────────┬────────────┘
                                  │
                                  ▼
                      ┌────────────────────────┐
                      │   Storage Abstraction  │
                      │  (app.storage.base)    │
                      └───────────┬────────────┘
                                  │
                ┌─────────────────┴─────────────────┐
                │                                   │
                ▼                                   ▼
      ┌───────────────────┐               ┌───────────────────┐
      │  Supabase Adapter │               │   SQLite Adapter  │
      │  (PostgREST API)  │               │ (Local Fallback)  │
      └─────────┬─────────┘               └─────────┬─────────┘
                │                                   │
                ▼                                   ▼
      ┌───────────────────┐               ┌───────────────────┐
      │     Supabase      │               │   Local SQLite    │
      │    PostgreSQL     │               │     Database      │
      └───────────────────┘               └───────────────────┘
```

### Backend Selection & Failure Handling

- **Explicit Selection**: Configured via `DATABASE_BACKEND=supabase` or `DATABASE_BACKEND=sqlite` in `.env`.
- **No Silent Fallback**: When `DATABASE_BACKEND=supabase`, the application strictly connects to Supabase. If credentials or network connectivity fail, `SupabaseStorage` raises a clear `ConnectionError` or `ValueError` rather than masking the issue.
- **SQLite Preserved**: SQLite remains available as an explicitly selectable offline/testing database (`DATABASE_BACKEND=sqlite`).

### PostgreSQL Schema & Relational Integrity

The PostgreSQL schema is defined in [`supabase/migrations/001_initial_schema.sql`](file:///e:/Hackmitten3.0/supabase/migrations/001_initial_schema.sql):

- **10 Relational Tables**: `services`, `dependencies`, `incidents`, `evidence`, `candidates`, `analysis_runs`, `timeline_events`, `evaluation_ground_truth`, `users`, `audit_logs`.
- **Foreign Keys**: Cascading deletion for incident evidence, runs, and timeline events; set-null on service deletion.
- **Native JSONB Storage**: Multi-factor scoring breakdowns, linkages, and metadata are persisted as native PostgreSQL `JSONB` structures, enabling high-performance queries and flexible schema evolution.

### Data Migration & Parity

The migration utility [`scripts/migrate_sqlite_to_supabase.py`](file:///e:/Hackmitten3.0/scripts/migrate_sqlite_to_supabase.py):

- Copies all services, dependency edges, incidents, normalized evidence, RCA candidates, timelines, analysis runs, users, and audit records into Supabase.
- Uses idempotent `Prefer: resolution=merge-duplicates` headers to guarantee safety across multiple runs without duplicating records.
- Verifies record counts across both databases to ensure 100% data parity.

### Security & Row Level Security (RLS)

- **Authoritative Backend**: Flask backend RBAC remains the authoritative authorization layer.
- **Credential Isolation**: Client publishable keys are isolated in `.env` and never exposed in code, JavaScript, HTML, documentation, or API responses. Zero service-role keys are required.
- **RLS Enabled**: RLS is activated on all tables with explicit application policies.
