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

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


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
                        logger.info("OpenEMR FHIR: JWT full payload: %s", payload)
                except Exception:
                    pass
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
            import jwt as _pyjwt
            import uuid

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
        with httpx.Client(timeout=_TIMEOUT, verify=True) as client:
            resp = client.get(url, headers=self._auth_headers(), params=params)
            if resp.status_code == 401:
                logger.warning(
                    "FHIR GET %s -> 401, forcing token refresh", resource_path
                )
                self._force_refresh()
                resp = client.get(url, headers=self._auth_headers(), params=params)
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

        with httpx.Client(timeout=_TIMEOUT, verify=True) as client:
            for page in range(max_pages):
                resp = client.get(
                    url, headers=self._auth_headers(), params=p if page == 0 else None
                )
                if resp.status_code == 401:
                    logger.warning(
                        "FHIR %s page %d -> 401 body: %s",
                        resource_type,
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
                p = None  # params already in the next URL

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
                    errors.append(f"Encounter {resource.get('id')}: {exc}")
        except Exception as exc:
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
                    errors.append(f"MedicationRequest {resource.get('id')}: {exc}")
        except Exception as exc:
            errors.append(f"MedicationRequest fetch failed: {exc}")

        # ------------------------------------------------------------------ #
        # Phase 4 — RAF score calculation                                      #
        # ------------------------------------------------------------------ #
        try:
            raf_scores_calculated = self._calculate_raf_scores()
        except Exception as exc:
            errors.append(f"RAF score calculation failed: {exc}")

        logger.info(
            "OpenEMR FHIR sync done: %d patients, %d conditions, %d conditions_skipped, "
            "%d encounters, %d medications, %d RAF scores, %d errors",
            patients_synced,
            conditions_found,
            conditions_skipped,
            encounters_synced,
            medications_synced,
            raf_scores_calculated,
            len(errors),
        )
        return {
            "patients_synced": patients_synced,
            "conditions_found": conditions_found,
            "conditions_skipped": conditions_skipped,
            "encounters_synced": encounters_synced,
            "medications_synced": medications_synced,
            "raf_scores_calculated": raf_scores_calculated,
            "errors": errors,
        }

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

        with raf_cursor() as cur:
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
                           preferred_language = IF(%s != '', %s, preferred_language),
                           race = IF(%s != '', %s, race),
                           ethnicity = IF(%s != '', %s, ethnicity),
                           address = %s, city = %s, state = %s, zip = %s,
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
                            created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'fhir', 1,
                               %s, %s, %s, %s, %s, %s, %s, %s, %s,
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
                           preferred_language = IF(VALUES(preferred_language) != '', VALUES(preferred_language), preferred_language),
                           race       = IF(VALUES(race) != '', VALUES(race), race),
                           ethnicity  = IF(VALUES(ethnicity) != '', VALUES(ethnicity), ethnicity),
                           address    = VALUES(address),
                           city       = VALUES(city),
                           state      = VALUES(state),
                           zip        = VALUES(zip),
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
        from app.db import raf_cursor
        import json as _json

        icd10 = (condition.get("icd10_code") or "").strip().upper()
        if not icd10:
            return

        measurement_year = date.today().year

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

            # 4. Determine MEAT status based on clinical documentation presence
            meat_status = "complete" if condition.get("onset_date") else "partial"

            # 5. Upsert into raf_patient_hcc
            cur.execute(
                """
                INSERT INTO raf_patient_hcc
                    (patient_id, measurement_year, hcc_code, icd10_codes,
                     source_encounter_ids, raf_coefficient, meat_status,
                     is_trumped, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 0, NOW())
                ON DUPLICATE KEY UPDATE
                    icd10_codes = JSON_ARRAY_APPEND(
                        COALESCE(icd10_codes, JSON_ARRAY()), '$', %s
                    ),
                    raf_coefficient = VALUES(raf_coefficient),
                    meat_status = VALUES(meat_status),
                    updated_at = NOW()
                """,
                (
                    raf_patient_id,
                    measurement_year,
                    hcc_code,
                    _json.dumps([icd10]),
                    _json.dumps([]),
                    raf_coefficient,
                    meat_status,
                    # ON DUPLICATE KEY extra param for JSON_ARRAY_APPEND
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
            encounter_surrogate: int = int(hashlib.md5(encounter_fhir_id.encode()).hexdigest()[:8], 16) % (2**31)

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
    # RAF score calculation
    # ------------------------------------------------------------------

    def _calculate_raf_scores(self) -> int:
        """Roll up demographic + disease + interaction scores into raf_scores
        for every patient in raf_patient_demographics for the current
        measurement year.

        Returns the count of patient scores written.
        """
        from app.db import raf_cursor
        import json as _json

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
