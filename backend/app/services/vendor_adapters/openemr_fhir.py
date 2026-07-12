"""
OpenEMR FHIR R4 adapter.

Connects to any OpenEMR instance via its FHIR R4 API using OAuth2
client_credentials flow.  Fetches Patient and Condition resources
and normalises them into the standard shapes.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import date, datetime, timezone
from typing import Any

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ---------------------------------------------------------------------------
# Tenacity retry policy for FHIR HTTP calls
# ---------------------------------------------------------------------------
_FHIR_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def _is_retryable_fhir_error(exc: BaseException) -> bool:
    """Return True for transient network/server errors from httpx."""
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _FHIR_RETRYABLE_STATUS
    return False


_fhir_retry = retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=0.5, max=8),
    retry=retry_if_exception(_is_retryable_fhir_error),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


class OpenEMRFhirAdapter:
    """FHIR R4 adapter for OpenEMR."""

    vendor_name = "openemr"

    def __init__(self, connection: dict[str, Any]) -> None:
        self.connection = connection
        self.connection_id: int = connection.get("id", 0)
        self.base_url: str = (
            connection.get("base_url") or connection.get("fhir_base_url") or ""
        ).rstrip("/")
        self.token_url: str = (
            connection.get("token_url") or connection.get("fhir_token_url") or ""
        )
        self.client_id: str = (
            connection.get("client_id") or connection.get("fhir_client_id") or ""
        )
        self.client_secret: str = (
            connection.get("client_secret")
            or connection.get("fhir_client_secret")
            or ""
        )
        self.scope: str = connection.get("scope") or "openid api:fhir"
        # OpenEMR password grant credentials (stored in extra_config or api_username/api_password)
        extra = connection.get("extra_config") or {}
        if isinstance(extra, str):
            import json as _json

            try:
                extra = _json.loads(extra)
            except (ValueError, TypeError):
                extra = {}
        self.emr_username: str = (
            extra.get("emr_username")
            or connection.get("api_username")
            or connection.get("db_user")
            or ""
        )
        self.emr_password: str = (
            extra.get("emr_password")
            or connection.get("api_password")
            or connection.get("db_password")
            or ""
        )
        self._jwks_private_key_pem: str = extra.get("jwks_private_key_pem") or ""
        self._access_token: str | None = None

    # ------------------------------------------------------------------
    # OAuth2
    # ------------------------------------------------------------------

    def _get_access_token(self) -> str:
        """Return a valid OAuth2 access token.

        Priority:
        1. Cached in-memory token
        2. Stored token from DB (from Authorization Code flow) — refresh if expired
        3. Password grant fallback
        4. Client credentials fallback
        """
        if self._access_token:
            return self._access_token

        # --- Try stored token from Authorization Code flow ---
        stored_token = self.connection.get("access_token") or ""
        token_expires = self.connection.get("token_expires_at")
        refresh_token = self.connection.get("refresh_token_emr") or ""

        if stored_token:
            # Check if expired
            is_expired = False
            if token_expires:
                if isinstance(token_expires, str):
                    try:
                        token_expires = datetime.fromisoformat(
                            token_expires.replace("Z", "+00:00")
                        )
                    except ValueError:
                        is_expired = True
                if isinstance(token_expires, datetime):
                    if token_expires.tzinfo is None:
                        token_expires = token_expires.replace(tzinfo=timezone.utc)
                    if token_expires < datetime.now(timezone.utc):
                        is_expired = True

            if not is_expired:
                self._access_token = stored_token
                # Decode JWT to see actual scopes
                try:
                    import base64 as _b64

                    parts = stored_token.split(".")
                    if len(parts) >= 2:
                        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
                        import json as _json2

                        payload = _json2.loads(_b64.urlsafe_b64decode(padded))
                        logger.debug("OpenEMR FHIR: JWT payload decoded for connection %s", self.connection_id)
                except (ValueError, Exception) as _jwt_exc:  # noqa: BLE001
                    logger.debug(
                        "OpenEMR FHIR: JWT decode skipped for connection %s: %s",
                        self.connection_id, _jwt_exc,
                    )
                logger.info(
                    "OpenEMR FHIR: using stored access token for connection %s (len=%d)",
                    self.connection_id,
                    len(stored_token),
                )
                return self._access_token

            # Token expired — try refresh
            if refresh_token and self.token_url:
                refreshed = self._refresh_token(refresh_token)
                if refreshed:
                    return refreshed

        # --- Fallback: password grant ---
        if not self.token_url:
            raise ValueError(
                "No token_url configured and no stored token available. Run OAuth2 Authorize first."
            )

        with httpx.Client(timeout=_TIMEOUT, verify=True) as client:
            if self.emr_username and self.emr_password:
                resp = client.post(
                    self.token_url,
                    data={
                        "grant_type": "password",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "username": self.emr_username,
                        "password": self.emr_password,
                        "scope": self.scope,
                        "user_role": "users",
                    },
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "User-Agent": _BROWSER_UA,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._access_token = data.get("access_token")
                    if self._access_token:
                        logger.info(
                            "OpenEMR FHIR: got token via password grant for connection %s",
                            self.connection_id,
                        )
                        return self._access_token

            # Fallback: client_credentials grant with private_key_jwt
            cc_data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "scope": self.scope,
            }
            self._add_client_auth(cc_data)
            resp = client.post(
                self.token_url,
                data=cc_data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": _BROWSER_UA,
                },
            )
            if resp.status_code != 200:
                raise ValueError(
                    f"OAuth2 token request failed ({resp.status_code}): {resp.text[:300]}"
                )
            data = resp.json()
            self._access_token = data.get("access_token")
            if not self._access_token:
                raise ValueError(f"No access_token in OAuth2 response: {data}")
            logger.info(
                "OpenEMR FHIR: obtained access token for connection %s",
                self.connection_id,
            )
            return self._access_token

    def _build_client_assertion(self) -> str | None:
        """Build a signed JWT for private_key_jwt client auth (RFC 7523)."""
        if not self._jwks_private_key_pem or not self.token_url:
            return None
        try:
            import uuid

            import jwt as _pyjwt

            payload = {
                "iss": self.client_id,
                "sub": self.client_id,
                "aud": self.token_url,
                "jti": str(uuid.uuid4()),
                "iat": int(time.time()),
                "exp": int(time.time()) + 120,
            }
            return _pyjwt.encode(
                payload,
                self._jwks_private_key_pem,
                algorithm="RS384",
                headers={"typ": "JWT", "alg": "RS384"},
            )
        except Exception as exc:
            logger.warning("OpenEMR FHIR: failed to build client assertion: %s", exc)
            return None

    def _add_client_auth(self, data: dict) -> dict:
        """Add client authentication to token request data."""
        assertion = self._build_client_assertion()
        if assertion:
            data["client_assertion_type"] = (
                "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            )
            data["client_assertion"] = assertion
        elif self.client_secret:
            data["client_secret"] = self.client_secret
        else:
            data["client_id"] = self.client_id
        return data

    def _refresh_token(self, refresh_token: str) -> str | None:
        """Use the refresh token to get a new access token and persist it."""
        try:
            token_data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
            }
            self._add_client_auth(token_data)
            with httpx.Client(timeout=_TIMEOUT, verify=True) as client:
                resp = client.post(
                    self.token_url,
                    data=token_data,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "User-Agent": _BROWSER_UA,
                    },
                )
            if resp.status_code != 200:
                logger.warning(
                    "OpenEMR FHIR: refresh token failed (%s): %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return None

            data = resp.json()
            new_access = data.get("access_token", "")
            new_refresh = data.get("refresh_token", "") or refresh_token
            expires_in = data.get("expires_in", 3600)

            if not new_access:
                return None

            # Persist new tokens
            try:
                from app.services import emr_manager as emr_mgr

                emr_mgr.store_oauth2_tokens(
                    self.connection_id, new_access, new_refresh, expires_in
                )
            except Exception as exc:
                logger.warning("Failed to persist refreshed tokens: %s", exc)

            self._access_token = new_access
            logger.info(
                "OpenEMR FHIR: refreshed access token for connection %s",
                self.connection_id,
            )
            return new_access
        except Exception as exc:
            logger.warning("OpenEMR FHIR: refresh token error: %s", exc)
            return None

    def _auth_headers(self) -> dict[str, str]:
        token = self._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/fhir+json",
            "User-Agent": _BROWSER_UA,
        }

    # ------------------------------------------------------------------
    # FHIR requests
    # ------------------------------------------------------------------

    def _force_refresh(self) -> None:
        """Clear cached token and try to refresh via refresh_token."""
        self._access_token = None
        # Prevent _get_access_token from returning the same stored token
        self.connection["access_token"] = ""
        refresh_token = self.connection.get("refresh_token_emr") or ""
        if refresh_token and self.token_url:
            self._refresh_token(refresh_token)

    def _fhir_get(self, resource_path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}/{resource_path}"

        @_fhir_retry
        def _do_get(headers: dict) -> httpx.Response:
            with httpx.Client(timeout=_TIMEOUT, verify=True) as client:
                resp = client.get(url, headers=headers, params=params)
                if resp.status_code in _FHIR_RETRYABLE_STATUS:
                    resp.raise_for_status()
                return resp

        resp = _do_get(self._auth_headers())
        if resp.status_code == 401:
            logger.warning(
                "FHIR GET %s -> 401, forcing token refresh", resource_path
            )
            self._force_refresh()
            resp = _do_get(self._auth_headers())
        if resp.status_code != 200:
            logger.warning(
                "FHIR GET %s -> %s: %s",
                resource_path,
                resp.status_code,
                resp.text[:200],
            )
            return {}
        return resp.json()

    def _fhir_get_all(
        self, resource_type: str, params: dict | None = None, max_pages: int = 50
    ) -> list[dict]:
        """Fetch all pages of a FHIR Bundle."""
        all_entries: list[dict] = []
        url = f"{self.base_url}/{resource_type}"
        p = params or {}
        p.setdefault("_count", "100")

        @_fhir_retry
        def _do_page(page_url: str, page_params: dict | None, headers: dict) -> httpx.Response:
            with httpx.Client(timeout=_TIMEOUT, verify=True) as client:
                resp = client.get(page_url, headers=headers, params=page_params)
                if resp.status_code in _FHIR_RETRYABLE_STATUS:
                    resp.raise_for_status()
                return resp

        for page in range(max_pages):
            page_params = p if page == 0 else None
            resp = _do_page(url, page_params, self._auth_headers())
            if resp.status_code == 401:
                logger.warning(
                    "FHIR %s page %d -> 401 body: %s",
                    resource_type,
                    page,
                    resp.text[:300],
                )
                self._force_refresh()
                resp = _do_page(url, page_params, self._auth_headers())
            if resp.status_code != 200:
                logger.warning(
                    "FHIR %s page %d -> %s body: %s",
                    resource_type,
                    page,
                    resp.status_code,
                    resp.text[:300],
                )
                break
            bundle = resp.json()
            entries = bundle.get("entry", [])
            all_entries.extend(entries)
            # Follow next link
            next_url = None
            for link in bundle.get("link", []):
                if link.get("relation") == "next":
                    next_url = link.get("url")
                    break
            if not next_url or not entries:
                break
            url = next_url

        return all_entries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def test_connection(self) -> dict[str, Any]:
        """Test FHIR connectivity by fetching the CapabilityStatement (no auth needed)."""
        t0 = time.time()
        try:
            url = f"{self.base_url}/metadata"
            with httpx.Client(timeout=_TIMEOUT, verify=True) as client:
                resp = client.get(
                    url,
                    headers={
                        "Accept": "application/fhir+json",
                        "User-Agent": _BROWSER_UA,
                    },
                )
                latency = int((time.time() - t0) * 1000)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("resourceType") == "CapabilityStatement":
                        fhir_ver = data.get("fhirVersion", "?")
                        sw = data.get("software", {}).get("name", "FHIR Server")
                        return {
                            "success": True,
                            "message": f"Connected to {sw} FHIR R4 v{fhir_ver}",
                            "latency_ms": latency,
                        }
                return {
                    "success": False,
                    "message": f"HTTP {resp.status_code}: {resp.text[:200]}",
                    "latency_ms": latency,
                }
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            latency = int((time.time() - t0) * 1000)
            return {"success": False, "message": str(exc)[:300], "latency_ms": latency}

    def run_sync(self, sync_type: str = "full") -> dict[str, Any]:
        """Industry-level FHIR sync: patients, demographics, conditions, HCC mapping,
        encounters, and RAF score calculation.

        Sync phases:
        1. Patient resources  → emr_patient_matches + raf_patient_demographics
        2. Condition resources → raf_patient_hcc (with ICD-10→HCC crosswalk)
        3. Encounter resources → raf_encounter_analysis
        4. RAF score rollup   → raf_scores
        """
        errors: list[str] = []
        patients_synced = 0
        conditions_found = 0
        conditions_skipped = 0
        encounters_synced = 0
        raf_scores_calculated = 0

        # ------------------------------------------------------------------ #
        # Phase 1 — Patients                                                   #
        # ------------------------------------------------------------------ #
        try:
            patient_entries = self._fhir_get_all("Patient")
            logger.info(
                "OpenEMR FHIR: fetched %d Patient entries", len(patient_entries)
            )
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            errors.append(f"Patient fetch failed: {exc}")
            patient_entries = []

        for entry in patient_entries:
            resource = entry.get("resource", {})
            if resource.get("resourceType") != "Patient":
                continue
            try:
                patient = self._normalize_patient(resource)
                self._upsert_patient(patient)
                self._upsert_demographics(patient)
                patients_synced += 1
            except Exception as exc:
                logger.debug("swallowed exception", exc_info=True)
                errors.append(f"Patient {resource.get('id')}: {exc}")

        # ------------------------------------------------------------------ #
        # Phase 2 — Conditions (all statuses, not just active)                #
        # ------------------------------------------------------------------ #
        try:
            condition_entries = self._fhir_get_all("Condition")
            logger.info(
                "OpenEMR FHIR: fetched %d Condition entries", len(condition_entries)
            )
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            errors.append(f"Condition fetch failed: {exc}")
            condition_entries = []

        for entry in condition_entries:
            resource = entry.get("resource", {})
            if resource.get("resourceType") != "Condition":
                continue
            try:
                condition = self._normalize_condition(resource)
                if condition.get("icd10_code"):
                    self._upsert_condition_with_hcc(condition)
                    conditions_found += 1
                else:
                    logger.warning(
                        "Skipping condition without ICD-10 mapping: %s",
                        condition.get("display", "unknown"),
                    )
                    conditions_skipped += 1
            except Exception as exc:
                logger.debug("swallowed exception", exc_info=True)
                errors.append(f"Condition {resource.get('id')}: {exc}")

        # ------------------------------------------------------------------ #
        # Phase 3 — Encounters                                                 #
        # ------------------------------------------------------------------ #
        try:
            encounter_entries = self._fhir_get_all("Encounter")
            logger.info(
                "OpenEMR FHIR: fetched %d Encounter entries", len(encounter_entries)
            )
            for entry in encounter_entries:
                resource = entry.get("resource", {})
                if resource.get("resourceType") != "Encounter":
                    continue
                try:
                    self._upsert_encounter(resource)
                    encounters_synced += 1
                except Exception as exc:
                    logger.debug("swallowed exception", exc_info=True)
                    errors.append(f"Encounter {resource.get('id')}: {exc}")
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            errors.append(f"Encounter fetch failed: {exc}")

        # ------------------------------------------------------------------ #
        # Phase 3.5 — MedicationRequests                                       #
        # ------------------------------------------------------------------ #
        medications_synced = 0
        try:
            med_entries = self._fhir_get_all("MedicationRequest")
            logger.info(
                "OpenEMR FHIR: fetched %d MedicationRequest entries", len(med_entries)
            )
            for entry in med_entries:
                resource = entry.get("resource", {})
                if resource.get("resourceType") != "MedicationRequest":
                    continue
                try:
                    self._upsert_medication(resource)
                    medications_synced += 1
                except Exception as exc:
                    logger.debug("swallowed exception", exc_info=True)
                    errors.append(f"MedicationRequest {resource.get('id')}: {exc}")
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            errors.append(f"MedicationRequest fetch failed: {exc}")

        # ------------------------------------------------------------------ #
        # Phase 5 — DocumentReferences                                         #
        # ------------------------------------------------------------------ #
        documents_synced = 0
        try:
            doc_entries = self._fhir_get_all("DocumentReference")
            logger.info(
                "OpenEMR FHIR: fetched %d DocumentReference entries", len(doc_entries)
            )
            for entry in doc_entries:
                resource = entry.get("resource", {})
                if resource.get("resourceType") != "DocumentReference":
                    continue
                try:
                    self._upsert_document_reference(resource)
                    documents_synced += 1
                except Exception as exc:
                    logger.debug("swallowed exception", exc_info=True)
                    errors.append(f"DocumentReference {resource.get('id')}: {exc}")
                try:
                    self._upsert_clinical_note_from_ref(resource)
                except Exception as exc:
                    logger.debug("swallowed exception", exc_info=True)
                    errors.append(
                        f"DocumentReference note {resource.get('id')}: {exc}"
                    )
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            errors.append(f"DocumentReference fetch failed: {exc}")

        # ------------------------------------------------------------------ #
        # Phase 6 — Observations (lab results, vitals, social history)         #
        # ------------------------------------------------------------------ #
        observations_synced = 0
        try:
            obs_entries = self._fhir_get_all("Observation")
            logger.info(
                "OpenEMR FHIR: fetched %d Observation entries", len(obs_entries)
            )
            for entry in obs_entries:
                resource = entry.get("resource", {})
                if resource.get("resourceType") != "Observation":
                    continue
                try:
                    self._upsert_observation(resource)
                    observations_synced += 1
                except Exception as exc:
                    logger.debug("swallowed exception", exc_info=True)
                    errors.append(f"Observation {resource.get('id')}: {exc}")
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            errors.append(f"Observation fetch failed: {exc}")

        # ------------------------------------------------------------------ #
        # Phase 8 — Immunizations                                              #
        # ------------------------------------------------------------------ #
        immunizations_synced = 0
        try:
            imm_entries = self._fhir_get_all("Immunization")
            logger.info(
                "OpenEMR FHIR: fetched %d Immunization entries", len(imm_entries)
            )
            for entry in imm_entries:
                resource = entry.get("resource", {})
                if resource.get("resourceType") != "Immunization":
                    continue
                try:
                    self._upsert_immunization(resource)
                    immunizations_synced += 1
                except Exception as exc:
                    logger.debug("swallowed exception", exc_info=True)
                    errors.append(f"Immunization {resource.get('id')}: {exc}")
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            errors.append(f"Immunization fetch failed: {exc}")

        # ------------------------------------------------------------------ #
        # Phase 9 — AllergyIntolerance                                         #
        # ------------------------------------------------------------------ #
        allergies_synced = 0
        try:
            allergy_entries = self._fhir_get_all("AllergyIntolerance")
            logger.info(
                "OpenEMR FHIR: fetched %d AllergyIntolerance entries", len(allergy_entries)
            )
            for entry in allergy_entries:
                resource = entry.get("resource", {})
                if resource.get("resourceType") != "AllergyIntolerance":
                    continue
                try:
                    self._upsert_allergy(resource)
                    allergies_synced += 1
                except Exception as exc:
                    logger.debug("swallowed exception", exc_info=True)
                    errors.append(f"AllergyIntolerance {resource.get('id')}: {exc}")
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            errors.append(f"AllergyIntolerance fetch failed: {exc}")

        # ------------------------------------------------------------------ #
        # Phase 7 — DiagnosticReports (lab panels, radiology, pathology)      #
        # ------------------------------------------------------------------ #
        diagnostic_reports_synced = 0
        try:
            dr_entries = self._fhir_get_all("DiagnosticReport")
            logger.info(
                "OpenEMR FHIR: fetched %d DiagnosticReport entries", len(dr_entries)
            )
            for entry in dr_entries:
                resource = entry.get("resource", {})
                if resource.get("resourceType") != "DiagnosticReport":
                    continue
                try:
                    self._upsert_diagnostic_report(resource)
                    diagnostic_reports_synced += 1
                except Exception as exc:
                    logger.debug("swallowed exception", exc_info=True)
                    errors.append(f"DiagnosticReport {resource.get('id')}: {exc}")
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            errors.append(f"DiagnosticReport fetch failed: {exc}")

        # ------------------------------------------------------------------ #
        # Phase 4 — RAF score calculation                                      #
        # ------------------------------------------------------------------ #
        try:
            raf_scores_calculated = self._calculate_raf_scores()
        except Exception as exc:
            logger.debug("swallowed exception", exc_info=True)
            errors.append(f"RAF score calculation failed: {exc}")

        logger.info(
            "OpenEMR FHIR sync done: %d patients, %d conditions, %d conditions_skipped, "
            "%d encounters, %d medications, %d documents, %d observations, "
            "%d immunizations, %d allergies, %d diagnostic_reports, %d RAF scores, %d errors",
            patients_synced,
            conditions_found,
            conditions_skipped,
            encounters_synced,
            medications_synced,
            documents_synced,
            observations_synced,
            immunizations_synced,
            allergies_synced,
            diagnostic_reports_synced,
            raf_scores_calculated,
            len(errors),
        )
        return {
            "patients_synced": patients_synced,
            "conditions_found": conditions_found,
            "conditions_skipped": conditions_skipped,
            "encounters_synced": encounters_synced,
            "medications_synced": medications_synced,
            "documents_synced": documents_synced,
            "observations_synced": observations_synced,
            "immunizations_synced": immunizations_synced,
            "allergies_synced": allergies_synced,
            "diagnostic_reports_synced": diagnostic_reports_synced,
            "raf_scores_calculated": raf_scores_calculated,
            "errors": errors,
        }

    def fetch_document_references(self, patient_id: str) -> list[dict]:
        """Fetch DocumentReference notes for a patient from OpenEMR FHIR.

        Returns a list of {external_id, note_date, note_type, encounter_ref, text}
        dicts, drawn from inline base64 attachments or narrative text.div. Entries
        with remote attachment URLs are skipped (no extra HTTP calls). Text bodies
        shorter than 20 chars are dropped. Follows Bundle.link[relation=next].
        """
        import base64
        import re

        notes: list[dict] = []
        url = f"{self.base_url}/DocumentReference"
        p: dict | None = {"patient": patient_id, "_count": "100"}

        with httpx.Client(timeout=_TIMEOUT, verify=True) as client:
            for page in range(50):
                resp = client.get(
                    url, headers=self._auth_headers(), params=p if page == 0 else None
                )
                if resp.status_code == 401:
                    logger.warning(
                        "FHIR DocumentReference page %d -> 401 body: %s",
                        page,
                        resp.text[:300],
                    )
                    self._force_refresh()
                    resp = client.get(
                        url,
                        headers=self._auth_headers(),
                        params=p if page == 0 else None,
                    )
                if resp.status_code != 200:
                    logger.warning(
                        "FHIR DocumentReference page %d -> %s body: %s",
                        page,
                        resp.status_code,
                        resp.text[:300],
                    )
                    break
                bundle = resp.json()
                entries = bundle.get("entry", [])
                for entry in entries:
                    resource = entry.get("resource", {})
                    if resource.get("resourceType") != "DocumentReference":
                        continue
                    external_id = resource.get("id", "")
                    text_body = ""
                    content_list = resource.get("content", [])
                    attachment = (content_list[0].get("attachment", {})
                                  if content_list else {})
                    b64_data = attachment.get("data")
                    attach_url = attachment.get("url")
                    if b64_data:
                        try:
                            text_body = base64.b64decode(b64_data).decode(
                                "utf-8", errors="replace"
                            )
                        except Exception as exc:
                            logger.warning(
                                "DocumentReference %s: base64 decode failed: %s",
                                external_id,
                                exc,
                            )
                    elif attach_url:
                        logger.info(
                            "DocumentReference %s: attachment.url present, skipping remote fetch",
                            external_id,
                        )
                    if not text_body:
                        div = (resource.get("text") or {}).get("div", "")
                        if div:
                            text_body = re.sub(r"<[^>]+>", "", div)
                    text_body = (text_body or "").strip()
                    if len(text_body) < 20:
                        continue
                    raw_date = resource.get("date", "") or ""
                    note_date: str | None = None
                    if raw_date:
                        try:
                            note_date = datetime.fromisoformat(
                                raw_date.replace("Z", "+00:00")
                            ).date().isoformat()
                        except Exception:
                            logger.debug("swallowed exception", exc_info=True)
                            note_date = raw_date[:10] or None
                    type_obj = resource.get("type") or {}
                    coding = type_obj.get("coding") or []
                    note_type = (
                        (coding[0].get("display") if coding else None)
                        or type_obj.get("text")
                        or "clinical_note"
                    )
                    encounter_ref: str | None = None
                    context_enc = (resource.get("context") or {}).get("encounter") or []
                    if context_enc:
                        encounter_ref = context_enc[0].get("reference") or None
                    notes.append(
                        {
                            "external_id": external_id,
                            "note_date": note_date,
                            "note_type": note_type,
                            "encounter_ref": encounter_ref,
                            "text": text_body,
                        }
                    )
                next_url = None
                for link in bundle.get("link", []):
                    if link.get("relation") == "next":
                        next_url = link.get("url")
                        break
                if not next_url or not entries:
                    break
                url = next_url
                p = None

        return notes

    # ------------------------------------------------------------------
    # DocumentReference + Binary — FHIR document ingest pipeline
    # ------------------------------------------------------------------

    def list_document_references(
        self,
        patient_emr_pid: str,
        *,
        since: str | None = None,
        category: str | None = None,
        _count: int = 50,
    ) -> list[dict]:
        """GET /DocumentReference?subject=Patient/{pid}&_count=50&date=ge{since}.

        Returns raw FHIR Bundle entry list.  Each item is
        ``{"resource": {DocumentReference}, "fullUrl": ...}``.
        Honors the per-tenant circuit breaker via get_breaker().
        """
        from app.services.circuit_breaker import get_breaker, CircuitBreakerError

        cb_key = f"fhir_doc_ref:{self.connection_id}:{self.base_url}"
        breaker = get_breaker(cb_key, failure_threshold=3, recovery_timeout=90.0)

        params: dict[str, str] = {
            "subject": f"Patient/{patient_emr_pid}",
            "_count": str(_count),
        }
        if since:
            params["date"] = f"ge{since}"
        if category:
            params["category"] = category

        try:
            current_state = breaker.state
            from app.services.circuit_breaker import CircuitState
            if current_state == CircuitState.OPEN:
                import time as _time
                elapsed = _time.time() - breaker._last_failure_time
                retry_after = max(0.0, breaker.recovery_timeout - elapsed)
                raise CircuitBreakerError(cb_key, retry_after)

            entries = self._fhir_get_all(
                "DocumentReference", params=params, max_pages=20
            )
            breaker.record_success()
            return [e for e in entries if e.get("resource", {}).get("resourceType") == "DocumentReference"]
        except CircuitBreakerError:
            raise
        except Exception as exc:
            breaker.record_failure()
            logger.warning(
                "list_document_references patient=%s failed: %s",
                patient_emr_pid, exc,
            )
            raise

    def fetch_binary(self, binary_id_or_url: str) -> tuple[bytes, str]:
        """Fetch raw bytes for a FHIR Binary resource.

        Accepts either:
          - a bare reference like ``Binary/abc123``
          - a full URL like ``https://ehr.example.com/fhir/Binary/abc123``

        Sends ``Accept: application/pdf,application/fhir+json`` so both
        Epic/Cerner (raw bytes) and base64-wrapped servers work.
        Returns ``(bytes, mime_type)``.
        Honors the per-tenant circuit breaker.
        """
        import base64 as _b64
        from app.services.circuit_breaker import get_breaker, CircuitBreakerError, CircuitState

        cb_key = f"fhir_binary:{self.connection_id}:{self.base_url}"
        breaker = get_breaker(cb_key, failure_threshold=3, recovery_timeout=90.0)

        # Resolve to full URL
        if binary_id_or_url.startswith("http://") or binary_id_or_url.startswith("https://"):
            url = binary_id_or_url
        elif binary_id_or_url.startswith("Binary/"):
            url = f"{self.base_url}/{binary_id_or_url}"
        else:
            url = f"{self.base_url}/Binary/{binary_id_or_url}"

        current_state = breaker.state
        if current_state == CircuitState.OPEN:
            import time as _time
            elapsed = _time.time() - breaker._last_failure_time
            retry_after = max(0.0, breaker.recovery_timeout - elapsed)
            raise CircuitBreakerError(cb_key, retry_after)

        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Accept": "application/pdf,application/fhir+json;q=0.9,*/*;q=0.8",
            "User-Agent": _BROWSER_UA,
        }

        @_fhir_retry
        def _do_fetch() -> httpx.Response:
            with httpx.Client(timeout=_TIMEOUT, verify=True) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code in _FHIR_RETRYABLE_STATUS:
                    resp.raise_for_status()
                return resp

        try:
            resp = _do_fetch()
            if resp.status_code == 401:
                self._force_refresh()
                headers["Authorization"] = f"Bearer {self._get_access_token()}"
                resp = _do_fetch()
            if resp.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"Binary fetch {url} -> {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )

            content_type = resp.headers.get("content-type", "application/octet-stream")
            mime_type = content_type.split(";")[0].strip()

            # FHIR JSON-wrapped Binary (base64 encoded data field)
            if "fhir+json" in mime_type or mime_type == "application/json":
                body = resp.json()
                b64_data = body.get("data", "")
                raw_bytes = _b64.b64decode(b64_data) if b64_data else b""
                wrapped_mime = body.get("contentType", "application/octet-stream")
                breaker.record_success()
                return raw_bytes, wrapped_mime

            # Raw bytes (Epic, Cerner style)
            breaker.record_success()
            return resp.content, mime_type

        except CircuitBreakerError:
            raise
        except Exception as exc:
            breaker.record_failure()
            logger.warning("fetch_binary %s failed: %s", url, exc)
            raise

    # ------------------------------------------------------------------
    # Normalizers
    # ------------------------------------------------------------------

    def _normalize_patient(self, resource: dict) -> dict:
        names = resource.get("name", [{}])
        name = names[0] if names else {}
        first = " ".join(name.get("given", []))
        last = name.get("family", "")
        dob = resource.get("birthDate", "")
        sex = (resource.get("gender") or "unknown")[0].upper()
        if sex not in ("M", "F"):
            sex = "U"

        # Phone and Email: telecom array
        phone = ""
        email = ""
        for telecom in resource.get("telecom", []):
            if telecom.get("system") == "phone" and not phone:
                phone = telecom.get("value", "")
            elif telecom.get("system") == "email" and not email:
                email = telecom.get("value", "")

        # Language: communication[0].language.coding[0].display or .text
        language = ""
        communications = resource.get("communication", [])
        if communications:
            lang_obj = communications[0].get("language", {})
            codings = lang_obj.get("coding", [])
            if codings:
                language = codings[0].get("display", "")
            if not language:
                language = lang_obj.get("text", "")

        # Race and Ethnicity from US Core extensions
        race = ""
        ethnicity = ""
        for ext in resource.get("extension", []):
            url = ext.get("url", "")
            if url.endswith("us-core-race"):
                for sub in ext.get("extension", []):
                    if sub.get("url") == "text":
                        race = sub.get("valueString", "")
                        break
            elif url.endswith("us-core-ethnicity"):
                for sub in ext.get("extension", []):
                    if sub.get("url") == "text":
                        ethnicity = sub.get("valueString", "")
                        break

        # Address: first address entry
        address_street = ""
        address_city = ""
        address_state = ""
        address_zip = ""
        addresses = resource.get("address", [])
        if addresses:
            addr = addresses[0]
            lines = addr.get("line", [])
            address_street = lines[0] if lines else ""
            address_city = addr.get("city", "")
            address_state = addr.get("state", "")
            address_zip = addr.get("postalCode", "")

        # Deceased status: prefer deceasedDateTime, fall back to deceasedBoolean
        deceased_date = None
        deceased_dt = resource.get("deceasedDateTime")
        if deceased_dt:
            # deceasedDateTime is ISO-8601; take the date portion only
            deceased_date = str(deceased_dt)[:10]
        elif resource.get("deceasedBoolean") is True:
            # No exact date known — mark as deceased with a sentinel so the
            # column is non-NULL (downstream filters check for non-NULL).
            from datetime import date as _date
            deceased_date = str(_date.today())

        return {
            "external_id": resource.get("id", ""),
            "first_name": first,
            "last_name": last,
            "date_of_birth": dob,
            "sex": sex,
            "mrn": resource.get("id", ""),
            "phone": phone,
            "email": email,
            "language": language,
            "race": race,
            "ethnicity": ethnicity,
            "address": address_street,
            "city": address_city,
            "state": address_state,
            "zip": address_zip,
            "deceased_date": deceased_date,
        }

    # Common clinical text → ICD-10-CM mapping for conditions without coded entries
    _TEXT_TO_ICD10: dict[str, tuple[str, str]] = {
        "type 2 diabetes mellitus": (
            "E11.9",
            "Type 2 diabetes mellitus without complications",
        ),
        "type 2 diabetes": ("E11.9", "Type 2 diabetes mellitus without complications"),
        "type 1 diabetes mellitus": (
            "E10.9",
            "Type 1 diabetes mellitus without complications",
        ),
        "essential hypertension": ("I10", "Essential (primary) hypertension"),
        "hypertension": ("I10", "Essential (primary) hypertension"),
        "copd": (
            "J44.1",
            "Chronic obstructive pulmonary disease with acute exacerbation",
        ),
        "chronic obstructive pulmonary disease": (
            "J44.1",
            "COPD with acute exacerbation",
        ),
        "osteoarthritis of knee": ("M17.9", "Osteoarthritis of knee, unspecified"),
        "osteoarthritis": ("M19.90", "Unspecified osteoarthritis, unspecified site"),
        "hyperlipidemia": ("E78.5", "Hyperlipidemia, unspecified"),
        "major depressive disorder": (
            "F33.0",
            "Major depressive disorder, recurrent, mild",
        ),
        "depression": ("F33.0", "Major depressive disorder, recurrent, mild"),
        "hypothyroidism": ("E03.9", "Hypothyroidism, unspecified"),
        "anxiety disorder": ("F41.9", "Anxiety disorder, unspecified"),
        "generalized anxiety disorder": ("F41.1", "Generalized anxiety disorder"),
        "atrial fibrillation": ("I48.91", "Unspecified atrial fibrillation"),
        "heart failure": ("I50.9", "Heart failure, unspecified"),
        "congestive heart failure": ("I50.9", "Heart failure, unspecified"),
        "chronic kidney disease": ("N18.9", "Chronic kidney disease, unspecified"),
        "ckd stage 3": ("N18.3", "Chronic kidney disease, stage 3"),
        "ckd stage 4": ("N18.4", "Chronic kidney disease, stage 4"),
        "ckd stage 5": ("N18.5", "Chronic kidney disease, stage 5"),
        "asthma": ("J45.909", "Unspecified asthma, uncomplicated"),
        "obesity": ("E66.9", "Obesity, unspecified"),
        "morbid obesity": ("E66.01", "Morbid (severe) obesity due to excess calories"),
        "stroke": ("I63.9", "Cerebral infarction, unspecified"),
        "peripheral vascular disease": (
            "I73.9",
            "Peripheral vascular disease, unspecified",
        ),
        "rheumatoid arthritis": ("M06.9", "Rheumatoid arthritis, unspecified"),
        "diabetic neuropathy": (
            "E11.40",
            "Type 2 DM with diabetic neuropathy, unspecified",
        ),
        "diabetic retinopathy": (
            "E11.319",
            "Type 2 DM with unspecified diabetic retinopathy",
        ),
        "chronic pain": ("G89.29", "Other chronic pain"),
        "dementia": ("F03.90", "Unspecified dementia without behavioral disturbance"),
        "alzheimer": ("G30.9", "Alzheimer's disease, unspecified"),
        "parkinson": ("G20", "Parkinson's disease"),
        "seizure disorder": ("G40.909", "Epilepsy, unspecified, not intractable"),
        "epilepsy": ("G40.909", "Epilepsy, unspecified, not intractable"),
        "cirrhosis": ("K74.60", "Unspecified cirrhosis of liver"),
        "hepatitis c": ("B18.2", "Chronic viral hepatitis C"),
        "hiv": ("B20", "Human immunodeficiency virus [HIV] disease"),
        "lung cancer": (
            "C34.90",
            "Malignant neoplasm of unspecified part of bronchus or lung",
        ),
        "breast cancer": (
            "C50.919",
            "Malignant neoplasm of unspecified site of unspecified breast",
        ),
        "colon cancer": ("C18.9", "Malignant neoplasm of colon, unspecified"),
        "prostate cancer": ("C61", "Malignant neoplasm of prostate"),
        "schizophrenia": ("F20.9", "Schizophrenia, unspecified"),
        "bipolar disorder": ("F31.9", "Bipolar disorder, unspecified"),
    }

    def _text_to_icd10(self, text: str) -> tuple[str, str]:
        """Look up ICD-10 code from condition description text."""
        key = text.strip().lower()
        if key in self._TEXT_TO_ICD10:
            return self._TEXT_TO_ICD10[key]
        # Partial match
        for k, v in self._TEXT_TO_ICD10.items():
            if k in key or key in k:
                return v
        return ("", "")

    @staticmethod
    def _safe_onset_date(val: str) -> str | None:
        """Sanitize a FHIR date to YYYY-MM-DD or None.
        Handles invalid dates like '-0001-11-30' from OpenEMR."""
        if not val:
            return None
        s = str(val)[:10]
        if s.startswith("-") or s < "0001":
            return None
        # Validate it's a real date
        try:
            from datetime import datetime as _dt
            _dt.strptime(s, "%Y-%m-%d")
        except (ValueError, TypeError):
            return None
        return s

    def _normalize_condition(self, resource: dict) -> dict:
        # Extract ICD-10 code from coding
        icd_code = ""
        description = ""
        code_obj = resource.get("code", {})
        for coding in code_obj.get("coding", []):
            system = coding.get("system", "")
            if (
                "icd" in system.lower()
                or "icd10" in system.lower()
                or system == "http://hl7.org/fhir/sid/icd-10-cm"
            ):
                icd_code = coding.get("code", "")
                description = coding.get("display", "")
                break
        if not icd_code:
            # Try first coding
            codings = code_obj.get("coding", [])
            if codings:
                icd_code = codings[0].get("code", "")
                description = codings[0].get("display", "")
        # Fallback: map text description to ICD-10
        if not icd_code:
            text = code_obj.get("text", "")
            mapped_code, mapped_desc = self._text_to_icd10(text)
            if mapped_code:
                icd_code = mapped_code
                description = description or mapped_desc
                logger.info("Mapped condition text '%s' → ICD-10 %s", text, icd_code)

        if not description:
            description = code_obj.get("text", "")

        # Status
        clinical_status = resource.get("clinicalStatus", {})
        status_codings = (
            clinical_status.get("coding", [])
            if isinstance(clinical_status, dict)
            else []
        )
        status = status_codings[0].get("code", "active") if status_codings else "active"

        # Onset
        onset = resource.get("onsetDateTime", "")
        if not onset:
            onset_period = resource.get("onsetPeriod", {})
            onset = (
                onset_period.get("start", "") if isinstance(onset_period, dict) else ""
            )

        # Patient reference
        subject = resource.get("subject", {})
        patient_ref = (subject.get("reference") or "").replace("Patient/", "")

        return {
            "icd10_code": icd_code,
            "description": description,
            "status": status,
            "onset_date": self._safe_onset_date(onset),
            "patient_external_id": patient_ref,
        }

    # ------------------------------------------------------------------
    # DB upsert helpers
    # ------------------------------------------------------------------

    def _upsert_patient(self, patient: dict) -> None:
        from app.db import raf_cursor

        # Use the FHIR resource UUID as emr_pid so lookups against
        # fhir_conditions / fhir_encounters / fhir_medications (which key
        # on the UUID) work correctly.
        emr_pid = patient["external_id"] or ""
        tenant_id = self.connection.get("tenant_id", "1")
        dob = patient["date_of_birth"] or None
        fname = patient["first_name"]
        lname = patient["last_name"]
        deceased_date = patient.get("deceased_date") or None

        with raf_cursor() as cur:
            # Ensure deceased_date column exists (idempotent — silently ignores
            # "Duplicate column" errors so it is safe to run on every sync).
            try:
                cur.execute(
                    "ALTER TABLE patients ADD COLUMN deceased_date DATE DEFAULT NULL"
                )
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
                pass  # Column already exists — this is expected after first run
            # --- Check if a patient with the same name+DOB already exists
            #     (handles OpenEMR creating multiple FHIR resources for
            #     the same person with different UUIDs) ---
            existing_id = None
            cur.execute(
                """SELECT id FROM patients
                   WHERE tenant_id = %s
                     AND first_name = %s AND last_name = %s AND dob = %s
                     AND emr_connection_id = %s
                   LIMIT 1""",
                (tenant_id, fname, lname, dob, self.connection_id),
            )
            row = cur.fetchone()
            if row:
                existing_id = row["id"]

            if existing_id:
                # Update existing patient (matched by name+DOB)
                cur.execute(
                    """UPDATE patients SET
                           fname = %s, lname = %s,
                           gender = %s, emr_pid = %s,
                           phone = %s, email = %s,
                           preferred_language = IF(%s NOT IN ('', 'Unknown'), %s, preferred_language),
                           race = IF(%s NOT IN ('', 'Unknown'), %s, race),
                           ethnicity = IF(%s NOT IN ('', 'Unknown'), %s, ethnicity),
                           address = %s, city = %s, state = %s, zip = %s,
                           deceased_date = COALESCE(%s, deceased_date),
                           updated_at = NOW()
                       WHERE id = %s""",
                    (
                        fname, lname,
                        (patient["sex"] or "M")[0].upper(), emr_pid,
                        patient.get("phone") or None,
                        patient.get("email") or None,
                        patient.get("language") or "", patient.get("language") or "",
                        patient.get("race") or "", patient.get("race") or "",
                        patient.get("ethnicity") or "", patient.get("ethnicity") or "",
                        patient.get("address") or None,
                        patient.get("city") or None,
                        patient.get("state") or None,
                        patient.get("zip") or None,
                        deceased_date,
                        existing_id,
                    ),
                )
            else:
                # Insert new patient
                cur.execute(
                    """INSERT INTO patients
                           (tenant_id, first_name, last_name, fname, lname, dob, gender,
                            emr_pid, emr_connection_id, data_source, is_active,
                            phone, email, preferred_language, race, ethnicity,
                            address, city, state, zip,
                            deceased_date,
                            created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'fhir', 1,
                               %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s,
                               NOW(), NOW())
                       ON DUPLICATE KEY UPDATE
                           first_name = VALUES(first_name),
                           last_name  = VALUES(last_name),
                           fname      = VALUES(fname),
                           lname      = VALUES(lname),
                           dob        = VALUES(dob),
                           gender     = VALUES(gender),
                           phone      = VALUES(phone),
                           email      = VALUES(email),
                           preferred_language = IF(VALUES(preferred_language) NOT IN ('', 'Unknown'), VALUES(preferred_language), preferred_language),
                           race       = IF(VALUES(race) NOT IN ('', 'Unknown'), VALUES(race), race),
                           ethnicity  = IF(VALUES(ethnicity) NOT IN ('', 'Unknown'), VALUES(ethnicity), ethnicity),
                           address    = VALUES(address),
                           city       = VALUES(city),
                           state      = VALUES(state),
                           zip        = VALUES(zip),
                           deceased_date = COALESCE(VALUES(deceased_date), deceased_date),
                           updated_at = NOW()""",
                    (
                        tenant_id, fname, lname, fname, lname,
                        dob,
                        (patient["sex"] or "M")[0].upper(),
                        emr_pid,
                        self.connection_id,
                        patient.get("phone") or None,
                        patient.get("email") or None,
                        patient.get("language") or None,
                        patient.get("race") or None,
                        patient.get("ethnicity") or None,
                        patient.get("address") or None,
                        patient.get("city") or None,
                        patient.get("state") or None,
                        patient.get("zip") or None,
                        deceased_date,
                    ),
                )
            # Get the internal patient_id
            cur.execute(
                "SELECT id FROM patients WHERE emr_pid = %s AND emr_connection_id = %s AND tenant_id = %s LIMIT 1",
                (emr_pid, self.connection_id, tenant_id),
            )
            p_row = cur.fetchone()
            internal_pid = p_row["id"] if p_row else 0

            # --- emr_patient_matches ---
            cur.execute(
                """
                INSERT INTO emr_patient_matches (
                    patient_id, emr_connection_id, emr_patient_id,
                    connection_id, external_id, emr_pid, first_name, last_name,
                    date_of_birth, sex, mrn, match_status, tenant_id, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'auto', %s, NOW())
                ON DUPLICATE KEY UPDATE
                    patient_id = VALUES(patient_id),
                    first_name = VALUES(first_name),
                    last_name = VALUES(last_name),
                    date_of_birth = VALUES(date_of_birth),
                    sex = VALUES(sex),
                    external_id = VALUES(external_id),
                    mrn = VALUES(mrn)
                """,
                (
                    internal_pid,
                    self.connection_id,
                    patient["external_id"],
                    self.connection_id,
                    patient["external_id"],
                    emr_pid,
                    patient["first_name"],
                    patient["last_name"],
                    patient["date_of_birth"] or None,
                    patient["sex"],
                    patient["mrn"],
                    tenant_id,
                ),
            )

    # ------------------------------------------------------------------
    # Demographics upsert
    # ------------------------------------------------------------------

    @staticmethod
    def _cms_age_band(dob_str: str) -> str:
        """Return the CMS age band string for a given ISO date-of-birth string.

        Bands mirror CMS HCC model age groupings:
        0-34, 35-44, 45-54, 55-59, 60-64, 65-69, 70-74, 75-79, 80-84,
        85-89, 90-94, 95+
        """
        if not dob_str:
            return "0-34"
        try:
            dob = date.fromisoformat(dob_str[:10])
        except ValueError:
            return "0-34"
        today = date.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if age < 35:
            return "0-34"
        if age < 45:
            return "35-44"
        if age < 55:
            return "45-54"
        if age < 60:
            return "55-59"
        if age < 65:
            return "60-64"
        if age < 70:
            return "65-69"
        if age < 75:
            return "70-74"
        if age < 80:
            return "75-79"
        if age < 85:
            return "80-84"
        if age < 90:
            return "85-89"
        if age < 95:
            return "90-94"
        return "95+"

    def _upsert_demographics(self, patient: dict) -> None:
        """Create or update a raf_patient_demographics row for the patient and
        backfill emr_patient_matches.raf_patient_id."""
        from app.db import raf_cursor

        dob = patient.get("date_of_birth") or ""
        sex = patient.get("sex") or "M"
        if sex not in ("M", "F"):
            sex = "M"  # default; unknown maps to male for model purposes
        age_band = self._cms_age_band(dob)
        measurement_year = date.today().year

        with raf_cursor() as cur:
            # Resolve the emr_patient_matches row to see if we already have a
            # raf_patient_id linked.
            cur.execute(
                """
                SELECT id, raf_patient_id
                FROM emr_patient_matches
                WHERE connection_id = %s AND external_id = %s
                LIMIT 1
                """,
                (self.connection_id, patient["external_id"]),
            )
            row = cur.fetchone()
            if not row:
                # Patient not yet in matches — nothing to link
                return

            match_id: int = row["id"]
            existing_raf_id: int | None = row["raf_patient_id"]

            # Resolve real patients.id for this FHIR patient
            _emr_pid = patient["external_id"] or ""
            _tenant = self.connection.get("tenant_id", "1")
            cur.execute(
                "SELECT id FROM patients WHERE emr_pid = %s AND emr_connection_id = %s AND tenant_id = %s LIMIT 1",
                (_emr_pid, self.connection_id, _tenant),
            )
            _p_row = cur.fetchone()
            real_patient_id = _p_row["id"] if _p_row else match_id

            if existing_raf_id:
                # Update the existing demographics row
                cur.execute(
                    """
                    UPDATE raf_patient_demographics
                    SET patient_id = %s,
                        age_band = %s,
                        sex = %s,
                        measurement_year = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (real_patient_id, age_band, sex, measurement_year, existing_raf_id),
                )
                logger.debug(
                    "OpenEMR FHIR: updated demographics for raf_patient_id=%s",
                    existing_raf_id,
                )
            else:
                # Upsert demographics row using real patients.id
                cur.execute(
                    """
                    INSERT INTO raf_patient_demographics
                        (patient_id, measurement_year, age_band, sex,
                         dual_status, disabled, model_segment)
                    VALUES (%s, %s, %s, %s, 0, 0, 'CNA')
                    ON DUPLICATE KEY UPDATE
                        age_band = VALUES(age_band),
                        sex = VALUES(sex),
                        updated_at = NOW()
                    """,
                    (real_patient_id, measurement_year, age_band, sex),
                )
                # Get the id (whether inserted or existing)
                cur.execute(
                    "SELECT id FROM raf_patient_demographics WHERE patient_id = %s AND measurement_year = %s",
                    (real_patient_id, measurement_year),
                )
                demo_row = cur.fetchone()
                new_raf_id: int = demo_row["id"] if demo_row else cur.lastrowid
                # Link the match row back to the demographics id
                cur.execute(
                    "UPDATE emr_patient_matches SET raf_patient_id = %s WHERE id = %s",
                    (new_raf_id, match_id),
                )
                logger.debug(
                    "OpenEMR FHIR: created demographics id=%s for match id=%s",
                    new_raf_id,
                    match_id,
                )

    # ------------------------------------------------------------------
    # Patient resolution helper
    # ------------------------------------------------------------------

    def _resolve_or_create_raf_patient_id(self, external_id: str) -> int | None:
        """Return the real patients.id for a FHIR patient.

        The FK on raf_patient_hcc references raf_patient_demographics(patient_id,
        measurement_year), and patient_id there is patients.id.  So this method
        must return patients.id, NOT raf_patient_demographics.id.

        If the emr_patient_matches row exists but raf_patient_id is not yet
        linked, this method calls _upsert_demographics to create the missing row.

        Returns None only when the patient is not present in
        emr_patient_matches at all.
        """
        from app.db import raf_cursor

        # Use the FHIR UUID directly as emr_pid (matches _upsert_patient)
        emr_pid = external_id or ""
        tenant_id = self.connection.get("tenant_id", "1")

        with raf_cursor() as cur:
            # Look up the real patients.id — first by emr_pid, then fall
            # back to emr_patient_matches (handles multiple FHIR UUIDs
            # for the same person).
            cur.execute(
                "SELECT id FROM patients WHERE emr_pid = %s AND emr_connection_id = %s AND tenant_id = %s LIMIT 1",
                (emr_pid, self.connection_id, tenant_id),
            )
            p_row = cur.fetchone()
            if not p_row:
                # Check emr_patient_matches for an alternate UUID mapping
                cur.execute(
                    "SELECT patient_id FROM emr_patient_matches WHERE emr_pid = %s AND connection_id = %s LIMIT 1",
                    (emr_pid, self.connection_id),
                )
                m_row = cur.fetchone()
                if m_row and m_row["patient_id"]:
                    p_row = {"id": m_row["patient_id"]}
            if not p_row:
                return None
            real_pid = p_row["id"]

            # Ensure demographics exist for this patient
            cur.execute(
                "SELECT id FROM raf_patient_demographics WHERE patient_id = %s AND measurement_year = %s",
                (real_pid, date.today().year),
            )
            if not cur.fetchone():
                # Need to create demographics — get patient data from emr_patient_matches
                cur.execute(
                    "SELECT first_name, last_name, date_of_birth, sex FROM emr_patient_matches WHERE connection_id = %s AND external_id = %s LIMIT 1",
                    (self.connection_id, external_id),
                )
                row = cur.fetchone()
                if row:
                    patient_stub = {
                        "external_id": external_id,
                        "first_name": row.get("first_name") or "",
                        "last_name": row.get("last_name") or "",
                        "date_of_birth": (row.get("date_of_birth") or ""),
                        "sex": row.get("sex") or "M",
                    }
                    if hasattr(patient_stub["date_of_birth"], "isoformat"):
                        patient_stub["date_of_birth"] = patient_stub["date_of_birth"].isoformat()
                    self._upsert_demographics(patient_stub)

        return real_pid

    # ------------------------------------------------------------------
    # Condition → HCC upsert (with ICD-10 crosswalk)
    # ------------------------------------------------------------------

    def _upsert_condition_with_hcc(self, condition: dict) -> None:
        """Map an ICD-10 code to its HCC via hcc_icd10_crosswalk and write to
        raf_patient_hcc.  Silently skips if the ICD-10 code has no HCC mapping
        or the patient cannot be resolved.
        """
        import json as _json

        from app.db import raf_cursor

        icd10 = (condition.get("icd10_code") or "").strip().upper()
        if not icd10:
            return

        current_year = date.today().year
        measurement_year = current_year

        # Also determine the onset year so we can map HCCs to both years
        onset_year: int | None = None
        onset_dt = condition.get("onset_date")
        if onset_dt:
            try:
                if isinstance(onset_dt, date):
                    onset_year = onset_dt.year
                elif isinstance(onset_dt, str) and len(onset_dt) >= 4:
                    onset_year = int(onset_dt[:4])
            except (ValueError, TypeError):
                pass
        # Build list of years to create HCCs for
        hcc_years = [current_year]
        if onset_year and onset_year != current_year and onset_year >= current_year - 2:
            hcc_years.append(onset_year)

        # Resolve internal patient id — if demographics row is missing, create it
        # on the fly from the data already stored in emr_patient_matches so that
        # the FK constraint on raf_patient_hcc is satisfied.
        raf_patient_id: int | None = self._resolve_or_create_raf_patient_id(
            condition["patient_external_id"]
        )
        if raf_patient_id is None:
            logger.debug(
                "OpenEMR FHIR: skipping condition %s — patient %s not in emr_patient_matches",
                icd10,
                condition["patient_external_id"],
            )
            return

        with raf_cursor() as cur:

            # 2. ICD-10 → HCC crosswalk lookup (prefer current year, fall back
            #    to nearest available year)
            cur.execute(
                """
                SELECT hcc_code
                FROM hcc_icd10_crosswalk
                WHERE icd10_code = %s
                ORDER BY ABS(CAST(effective_year AS SIGNED) - %s)
                LIMIT 1
                """,
                (icd10, measurement_year),
            )
            xwalk = cur.fetchone()
            if not xwalk:
                logger.debug(
                    "OpenEMR FHIR: ICD-10 %s has no HCC mapping — storing as HCC 0",
                    icd10,
                )
                hcc_code = 0
                raf_coefficient = 0.0
            else:
                _raw_hcc = str(xwalk["hcc_code"]).replace("HCC", "").strip()
                hcc_code: int = int(_raw_hcc)

                # 3. HCC coefficient lookup
                cur.execute(
                    """
                    SELECT coefficient
                    FROM hcc_raf_coefficients
                    WHERE hcc_code = %s
                    ORDER BY ABS(CAST(model_year AS SIGNED) - %s)
                    LIMIT 1
                    """,
                    (hcc_code, measurement_year),
                )
                coeff_row = cur.fetchone()
                raf_coefficient = float(coeff_row["coefficient"]) if coeff_row else 0.0

            # 4. Determine MEAT status — cap at 'partial' when billing gate requires LLM validation
            from app.config import settings as _cfg
            if _cfg.require_llm_meat_for_billing:
                meat_status = "partial"
            else:
                meat_status = "complete" if condition.get("onset_date") else "partial"

            # 5. Upsert into raf_patient_hcc for each applicable year
            for _yr in hcc_years:
                # Ensure demographics row exists for this year
                cur.execute(
                    "SELECT id FROM raf_patient_demographics WHERE patient_id = %s AND measurement_year = %s",
                    (raf_patient_id, _yr),
                )
                if not cur.fetchone():
                    # Copy from current year or create minimal row
                    cur.execute(
                        "SELECT age_band, sex, orec, model_segment, tenant_id FROM raf_patient_demographics WHERE patient_id = %s ORDER BY ABS(CAST(measurement_year AS SIGNED) - %s) LIMIT 1",
                        (raf_patient_id, _yr),
                    )
                    demo_src = cur.fetchone()
                    if demo_src:
                        cur.execute(
                            "INSERT IGNORE INTO raf_patient_demographics (patient_id, measurement_year, age_band, sex, orec, model_segment, tenant_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                            (raf_patient_id, _yr, demo_src["age_band"], demo_src["sex"], demo_src["orec"], demo_src["model_segment"], demo_src.get("tenant_id")),
                        )

                cur.execute(
                    """
                    INSERT INTO raf_patient_hcc
                        (patient_id, measurement_year, hcc_code, icd10_codes,
                         source_encounter_ids, raf_coefficient, meat_status,
                         is_trumped, model_version, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 'V28', NOW())
                    ON DUPLICATE KEY UPDATE
                        icd10_codes = JSON_ARRAY_APPEND(
                            COALESCE(icd10_codes, JSON_ARRAY()), '$', %s
                        ),
                        raf_coefficient = VALUES(raf_coefficient),
                        meat_status = VALUES(meat_status),
                        model_version = VALUES(model_version),
                        updated_at = NOW()
                    """,
                    (
                        raf_patient_id,
                        _yr,
                        hcc_code,
                        _json.dumps([icd10]),
                        _json.dumps([]),
                        raf_coefficient,
                        meat_status,
                        icd10,
                    ),
                )

            # Also upsert into patient_conditions so the "Active Problems"
            # section on the patient detail page reflects FHIR conditions.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS patient_conditions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    patient_id INT NOT NULL,
                    icd10_code VARCHAR(20),
                    description VARCHAR(500),
                    hcc_code VARCHAR(20),
                    onset_date DATE,
                    status VARCHAR(50) DEFAULT 'active',
                    severity VARCHAR(50),
                    tenant_id VARCHAR(50),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_pid_icd (patient_id, icd10_code)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            tenant_id = self.connection.get("tenant_id", "1")
            onset_date = self._safe_onset_date(condition.get("onset_date"))
            status = condition.get("status") or "active"
            cur.execute(
                """
                INSERT INTO patient_conditions
                    (patient_id, icd10_code, description, onset_date, status, tenant_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    description = VALUES(description),
                    onset_date  = VALUES(onset_date),
                    status      = VALUES(status)
                """,
                (
                    raf_patient_id,
                    icd10,
                    condition.get("description") or "",
                    onset_date,
                    status,
                    tenant_id,
                ),
            )

    # ------------------------------------------------------------------
    # Encounter upsert
    # ------------------------------------------------------------------

    def _upsert_encounter(self, resource: dict) -> None:
        """Store a FHIR Encounter in raf_encounter_analysis if the referenced
        patient is already tracked in raf_patient_demographics.
        """
        from app.db import raf_cursor

        encounter_fhir_id: str = resource.get("id", "")
        subject = resource.get("subject", {})
        patient_external_id: str = (
            (subject.get("reference") or "").replace("Patient/", "").strip()
        )
        if not patient_external_id:
            return

        # Period
        period = resource.get("period", {})
        period_start: str | None = self._safe_onset_date(period.get("start", ""))
        status: str = resource.get("status", "unknown")

        # Service type / class
        enc_class = resource.get("class", {})
        if isinstance(enc_class, dict):
            enc_type_code: str = enc_class.get("code", "")
        else:
            enc_type_code = ""

        # Resolve patient — ensure demographics row exists before writing encounter
        raf_patient_id: int | None = self._resolve_or_create_raf_patient_id(
            patient_external_id
        )
        if raf_patient_id is None:
            return  # Patient not in emr_patient_matches; skip encounter

        with raf_cursor() as cur:
            # We store one row per encounter in raf_encounter_analysis.
            # encounter_id is a surrogate generated from the FHIR id hash so
            # we can upsert deterministically.
            # Surrogate ID — purely deterministic indexing key, NOT a security hash.
            # `usedforsecurity=False` quiets bandit B324 and is required by FIPS.
            encounter_surrogate: int = int(
                hashlib.md5(encounter_fhir_id.encode(), usedforsecurity=False).hexdigest()[:8],
                16,
            ) % (2**31)

            cur.execute(
                """
                INSERT INTO raf_encounter_analysis
                    (patient_id, encounter_id, overall_score,
                     hcc_opportunity_count, analyzed_at, created_at)
                VALUES (%s, %s, 0, 0, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    analyzed_at = VALUES(analyzed_at)
                """,
                (
                    raf_patient_id,
                    encounter_surrogate,
                    period_start or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            # Also write encounter metadata to fhir_encounters for UI display
            # (best-effort — FK may fail if fhir_connections row doesn't exist)
            try:
                cur.execute(
                    """
                    INSERT INTO fhir_encounters
                        (fhir_encounter_id, fhir_patient_id, connection_id, period_start,
                         status, encounter_class, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE
                        period_start = VALUES(period_start),
                        status = VALUES(status),
                        encounter_class = VALUES(encounter_class)
                    """,
                    (
                        encounter_fhir_id,
                        patient_external_id,
                        self.connection_id,
                        period_start,
                        status or "unknown",
                        enc_type_code,
                    ),
                )
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
                pass  # fhir_encounters is optional UI metadata

    # ------------------------------------------------------------------
    # Medication upsert
    # ------------------------------------------------------------------

    def _upsert_medication(self, resource: dict) -> None:
        """Store a FHIR MedicationRequest in patient_medications for UI display."""
        from app.db import raf_cursor

        med_fhir_id: str = resource.get("id", "")
        subject = resource.get("subject", {})
        patient_external_id: str = (
            (subject.get("reference") or "").replace("Patient/", "").strip()
        )
        if not patient_external_id:
            return

        # Resolve internal raf_patient_id via emr_patient_matches
        raf_patient_id: int | None = self._resolve_or_create_raf_patient_id(
            patient_external_id
        )
        if raf_patient_id is None:
            return

        # Medication name
        med_concept = resource.get("medicationCodeableConcept", {})
        drug_name = med_concept.get("text", "")
        if not drug_name:
            codings = med_concept.get("coding", [])
            if codings:
                drug_name = codings[0].get("display", "") or codings[0].get("code", "")

        if not drug_name:
            med_ref = resource.get("medicationReference", {})
            drug_name = med_ref.get("display", "") or med_fhir_id

        # Dosage
        dosage_instructions = resource.get("dosageInstruction", [{}])
        dosage_text = dosage_instructions[0].get("text", "") if dosage_instructions else ""

        # Status
        status = resource.get("status", "active")
        is_active = 1 if status in ("active", "on-hold") else 0

        # Authored date
        authored_on = resource.get("authoredOn", "")
        start_date = authored_on[:10] if authored_on else None

        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO patient_medications
                    (patient_id, medication_name, dosage, status, start_date, fhir_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    medication_name = VALUES(medication_name),
                    dosage = VALUES(dosage),
                    status = VALUES(status),
                    start_date = VALUES(start_date)
                """,
                (
                    raf_patient_id,
                    drug_name[:255],
                    dosage_text[:255],
                    "active" if is_active else "inactive",
                    start_date,
                    med_fhir_id[:100],
                ),
            )

    # ------------------------------------------------------------------
    # Immunization upsert
    # ------------------------------------------------------------------

    def _upsert_immunization(self, resource: dict) -> None:
        """Store a FHIR Immunization in patient_immunizations for HEDIS measures."""
        from app.db import raf_cursor

        fhir_id: str = resource.get("id", "")
        patient_ref: str = (
            (resource.get("patient", {}).get("reference") or "").replace("Patient/", "").strip()
        )
        if not patient_ref:
            return

        raf_patient_id: int | None = self._resolve_or_create_raf_patient_id(patient_ref)
        if raf_patient_id is None:
            return

        # Vaccine code and name from vaccineCode
        vaccine_concept = resource.get("vaccineCode", {})
        codings = vaccine_concept.get("coding", [])
        vaccine_code = ""
        vaccine_name = vaccine_concept.get("text", "")
        for c in codings:
            if c.get("system", "").endswith("cvx") or "cvx" in c.get("system", "").lower():
                vaccine_code = c.get("code", "")
                if not vaccine_name:
                    vaccine_name = c.get("display", "")
                break
        if not vaccine_code and codings:
            vaccine_code = codings[0].get("code", "")
        if not vaccine_name and codings:
            vaccine_name = codings[0].get("display", "")
        if not vaccine_name:
            vaccine_name = vaccine_code

        # Occurrence date
        occurrence = resource.get("occurrenceDateTime", "")
        administered_date = occurrence[:10] if occurrence else None

        status = resource.get("status", "completed")
        lot_number = resource.get("lotNumber")

        # Site and route display text (optional)
        site_obj = resource.get("site", {})
        site_codings = site_obj.get("coding", [])
        site = site_obj.get("text", "") or (site_codings[0].get("display", "") if site_codings else "")

        tenant_id: str = str(self.connection.get("tenant_id") or "")

        with raf_cursor() as cur:
            # Ensure table exists (compatible with existing structure used by patients router)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS patient_immunizations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    patient_id INT NOT NULL,
                    tenant_id VARCHAR(64),
                    fhir_immunization_id VARCHAR(255),
                    vaccine_code VARCHAR(20),
                    vaccine_name VARCHAR(255),
                    administered_date DATE,
                    status VARCHAR(20),
                    lot_number VARCHAR(50) NULL,
                    site VARCHAR(100) NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_tenant_fhir_imm (tenant_id, fhir_immunization_id)
                )
                """
            )
            cur.execute(
                """
                INSERT INTO patient_immunizations
                    (patient_id, tenant_id, fhir_immunization_id, vaccine_code,
                     vaccine_name, administered_date, status, lot_number, site)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    patient_id = VALUES(patient_id),
                    vaccine_code = VALUES(vaccine_code),
                    vaccine_name = VALUES(vaccine_name),
                    administered_date = VALUES(administered_date),
                    status = VALUES(status),
                    lot_number = VALUES(lot_number),
                    site = VALUES(site)
                """,
                (
                    raf_patient_id,
                    tenant_id,
                    fhir_id[:255],
                    vaccine_code[:20] if vaccine_code else None,
                    vaccine_name[:255] if vaccine_name else None,
                    administered_date,
                    status[:20],
                    lot_number[:50] if lot_number else None,
                    site[:100] if site else None,
                ),
            )

    # ------------------------------------------------------------------
    # AllergyIntolerance upsert
    # ------------------------------------------------------------------

    def _upsert_allergy(self, resource: dict) -> None:
        """Store a FHIR AllergyIntolerance in patient_allergies."""
        from app.db import raf_cursor

        fhir_id: str = resource.get("id", "")
        patient_ref: str = (
            (resource.get("patient", {}).get("reference") or "").replace("Patient/", "").strip()
        )
        if not patient_ref:
            return

        raf_patient_id: int | None = self._resolve_or_create_raf_patient_id(patient_ref)
        if raf_patient_id is None:
            return

        tenant_id: str = str(self.connection.get("tenant_id") or "")

        # Substance code and display
        code_obj = resource.get("code", {})
        codings = code_obj.get("coding", [])
        substance = code_obj.get("text", "")
        if not substance and codings:
            substance = codings[0].get("display", "") or codings[0].get("code", "")

        # Clinical status: code inside clinicalStatus.coding[0].code
        clinical_status_obj = resource.get("clinicalStatus", {})
        cs_codings = clinical_status_obj.get("coding", [])
        clinical_status = cs_codings[0].get("code", "") if cs_codings else ""

        # Verification status
        verification_obj = resource.get("verificationStatus", {})
        vs_codings = verification_obj.get("coding", [])
        verification_status = vs_codings[0].get("code", "") if vs_codings else ""

        allergy_type = resource.get("type", "")  # allergy | intolerance
        criticality = resource.get("criticality", "")

        # Category: first element of array
        categories = resource.get("category", [])
        category = categories[0] if categories else ""

        # Reaction manifestation display
        reactions = resource.get("reaction", [])
        reaction_display = ""
        if reactions:
            manifestations = reactions[0].get("manifestation", [])
            if manifestations:
                mf = manifestations[0]
                mf_codings = mf.get("coding", [])
                reaction_display = mf.get("text", "") or (
                    mf_codings[0].get("display", "") if mf_codings else ""
                )

        onset = resource.get("onsetDateTime", "")
        onset_date = onset[:10] if onset else None

        with raf_cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS patient_allergies (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    patient_id INT NOT NULL,
                    tenant_id VARCHAR(64),
                    fhir_allergy_id VARCHAR(255),
                    substance VARCHAR(255),
                    category VARCHAR(50),
                    criticality VARCHAR(20),
                    clinical_status VARCHAR(20),
                    verification_status VARCHAR(20),
                    allergy_type VARCHAR(20),
                    reaction_display VARCHAR(500) NULL,
                    onset_date DATE NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_tenant_fhir_allergy (tenant_id, fhir_allergy_id)
                )
                """
            )
            cur.execute(
                """
                INSERT INTO patient_allergies
                    (patient_id, tenant_id, fhir_allergy_id, substance, category,
                     criticality, clinical_status, verification_status, allergy_type,
                     reaction_display, onset_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    patient_id = VALUES(patient_id),
                    substance = VALUES(substance),
                    category = VALUES(category),
                    criticality = VALUES(criticality),
                    clinical_status = VALUES(clinical_status),
                    verification_status = VALUES(verification_status),
                    allergy_type = VALUES(allergy_type),
                    reaction_display = VALUES(reaction_display),
                    onset_date = VALUES(onset_date)
                """,
                (
                    raf_patient_id,
                    tenant_id,
                    fhir_id[:255],
                    substance[:255] if substance else None,
                    category[:50] if category else None,
                    criticality[:20] if criticality else None,
                    clinical_status[:20] if clinical_status else None,
                    verification_status[:20] if verification_status else None,
                    allergy_type[:20] if allergy_type else None,
                    reaction_display[:500] if reaction_display else None,
                    onset_date,
                ),
            )

    # ------------------------------------------------------------------
    # DocumentReference upsert
    # ------------------------------------------------------------------

    def _upsert_document_reference(self, resource: dict) -> None:
        """Download and store a FHIR DocumentReference attachment.

        Idempotent: uses ON DUPLICATE KEY UPDATE on (tenant_id, fhir_document_id).
        After saving, queues the document for AI analysis.
        """
        import re
        import uuid as _uuid
        from datetime import datetime as _dt
        from datetime import timezone as _tz
        from pathlib import Path

        from app.db import raf_cursor

        ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "text/plain"}

        tenant_id: str = str(self.connection.get("tenant_id", "1"))
        fhir_doc_id: str = resource.get("id", "")

        # ---- idempotent schema migrations --------------------------------
        with raf_cursor() as cur:
            for ddl in (
                "ALTER TABLE documents ADD COLUMN fhir_document_id VARCHAR(255) NULL",
                "ALTER TABLE documents ADD COLUMN source VARCHAR(64) NULL",
            ):
                try:
                    cur.execute(ddl)
                except Exception as col_exc:
                    if "Duplicate column name" not in str(col_exc):
                        raise

            try:
                cur.execute(
                    "ALTER TABLE documents ADD UNIQUE INDEX uq_tenant_fhir_doc "
                    "(tenant_id, fhir_document_id)"
                )
            except Exception as idx_exc:
                # Duplicate key name or already exists — safe to ignore
                if "Duplicate key name" not in str(idx_exc) and "already exists" not in str(idx_exc):
                    logger.debug("FHIR doc index note: %s", idx_exc)

        # ---- extract FHIR fields -----------------------------------------
        content_list = resource.get("content", [])
        if not content_list:
            logger.warning(
                "DocumentReference %s has no content entries — skipping", fhir_doc_id
            )
            return

        attachment = content_list[0].get("attachment", {})
        attach_url: str = attachment.get("url", "")
        content_type: str = attachment.get("contentType", "")
        attach_title: str = attachment.get("title", "") or fhir_doc_id

        if not attach_url:
            logger.warning(
                "DocumentReference %s has no attachment URL — skipping", fhir_doc_id
            )
            return

        if content_type not in ALLOWED_MIME:
            logger.info(
                "DocumentReference %s contentType '%s' not in allowed set — skipping",
                fhir_doc_id,
                content_type,
            )
            return

        # ---- resolve patient ---------------------------------------------
        subject_ref: str = (resource.get("subject") or {}).get("reference", "")
        external_patient_id = subject_ref.split("/")[-1] if subject_ref else ""
        try:
            raf_patient_id: int | None = self._resolve_or_create_raf_patient_id(
                external_patient_id
            )
        except Exception as exc:
            logger.warning(
                "DocumentReference %s: could not resolve patient '%s': %s",
                fhir_doc_id,
                external_patient_id,
                exc,
            )
            raf_patient_id = None

        # ---- download content -------------------------------------------
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.get(attach_url, headers=self._auth_headers())
                resp.raise_for_status()
                file_bytes: bytes = resp.content
        except Exception as exc:
            logger.warning(
                "DocumentReference %s: failed to download attachment from %s: %s",
                fhir_doc_id,
                attach_url,
                exc,
            )
            return

        # ---- save to disk -----------------------------------------------
        sha256_hex = hashlib.sha256(file_bytes).hexdigest()
        safe_tenant = re.sub(r"[^a-zA-Z0-9_-]", "_", tenant_id)
        month_dir = (
            Path(__file__).resolve().parents[3]
            / "uploads"
            / "documents"
            / safe_tenant
            / _dt.now(_tz.utc).strftime("%Y-%m")
        )
        month_dir.mkdir(parents=True, exist_ok=True)

        ext_map = {
            "application/pdf": ".pdf",
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "text/plain": ".txt",
        }
        ext = ext_map.get(content_type, "")
        safe_title = re.sub(r"[^a-zA-Z0-9._-]", "_", attach_title)[:100]
        filename = f"fhir_{fhir_doc_id}_{safe_title}{ext}"
        file_path = month_dir / filename

        file_path.write_bytes(file_bytes)
        relative_path = str(file_path.relative_to(Path(__file__).resolve().parents[3]))

        # ---- insert into documents table --------------------------------
        document_id = str(_uuid.uuid4())
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents
                    (id, tenant_id, patient_id, original_filename, file_path,
                     mime_type, file_size, sha256, status, source, fhir_document_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'uploaded', 'fhir_sync', %s)
                ON DUPLICATE KEY UPDATE
                    file_path           = VALUES(file_path),
                    sha256              = VALUES(sha256),
                    file_size           = VALUES(file_size),
                    source              = VALUES(source)
                """,
                (
                    document_id,
                    tenant_id,
                    raf_patient_id,
                    filename,
                    relative_path,
                    content_type,
                    len(file_bytes),
                    sha256_hex,
                    fhir_doc_id,
                ),
            )
            # Retrieve the actual id in case the row was a duplicate update
            cur.execute(
                "SELECT id FROM documents WHERE tenant_id = %s AND fhir_document_id = %s LIMIT 1",
                (tenant_id, fhir_doc_id),
            )
            row = cur.fetchone()
            saved_doc_id: str = row["id"] if row else document_id

        logger.info(
            "DocumentReference %s saved as document %s (%d bytes)",
            fhir_doc_id,
            saved_doc_id,
            len(file_bytes),
        )

        # ---- trigger analysis (lazy import to avoid circular imports) ----
        try:
            from app.services.document_service import analyze_document

            analyze_document(saved_doc_id, tenant_id)
        except Exception as exc:
            logger.warning(
                "DocumentReference %s: analysis trigger failed: %s", fhir_doc_id, exc
            )


    def _upsert_clinical_note_from_ref(self, resource: dict) -> None:
        """Extract inline clinical text from a FHIR DocumentReference and upsert
        it into ``clinical_notes`` for MEAT extraction. Complements
        ``_upsert_document_reference`` (which stores URL-backed binary attachments).
        """
        import base64
        import re

        from app.db import raf_cursor

        fhir_doc_id: str = resource.get("id", "")
        tenant_id: str = str(self.connection.get("tenant_id", "1"))

        # ---- extract inline text ------------------------------------------
        text_body = ""
        content_list = resource.get("content", [])
        attachment = content_list[0].get("attachment", {}) if content_list else {}
        b64_data = attachment.get("data")
        if b64_data:
            try:
                text_body = base64.b64decode(b64_data).decode(
                    "utf-8", errors="replace"
                )
            except Exception as exc:
                logger.warning(
                    "DocumentReference %s: base64 decode failed: %s",
                    fhir_doc_id,
                    exc,
                )
        if not text_body:
            div = (resource.get("text") or {}).get("div", "")
            if div:
                text_body = re.sub(r"<[^>]+>", "", div)
        text_body = (text_body or "").strip()
        if len(text_body) < 20:
            return  # nothing extractable — URL-only attachment, handled elsewhere

        # ---- resolve patient ----------------------------------------------
        subject_ref: str = (resource.get("subject") or {}).get("reference", "")
        external_patient_id = subject_ref.split("/")[-1] if subject_ref else ""
        if not external_patient_id:
            return
        raf_patient_id: int | None = self._resolve_or_create_raf_patient_id(
            external_patient_id
        )
        if raf_patient_id is None:
            return

        # ---- note_date, note_type -----------------------------------------
        raw_date = resource.get("date", "") or ""
        note_date: str | None = None
        if raw_date:
            try:
                note_date = datetime.fromisoformat(
                    raw_date.replace("Z", "+00:00")
                ).date().isoformat()
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
                note_date = raw_date[:10] or None
        type_obj = resource.get("type") or {}
        coding = type_obj.get("coding") or []
        note_type = (
            (coding[0].get("display") if coding else None)
            or type_obj.get("text")
            or "clinical_note"
        )

        # ---- upsert into clinical_notes -----------------------------------
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO clinical_notes
                    (tenant_id, patient_id, source_system, external_id,
                     note_date, note_type, text)
                VALUES (%s, %s, 'openemr_fhir', %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    patient_id = VALUES(patient_id),
                    note_date  = VALUES(note_date),
                    note_type  = VALUES(note_type),
                    text       = VALUES(text)
                """,
                (
                    tenant_id,
                    raf_patient_id,
                    fhir_doc_id,
                    note_date,
                    note_type,
                    text_body,
                ),
            )


    def _upsert_observation(self, resource: dict) -> None:
        """Store a FHIR Observation (lab result, vital, social history) in
        patient_observations for UI display and RAF enrichment."""
        from app.db import raf_cursor

        # --- Ensure table exists once per sync run ---
        if not hasattr(self, "_obs_table_ensured"):
            with raf_cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS patient_observations (
                        id                  INT AUTO_INCREMENT PRIMARY KEY,
                        patient_id          INT NOT NULL,
                        tenant_id           VARCHAR(64),
                        fhir_observation_id VARCHAR(255),
                        category            VARCHAR(64),
                        loinc_code          VARCHAR(20),
                        display_name        VARCHAR(255),
                        value_numeric       DECIMAL(12,4) NULL,
                        value_string        TEXT NULL,
                        unit                VARCHAR(50),
                        interpretation      VARCHAR(50),
                        effective_date      DATE,
                        status              VARCHAR(20),
                        created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uq_tenant_obs (tenant_id, fhir_observation_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            self._obs_table_ensured = True  # type: ignore[attr-defined]

        obs_fhir_id: str = resource.get("id", "")
        if not obs_fhir_id:
            return

        # --- Resolve patient ---
        subject = resource.get("subject", {})
        patient_external_id: str = (
            (subject.get("reference") or "").replace("Patient/", "").strip()
        )
        if not patient_external_id:
            return

        raf_patient_id: int | None = self._resolve_or_create_raf_patient_id(
            patient_external_id
        )
        if raf_patient_id is None:
            return

        # --- Category (laboratory, vital-signs, social-history, …) ---
        category_str = ""
        for cat in resource.get("category", []):
            codings = cat.get("coding", [])
            if codings:
                category_str = codings[0].get("code", "") or cat.get("text", "")
                break
        if not category_str and resource.get("category"):
            category_str = resource["category"][0].get("text", "")

        # --- LOINC code + display name ---
        code_obj = resource.get("code", {})
        loinc_code = ""
        display_name = code_obj.get("text", "")
        for coding in code_obj.get("coding", []):
            system = coding.get("system", "")
            if "loinc" in system.lower():
                loinc_code = coding.get("code", "")
                if not display_name:
                    display_name = coding.get("display", "")
                break
        # Fallback: take first coding regardless of system
        if not loinc_code and code_obj.get("coding"):
            first = code_obj["coding"][0]
            loinc_code = first.get("code", "")
            if not display_name:
                display_name = first.get("display", "")

        # --- Value extraction ---
        value_numeric: float | None = None
        value_string: str | None = None
        unit = ""

        if "valueQuantity" in resource:
            vq = resource["valueQuantity"]
            raw_val = vq.get("value")
            if raw_val is not None:
                try:
                    value_numeric = float(raw_val)
                except (TypeError, ValueError):
                    value_string = str(raw_val)
            unit = vq.get("unit", "") or vq.get("code", "")
        elif "valueString" in resource:
            value_string = str(resource["valueString"])
        elif "valueCodeableConcept" in resource:
            vcc = resource["valueCodeableConcept"]
            value_string = vcc.get("text", "")
            if not value_string:
                codings = vcc.get("coding", [])
                if codings:
                    value_string = (
                        codings[0].get("display", "") or codings[0].get("code", "")
                    )
        elif "valueBoolean" in resource:
            value_string = str(resource["valueBoolean"])
        elif "valueInteger" in resource:
            try:
                value_numeric = float(resource["valueInteger"])
            except (TypeError, ValueError):
                value_string = str(resource["valueInteger"])

        # --- Interpretation ---
        interpretation_str = ""
        _interp_map = {
            "N": "normal",
            "H": "high",
            "L": "low",
            "A": "abnormal",
            "AA": "critical",
            "HH": "critical",
            "LL": "critical",
            "POS": "positive",
            "NEG": "negative",
        }
        for interp in resource.get("interpretation", []):
            codings = interp.get("coding", [])
            if codings:
                code = codings[0].get("code", "").upper()
                interpretation_str = _interp_map.get(code, code.lower())
                break

        # --- Effective date ---
        effective_raw = resource.get("effectiveDateTime", "") or resource.get(
            "effectivePeriod", {}
        ).get("start", "")
        effective_date = effective_raw[:10] if effective_raw else None

        # --- Status ---
        status = resource.get("status", "")

        tenant_id = str(self.connection.get("tenant_id") or "")

        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO patient_observations
                    (patient_id, tenant_id, fhir_observation_id, category,
                     loinc_code, display_name, value_numeric, value_string,
                     unit, interpretation, effective_date, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    category        = VALUES(category),
                    loinc_code      = VALUES(loinc_code),
                    display_name    = VALUES(display_name),
                    value_numeric   = VALUES(value_numeric),
                    value_string    = VALUES(value_string),
                    unit            = VALUES(unit),
                    interpretation  = VALUES(interpretation),
                    effective_date  = VALUES(effective_date),
                    status          = VALUES(status)
                """,
                (
                    raf_patient_id,
                    tenant_id[:64] if tenant_id else None,
                    obs_fhir_id[:255],
                    category_str[:64] if category_str else None,
                    loinc_code[:20] if loinc_code else None,
                    display_name[:255] if display_name else None,
                    value_numeric,
                    value_string,
                    unit[:50] if unit else None,
                    interpretation_str[:50] if interpretation_str else None,
                    effective_date,
                    status[:20] if status else None,
                ),
            )

    # ------------------------------------------------------------------
    # DiagnosticReport upsert
    # ------------------------------------------------------------------

    def _upsert_diagnostic_report(self, resource: dict) -> None:
        """Store a FHIR DiagnosticReport in patient_diagnostic_reports.

        Captures lab panels (CBC, BMP, etc.), radiology, and pathology reports.
        The ``conclusion`` field contains clinician narrative that can be mined
        for HCC suspects in a later NLP pass.
        """
        from app.db import raf_cursor

        fhir_report_id: str = resource.get("id", "")
        if not fhir_report_id:
            return

        # Patient reference
        subject = resource.get("subject", {})
        patient_external_id: str = (
            (subject.get("reference") or "").replace("Patient/", "").strip()
        )
        if not patient_external_id:
            return

        raf_patient_id: int | None = self._resolve_or_create_raf_patient_id(
            patient_external_id
        )
        if raf_patient_id is None:
            return

        tenant_id: str = str(self.connection.get("tenant_id", "1"))

        # Category — typically a CodeableConcept array; pick the first code
        category_str: str = ""
        categories = resource.get("category", [])
        if categories:
            cat_codings = categories[0].get("coding", [])
            if cat_codings:
                category_str = cat_codings[0].get("code", "") or cat_codings[0].get(
                    "display", ""
                )
            if not category_str:
                category_str = categories[0].get("text", "")

        # Report code (LOINC)
        loinc_code: str = ""
        display_name: str = ""
        code_obj = resource.get("code", {})
        code_codings = code_obj.get("coding", [])
        if code_codings:
            loinc_code = code_codings[0].get("code", "")
            display_name = code_codings[0].get("display", "")
        if not display_name:
            display_name = code_obj.get("text", "")

        # Dates
        effective_raw: str = resource.get("effectiveDateTime", "") or resource.get(
            "effectivePeriod", {}
        ).get("start", "")
        effective_date = effective_raw[:10] if effective_raw else None

        issued_raw: str = resource.get("issued", "")
        # issued is RFC-3339; MySQL DATETIME accepts "YYYY-MM-DD HH:MM:SS"
        issued_date: str | None = None
        if issued_raw:
            issued_date = issued_raw[:19].replace("T", " ")

        status: str = resource.get("status", "")[:20]

        # Conclusion / narrative
        conclusion: str | None = resource.get("conclusion") or None

        # Attachments
        presented_forms = resource.get("presentedForm", [])
        has_attachment: int = 1 if presented_forms else 0

        with raf_cursor() as cur:
            # Ensure table exists exactly once per adapter instance
            if not hasattr(self, "_diag_table_ensured"):
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS patient_diagnostic_reports (
                        id                INT AUTO_INCREMENT PRIMARY KEY,
                        patient_id        INT NOT NULL,
                        tenant_id         VARCHAR(64),
                        fhir_report_id    VARCHAR(255),
                        category          VARCHAR(64),
                        loinc_code        VARCHAR(20),
                        display_name      VARCHAR(255),
                        conclusion        TEXT NULL,
                        effective_date    DATE,
                        issued_date       DATETIME,
                        status            VARCHAR(20),
                        has_attachment    TINYINT DEFAULT 0,
                        created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uq_tenant_fhir_report (tenant_id, fhir_report_id)
                    )
                    """
                )
                self._diag_table_ensured = True  # type: ignore[attr-defined]

            cur.execute(
                """
                INSERT INTO patient_diagnostic_reports
                    (patient_id, tenant_id, fhir_report_id, category, loinc_code,
                     display_name, conclusion, effective_date, issued_date, status,
                     has_attachment)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    patient_id     = VALUES(patient_id),
                    category       = VALUES(category),
                    loinc_code     = VALUES(loinc_code),
                    display_name   = VALUES(display_name),
                    conclusion     = VALUES(conclusion),
                    effective_date = VALUES(effective_date),
                    issued_date    = VALUES(issued_date),
                    status         = VALUES(status),
                    has_attachment = VALUES(has_attachment)
                """,
                (
                    raf_patient_id,
                    tenant_id,
                    fhir_report_id[:255],
                    category_str[:64] if category_str else None,
                    loinc_code[:20] if loinc_code else None,
                    display_name[:255] if display_name else None,
                    conclusion,
                    effective_date,
                    issued_date,
                    status or None,
                    has_attachment,
                ),
            )

        # Log substantial conclusion text for future NLP/HCC suspect detection
        if conclusion and len(conclusion) > 50:
            logger.info(
                "DiagnosticReport %s (patient=%d) has conclusion text (%d chars) "
                "available for NLP suspect detection",
                fhir_report_id,
                raf_patient_id,
                len(conclusion),
            )

        # Download PDF/image attachments through the document pipeline if present
        if presented_forms:
            for form in presented_forms:
                content_type: str = form.get("contentType", "")
                url: str = form.get("url", "")
                data_b64: str = form.get("data", "")
                if not (url or data_b64):
                    continue
                try:
                    self._save_diagnostic_report_attachment(
                        fhir_report_id=fhir_report_id,
                        raf_patient_id=raf_patient_id,
                        content_type=content_type,
                        url=url,
                        data_b64=data_b64,
                    )
                except Exception as exc:
                    logger.warning(
                        "DiagnosticReport %s: attachment download failed: %s",
                        fhir_report_id,
                        exc,
                    )

    def _save_diagnostic_report_attachment(
        self,
        *,
        fhir_report_id: str,
        raf_patient_id: int,
        content_type: str,
        url: str,
        data_b64: str,
    ) -> None:
        """Fetch and persist a DiagnosticReport presentedForm attachment.

        Downloads via FHIR bearer token when a URL is provided; decodes
        inline base64 data otherwise.  Delegates to ``_save_document_bytes``
        (the same hook used by the DocumentReference phase) so the binary
        lands in the patient document list and can be queued for analysis.
        """
        import base64

        raw_bytes: bytes | None = None

        if url:
            try:
                token = self._get_access_token()
                with httpx.Client(timeout=_TIMEOUT) as client:
                    resp = client.get(
                        url,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Accept": content_type or "*/*",
                        },
                    )
                    resp.raise_for_status()
                    raw_bytes = resp.content
            except Exception as exc:
                logger.warning(
                    "DiagnosticReport %s: could not fetch attachment from %s: %s",
                    fhir_report_id,
                    url,
                    exc,
                )
                return
        elif data_b64:
            try:
                raw_bytes = base64.b64decode(data_b64)
            except Exception as exc:
                logger.warning(
                    "DiagnosticReport %s: base64 decode failed: %s",
                    fhir_report_id,
                    exc,
                )
                return

        if not raw_bytes:
            return

        ext_map = {
            "application/pdf": ".pdf",
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "text/plain": ".txt",
            "text/html": ".html",
        }
        ext = ext_map.get(content_type.split(";")[0].strip(), ".bin")
        file_name = f"diagnostic_report_{fhir_report_id}{ext}"

        # Delegate to the shared document-save hook when available
        save_fn = getattr(self, "_save_document_bytes", None)
        if callable(save_fn):
            save_fn(
                raf_patient_id=raf_patient_id,
                file_name=file_name,
                content_type=content_type,
                raw_bytes=raw_bytes,
                source_ref=f"DiagnosticReport/{fhir_report_id}",
            )
        else:
            logger.info(
                "DiagnosticReport %s: attachment ready (%d bytes, %s) — "
                "no _save_document_bytes hook; skipping persist",
                fhir_report_id,
                len(raw_bytes),
                content_type,
            )

    # ------------------------------------------------------------------
    # RAF score calculation
    # ------------------------------------------------------------------

    def _calculate_raf_scores(self) -> int:
        """Roll up demographic + disease + interaction scores into raf_scores
        for every patient in raf_patient_demographics for the current
        measurement year.

        Returns the count of patient scores written.
        """
        import json as _json

        from app.db import raf_cursor

        measurement_year = date.today().year
        scores_written = 0

        with raf_cursor() as cur:
            # Fetch all demographics rows for current year scoped to this tenant
            tenant_id = str(self.connection.get("tenant_id") or "")
            if not tenant_id:
                raise ValueError("EMR connection has no tenant_id — cannot write RAF scores without tenant scope.")
            cur.execute(
                """
                SELECT patient_id AS raf_patient_id, age_band, sex, model_segment
                FROM raf_patient_demographics
                WHERE measurement_year = %s
                  AND patient_id IN (
                      SELECT id FROM patients WHERE emr_connection_id = %s AND tenant_id = %s
                  )
                """,
                (measurement_year, self.connection_id, tenant_id),
            )
            demo_rows = cur.fetchall()

        for demo in demo_rows:
            raf_patient_id: int = demo["raf_patient_id"]
            age_band: str = demo["age_band"]
            sex: str = demo["sex"]
            model_segment: str = demo["model_segment"]

            try:
                with raf_cursor() as cur:
                    # 1. Demographic coefficient
                    cur.execute(
                        """
                        SELECT coefficient
                        FROM hcc_demographic_coefficients
                        WHERE model_segment = %s
                          AND age_band = %s
                          AND sex = %s
                        ORDER BY ABS(CAST(model_year AS SIGNED) - %s)
                        LIMIT 1
                        """,
                        (model_segment, age_band, sex, measurement_year),
                    )
                    dc_row = cur.fetchone()
                    demographic_score = float(dc_row["coefficient"]) if dc_row else 0.0

                    # 2. Disease score — sum of non-trumped HCC coefficients
                    cur.execute(
                        """
                        SELECT COALESCE(SUM(raf_coefficient), 0) AS disease_score
                        FROM raf_patient_hcc
                        WHERE patient_id = %s
                          AND measurement_year = %s
                          AND is_trumped = 0
                        """,
                        (raf_patient_id, measurement_year),
                    )
                    ds_row = cur.fetchone()
                    disease_score = float(ds_row["disease_score"]) if ds_row else 0.0

                    # 3. Count of HCC codes for this patient / year
                    cur.execute(
                        """
                        SELECT COUNT(*) AS hcc_count
                        FROM raf_patient_hcc
                        WHERE patient_id = %s
                          AND measurement_year = %s
                          AND is_trumped = 0
                          AND hcc_code > 0
                        """,
                        (raf_patient_id, measurement_year),
                    )
                    cnt_row = cur.fetchone()
                    hcc_count: int = int(cnt_row["hcc_count"]) if cnt_row else 0

                    # 4. Interaction terms — check which terms apply by testing
                    #    whether the patient holds ALL required HCCs
                    cur.execute(
                        """
                        SELECT hcc_codes_required, coefficient
                        FROM hcc_interaction_terms
                        WHERE model_segment = %s
                        ORDER BY ABS(CAST(model_year AS SIGNED) - %s)
                        """,
                        (model_segment, measurement_year),
                    )
                    interaction_rows = cur.fetchall()

                    # Gather the patient's HCC set for fast membership testing
                    cur.execute(
                        """
                        SELECT DISTINCT hcc_code
                        FROM raf_patient_hcc
                        WHERE patient_id = %s
                          AND measurement_year = %s
                          AND is_trumped = 0
                        """,
                        (raf_patient_id, measurement_year),
                    )
                    patient_hccs: set[int] = set()
                    for r in cur.fetchall():
                        try:
                            patient_hccs.add(int(str(r["hcc_code"]).replace("HCC", "").strip()))
                        except (ValueError, TypeError):
                            pass

                    interaction_score = 0.0
                    for iterm in interaction_rows:
                        required_raw = iterm["hcc_codes_required"]
                        if isinstance(required_raw, str):
                            required_raw = _json.loads(required_raw)
                        required_hccs: set[int] = {int(h) for h in (required_raw or [])}
                        if required_hccs and required_hccs.issubset(patient_hccs):
                            interaction_score += float(iterm["coefficient"])

                    # 5. Aggregate
                    total_raw = demographic_score + disease_score + interaction_score
                    final_raf = round(total_raw, 4)

                    # 6. Upsert raf_scores
                    cur.execute(
                        """
                        INSERT INTO raf_scores
                            (patient_id, measurement_year, score_type,
                             model_segment, demographic_score, disease_score,
                             interaction_score, total_raw, normalization_factor,
                             final_raf, hcc_count, calculated_at)
                        VALUES (%s, %s, 'prospective', %s, %s, %s, %s, %s,
                                1.0, %s, %s, NOW())
                        ON DUPLICATE KEY UPDATE
                            demographic_score    = VALUES(demographic_score),
                            disease_score        = VALUES(disease_score),
                            interaction_score    = VALUES(interaction_score),
                            total_raw            = VALUES(total_raw),
                            final_raf            = VALUES(final_raf),
                            hcc_count            = VALUES(hcc_count),
                            calculated_at        = NOW(),
                            updated_at           = NOW()
                        """,
                        (
                            raf_patient_id,
                            measurement_year,
                            model_segment,
                            demographic_score,
                            disease_score,
                            interaction_score,
                            total_raw,
                            final_raf,
                            hcc_count,
                        ),
                    )
                    scores_written += 1
            except Exception as exc:
                logger.warning(
                    "OpenEMR FHIR: RAF score calculation failed for patient %s: %s",
                    raf_patient_id,
                    exc,
                )

        logger.info(
            "OpenEMR FHIR: wrote %d RAF score rows for measurement_year=%s",
            scores_written,
            measurement_year,
        )
        return scores_written

    # ------------------------------------------------------------------
    # Legacy condition upsert (kept for backward compatibility)
    # ------------------------------------------------------------------

    def _upsert_condition(self, condition: dict) -> None:
        """Deprecated: delegates to _upsert_condition_with_hcc."""
        self._upsert_condition_with_hcc(condition)
