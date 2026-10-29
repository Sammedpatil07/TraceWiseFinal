"""Deterministic RCA Correlation and Scoring Engine for AO-03.

Implements:
1. Multi-factor evidence-to-evidence correlation (Time, Service, Trace, Parent-Child, Dependency, Error, Deployment, Config, Metric).
2. Dynamic candidate cause generation derived from actual evidence.
3. Deterministic weighted Evidence Scoring (never called probability).
4. Explanations of contributing factors, supporting/contradicting evidence, and reasoning.
5. Detection of insufficient or conflicting evidence.
"""

from typing import List, Dict, Any, Tuple, Optional, Set
from datetime import datetime
from collections import defaultdict

from app.config import Config
from app.models.evidence import (
    NormalizedEvidence,
    EvidenceType,
    EvidenceSeverity,
    EvidenceCorrelation,
)
from app.models.incident import CandidateCause, Incident
from app.engine.dependency_graph import DependencyGraphManager


class CorrelationEngine:
    def __init__(self, graph_manager: DependencyGraphManager, weights: Optional[Dict[str, float]] = None):
        self.graph = graph_manager
        self.weights = weights or {
            "temporal": Config.WEIGHT_TEMPORAL_PRECEDENCE,
            "dependency": Config.WEIGHT_DEPENDENCY_RELEVANCE,
            "anomaly": Config.WEIGHT_ANOMALY_MAGNITUDE,
            "error": Config.WEIGHT_ERROR_CORRELATION,
            "trace": Config.WEIGHT_TRACE_CORRELATION,
            "deployment": Config.WEIGHT_DEPLOYMENT_PROXIMITY,
            "configuration": Config.WEIGHT_CONFIGURATION_PROXIMITY,
            "blast": Config.WEIGHT_BLAST_RADIUS,
        }

    # =========================================================================
    # PHASE 4: EVIDENCE-TO-EVIDENCE CORRELATION
    # =========================================================================

    def find_all_correlations(self, evidence_list: List[NormalizedEvidence]) -> List[EvidenceCorrelation]:
        """Discovers deterministic causal relationships between evidence items."""
        correlations: List[EvidenceCorrelation] = []
        n = len(evidence_list)
        if n < 2:
            return correlations

        # Sort evidence chronologically
        sorted_ev = sorted(evidence_list, key=lambda e: e.parsed_time)

        for i in range(n):
            e1 = sorted_ev[i]
            for j in range(i + 1, n):
                e2 = sorted_ev[j]
                pair_corrs = self._correlate_pair(e1, e2)
                correlations.extend(pair_corrs)

        return correlations

    def _correlate_pair(self, e1: NormalizedEvidence, e2: NormalizedEvidence) -> List[EvidenceCorrelation]:
        results: List[EvidenceCorrelation] = []
        delta_sec = abs((e2.parsed_time - e1.parsed_time).total_seconds())

        # 1. Trace parent-child relationship
        if (e1.span_id and e2.parent_span_id and e1.span_id == e2.parent_span_id) or \
           (e2.span_id and e1.parent_span_id and e2.span_id == e1.parent_span_id):
            results.append(EvidenceCorrelation(
                source_evidence_id=e1.id,
                target_evidence_id=e2.id,
                relation_type="TRACE_PARENT_CHILD",
                reason=f"Direct span parent-child call relationship ({e1.service} <-> {e2.service})",
                score=1.0,
            ))

        # 2. Same trace / request
        elif (e1.trace_id and e2.trace_id and e1.trace_id == e2.trace_id) or \
             (e1.request_id and e2.request_id and e1.request_id == e2.request_id):
            results.append(EvidenceCorrelation(
                source_evidence_id=e1.id,
                target_evidence_id=e2.id,
                relation_type="SAME_TRACE",
                reason=f"Share identical distributed trace/request context '{e1.trace_id or e1.request_id}'",
                score=0.9,
            ))

        # 3. Same service relationship
        if e1.service == e2.service:
            if delta_sec <= 300:
                results.append(EvidenceCorrelation(
                    source_evidence_id=e1.id,
                    target_evidence_id=e2.id,
                    relation_type="SAME_SERVICE",
                    reason=f"Both events occurred on service '{e1.service}' within {int(delta_sec)}s",
                    score=0.8,
                ))

        # 4. Dependency relationship between different services
        elif self.graph.can_cause_impact_on(e1.service, e2.service):
            if delta_sec <= 600:
                results.append(EvidenceCorrelation(
                    source_evidence_id=e1.id,
                    target_evidence_id=e2.id,
                    relation_type="DEPENDENCY_PROPAGATION",
                    reason=f"Service '{e2.service}' depends on '{e1.service}', failure propagated upstream within {int(delta_sec)}s",
                    score=0.85,
                ))

        # 5. Deployment proximity
        if e1.evidence_type == EvidenceType.DEPLOYMENT and e2.severity in [EvidenceSeverity.CRITICAL, EvidenceSeverity.HIGH]:
            if 0 <= (e2.parsed_time - e1.parsed_time).total_seconds() <= 900:
                if e1.service == e2.service or self.graph.can_cause_impact_on(e1.service, e2.service):
                    results.append(EvidenceCorrelation(
                        source_evidence_id=e1.id,
                        target_evidence_id=e2.id,
                        relation_type="DEPLOYMENT_PRECEDENCE",
                        reason=f"Deployment on '{e1.service}' directly preceded error surge on '{e2.service}' by {int(delta_sec)}s",
                        score=0.95,
                    ))

        # 6. Configuration proximity
        if e1.evidence_type == EvidenceType.CONFIGURATION and (e2.anomaly_score >= 0.5 or e2.severity == EvidenceSeverity.HIGH):
            if 0 <= (e2.parsed_time - e1.parsed_time).total_seconds() <= 900:
                if e1.service == e2.service or self.graph.can_cause_impact_on(e1.service, e2.service):
                    results.append(EvidenceCorrelation(
                        source_evidence_id=e1.id,
                        target_evidence_id=e2.id,
                        relation_type="CONFIG_PRECEDENCE",
                        reason=f"Configuration change on '{e1.service}' directly preceded anomaly on '{e2.service}' by {int(delta_sec)}s",
                        score=0.95,
                    ))

        # 7. Metric anomaly proximity to error logs
        if (e1.evidence_type == EvidenceType.METRIC and e2.evidence_type == EvidenceType.LOG) or \
           (e2.evidence_type == EvidenceType.METRIC and e1.evidence_type == EvidenceType.LOG):
            if delta_sec <= 180 and (e1.anomaly_score >= 0.5 or e2.anomaly_score >= 0.5):
                results.append(EvidenceCorrelation(
                    source_evidence_id=e1.id,
                    target_evidence_id=e2.id,
                    relation_type="METRIC_ANOMALY_PROXIMITY",
                    reason=f"Metric anomaly aligned in time ({int(delta_sec)}s) with application error log on '{e1.service}'",
                    score=0.85,
                ))

        # 8. Time proximity (general co-occurrence)
        if delta_sec <= 60 and not results:
            results.append(EvidenceCorrelation(
                source_evidence_id=e1.id,
                target_evidence_id=e2.id,
                relation_type="TIME_PROXIMITY",
                reason=f"Telemetry events occurred within {int(delta_sec)}s window",
                score=0.5,
            ))

        return results

    # =========================================================================
    # PHASES 5 & 6: CANDIDATE CAUSE GENERATION & SCORING
    # =========================================================================

    def evaluate_candidates(
        self, incident: Incident, evidence_list: List[NormalizedEvidence]
    ) -> List[CandidateCause]:
        """Evaluates evidence, generates candidate causes, and scores them deterministically.
        Sets self.has_conflicting_evidence if top candidates are ambiguous.
        """
        self.has_conflicting_evidence = False
        if not evidence_list:
            return []

        # Group evidence by service
        service_evidence: Dict[str, List[NormalizedEvidence]] = defaultdict(list)
        for ev in evidence_list:
            if ev.service:
                service_evidence[ev.service].append(ev)

        # Baseline timeline window
        sorted_all = sorted(evidence_list, key=lambda e: e.parsed_time)
        t_start = sorted_all[0].parsed_time
        t_end = sorted_all[-1].parsed_time
        duration_sec = max(1.0, (t_end - t_start).total_seconds())

        affected_services = set(incident.affected_services)
        candidate_causes: List[CandidateCause] = []

        for service_id, ev_group in service_evidence.items():
            candidate = self._generate_and_score_candidate(
                service_id=service_id,
                ev_group=ev_group,
                incident=incident,
                t_start=t_start,
                duration_sec=duration_sec,
                affected_services=affected_services,
            )
            if candidate and candidate.evidence_score > 0.0:
                candidate_causes.append(candidate)

        # Sort candidates descending by Evidence Score
        candidate_causes.sort(key=lambda c: c.evidence_score, reverse=True)

        # Assign ranks
        for idx, c in enumerate(candidate_causes):
            c.rank = idx + 1

        # Check for conflicting evidence (two top candidates tied or nearly tied with ambiguous scores)
        if len(candidate_causes) >= 2:
            top1 = candidate_causes[0]
            top2 = candidate_causes[1]
            diff = abs(top1.evidence_score - top2.evidence_score)
            # If top two candidates are close in score and neither depends on the other
            if diff < 0.05 and not self.graph.can_cause_impact_on(top1.service_id, top2.service_id) and not self.graph.can_cause_impact_on(top2.service_id, top1.service_id):
                self.has_conflicting_evidence = True

        return candidate_causes

    def _generate_and_score_candidate(
        self,
        service_id: str,
        ev_group: List[NormalizedEvidence],
        incident: Incident,
        t_start: datetime,
        duration_sec: float,
        affected_services: Set[str],
    ) -> Optional[CandidateCause]:
        supporting_ids: List[str] = []
        contradicting_ids: List[str] = []
        reasoning_factors: List[str] = []

        # 1. Temporal Precedence
        # Find earliest anomalous or change event on this service
        anom_events = [
            e for e in ev_group
            if e.anomaly_score >= 0.35 or e.evidence_type in [EvidenceType.DEPLOYMENT, EvidenceType.CONFIGURATION] or e.severity in [EvidenceSeverity.CRITICAL, EvidenceSeverity.HIGH]
        ]

        if not anom_events:
            # Service has zero anomalous telemetry
            return None

        earliest_anom = min(anom_events, key=lambda e: e.parsed_time)
        time_offset_sec = max(0.0, (earliest_anom.parsed_time - t_start).total_seconds())
        s_temporal = max(0.0, 1.0 - (time_offset_sec / duration_sec))
        reasoning_factors.append(
            f"First anomalous event on '{service_id}' occurred {int(time_offset_sec)}s into incident window (Temporal Score: {s_temporal:.2f})"
        )

        # 2. Dependency Relevance: Downstream/root nodes get higher score than upstream sinks
        is_root_leaf = len(self.graph.get_downstream_services(service_id)) == 0
        has_upstream_callers = len(self.graph.get_upstream_services(service_id)) > 0
        if is_root_leaf and has_upstream_callers:
            s_dependency = 1.0
            reasoning_factors.append(f"'{service_id}' is a terminal dependency node called by upstream services.")
        elif has_upstream_callers:
            s_dependency = 0.75
            reasoning_factors.append(f"'{service_id}' has upstream dependent services in the topology.")
        else:
            s_dependency = 0.35  # Edge ingress or standalone
            reasoning_factors.append(f"'{service_id}' has no upstream dependent callers (likely client ingress).")

        # 3. Anomaly Magnitude Score
        metric_ev = [e for e in ev_group if e.evidence_type == EvidenceType.METRIC]
        anomalous_metrics = [e for e in metric_ev if e.anomaly_score >= 0.35]
        if anomalous_metrics:
            max_metric_anom = max(e.anomaly_score for e in anomalous_metrics)
            avg_metric_anom = sum(e.anomaly_score for e in anomalous_metrics) / len(anomalous_metrics)
            s_anomaly = (max_metric_anom * 0.7) + (avg_metric_anom * 0.3)
            for m in anomalous_metrics:
                supporting_ids.append(m.id)
            reasoning_factors.append(f"Peak metric anomaly score of {max_metric_anom:.2f} observed.")
        else:
            s_anomaly = 0.0

        for m in metric_ev:
            if m.anomaly_score < 0.2:
                contradicting_ids.append(m.id)

        # 4. Error Correlation Score
        log_ev = [e for e in ev_group if e.evidence_type == EvidenceType.LOG]
        error_logs = [e for e in log_ev if e.severity in [EvidenceSeverity.CRITICAL, EvidenceSeverity.HIGH]]
        if error_logs:
            s_error = min(1.0, len(error_logs) / 2.0)
            for err in error_logs:
                supporting_ids.append(err.id)
            reasoning_factors.append(f"{len(error_logs)} high/critical severity error log(s) captured.")
        else:
            s_error = 0.0

        # 5. Trace Correlation Score
        trace_ev = [e for e in ev_group if e.evidence_type == EvidenceType.TRACE]
        error_traces = [e for e in trace_ev if e.severity == EvidenceSeverity.CRITICAL or e.details.get("error")]
        if error_traces:
            s_trace = 1.0
            for tr in error_traces:
                supporting_ids.append(tr.id)
            reasoning_factors.append(f"Trace spans exhibit HTTP 5xx / application faults on '{service_id}'.")
        elif trace_ev:
            s_trace = sum(e.anomaly_score for e in trace_ev) / len(trace_ev)
        else:
            s_trace = 0.0

        # 6. Deployment Proximity
        deploy_ev = [e for e in ev_group if e.evidence_type == EvidenceType.DEPLOYMENT]
        if deploy_ev:
            s_deployment = 1.0
            for d in deploy_ev:
                supporting_ids.append(d.id)
            reasoning_factors.append(f"Deployment record found on '{service_id}' immediately prior to errors.")
        else:
            s_deployment = 0.0

        # 7. Configuration Proximity
        config_ev = [e for e in ev_group if e.evidence_type == EvidenceType.CONFIGURATION]
        if config_ev:
            s_config = 1.0
            for c in config_ev:
                supporting_ids.append(c.id)
            reasoning_factors.append(f"Configuration change record detected on '{service_id}'.")
        else:
            s_config = 0.0

        # 8. Blast Radius & Reachability
        if affected_services:
            reach_count = sum(1 for aff in affected_services if self.graph.can_cause_impact_on(service_id, aff))
            s_blast = reach_count / len(affected_services)
            reasoning_factors.append(f"Topological path exists to {reach_count}/{len(affected_services)} affected service(s).")
        else:
            s_blast = 0.5

        # Direct causal evidence check:
        # If there are zero anomalous metrics, zero error logs, zero trace failures, and zero changes:
        direct_causal_signal = (
            self.weights["anomaly"] * s_anomaly
            + self.weights["error"] * s_error
            + self.weights["trace"] * s_trace
            + self.weights["deployment"] * s_deployment
            + self.weights["configuration"] * s_config
        )

        if direct_causal_signal == 0.0:
            return None

        # Calculate composite Evidence Score
        evidence_score = (
            self.weights["temporal"] * s_temporal
            + self.weights["dependency"] * s_dependency
            + self.weights["anomaly"] * s_anomaly
            + self.weights["error"] * s_error
            + self.weights["trace"] * s_trace
            + self.weights["deployment"] * s_deployment
            + self.weights["configuration"] * s_config
            + self.weights["blast"] * s_blast
        )
        evidence_score = round(min(1.0, max(0.0, evidence_score)), 3)

        # Dynamic Candidate Classification from actual evidence
        if config_ev:
            candidate_type = "CONFIG_DRIFT"
            title = f"Configuration drift on {service_id}"
            desc = f"Configuration changes on {service_id} immediately preceded the telemetry anomalies."
        elif deploy_ev:
            candidate_type = "DEPLOYMENT_FAULT"
            title = f"Recent deployment fault on {service_id}"
            desc = f"New code deployment on {service_id} closely correlates with failure onset."
        elif any("pool" in e.summary.lower() or "connection" in e.summary.lower() or "db" in e.summary.lower() for e in ev_group):
            candidate_type = "DATABASE_OR_RESOURCE_SATURATION"
            title = f"Database or connection pool starvation on {service_id}"
            desc = f"Telemetry on {service_id} reflects database timeout or connection pool exhaustion."
        elif is_root_leaf and s_anomaly >= 0.6:
            candidate_type = "DOWNSTREAM_DEPENDENCY_FAILURE"
            title = f"Downstream dependency failure on {service_id}"
            desc = f"Downstream core service {service_id} collapsed under anomalous load/errors."
        elif s_error >= 0.7:
            candidate_type = "ERROR_RATE_ANOMALY"
            title = f"Severe error rate spike on {service_id}"
            desc = f"Surge of critical application exceptions observed on {service_id}."
        elif s_trace >= 0.7:
            candidate_type = "TRACE_FAILURE"
            title = f"Trace request failures on {service_id}"
            desc = f"Distributed trace spans failed with server errors on {service_id}."
        else:
            candidate_type = "CASCADING_LATENCY"
            title = f"Cascading degradation on {service_id}"
            desc = f"Telemetry reflects upstream symptoms or secondary impact on {service_id}."

        contributing_factors = {
            "temporal_precedence": round(s_temporal, 3),
            "dependency_relevance": round(s_dependency, 3),
            "anomaly_magnitude": round(s_anomaly, 3),
            "error_correlation": round(s_error, 3),
            "trace_correlation": round(s_trace, 3),
            "deployment_proximity": round(s_deployment, 3),
            "configuration_proximity": round(s_config, 3),
            "change_proximity": round(max(s_deployment, s_config), 3),
            "blast_radius": round(s_blast, 3),
            "blast_reachability": round(s_blast, 3),
        }

        # Calculate affected downstream callers
        affected_list = list(self.graph.get_blast_radius(service_id))
        if service_id not in affected_list:
            affected_list.append(service_id)

        return CandidateCause(
            id=f"cand_{service_id}_{incident.id}",
            incident_id=incident.id,
            service_id=service_id,
            title=title,
            description=desc,
            candidate_type=candidate_type,
            rank=1,
            evidence_score=evidence_score,
            contributing_factors=contributing_factors,
            supporting_evidence_ids=list(dict.fromkeys(supporting_ids)),
            contradicting_evidence_ids=list(dict.fromkeys(contradicting_ids)),
            affected_services=affected_list,
            reasoning_factors=reasoning_factors,
        )
