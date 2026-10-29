"""Evidence Validation Engine for AO-03.

Enforces ground-truth integrity:
Every explanation, candidate, and LLM statement must reference evidence IDs that actually exist in the database
and belong to the specific incident being analyzed.
"""

import re
from typing import Set, List, Dict, Any, Tuple, Optional
from app.models.incident import CandidateCause
from app.models.evidence import NormalizedEvidence


class EvidenceValidator:
    """Validates that evidence references strictly match existing database IDs for the incident."""

    @staticmethod
    def redact_sensitive_data(text: str) -> str:
        """Redacts API keys, passwords, bearer tokens, authorization headers, and secrets."""
        if not isinstance(text, str):
            text = str(text)
        # Bearer tokens
        text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9_\-\.]+", "Bearer [REDACTED]", text)
        # Authorization header
        text = re.sub(r"(?i)\b(authorization)\s*:\s*[^\r\n,]+", r"\1: [REDACTED]", text)
        # Password, secret, api key
        text = re.sub(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*['\"]?[^\s,'\"]+['\"]?", r"\1=[REDACTED]", text)
        # JWT
        text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[REDACTED_JWT]", text)
        return text

    @staticmethod
    def validate_candidate_evidence(
        candidate: CandidateCause, valid_evidence_ids: Set[str]
    ) -> CandidateCause:
        """Filters candidate evidence references to only retain verified database IDs for this incident."""
        candidate.supporting_evidence_ids = [
            eid for eid in candidate.supporting_evidence_ids if eid in valid_evidence_ids
        ]
        candidate.contradicting_evidence_ids = [
            eid for eid in candidate.contradicting_evidence_ids if eid in valid_evidence_ids
        ]
        return candidate

    @staticmethod
    def extract_evidence_ids_from_text(text: str) -> List[str]:
        """Extracts evidence ID patterns (e.g., EVID-DEMO-001, log_abc123, met_123, dep_123)."""
        pattern = r"\b(?:EVID-[A-Za-z0-9_-]+|(?:log|met|trc|dep|cfg)_[a-zA-Z0-9_-]+)\b"
        return list(dict.fromkeys(re.findall(pattern, text)))

    @classmethod
    def validate_llm_hypothesis(
        cls, hypothesis_data: Dict[str, Any], valid_evidence_ids: Set[str]
    ) -> Tuple[bool, List[str], Dict[str, Any]]:
        """Verifies that every evidence ID cited in the LLM hypothesis exists in the database.
        Returns (is_valid, list_of_invalid_ids, sanitized_hypothesis).
        """
        invalid_ids: List[str] = []

        # Check explicit cited_evidence_ids list
        cited_ids = hypothesis_data.get("supporting_evidence", [])
        if isinstance(cited_ids, list):
            for eid in cited_ids:
                if eid not in valid_evidence_ids:
                    invalid_ids.append(eid)

        # Check in the text fields for any unverified citations
        all_text = " ".join([
            str(hypothesis_data.get("incident_summary", "")),
            str(hypothesis_data.get("most_likely_cause", "")),
            str(hypothesis_data.get("timeline_interpretation", "")),
            str(hypothesis_data.get("confidence_explanation", "")),
        ])
        found_in_text = cls.extract_evidence_ids_from_text(all_text)
        for eid in found_in_text:
            if eid not in valid_evidence_ids:
                invalid_ids.append(eid)

        invalid_ids = list(dict.fromkeys(invalid_ids))
        is_valid = len(invalid_ids) == 0

        sanitized = dict(hypothesis_data)
        sanitized["verified_evidence_refs"] = [
            eid for eid in cited_ids if eid in valid_evidence_ids
        ]
        sanitized["unverified_evidence_refs"] = invalid_ids
        sanitized["validation_passed"] = is_valid

        # Reject or sanitize claims with invalid evidence references
        if not is_valid:
            sanitized["supporting_evidence"] = sanitized["verified_evidence_refs"]

        return is_valid, invalid_ids, sanitized

    @staticmethod
    def check_evidence_incident_ownership(
        evidence_list: List[NormalizedEvidence], incident_id: str
    ) -> Tuple[List[NormalizedEvidence], List[str]]:
        """Ensures all evidence records strictly belong to the specified incident.
        Returns (valid_records, mismatched_ids).
        """
        valid_records: List[NormalizedEvidence] = []
        mismatched: List[str] = []

        for e in evidence_list:
            if e.incident_id == incident_id:
                valid_records.append(e)
            else:
                mismatched.append(e.id)

        return valid_records, mismatched
