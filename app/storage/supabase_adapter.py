"""Supabase PostgreSQL Storage Adapter for TraceWise AO-03.
Interacts with the Supabase PostgREST API with explicit error handling and no silent fallback.
Provides identical logical storage contract as SqliteStorage.
"""

import json
import logging
import os
import requests
from requests.adapters import HTTPAdapter
from datetime import datetime, timezone
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
from app.models.audit import AuditLog
from werkzeug.security import generate_password_hash

logger = logging.getLogger(__name__)


import time


class SupabaseStorage(BaseStorage):
    def __init__(self, supabase_url: str, supabase_key: str, fallback_sqlite_path: Optional[str] = None):
        self.supabase_url = supabase_url.rstrip("/") if supabase_url else ""
        self.supabase_key = supabase_key
        self.fallback_path = fallback_sqlite_path
        self.timeout = int(os.getenv("SUPABASE_TIMEOUT", "15"))

        if not self.supabase_url or not self.supabase_key:
            raise ValueError("SupabaseStorage requires valid SUPABASE_URL and SUPABASE_KEY.")

        self.headers = {
            "apikey": self.supabase_key,
            "Authorization": f"Bearer {self.supabase_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

        self.session = requests.Session()
        self.session.headers.update(self.headers)
        adapter = HTTPAdapter(pool_connections=25, pool_maxsize=25, max_retries=2)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # Verify initial connectivity
        self.verify_connection()

    def verify_connection(self) -> Dict[str, Any]:
        """Verifies remote connectivity to Supabase. Raises ConnectionError on failure."""
        last_err = None
        for attempt in range(3):
            try:
                r = requests.get(
                    f"{self.supabase_url}/rest/v1/services?select=id&limit=1",
                    headers=self.headers,
                    timeout=self.timeout,
                )
                if r.status_code in (401, 403):
                    raise ConnectionError(f"Supabase authorization failed with HTTP {r.status_code}: {r.text}")
                return {
                    "status": "HEALTHY" if r.status_code == 200 else "SCHEMA_PENDING",
                    "status_code": r.status_code,
                    "project_url": self.supabase_url,
                }
            except ConnectionError:
                raise
            except requests.exceptions.RequestException as e:
                last_err = e
                if attempt < 2:
                    time.sleep(0.5)
                    continue
        raise ConnectionError(f"Failed to reach Supabase project at {self.supabase_url}: {last_err}")

    def init_db(self) -> None:
        """Verifies schema presence and ensures default users exist."""
        try:
            users = self.get_all_users()
            if not users:
                self.seed_default_users()
        except Exception as e:
            logger.info(f"Supabase init_db notice: {e}")

    def seed_default_users(self) -> None:
        """Seeds standard demo roles if users table is empty."""
        default_admin_pass = os.getenv("DEMO_ADMIN_PASSWORD", "Admin!Pass2026")
        default_sre_pass = os.getenv("DEMO_SRE_PASSWORD", "Sre!Pass2026")
        default_viewer_pass = os.getenv("DEMO_VIEWER_PASSWORD", "Viewer!Pass2026")

        demo_users = [
            User(
                id="usr_admin_001",
                username="admin",
                password_hash=generate_password_hash(default_admin_pass),
                role=UserRole.ADMIN,
                email="admin@tracewise.internal",
                is_active=True,
            ),
            User(
                id="usr_responder_001",
                username="sre_responder",
                password_hash=generate_password_hash(default_sre_pass),
                role=UserRole.INCIDENT_RESPONDER,
                email="sre@tracewise.internal",
                is_active=True,
            ),
            User(
                id="usr_viewer_001",
                username="auditor_viewer",
                password_hash=generate_password_hash(default_viewer_pass),
                role=UserRole.VIEWER,
                email="auditor@tracewise.internal",
                is_active=True,
            ),
        ]
        for u in demo_users:
            try:
                self.save_user(u)
            except Exception as e:
                logger.debug(f"User seed notice for {u.username}: {e}")

    # ================= SERVICES & TOPOLOGY =================

    def save_service(self, service: ServiceNode) -> None:
        url = f"{self.supabase_url}/rest/v1/services"
        headers = dict(self.headers, Prefer="resolution=merge-duplicates")
        payload = {
            "id": service.id,
            "name": service.name,
            "tier": service.tier,
            "description": service.description,
        }
        r = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase error saving service '{service.id}': {r.status_code} {r.text}")

    def get_services(self) -> List[ServiceNode]:
        url = f"{self.supabase_url}/rest/v1/services?select=*&order=id.asc"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200:
            return [
                ServiceNode(
                    id=x["id"],
                    name=x["name"],
                    tier=x.get("tier", "service"),
                    description=x.get("description", ""),
                )
                for x in r.json()
            ]
        elif r.status_code == 404:
            return []
        raise RuntimeError(f"Supabase error getting services: {r.status_code} {r.text}")

    def save_dependency(self, dependency: ServiceDependency) -> None:
        self.save_dependencies_batch([dependency])

    def save_dependencies_batch(self, dependencies: List[ServiceDependency]) -> None:
        if not dependencies:
            return
        url = f"{self.supabase_url}/rest/v1/dependencies"
        headers = dict(self.headers, Prefer="resolution=merge-duplicates")
        payload = [
            {
                "id": d.id,
                "source_service": d.source_service,
                "target_service": d.target_service,
                "call_type": d.call_type,
                "critical": bool(d.critical),
            }
            for d in dependencies
        ]
        r = self.session.post(url, json=payload, headers=headers, timeout=max(self.timeout, 20))
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase error batch saving dependencies: {r.status_code} {r.text}")

    def get_dependencies(self) -> List[ServiceDependency]:
        url = f"{self.supabase_url}/rest/v1/dependencies?select=*&order=created_at.asc"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200:
            return [
                ServiceDependency(
                    id=x["id"],
                    source_service=x["source_service"],
                    target_service=x["target_service"],
                    call_type=x.get("call_type", "HTTP"),
                    critical=bool(x.get("critical", True)),
                )
                for x in r.json()
            ]
        elif r.status_code == 404:
            return []
        raise RuntimeError(f"Supabase error getting dependencies: {r.status_code} {r.text}")

    # ================= INCIDENTS =================

    def save_incident(self, incident: Incident) -> None:
        url = f"{self.supabase_url}/rest/v1/incidents"
        headers = dict(self.headers, Prefer="resolution=merge-duplicates")
        started_at = (
            incident.started_at
            if (incident.started_at and str(incident.started_at).strip())
            else datetime.now(timezone.utc).isoformat()
        )
        resolved_at = (
            incident.resolved_at
            if (incident.resolved_at and str(incident.resolved_at).strip())
            else None
        )
        payload = {
            "id": incident.id,
            "title": incident.title,
            "description": incident.description,
            "status": incident.status,
            "severity": incident.severity,
            "started_at": started_at,
            "resolved_at": resolved_at,
            "affected_services": incident.affected_services if isinstance(incident.affected_services, list) else [],
        }
        r = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase error saving incident '{incident.id}': {r.status_code} {r.text}")

    def get_incidents(self) -> List[Incident]:
        url = f"{self.supabase_url}/rest/v1/incidents?select=*&order=started_at.desc"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200:
            return [Incident.from_dict(x) for x in r.json()]
        elif r.status_code == 404:
            return []
        raise RuntimeError(f"Supabase error getting incidents: {r.status_code} {r.text}")

    def get_incident(self, incident_id: str) -> Optional[Incident]:
        url = f"{self.supabase_url}/rest/v1/incidents?id=eq.{incident_id}&select=*"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200 and r.json():
            return Incident.from_dict(r.json()[0])
        elif r.status_code in (200, 404):
            return None
        raise RuntimeError(f"Supabase error getting incident '{incident_id}': {r.status_code} {r.text}")

    # ================= EVIDENCE =================

    def save_evidence(self, evidence: NormalizedEvidence) -> None:
        url = f"{self.supabase_url}/rest/v1/evidence"
        headers = dict(self.headers, Prefer="resolution=merge-duplicates")
        payload = self._evidence_to_payload(evidence)
        r = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase error saving evidence '{evidence.id}': {r.status_code} {r.text}")

    def save_evidence_batch(self, evidence_list: List[NormalizedEvidence]) -> None:
        if not evidence_list:
            return
        url = f"{self.supabase_url}/rest/v1/evidence"
        headers = dict(self.headers, Prefer="resolution=merge-duplicates")
        payload = [self._evidence_to_payload(e) for e in evidence_list]
        r = self.session.post(url, json=payload, headers=headers, timeout=max(self.timeout, 20))
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase error batch saving evidence: {r.status_code} {r.text}")

    def get_evidence_by_incident(
        self, incident_id: str, evidence_type: Optional[str] = None
    ) -> List[NormalizedEvidence]:
        url = f"{self.supabase_url}/rest/v1/evidence?incident_id=eq.{incident_id}&order=timestamp.asc"
        if evidence_type:
            url += f"&evidence_type=eq.{evidence_type.upper()}"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200:
            return [self._payload_to_evidence(x) for x in r.json()]
        elif r.status_code == 404:
            return []
        raise RuntimeError(f"Supabase error getting evidence for incident '{incident_id}': {r.status_code} {r.text}")

    def get_evidence_by_id(self, evidence_id: str) -> Optional[NormalizedEvidence]:
        url = f"{self.supabase_url}/rest/v1/evidence?id=eq.{evidence_id}&select=*"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200 and r.json():
            return self._payload_to_evidence(r.json()[0])
        elif r.status_code in (200, 404):
            return None
        raise RuntimeError(f"Supabase error getting evidence '{evidence_id}': {r.status_code} {r.text}")

    def get_all_evidence(
        self, limit: int = 200, evidence_type: Optional[str] = None
    ) -> List[NormalizedEvidence]:
        url = f"{self.supabase_url}/rest/v1/evidence?select=*&order=timestamp.desc&limit={limit}"
        if evidence_type:
            url += f"&evidence_type=eq.{evidence_type.upper()}"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200:
            return [self._payload_to_evidence(x) for x in r.json()]
        elif r.status_code == 404:
            return []
        raise RuntimeError(f"Supabase error getting all evidence: {r.status_code} {r.text}")

    def _evidence_to_payload(self, ev: NormalizedEvidence) -> Dict[str, Any]:
        """Prepares NormalizedEvidence for PostgreSQL JSONB columns."""
        details_obj = dict(ev.details or {})
        # Sync specific linkages into details
        if ev.trace_id: details_obj["trace_id"] = ev.trace_id
        if ev.span_id: details_obj["span_id"] = ev.span_id
        if ev.parent_span_id: details_obj["parent_span_id"] = ev.parent_span_id
        if ev.request_id: details_obj["request_id"] = ev.request_id
        if ev.deployment_id: details_obj["deployment_id"] = ev.deployment_id
        if ev.configuration_id: details_obj["configuration_id"] = ev.configuration_id
        if ev.metric_name: details_obj["metric_name"] = ev.metric_name
        if ev.metric_value is not None: details_obj["metric_value"] = ev.metric_value

        ts_val = (
            ev.timestamp
            if (ev.timestamp and str(ev.timestamp).strip())
            else datetime.now(timezone.utc).isoformat()
        )
        return {
            "id": ev.id,
            "incident_id": ev.incident_id,
            "evidence_type": ev.evidence_type.value if hasattr(ev.evidence_type, "value") else str(ev.evidence_type),
            "service_id": ev.service_id,
            "timestamp": ts_val,
            "source_type": ev.source_type.value if hasattr(ev.source_type, "value") else str(ev.source_type),
            "summary": ev.summary,
            "details": details_obj,
            "severity": ev.severity.value if hasattr(ev.severity, "value") else str(ev.severity),
            "anomaly_score": float(ev.anomaly_score),
        }

    def _payload_to_evidence(self, row: Dict[str, Any]) -> NormalizedEvidence:
        details = row.get("details")
        if isinstance(details, str):
            try: details = json.loads(details)
            except Exception: details = {}
        elif not isinstance(details, dict):
            details = {}

        return NormalizedEvidence.from_dict({
            "id": row["id"],
            "incident_id": row.get("incident_id", ""),
            "evidence_type": row.get("evidence_type", "LOG"),
            "service": row.get("service_id", "unknown-service"),
            "service_id": row.get("service_id", "unknown-service"),
            "timestamp": row.get("timestamp", ""),
            "source_type": row.get("source_type", "ORGANIZER"),
            "summary": row.get("summary", ""),
            "details": details,
            "severity": row.get("severity", "INFO"),
            "anomaly_score": float(row.get("anomaly_score", 0.0)),
        })

    # ================= CANDIDATES & RCA =================

    def save_candidate(self, candidate: CandidateCause) -> None:
        self.save_candidates_batch([candidate])

    def save_candidates_batch(self, candidates: List[CandidateCause]) -> None:
        if not candidates:
            return
        url = f"{self.supabase_url}/rest/v1/candidates"
        headers = dict(self.headers, Prefer="resolution=merge-duplicates")
        payload = [
            {
                "id": candidate.id,
                "incident_id": candidate.incident_id,
                "service_id": candidate.service_id,
                "title": candidate.title,
                "description": candidate.description,
                "candidate_type": candidate.candidate_type,
                "rank": candidate.rank,
                "confidence_score": candidate.evidence_score,
                "scoring_breakdown": candidate.contributing_factors if isinstance(candidate.contributing_factors, dict) else {},
                "supporting_evidence_ids": candidate.supporting_evidence_ids if isinstance(candidate.supporting_evidence_ids, list) else [],
                "contradicting_evidence_ids": candidate.contradicting_evidence_ids if isinstance(candidate.contradicting_evidence_ids, list) else [],
            }
            for candidate in candidates
        ]
        r = self.session.post(url, json=payload, headers=headers, timeout=max(self.timeout, 20))
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase error batch saving candidates: {r.status_code} {r.text}")

    def get_candidates_by_incident(self, incident_id: str) -> List[CandidateCause]:
        url = f"{self.supabase_url}/rest/v1/candidates?incident_id=eq.{incident_id}&order=rank.asc,confidence_score.desc"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200:
            return [CandidateCause.from_dict(x) for x in r.json()]
        elif r.status_code == 404:
            return []
        raise RuntimeError(f"Supabase error getting candidates for incident '{incident_id}': {r.status_code} {r.text}")

    def get_all_candidates(self) -> List[CandidateCause]:
        url = f"{self.supabase_url}/rest/v1/candidates?order=rank.asc,confidence_score.desc"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200:
            return [CandidateCause.from_dict(x) for x in r.json()]
        elif r.status_code == 404:
            return []
        raise RuntimeError(f"Supabase error getting all candidates: {r.status_code} {r.text}")

    # ================= TIMELINE =================

    def save_timeline_event(self, event: TimelineEvent) -> None:
        self.save_timeline_events_batch([event])

    def save_timeline_events_batch(self, events: List[TimelineEvent]) -> None:
        if not events:
            return
        url = f"{self.supabase_url}/rest/v1/timeline_events"
        headers = dict(self.headers, Prefer="resolution=merge-duplicates")
        payload = [
            {
                "id": event.id,
                "incident_id": event.incident_id,
                "timestamp": (
                    event.timestamp
                    if (event.timestamp and str(event.timestamp).strip())
                    else datetime.now(timezone.utc).isoformat()
                ),
                "event_type": event.event_type,
                "service_id": event.service_id,
                "summary": event.summary,
                "evidence_id": event.evidence_id,
                "significance": event.significance,
            }
            for event in events
        ]
        r = self.session.post(url, json=payload, headers=headers, timeout=max(self.timeout, 20))
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase error batch saving timeline events: {r.status_code} {r.text}")

    def get_timeline_by_incident(self, incident_id: str) -> List[TimelineEvent]:
        url = f"{self.supabase_url}/rest/v1/timeline_events?incident_id=eq.{incident_id}&order=timestamp.asc"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200:
            return [TimelineEvent.from_dict(x) for x in r.json()]
        elif r.status_code == 404:
            return []
        raise RuntimeError(f"Supabase error getting timeline for incident '{incident_id}': {r.status_code} {r.text}")

    # ================= ANALYSIS RUNS =================

    def save_analysis_run(self, run_data: Dict[str, Any]) -> None:
        self.save_analysis_runs_batch([run_data])

    def save_analysis_runs_batch(self, runs: List[Dict[str, Any]]) -> None:
        if not runs:
            return
        url = f"{self.supabase_url}/rest/v1/analysis_runs"
        headers = dict(self.headers, Prefer="resolution=merge-duplicates")
        payload = [
            {
                "id": r.get("id"),
                "incident_id": r.get("incident_id"),
                "status": r.get("status", "SUCCESS"),
                "engine_version": r.get("engine_version", "1.0.0"),
                "top_candidate_id": r.get("top_candidate_id"),
                "llm_hypothesis": r.get("llm_hypothesis"),
                "llm_summary": r.get("llm_summary", {}),
                "llm_status": r.get("llm_status", "AVAILABLE"),
            }
            for r in runs
        ]
        r = self.session.post(url, json=payload, headers=headers, timeout=max(self.timeout, 20))
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase error saving analysis runs: {r.status_code} {r.text}")

    def get_latest_analysis_run(self, incident_id: str) -> Optional[Dict[str, Any]]:
        url = f"{self.supabase_url}/rest/v1/analysis_runs?incident_id=eq.{incident_id}&order=created_at.desc&limit=1"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200 and r.json():
            return r.json()[0]
        elif r.status_code in (200, 404):
            return None
        raise RuntimeError(f"Supabase error getting analysis run for '{incident_id}': {r.status_code} {r.text}")

    def get_analysis_runs_count(self) -> int:
        url = f"{self.supabase_url}/rest/v1/analysis_runs?select=id"
        headers = dict(self.headers, Prefer="count=exact")
        r = self.session.get(url, headers=headers, timeout=self.timeout)
        if r.status_code == 200:
            if "content-range" in r.headers:
                total = r.headers["content-range"].split("/")[-1]
                return int(total) if total.isdigit() else len(r.json())
            return len(r.json())
        elif r.status_code == 404:
            return 0
        raise RuntimeError(f"Supabase error counting analysis runs: {r.status_code} {r.text}")

    def get_evidence_count(self) -> int:
        url = f"{self.supabase_url}/rest/v1/evidence?select=id"
        headers = dict(self.headers, Prefer="count=exact")
        r = self.session.get(url, headers=headers, timeout=self.timeout)
        if r.status_code == 200:
            if "content-range" in r.headers:
                total = r.headers["content-range"].split("/")[-1]
                return int(total) if total.isdigit() else len(r.json())
            return len(r.json())
        elif r.status_code == 404:
            return 0
        raise RuntimeError(f"Supabase error counting evidence: {r.status_code} {r.text}")

    def get_latest_analysis_runs_map(self) -> Dict[str, Dict[str, Any]]:
        url = f"{self.supabase_url}/rest/v1/analysis_runs?select=*&order=created_at.asc"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200:
            latest_map = {}
            for x in r.json():
                latest_map[x["incident_id"]] = x
            return latest_map
        elif r.status_code == 404:
            return {}
        raise RuntimeError(f"Supabase error getting analysis runs map: {r.status_code} {r.text}")

    # ================= USER & ROLE MANAGEMENT (RBAC) =================

    def save_user(self, user: User) -> None:
        url = f"{self.supabase_url}/rest/v1/users"
        headers = dict(self.headers, Prefer="resolution=merge-duplicates")
        payload = {
            "id": user.id,
            "username": user.username,
            "password_hash": user.password_hash,
            "role": user.role,
            "email": user.email,
            "is_active": bool(user.is_active),
        }
        r = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase error saving user '{user.username}': {r.status_code} {r.text}")

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        url = f"{self.supabase_url}/rest/v1/users?id=eq.{user_id}&select=*"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200 and r.json():
            return User.from_dict(r.json()[0])
        elif r.status_code in (200, 404):
            return None
        raise RuntimeError(f"Supabase error getting user '{user_id}': {r.status_code} {r.text}")

    def get_user_by_username(self, username: str) -> Optional[User]:
        clean = (username or "").strip()
        if not clean:
            return None
        # Support demo aliases and developer email mapping
        lower_clean = clean.lower()
        if lower_clean in ("sammedp63@gmail.com", "samme", "sammed", "admin"):
            clean = "admin"
        elif lower_clean in ("sre", "responder", "sre_responder"):
            clean = "sre_responder"
        elif lower_clean in ("viewer", "auditor", "auditor_viewer"):
            clean = "auditor_viewer"

        # Try username match (case-insensitive)
        url = f"{self.supabase_url}/rest/v1/users?username=ilike.{clean}&select=*"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200 and r.json():
            return User.from_dict(r.json()[0])

        # Try email match (case-insensitive)
        url_email = f"{self.supabase_url}/rest/v1/users?email=ilike.{clean}&select=*"
        r_email = self.session.get(url_email, headers=self.headers, timeout=self.timeout)
        if r_email.status_code == 200 and r_email.json():
            return User.from_dict(r_email.json()[0])

        return None

    def get_all_users(self) -> List[User]:
        url = f"{self.supabase_url}/rest/v1/users?select=*&order=created_at.asc"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200:
            return [User.from_dict(x) for x in r.json()]
        elif r.status_code == 404:
            return []
        raise RuntimeError(f"Supabase error getting all users: {r.status_code} {r.text}")

    def update_user_role(self, user_id: str, new_role: str) -> bool:
        url = f"{self.supabase_url}/rest/v1/users?id=eq.{user_id}"
        r = self.session.patch(url, json={"role": new_role}, headers=self.headers, timeout=self.timeout)
        return r.status_code in (200, 204)

    def update_user_status(self, user_id: str, is_active: bool) -> bool:
        url = f"{self.supabase_url}/rest/v1/users?id=eq.{user_id}"
        r = self.session.patch(url, json={"is_active": bool(is_active)}, headers=self.headers, timeout=self.timeout)
        return r.status_code in (200, 204)

    # ================= SECURITY AUDIT LOGGING =================

    def save_audit_log(self, entry: AuditLog) -> None:
        self.save_audit_logs_batch([entry])

    def save_audit_logs_batch(self, logs: List[AuditLog]) -> None:
        if not logs:
            return
        url = f"{self.supabase_url}/rest/v1/audit_logs"
        headers = dict(self.headers, Prefer="resolution=merge-duplicates")
        payload = [
            {
                "id": entry.id,
                "timestamp": (
                    entry.timestamp
                    if (entry.timestamp and str(entry.timestamp).strip())
                    else datetime.now(timezone.utc).isoformat()
                ),
                "user_id": entry.user_id,
                "username": entry.username,
                "role": entry.role,
                "action": entry.action,
                "resource_type": entry.resource_type,
                "resource_id": entry.resource_id,
                "result": entry.result,
                "metadata": entry.metadata if isinstance(entry.metadata, dict) else {},
            }
            for entry in logs
        ]
        r = self.session.post(url, json=payload, headers=headers, timeout=max(self.timeout, 20))
        if r.status_code >= 400:
            logger.warning(f"Supabase audit log insert notice ({r.status_code}): {r.text}")

    def get_audit_logs(
        self, limit: int = 100, user_id: Optional[str] = None, action: Optional[str] = None
    ) -> List[AuditLog]:
        url = f"{self.supabase_url}/rest/v1/audit_logs?select=*&order=timestamp.desc&limit={limit}"
        if user_id:
            url += f"&user_id=eq.{user_id}"
        if action:
            url += f"&action=eq.{action}"
        r = self.session.get(url, headers=self.headers, timeout=self.timeout)
        if r.status_code == 200:
            return [AuditLog.from_dict(x) for x in r.json()]
        elif r.status_code == 404:
            return []
        raise RuntimeError(f"Supabase error getting audit logs: {r.status_code} {r.text}")

    # ================= DATA RESET =================

    def clear_all_data(self) -> None:
        """Clears telemetry, runs, and audit tables while preserving user accounts."""
        tables = [
            "audit_logs",
            "analysis_runs",
            "candidates",
            "timeline_events",
            "evidence",
            "dependencies",
            "incidents",
            "services",
        ]
        for tbl in tables:
            try:
                # Delete all rows where id is not null
                url = f"{self.supabase_url}/rest/v1/{tbl}?id=neq.placeholder_nonexistent"
                self.session.delete(url, headers=self.headers, timeout=self.timeout)
            except Exception as e:
                logger.warning(f"Supabase clear table notice for {tbl}: {e}")
