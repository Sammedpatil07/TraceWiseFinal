"""Timeline Generation for AO-03.
Generates an ordered incident timeline directly from verified NormalizedEvidence records.
Strictly derived from real telemetry; no fabricated events.
"""

from typing import List
from app.models.evidence import NormalizedEvidence, EvidenceType, EvidenceSeverity
from app.models.incident import TimelineEvent


def generate_incident_timeline(evidence_list: List[NormalizedEvidence]) -> List[TimelineEvent]:
    """Derive an ordered chronological timeline from normalized evidence."""
    if not evidence_list:
        return []

    # Sort evidence chronologically by parsed_time
    sorted_ev = sorted(evidence_list, key=lambda e: e.parsed_time)
    timeline_events: List[TimelineEvent] = []

    trigger_assigned = False

    for ev in sorted_ev:
        event_type = "EVENT"
        significance = "MEDIUM"

        if ev.evidence_type == EvidenceType.CONFIGURATION:
            event_type = "CONFIG_CHANGE"
            significance = "HIGH"
        elif ev.evidence_type == EvidenceType.DEPLOYMENT:
            event_type = "DEPLOYMENT"
            significance = "HIGH"
        elif ev.evidence_type == EvidenceType.METRIC:
            if ev.anomaly_score >= 0.7:
                event_type = "METRIC_SPIKE"
                significance = "HIGH"
            else:
                event_type = "METRIC_UPDATE"
                significance = "LOW"
        elif ev.evidence_type == EvidenceType.LOG:
            if any(w in ev.summary.lower() for w in ["restart", "recovered", "healthy", "restored"]):
                event_type = "RECOVERY"
                significance = "HIGH"
            elif ev.severity in [EvidenceSeverity.CRITICAL, EvidenceSeverity.HIGH]:
                event_type = "ERROR_SURGE"
                significance = "HIGH"
            else:
                event_type = "LOG_NOTE"
                significance = "LOW"
        elif ev.evidence_type == EvidenceType.TRACE:
            if ev.severity == EvidenceSeverity.CRITICAL or ev.details.get("error"):
                event_type = "TRACE_FAILURE"
                significance = "HIGH"
            else:
                event_type = "TRACE_SPAN"
                significance = "LOW"

        # Designate trigger event if this is early and high-impact
        if not trigger_assigned and event_type in ["CONFIG_CHANGE", "DEPLOYMENT", "METRIC_SPIKE"]:
            event_type = "TRIGGER"
            significance = "HIGH"
            trigger_assigned = True

        event = TimelineEvent(
            id=f"tl_{ev.id}",
            incident_id=ev.incident_id,
            timestamp=ev.timestamp,
            event_type=event_type,
            service_id=ev.service,
            summary=ev.summary,
            evidence_id=ev.id,  # Direct link to source evidence
            source_type=ev.source_type.value,
            severity=ev.severity.value,
            significance=significance,
        )
        timeline_events.append(event)

    return timeline_events
