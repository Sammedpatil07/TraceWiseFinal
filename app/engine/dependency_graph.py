"""Dependency Graph Support for AO-03.
Utilizes NetworkX to model service topology, blast radius, upstream/downstream relationships,
and trace-inferred dependency discovery.
"""

from typing import List, Dict, Set, Optional, Any
import networkx as nx
from app.models.evidence import ServiceDependency, ServiceNode, NormalizedEvidence, EvidenceType


class DependencyGraphManager:
    def __init__(
        self,
        services: Optional[List[ServiceNode]] = None,
        dependencies: Optional[List[ServiceDependency]] = None,
    ):
        self.graph = nx.DiGraph()
        self.service_map: Dict[str, ServiceNode] = {}

        if services:
            for s in services:
                self.add_service(s)

        if dependencies:
            for d in dependencies:
                self.add_dependency(d)

    def add_service(self, service: ServiceNode) -> None:
        self.service_map[service.id] = service
        self.graph.add_node(service.id, name=service.name, tier=service.tier)

    def add_dependency(self, dependency: ServiceDependency) -> None:
        if dependency.source_service not in self.graph:
            self.graph.add_node(dependency.source_service, name=dependency.source_service, tier="service")
        if dependency.target_service not in self.graph:
            self.graph.add_node(dependency.target_service, name=dependency.target_service, tier="service")

        self.graph.add_edge(
            dependency.source_service,
            dependency.target_service,
            id=dependency.id,
            call_type=dependency.call_type,
            critical=dependency.critical,
        )

    def infer_dependencies_from_traces(self, evidence_list: List[NormalizedEvidence]) -> List[ServiceDependency]:
        """Infers call dependencies from trace spans: caller (parent span) -> callee (child span)."""
        span_to_service: Dict[str, str] = {}
        child_to_parent: List[Tuple[str, str, str]] = []  # (caller_svc, callee_svc, trace_id)
        inferred_deps: List[ServiceDependency] = []

        traces = [e for e in evidence_list if e.evidence_type == EvidenceType.TRACE]
        for t in traces:
            if t.span_id and t.service:
                span_to_service[t.span_id] = t.service

        for t in traces:
            if t.parent_span_id and t.parent_span_id in span_to_service:
                caller_svc = span_to_service[t.parent_span_id]
                callee_svc = t.service
                if caller_svc != callee_svc:
                    child_to_parent.append((caller_svc, callee_svc, t.trace_id or "trace"))

        # Deduplicate and register into graph
        seen = set()
        for caller, callee, trace_id in child_to_parent:
            edge_key = (caller, callee)
            if edge_key not in seen:
                seen.add(edge_key)
                dep = ServiceDependency(
                    id=f"inferred_{caller}_{callee}",
                    source_service=caller,
                    target_service=callee,
                    call_type="HTTP_TRACE",
                    critical=True,
                )
                self.add_dependency(dep)
                inferred_deps.append(dep)

        return inferred_deps

    def can_cause_impact_on(self, candidate_service: str, symptom_service: str) -> bool:
        """Checks if a failure in candidate_service can reach/impact symptom_service.
        If symptom_service calls candidate_service directly or transitively,
        symptom_service has a path to candidate_service.
        """
        if candidate_service == symptom_service:
            return True
        if candidate_service not in self.graph or symptom_service not in self.graph:
            return False
        return nx.has_path(self.graph, symptom_service, candidate_service)

    def get_upstream_services(self, service_id: str) -> List[str]:
        """Returns direct and transitive upstream callers that depend on service_id."""
        if service_id not in self.graph:
            return []
        reversed_graph = self.graph.reverse(copy=False)
        return list(nx.descendants(reversed_graph, service_id))

    def get_downstream_services(self, service_id: str) -> List[str]:
        """Returns direct and transitive downstream dependencies that service_id calls."""
        if service_id not in self.graph:
            return []
        return list(nx.descendants(self.graph, service_id))

    def get_blast_radius(self, service_id: str) -> List[str]:
        """Returns all services affected if service_id fails (its upstream callers)."""
        return self.get_upstream_services(service_id)

    def get_upstream_distance(self, candidate_service: str, symptom_service: str) -> int:
        """Returns hop distance from symptom_service to candidate_service."""
        if candidate_service == symptom_service:
            return 0
        if not self.can_cause_impact_on(candidate_service, symptom_service):
            return 999
        try:
            return nx.shortest_path_length(self.graph, symptom_service, candidate_service)
        except Exception:
            return 999

    def get_incident_graph(
        self,
        affected_services: Optional[List[str]] = None,
        suspected_root: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Returns complete topological graph state enriched with root and affected node roles."""
        affected_set = set(affected_services or [])
        upstream_of_root = set(self.get_upstream_services(suspected_root)) if suspected_root else set()
        downstream_of_root = set(self.get_downstream_services(suspected_root)) if suspected_root else set()

        nodes = []
        for node_id in self.graph.nodes:
            data = self.graph.nodes[node_id]
            nodes.append({
                "id": node_id,
                "label": data.get("name", node_id),
                "tier": data.get("tier", "service"),
                "is_root": (node_id == suspected_root),
                "is_affected": (node_id in affected_set),
                "is_upstream": (node_id in upstream_of_root),
                "is_downstream": (node_id in downstream_of_root),
            })

        edges = []
        for u, v, data in self.graph.edges(data=True):
            edges.append({
                "id": f"{u}->{v}",
                "source": u,
                "target": v,
                "call_type": data.get("call_type", "HTTP"),
                "critical": data.get("critical", True),
            })

        return {
            "nodes": nodes,
            "edges": edges,
            "suspected_root": suspected_root,
            "affected_services": list(affected_set),
            "blast_radius": list(upstream_of_root),
        }

    def to_cytoscape_elements(self) -> List[Dict[str, Any]]:
        """Exports graph elements formatted for frontend visualization."""
        elements = []
        for node_id in self.graph.nodes:
            node_data = self.graph.nodes[node_id]
            elements.append({
                "data": {
                    "id": node_id,
                    "label": node_data.get("name", node_id),
                    "tier": node_data.get("tier", "service"),
                }
            })

        for u, v, data in self.graph.edges(data=True):
            elements.append({
                "data": {
                    "id": f"{u}->{v}",
                    "source": u,
                    "target": v,
                    "call_type": data.get("call_type", "HTTP"),
                }
            })
        return elements
