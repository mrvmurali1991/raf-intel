"""
CMS SFTP Service — Automated file transmission to/from CMS via SFTP.

Handles RAPS/EDPS submission uploads and MAO-002/MAO-004 response downloads
using paramiko. SFTP credentials are stored encrypted at rest via the shared
encryption_service (AES-256-GCM, key derived from DATA_ENCRYPTION_KEY /
JWT_SECRET).

Required tables
---------------

-- CREATE TABLE IF NOT EXISTS cms_sftp_config (
--     id BIGINT PRIMARY KEY AUTO_INCREMENT,
--     tenant_id VARCHAR(50) NOT NULL UNIQUE,
--     host VARCHAR(255) NOT NULL,
--     port INT DEFAULT 22,
--     username VARCHAR(100),
--     auth_type VARCHAR(20) DEFAULT 'password', -- password, key
--     encrypted_password TEXT,
--     private_key_path VARCHAR(500),
--     remote_upload_dir VARCHAR(500) DEFAULT '/upload',
--     remote_response_dir VARCHAR(500) DEFAULT '/response',
--     is_active BOOLEAN DEFAULT TRUE,
--     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
--     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
-- );
--
-- CREATE TABLE IF NOT EXISTS cms_transmission_log (
--     id BIGINT PRIMARY KEY AUTO_INCREMENT,
--     tenant_id VARCHAR(50),
--     submission_id BIGINT,
--     direction VARCHAR(10) DEFAULT 'upload', -- upload, download
--     filename VARCHAR(255),
--     remote_path VARCHAR(500),
--     file_size BIGINT,
--     status VARCHAR(20) DEFAULT 'success', -- success, failed, partial
--     error_message TEXT,
--     transmitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
--     transmitted_by VARCHAR(100)
-- );
"""
from __future__ import annotations

import logging
import os
import time

from app.db import raf_cursor
from app.services.circuit_breaker import sftp_breaker
from app.services.encryption_service import decrypt, encrypt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional paramiko import — fail loudly only at call-time, not at import
# ---------------------------------------------------------------------------
try:
    import paramiko  # type: ignore[import]

    _PARAMIKO_AVAILABLE = True
except ImportError:
    _PARAMIKO_AVAILABLE = False
    logger.warning(
        "cms_sftp_service: 'paramiko' not installed. "
        "SFTP operations will raise RuntimeError. "
        "Install with: pip install paramiko"
    )

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_REQUIRED_CONFIG_FIELDS = {"host", "username", "auth_type"}
_VALID_AUTH_TYPES = {"password", "key"}
_RESPONSE_FILE_PATTERNS = ("MAO-002", "MAO-004", ".rsp", ".err", ".ack")


def _assert_paramiko() -> None:
    if not _PARAMIKO_AVAILABLE:
        raise RuntimeError(
            "paramiko is required for SFTP operations. "
            "Install with: pip install paramiko"
        )


def _build_transport(config: dict) -> paramiko.Transport:
    """Open a paramiko Transport and authenticate using the stored config."""
    _assert_paramiko()

    host: str = config["host"]
    port: int = int(config.get("port") or 22)
    username: str = config["username"]
    auth_type: str = config.get("auth_type", "password")
    known_hosts_path: str | None = config.get("known_hosts_path")

    transport = paramiko.Transport((host, port))
    transport.connect()

    # Host-key verification
    host_keys = paramiko.HostKeys()
    if known_hosts_path and os.path.isfile(known_hosts_path):
        host_keys.load(known_hosts_path)
        server_key = transport.get_remote_server_key()
        hostname_entry = host_keys.lookup(host)
        if hostname_entry is None or server_key not in hostname_entry.values():
            transport.close()
            raise paramiko.ssh_exception.SSHException(
                f"Host key verification failed for {host}. "
                "Update your known_hosts_path or pre-approve the server key."
            )
    else:
        logger.warning(
            "cms_sftp_service: known_hosts_path not configured for %s — "
            "host key verification is DISABLED. Configure known_hosts_path in production.",
            host,
        )

    if auth_type == "key":
        key_path = config.get("private_key_path")
        if not key_path or not os.path.isfile(key_path):
            transport.close()
            raise FileNotFoundError(
                f"Private key not found at path: {key_path!r}"
            )
        # Try RSA → Ed25519 → ECDSA in order
        pkey = None
        for key_cls in (
            paramiko.RSAKey,
            paramiko.Ed25519Key,
            paramiko.ECDSAKey,
            paramiko.DSSKey,
        ):
            try:
                pkey = key_cls.from_private_key_file(key_path)
                break
            except paramiko.ssh_exception.SSHException:
                continue
        if pkey is None:
            transport.close()
            raise paramiko.ssh_exception.SSHException(
                f"Could not load private key from {key_path!r}. "
                "Supported types: RSA, Ed25519, ECDSA, DSS."
            )
        transport.auth_publickey(username, pkey)
    else:
        # password auth
        encrypted_pw = config.get("encrypted_password") or ""
        password = decrypt(encrypted_pw) if encrypted_pw else ""
        transport.auth_password(username, password)

    return transport


