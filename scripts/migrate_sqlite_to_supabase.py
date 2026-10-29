"""SQLite to Supabase PostgreSQL Data Migration Script for TraceWise AO-03.
Reads all existing data from the active local SQLite database and migrates it
into Supabase via the PostgREST API with idempotent upsert resolution.
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.config import Config
from app.storage.sqlite_adapter import SqliteStorage
from app.storage.supabase_adapter import SupabaseStorage


def run_migration() -> Dict[str, Any]:
    print("=" * 70)
    print(" TraceWise AO-03 :: SQLite -> Supabase PostgreSQL Data Migration")
    print("=" * 70)

    sqlite_path = Config.SQLITE_DB_PATH
    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(f"SQLite database not found at {sqlite_path}")

    supabase_url = Config.SUPABASE_URL
    supabase_key = Config.SUPABASE_KEY

    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be configured in environment.")

    print(f"\nSource SQLite: {sqlite_path}")
    print(f"Target Supabase: {supabase_url}\n")

    sqlite = SqliteStorage(sqlite_path)
    supabase = SupabaseStorage(supabase_url=supabase_url, supabase_key=supabase_key)

    # 1. Services
    services = sqlite.get_services()
    print(f"[*] Migrating {len(services)} services...")
    for svc in services:
        supabase.save_service(svc)

    # 2. Dependencies
    dependencies = sqlite.get_dependencies()
    print(f"[*] Migrating {len(dependencies)} dependency edges...")
    for dep in dependencies:
        supabase.save_dependency(dep)

    # 3. Incidents
    incidents = sqlite.get_incidents()
    print(f"[*] Migrating {len(incidents)} incidents...")
    for inc in incidents:
        supabase.save_incident(inc)

    # 4. Evidence Records
    all_evidence = sqlite.get_all_evidence(limit=2000)
    print(f"[*] Migrating {len(all_evidence)} normalized evidence records...")
    supabase.save_evidence_batch(all_evidence)

    # 5. Candidate Causes
    total_candidates = 0
    for inc in incidents:
        cands = sqlite.get_candidates_by_incident(inc.id)
        for c in cands:
            supabase.save_candidate(c)
            total_candidates += 1
    print(f"[*] Migrating {total_candidates} candidate causes...")

    # 6. Timeline Events
    total_timeline = 0
    for inc in incidents:
        events = sqlite.get_timeline_by_incident(inc.id)
        for ev in events:
            supabase.save_timeline_event(ev)
            total_timeline += 1
    print(f"[*] Migrating {total_timeline} timeline events...")

    # 7. Analysis Runs (read directly from SQLite connection)
    with sqlite._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM analysis_runs")
        run_rows = cursor.fetchall()
        print(f"[*] Migrating {len(run_rows)} analysis runs...")
        analysis_runs_payload = []
        for r in run_rows:
            llm_summary = r["llm_summary"]
            if isinstance(llm_summary, str):
                try: llm_summary = json.loads(llm_summary)
                except Exception: llm_summary = {}
            analysis_runs_payload.append({
                "id": r["id"],
                "incident_id": r["incident_id"],
                "status": r["status"],
                "engine_version": r["engine_version"],
                "top_candidate_id": r["top_candidate_id"],
                "llm_hypothesis": r["llm_hypothesis"],
                "llm_summary": llm_summary or {},
                "llm_status": r["llm_status"],
            })
        supabase.save_analysis_runs_batch(analysis_runs_payload)

    # 8. Registered System Users
    users = sqlite.get_all_users()
    print(f"[*] Migrating {len(users)} registered users...")
    for u in users:
        supabase.save_user(u)

    # 9. Audit Logs
    audit_logs = sqlite.get_audit_logs(limit=2000)
    print(f"[*] Migrating {len(audit_logs)} security audit logs...")
    supabase.save_audit_logs_batch(audit_logs)

    print("\n" + "-" * 70)
    print(" VERIFYING DATA COUNTS & INTEGRITY (SQLite vs Supabase)")
    print("-" * 70)

    # Verification counts
    counts_sqlite = get_sqlite_counts(sqlite_path)
    counts_supabase = get_supabase_counts(supabase)

    print(f"{'Entity':<20} | {'SQLite Count':<14} | {'Supabase Count':<14} | {'Match'}")
    print("-" * 65)

    all_matched = True
    for entity in ["services", "dependencies", "incidents", "evidence", "candidates", "timeline_events", "analysis_runs", "users", "audit_logs"]:
        c_sql = counts_sqlite.get(entity, 0)
        c_sup = counts_supabase.get(entity, 0)
        match_str = "[OK] MATCH" if c_sql == c_sup else "[MISMATCH]"
        if c_sql != c_sup:
            all_matched = False
        print(f"{entity:<20} | {c_sql:<14} | {c_sup:<14} | {match_str}")

    print("-" * 65)
    if all_matched:
        print("[SUCCESS] All tables migrated with 100% data parity!\n")
    else:
        print("[WARN] Some table counts differed. Inspect logs above.\n")

    return {
        "sqlite": counts_sqlite,
        "supabase": counts_supabase,
        "all_matched": all_matched,
    }


def get_sqlite_counts(db_path: str) -> Dict[str, int]:
    counts = {}
    with sqlite3.connect(db_path) as conn:
        c = conn.cursor()
        for tbl in ["services", "dependencies", "incidents", "evidence", "candidates", "analysis_runs", "timeline_events", "users", "audit_logs"]:
            try:
                c.execute(f"SELECT COUNT(*) FROM {tbl}")
                counts[tbl] = c.fetchone()[0]
            except Exception:
                counts[tbl] = 0
    return counts


def get_supabase_counts(supabase: SupabaseStorage) -> Dict[str, int]:
    counts = {}
    entities = [
        ("services", lambda: len(supabase.get_services())),
        ("dependencies", lambda: len(supabase.get_dependencies())),
        ("incidents", lambda: len(supabase.get_incidents())),
        ("evidence", lambda: len(supabase.get_all_evidence(limit=5000))),
        ("candidates", lambda: sum(len(supabase.get_candidates_by_incident(i.id)) for i in supabase.get_incidents())),
        ("timeline_events", lambda: sum(len(supabase.get_timeline_by_incident(i.id)) for i in supabase.get_incidents())),
        ("analysis_runs", lambda: supabase.get_analysis_runs_count()),
        ("users", lambda: len(supabase.get_all_users())),
        ("audit_logs", lambda: len(supabase.get_audit_logs(limit=5000))),
    ]
    for name, getter in entities:
        try:
            counts[name] = getter()
        except Exception as e:
            counts[name] = 0
    return counts


if __name__ == "__main__":
    try:
        run_migration()
    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        sys.exit(1)
