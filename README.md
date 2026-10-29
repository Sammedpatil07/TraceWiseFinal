# AO-03 — Incident Root Cause Analysis Engine

> _"The incident is resolved; nobody knows why."_  
> **Mission:** Answer _"What most likely caused this incident, and what evidence proves it?"_ with mathematical rigor, deterministic telemetry correlation, and verified evidence integrity.

---

## 1. Project Purpose & Core Philosophy

In modern distributed microservices architectures, transient outages frequently clear before root cause determination completes. AO-03 is a deterministic Root Cause Analysis (RCA) engine designed to retrospectively analyze telemetry from resolved incidents without creating fake production data or fabricating evidence.

### Architectural Principles:

1. **Evidence Precedes AI**: Deterministic correlation algorithms are the sole source of truth. Causal scores are calculated directly from telemetry data.
2. **LLM as Explainer Only**: The LLM layer receives only structured, pre-validated investigation packets and generates natural-language summaries.
3. **Mandatory Hypothesis Notice**: Every AI finding is clearly labeled:
   ```
   AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING
   ```
4. **Strict Evidence Verification**: Every candidate explanation and LLM claim must cite verified Evidence IDs stored in the database. Hallucinated IDs are systematically stripped or rejected.
5. **Insufficient Evidence Guardrail**: If telemetry is sparse, normal, or lacks causal linkage, the system explicitly returns:
   ```
   UNKNOWN / INSUFFICIENT EVIDENCE
   ```
6. **Decoupled Demonstration Fixtures**: All synthetic development data is strictly labeled `SourceType.SYNTHETIC_DEMO`. The organizer ingestion pathway is completely decoupled.

---

## 2. System Architecture

```
                               ┌────────────────────────────────────────┐
                               │           Raw Telemetry Sources        │
                               │   (Logs, Metrics, Traces, Changes)     │
                               └──────────────────┬─────────────────────┘
                                                  │
                                                  ▼
                               ┌────────────────────────────────────────┐
                               │       Generic Ingestion Pipeline       │
                               │      (Normalized Internal Model)       │
                               └──────────────────┬─────────────────────┘
                                                  │
                                                  ▼
                       ┌────────────────────────────────────────────────────────┐
                       │                   Dual Storage Layer                   │
                       │     (Supabase PostgreSQL / Zero-Config SQLite)         │
                       └──────────────────┬───────────────────┬─────────────────┘
                                          │                   │
                        ┌─────────────────┴─┐               ┌─┴────────────────┐
                        │ Dynamic DAG Graph │               │ Chronological    │
                        │ (NetworkX Blast)  │               │ Timeline Builder │
                        └─────────────────┬─┘               └─┬────────────────┘
                                          │                   │
                                          ▼                   ▼
                               ┌────────────────────────────────────────┐
                               │       Deterministic RCA Engine         │
                               │  - Temporal Precedence      (15%)      │
                               │  - Dependency Relevance     (15%)      │
                               │  - Anomaly Magnitude        (15%)      │
                               │  - Error Surge Rate         (15%)      │
                               │  - Trace Correlation        (10%)      │
                               │  - Deployment Proximity     (10%)      │
                               │  - Configuration Proximity  (10%)      │
                               │  - Blast Reachability       (10%)      │
                               └──────────────────┬─────────────────────┘
                                                  │
                                                  ▼
                               ┌────────────────────────────────────────┐
                               │     Evidence & Ground-Truth Validator  │
                               └──────────────────┬─────────────────────┘
                                                  │
                                                  ▼
                               ┌────────────────────────────────────────┐
                               │        LLM Explanation Layer           │
                               │  (Local Ollama / Offline Heuristic)    │
                               └──────────────────┬─────────────────────┘
                                                  │
                                                  ▼
                               ┌────────────────────────────────────────┐
                               │    AO-03 Web Dashboard & Explorer      │
                               └────────────────────────────────────────┘
```

---

## 3. Folder Structure

