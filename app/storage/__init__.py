"""Storage factory for AO-03.
"""

from typing import Optional
from app.config import Config
from app.storage.base import BaseStorage
from app.storage.sqlite_adapter import SqliteStorage
from app.storage.supabase_adapter import SupabaseStorage

_storage_instance: Optional[BaseStorage] = None


def get_storage() -> BaseStorage:
    global _storage_instance
    if _storage_instance is None:
        backend = (Config.DATABASE_BACKEND or Config.STORAGE_BACKEND or "sqlite").lower()
        if backend == "supabase":
            if not Config.SUPABASE_URL or not Config.SUPABASE_KEY:
                raise ValueError(
                    "DATABASE_BACKEND is configured as 'supabase', but SUPABASE_URL or SUPABASE_KEY is missing from environment."
                )
            _storage_instance = SupabaseStorage(
                supabase_url=Config.SUPABASE_URL,
                supabase_key=Config.SUPABASE_KEY,
                fallback_sqlite_path=Config.SQLITE_DB_PATH,
            )
        elif backend == "sqlite":
            _storage_instance = SqliteStorage(Config.SQLITE_DB_PATH)
        else:
            raise ValueError(f"Unsupported DATABASE_BACKEND '{backend}'. Must be 'supabase' or 'sqlite'.")
    return _storage_instance


def reset_storage() -> None:
    global _storage_instance
    _storage_instance = None
