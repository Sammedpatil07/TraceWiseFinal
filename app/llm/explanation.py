"""Structured Investigation Packet and Explanation Service for AO-03.
Coordinates the LLM explanation layer, strictly feeding verified evidence packets.
"""

import json
import logging
from typing import Dict, Any, List, Tuple

from app.models.incident import Incident, CandidateCause, TimelineEvent
from app.models.evidence import NormalizedEvidence
from app.llm.ollama_provider import OllamaProvider
from app.llm.heuristic_provider import HeuristicProvider
from app.engine.validator import EvidenceValidator

logger = logging.getLogger(__name__)


def _extract_json_text(text: str) -> str:
    """Extract a JSON document from LLM output.

    Ollama instruction models frequently wrap JSON in markdown code fences
    (````json ... ````) or surround it with prose. Strips those wrappers and
    isolates the outermost ``{ ... }`` block so ``json.loads`` can parse it.
    Raises ValueError with a clear diagnostic when no JSON can be extracted.
    """
    if text is None:
        raise ValueError("Ollama returned no generated text (content was None).")
    text = str(text).strip()
    if not text:
        raise ValueError("Ollama returned an empty response; no generated text to parse.")

    # Strip markdown code fences: ```json ... ```  or  ``` ...
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        closing = text.rfind("```")
        if closing != -1:
            text = text[:closing]
        text = text.strip()

    # Isolate the outermost JSON object if surrounding prose is present.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in Ollama response.")
    text = text[start:end + 1]

    return text


