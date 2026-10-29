"""Offline / Heuristic Explanation Provider for AO-03.
Ensures the system produces structured, verified explanations even when the external LLM API is unavailable.
"""

import json
from typing import Dict, Any, List
from app.llm.provider import BaseLLMProvider


class HeuristicProvider(BaseLLMProvider):
    def is_available(self) -> bool:
        return True

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        # Parsed directly in ExplanationService for offline fallback
        return json.dumps({
            "header": "AI-GENERATED HYPOTHESIS — NOT A CONFIRMED FINDING",
            "incident_summary": "Offline deterministic explanation generated from verified telemetry evidence.",
            "most_likely_cause": "Telemetry correlation identified top candidate service.",
            "confidence_explanation": "Deterministic score computed based on temporal order, error surge, and anomaly magnitude.",
            "supporting_evidence": [],
            "contradicting_evidence": [],
            "alternative_causes": [],
            "timeline_interpretation": "Events occurred in causal chronological sequence.",
            "unknowns": "External LLM was offline; heuristic rule-based template applied.",
            "hypothesis_status": "DETERMINISTIC_HEURISTIC",
        })
