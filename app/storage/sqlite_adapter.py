"""SQLite Storage Adapter for AO-03.
Provides high-performance, zero-config local storage matching the Supabase schema.
"""

import sqlite3
import json
import os
from pathlib import Path
from typing import List, Optional, Dict, Any

from app.storage.base import BaseStorage
from app.models.evidence import (
    NormalizedEvidence,
    EvidenceType,
    EvidenceSeverity,
    SourceType,
    ServiceNode,
    ServiceDependency,
)
from app.models.incident import Incident, CandidateCause, TimelineEvent
from app.models.user import User, UserRole
from app.models.audit import AuditLog, AuditAction
from werkzeug.security import generate_password_hash


class SqliteStorage(BaseStorage):
    def __init__(self, db_path: str):
        self.db_path = db_path
        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS services (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    tier TEXT DEFAULT 'service',
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS dependencies (
                    id TEXT PRIMARY KEY,
                    source_service TEXT NOT NULL,
                    target_service TEXT NOT NULL,
                    call_type TEXT DEFAULT 'HTTP',
                    critical INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_service, target_service),
                    FOREIGN KEY(source_service) REFERENCES services(id) ON DELETE CASCADE,
                    FOREIGN KEY(target_service) REFERENCES services(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    severity TEXT NOT NULL DEFAULT 'HIGH',
                    started_at TEXT NOT NULL,
                    resolved_at TEXT,
                    affected_services TEXT NOT NULL DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    incident_id TEXT,
                    evidence_type TEXT NOT NULL,
                    service_id TEXT,
                    timestamp TEXT NOT NULL,
                    source_type TEXT DEFAULT 'ORGANIZER',
                    summary TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '{}',
                    severity TEXT DEFAULT 'INFO',
                    anomaly_score REAL DEFAULT 0.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(incident_id) REFERENCES incidents(id) ON DELETE CASCADE,
                    FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_evidence_incident ON evidence(incident_id);
                CREATE INDEX IF NOT EXISTS idx_evidence_service ON evidence(service_id);
                CREATE INDEX IF NOT EXISTS idx_evidence_timestamp ON evidence(timestamp);
                CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(evidence_type);

                CREATE TABLE IF NOT EXISTS candidates (
                    id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    service_id TEXT,
                    title TEXT NOT NULL,
                    description TEXT,
                    candidate_type TEXT NOT NULL,
                    rank INTEGER DEFAULT 1,
                    confidence_score REAL NOT NULL,
                    scoring_breakdown TEXT NOT NULL DEFAULT '{}',
                    supporting_evidence_ids TEXT NOT NULL DEFAULT '[]',
                    contradicting_evidence_ids TEXT NOT NULL DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(incident_id) REFERENCES incidents(id) ON DELETE CASCADE,
                    FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS analysis_runs (
                    id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'SUCCESS',
                    engine_version TEXT NOT NULL DEFAULT '1.0.0',
                    top_candidate_id TEXT,
                    llm_hypothesis TEXT,
                    llm_summary TEXT DEFAULT '{}',
                    llm_status TEXT DEFAULT 'AVAILABLE',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(incident_id) REFERENCES incidents(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS timeline_events (
                    id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    service_id TEXT,
                    summary TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    significance TEXT DEFAULT 'MEDIUM',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(incident_id) REFERENCES incidents(id) ON DELETE CASCADE,
                    FOREIGN KEY(evidence_id) REFERENCES evidence(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_timeline_incident_time ON timeline_events(incident_id, timestamp);

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'VIEWER',
                    email TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

                CREATE TABLE IF NOT EXISTS audit_logs (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    role TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT,
                    result TEXT NOT NULL DEFAULT 'SUCCESS',
                    metadata TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp);
                CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id);
                CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);
            """)
            self.seed_default_users()

    def save_service(self, service: ServiceNode) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO services (id, name, tier, description)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    tier=excluded.tier,
                    description=excluded.description;
                """,
                (service.id, service.name, service.tier, service.description),
            )

    def get_services(self) -> List[ServiceNode]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT id, name, tier, description FROM services ORDER BY name ASC").fetchall()
            return [ServiceNode(id=r["id"], name=r["name"], tier=r["tier"] or "service", description=r["description"] or "") for r in rows]

    def save_dependency(self, dependency: ServiceDependency) -> None:
        self.save_dependencies_batch([dependency])

    def save_dependencies_batch(self, dependencies: List[ServiceDependency]) -> None:
        if not dependencies:
            return
        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO dependencies (id, source_service, target_service, call_type, critical)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_service, target_service) DO UPDATE SET
                    call_type=excluded.call_type,
                    critical=excluded.critical;
                """,
                [
                    (d.id, d.source_service, d.target_service, d.call_type, 1 if d.critical else 0)
                    for d in dependencies
                ],
            )

    def get_dependencies(self) -> List[ServiceDependency]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT id, source_service, target_service, call_type, critical FROM dependencies").fetchall()
            return [
                ServiceDependency(
                    id=r["id"],
                    source_service=r["source_service"],
                    target_service=r["target_service"],
                    call_type=r["call_type"],
                    critical=bool(r["critical"]),
                )
                for r in rows
            ]

    def save_incident(self, incident: Incident) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO incidents (id, title, description, status, severity, started_at, resolved_at, affected_services)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    status=excluded.status,
                    severity=excluded.severity,
                    started_at=excluded.started_at,
                    resolved_at=excluded.resolved_at,
                    affected_services=excluded.affected_services;
                """,
                (
                    incident.id,
                    incident.title,
                    incident.description,
                    incident.status,
                    incident.severity,
                    incident.started_at,
                    incident.resolved_at,
                    json.dumps(incident.affected_services),
                ),
            )

    def get_incidents(self) -> List[Incident]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM incidents ORDER BY started_at DESC").fetchall()
            return [
                Incident(
                    id=r["id"],
                    title=r["title"],
                    description=r["description"] or "",
                    status=r["status"],
                    severity=r["severity"],
                    started_at=r["started_at"],
                    resolved_at=r["resolved_at"],
                    affected_services=json.loads(r["affected_services"] or "[]"),
                )
                for r in rows
            ]

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        with self._get_connection() as conn:
            r = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
            if not r:
                return None
            return Incident(
                id=r["id"],
                title=r["title"],
                description=r["description"] or "",
                status=r["status"],
                severity=r["severity"],
                started_at=r["started_at"],
                resolved_at=r["resolved_at"],
                affected_services=json.loads(r["affected_services"] or "[]"),
            )

    def save_evidence(self, evidence: NormalizedEvidence) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO evidence (id, incident_id, evidence_type, service_id, timestamp, source_type, summary, details, severity, anomaly_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    incident_id=excluded.incident_id,
                    evidence_type=excluded.evidence_type,
                    service_id=excluded.service_id,
                    timestamp=excluded.timestamp,
                    source_type=excluded.source_type,
                    summary=excluded.summary,
                    details=excluded.details,
                    severity=excluded.severity,
                    anomaly_score=excluded.anomaly_score;
                """,
                (
                    evidence.id,
                    evidence.incident_id,
                    evidence.evidence_type.value,
                    evidence.service_id,
                    evidence.timestamp,
                    evidence.source_type.value,
                    evidence.summary,
                    json.dumps(evidence.details),
                    evidence.severity.value,
                    evidence.anomaly_score,
                ),
            )

    def save_evidence_batch(self, evidence_list: List[NormalizedEvidence]) -> None:
        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO evidence (id, incident_id, evidence_type, service_id, timestamp, source_type, summary, details, severity, anomaly_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    incident_id=excluded.incident_id,
                    evidence_type=excluded.evidence_type,
                    service_id=excluded.service_id,
                    timestamp=excluded.timestamp,
                    source_type=excluded.source_type,
                    summary=excluded.summary,
                    details=excluded.details,
                    severity=excluded.severity,
                    anomaly_score=excluded.anomaly_score;
                """,
                [
                    (
                        e.id,
                        e.incident_id,
                        e.evidence_type.value,
                        e.service_id,
                        e.timestamp,
                        e.source_type.value,
                        e.summary,
                        json.dumps(e.details),
                        e.severity.value,
                        e.anomaly_score,
                    )
                    for e in evidence_list
                ],
            )

    def _row_to_evidence(self, r: sqlite3.Row) -> NormalizedEvidence:
        return NormalizedEvidence(
            id=r["id"],
            incident_id=r["incident_id"] or "",
            evidence_type=EvidenceType(r["evidence_type"]),
            service_id=r["service_id"] or "",
            timestamp=r["timestamp"],
            source_type=SourceType(r["source_type"] or "ORGANIZER"),
            summary=r["summary"],
            details=json.loads(r["details"] or "{}"),
            severity=EvidenceSeverity(r["severity"] or "INFO"),
            anomaly_score=float(r["anomaly_score"] or 0.0),
        )

    def get_evidence_by_incident(
        self, incident_id: str, evidence_type: Optional[str] = None
    ) -> List[NormalizedEvidence]:
        with self._get_connection() as conn:
            if evidence_type:
                rows = conn.execute(
                    "SELECT * FROM evidence WHERE incident_id = ? AND evidence_type = ? ORDER BY timestamp ASC",
                    (incident_id, evidence_type.upper()),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM evidence WHERE incident_id = ? ORDER BY timestamp ASC",
                    (incident_id,),
                ).fetchall()
            return [self._row_to_evidence(r) for r in rows]

    def get_evidence_by_id(self, evidence_id: str) -> Optional[NormalizedEvidence]:
        with self._get_connection() as conn:
            r = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
            if not r:
                return None
            return self._row_to_evidence(r)

    def get_all_evidence(
        self, limit: int = 200, evidence_type: Optional[str] = None
    ) -> List[NormalizedEvidence]:
        with self._get_connection() as conn:
            if evidence_type:
                rows = conn.execute(
                    "SELECT * FROM evidence WHERE evidence_type = ? ORDER BY timestamp DESC LIMIT ?",
                    (evidence_type.upper(), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM evidence ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._row_to_evidence(r) for r in rows]

    def save_candidate(self, candidate: CandidateCause) -> None:
        self.save_candidates_batch([candidate])

    def save_candidates_batch(self, candidates: List[CandidateCause]) -> None:
        if not candidates:
            return
        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO candidates (id, incident_id, service_id, title, description, candidate_type, rank, confidence_score, scoring_breakdown, supporting_evidence_ids, contradicting_evidence_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    service_id=excluded.service_id,
                    title=excluded.title,
                    description=excluded.description,
                    candidate_type=excluded.candidate_type,
                    rank=excluded.rank,
                    confidence_score=excluded.confidence_score,
                    scoring_breakdown=excluded.scoring_breakdown,
                    supporting_evidence_ids=excluded.supporting_evidence_ids,
                    contradicting_evidence_ids=excluded.contradicting_evidence_ids;
                """,
                [
                    (
                        c.id,
                        c.incident_id,
                        c.service_id,
                        c.title,
                        c.description,
                        c.candidate_type,
                        c.rank,
                        c.confidence_score,
                        json.dumps(c.scoring_breakdown),
                        json.dumps(c.supporting_evidence_ids),
                        json.dumps(c.contradicting_evidence_ids),
                    )
                    for c in candidates
                ],
            )

    def get_candidates_by_incident(self, incident_id: str) -> List[CandidateCause]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM candidates WHERE incident_id = ? ORDER BY rank ASC, confidence_score DESC",
                (incident_id,),
            ).fetchall()
            return [
                CandidateCause(
                    id=r["id"],
                    incident_id=r["incident_id"],
                    service_id=r["service_id"] or "",
                    title=r["title"],
                    description=r["description"] or "",
                    candidate_type=r["candidate_type"],
                    rank=r["rank"],
                    confidence_score=r["confidence_score"],
                    scoring_breakdown=json.loads(r["scoring_breakdown"] or "{}"),
                    supporting_evidence_ids=json.loads(r["supporting_evidence_ids"] or "[]"),
                    contradicting_evidence_ids=json.loads(r["contradicting_evidence_ids"] or "[]"),
                )
                for r in rows
            ]

    def get_all_candidates(self) -> List[CandidateCause]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM candidates ORDER BY rank ASC, confidence_score DESC"
            ).fetchall()
            return [
                CandidateCause(
                    id=r["id"],
                    incident_id=r["incident_id"],
                    service_id=r["service_id"] or "",
                    title=r["title"],
                    description=r["description"] or "",
                    candidate_type=r["candidate_type"],
                    rank=r["rank"],
                    confidence_score=r["confidence_score"],
                    scoring_breakdown=json.loads(r["scoring_breakdown"] or "{}"),
                    supporting_evidence_ids=json.loads(r["supporting_evidence_ids"] or "[]"),
                    contradicting_evidence_ids=json.loads(r["contradicting_evidence_ids"] or "[]"),
                )
                for r in rows
            ]

    def save_timeline_event(self, event: TimelineEvent) -> None:
        self.save_timeline_events_batch([event])

    def save_timeline_events_batch(self, events: List[TimelineEvent]) -> None:
        if not events:
            return
        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO timeline_events (id, incident_id, timestamp, event_type, service_id, summary, evidence_id, significance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timestamp=excluded.timestamp,
                    event_type=excluded.event_type,
                    service_id=excluded.service_id,
                    summary=excluded.summary,
                    evidence_id=excluded.evidence_id,
                    significance=excluded.significance;
                """,
                [
                    (
                        e.id,
                        e.incident_id,
                        e.timestamp,
                        e.event_type,
                        e.service_id,
                        e.summary,
                        e.evidence_id,
                        e.significance,
                    )
                    for e in events
                ],
            )

    def get_timeline_by_incident(self, incident_id: str) -> List[TimelineEvent]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM timeline_events WHERE incident_id = ? ORDER BY timestamp ASC",
                (incident_id,),
            ).fetchall()
            return [
                TimelineEvent(
                    id=r["id"],
                    incident_id=r["incident_id"],
                    timestamp=r["timestamp"],
                    event_type=r["event_type"],
                    service_id=r["service_id"] or "",
                    summary=r["summary"],
                    evidence_id=r["evidence_id"],
                    significance=r["significance"] or "MEDIUM",
                )
                for r in rows
            ]

    def save_analysis_run(self, run_data: Dict[str, Any]) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO analysis_runs (id, incident_id, status, engine_version, top_candidate_id, llm_hypothesis, llm_summary, llm_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    engine_version=excluded.engine_version,
                    top_candidate_id=excluded.top_candidate_id,
                    llm_hypothesis=excluded.llm_hypothesis,
                    llm_summary=excluded.llm_summary,
                    llm_status=excluded.llm_status;
                """,
                (
                    run_data["id"],
                    run_data["incident_id"],
                    run_data.get("status", "SUCCESS"),
                    run_data.get("engine_version", "1.0.0"),
                    run_data.get("top_candidate_id"),
                    run_data.get("llm_hypothesis", ""),
                    json.dumps(run_data.get("llm_summary", {})),
                    run_data.get("llm_status", "AVAILABLE"),
                ),
            )

    def get_latest_analysis_run(self, incident_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            r = conn.execute(
                "SELECT * FROM analysis_runs WHERE incident_id = ? ORDER BY created_at DESC LIMIT 1",
                (incident_id,),
            ).fetchone()
            if not r:
                return None
            return {
                "id": r["id"],
                "incident_id": r["incident_id"],
                "status": r["status"],
                "engine_version": r["engine_version"],
                "top_candidate_id": r["top_candidate_id"],
                "llm_hypothesis": r["llm_hypothesis"],
                "llm_summary": json.loads(r["llm_summary"] or "{}"),
                "llm_status": r["llm_status"],
                "created_at": r["created_at"],
            }

    def get_analysis_runs_count(self) -> int:
        with self._get_connection() as conn:
            r = conn.execute("SELECT count(*) FROM analysis_runs").fetchone()
            return int(r[0]) if r else 0

    def get_evidence_count(self) -> int:
        with self._get_connection() as conn:
            r = conn.execute("SELECT count(*) FROM evidence").fetchone()
            return int(r[0]) if r else 0

    def get_latest_analysis_runs_map(self) -> Dict[str, Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM analysis_runs ORDER BY created_at ASC").fetchall()
            latest_map = {}
            for r in rows:
                latest_map[r["incident_id"]] = {
                    "id": r["id"],
                    "incident_id": r["incident_id"],
                    "status": r["status"],
                    "engine_version": r["engine_version"],
                    "top_candidate_id": r["top_candidate_id"],
                    "llm_hypothesis": r["llm_hypothesis"],
                    "llm_summary": json.loads(r["llm_summary"] or "{}"),
                    "llm_status": r["llm_status"],
                    "created_at": r["created_at"],
                }
            return latest_map

    def clear_all_data(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
                DELETE FROM timeline_events;
                DELETE FROM analysis_runs;
                DELETE FROM candidates;
                DELETE FROM evidence;
                DELETE FROM dependencies;
                DELETE FROM incidents;
                DELETE FROM services;
            """)
        self.seed_default_users()

    def seed_default_users(self) -> None:
        with self._get_connection() as conn:
            row = conn.execute("SELECT count(*) FROM users").fetchone()
            count = row[0] if row else 0
            if count == 0:
                demo_users = [
                    User(
                        id="usr_admin_001",
                        username="admin",
                        password_hash=generate_password_hash(os.getenv("DEMO_ADMIN_PASSWORD", "Admin!Pass2026")),
                        role=UserRole.ADMIN,
                        email="admin@tracewise.internal",
                    ),
                    User(
                        id="usr_responder_001",
                        username="sre_responder",
                        password_hash=generate_password_hash(os.getenv("DEMO_RESPONDER_PASSWORD", "Sre!Pass2026")),
                        role=UserRole.INCIDENT_RESPONDER,
                        email="sre@tracewise.internal",
                    ),
                    User(
                        id="usr_viewer_001",
                        username="auditor_viewer",
                        password_hash=generate_password_hash(os.getenv("DEMO_VIEWER_PASSWORD", "Viewer!Pass2026")),
                        role=UserRole.VIEWER,
                        email="auditor@tracewise.internal",
                    ),
                ]
                for u in demo_users:
                    conn.execute(
                        """
                        INSERT INTO users (id, username, password_hash, role, email, is_active, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(username) DO NOTHING
                        """,
                        (u.id, u.username, u.password_hash, u.role, u.email, 1 if u.is_active else 0, u.created_at),
                    )

    def save_user(self, user: User) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (id, username, password_hash, role, email, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    username = excluded.username,
                    password_hash = excluded.password_hash,
                    role = excluded.role,
                    email = excluded.email,
                    is_active = excluded.is_active
                """,
                (user.id, user.username, user.password_hash, user.role, user.email, 1 if user.is_active else 0, user.created_at),
            )

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        with self._get_connection() as conn:
            r = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not r:
                return None
            return User(
                id=r["id"],
                username=r["username"],
                password_hash=r["password_hash"],
                role=r["role"],
                email=r["email"],
                is_active=bool(r["is_active"]),
                created_at=r["created_at"],
            )

    def get_user_by_username(self, username: str) -> Optional[User]:
        clean = (username or "").strip()
        if not clean:
            return None
        lower_clean = clean.lower()
        if lower_clean in ("sammedp63@gmail.com", "samme", "sammed", "admin"):
            clean = "admin"
        elif lower_clean in ("sre", "responder", "sre_responder"):
            clean = "sre_responder"
        elif lower_clean in ("viewer", "auditor", "auditor_viewer"):
            clean = "auditor_viewer"
        with self._get_connection() as conn:
            r = conn.execute(
                "SELECT * FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)",
                (clean, clean),
            ).fetchone()
            if not r:
                return None
            return User(
                id=r["id"],
                username=r["username"],
                password_hash=r["password_hash"],
                role=r["role"],
                email=r["email"],
                is_active=bool(r["is_active"]),
                created_at=r["created_at"],
            )

    def get_all_users(self) -> List[User]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
            return [
                User(
                    id=r["id"],
                    username=r["username"],
                    password_hash=r["password_hash"],
                    role=r["role"],
                    email=r["email"],
                    is_active=bool(r["is_active"]),
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def update_user_role(self, user_id: str, new_role: str) -> bool:
        norm_role = UserRole.normalize(new_role)
        with self._get_connection() as conn:
            cur = conn.execute("UPDATE users SET role = ? WHERE id = ?", (norm_role, user_id))
            return cur.rowcount > 0

    def update_user_status(self, user_id: str, is_active: bool) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if is_active else 0, user_id))
            return cur.rowcount > 0

    def save_audit_log(self, entry: AuditLog) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_logs (id, timestamp, user_id, username, role, action, resource_type, resource_id, result, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.id,
                    entry.timestamp,
                    entry.user_id,
                    entry.username,
                    entry.role,
                    entry.action,
                    entry.resource_type,
                    entry.resource_id,
                    entry.result,
                    json.dumps(entry.metadata or {}),
                    entry.timestamp,
                ),
            )

    def get_audit_logs(
        self, limit: int = 100, user_id: Optional[str] = None, action: Optional[str] = None
    ) -> List[AuditLog]:
        with self._get_connection() as conn:
            query = "SELECT * FROM audit_logs WHERE 1=1"
            params: List[Any] = []
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            if action:
                query += " AND action = ?"
                params.append(action)
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [
                AuditLog(
                    id=r["id"],
                    timestamp=r["timestamp"],
                    user_id=r["user_id"],
                    username=r["username"],
                    role=r["role"],
                    action=r["action"],
                    resource_type=r["resource_type"],
                    resource_id=r["resource_id"],
                    result=r["result"],
                    metadata=json.loads(r["metadata"] or "{}"),
                )
                for r in rows
            ]