def _log_transmission(
    *,
    tenant_id: str,
    submission_id: int | None,
    direction: str,
    filename: str,
    remote_path: str,
    file_size: int,
    status: str,
    error_message: str | None,
    transmitted_by: str = "system",
) -> int:
    """Insert a row into cms_transmission_log and return its new id."""
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO cms_transmission_log
                (tenant_id, submission_id, direction, filename, remote_path,
                 file_size, status, error_message, transmitted_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id,
                submission_id,
                direction,
                filename,
                remote_path,
                file_size,
                status,
                error_message,
                transmitted_by,
            ),
        )
        cur.execute("SELECT LAST_INSERT_ID() AS id")
        row = cur.fetchone()
        return int(row["id"])


# ---------------------------------------------------------------------------
# 1. SFTP Configuration
# ---------------------------------------------------------------------------


def get_sftp_config(tenant_id: str) -> dict | None:
    if not tenant_id:
        raise ValueError(
            "get_sftp_config: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """Return the SFTP configuration for *tenant_id*, or ``None`` if not set.

    The stored encrypted_password is decrypted in-memory before returning so
    callers receive the plain-text value.  The decrypted value is labelled
    ``password`` for ergonomics; the raw ``encrypted_password`` field is
    stripped from the result.
    """
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM cms_sftp_config WHERE tenant_id = %s AND is_active = TRUE",
            (tenant_id,),
        )
        row = cur.fetchone()

    if row is None:
        return None

    result = dict(row)
    encrypted_pw = result.pop("encrypted_password", None)
    result["password"] = ""
    if encrypted_pw:
        try:
            result["password"] = decrypt(encrypted_pw)
        except Exception:
            logger.warning(
                "cms_sftp_service: failed to decrypt password for tenant %s", tenant_id
            )

    return result


def save_sftp_config(tenant_id: str, config: dict) -> int:
    if not tenant_id:
        raise ValueError(
            "save_sftp_config: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """Persist SFTP connection settings for *tenant_id*.

    Performs an INSERT … ON DUPLICATE KEY UPDATE so the same call works for
    both create and update scenarios.

    Args:
        tenant_id: Logical tenant identifier (e.g. ``"default"``).
        config: Dict with keys: host, port, username, auth_type, password,
                private_key_path, remote_upload_dir, remote_response_dir,
                known_hosts_path.

    Returns:
        The primary-key ``id`` of the upserted row.

    Raises:
        ValueError: If required fields are missing or auth_type is invalid.
    """
    missing = _REQUIRED_CONFIG_FIELDS - set(config.keys())
    if missing:
        raise ValueError(f"Missing required SFTP config fields: {missing}")

    auth_type = config.get("auth_type", "password")
    if auth_type not in _VALID_AUTH_TYPES:
        raise ValueError(
            f"Invalid auth_type {auth_type!r}. Must be one of {_VALID_AUTH_TYPES}."
        )

    plain_password = config.get("password") or ""
    encrypted_password = encrypt(plain_password) if plain_password else None

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO cms_sftp_config
                (tenant_id, host, port, username, auth_type,
                 encrypted_password, private_key_path,
                 remote_upload_dir, remote_response_dir, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            ON DUPLICATE KEY UPDATE
                host               = VALUES(host),
                port               = VALUES(port),
                username           = VALUES(username),
                auth_type          = VALUES(auth_type),
                encrypted_password = VALUES(encrypted_password),
                private_key_path   = VALUES(private_key_path),
                remote_upload_dir  = VALUES(remote_upload_dir),
                remote_response_dir = VALUES(remote_response_dir),
                is_active          = TRUE
            """,
            (
                tenant_id,
                config["host"],
                int(config.get("port") or 22),
                config["username"],
                auth_type,
                encrypted_password,
                config.get("private_key_path"),
                config.get("remote_upload_dir", "/upload"),
                config.get("remote_response_dir", "/response"),
            ),
        )
        cur.execute("SELECT id FROM cms_sftp_config WHERE tenant_id = %s", (tenant_id,))
        row = cur.fetchone()
        return int(row["id"])


