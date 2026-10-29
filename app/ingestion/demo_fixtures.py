"""Demonstration & Development Fixtures for AO-03.

IMPORTANT:
All data here is strictly DEVELOPMENT / SYNTHETIC DATA for local development and testing.
Every record is explicitly tagged with source_type='SYNTHETIC_DEMO'.
This file does NOT contain organizer data.
"""

from typing import Dict, Any, List
from app.models.evidence import (
    NormalizedEvidence,
    EvidenceType,
    EvidenceSeverity,
    SourceType,
    ServiceNode,
    ServiceDependency,
)
from app.models.incident import Incident
from app.storage.base import BaseStorage


def get_demo_services() -> List[ServiceNode]:
    return [
        ServiceNode(id="api-gateway", name="API Gateway", tier="ingress", description="External ingress routing and authentication gate"),
        ServiceNode(id="order-service", name="Order Service", tier="core", description="Coordinates checkout and order fulfillment"),
        ServiceNode(id="payment-service", name="Payment Service", tier="core", description="Processes payment transactions and interacts with DB"),
        ServiceNode(id="inventory-service", name="Inventory Service", tier="core", description="Manages warehouse stock allocations"),
        ServiceNode(id="auth-service", name="Auth Service", tier="security", description="Token issuance and permission verification"),
        ServiceNode(id="notification-service", name="Notification Service", tier="worker", description="Async email and SMS dispatch"),
    ]


def get_demo_dependencies() -> List[ServiceDependency]:
    return [
        ServiceDependency(id="dep_gw_auth", source_service="api-gateway", target_service="auth-service", call_type="HTTP", critical=True),
        ServiceDependency(id="dep_gw_order", source_service="api-gateway", target_service="order-service", call_type="HTTP", critical=True),
        ServiceDependency(id="dep_order_payment", source_service="order-service", target_service="payment-service", call_type="HTTP", critical=True),
        ServiceDependency(id="dep_order_inventory", source_service="order-service", target_service="inventory-service", call_type="HTTP", critical=True),
        ServiceDependency(id="dep_order_notify", source_service="order-service", target_service="notification-service", call_type="ASYNC", critical=False),
    ]


def get_demo_incidents() -> List[Incident]:
    return [
        # Incident 1: Deployment & Config drift -> Failure (INC-2026-001)
        Incident(
            id="INC-2026-001",
            title="Checkout & Payment Gateway 504 Timeout Cascade",
            description="The incident is resolved; customer checkout failed with 504 errors on api-gateway after a deployment to payment-service. Nobody knows why.",
            status="RESOLVED",
            severity="CRITICAL",
            started_at="2026-10-28T14:00:00Z",
            resolved_at="2026-10-28T14:30:00Z",
            affected_services=["api-gateway", "order-service", "payment-service"],
        ),

        # Incident 2: Insufficient Telemetry -> UNKNOWN (INC-2026-002)
        Incident(
            id="INC-2026-002",
            title="Transient Health Check Blip (Sparse Telemetry)",
            description="A brief monitoring alert was cleared automatically. Sparse logs exist with no causal correlation or anomalous thresholds.",
            status="RESOLVED",
            severity="LOW",
            started_at="2026-10-28T11:00:00Z",
            resolved_at="2026-10-28T11:10:00Z",
            affected_services=["inventory-service"],
        ),

        # Incident 3: Downstream Dependency Failure -> Cascading Failure (INC-2026-003)
        Incident(
            id="INC-2026-003",
            title="Auth Service Token Validation Outage Cascading to API Gateway",
            description="All external requests failed with HTTP 500 / 401 at the gateway. Root cause was downstream auth-service database locking.",
            status="RESOLVED",
            severity="HIGH",
            started_at="2026-10-28T09:00:00Z",
            resolved_at="2026-10-28T09:40:00Z",
            affected_services=["api-gateway", "auth-service"],
        ),
    ]


