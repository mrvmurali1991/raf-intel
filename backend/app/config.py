"""
Application configuration loaded from .env file.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels above this file)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)


class Settings:
    # Gemini
    google_api_key: str = os.getenv("GOOGLE_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")

    # OpenEMR database
    openemr_db_host: str = os.getenv("OPENEMR_DB_HOST", "127.0.0.1")
    openemr_db_port: int = int(os.getenv("OPENEMR_DB_PORT", "3309"))
    openemr_db_user: str = os.getenv("OPENEMR_DB_USER", "root")
    openemr_db_password: str = os.getenv("OPENEMR_DB_PASSWORD", "root")
    openemr_db_name: str = os.getenv("OPENEMR_DB_NAME", "openemr")

    # RAF database
    raf_db_host: str = os.getenv("RAF_DB_HOST", "127.0.0.1")
    raf_db_port: int = int(os.getenv("RAF_DB_PORT", "3309"))
    raf_db_user: str = os.getenv("RAF_DB_USER", "root")
    raf_db_password: str = os.getenv("RAF_DB_PASSWORD", "root")
    raf_db_name: str = os.getenv("RAF_DB_NAME", "raf_intelligence")

    # Application
    app_port: int = int(os.getenv("APP_PORT", "8500"))
    openemr_url: str = os.getenv("OPENEMR_URL", "http://localhost:8080")

    # Redis (for Celery)
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")


settings = Settings()
