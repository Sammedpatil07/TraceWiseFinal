"""Main Deterministic Root Cause Analysis (RCA) Engine for AO-03.
Coordinates ingestion retrieval, graph analysis, scoring, timeline generation,
and LLM explanation orchestration.
"""

from typing import Optional, Dict, Any, List
import uuid

from app.config import Config
from app.storage.base import BaseStorage
from app.models.incident import Incident, CandidateCause, TimelineEvent, AnalysisResult
from app.models.evidence import NormalizedEvidence, EvidenceType
from app.engine.dependency_graph import DependencyGraphManager
from app.engine.timeline import generate_incident_timeline
from app.engine.correlation import CorrelationEngine
from app.engine.validator import EvidenceValidator
from app.llm.explanation import ExplanationService


class RCAEngine:
    def __init__(self, storage: BaseStorage):
        self.storage = storage
        self.explanation_service = ExplanationService()

    def run_rca(self, incident_id: str, trigger_llm: bool = True) -> AnalysisResult:
        """Executes end-to-end Root Cause Analysis for a given incident."""
        incident = self.storage.get_incident(incident_id)
        if not incident:
            return AnalysisResult(
                incident_id=incident_id,
                status="FAILED",
                reason=f"Incident '{incident_id}' not found.",
            )

        # 1. Fetch topology
        services = self.storage.get_services()
        dependencies = self.storage.get_dependencies()
        graph_manager = DependencyGraphManager(services, dependencies)

        # 2. Fetch all incident evidence
        evidence_list = self.storage.get_evidence_by_incident(incident_id)

        # Enforce incident ownership validation
        valid_evidence_list, mismatched = EvidenceValidator.check_evidence_incident_ownership(
            evidence_list, incident_id
        )
        valid_evidence_ids = {e.id for e in valid_evidence_list}

        # 3. Check for Insufficient Evidence condition (zero records)
        if not valid_evidence_list:
            reason = "UNKNOWN / INSUFFICIENT EVIDENCE: No telemetry records exist for this incident."
            result = AnalysisResult(
                incident_id=incident_id,
                status="INSUFFICIENT_EVIDENCE",
                reason=reason,
            )
            self._save_run(incident_id, "INSUFFICIENT_EVIDENCE", None, None, reason)
            return result

        # 4. Trace-inferred dependency discovery
        inferred_deps = graph_manager.infer_dependencies_from_traces(valid_evidence_list)
        if inferred_deps:
            self.storage.save_dependencies_batch(inferred_deps)

        # 5. Generate Timeline
        timeline_events = generate_incident_timeline(valid_evidence_list)
        if timeline_events:
            self.storage.save_timeline_events_batch(timeline_events)

        # 6. Deterministic Candidate Evaluation & Evidence Correlations
        correlation_engine = CorrelationEngine(graph_manager)
        correlations = correlation_engine.find_all_correlations(valid_evidence_list)
        candidates = correlation_engine.evaluate_candidates(incident, valid_evidence_list)
        has_conflicting = correlation_engine.has_conflicting_evidence

        # Validate candidate evidence IDs
        for cand in candidates:
            EvidenceValidator.validate_candidate_evidence(cand, valid_evidence_ids)
        if candidates:
            self.storage.save_candidates_batch(candidates)

        # 7. Check for Insufficient or Conflicting Evidence
        top_cand = candidates[0] if candidates else None

        if has_conflicting:
            reason = (
                "UNKNOWN / INSUFFICIENT EVIDENCE: Conflicting telemetry evidence detected between multiple independent candidate services "
                f"('{candidates[0].service_id}' and '{candidates[1].service_id}') with ambiguous causal scores ({candidates[0].evidence_score:.2f} vs {candidates[1].evidence_score:.2f})."
            )
            result = AnalysisResult(
                incident_id=incident_id,
                status="INSUFFICIENT_EVIDENCE",
                top_candidate=top_cand,
                ranked_candidates=candidates,
                timeline=timeline_events,
                correlations=[c.to_dict() for c in correlations],
                reason=reason,
            )
            self._save_run(incident_id, "INSUFFICIENT_EVIDENCE", top_cand.id if top_cand else None, None, reason)
            return result

        if not top_cand or top_cand.evidence_score < Config.MIN_CONFIDENCE_THRESHOLD:
            reason = (
                f"UNKNOWN / INSUFFICIENT EVIDENCE: Top candidate Evidence Score ({top_cand.evidence_score if top_cand else 0.0:.2f}) "
                f"is below the minimum threshold ({Config.MIN_CONFIDENCE_THRESHOLD}). Causal evidence is inconclusive."
            )
            result = AnalysisResult(
                incident_id=incident_id,
                status="INSUFFICIENT_EVIDENCE",
                top_candidate=top_cand,
                ranked_candidates=candidates,
                timeline=timeline_events,
                correlations=[c.to_dict() for c in correlations],
                reason=reason,
            )
            self._save_run(incident_id, "INSUFFICIENT_EVIDENCE", top_cand.id if top_cand else None, None, reason)
            return result

        # 8. LLM Explanation Layer (if enabled)
        llm_hypothesis: Optional[Dict[str, Any]] = None
        llm_status = "DISABLED"

        if trigger_llm:
            try:
                raw_hypothesis, status = self.explanation_service.generate_explanation(
                    incident=incident,
                    top_candidate=top_cand,
                    ranked_candidates=candidates,
                    timeline=timeline_events,
                    evidence_list=valid_evidence_list,
                )
                llm_status = status
                # Evidence validation: Ensure all cited evidence exists
                _, _, validated_hypothesis = EvidenceValidator.validate_llm_hypothesis(
                    raw_hypothesis, valid_evidence_ids
                )
                llm_hypothesis = validated_hypothesis
            except Exception as e:
                llm_status = "ERROR"
                llm_hypothesis = {
                    "header": "AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING",
                    "incident_summary": incident.description,
                    "most_likely_cause": top_cand.title,
                    "confidence_explanation": f"Deterministic score: {top_cand.evidence_score:.2f}",
                    "unknowns": f"LLM generation failed: {str(e)}",
                    "hypothesis_status": "HEURISTIC_ONLY",
                }

        # 9. Persist Analysis Run
        self._save_run(
            incident_id=incident_id,
            status="SUCCESS",
            top_candidate_id=top_cand.id if top_cand else None,
            llm_summary=llm_hypothesis,
            llm_status=llm_status,
        )

        return AnalysisResult(
            incident_id=incident_id,
            status="SUCCESS",
            top_candidate=top_cand,
            ranked_candidates=candidates,
            timeline=timeline_events,
            correlations=[c.to_dict() for c in correlations],
            llm_hypothesis=llm_hypothesis,
        )

    def _save_run(
        self,
        incident_id: str,
        status: str,
        top_candidate_id: Optional[str],
        llm_summary: Optional[Dict[str, Any]],
        reason: Optional[str] = None,
        llm_status: str = "AVAILABLE",
    ) -> None:
        run_data = {
            "id": f"run_{uuid.uuid4().hex[:8]}",
            "incident_id": incident_id,
            "status": status,
            "engine_version": "1.0.0",
            "top_candidate_id": top_candidate_id,
            "llm_hypothesis": reason or (llm_summary.get("most_likely_cause") if llm_summary else ""),
            "llm_summary": llm_summary or {},
            "llm_status": llm_status,
        }
        self.storage.save_analysis_run(run_data)
