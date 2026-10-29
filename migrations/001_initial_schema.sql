-- Supabase / PostgreSQL Migration: 001_initial_schema.sql
-- AO-03: TraceWise Incident Root Cause Analysis & RBAC Schema

-- 1. Services Table
CREATE TABLE IF NOT EXISTS services (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    tier VARCHAR(64) DEFAULT 'service',
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Dependencies Table (Service Topology DAG)
CREATE TABLE IF NOT EXISTS dependencies (
    id VARCHAR(64) PRIMARY KEY,
    source_service VARCHAR(64) NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    target_service VARCHAR(64) NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    call_type VARCHAR(32) DEFAULT 'HTTP',
    critical BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_dependency_edge UNIQUE (source_service, target_service)
);

-- 3. Incidents Table
CREATE TABLE IF NOT EXISTS incidents (
    id VARCHAR(64) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'OPEN',
    severity VARCHAR(32) NOT NULL DEFAULT 'HIGH',
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    resolved_at TIMESTAMP WITH TIME ZONE,
    affected_services JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Evidence Table (Normalized Multi-Modal Telemetry Evidence)
CREATE TABLE IF NOT EXISTS evidence (
    id VARCHAR(64) PRIMARY KEY,
    incident_id VARCHAR(64) REFERENCES incidents(id) ON DELETE CASCADE,
    evidence_type VARCHAR(32) NOT NULL,
    service_id VARCHAR(64) REFERENCES services(id) ON DELETE SET NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    source_type VARCHAR(32) DEFAULT 'ORGANIZER',
    summary TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    severity VARCHAR(32) DEFAULT 'INFO',
    anomaly_score DOUBLE PRECISION DEFAULT 0.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_evidence_incident ON evidence(incident_id);
CREATE INDEX IF NOT EXISTS idx_evidence_service ON evidence(service_id);
CREATE INDEX IF NOT EXISTS idx_evidence_timestamp ON evidence(timestamp);
CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(evidence_type);

-- 5. Candidates / Potential Root Causes
CREATE TABLE IF NOT EXISTS candidates (
    id VARCHAR(64) PRIMARY KEY,
    incident_id VARCHAR(64) NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    service_id VARCHAR(64) REFERENCES services(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    candidate_type VARCHAR(64) NOT NULL,
    rank INTEGER DEFAULT 1,
    confidence_score DOUBLE PRECISION NOT NULL,
    scoring_breakdown JSONB NOT NULL DEFAULT '{}'::jsonb,
    supporting_evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    contradicting_evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_candidates_incident ON candidates(incident_id);

-- 6. Analysis Runs
CREATE TABLE IF NOT EXISTS analysis_runs (
    id VARCHAR(64) PRIMARY KEY,
    incident_id VARCHAR(64) NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'SUCCESS',
    engine_version VARCHAR(32) NOT NULL DEFAULT '1.0.0',
    top_candidate_id VARCHAR(64) REFERENCES candidates(id) ON DELETE SET NULL,
    llm_hypothesis TEXT,
    llm_summary JSONB DEFAULT '{}'::jsonb,
    llm_status VARCHAR(32) DEFAULT 'AVAILABLE',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. Timeline Events (Derived from Verified Evidence)
CREATE TABLE IF NOT EXISTS timeline_events (
    id VARCHAR(64) PRIMARY KEY,
    incident_id VARCHAR(64) NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    service_id VARCHAR(64) REFERENCES services(id) ON DELETE SET NULL,
    summary TEXT NOT NULL,
    evidence_id VARCHAR(64) REFERENCES evidence(id) ON DELETE CASCADE,
    significance VARCHAR(32) DEFAULT 'MEDIUM',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_timeline_incident_time ON timeline_events(incident_id, timestamp);

-- 8. Evaluation Ground Truth (For Benchmark Scoring)
CREATE TABLE IF NOT EXISTS evaluation_ground_truth (
    id VARCHAR(64) PRIMARY KEY,
    incident_id VARCHAR(64) NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    actual_root_cause_service VARCHAR(64) REFERENCES services(id) ON DELETE SET NULL,
    actual_root_cause_type VARCHAR(64) NOT NULL,
    actual_trigger_time TIMESTAMP WITH TIME ZONE,
    ground_truth_evidence_ids JSONB DEFAULT '[]'::jsonb,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_incident_evaluation UNIQUE (incident_id)
);

-- 9. Users Table (Role-Based Access Control)
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    username VARCHAR(128) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'VIEWER',
    email VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

-- 10. Audit Logs Table (Security and Investigation Trail)
CREATE TABLE IF NOT EXISTS audit_logs (
    id VARCHAR(64) PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    username VARCHAR(128) NOT NULL,
    role VARCHAR(32) NOT NULL,
    action VARCHAR(64) NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource_id VARCHAR(64),
    result VARCHAR(32) NOT NULL DEFAULT 'SUCCESS',
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);

-- Enable Row Level Security (RLS) on all tables
ALTER TABLE services ENABLE ROW LEVEL SECURITY;
ALTER TABLE dependencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE timeline_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_ground_truth ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- RLS Policies for authenticated application access
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow read services') THEN
        CREATE POLICY "Allow read services" ON services FOR SELECT USING (true);
        CREATE POLICY "Allow write services" ON services FOR ALL USING (true);
        CREATE POLICY "Allow read dependencies" ON dependencies FOR SELECT USING (true);
        CREATE POLICY "Allow write dependencies" ON dependencies FOR ALL USING (true);
        CREATE POLICY "Allow read incidents" ON incidents FOR SELECT USING (true);
        CREATE POLICY "Allow write incidents" ON incidents FOR ALL USING (true);
        CREATE POLICY "Allow read evidence" ON evidence FOR SELECT USING (true);
        CREATE POLICY "Allow write evidence" ON evidence FOR ALL USING (true);
        CREATE POLICY "Allow read candidates" ON candidates FOR SELECT USING (true);
        CREATE POLICY "Allow write candidates" ON candidates FOR ALL USING (true);
        CREATE POLICY "Allow read analysis_runs" ON analysis_runs FOR SELECT USING (true);
        CREATE POLICY "Allow write analysis_runs" ON analysis_runs FOR ALL USING (true);
        CREATE POLICY "Allow read timeline_events" ON timeline_events FOR SELECT USING (true);
        CREATE POLICY "Allow write timeline_events" ON timeline_events FOR ALL USING (true);
        CREATE POLICY "Allow read evaluation_ground_truth" ON evaluation_ground_truth FOR SELECT USING (true);
        CREATE POLICY "Allow write evaluation_ground_truth" ON evaluation_ground_truth FOR ALL USING (true);
        CREATE POLICY "Allow read users" ON users FOR SELECT USING (true);
        CREATE POLICY "Allow write users" ON users FOR ALL USING (true);
        CREATE POLICY "Allow read audit_logs" ON audit_logs FOR SELECT USING (true);
        CREATE POLICY "Allow write audit_logs" ON audit_logs FOR ALL USING (true);
    END IF;
END $$;