def get_demo_evidence() -> List[NormalizedEvidence]:
    return [
        # =====================================================================
        # SCENARIO 1: DEPLOYMENT -> FAILURE (INC-2026-001)
        # =====================================================================
        NormalizedEvidence(
            id="EVID-DEMO-001",
            incident_id="INC-2026-001",
            evidence_type=EvidenceType.CONFIGURATION,
            service="payment-service",
            timestamp="2026-10-28T14:02:10Z",
            summary="Configuration update: 'db.pool.max_connections' changed from 50 to 5",
            details={"key": "db.pool.max_connections", "previous_value": 50, "new_value": 5, "author": "ops-bot"},
            severity=EvidenceSeverity.HIGH,
            anomaly_score=0.90,
            source_type=SourceType.SYNTHETIC_DEMO,
            configuration_id="cfg-pool-limit",
        ),
        NormalizedEvidence(
            id="EVID-DEMO-002",
            incident_id="INC-2026-001",
            evidence_type=EvidenceType.DEPLOYMENT,
            service="payment-service",
            timestamp="2026-10-28T14:03:00Z",
            summary="Deployment v2.4.1 applied config change to payment-service pods",
            details={"commit_hash": "f8a91bc", "image_tag": "payment:v2.4.1", "diff_summary": "Update default DB pool limits"},
            severity=EvidenceSeverity.HIGH,
            anomaly_score=0.88,
            source_type=SourceType.SYNTHETIC_DEMO,
            deployment_id="deploy-v2.4.1",
        ),
        NormalizedEvidence(
            id="EVID-DEMO-003",
            incident_id="INC-2026-001",
            evidence_type=EvidenceType.METRIC,
            service="payment-service",
            timestamp="2026-10-28T14:05:30Z",
            summary="db_connection_wait_ms exceeded threshold: value=4520ms (threshold=200ms, z_score=6.1)",
            details={"metric_name": "db_connection_wait_ms", "value": 4520, "threshold": 200, "z_score": 6.1},
            severity=EvidenceSeverity.CRITICAL,
            anomaly_score=0.95,
            source_type=SourceType.SYNTHETIC_DEMO,
            metric_name="db_connection_wait_ms",
            metric_value=4520.0,
        ),
        NormalizedEvidence(
            id="EVID-DEMO-004",
            incident_id="INC-2026-001",
            evidence_type=EvidenceType.LOG,
            service="payment-service",
            timestamp="2026-10-28T14:06:15Z",
            summary="ConnectionPoolTimeoutException: Timeout waiting for idle DB connection from pool (limit=5 reached)",
            details={"level": "ERROR", "exception_class": "ConnectionPoolTimeoutException", "pool_size": 5, "active": 5},
            severity=EvidenceSeverity.HIGH,
            anomaly_score=0.92,
            source_type=SourceType.SYNTHETIC_DEMO,
        ),
        NormalizedEvidence(
            id="EVID-DEMO-005",
            incident_id="INC-2026-001",
            evidence_type=EvidenceType.TRACE,
            service="payment-service",
            timestamp="2026-10-28T14:07:00Z",
            summary="Trace /pay span error: HTTP 500 (duration=5200ms)",
            details={"trace_id": "tr-71092a", "span_id": "sp-9901", "endpoint": "/pay", "http_status": 500, "duration_ms": 5200, "error": True},
            severity=EvidenceSeverity.CRITICAL,
            anomaly_score=0.88,
            source_type=SourceType.SYNTHETIC_DEMO,
            trace_id="tr-71092a",
            span_id="sp-9901",
        ),
        NormalizedEvidence(
            id="EVID-DEMO-006",
            incident_id="INC-2026-001",
            evidence_type=EvidenceType.METRIC,
            service="order-service",
            timestamp="2026-10-28T14:08:20Z",
            summary="client_call_duration_ms to payment-service escalated to 5100ms",
            details={"metric_name": "client_call_duration_ms", "target": "payment-service", "value": 5100, "threshold": 300},
            severity=EvidenceSeverity.HIGH,
            anomaly_score=0.80,
            source_type=SourceType.SYNTHETIC_DEMO,
            metric_name="client_call_duration_ms",
            metric_value=5100.0,
        ),
        NormalizedEvidence(
            id="EVID-DEMO-007",
            incident_id="INC-2026-001",
            evidence_type=EvidenceType.LOG,
            service="order-service",
            timestamp="2026-10-28T14:09:00Z",
            summary="DownstreamPaymentTimeout: payment-service call failed to respond in 5000ms",
            details={"level": "ERROR", "target_service": "payment-service", "endpoint": "/pay"},
            severity=EvidenceSeverity.HIGH,
            anomaly_score=0.78,
            source_type=SourceType.SYNTHETIC_DEMO,
        ),
        NormalizedEvidence(
            id="EVID-DEMO-008",
            incident_id="INC-2026-001",
            evidence_type=EvidenceType.LOG,
            service="api-gateway",
            timestamp="2026-10-28T14:10:00Z",
            summary="504 Gateway Timeout returned to client on POST /checkout",
            details={"level": "ERROR", "http_status": 504, "path": "/checkout"},
            severity=EvidenceSeverity.HIGH,
            anomaly_score=0.75,
            source_type=SourceType.SYNTHETIC_DEMO,
        ),
        NormalizedEvidence(
            id="EVID-DEMO-009",
            incident_id="INC-2026-001",
            evidence_type=EvidenceType.LOG,
            service="payment-service",
            timestamp="2026-10-28T14:26:00Z",
            summary="Payment service restarted with restored pool config (limit=50). Connection pool healthy.",
            details={"level": "INFO", "pool_size": 50, "status": "RECOVERED"},
            severity=EvidenceSeverity.INFO,
            anomaly_score=0.1,
            source_type=SourceType.SYNTHETIC_DEMO,
        ),

        # =====================================================================
        # SCENARIO 2: INSUFFICIENT EVIDENCE -> UNKNOWN (INC-2026-002)
        # =====================================================================
        NormalizedEvidence(
            id="EVID-DEMO-020",
            incident_id="INC-2026-002",
            evidence_type=EvidenceType.LOG,
            service="inventory-service",
            timestamp="2026-10-28T11:02:00Z",
            summary="Routine cache cleanup completed successfully",
            details={"level": "INFO", "items_cleared": 42},
            severity=EvidenceSeverity.INFO,
            anomaly_score=0.05,
            source_type=SourceType.SYNTHETIC_DEMO,
        ),
        NormalizedEvidence(
            id="EVID-DEMO-021",
            incident_id="INC-2026-002",
            evidence_type=EvidenceType.METRIC,
            service="inventory-service",
            timestamp="2026-10-28T11:05:00Z",
            summary="cpu_utilization = 14% (normal)",
            details={"metric_name": "cpu_utilization", "value": 14, "threshold": 80},
            severity=EvidenceSeverity.INFO,
            anomaly_score=0.05,
            source_type=SourceType.SYNTHETIC_DEMO,
            metric_name="cpu_utilization",
            metric_value=14.0,
        ),

        # =====================================================================
        # SCENARIO 3: DOWNSTREAM DEPENDENCY FAILURE -> CASCADE (INC-2026-003)
        # =====================================================================
        NormalizedEvidence(
            id="EVID-DEMO-030",
            incident_id="INC-2026-003",
            evidence_type=EvidenceType.METRIC,
            service="auth-service",
            timestamp="2026-10-28T09:01:00Z",
            summary="auth_db_lock_wait_seconds spiked to 12.4s (threshold=1.0s, z_score=5.8)",
            details={"metric_name": "auth_db_lock_wait_seconds", "value": 12.4, "threshold": 1.0, "z_score": 5.8},
            severity=EvidenceSeverity.CRITICAL,
            anomaly_score=0.94,
            source_type=SourceType.SYNTHETIC_DEMO,
            metric_name="auth_db_lock_wait_seconds",
            metric_value=12.4,
        ),
        NormalizedEvidence(
            id="EVID-DEMO-031",
            incident_id="INC-2026-003",
            evidence_type=EvidenceType.LOG,
            service="auth-service",
            timestamp="2026-10-28T09:02:15Z",
            summary="DatabaseDeadlockException: Lock wait timeout exceeded in sessions table update",
            details={"level": "ERROR", "exception": "DatabaseDeadlockException"},
            severity=EvidenceSeverity.CRITICAL,
            anomaly_score=0.92,
            source_type=SourceType.SYNTHETIC_DEMO,
        ),
        NormalizedEvidence(
            id="EVID-DEMO-032",
            incident_id="INC-2026-003",
            evidence_type=EvidenceType.TRACE,
            service="auth-service",
            timestamp="2026-10-28T09:03:00Z",
            summary="Trace /validate_token failed: HTTP 500 (duration=8200ms)",
            details={"trace_id": "tr-auth-8812", "span_id": "sp-auth-1", "http_status": 500, "error": True},
            severity=EvidenceSeverity.CRITICAL,
            anomaly_score=0.90,
            source_type=SourceType.SYNTHETIC_DEMO,
            trace_id="tr-auth-8812",
            span_id="sp-auth-1",
        ),
        NormalizedEvidence(
            id="EVID-DEMO-033",
            incident_id="INC-2026-003",
            evidence_type=EvidenceType.LOG,
            service="api-gateway",
            timestamp="2026-10-28T09:05:00Z",
            summary="AuthenticationGatewayError: Failed to verify JWT token from auth-service; returned 500",
            details={"level": "ERROR", "upstream": "auth-service", "http_status": 502},
            severity=EvidenceSeverity.HIGH,
            anomaly_score=0.76,
            source_type=SourceType.SYNTHETIC_DEMO,
            trace_id="tr-auth-8812",
            parent_span_id="sp-auth-1",
        ),
        NormalizedEvidence(
            id="EVID-DEMO-034",
            incident_id="INC-2026-003",
            evidence_type=EvidenceType.LOG,
            service="auth-service",
            timestamp="2026-10-28T09:35:00Z",
            summary="Database locks cleared. Token validation service back to normal latency (12ms).",
            details={"level": "INFO", "status": "RECOVERED"},
            severity=EvidenceSeverity.INFO,
            anomaly_score=0.05,
            source_type=SourceType.SYNTHETIC_DEMO,
        ),
    ]


def load_demo_data(storage: BaseStorage) -> Dict[str, int]:
    """Populates storage with the clearly labeled SYNTHETIC DEMONSTRATION fixtures."""
    services = get_demo_services()
    for s in services:
        storage.save_service(s)

    deps = get_demo_dependencies()
    for d in deps:
        storage.save_dependency(d)

    incidents = get_demo_incidents()
    for inc in incidents:
        storage.save_incident(inc)

    evidence_list = get_demo_evidence()
    storage.save_evidence_batch(evidence_list)

    return {
        "services": len(services),
        "dependencies": len(deps),
        "incidents": len(incidents),
        "evidence": len(evidence_list),
    }
