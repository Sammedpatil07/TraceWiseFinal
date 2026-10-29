"""Configuration module for AO-03.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    # Flask settings
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-ao03-local-key")
    DEBUG = os.getenv("FLASK_DEBUG", "1") == "1"
    PORT = int(os.getenv("PORT", "5000"))

    # Session & Cookie Security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = 43200  # 12 hours in seconds

    # Storage Backend: 'sqlite' (local fallback) or 'supabase'
    STORAGE_BACKEND = os.getenv("DATABASE_BACKEND", os.getenv("STORAGE_BACKEND", "sqlite")).lower()
    DATABASE_BACKEND = STORAGE_BACKEND
    SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", str(BASE_DIR / "data" / "ao03_telemetry.db"))

    # Supabase credentials (for remote PostgreSQL persistence)
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY", os.getenv("SUPABASE_PUBLISHABLE_KEY", ""))
    SUPABASE_PUBLISHABLE_KEY = SUPABASE_KEY
    SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL", "")

    # Ollama Local LLM Provider (no API key required)
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")

    # Deterministic RCA Weights (Sum = 1.0)
    # Termed "Evidence Score" (never called a probability without calibration).
    WEIGHT_TEMPORAL_PRECEDENCE = float(os.getenv("WEIGHT_TEMPORAL_PRECEDENCE", "0.15"))
    WEIGHT_DEPENDENCY_RELEVANCE = float(os.getenv("WEIGHT_DEPENDENCY_RELEVANCE", "0.15"))
    WEIGHT_ANOMALY_MAGNITUDE = float(os.getenv("WEIGHT_ANOMALY_MAGNITUDE", "0.15"))
    WEIGHT_ERROR_CORRELATION = float(os.getenv("WEIGHT_ERROR_CORRELATION", "0.15"))
    WEIGHT_TRACE_CORRELATION = float(os.getenv("WEIGHT_TRACE_CORRELATION", "0.10"))
    WEIGHT_DEPLOYMENT_PROXIMITY = float(os.getenv("WEIGHT_DEPLOYMENT_PROXIMITY", "0.10"))
    WEIGHT_CONFIGURATION_PROXIMITY = float(os.getenv("WEIGHT_CONFIGURATION_PROXIMITY", "0.10"))
    WEIGHT_BLAST_RADIUS = float(os.getenv("WEIGHT_BLAST_RADIUS", "0.10"))

    # Minimum threshold below which candidate is rejected or labeled UNKNOWN / INSUFFICIENT EVIDENCE
    MIN_CONFIDENCE_THRESHOLD = float(os.getenv("MIN_CONFIDENCE_THRESHOLD", "0.35"))