```text
E:\Hackmitten3.0\
├── app\
│   ├── __init__.py                # Flask application factory
│   ├── config.py                  # Environment settings & scoring weights
│   ├── models\                    # Normalized dataclasses & domain models
│   │   ├── evidence.py            # NormalizedEvidence (LOG, METRIC, TRACE, DEPLOYMENT, CONFIG)
│   │   └── incident.py            # Incident, CandidateCause, TimelineEvent, AnalysisResult
│   ├── storage\                   # Dual-persistence storage adapters
│   │   ├── base.py                # Abstract BaseStorage interface
│   │   ├── sqlite_adapter.py      # Zero-setup local SQLite engine
│   │   └── supabase_adapter.py    # Supabase PostgreSQL client with fallback
│   ├── ingestion\                 # Ingestion pipeline & demo fixtures
│   │   ├── base.py                # BaseIngestionAdapter
│   │   ├── generic_adapter.py     # Generic Log, Metric, Trace, Deployment, Config adapters
│   │   └── demo_fixtures.py       # Isolated synthetic demonstration fixtures (tagged DEMO)
│   ├── engine\                    # Deterministic RCA Core
│   │   ├── dependency_graph.py    # NetworkX service DAG & blast reachability
│   │   ├── timeline.py            # Timeline event generation & trigger tagging
│   │   ├── correlation.py         # Multi-factor causal scoring engine
│   │   ├── validator.py           # Evidence reference validator (anti-hallucination)
│   │   └── rca_engine.py          # RCA orchestrator & Insufficient Evidence guard
│   ├── llm\                       # LLM explanation layer
│   │   ├── provider.py            # BaseLLMProvider interface
│   │   ├── ollama_provider.py     # Local Ollama LLM integration (no API key)
│   │   ├── heuristic_provider.py  # Offline deterministic heuristic fallback
│   │   └── explanation.py         # Structured InvestigationPacket builder
│   ├── api\                       # REST API Blueprints
│   │   ├── incidents.py           # /api/incidents, /api/incidents/<id>/rca, /api/stats
│   │   ├── evidence.py            # /api/evidence, /api/ingest
│   │   ├── topology.py            # /api/services, /api/topology
│   │   └── demo.py                # /api/demo/load, /api/demo/reset
│   ├── static\                    # Frontend assets
│   │   ├── css\style.css          # Sleek high-contrast modern dark design system
│   │   └── js\
│   │       ├── app.js             # Navigation, metrics & modal bindings
│   │       ├── investigation.js   # Investigation view, Chart.js, topology canvas
│   │       └── explorer.js        # Filterable evidence explorer table
│   └── templates\
│       └── index.html             # Single-page dashboard application
├── migrations\
│   ├── 001_initial_schema.sql     # Supabase PostgreSQL DDL migration
│   └── supabase_setup.md          # Supabase setup instructions
├── tests\                         # Pytest unit and integration test suite
│   ├── test_normalization.py
│   ├── test_dependency_graph.py
│   ├── test_timeline.py
│   ├── test_scoring.py
│   ├── test_evidence_validation.py
│   ├── test_insufficient_evidence.py
│   └── test_api.py
├── docs\
│   ├── DEVELOPMENT_LOG.md         # Development decisions & timeline
│   └── AI_DEVELOPMENT.md          # AI usage and manual verification record
├── requirements.txt
├── .env.example
├── run.py                         # Application entrypoint
└── README.md
```

---

## 4. How to Install

### Prerequisites:

- Python 3.10+ (tested on Python 3.14)
- Pip

### Installation:

```bash
git clone <repo-url>
cd Hackmitten3.0

# Install dependencies
python -m pip install -r requirements.txt
```

---

## 5. Configuration

Copy `.env.example` to `.env`:

```bash
copy .env.example .env
```

### Storage Configuration:

- **Local SQLite (Default - Zero setup required):**
  ```env
  STORAGE_BACKEND=sqlite
  SQLITE_DB_PATH=data/ao03_telemetry.db
  ```
- **Supabase PostgreSQL (Optional):**
  ```env
  STORAGE_BACKEND=supabase
  SUPABASE_URL=https://your-project.supabase.co
  SUPABASE_KEY=your-supabase-key
  ```
  _(See [`migrations/supabase_setup.md`](migrations/supabase_setup.md) for applying `001_initial_schema.sql` via Supabase SQL Editor)._

### Local LLM via Ollama (Recommended):

The system uses a **fully local** Ollama LLM for AI-generated explanations — no API key or cloud account required. All inference runs on your machine.

#### Prerequisites:

