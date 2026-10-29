"""Ingestion package for AO-03.
"""

from app.ingestion.base import BaseIngestionAdapter
from app.ingestion.generic_adapter import (
    GenericTelemetryIngestor,
    SchemaMapping,
    parse_raw_payload,
    GenericLogAdapter,
    GenericMetricAdapter,
    GenericTraceAdapter,
    GenericDeploymentAdapter,
    GenericConfigAdapter,
)
from app.ingestion.demo_fixtures import load_demo_data

__all__ = [
    "BaseIngestionAdapter",
    "GenericTelemetryIngestor",
    "SchemaMapping",
    "parse_raw_payload",
    "GenericLogAdapter",
    "GenericMetricAdapter",
    "GenericTraceAdapter",
    "GenericDeploymentAdapter",
    "GenericConfigAdapter",
    "load_demo_data",
]
