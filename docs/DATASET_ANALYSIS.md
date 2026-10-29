# Dataset Analysis — TraceWise AO-03

## 1. Active Database & Provenance

- **Storage Backend**: Local SQLite database located at `data/ao03_telemetry.db` (with dual-storage support for Supabase PostgreSQL via `migrations/001_initial_schema.sql`).
- **Data Provenance**: Explicitly tracked per record using the `source_type` enumeration (`ORGANIZER`, `SYNTHETIC_DEMO`, `IMPORTED`).
- **Data Isolation**: Synthetic fixtures are isolated in `app/ingestion/demo_fixtures.py` and labeled `source_type="SYNTHETIC_DEMO"`. When organizer datasets are provided, `GenericTelemetryIngestor` ingests them as `source_type="ORGANIZER"` without schema changes.

---

## 2. Inventory of Telemetry & Topology

### Services (6 Nodes)
| Service ID | Service Name | Tier | Dependencies |
| :--- | :--- | :--- | :--- |
| `api-gateway` | API Gateway | edge / gateway | `checkout-service`, `auth-service` |
| `checkout-service` | Checkout Service | core | `payment-service`, `inventory-service`, `notification-service` |
| `payment-service` | Payment Service | backend | Downstream provider gateway |
| `auth-service` | Authentication Service | backend | Database pool |
| `inventory-service` | Inventory Service | backend | Storage layer |
| `notification-service` | Notification Service | background | Queue workers |

### Causal Dependencies (5 Direct Edges)
- `api-gateway` $\rightarrow$ `checkout-service` (HTTP / Critical)
- `api-gateway` $\rightarrow$ `auth-service` (HTTP / Critical)
- `checkout-service` $\rightarrow$ `payment-service` (HTTP / Critical)
- `checkout-service` $\rightarrow$ `inventory-service` (gRPC / High)
- `checkout-service` $\rightarrow$ `notification-service` (AMQP / Async)

---

## 3. Incident Scenarios

### Scenario 1: `INC-2026-001` — Payment Gateway Latency Spike & Cascade
- **Severity**: P1 (CRITICAL)
- **Status**: ACTIVE
- **Target Services**: `payment-service`, `checkout-service`, `api-gateway`
- **Telemetry Records**: 9 normalized records
  - `EVID-PAY-CFG-01`: Configuration drift `cfg_pay_v201` setting timeout to 100ms.
  - `EVID-PAY-DEP-01`: Deployment `dep_pay_8841` committing payment retry policy change.
  - `EVID-PAY-MET-01`: Metric anomaly: p99 latency spiked to 4820ms on `payment-service`.
  - `EVID-PAY-LOG-01`: Log error: HTTP 504 Gateway Timeout on `/v1/charge`.
  - `EVID-PAY-TRC-01`: Distributed trace `trc_pay_77102`: span duration 5100ms on `payment-service`.
  - `EVID-CHK-MET-01`: Upstream checkout error rate surged to 34.2%.
  - `EVID-CHK-LOG-01`: Upstream log: `Downstream service payment-service timed out`.
  - `EVID-CHK-TRC-01`: Parent trace span on `checkout-service` waiting for child span.
  - `EVID-GW-LOG-01`: Edge gateway returning HTTP 502 Bad Gateway to end users.
- **Root Cause Ground Truth**: Configuration drift + deployment on `payment-service`.
- **Engine Score**: 0.917 (Top Candidate: "Configuration drift on payment-service").

### Scenario 2: `INC-2026-002` — Elevated 503s on Checkout Service (Sparse Telemetry)
- **Severity**: P2 (HIGH)
- **Status**: ACTIVE
- **Target Services**: `checkout-service`
- **Telemetry Records**: 2 isolated log warnings with no causal or temporal correlations.
- **Engine Guardrail**: Score $< 0.35$ triggers honest `UNKNOWN / INSUFFICIENT EVIDENCE` instead of guessing.

### Scenario 3: `INC-2026-003` — DB Connection Pool Exhaustion on Auth Service
- **Severity**: P1 (CRITICAL)
- **Status**: RESOLVED
- **Target Services**: `auth-service`, `api-gateway`
- **Telemetry Records**: 4 records showing database lock wait, pool exhaustion, and auth timeouts.
- **Engine Score**: 0.880 (Top Candidate: "Database connection pool exhaustion on auth-service").

### Scenario 4: `INC-2026-004` — Search Worker Synchronization Lag
- **Severity**: P3 (MEDIUM)
- **Status**: RESOLVED
- **Target Services**: `inventory-service`
- **Telemetry Records**: 2 records showing queue consumer backlog.

---

## 4. Evaluation & Benchmark Status

- **Total Incidents Analyzed**: 4
- **Evidence Telemetry Records Ingested**: 17
- **Evidence Coverage**: 100% (all evidence records map to valid services and timestamps).
- **Mean Investigation Latency**: ~140ms.
- **Ground Truth Status**: Top-1 / Top-3 / MRR are honestly reported as `Ground truth not loaded` until organizers supply labeled benchmark datasets.