1. **Install Ollama** from [ollama.com](https://ollama.com) (if not already installed).
2. **Start Ollama** (it runs as a background service on Windows — look for it in your system tray, or run `ollama serve` in a terminal).
3. **Pull the model:**
   ```bash
   ollama pull qwen2.5:0.5b
   ```
4. **Verify the model is available:**
   ```bash
   ollama list
   ```
   You should see `qwen2.5:0.5b` in the output.

#### Configuration in `.env`:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:0.5b
```

If Ollama is not running or the model is missing, the system automatically falls back to the built-in deterministic heuristic explainer (`app/llm/heuristic_provider.py`), ensuring full functionality.

#### Testing the local LLM:

```bash
# Verify Ollama is responding:
curl http://localhost:11434/api/tags

# Test a generation:
curl http://localhost:11434/api/chat -d "{\"model\": \"qwen2.5:0.5b\", \"messages\": [{\"role\": \"user\", \"content\": \"hello\"}], \"stream\": false}"
```

> **Note:** All LLM inference is 100% local. No data is sent to OpenAI, Google, or any cloud API. No API tokens are consumed.

---

## 6. How Future Organizer Telemetry Will Be Ingested

Organizer datasets can be ingested directly into the engine without modifying the core RCA logic via the Generic Ingestion API:

### Generic Ingestion Route: `POST /api/ingest`

```bash
curl -X POST http://127.0.0.1:5000/api/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "incident_id": "INC-ORGANIZER-101",
    "evidence_type": "LOG",
    "source_type": "ORGANIZER",
    "records": [
      {
        "service": "checkout-service",
        "time": "2026-10-28T14:05:00Z",
        "level": "ERROR",
        "message": "Connection timed out to redis-master"
      }
    ]
  }'
```

Supported `evidence_type` values:

- `LOG`: Accepts log events (service, time, level, message, details).
- `METRIC`: Accepts metrics (service, timestamp, metric_name, value, threshold, z_score).
- `TRACE`: Accepts trace spans (service, timestamp, endpoint, http_status, duration_ms, error).
- `DEPLOYMENT`: Accepts code deployments (service, timestamp, commit_hash, diff_summary).
- `CONFIGURATION`: Accepts config drifts (service, timestamp, key, previous_value, new_value).

---

## 7. Role-Based Access Control (RBAC) & Authentication

TraceWise AO-03 implements server-enforced Role-Based Access Control (RBAC) on top of the local persistence layer. Authorization is strictly verified at the Flask route level.

### Three Distinct Roles

| Feature / Capability                    | ADMIN | INCIDENT_RESPONDER |           VIEWER           |
| --------------------------------------- | :---: | :----------------: | :------------------------: |
| **Dashboard & Metric Summaries**        |  YES  |        YES         |            YES             |
| **Incident Registry & Filter**          |  YES  |        YES         |            YES             |
| **Run Root Cause Analysis (RCA)**       |  YES  |        YES         | READ-ONLY (403 on Trigger) |
| **Service Graph & Timeline**            |  YES  |        YES         |         READ-ONLY          |
| **Raw Telemetry & Evidence Details**    |  YES  |  YES (Read-Only)   |   RESTRICTED / SANITIZED   |
| **Telemetry Ingestion (`/api/ingest`)** |  YES  |      NO (403)      |          NO (403)          |
| **Demo Fixture Load / Data Reset**      |  YES  |      NO (403)      |          NO (403)          |
| **User & Role Administration**          |  YES  |      NO (403)      |          NO (403)          |
| **Security Audit Logs**                 |  YES  |      NO (403)      |          NO (403)          |

### Architecture & Security Details

- **Authentication**: Secure server-side sessions with HTTP-only cookies. Passwords are never stored in plaintext and are hashed using Werkzeug/scrypt.
- **Backend Enforcement**: Protected endpoints utilize `@login_required` and `@role_required(*roles)` decorators with automatic audit logging on authorization failures.
- **Sensitive Data Redaction**: EvidenceValidator sanitizes bearer tokens, API keys, passwords, and secrets before telemetry is viewed or transmitted to the LLM explainer.
- **Security Audit Trail**: Every sensitive action (`LOGIN`, `FAILED_LOGIN`, `RUN_RCA`, `CREATE_USER`, `UPDATE_ROLE`, `UNAUTHORIZED_ACCESS`) is recorded in the immutable `audit_logs` table.
- **Demo Seeding**: Automatic safe default user provisioning during database initialization (or configurable via environment variables `ADMIN_DEFAULT_PASSWORD`, `SRE_DEFAULT_PASSWORD`, `VIEWER_DEFAULT_PASSWORD`).
  _Quick demo access buttons in the UI modal allow instant single-click role switching for judges._

---

## 8. Supabase PostgreSQL Storage Architecture & Database Selection

TraceWise AO-03 supports dual storage backends via a unified storage abstraction:

1. **Supabase PostgreSQL (`DATABASE_BACKEND=supabase`)**: Production-ready cloud persistence using PostgREST API with Row Level Security (RLS).
2. **Local SQLite (`DATABASE_BACKEND=sqlite`)**: Zero-config, zero-dependency embedded database at `data/ao03_telemetry.db`.

### Environment Configuration

The database backend is selected strictly via `.env` (which is git-ignored and never committed):

```env
# Database Backend Selection: "supabase" (default) or "sqlite"
DATABASE_BACKEND=supabase
STORAGE_BACKEND=supabase

