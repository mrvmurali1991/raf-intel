"""
Application configuration loaded from .env file.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels above this file)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

# Resolve APP_ENV once at import time so _get_jwt_secret() can use it.
# Default is "production" so a missing env var never silently enables dev mode.
_APP_ENV = os.getenv("APP_ENV", "production").lower()


def _get_required_credential(env_var: str) -> str:
    """Return a required database credential from the environment.

    In production the application refuses to start if the variable is not set.
    In development a loud warning is logged and an empty string is returned so
    that local bring-up works without extra configuration.
    """
    value = os.getenv(env_var, "")
    if not value:
        if _APP_ENV != "development":
            raise RuntimeError(
                f"FATAL: {env_var} environment variable is not set. "
                f"The application cannot start in production without this credential. "
                f"Set {env_var} in your environment or .env file."
            )
        import logging
        logging.getLogger(__name__).warning(
            "WARNING: %s is not set. This is only acceptable in development.", env_var
        )
    return value


def _get_jwt_secret() -> str:
    """Return JWT_SECRET from env.

    In production the application refuses to start if JWT_SECRET is not set –
    a randomly generated secret would invalidate all tokens on every restart
    and is not acceptable for production use.

    In development a random secret is generated with a loud warning so that
    local bring-up works without extra configuration.
    """
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        if _APP_ENV != "development":
            raise RuntimeError(
                "FATAL: JWT_SECRET environment variable is not set. "
                "The application cannot start in production without a stable JWT secret. "
                "Set JWT_SECRET in your environment or .env file."
            )
        import logging
        logging.getLogger(__name__).warning(
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
            "WARNING: JWT_SECRET is not set – generating a random secret.\n"
            "All tokens will be invalidated on every process restart.\n"
            "This is ONLY acceptable in development. Set JWT_SECRET before\n"
            "deploying to any shared or production environment.\n"
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )
        return secrets.token_hex(32)
    return secret


def _get_submission_output_dir() -> str:
    """Return the submission output directory, warning if it falls under /tmp in non-dev."""
    default = "/var/lib/raf_intelligence/submissions"
    path = os.getenv("SUBMISSION_OUTPUT_DIR", default)
    if path.startswith("/tmp") and _APP_ENV != "development":
        import logging
        logging.getLogger(__name__).warning(
            "WARNING: SUBMISSION_OUTPUT_DIR is set to a path under /tmp (%s). "
            "Files under /tmp may be purged by the OS at any time and are not suitable "
            "for production use. Set SUBMISSION_OUTPUT_DIR to a persistent directory.",
            path,
        )
    return path


class Settings:
    # Environment
    app_env: str = _APP_ENV

    # Gemini
    google_api_key: str = os.getenv("GOOGLE_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")

    # LLM model names — per-pipeline overrides via environment variables.
    # All model-name literals that were previously scattered across services
    # are consolidated here so a single env change swaps every pipeline.
    llm_model_blind: str = os.getenv("LLM_MODEL_BLIND", "gemini-2.0-flash")
    """Fast, cheap model for blind (no-context) extraction (Pass 1)."""

    llm_model_contextual: str = os.getenv("LLM_MODEL_CONTEXTUAL", "gemini-2.5-pro")
    """High-quality model for contextual extraction / MEAT / suspect (Pass 2)."""

    llm_model_meat: str = os.getenv("LLM_MODEL_MEAT", "gemini-2.5-pro")
    """Model used by the MEAT evidence extractor (meat_extractor.py)."""

    llm_model_suspect: str = os.getenv("LLM_MODEL_SUSPECT", "gemini-2.0-flash")
    """Model used by the AI suspect pipeline (ai_pipeline/suspect_engine.py)."""

    @property
    def gemini_api_key(self) -> str:
        """Alias for google_api_key — used by readiness probe and health checks."""
        return self.google_api_key

    # OpenEMR database
    openemr_db_host: str = os.getenv("OPENEMR_DB_HOST") or "mysql"
    openemr_db_port: int = int(os.getenv("OPENEMR_DB_PORT") or "3306")
    openemr_db_user: str = _get_required_credential("OPENEMR_DB_USER")
    openemr_db_password: str = _get_required_credential("OPENEMR_DB_PASSWORD")
    openemr_db_name: str = os.getenv("OPENEMR_DB_NAME", "openemr")

    # RAF database
    raf_db_host: str = os.getenv("RAF_DB_HOST") or "127.0.0.1"
    raf_db_port: int = int(os.getenv("RAF_DB_PORT") or "3306")
    raf_db_user: str = _get_required_credential("RAF_DB_USER")
    raf_db_password: str = _get_required_credential("RAF_DB_PASSWORD")
    raf_db_name: str = os.getenv("RAF_DB_NAME", "raf_intelligence")

    # Application
    app_port: int = int(os.getenv("APP_PORT", "8500"))
    openemr_url: str = os.getenv("OPENEMR_URL") or "http://localhost:8080"

    # Redis (for Celery)
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # JWT / Auth
    jwt_secret: str = _get_jwt_secret()
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))  # was 30; reduced for HIPAA

    @property
    def jwt_refresh_secret(self) -> str:
        """Separate signing key for refresh tokens.

        Reads JWT_REFRESH_SECRET from the environment.  In production the
        application raises RuntimeError if it is not set — a derived fallback
        key is not acceptable for production use.  In development it falls back
        to jwt_secret + '_refresh' with a loud warning so local bring-up works
        without extra configuration.
        """
        env_val = os.getenv("JWT_REFRESH_SECRET", "")
        if not env_val:
            if _APP_ENV != "development":
                raise RuntimeError(
                    "FATAL: JWT_REFRESH_SECRET environment variable is not set. "
                    "The application cannot start in production without a stable "
                    "refresh token secret. Set JWT_REFRESH_SECRET in your environment "
                    "or .env file."
                )
            import logging
            logging.getLogger(__name__).warning(
                "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
                "WARNING: JWT_REFRESH_SECRET is not set – deriving from JWT_SECRET.\n"
                "This is ONLY acceptable in development. Set JWT_REFRESH_SECRET\n"
                "before deploying to any shared or production environment.\n"
                "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
            )
            return self.jwt_secret + "_refresh"
        return env_val

    refresh_token_expire_days: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
    max_failed_logins: int = int(os.getenv("MAX_FAILED_LOGINS", "5"))
    lockout_duration_minutes: int = int(os.getenv("LOCKOUT_DURATION_MINUTES", "15"))
    idle_timeout_minutes: int = int(os.getenv("IDLE_TIMEOUT_MINUTES", "15"))

    # Database TLS / SSL
    # Default to enabled in production so TLS is required unless explicitly
    # overridden via DB_SSL_ENABLED=false.  In non-production environments the
    # default stays disabled to reduce friction with local dev databases.
    db_ssl_enabled: bool = os.getenv(
        "DB_SSL_ENABLED",
        "true" if _APP_ENV == "production" else "false",
    ).lower() in ("1", "true", "yes")
    db_ssl_ca: str = os.getenv("DB_SSL_CA", "")

    # Submission output directory (used by submission_service for generated files)
    submission_output_dir: str = _get_submission_output_dir()

    # Error monitoring (Sentry)
    sentry_dsn: str = os.getenv("SENTRY_DSN", "")
    sentry_environment: str = os.getenv("SENTRY_ENV", "development")

    # Data retention
    data_retention_enabled: bool = os.getenv("DATA_RETENTION_ENABLED", "true").lower() not in ("0", "false", "no")
    retention_check_interval_hours: int = int(os.getenv("RETENTION_CHECK_INTERVAL_HOURS", "24"))

    # SMTP / Email notifications
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "noreply@raf-intelligence.com")
    smtp_tls: bool = os.getenv("SMTP_TLS", "true").lower() == "true"

    # Frontend URL (used to construct email links, e.g. password reset)
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:3000")

    # CMS per-member per-year revenue benchmark used for RAF opportunity calcs.
    # CMS PY2026 national per-capita rate. Update annually from CMS Rate Announcement.
    cms_revenue_per_raf_point: float = float(
        os.getenv("CMS_REVENUE_PER_RAF_POINT", "11800")
    )

    # RADV billing gate: when True (default), only LLM-validated MEAT evidence
    # (nlp_model != 'rule-based:meat_validator') can promote an HCC to
    # meat_status='complete' for billing purposes.  The regex validator remains
    # a pre-filter triage signal but cannot be authoritative for RADV defense.
    # Set REQUIRE_LLM_MEAT_FOR_BILLING=false to disable during a grace period
    # while the LLM pipeline is being rolled out.
    require_llm_meat_for_billing: bool = os.getenv(
        "REQUIRE_LLM_MEAT_FOR_BILLING", "true"
    ).lower() not in ("0", "false", "no")

    # Coefficient drift gate — when False (default), a mismatch between the
    # hccinfhir version pinned in coefficients_manifest.json and the version
    # actually installed at runtime raises CoefficientPinDriftError and halts
    # the score calculation.  Set to True only for emergency rollback / local
    # experimentation; never in production.
    allow_coefficient_drift: bool = os.getenv(
        "ALLOW_COEFFICIENT_DRIFT", "false"
    ).lower() in ("1", "true", "yes")

    # Independent CMS hierarchy cross-check on every score. When True (default
    # in production) the RAF hot path calls
    # app.services.raf.reconcile.validate_hierarchy() on the HCC set returned
    # by hccinfhir and raises HierarchyMismatchError if the library failed to
    # drop a child HCC whose parent is present.  Defaults to False in dev so
    # local experiments with custom hierarchies are not rejected.  Override
    # via RAF_INDEPENDENT_VALIDATION=true|false in any environment.
    raf_independent_validation: bool = os.getenv(
        "RAF_INDEPENDENT_VALIDATION",
        "true" if _APP_ENV == "production" else "false",
    ).lower() in ("1", "true", "yes")

    # Suspect-confidence calibration gate.  When True (prod default), the
    # suspect pipelines expose calibrated_confidence on each suspect in
    # addition to the raw score.  Turn OFF in dev / during A/B to keep
    # behaviour identical to the pre-calibration baseline.
    # See backend/app/services/raf/calibration/__init__.py for the full
    # caveats — v1 artifacts are fit on synthetic bootstrap labels.
    use_calibrated_confidence: bool = os.getenv(
        "USE_CALIBRATED_CONFIDENCE",
        "false" if _APP_ENV == "development" else "true",
    ).lower() in ("1", "true", "yes")

    # NLP context detector gate. When True (default), suspect generation
    # routes candidate mentions through app.services.nlp.context_detector to
    # suppress negated / hypothetical / historical / family-history findings.
    # Toggle OFF only for emergency rollback if context detection produces
    # regressions; disabling will increase false-positive suspect rate.
    use_context_detector: bool = os.getenv(
        "USE_CONTEXT_DETECTOR", "true"
    ).lower() in ("1", "true", "yes")

    # Clinical billing gate for MEAT evidence promotion. When True (default),
    # gate_billed_promotion blocks MEAT evidence from being promoted to
    # billable HCC status unless the supporting documentation passes
    # clinical validation rules. Toggle OFF only for emergency rollback;
    # disabling may allow unsupported HCCs to be billed.
    use_clinical_billing_gate: bool = os.getenv(
        "USE_CLINICAL_BILLING_GATE", "true"
    ).lower() in ("1", "true", "yes")

    # Gap #12 — lazily run the LLM MEAT evidence-snippet extractor at
    # raf-central load time when an HCC has no recorded evidence text.
    # Disabled by default because each call spends Gemini tokens; flip to
    # ``true`` in environments where extraction cost is acceptable.
    # The explicit POST /api/meat-evidence/extract endpoint is always
    # available regardless of this flag.
    lazy_meat_extraction: bool = os.getenv(
        "LAZY_MEAT_EXTRACTION", "false"
    ).lower() in ("1", "true", "yes")

    # Shared HMAC secret used by OpenEMR (or any embedding host) to mint a
    # short-lived JWT that /api/auth/embed/exchange will accept in lieu of
    # username/password. Required in production — RAF Central refuses embed
    # handshakes if this is unset in a non-dev environment.
    openemr_embed_secret: str = os.getenv("OPENEMR_EMBED_SECRET", "")
    # Tenant id assumed for embed sessions when the token omits it (single-tenant
    # demo deployments). Leave empty to require the token to carry tenant_id.
    openemr_embed_default_tenant_id: str = os.getenv(
        "OPENEMR_EMBED_DEFAULT_TENANT_ID", ""
    )
    # Access token lifetime issued by the embed exchange. Kept short because
    # the iframe has no silent refresh.
    embed_access_token_expire_minutes: int = int(
        os.getenv("EMBED_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    )

    # Dev admin seed gate. Both this flag AND app_env == "development" must be
    # true for _seed_dev_admin_user() to run. Default is False so production
    # instances never seed a dev admin even if APP_ENV is accidentally omitted.
    allow_dev_admin_seed: bool = os.getenv(
        "ALLOW_DEV_ADMIN_SEED", "false"
    ).lower() in ("1", "true", "yes")

    # OpenTelemetry OTLP collector endpoint.
    # When None, telemetry.py falls back to ConsoleSpanExporter in dev or
    # no-ops entirely so startup is unaffected by a missing collector.
    # Example: "http://otel-collector:4317"
    otel_exporter_otlp_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")

    # Auto-sync polling loop — runs every 30 s and syncs new OpenEMR patients
    # into raf_intelligence, then scores and analyzes them automatically.
    # Default: enabled in development/demo, disabled in production.
    auto_sync_enabled: bool = os.getenv(
        "AUTO_SYNC_ENABLED",
        "true" if _APP_ENV in ("development", "demo") else "false",
    ).lower() in ("1", "true", "yes")
    auto_sync_interval_seconds: int = int(os.getenv("AUTO_SYNC_INTERVAL_SECONDS", "30"))

    # ---------------------------------------------------------------------------
    # Storage backend
    # ---------------------------------------------------------------------------
    # STORAGE_BACKEND  — "local" (default) or "s3".
    #   local: files written to storage_local_root on the container filesystem.
    #   s3:    files written to S3/MinIO; requires boto3 and storage_s3_bucket.
    # These fields are intentionally not wired to any upload route yet —
    # see backend/app/services/storage.py for the abstraction.
    storage_backend: str = os.getenv("STORAGE_BACKEND", "local")
    storage_local_root: str = os.getenv("STORAGE_LOCAL_ROOT", "/app/uploads")
    storage_s3_bucket: str = os.getenv("STORAGE_S3_BUCKET", "")
    storage_s3_region: str = os.getenv("STORAGE_S3_REGION", "us-east-1")


# Known-weak / well-publicised dev JWT secrets that must never be used in
# production.  Kept module-level so validate_startup.py can re-use the set.
_WEAK_JWT_SECRETS: frozenset[str] = frozenset({
    "change-me",
    "dev-secret",
    "raf-dev-secret-key-2026-do-not-use-in-production",
    "",
})


def _validate_production(s: Settings) -> list[str]:
    """Enforce production-only secret / TLS hygiene.

    Returns a list of *non-fatal* warning strings so callers (validate_startup,
    main() banner) can surface them in their summaries.  Fatal misconfigs
    raise ``RuntimeError`` immediately — the application refuses to boot.
    """
    import logging as _logging

    _log = _logging.getLogger(__name__)
    warnings: list[str] = []

    # --- Fatal: JWT secret must be present and non-default --------------
    if not s.jwt_secret or s.jwt_secret in _WEAK_JWT_SECRETS or len(s.jwt_secret) < 32:
        raise RuntimeError(
            "FATAL: JWT_SECRET is empty, a known dev default, or shorter than "
            "32 characters. Generate a fresh one with "
            "`python -c 'import secrets; print(secrets.token_hex(32))'` and set "
            "JWT_SECRET before starting in production."
        )

    # --- Fatal: PHI encryption material -------------------------------
    # The encryption_service derives keys via HKDF; without these two the
    # service silently falls back to JWT_SECRET + a hard-coded salt, which is
    # explicitly rejected by encryption_service in prod.  Fail fast here so
    # operators see a single banner instead of a confusing per-request error.
    if not os.getenv("ENCRYPTION_SALT", ""):
        raise RuntimeError(
            "FATAL: ENCRYPTION_SALT is not set. Required for PHI encryption "
            "in production. Generate with "
            "`python -c 'import secrets; print(secrets.token_hex(16))'`."
        )
    if not os.getenv("DATA_ENCRYPTION_KEY", ""):
        raise RuntimeError(
            "FATAL: DATA_ENCRYPTION_KEY is not set. Required so PHI encryption "
            "is independent of JWT_SECRET. Generate with "
            "`python -c 'import secrets; print(secrets.token_hex(32))'`."
        )

    # --- Fatal: OpenEMR embed secret when embed is mounted ------------
    # Embed routes are mounted whenever the env-var is non-empty; if a deployer
    # has *configured* an embed default tenant but left the HMAC blank, that
    # is almost certainly a misconfiguration and we refuse to boot.
    if s.openemr_embed_default_tenant_id and not s.openemr_embed_secret:
        raise RuntimeError(
            "FATAL: OPENEMR_EMBED_DEFAULT_TENANT_ID is configured but "
            "OPENEMR_EMBED_SECRET is empty. Either unset the tenant id "
            "(disables embed) or set a 32+ byte HMAC secret."
        )

    # --- Warning: DB SSL disabled -------------------------------------
    # Per RAF deployment notes the prod DB is on an internal-only network with
    # no cert provisioned, so we warn (not fail) — see
    # docs/operations/prod_db_ssl.md for the rationale and remediation plan.
    if not s.db_ssl_enabled:
        msg = (
            "DB_SSL_ENABLED=false in production — DB traffic is in cleartext. "
            "Acceptable only on a fully isolated internal network. See "
            "docs/operations/prod_db_ssl.md for the migration plan."
        )
        warnings.append(msg)
        _log.warning("WARNING: %s", msg)

    # --- Warning: DB users named 'root' --------------------------------
    for label, value in (("RAF_DB_USER", s.raf_db_user),
                         ("OPENEMR_DB_USER", s.openemr_db_user)):
        if value == "root":
            msg = (
                f"{label}='root' in production — create a least-privilege "
                f"application user (DDL not required at runtime)."
            )
            warnings.append(msg)
            _log.warning("WARNING: %s", msg)

    # --- Warning: refresh-token secret equals access-token secret -----
    refresh = os.getenv("JWT_REFRESH_SECRET", "")
    if refresh and refresh == s.jwt_secret:
        msg = (
            "JWT_REFRESH_SECRET equals JWT_SECRET — refresh tokens should be "
            "signed with an independent key so a JWT key compromise does not "
            "automatically extend session lifetime."
        )
        warnings.append(msg)
        _log.warning("WARNING: %s", msg)

    return warnings


def _validate_settings(s: Settings) -> None:
    """Run post-instantiation checks and emit the mandatory APP_ENV banner.

    Called once immediately after ``settings`` is constructed.  Raises
    ``ValueError``/``RuntimeError`` for configurations that must never reach
    production.
    """
    import logging as _logging

    _log = _logging.getLogger(__name__)

    # Always emit which mode is active so operators can confirm at a glance.
    _log.warning("APP_ENV=%s", s.app_env)

    if s.app_env == "production":
        _validate_production(s)


settings = Settings()
_validate_settings(settings)