class ExplanationService:
    def __init__(self):
        self.ollama = OllamaProvider()
        self.heuristic = HeuristicProvider()

    def build_investigation_packet(
        self,
        incident: Incident,
        top_candidate: CandidateCause,
        ranked_candidates: List[CandidateCause],
        timeline: List[TimelineEvent],
        evidence_list: List[NormalizedEvidence],
    ) -> Dict[str, Any]:
        """Prepares a strictly bounded investigation packet for the LLM with redaction of secrets."""
        redact = EvidenceValidator.redact_sensitive_data
        evidence_map = {e.id: redact(e.summary) for e in evidence_list}

        supporting = [
            {"id": eid, "summary": evidence_map.get(eid, "Evidence details")}
            for eid in top_candidate.supporting_evidence_ids
        ]
        contradicting = [
            {"id": eid, "summary": evidence_map.get(eid, "Evidence details")}
            for eid in top_candidate.contradicting_evidence_ids
        ]

        alternatives = [
            {
                "service": c.service_id,
                "title": redact(c.title),
                "confidence_score": c.confidence_score,
                "rank": c.rank,
            }
            for c in ranked_candidates[1:4]  # Next top 3 alternatives
        ]

        timeline_summary = [
            {
                "time": t.timestamp,
                "event_type": t.event_type,
                "service": t.service_id,
                "summary": redact(t.summary),
                "evidence_id": t.evidence_id,
            }
            for t in timeline[:15]
        ]

        return {
            "incident": {
                "id": incident.id,
                "title": redact(incident.title),
                "description": redact(incident.description),
                "started_at": incident.started_at,
                "resolved_at": incident.resolved_at,
                "affected_services": incident.affected_services,
            },
            "top_candidate": {
                "service_id": top_candidate.service_id,
                "title": redact(top_candidate.title),
                "candidate_type": top_candidate.candidate_type,
                "confidence_score": top_candidate.confidence_score,
                "scoring_breakdown": top_candidate.scoring_breakdown,
                "supporting_evidence": supporting,
                "contradicting_evidence": contradicting,
            },
            "alternative_causes": alternatives,
            "timeline": timeline_summary,
        }

    def generate_explanation(
        self,
        incident: Incident,
        top_candidate: CandidateCause,
        ranked_candidates: List[CandidateCause],
        timeline: List[TimelineEvent],
        evidence_list: List[NormalizedEvidence],
    ) -> Tuple[Dict[str, Any], str]:
        """Generates structured RCA explanation. Returns (explanation_dict, status)."""
        packet = self.build_investigation_packet(
            incident, top_candidate, ranked_candidates, timeline, evidence_list
        )

        system_prompt = (
            "You are an expert site reliability and root cause analysis AI. "
            "You are analyzing an incident that is resolved, but nobody knows why.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. EVIDENCE BEFORE EXPLANATION: All explanations must be strictly anchored in verified telemetry evidence. You do NOT guess or jump to conclusions without citing evidence.\n"
            "2. You must ONLY cite evidence IDs that are explicitly listed in the Investigation Packet (e.g. EVID-DEMO-001, log_123).\n"
            "3. Do NOT hallucinate or invent new evidence IDs.\n"
            "4. The deterministic correlation engine has already ranked the candidates. Explain WHY the top candidate ranked highest.\n"
            "5. Clearly label your output with: 'AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING'.\n"
            "6. Respond with a valid JSON object matching the requested schema exactly.\n\n"
            "SCHEMA:\n"
            "{\n"
            '  "header": "AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING",\n'
            '  "incident_summary": "<brief summary of what occurred>",\n'
            '  "most_likely_cause": "<concise statement of the root cause>",\n'
            '  "confidence_explanation": "<why the causal score is high/medium based on evidence>",\n'
            '  "supporting_evidence": ["<evidence_id_1>", "<evidence_id_2>"],\n'
            '  "contradicting_evidence": ["<evidence_id_3>"],\n'
            '  "alternative_causes": [{"cause": "<cause>", "reason_rejected": "<reason>"}],\n'
            '  "timeline_interpretation": "<how the failure cascaded chronologically>",\n'
            '  "unknowns": "<what questions remain or what telemetry was missing>",\n'
            '  "hypothesis_status": "GENERATED"\n'
            "}"
        )

        user_prompt = f"Investigation Packet:\n{json.dumps(packet, indent=2)}"

        if self.ollama.is_available():
            try:
                raw_resp = self.ollama.generate(system_prompt, user_prompt)
                json_text = _extract_json_text(raw_resp)
                parsed = json.loads(json_text)
                if not isinstance(parsed, dict):
                    raise ValueError(
                        f"Ollama returned a non-object JSON value: {type(parsed).__name__}"
                    )
                parsed["header"] = "AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING"
                parsed["hypothesis_status"] = "AI_GENERATED"
                return parsed, "AVAILABLE"
            except Exception as e:
                logger.warning(f"Ollama generation failed: {e}. Falling back to heuristic explanation.")

        # Heuristic fallback (Deterministic template)
        supporting_ids = [e["id"] for e in packet["top_candidate"]["supporting_evidence"]]
        contradicting_ids = [e["id"] for e in packet["top_candidate"]["contradicting_evidence"]]

        heuristic_explanation = {
            "header": "AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING",
            "incident_summary": (
                f"Incident '{incident.title}' affected {len(incident.affected_services)} services "
                f"({', '.join(incident.affected_services)}). The system recovered after remediation."
            ),
            "most_likely_cause": top_candidate.title,
            "confidence_explanation": (
                f"The deterministic scoring engine assigned a Causal Evidence Score of {top_candidate.confidence_score:.2f} "
                f"to {top_candidate.service_id}. Multi-factor scoring breakdown: Temporal precedence "
                f"({top_candidate.scoring_breakdown.get('temporal_precedence', 0.0):.2f}), "
                f"Anomaly magnitude ({top_candidate.scoring_breakdown.get('anomaly_magnitude', 0.0):.2f}), "
                f"Error surge ({top_candidate.scoring_breakdown.get('error_correlation', 0.0):.2f}), "
                f"and Change proximity ({top_candidate.scoring_breakdown.get('change_proximity', 0.0):.2f})."
            ),
            "supporting_evidence": supporting_ids,
            "contradicting_evidence": contradicting_ids,
            "alternative_causes": [
                {
                    "cause": alt["title"],
                    "reason_rejected": f"Ranked lower (Score: {alt['confidence_score']:.2f}) due to later occurrence or upstream symptom nature.",
                }
                for alt in packet["alternative_causes"]
            ],
            "timeline_interpretation": (
                f"The earliest anomalous event was detected on '{top_candidate.service_id}', "
                "followed by latency degradation and error propagation upstream to client-facing services."
            ),
            "unknowns": "No deep database internal locking dumps were attached; engine correlated from external pool wait metrics.",
            "hypothesis_status": "DETERMINISTIC_HEURISTIC",
        }

        return heuristic_explanation, "FALLBACK_HEURISTIC"
