"""Base Storage Interface for AO-03.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from app.models.evidence import NormalizedEvidence, ServiceNode, ServiceDependency
from app.models.incident import Incident, CandidateCause, TimelineEvent
from app.models.user import User
from app.models.audit import AuditLog


class BaseStorage(ABC):
    @abstractmethod
    def init_db(self) -> None:
        pass

    @abstractmethod
    def save_service(self, service: ServiceNode) -> None:
        pass

    @abstractmethod
    def get_services(self) -> List[ServiceNode]:
        pass

    @abstractmethod
    def save_dependency(self, dependency: ServiceDependency) -> None:
        pass

    @abstractmethod
    def get_dependencies(self) -> List[ServiceDependency]:
        pass

    @abstractmethod
    def save_incident(self, incident: Incident) -> None:
        pass

    @abstractmethod
    def get_incidents(self) -> List[Incident]:
        pass

    @abstractmethod
    def get_incident(self, incident_id: str) -> Optional[Incident]:
        pass

    @abstractmethod
    def save_evidence(self, evidence: NormalizedEvidence) -> None:
        pass

    @abstractmethod
    def save_evidence_batch(self, evidence_list: List[NormalizedEvidence]) -> None:
        pass

    @abstractmethod
    def get_evidence_by_incident(
        self, incident_id: str, evidence_type: Optional[str] = None
    ) -> List[NormalizedEvidence]:
        pass

    @abstractmethod
    def get_evidence_by_id(self, evidence_id: str) -> Optional[NormalizedEvidence]:
        pass

    @abstractmethod
    def get_all_evidence(
        self, limit: int = 200, evidence_type: Optional[str] = None
    ) -> List[NormalizedEvidence]:
        pass

    @abstractmethod
    def get_evidence_count(self) -> int:
        pass

    @abstractmethod
    def get_latest_analysis_runs_map(self) -> Dict[str, Dict[str, Any]]:
        pass

    @abstractmethod
    def save_candidate(self, candidate: CandidateCause) -> None:
        pass

    def save_candidates_batch(self, candidates: List[CandidateCause]) -> None:
        for c in candidates:
            self.save_candidate(c)

    @abstractmethod
    def get_candidates_by_incident(self, incident_id: str) -> List[CandidateCause]:
        pass

    @abstractmethod
    def get_all_candidates(self) -> List[CandidateCause]:
        pass

    @abstractmethod
    def save_timeline_event(self, event: TimelineEvent) -> None:
        pass

    def save_timeline_events_batch(self, events: List[TimelineEvent]) -> None:
        for e in events:
            self.save_timeline_event(e)

    def save_dependencies_batch(self, dependencies: List[ServiceDependency]) -> None:
        for d in dependencies:
            self.save_dependency(d)

    @abstractmethod
    def get_timeline_by_incident(self, incident_id: str) -> List[TimelineEvent]:
        pass

    @abstractmethod
    def save_analysis_run(self, run_data: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    def get_latest_analysis_run(self, incident_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_analysis_runs_count(self) -> int:
        pass

    @abstractmethod
    def save_user(self, user: User) -> None:
        pass

    @abstractmethod
    def get_user_by_id(self, user_id: str) -> Optional[User]:
        pass

    @abstractmethod
    def get_user_by_username(self, username: str) -> Optional[User]:
        pass

    @abstractmethod
    def get_all_users(self) -> List[User]:
        pass

    @abstractmethod
    def update_user_role(self, user_id: str, new_role: str) -> bool:
        pass

    @abstractmethod
    def update_user_status(self, user_id: str, is_active: bool) -> bool:
        pass

    @abstractmethod
    def save_audit_log(self, entry: AuditLog) -> None:
        pass

    @abstractmethod
    def get_audit_logs(
        self, limit: int = 100, user_id: Optional[str] = None, action: Optional[str] = None
    ) -> List[AuditLog]:
        pass

    @abstractmethod
    def clear_all_data(self) -> None:
        pass
