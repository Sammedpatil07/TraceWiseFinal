# AI Assistance & Verification Log — AO-03

## Guidelines

- LLM is strictly used for synthesis and natural-language summarization of verified evidence.
- The deterministic evidence correlation engine is the definitive source of truth.
- Every claim made by the LLM layer must link to a valid Evidence ID stored in the database.
- The displayed text must clearly state:
  `"AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING"`

---

## AI Implementation Record

### 1. Codebase Generation & Assistance

- **Role**: AI assistant generated scaffolding, multi-factor correlation algorithms, schema mappers, unit tests, and dashboard UI following modern, clean engineering practices.
- **Verification**:
  - All mathematical scoring functions are deterministic and unit-tested across 24 pytest cases.
  - Scores are normalized between 0.0 and 1.0 and explicitly termed "Evidence Score" (never referred to as a probability).
  - Schema migrations are verified for PostgreSQL / Supabase compliance.
  - Ingestion interfaces enforce the normalized Evidence contract.

### 2. Runtime LLM Explanation Layer

- **Provider**: Local Ollama LLM via `app/llm/ollama_provider.py` (no API key required).
- **Fallback**: Built-in deterministic template / heuristic explainer (`app/llm/heuristic_provider.py`) activates automatically when Ollama is unavailable or the configured model is not pulled.
- **Guardrails**:
  - The LLM explanation receives only a pre-validated, bounded `InvestigationPacket`.
  - An evidence validator (`EvidenceValidator.validate_llm_hypothesis`) scans the LLM output to ensure every cited evidence ID exists in the database.
  - Unverified or hallucinated evidence references are rejected and stripped.
  - All outputs carry the mandatory header:
    `"AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING"`

### 3. Sensitive Data Redaction Guardrail

- Implemented in `app/engine/validator.py` via `EvidenceValidator.redact_sensitive_data`.
- Automatically scrubs secrets before payloads are sent to external LLMs:
  - Bearer tokens: `Bearer [REDACTED]`
  - Authorization headers: `authorization: [REDACTED]`
  - Passwords and secrets: `password=[REDACTED]`, `secret=[REDACTED]`, `api_key=[REDACTED]`
  - JWT structures: `[REDACTED_JWT]`
- Unit-tested in `tests/test_evidence_validation.py` and `scripts/demo_check.py`.

### 4. Insufficient Telemetry Handling

- When evidence score is below the minimum confidence threshold ($0.35$), the system does not prompt the LLM to hallucinate a root cause.
- Instead, the deterministic engine issues `UNKNOWN / INSUFFICIENT EVIDENCE`, which the UI and LLM layers honor explicitly.

### 5. RBAC & LLM Authorization Guardrails

- **Trigger Authorization**: Only users authenticated with `ADMIN` or `INCIDENT_RESPONDER` roles may trigger `POST /api/incidents/<id>/analyze` (which calls the LLM explanation layer).
- **Viewer Restrictions**: `VIEWER` users attempting to trigger RCA/LLM analysis receive HTTP `403 Forbidden` and the attempt is recorded in the security audit trail.
- **Pre-Dispatch Sanitization**: Redaction via `EvidenceValidator.redact_sensitive_data` occurs _strictly before_ telemetry packets are formatted for LLM ingestion.
- **Audit Logging**: Every LLM investigation invocation is audited with `RUN_RCA`, recording the acting user ID, role, incident ID, and execution status without leaking prompt tokens or confidential metadata.

### 6. Cloud Storage & Credential Guardrails (Step 2)

- **Zero Credential Ingestion**: The AI explainer prompt never ingests database credentials, Supabase API keys, connection strings, or system environment variables.
- **Data Source Grounding**: All evidence synthesized by the LLM layer originates strictly from verified storage adapter queries (`BaseStorage.get_incident_evidence`), preventing LLM hallucination of ungrounded telemetry.
- **Active Backend Transparency**: LLM hypotheses reflect deterministic root cause calculations regardless of whether the active storage backend is Supabase PostgreSQL or local SQLite.

### 7. Final Hardening & Evidence-First Verification (Step 3)

- **Evidence Before Explanation Invariant**: Explicitly codified into the system prompt: `"EVIDENCE BEFORE EXPLANATION: All explanations must be strictly anchored in verified telemetry evidence."`
- **Mandatory Citation Validation**: `EvidenceValidator.validate_llm_hypothesis` enforces that 100% of cited evidence IDs exist in the active PostgreSQL database, rejecting any unverified citations.
- **Graceful Offline Fallback**: When the local Ollama instance is unavailable, the system automatically falls back to deterministic template generation without crashing or compromising mathematical ranking. No cloud API key is required.
- **Mandatory Disclosure Header**: All generated outputs enforce the header: `"AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING"`.
