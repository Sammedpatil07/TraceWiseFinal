"""Production-grade CSV Log and Telemetry Ingestion Engine for TraceWise AO-03.

Handles:
- Standard CSV files with arbitrary column headers
- UTF-8 and UTF-8-BOM (utf-8-sig) encodings
- Quoted values containing commas, line breaks, and escaped quotes
- Windows CRLF and Unix LF line endings
- Flexible header alias mapping (timestamp, service, severity, message, etc.)
- Strict row-level validation (timestamp parsing, service, message)
- Sensitive data redaction (API keys, passwords, bearer tokens)
- Formula injection defense (sanitizes =, +, -, @ prefixes)
- Duplicate detection against existing incident evidence and intra-batch duplicates
- Generation of detailed validation summaries, preview rows, and error diagnostics
"""

import io
import re
import csv
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Set, Tuple

from app.models.evidence import (
    NormalizedEvidence,
    EvidenceType,
    EvidenceSeverity,
    SourceType,
)
from app.ingestion.base import BaseIngestionAdapter
from app.ingestion.generic_adapter import SchemaMapping
from app.engine.validator import EvidenceValidator


class CSVLogIngestor(BaseIngestionAdapter):
    """Production CSV Ingestion and Validation Engine."""

    MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
    MAX_RECORD_COUNT = 5000                  # Maximum allowed rows per upload
    PREVIEW_LIMIT = 20                       # Number of records to return for preview

    # Formula injection characters
    DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

    def __init__(self, custom_mapping: Optional[Dict[str, str]] = None):
        self.mapper = SchemaMapping(custom_mapping)

    @classmethod
    def sanitize_field_value(cls, val: Any) -> str:
        """Sanitizes text fields to neutralize formula injection attacks."""
        if val is None:
            return ""
        s = str(val).strip()
        # Prevent spreadsheet formula execution if exported or viewed
        if s.startswith(cls.DANGEROUS_PREFIXES):
            s = "'" + s
        return s

    @classmethod
    def parse_timestamp_str(cls, raw_ts: Any) -> Tuple[Optional[str], Optional[str]]:
        """Parses various timestamp representations into a standardized ISO-8601 UTC string.
        Returns (iso_string, error_message).
        """
        if raw_ts is None:
            return None, "Timestamp is missing."
        s = str(raw_ts).strip()
        if not s:
            return None, "Timestamp is empty."

        # 1. Numeric epoch (seconds or milliseconds)
        try:
            val = float(s)
            if val > 1e11:  # Milliseconds
                dt = datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
            else:           # Seconds
                dt = datetime.fromtimestamp(val, tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), None
        except (ValueError, OverflowError):
            pass

        # 2. ISO-8601 or common datetime string patterns
        s_iso = s.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s_iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), None
        except Exception:
            pass

        # 3. Known formats fallback (with explicit year)
        known_formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%m/%d/%Y %H:%M:%S",
            "%b %d %Y %H:%M:%S",
        ]
        for fmt in known_formats:
            try:
                dt = datetime.strptime(s, fmt)
                dt = dt.replace(tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), None
            except ValueError:
                continue

        return None, f"Unrecognized timestamp format: '{s[:40]}'. Expected ISO-8601 (e.g. 2026-03-15T14:30:00Z)."

    def parse_csv_stream(
        self,
        csv_text: str,
        incident_id: str,
        existing_signatures: Optional[Set[str]] = None,
        source_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Parses CSV content with complete validation, deduplication, and anomaly scoring.
        Does NOT persist records.

        Returns a validation report with preview items and normalized candidates ready for commit.
        """
        if existing_signatures is None:
            existing_signatures = set()

        if not csv_text or not csv_text.strip():
            return {
                "status": "INVALID",
                "total_rows": 0,
                "valid_count": 0,
                "invalid_count": 0,
                "duplicate_count": 0,
                "preview_rows": [],
                "normalized_records": [],
                "row_errors": [{"row": 0, "error": "CSV file is empty or contains no content.", "field": "file"}],
                "warnings": ["The provided CSV file contains no readable data."],
                "services_detected": [],
            }

        # Handle UTF-8 BOM if present in raw string
        clean_text = csv_text.lstrip("\ufeff")

        # Standard CSV reader with Sniffer fallback
        try:
            # Check for delimiter (comma, semicolon, tab)
            sample = clean_text[:4096]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            except Exception:
                dialect = csv.excel

            stream = io.StringIO(clean_text, newline="")
            reader = csv.DictReader(stream, dialect=dialect)
        except Exception as e:
            return {
                "status": "INVALID",
                "total_rows": 0,
                "valid_count": 0,
                "invalid_count": 0,
                "duplicate_count": 0,
                "preview_rows": [],
                "normalized_records": [],
                "row_errors": [{"row": 0, "error": f"Failed to initialize CSV parser: {str(e)}", "field": "syntax"}],
                "warnings": ["Ensure file is a valid comma-separated CSV with standard headers."],
                "services_detected": [],
            }

        headers = reader.fieldnames or []
        if not headers:
            return {
                "status": "INVALID",
                "total_rows": 0,
                "valid_count": 0,
                "invalid_count": 0,
                "duplicate_count": 0,
                "preview_rows": [],
                "normalized_records": [],
                "row_errors": [{"row": 1, "error": "CSV missing header row.", "field": "headers"}],
                "warnings": ["The CSV file must have a header row defining column names."],
                "services_detected": [],
            }

        # Normalize header keys for mapping (strip whitespace, lowercase)
        normalized_headers = [h.strip() for h in headers if h]

        normalized_records: List[NormalizedEvidence] = []
        preview_rows: List[Dict[str, Any]] = []
        row_errors: List[Dict[str, Any]] = []
        warnings: List[str] = []
        seen_batch_signatures: Set[str] = set()
        services_detected: Set[str] = set()

        total_rows = 0
        valid_count = 0
        invalid_count = 0
        duplicate_count = 0

        # Process each row
        for row_index, raw_row in enumerate(reader, start=2):  # Start at line 2 (line 1 is header)
            total_rows += 1

            if total_rows > self.MAX_RECORD_COUNT:
                warnings.append(
                    f"Maximum row limit of {self.MAX_RECORD_COUNT} reached. Additional rows were truncated."
                )
                break

            # Skip entirely blank rows
            if not any(v.strip() for v in raw_row.values() if isinstance(v, str)):
                continue

            # Clean keys and values
            clean_row = {
                k.strip(): (v.strip() if isinstance(v, str) else v)
                for k, v in raw_row.items()
                if k is not None
            }

            # 1. Extract Service
            service = str(self.mapper.extract(clean_row, "service", "")).strip()
            if not service:
                # Check if there is an app or component field
                service = clean_row.get("service") or clean_row.get("service_name") or clean_row.get("app") or clean_row.get("host") or ""
            if not service:
                service = "unassigned-service"
                if len(warnings) < 10 and "Default fallback service 'unassigned-service' used for some rows." not in warnings:
                    warnings.append("Default fallback service 'unassigned-service' used for rows missing service column.")

            services_detected.add(service)

            # 2. Extract and Validate Timestamp
            raw_ts = self.mapper.extract(clean_row, "timestamp")
            iso_ts, ts_error = self.parse_timestamp_str(raw_ts)
            if ts_error:
                invalid_count += 1
                row_errors.append({
                    "row": row_index,
                    "field": "timestamp",
                    "error": ts_error,
                    "sample": str(raw_ts)[:60] if raw_ts else "EMPTY",
                })
                if len(preview_rows) < self.PREVIEW_LIMIT:
                    preview_rows.append({
                        "row": row_index,
                        "timestamp": str(raw_ts or "-"),
                        "service": service,
                        "severity": "ERROR",
                        "summary": str(clean_row.get("message", "-"))[:100],
                        "status": "INVALID",
                        "error": ts_error,
                    })
                continue

            # 3. Extract Message / Summary
            raw_msg = self.mapper.extract(clean_row, "message")
            if not raw_msg:
                # Try finding any descriptive column
                for candidate in ["log", "summary", "description", "text", "event", "detail"]:
                    if candidate in clean_row and clean_row[candidate]:
                        raw_msg = clean_row[candidate]
                        break
            if not raw_msg:
                invalid_count += 1
                row_errors.append({
                    "row": row_index,
                    "field": "message",
                    "error": "Record is missing log message or summary.",
                    "sample": str(clean_row)[:80],
                })
                if len(preview_rows) < self.PREVIEW_LIMIT:
                    preview_rows.append({
                        "row": row_index,
                        "timestamp": iso_ts,
                        "service": service,
                        "severity": "ERROR",
                        "summary": "[MISSING MESSAGE]",
                        "status": "INVALID",
                        "error": "Missing message or summary field.",
                    })
                continue

            # 4. Redaction of sensitive credentials
            clean_msg = EvidenceValidator.redact_sensitive_data(str(raw_msg))
            clean_msg = self.sanitize_field_value(clean_msg)

            # 5. Extract Severity
            raw_sev = str(self.mapper.extract(clean_row, "severity", "INFO")).strip().upper()
            severity = EvidenceSeverity.INFO
            if raw_sev in ["FATAL", "CRITICAL", "EMERGENCY"] or clean_row.get("status_code") in ["500", "502", "503", "504"]:
                severity = EvidenceSeverity.CRITICAL
            elif raw_sev in ["ERROR", "ERR"]:
                severity = EvidenceSeverity.HIGH
            elif raw_sev in ["WARN", "WARNING"]:
                severity = EvidenceSeverity.MEDIUM
            elif raw_sev in ["INFO", "INFORMATION", "NOTICE", "DEBUG"]:
                severity = EvidenceSeverity.INFO

            # 6. Extract Telemetry Identifiers
            trace_id = self.sanitize_field_value(self.mapper.extract(clean_row, "trace_id")) or None
            span_id = self.sanitize_field_value(self.mapper.extract(clean_row, "span_id")) or None
            parent_span_id = self.sanitize_field_value(self.mapper.extract(clean_row, "parent_span_id")) or None
            request_id = self.sanitize_field_value(self.mapper.extract(clean_row, "request_id")) or None
            deployment_id = self.sanitize_field_value(self.mapper.extract(clean_row, "deployment_id")) or None
            configuration_id = self.sanitize_field_value(self.mapper.extract(clean_row, "configuration_id")) or None

            # 7. Evidence Type Resolution
            raw_type = str(clean_row.get("evidence_type") or clean_row.get("type") or "LOG").upper()
            try:
                ev_type = EvidenceType(raw_type)
            except Exception:
                if trace_id or span_id:
                    ev_type = EvidenceType.TRACE
                elif deployment_id:
                    ev_type = EvidenceType.DEPLOYMENT
                elif configuration_id:
                    ev_type = EvidenceType.CONFIGURATION
                else:
                    ev_type = EvidenceType.LOG

            # 8. Anomaly Score
            score_raw = self.mapper.extract(clean_row, "anomaly_score")
            if score_raw is not None:
                try:
                    anomaly_score = max(0.0, min(1.0, float(score_raw)))
                except (ValueError, TypeError):
                    anomaly_score = 0.0
            elif severity == EvidenceSeverity.CRITICAL:
                anomaly_score = 0.90
            elif severity == EvidenceSeverity.HIGH:
                anomaly_score = 0.75
            elif severity == EvidenceSeverity.MEDIUM:
                anomaly_score = 0.40
            else:
                anomaly_score = 0.05

            # 9. Deduplication Signature
            sig_input = f"{incident_id}_{service}_{iso_ts}_{clean_msg[:120]}"
            signature = hashlib.sha256(sig_input.encode()).hexdigest()

            # Check for duplicate
            is_duplicate = (signature in existing_signatures) or (signature in seen_batch_signatures)
            if is_duplicate:
                duplicate_count += 1
                if len(preview_rows) < self.PREVIEW_LIMIT:
                    preview_rows.append({
                        "row": row_index,
                        "timestamp": iso_ts,
                        "service": service,
                        "type": ev_type.value,
                        "severity": severity.value,
                        "anomaly_score": round(anomaly_score, 2),
                        "summary": clean_msg[:120],
                        "status": "DUPLICATE",
                        "error": "Duplicate of an existing evidence record or duplicate within batch.",
                    })
                continue

            seen_batch_signatures.add(signature)

            # Generate unique deterministic evidence ID
            provided_id = clean_row.get("id") or clean_row.get("evidence_id")
            if provided_id and str(provided_id).strip():
                ev_id = str(provided_id).strip()
            else:
                prefix = ev_type.value.lower()[:3]
                ev_id = f"{prefix}_{signature[:10]}"

            # Construct NormalizedEvidence record
            evidence_item = NormalizedEvidence(
                id=ev_id,
                incident_id=incident_id,
                evidence_type=ev_type,
                service=service,
                timestamp=iso_ts,
                severity=severity,
                event_type=ev_type.value,
                message=clean_msg,
                summary=clean_msg[:240],
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                request_id=request_id,
                deployment_id=deployment_id,
                configuration_id=configuration_id,
                source_type=SourceType.ORGANIZER,
                source_file=source_file,
                source_record=clean_row,
                redacted=("[REDACTED" in clean_msg),
                anomaly_score=anomaly_score,
                metadata={"csv_row": row_index, "signature": signature},
                details=clean_row,
            )

            normalized_records.append(evidence_item)
            valid_count += 1

            if len(preview_rows) < self.PREVIEW_LIMIT:
                preview_rows.append({
                    "row": row_index,
                    "id": ev_id,
                    "timestamp": iso_ts,
                    "service": service,
                    "type": ev_type.value,
                    "severity": severity.value,
                    "anomaly_score": round(anomaly_score, 2),
                    "summary": clean_msg[:120],
                    "status": "VALID",
                    "error": None,
                })

        # Determine overall validation status
        if total_rows == 0:
            status = "INVALID"
        elif valid_count == 0 and invalid_count > 0:
            status = "INVALID"
        elif invalid_count > 0 or duplicate_count > 0:
            status = "PARTIAL_VALID"
        else:
            status = "VALID"

        return {
            "status": status,
            "total_rows": total_rows,
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "duplicate_count": duplicate_count,
            "preview_rows": preview_rows,
            "normalized_records": normalized_records,
            "row_errors": row_errors,
            "warnings": warnings,
            "services_detected": sorted(list(services_detected)),
        }

    def parse(
        self,
        raw_data: Any,
        incident_id: str,
        source_type: SourceType = SourceType.ORGANIZER,
    ) -> List[NormalizedEvidence]:
        """Implements BaseIngestionAdapter parse interface."""
        report = self.parse_csv_stream(str(raw_data), incident_id)
        return report["normalized_records"]