# Supabase Project Credentials (Only client publishable key required)
SUPABASE_URL=https://[YOUR_PROJECT_REF].supabase.co
SUPABASE_KEY=[YOUR_PUBLISHABLE_KEY]
```

### Reproducible Schema Migrations

The PostgreSQL DDL schema definition is stored in:

- [`supabase/migrations/001_initial_schema.sql`](file:///e:/Hackmitten3.0/supabase/migrations/001_initial_schema.sql)
- [`migrations/001_initial_schema.sql`](file:///e:/Hackmitten3.0/migrations/001_initial_schema.sql)

It establishes all 10 core entities (`services`, `dependencies`, `incidents`, `evidence`, `candidates`, `analysis_runs`, `timeline_events`, `evaluation_ground_truth`, `users`, `audit_logs`), performance indexes, and Row Level Security policies.

### Data Migration from SQLite to Supabase

To copy all telemetry records, incidents, users, and audit logs into Supabase with duplicate protection:

```bash
python scripts/migrate_sqlite_to_supabase.py
```

This utility uses idempotent `Prefer: resolution=merge-duplicates` upserts and prints an automated data parity audit comparing record counts between SQLite and Supabase.

### Active Storage Diagnostic

Inspect active database status and connection health in real time:

```bash
curl http://127.0.0.1:5000/api/diagnostic
```

Returns:

```json
{
  "active_database": "SUPABASE",
  "connection": "HEALTHY",
  "database_backend": "supabase",
  "engine_version": "1.0.0",
  "service": "ao03-incident-rca",
  "status": "HEALTHY"
}
```

---

## 9. How to Run & Verify

### Start the Local Application

```bash
python run.py
```

Open your browser at:

```
http://127.0.0.1:5000/
```

### Verified Demo Role Credentials

The application enforces strict server-side RBAC across 3 roles:

- **Admin** (Full Control, User Management, Ingestion): `admin` / `Admin!Pass2026` (or alias `admin` / `admin`)
- **Incident Responder** (Investigation, RCA, Operational Audit): `sre` / `Sre!Pass2026` (or alias `sre` / `sre`)
- **Viewer / Auditor** (Read-Only, Telemetry Redacted): `viewer` / `Viewer!Pass2026` (or alias `viewer` / `viewer`)

---

## 10. Automated Test & Verification Suites

Execute the 4 automated testing scripts:

1. **Unit, Integration, and RBAC Test Suite (42 tests)**:
   ```bash
   python -m pytest tests/ -v
   ```
2. **13-Stage Pipeline Acceptance Suite (13 stages)**:
   ```bash
   python scripts/demo_check.py
   ```
3. **Comprehensive All-Scenario Verification Suite (34 scenarios)**:
   ```bash
   python scratch/verify_all_scenarios.py
   ```
4. **Interactive UI Tabs, Modals & Controls Audit (31 controls)**:
   ```bash
   python scratch/test_every_tab_and_control.py
   ```

**Total Verified Automated Tests: 120 / 120 Passed (0 Failed).**

---

## 11. Guided Hackathon Demo Workflow

1. **Sign In & Role Demonstration**:
   - Navigate to `http://127.0.0.1:5000/`. Unauthenticated visitors see the secure login gate.
   - Click any Quick Demo button or enter credentials to sign in.
   - Observe that the navbar dynamically reflects user identity, role badge, and permission-gated controls.
2. **Dashboard Overview**:
   - Inspect the top 6 summary KPI cards (Total, Active, Resolved, Evidence, Services, Investigations).
   - In the **Incident Registry**, test real-time search, severity filter (`CRITICAL`), status filter, and service dropdown.
3. **Launch Investigation**:
   - Click **"Investigate"** on `INC-2026-001` (_Checkout & Payment Gateway 504 Timeout Cascade_).
   - The system automatically retrieves normalized evidence, generates the causal DAG, and executes deterministic RCA in <3 seconds.
