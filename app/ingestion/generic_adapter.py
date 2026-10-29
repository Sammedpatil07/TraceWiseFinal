"""Generic Ingestion Adapters and Multi-Format Parser for AO-03.

Supports:
- JSON (arrays, objects)
- JSONL (line-delimited JSON)
- CSV (comma-separated with header row)
- Custom schema mappings
- Graceful error isolation (malformed records do not abort the batch)
- Ground-truth provenance preservation (source_record, source_file)
"""

import json
import csv
import io
import uuid
import hashlib
from typing import List, Dict, Any, Optional, Tuple

from app.ingestion.base import BaseIngestionAdapter
from app.models.evidence import (
    NormalizedEvidence,
    EvidenceType,
    EvidenceSeverity,
    SourceType,
)


class SchemaMapping:
    """User-configurable field mappings for heterogeneous organizer data."""

    DEFAULT_MAPPINGS = {
        "timestamp": ["timestamp", "time", "ts", "@timestamp", "datetime", "date"],
        "service": ["service", "service_name", "app", "component", "service_id", "host"],
        "severity": ["severity", "level", "log_level", "status", "priority"],
        "message": ["message", "msg", "summary", "description", "log", "text", "body"],
        "event_type": ["event_type", "event", "type", "action", "category"],
        "trace_id": ["trace_id", "traceId", "trace"],
        "span_id": ["span_id", "spanId", "span"],
        "parent_span_id": ["parent_span_id", "parentSpanId", "parentId", "parent_id"],
        "request_id": ["request_id", "requestId", "req_id", "x_request_id"],
        "deployment_id": ["deployment_id", "deploymentId", "deploy_id", "commit_hash", "commit"],
        "configuration_id": ["configuration_id", "config_id", "change_id"],
        "metric_name": ["metric_name", "name", "metric", "measurement"],
        "metric_value": ["metric_value", "value", "val"],
        "anomaly_score": ["anomaly_score", "z_score", "anomaly", "score"],
    }

    def __init__(self, custom_mapping: Optional[Dict[str, str]] = None):
        self.mapping = custom_mapping or {}

    def extract(self, record: Dict[str, Any], field_key: str, default: Any = None) -> Any:
        # Check custom mapping first
        if field_key in self.mapping and self.mapping[field_key] in record:
            return record[self.mapping[field_key]]

        # Check default candidate names
        candidates = self.DEFAULT_MAPPINGS.get(field_key, [field_key])
        for cand in candidates:
            if cand in record and record[cand] is not None:
                return record[cand]

        return default