def test_sftp_connection(tenant_id: str) -> dict:
    if not tenant_id:
        raise ValueError(
            "test_sftp_connection: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """Verify SFTP connectivity for the stored configuration.

    Returns:
        ``{success: bool, message: str, latency_ms: int}``
    """
    _assert_paramiko()

    config = get_sftp_config(tenant_id)
    if config is None:
        return {
            "success": False,
            "message": f"No SFTP configuration found for tenant '{tenant_id}'.",
            "latency_ms": 0,
        }

    start = time.monotonic()
    transport: paramiko.Transport | None = None
    try:
        transport = _build_transport(config)
        sftp = paramiko.SFTPClient.from_transport(transport)

        # Probe the upload directory so we confirm both auth and filesystem access.
        upload_dir = config.get("remote_upload_dir", "/upload")
        sftp.listdir(upload_dir)
        sftp.close()

        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "success": True,
            "message": f"Connected to {config['host']}:{config.get('port', 22)} successfully ({latency_ms} ms).",
            "latency_ms": latency_ms,
        }
    except FileNotFoundError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        # Upload dir may not exist yet — connection itself succeeded.
        return {
            "success": True,
            "message": (
                f"Connected to {config['host']} but remote directory "
                f"'{config.get('remote_upload_dir')}' does not exist: {exc}"
            ),
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.warning("cms_sftp_service: connection test failed for %s: %s", tenant_id, exc)
        return {
            "success": False,
            "message": f"Connection failed: {exc}",
            "latency_ms": latency_ms,
        }
    finally:
        if transport is not None and transport.is_active():
            transport.close()


# ---------------------------------------------------------------------------
# 2. File Transmission
# ---------------------------------------------------------------------------


@sftp_breaker
def transmit_submission(submission_id: int, tenant_id: str) -> dict:
    if not tenant_id:
        raise ValueError(
            "transmit_submission: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """Upload a generated RAPS/EDPS submission file to CMS via SFTP.

    Reads the file path and content from ``submission_batches``, connects to
    the configured SFTP server, uploads the file, and records the transmission
    in ``cms_transmission_log``.  On success the batch status is updated to
    ``'transmitted'``.

    Args:
        submission_id: Primary key of the ``submission_batches`` row.
        tenant_id: Logical tenant identifier.

    Returns:
        ``{success, remote_path, bytes_transferred, transmission_id}``
    """
    _assert_paramiko()

    # ------------------------------------------------------------------
    # 1. Fetch submission batch record
    # ------------------------------------------------------------------
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM submission_batches WHERE id = %s AND tenant_id = %s",
            (submission_id, tenant_id),
        )
        batch = cur.fetchone()

    if batch is None:
        return {
            "success": False,
            "remote_path": None,
            "bytes_transferred": 0,
            "transmission_id": None,
            "error": f"Submission batch {submission_id} not found for tenant '{tenant_id}'.",
        }

    local_file_path: str = batch.get("file_path") or ""
    if not local_file_path or not os.path.isfile(local_file_path):
        transmission_id = _log_transmission(
            tenant_id=tenant_id,
            submission_id=submission_id,
            direction="upload",
            filename=os.path.basename(local_file_path) if local_file_path else "",
            remote_path="",
            file_size=0,
            status="failed",
            error_message=f"Local file not found: {local_file_path!r}",
        )
        return {
            "success": False,
            "remote_path": None,
            "bytes_transferred": 0,
            "transmission_id": transmission_id,
            "error": f"Local file not found: {local_file_path!r}",
        }

    filename = os.path.basename(local_file_path)
    local_size = os.path.getsize(local_file_path)

    # ------------------------------------------------------------------
    # 2. Load SFTP config
    # ------------------------------------------------------------------
    config = get_sftp_config(tenant_id)
    if config is None:
        transmission_id = _log_transmission(
            tenant_id=tenant_id,
            submission_id=submission_id,
            direction="upload",
            filename=filename,
            remote_path="",
            file_size=local_size,
            status="failed",
            error_message=f"No SFTP configuration for tenant '{tenant_id}'.",
        )
        return {
            "success": False,
            "remote_path": None,
            "bytes_transferred": 0,
            "transmission_id": transmission_id,
            "error": f"No SFTP configuration for tenant '{tenant_id}'.",
        }

    upload_dir: str = config.get("remote_upload_dir") or "/upload"
    remote_path = f"{upload_dir.rstrip('/')}/{filename}"

    # ------------------------------------------------------------------
    # 3. Upload
    # ------------------------------------------------------------------
    transport: paramiko.Transport | None = None
    try:
        transport = _build_transport(config)
        sftp = paramiko.SFTPClient.from_transport(transport)

        # Ensure remote directory exists
        try:
            sftp.stat(upload_dir)
        except FileNotFoundError:
            sftp.mkdir(upload_dir)

        bytes_transferred = 0

        def _track_progress(transferred: int, total: int) -> None:
            nonlocal bytes_transferred
            bytes_transferred = transferred

        sftp.put(local_file_path, remote_path, callback=_track_progress)
        sftp.close()

        # Final size from remote stat for accuracy
        with paramiko.SFTPClient.from_transport(transport) as sftp2:
            try:
                remote_stat = sftp2.stat(remote_path)
                bytes_transferred = remote_stat.st_size or bytes_transferred
            except Exception:
                pass  # Callback value is good enough

        transmission_id = _log_transmission(
            tenant_id=tenant_id,
            submission_id=submission_id,
            direction="upload",
            filename=filename,
            remote_path=remote_path,
            file_size=bytes_transferred,
            status="success",
            error_message=None,
        )

        # Update batch status to 'transmitted'
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE submission_batches SET status = 'transmitted' WHERE id = %s",
                (submission_id,),
            )

        logger.info(
            "cms_sftp_service: uploaded %s (%d bytes) to %s for tenant %s (tx_id=%d)",
            filename,
            bytes_transferred,
            remote_path,
            tenant_id,
            transmission_id,
        )

        return {
            "success": True,
            "remote_path": remote_path,
            "bytes_transferred": bytes_transferred,
            "transmission_id": transmission_id,
        }

    except Exception as exc:
        logger.error(
            "cms_sftp_service: upload failed for submission %d (tenant %s): %s",
            submission_id,
            tenant_id,
            exc,
            exc_info=True,
        )
        transmission_id = _log_transmission(
            tenant_id=tenant_id,
            submission_id=submission_id,
            direction="upload",
            filename=filename,
            remote_path=remote_path,
            file_size=0,
            status="failed",
            error_message=str(exc),
        )
        return {
            "success": False,
            "remote_path": remote_path,
            "bytes_transferred": 0,
            "transmission_id": transmission_id,
            "error": str(exc),
        }
    finally:
        if transport is not None and transport.is_active():
            transport.close()


@sftp_breaker
def check_for_responses(tenant_id: str) -> list[dict]:
    if not tenant_id:
        raise ValueError(
            "check_for_responses: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """Poll the SFTP response directory for new CMS response files.

    Downloads files matching known CMS response patterns (MAO-002, MAO-004,
    .rsp, .err, .ack) that have not already been recorded in
    ``cms_transmission_log``.  Downloaded files are saved to the local
    ``downloads/`` directory relative to the configured upload path.

    Args:
        tenant_id: Logical tenant identifier.

    Returns:
        List of dicts, one per downloaded file:
        ``{filename, remote_path, local_path, file_size, transmission_id}``
    """
    _assert_paramiko()

    config = get_sftp_config(tenant_id)
    if config is None:
        logger.warning(
            "cms_sftp_service: check_for_responses called but no SFTP config for tenant %s",
            tenant_id,
        )
        return []

    response_dir: str = config.get("remote_response_dir") or "/response"

    # ------------------------------------------------------------------
    # Build set of already-downloaded remote paths to avoid re-downloading
    # ------------------------------------------------------------------
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT remote_path FROM cms_transmission_log
            WHERE tenant_id = %s AND direction = 'download' AND status = 'success'
            """,
            (tenant_id,),
        )
        already_downloaded: set[str] = {row["remote_path"] for row in cur.fetchall()}

    # ------------------------------------------------------------------
    # Determine local download directory
    # ------------------------------------------------------------------
    local_base_dir = os.environ.get("CMS_RESPONSE_DOWNLOAD_DIR", "/tmp/cms_responses")
    tenant_download_dir = os.path.join(local_base_dir, tenant_id)
    os.makedirs(tenant_download_dir, exist_ok=True)

    downloaded: list[dict] = []
    transport: paramiko.Transport | None = None

    try:
        transport = _build_transport(config)
        sftp = paramiko.SFTPClient.from_transport(transport)

        try:
            remote_files = sftp.listdir_attr(response_dir)
        except FileNotFoundError:
            logger.info(
                "cms_sftp_service: response directory %s does not exist on %s",
                response_dir,
                config["host"],
            )
            sftp.close()
            return []

        for attr in remote_files:
            fname: str = attr.filename  # type: ignore[assignment]
            if not fname:
                continue

            # Filter to known CMS response file patterns
            is_response_file = any(pat in fname for pat in _RESPONSE_FILE_PATTERNS)
            if not is_response_file:
                continue

            remote_path = f"{response_dir.rstrip('/')}/{fname}"

            if remote_path in already_downloaded:
                logger.debug(
                    "cms_sftp_service: skipping already-downloaded file %s", remote_path
                )
                continue

            local_path = os.path.join(tenant_download_dir, fname)
            file_size = 0

            try:
                sftp.get(remote_path, local_path)
                file_size = os.path.getsize(local_path) if os.path.isfile(local_path) else 0

                transmission_id = _log_transmission(
                    tenant_id=tenant_id,
                    submission_id=None,
                    direction="download",
                    filename=fname,
                    remote_path=remote_path,
                    file_size=file_size,
                    status="success",
                    error_message=None,
                )

                downloaded.append(
                    {
                        "filename": fname,
                        "remote_path": remote_path,
                        "local_path": local_path,
                        "file_size": file_size,
                        "transmission_id": transmission_id,
                    }
                )
                logger.info(
                    "cms_sftp_service: downloaded response file %s (%d bytes) for tenant %s",
                    fname,
                    file_size,
                    tenant_id,
                )

            except Exception as exc:
                logger.error(
                    "cms_sftp_service: failed to download %s: %s", remote_path, exc
                )
                _log_transmission(
                    tenant_id=tenant_id,
                    submission_id=None,
                    direction="download",
                    filename=fname,
                    remote_path=remote_path,
                    file_size=0,
                    status="failed",
                    error_message=str(exc),
                )

        sftp.close()

    except Exception as exc:
        logger.error(
            "cms_sftp_service: check_for_responses failed for tenant %s: %s",
            tenant_id,
            exc,
            exc_info=True,
        )
    finally:
        if transport is not None and transport.is_active():
            transport.close()

    return downloaded


