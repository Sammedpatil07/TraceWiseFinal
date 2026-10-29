"""Incident and Candidate models for AO-03.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional


@dataclass
class Incident:
    id: str
    title: str
    description: str = ""
    status: str = "RESOLVED"  # "AO-03: The incident is resolved; nobody knows why"
    severity: str = "HIGH"
    started_at: str = ""
    resolved_at: Optional[str] = None
    affected_services: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Incident:
        return cls(
            id=str(data["id"]),
            title=str(data["title"]),
            description=str(data.get("description", "")),
            status=str(data.get("status", "RESOLVED")),
            severity=str(data.get("severity", "HIGH")),
            started_at=str(data.get("started_at", "")),
            resolved_at=data.get("resolved_at"),
            affected_services=list(data.get("affected_services", [])),
        )


@dataclass
class CandidateCause:
    id: str
    incident_id: str
    service_id: str
    title: str
    description: str
    candidate_type: str  # DEPLOYMENT_FAULT, CONFIG_DRIFT, RESOURCE_EXHAUSTION, CASCADING_LATENCY, DATABASE_LOCK, UPSTREAM_FAILURE, DOWNSTREAM_FAILURE, etc.
    rank: int = 1
    evidence_score: float = 0.0  # Normalized [0.0 - 1.0] Evidence Score (never called probability)
    contributing_factors: Dict[str, float] = field(default_factory=dict)
    supporting_evidence_ids: List[str] = field(default_factory=list)
    contradicting_evidence_ids: List[str] = field(default_factory=list)
    affected_services: List[str] = field(default_factory=list)
    reasoning_factors: List[str] = field(default_factory=list)

    def __init__(
        self,
        id: str,
        incident_id: str,
        service_id: str = "",
        title: str = "",
        description: str = "",
        candidate_type: str = "UNKNOWN",
        rank: int = 1,
        evidence_score: float = 0.0,
        confidence_score: Optional[float] = None,
        contributing_factors: Optional[Dict[str, float]] = None,
        scoring_breakdown: Optional[Dict[str, float]] = None,
        supporting_evidence_ids: Optional[List[str]] = None,
        contradicting_evidence_ids: Optional[List[str]] = None,
        affected_services: Optional[List[str]] = None,
        reasoning_factors: Optional[List[str]] = None,
        service: Optional[str] = None,
        **kwargs: Any,
    ):
        self.id = str(id)
        self.incident_id = str(incident_id)
        self.service_id = str(service_id or service or "")
        self.title = str(title)
        self.description = str(description)
        self.candidate_type = str(candidate_type)
        self.rank = int(rank)

        # Evidence Score (alias confidence_score)
        score_val = confidence_score if confidence_score is not None else evidence_score
        self.evidence_score = round(max(0.0, min(1.0, float(score_val))), 3)

        # Contributing factors / scoring breakdown
        self.contributing_factors = dict(contributing_factors or scoring_breakdown or {})
        self.supporting_evidence_ids = list(supporting_evidence_ids or [])
        self.contradicting_evidence_ids = list(contradicting_evidence_ids or [])
        self.affected_services = list(affected_services or [])
        self.reasoning_factors = list(reasoning_factors or [])

    @property
    def service(self) -> str:
        return self.service_id

    @property
    def confidence_score(self) -> float:
        """Backward-compatible alias for evidence_score."""
        return self.evidence_score

    @confidence_score.setter
    def confidence_score(self, val: float):
        self.evidence_score = round(max(0.0, min(1.0, float(val))), 3)

    @property
    def scoring_breakdown(self) -> Dict[str, float]:
        """Backward-compatible alias for contributing_factors."""
        return self.contributing_factors

    @scoring_breakdown.setter
    def scoring_breakdown(self, val: Dict[str, float]):
        self.contributing_factors = dict(val)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "service_id": self.service_id,
            "service": self.service_id,
            "title": self.title,
            "description": self.description,
            "candidate_type": self.candidate_type,
            "rank": self.rank,
            "evidence_score": self.evidence_score,
            "confidence_score": self.evidence_score,  # alias
            "contributing_factors": self.contributing_factors,
            "scoring_breakdown": self.contributing_factors,  # alias
            "supporting_evidence_ids": self.supporting_evidence_ids,
            "contradicting_evidence_ids": self.contradicting_evidence_ids,
            "affected_services": self.affected_services,
            "reasoning_factors": self.reasoning_factors,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CandidateCause:
        return cls(
            id=str(data["id"]),
            incident_id=str(data["incident_id"]),
            service_id=str(data.get("service_id") or data.get("service", "")),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            candidate_type=str(data.get("candidate_type", "UNKNOWN")),
            rank=int(data.get("rank", 1)),
            evidence_score=float(data.get("evidence_score") if "evidence_score" in data else data.get("confidence_score", 0.0)),
            contributing_factors=dict(data.get("contributing_factors") or data.get("scoring_breakdown", {})),
            supporting_evidence_ids=list(data.get("supporting_evidence_ids", [])),
            contradicting_evidence_ids=list(data.get("contradicting_evidence_ids", [])),
            affected_services=list(data.get("affected_services", [])),
            reasoning_factors=list(data.get("reasoning_factors", [])),
        )


@dataclass
class TimelineEvent:
    id: str
    incident_id: str
    timestamp: str
    event_type: str = "EVENT"  # TRIGGER, METRIC_SPIKE, ERROR_SURGE, DEPLOYMENT, CONFIG_CHANGE, RECOVERY
    service_id: str = ""
    summary: str = ""
    evidence_id: str = ""  # Must reference a real NormalizedEvidence ID
    source_type: str = "ORGANIZER"
    severity: str = "INFO"
    significance: str = "MEDIUM"  # HIGH, MEDIUM, LOW

    def __init__(
        self,
        id: str,
        incident_id: str,
        timestamp: str,
        event_type: str = "EVENT",
        service_id: str = "",
        summary: str = "",
        evidence_id: str = "",
        source_type: str = "ORGANIZER",
        severity: str = "INFO",
        significance: str = "MEDIUM",
        event: Optional[str] = None,
        service: Optional[str] = None,
        **kwargs: Any,
    ):
        self.id = str(id)
        self.incident_id = str(incident_id)
        self.timestamp = str(timestamp)
        self.event_type = str(event_type)
        self.service_id = str(service_id or service or "")
        self.summary = str(summary or event or "")
        self.evidence_id = str(evidence_id)
        self.source_type = str(source_type)
        self.severity = str(severity)
        self.significance = str(significance)

    @property
    def service(self) -> str:
        return self.service_id

    @property
    def event(self) -> str:
        return self.summary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "service_id": self.service_id,
            "service": self.service_id,
            "summary": self.summary,
            "event": self.summary,
            "evidence_id": self.evidence_id,
            "source_type": self.source_type,
            "severity": self.severity,
            "significance": self.significance,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TimelineEvent:
        return cls(
            id=str(data["id"]),
            incident_id=str(data["incident_id"]),
            timestamp=str(data["timestamp"]),
            event_type=str(data.get("event_type", "EVENT")),
            service_id=str(data.get("service_id") or data.get("service", "")),
            summary=str(data.get("summary") or data.get("event", "")),
            evidence_id=str(data["evidence_id"]),
            source_type=str(data.get("source_type", "ORGANIZER")),
            severity=str(data.get("severity", "INFO")),
            significance=str(data.get("significance", "MEDIUM")),
        )


@dataclass
class AnalysisResult:
    incident_id: str
    status: str  # "SUCCESS", "INSUFFICIENT_EVIDENCE", "FAILED"
    top_candidate: Optional[CandidateCause] = None
    ranked_candidates: List[CandidateCause] = field(default_factory=list)
    timeline: List[TimelineEvent] = field(default_factory=list)
    correlations: List[Dict[str, Any]] = field(default_factory=list)
    llm_hypothesis: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    is_insufficient_evidence: bool = False

    def __post_init__(self):
        if self.status == "INSUFFICIENT_EVIDENCE":
            self.is_insufficient_evidence = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "status": self.status,
            "is_insufficient_evidence": self.status == "INSUFFICIENT_EVIDENCE",
            "top_candidate": self.top_candidate.to_dict() if self.top_candidate else None,
            "ranked_candidates": [c.to_dict() for c in self.ranked_candidates],
            "timeline": [t.to_dict() for t in self.timeline],
            "correlations": self.correlations,
            "llm_hypothesis": self.llm_hypothesis,
            "reason": self.reason,
        }
