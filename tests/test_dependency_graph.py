"""Unit tests for Dependency Graph Support and blast radius calculations.
"""

import pytest
from app.models.evidence import ServiceNode, ServiceDependency
from app.engine.dependency_graph import DependencyGraphManager


def test_dependency_graph():
    services = [
        ServiceNode(id="api-gateway", name="Gateway", tier="ingress"),
        ServiceNode(id="order-service", name="Orders", tier="core"),
        ServiceNode(id="payment-service", name="Payments", tier="core"),
        ServiceNode(id="email-service", name="Emails", tier="worker"),
    ]
    dependencies = [
        ServiceDependency(id="d1", source_service="api-gateway", target_service="order-service"),
        ServiceDependency(id="d2", source_service="order-service", target_service="payment-service"),
        ServiceDependency(id="d3", source_service="order-service", target_service="email-service"),
    ]

    graph = DependencyGraphManager(services, dependencies)

    # In microservices, if api-gateway calls order-service, which calls payment-service:
    # A failure in payment-service impacts order-service and api-gateway
    assert graph.can_cause_impact_on("payment-service", "order-service") is True
    assert graph.can_cause_impact_on("payment-service", "api-gateway") is True

    # But email-service does not call payment-service
    assert graph.can_cause_impact_on("payment-service", "email-service") is False

    # Blast radius: callers that depend on payment-service
    blast = graph.get_blast_radius("payment-service")
    assert "order-service" in blast
    assert "api-gateway" in blast

    # Distance
    dist_order = graph.get_upstream_distance("payment-service", "order-service")
    dist_gw = graph.get_upstream_distance("payment-service", "api-gateway")
    assert dist_order == 1
    assert dist_gw == 2