# ---------------------------------------------------------------------------
# 3. Transmission Logging
# ---------------------------------------------------------------------------


def get_transmission_history(tenant_id: str, limit: int = 50) -> list[dict]:
    if not tenant_id:
        raise ValueError(
            "get_transmission_history: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """Return recent transmission log entries for *tenant_id*.

    Args:
        tenant_id: Logical tenant identifier.
        limit: Maximum number of rows to return (default 50, capped at 500).

    Returns:
        List of transmission log dicts ordered by ``transmitted_at`` descending.
    """
    limit = max(1, min(limit, 500))

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                t.id,
                t.tenant_id,
                t.submission_id,
                t.direction,
                t.filename,
                t.remote_path,
                t.file_size,
                t.status,
                t.error_message,
                t.transmitted_at,
                t.transmitted_by,
                sb.file_type      AS batch_file_type,
                sb.payment_year   AS batch_payment_year,
                sb.sweep_type     AS batch_sweep_type
            FROM cms_transmission_log t
            LEFT JOIN submission_batches sb ON sb.id = t.submission_id
            WHERE t.tenant_id = %s
            ORDER BY t.transmitted_at DESC
            LIMIT %s
            """,
            (tenant_id, limit),
        )
        rows = cur.fetchall()

    return [dict(r) for r in rows]


def get_transmission_detail(transmission_id: int) -> dict | None:
    """Return full detail for a single transmission log entry.

    Args:
        transmission_id: Primary key of the ``cms_transmission_log`` row.

    Returns:
        Dict with all columns, or ``None`` if not found.
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                t.*,
                sb.file_type    AS batch_file_type,
                sb.payment_year AS batch_payment_year,
                sb.sweep_type   AS batch_sweep_type,
                sb.status       AS batch_status,
                sb.file_hash    AS batch_file_hash
            FROM cms_transmission_log t
            LEFT JOIN submission_batches sb ON sb.id = t.submission_id
            WHERE t.id = %s
            """,
            (transmission_id,),
        )
        row = cur.fetchone()

    return dict(row) if row else None
