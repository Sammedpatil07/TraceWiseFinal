"""Base Ingestion Adapter Interface for AO-03.
Ensures future organizer telemetry can be ingested seamlessly without touching the RCA engine.
"""

from abc import ABC, abstractmethod
from typing import List, Any, Dict
from app.models.evidence import NormalizedEvidence, EvidenceType, SourceType


class BaseIngestionAdapter(ABC):
    """Abstract base adapter for normalizing raw telemetry into NormalizedEvidence."""

    @abstractmethod
    def parse(self, raw_data: Any, incident_id: str, source_type: SourceType = SourceType.ORGANIZER) -> List[NormalizedEvidence]:
        """Convert arbitrary incoming organizer data into normalized evidence records."""
        pass

    def validate(self, evidence: NormalizedEvidence) -> bool:
        """Validate that normalized evidence complies with required attributes."""
        if not evidence.id or not evidence.incident_id:
            return False
        if not evidence.evidence_type or not evidence.service_id:
            return False
        if not evidence.timestamp or not evidence.summary:
            return False
        return True