4. **Inspect Root Cause Ranking & Evidence Proof**:
   - Top candidate ranked #1: _"Configuration drift on payment-service"_ (Evidence Score: `0.992`).
   - Examine the **"Why This Cause?"** score attribution chart showing mathematical weights and factor contributions.
   - Expand the **Evidence Proof Drawer** to inspect the full verification chain:
     $$\text{CLAIM} \longrightarrow \text{EVIDENCE} \longrightarrow \text{SOURCE}$$
   - Check the **Contradicting Evidence** section proving non-causal events were evaluated.
5. **Chronological Timeline**:
   - Review events from configuration change $\rightarrow$ latency spike $\rightarrow$ error surge $\rightarrow$ downstream timeout $\rightarrow$ detection.
   - Click any event pill to focus on the underlying evidence.
6. **Interactive Service Dependency Topology**:
   - Visualize the DAG with badges: `ROOT` (`payment-service`), `AFFECTED` (`checkout-service`, `api-gateway`), and `UPSTREAM`.
   - Click `payment-service` to filter and highlight its supporting telemetry.
7. **Bounded AI Hypothesis**:
   - Review the AI synthesis card carrying the mandatory label:
     `AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING`.
   - Verify that all cited evidence IDs are clickable and grounded in the database.
8. **Verify Honest UNKNOWN Guardrail**:
   - Switch to `INC-2026-002` (_Elevated 503s on checkout-service_).
   - Observe that the engine honestly returns `UNKNOWN / INSUFFICIENT EVIDENCE` due to sparse telemetry without hallucinating a false cause.
9. **Security Administration & Audit Trail**:
   - Sign in as `admin`, navigate to **Admin & Audit**.
   - Review registered system users, provision new accounts, change roles, or inspect immutable audit records.
10. **Evidence Redaction Verification**:

- Log out and sign in as `viewer`.
- In the Evidence Explorer, raw payload metadata and source records are automatically redacted (`[RESTRICTED]`).
- Privileged operations (Run RCA, User Management, Audit Trail) are strictly blocked with HTTP 403.

---

## 12. Technical Documentation

- [System Architecture](docs/ARCHITECTURE.md) — Multi-factor scoring math, causal gating, DAG inference, and security redaction.
- [Dataset & Telemetry Analysis](docs/DATASET_ANALYSIS.md) — Service inventory, dependency edges, incident scenarios, and ground-truth status.
- [Development Log](docs/DEVELOPMENT_LOG.md) — Chronological implementation history from Phase 1 through Step 3 hardening.
- [AI Assistance & Verification Record](docs/AI_DEVELOPMENT.md) — Grounding rules, citation validation, and sensitive data scrubbers.

---

## 13. Known Limitations

1. **Benchmark Ground-Truth Dataset**: While deterministic RCA and evidence correlation operate with 100% precision on demo scenarios, aggregate Top-1/Top-3/MRR benchmark accuracy metrics in the Evaluation view remain pending organizer-supplied ground-truth evaluation datasets.
2. **Local Single-Node Deployment**: The application is configured for local-first demonstration (`http://127.0.0.1:5000`); horizontal cluster auto-scaling and Redis caching are omitted by design for hackathon simplicity.
3. **Local LLM Dependency**: The system uses a local Ollama instance for AI explanations. When Ollama is not running or the model `qwen2.5:0.5b` is not available, the system automatically activates its built-in deterministic heuristic explainer (`app/llm/heuristic_provider.py`), ensuring complete demo functionality. No cloud API key is required.
4. **Local Model Capability**: The `qwen2.5:0.5b` model is lightweight and fast but may produce lower-quality explanations compared to larger cloud models. For improved explanation quality, consider pulling a larger model (e.g., `qwen2.5:7b`) and updating `OLLAMA_MODEL` in `.env`.

---

## 14. Future Scope

1. **Automated Remediation Workflows**: Integration with runbook automation (Ansible, Kubernetes operators) to automatically rollback configuration drift or restart degraded microservices once evidence score exceeds $0.90$.
2. **Enterprise SSO & OIDC**: Federated identity integration (Okta, GitHub OAuth, Azure AD) complementing the native session-based RBAC.
3. **Streaming Ingestion Pipeline**: Real-time Kafka or OpenTelemetry collector integration for sub-second telemetry ingestion and streaming root cause correlation.
