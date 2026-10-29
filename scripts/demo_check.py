#!/usr/bin/env python3
"""
TraceWise AO-03: Comprehensive Demo & Pipeline Acceptance Check
=============================================================
Validates the entire pipeline end-to-end:
  Database -> Dataset -> Ingestion -> Evidence -> Correlation ->
  Ranking -> Timeline -> Graph -> LLM -> Evidence Validation ->
  API Endpoints -> End-to-End Investigation -> Unknown Scenario Handling

Usage:
  python scripts/demo_check.py
"""

import sys
import os
import json

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import create_app
from app.config import Config
from app.storage import get_storage
from app.storage.supabase_adapter import SupabaseStorage
from app.ingestion.generic_adapter import GenericTelemetryIngestor
from app.engine.dependency_graph import DependencyGraphManager
from app.engine.correlation import CorrelationEngine
from app.engine.timeline import generate_incident_timeline
from app.engine.rca_engine import RCAEngine
from app.engine.validator import EvidenceValidator
from app.llm.explanation import ExplanationService


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


class DemoChecker:
    def __init__(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.storage = get_storage()
        self.results = []
        # Authenticate demo client as Admin
        self.client.post("/api/auth/login", json={"username": "admin", "password": "Admin!Pass2026"})

    def log_step(self, step_name: str, passed: bool, details: str = ""):
        status_badge = f"{Colors.GREEN}[PASS]{Colors.RESET}" if passed else f"{Colors.RED}[FAIL]{Colors.RESET}"
        print(f" {status_badge} {Colors.BOLD}{step_name:<28}{Colors.RESET} {details}")
        self.results.append((step_name, passed, details))

    def run_all(self) -> bool:
        print(f"\n{Colors.CYAN}{'='*70}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.CYAN} TraceWise AO-03 :: System Acceptance & Demo Readiness Check{Colors.RESET}")
        print(f"{Colors.CYAN}{'='*70}{Colors.RESET}\n")

        # 1. Database
        self.check_database()

        # 2. Dataset
        self.check_dataset()

        # 3. Ingestion
        self.check_ingestion()

        # 4. Evidence
        self.check_evidence()

        # 5. Correlation
        self.check_correlation()

        # 6. Ranking
        self.check_ranking()

        # 7. Timeline
        self.check_timeline()

        # 8. Dependency Graph
        self.check_dependency_graph()

        # 9. LLM & Fallback
        self.check_llm()

        # 10. Evidence Validation & Redaction
        self.check_evidence_validation()

        # 11. API Endpoints
        self.check_api_endpoints()

        # 12. End-to-End Investigation (INC-2026-001)
        self.check_end_to_end_investigation()

        # 13. Unknown Scenario Guardrail (INC-2026-002)
        self.check_unknown_scenario()

        # Summary
        print(f"\n{Colors.CYAN}{'-'*70}{Colors.RESET}")
        total = len(self.results)
        passed_count = sum(1 for _, p, _ in self.results if p)
        failed_count = total - passed_count

        if failed_count == 0:
            print(f"{Colors.GREEN}{Colors.BOLD}ALL {total} PIPELINE CHECKS PASSED SUCCESSFULLY!{Colors.RESET}")
            print(f"{Colors.GREEN}{Colors.BOLD}# READY FOR LOCAL HACKATHON DEMO{Colors.RESET}\n")
            return True
        else:
            print(f"{Colors.RED}{Colors.BOLD}{failed_count}/{total} CHECKS FAILED!{Colors.RESET}\n")
            return False

    def check_database(self):
        try:
            configured_backend = (Config.DATABASE_BACKEND or Config.STORAGE_BACKEND or "sqlite").upper()
            is_supabase = isinstance(self.storage, SupabaseStorage)
            active_type = "SUPABASE" if is_supabase else "SQLITE"

            # Strict verification: If SUPABASE is configured, active storage MUST genuinely be SupabaseStorage
            if configured_backend == "SUPABASE" and not is_supabase:
                self.log_step(
                    "1. Database",
                    False,
                    f"CRITICAL MISCONFIGURATION: DATABASE_BACKEND=supabase but active storage is {active_type}!",
                )
                return

            incidents = self.storage.get_incidents()
            services = self.storage.get_services()
            passed = incidents is not None and services is not None
            details = f"Active DB: {active_type} | Config: {configured_backend} | Live connection verified"
            self.log_step("1. Database", passed, details)
        except Exception as e:
            self.log_step("1. Database", False, f"Error: {e}")

    def check_dataset(self):
        try:
            incidents = self.storage.get_incidents()
            services = self.storage.get_services()
            runs_count = self.storage.get_analysis_runs_count()
            passed = len(incidents) >= 3 and len(services) >= 4
            details = f"{len(incidents)} incidents, {len(services)} services, {runs_count} prior analysis runs"
            self.log_step("2. Dataset", passed, details)
        except Exception as e:
            self.log_step("2. Dataset", False, f"Error: {e}")

    def check_ingestion(self):
        try:
            ingestor = GenericTelemetryIngestor()
            raw_sample = [{
                "source": "generic_logs",
                "timestamp": "2026-03-29T10:15:00Z",
                "service": "payment-service",
                "log_level": "ERROR",
                "message": "Payment gateway timeout after 5000ms",
                "metadata": {"endpoint": "/v1/charge", "http_status": 504}
            }]
            normalized, report = ingestor.parse(raw_sample, incident_id="INC-2026-001")
            passed = report.get("status") == "SUCCESS" and len(normalized) == 1
            details = f"Normalized {len(normalized)} raw telemetry item (status: {report.get('status')})"
            self.log_step("3. Ingestion", passed, details)
        except Exception as e:
            self.log_step("3. Ingestion", False, f"Error: {e}")

    def check_evidence(self):
        try:
            evidence = self.storage.get_evidence_by_incident("INC-2026-001")
            passed = len(evidence) > 0 and all(hasattr(e, "id") and hasattr(e, "evidence_type") for e in evidence)
            types = set(e.evidence_type.value if hasattr(e.evidence_type, "value") else str(e.evidence_type) for e in evidence)
            details = f"{len(evidence)} evidence items loaded for INC-2026-001 (types: {', '.join(sorted(types))})"
            self.log_step("4. Evidence", passed, details)
        except Exception as e:
            self.log_step("4. Evidence", False, f"Error: {e}")

    def check_correlation(self):
        try:
            services = self.storage.get_services()
            dependencies = self.storage.get_dependencies()
            graph_mgr = DependencyGraphManager(services, dependencies)
            correlation_engine = CorrelationEngine(graph_mgr)
            incident = self.storage.get_incident("INC-2026-001")
            evidence = self.storage.get_evidence_by_incident("INC-2026-001")
            candidates = correlation_engine.evaluate_candidates(incident, evidence)
            correlations = correlation_engine.find_all_correlations(evidence)
            passed = len(candidates) > 0 and len(correlations) > 0
            top = candidates[0] if candidates else None
            details = f"Correlated {len(candidates)} candidates, {len(correlations)} evidence links (top: {top.title if top else 'None'})"
            self.log_step("5. Correlation", passed, details)
        except Exception as e:
            self.log_step("5. Correlation", False, f"Error: {e}")

    def check_ranking(self):
        try:
            rca = RCAEngine(self.storage)
            result = rca.run_rca("INC-2026-001")
            passed = result.status == "SUCCESS" and result.top_candidate is not None and result.top_candidate.evidence_score > 0.5
            top = result.top_candidate
            score = top.evidence_score if top else 0.0
            breakdown = top.contributing_factors or {}
            breakdown_summary = ", ".join(f"{k}: {v:.2f}" for k, v in list(breakdown.items())[:3])
            details = f"Top cause: '{top.title if top else 'None'}' (score: {score:.3f} | {breakdown_summary})"
            self.log_step("6. Ranking", passed, details)
        except Exception as e:
            self.log_step("6. Ranking", False, f"Error: {e}")

    def check_timeline(self):
        try:
            evidence = self.storage.get_evidence_by_incident("INC-2026-001")
            events = generate_incident_timeline(evidence)
            has_evidence_ids = all(bool(ev.evidence_id) for ev in events)
            passed = len(events) >= 3 and has_evidence_ids
            details = f"{len(events)} chronological events with verified evidence linkage"
            self.log_step("7. Timeline", passed, details)
        except Exception as e:
            self.log_step("7. Timeline", False, f"Error: {e}")

    def check_dependency_graph(self):
        try:
            services = self.storage.get_services()
            dependencies = self.storage.get_dependencies()
            mgr = DependencyGraphManager(services, dependencies)
            graph = mgr.get_incident_graph(affected_services=["checkout-service", "api-gateway"], suspected_root="payment-service")
            nodes = graph.get("nodes", [])
            edges = graph.get("edges", [])
            passed = len(nodes) >= 4 and len(edges) >= 3
            details = f"{len(nodes)} service nodes, {len(edges)} causal dependency edges"
            self.log_step("8. Graph", passed, details)
        except Exception as e:
            self.log_step("8. Graph", False, f"Error: {e}")

    def check_llm(self):
        try:
            rca = RCAEngine(self.storage)
            result = rca.run_rca("INC-2026-001", trigger_llm=True)
            hypothesis = result.llm_hypothesis
            header = hypothesis.get("header", "") if hypothesis else ""
            passed = hypothesis is not None and "AI-GENERATED HYPOTHESIS" in header
            details = f"Header: '{header}'"
            self.log_step("9. LLM", passed, details)
        except Exception as e:
            self.log_step("9. LLM", False, f"Error: {e}")

    def check_evidence_validation(self):
        try:
            evidence_ids = {"EV-001", "EV-002"}
            raw_hyp = {
                "supporting_evidence": ["EV-001", "EV-999"],
                "contradicting_evidence": [],
            }
            is_valid, invalid_ids, _ = EvidenceValidator.validate_llm_hypothesis(raw_hyp, evidence_ids)
            has_flagged_hallucination = not is_valid and "EV-999" in invalid_ids
            
            # Sensitive data redaction
            secret_text = "Authorization: Bearer sk-live-9988112233 and password=SuperSecretPassword!"
            redacted = EvidenceValidator.redact_sensitive_data(secret_text)
            secrets_removed = "sk-live-9988112233" not in redacted and "SuperSecretPassword!" not in redacted
            
            passed = has_flagged_hallucination and secrets_removed
            details = "Citation guardrail flags hallucinations; Secrets & bearer tokens safely redacted"
            self.log_step("10. Evidence Validation", passed, details)
        except Exception as e:
            self.log_step("10. Evidence Validation", False, f"Error: {e}")

    def check_api_endpoints(self):
        endpoints = [
            ("GET", "/api/stats", 200),
            ("GET", "/api/incidents", 200),
            ("GET", "/api/incidents/INC-2026-001", 200),
            ("GET", "/api/incidents/INC-2026-001/evidence", 200),
            ("GET", "/api/services", 200),
            ("GET", "/api/evaluation", 200),
        ]
        all_passed = True
        failed_ep = []
        for method, ep, exp_code in endpoints:
            res = self.client.get(ep)
            if res.status_code != exp_code:
                all_passed = False
                failed_ep.append(f"{ep} ({res.status_code})")
        details = "All core REST endpoints return 200 OK" if all_passed else f"Failures: {', '.join(failed_ep)}"
        self.log_step("11. API Endpoints", all_passed, details)

    def check_end_to_end_investigation(self):
        try:
            res = self.client.post("/api/incidents/INC-2026-001/analyze", json={"trigger_llm": True})
            if res.status_code != 200:
                self.log_step("12. E2E Investigation", False, f"Returned status {res.status_code}")
                return
            data = json.loads(res.data)
            has_candidates = len(data.get("ranked_candidates", [])) > 0 or len(data.get("candidates", [])) > 0
            has_timeline = len(data.get("timeline", [])) > 0
            has_llm = "llm_hypothesis" in data
            passed = has_candidates and has_timeline and has_llm
            top_cause = data.get("top_candidate", {}).get("title", "") if data.get("top_candidate") else "Unknown"
            details = f"Full investigation executed: Top Cause = '{top_cause}'"
            self.log_step("12. E2E Investigation", passed, details)
        except Exception as e:
            self.log_step("12. E2E Investigation", False, f"Error: {e}")

    def check_unknown_scenario(self):
        try:
            res = self.client.post("/api/incidents/INC-2026-002/analyze", json={"trigger_llm": False})
            if res.status_code != 200:
                self.log_step("13. Unknown Scenario", False, f"Returned status {res.status_code}")
                return
            data = json.loads(res.data)
            status = data.get("status", "")
            is_insufficient = data.get("is_insufficient_evidence", False) or status in ["INSUFFICIENT_EVIDENCE", "UNKNOWN"]
            passed = is_insufficient
            details = f"Honest status '{status}' returned when telemetry is sparse"
            self.log_step("13. Unknown Scenario", passed, details)
        except Exception as e:
            self.log_step("13. Unknown Scenario", False, f"Error: {e}")


if __name__ == "__main__":
    checker = DemoChecker()
    success = checker.run_all()
    sys.exit(0 if success else 1)