def parse_raw_payload(content: Any, format_hint: Optional[str] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Parses raw content (JSON array, JSONL string, CSV text, or Python objects).
    Returns (records_list, parse_errors).
    """
    records: List[Dict[str, Any]] = []
    errors: List[str] = []

    if isinstance(content, list):
        for idx, item in enumerate(content):
            if isinstance(item, dict):
                records.append(item)
            else:
                errors.append(f"Item at index {idx} is not a valid object: {type(item).__name__}")
        return records, errors

    if isinstance(content, dict):
        if "records" in content and isinstance(content["records"], list):
            return parse_raw_payload(content["records"], format_hint)
        records.append(content)
        return records, errors

    if not isinstance(content, str):
        errors.append(f"Unsupported payload type: {type(content).__name__}")
        return records, errors

    text = content.strip()
    if not text:
        return records, errors

    # Detect format
    format_type = format_hint.lower() if format_hint else None
    is_json = text.startswith("[") or (text.startswith("{") and "\n" not in text)
    is_jsonl = format_type == "jsonl" or ("\n" in text and any("{" in line and "}" in line for line in text.splitlines()[:5]))

    # 1. If explicit JSONL requested or looks like multiple JSON lines, try JSONL first
    if format_type == "jsonl" or (is_jsonl and format_type != "json"):
        lines = text.splitlines()
        jsonl_records = []
        jsonl_errors = []
        for line_no, line in enumerate(lines, start=1):
            clean_line = line.strip()
            if not clean_line:
                continue
            try:
                obj = json.loads(clean_line)
                if isinstance(obj, dict):
                    jsonl_records.append(obj)
                else:
                    jsonl_errors.append(f"Line {line_no} is not a JSON object.")
            except json.JSONDecodeError as err:
                jsonl_errors.append(f"Line {line_no} malformed JSON: {err}")
        if jsonl_records:
            return jsonl_records, jsonl_errors

    # 2. Try standard JSON
    if format_type == "json" or is_json or not format_type:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                for idx, r in enumerate(parsed):
                    if isinstance(r, dict):
                        records.append(r)
                    else:
                        errors.append(f"JSON array item at index {idx} is not a dictionary.")
            elif isinstance(parsed, dict):
                if "records" in parsed and isinstance(parsed["records"], list):
                    return parse_raw_payload(parsed["records"], None)
                records.append(parsed)
            return records, errors
        except json.JSONDecodeError as e:
            # Fall through to CSV if JSON decoding failed
            pass

    # 3. Try CSV
    try:
        reader = csv.DictReader(io.StringIO(text))
        for row_no, row in enumerate(reader, start=1):
            if any(row.values()):
                records.append(dict(row))
        if records:
            return records, errors
    except Exception as err:
        errors.append(f"CSV parse error: {err}")

    if not records and not errors:
        errors.append("Unable to determine data format (not valid JSON, JSONL, or CSV).")

    return records, errors


class GenericTelemetryIngestor(BaseIngestionAdapter):
    """Universal ingestion adapter handling JSON, JSONL, CSV, and schema mapping."""

    def __init__(self, schema_mapping: Optional[Dict[str, str]] = None):
        self.mapper = SchemaMapping(schema_mapping)

    def parse(
        self,
        raw_data: Any,
        incident_id: str,
        source_type: SourceType = SourceType.ORGANIZER,
        evidence_type_hint: Optional[str] = None,
        source_file: Optional[str] = None,
        format_hint: Optional[str] = None,
    ) -> Tuple[List[NormalizedEvidence], Dict[str, Any]]:
        """Parses heterogeneous input and returns (normalized_evidence_list, ingestion_report)."""
        raw_records, parse_errors = parse_raw_payload(raw_data, format_hint=format_hint)

        normalized_list: List[NormalizedEvidence] = []
        item_errors: List[Dict[str, Any]] = []
        warnings: List[str] = list(parse_errors)

        for idx, rec in enumerate(raw_records):
            try:
                ev = self._normalize_single_record(
                    rec=rec,
                    index=idx,
                    incident_id=incident_id,
                    source_type=source_type,
                    evidence_type_hint=evidence_type_hint,
                    source_file=source_file,
                )
                if self.validate(ev):
                    normalized_list.append(ev)
                else:
                    item_errors.append({
                        "index": idx,
                        "error": "Record validation failed: missing essential fields (id, service, timestamp, or summary)",
                        "record": {k: str(v)[:80] for k, v in list(rec.items())[:5]},
                    })
            except Exception as e:
                item_errors.append({
                    "index": idx,
                    "error": f"Failed to normalize record: {str(e)}",
                    "record": {k: str(v)[:80] for k, v in list(rec.items())[:5]},
                })

        # Calculate status
        total_errors = len(item_errors) + len(parse_errors)
        total_received = len(raw_records) + len(parse_errors)
        if total_received == 0 and parse_errors:
            status = "FAILED"
        elif total_errors > 0 and len(normalized_list) > 0:
            status = "PARTIAL_SUCCESS"
        elif total_errors > 0 and len(normalized_list) == 0:
            status = "FAILED"
        else:
            status = "SUCCESS"

        report = {
            "status": status,
            "total_received": total_received,
            "ingested_count": len(normalized_list),
            "failed_count": total_errors,
            "errors": item_errors + [{"parse_error": pe} for pe in parse_errors],
            "warnings": warnings,
        }

        return normalized_list, report

    def _normalize_single_record(
        self,
        rec: Dict[str, Any],
        index: int,
        incident_id: str,
        source_type: SourceType,
        evidence_type_hint: Optional[str],
        source_file: Optional[str],
    ) -> NormalizedEvidence:
        # Extract fields via SchemaMapping
        service = str(self.mapper.extract(rec, "service", "unknown-service"))
        timestamp = str(self.mapper.extract(rec, "timestamp", ""))
        severity_raw = str(self.mapper.extract(rec, "severity", "INFO")).upper()
        summary = str(self.mapper.extract(rec, "message", "Telemetry record"))
        event_type = str(self.mapper.extract(rec, "event_type", ""))

        trace_id = self.mapper.extract(rec, "trace_id")
        span_id = self.mapper.extract(rec, "span_id")
        parent_span_id = self.mapper.extract(rec, "parent_span_id")
        request_id = self.mapper.extract(rec, "request_id")
        deployment_id = self.mapper.extract(rec, "deployment_id")
        configuration_id = self.mapper.extract(rec, "configuration_id")
        metric_name = self.mapper.extract(rec, "metric_name")
        metric_val_raw = self.mapper.extract(rec, "metric_value")
        metric_value = float(metric_val_raw) if metric_val_raw is not None and str(metric_val_raw).replace(".", "", 1).isdigit() else None

        # Severity resolution
        severity = EvidenceSeverity.INFO
        if severity_raw in ["FATAL", "CRITICAL"] or rec.get("http_status") in [500, 502, 503, 504]:
            severity = EvidenceSeverity.CRITICAL
        elif severity_raw in ["ERROR", "ERR"]:
            severity = EvidenceSeverity.HIGH
        elif severity_raw in ["WARN", "WARNING"]:
            severity = EvidenceSeverity.MEDIUM

        # Evidence Type Resolution
        ev_type = EvidenceType.LOG
        if evidence_type_hint:
            try:
                ev_type = EvidenceType(evidence_type_hint.upper())
            except Exception:
                pass
        elif rec.get("evidence_type"):
            try:
                ev_type = EvidenceType(str(rec["evidence_type"]).upper())
            except Exception:
                pass
        elif metric_name is not None or metric_value is not None:
            ev_type = EvidenceType.METRIC
        elif trace_id is not None or span_id is not None or "http_status" in rec or "duration_ms" in rec:
            ev_type = EvidenceType.TRACE
        elif deployment_id is not None or "commit_hash" in rec or "image_tag" in rec:
            ev_type = EvidenceType.DEPLOYMENT
        elif configuration_id is not None or "config_key" in rec or "previous_value" in rec:
            ev_type = EvidenceType.CONFIGURATION
        elif "target_service" in rec:
            ev_type = EvidenceType.DEPENDENCY

        # Compute Anomaly Score
        score_val = self.mapper.extract(rec, "anomaly_score")
        if score_val is not None:
            try:
                anomaly_score = float(score_val)
            except Exception:
                anomaly_score = 0.0
        elif ev_type == EvidenceType.METRIC:
            threshold = float(rec.get("threshold", metric_value if metric_value is not None else 1.0))
            z_score = float(rec.get("z_score", 0.0))
            if z_score > 0:
                anomaly_score = min(1.0, z_score / 4.0)
            elif threshold > 0 and metric_value and metric_value > threshold:
                anomaly_score = min(1.0, (metric_value - threshold) / threshold)
            else:
                anomaly_score = 0.0
        elif ev_type in [EvidenceType.DEPLOYMENT, EvidenceType.CONFIGURATION]:
            anomaly_score = 0.85
        elif ev_type == EvidenceType.TRACE and (rec.get("error") or int(rec.get("http_status", 200)) >= 500):
            anomaly_score = 0.90
        elif severity in [EvidenceSeverity.CRITICAL, EvidenceSeverity.HIGH]:
            anomaly_score = 0.80
        else:
            anomaly_score = 0.05

        # If severity was not explicitly high/critical in record, upgrade based on anomaly score
        if severity == EvidenceSeverity.INFO:
            if anomaly_score >= 0.75:
                severity = EvidenceSeverity.CRITICAL
            elif anomaly_score >= 0.5:
                severity = EvidenceSeverity.HIGH
            elif anomaly_score >= 0.25:
                severity = EvidenceSeverity.MEDIUM

        # Deterministic or Provided ID
        provided_id = rec.get("id") or rec.get("evidence_id")
        if provided_id:
            ev_id = str(provided_id)
        else:
            # Deterministic hash to safely handle duplicate ingestion
            hash_input = f"{incident_id}_{service}_{timestamp}_{summary}_{index}"
            ev_id = f"{ev_type.value.lower()[:3]}_{hashlib.sha256(hash_input.encode()).hexdigest()[:10]}"

        return NormalizedEvidence(
            id=ev_id,
            incident_id=incident_id,
            evidence_type=ev_type,
            service=service,
            timestamp=timestamp,
            severity=severity,
            event_type=event_type or ev_type.value,
            message=summary,
            summary=summary,
            trace_id=str(trace_id) if trace_id else None,
            span_id=str(span_id) if span_id else None,
            parent_span_id=str(parent_span_id) if parent_span_id else None,
            request_id=str(request_id) if request_id else None,
            deployment_id=str(deployment_id) if deployment_id else None,
            configuration_id=str(configuration_id) if configuration_id else None,
            metric_name=str(metric_name) if metric_name else None,
            metric_value=metric_value,
            source_type=source_type,
            source_file=source_file,
            source_record=rec,
            redacted=bool(rec.get("redacted", False)),
            anomaly_score=anomaly_score,
            details=rec,
            metadata=rec,
        )


# Backward-compatible individual adapters
class GenericLogAdapter(BaseIngestionAdapter):
    def parse(self, raw_data: List[Dict[str, Any]], incident_id: str, source_type: SourceType = SourceType.ORGANIZER) -> List[NormalizedEvidence]:
        ingestor = GenericTelemetryIngestor()
        res, _ = ingestor.parse(raw_data, incident_id, source_type, evidence_type_hint="LOG")
        return res


class GenericMetricAdapter(BaseIngestionAdapter):
    def parse(self, raw_data: List[Dict[str, Any]], incident_id: str, source_type: SourceType = SourceType.ORGANIZER) -> List[NormalizedEvidence]:
        ingestor = GenericTelemetryIngestor()
        res, _ = ingestor.parse(raw_data, incident_id, source_type, evidence_type_hint="METRIC")
        return res


class GenericTraceAdapter(BaseIngestionAdapter):
    def parse(self, raw_data: List[Dict[str, Any]], incident_id: str, source_type: SourceType = SourceType.ORGANIZER) -> List[NormalizedEvidence]:
        ingestor = GenericTelemetryIngestor()
        res, _ = ingestor.parse(raw_data, incident_id, source_type, evidence_type_hint="TRACE")
        return res


class GenericDeploymentAdapter(BaseIngestionAdapter):
    def parse(self, raw_data: List[Dict[str, Any]], incident_id: str, source_type: SourceType = SourceType.ORGANIZER) -> List[NormalizedEvidence]:
        ingestor = GenericTelemetryIngestor()
        res, _ = ingestor.parse(raw_data, incident_id, source_type, evidence_type_hint="DEPLOYMENT")
        return res


class GenericConfigAdapter(BaseIngestionAdapter):
    def parse(self, raw_data: List[Dict[str, Any]], incident_id: str, source_type: SourceType = SourceType.ORGANIZER) -> List[NormalizedEvidence]:
        ingestor = GenericTelemetryIngestor()
        res, _ = ingestor.parse(raw_data, incident_id, source_type, evidence_type_hint="CONFIGURATION")
        return res
