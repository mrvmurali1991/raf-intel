"""
HL7 v2 MDM (Medical Document Management) Parser
=================================================

Pure parser — no MLLP socket listening.  A sidecar process (Mirth, Rhapsody,
or a thin HL7 relay) POSTs the raw pipe-delimited HL7 v2 text to the HTTP
receiver endpoint in ``routers/hl7v2_mdm_receiver.py``.

Supported message events
------------------------
  MDM^T02  — Original document notification (new document attached)
  MDM^T08  — Document edit notification (amendment / update)

Supported OBX-5 payloads
-------------------------
  Base64 PDF   — value type ED; component structure
                 ``<source>^application^pdf^Base64^<b64data>``
  Text report  — value type TX or FT; plain-text clinical note, possibly
                 spanning multiple OBX segments (continuation lines).

Public API
----------
  parse_mdm(raw: str) -> dict
      Returns a flat dict; never raises on well-formed HL7.  Raises
      ``HL7MDMParseError`` if the message is not an MDM type or is
      structurally invalid (no MSH).
"""
from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class HL7MDMParseError(ValueError):
    """Raised when the raw string cannot be parsed as an MDM message."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SEGMENT_TERMINATOR_RE = re.compile(r"\r\n|\r|\n")

# OBX value types that carry embedded documents
_OBX_TYPE_BINARY = {"ED", "RP"}
_OBX_TYPE_TEXT = {"TX", "FT", "ST"}


# ---------------------------------------------------------------------------
# Low-level segment tokeniser
# ---------------------------------------------------------------------------


def _split_segments(raw: str) -> list[str]:
    """Split a raw HL7 string into non-empty segment lines."""
    # Strip MLLP framing bytes in case they leak through
    stripped = raw.strip("\x0b\x1c\r\n ")
    segments = _SEGMENT_TERMINATOR_RE.split(stripped)
    return [s for s in segments if s.strip()]


def _parse_msh(seg: str) -> dict[str, Any]:
    """Parse the MSH segment; returns field dict keyed by 1-based index."""
    # MSH is special: field 1 IS the field separator character
    if not seg.startswith("MSH"):
        raise HL7MDMParseError("First segment is not MSH")
    field_sep = seg[3]  # almost always '|'
    comp_sep = seg[4] if len(seg) > 4 else "^"
    fields = seg.split(field_sep)
    return {
        "field_sep": field_sep,
        "comp_sep": comp_sep,
        "fields": fields,
        "raw": seg,
    }


def _field(fields: list[str], index: int, default: str = "") -> str:
    """Return field at 1-based *index* from a split segment list."""
    try:
        return fields[index] or default
    except IndexError:
        return default


def _component(value: str, comp_sep: str, index: int, default: str = "") -> str:
    """Return component at 0-based *index* from a field value."""
    parts = value.split(comp_sep)
    try:
        return parts[index] or default
    except IndexError:
        return default


# ---------------------------------------------------------------------------
# Public parse function
# ---------------------------------------------------------------------------


def parse_mdm(raw: str) -> dict[str, Any]:
    """Parse a raw HL7 v2 MDM^T02 / MDM^T08 message string.

    Parameters
    ----------
    raw:
        The complete HL7 v2 pipe-delimited text, using ``\\r``, ``\\n``,
        or ``\\r\\n`` as segment terminators.

    Returns
    -------
    dict with keys:
        msg_type            (str)  e.g. ``"MDM^T02"``
        msg_control_id      (str)  MSH-10
        patient_external_id (str)  PID-3 first patient ID
        document_type       (str)  TXA-2 document type code
        document_status     (str)  TXA-17 document completion status
        observation_date    (str)  OBX-14 or TXA-4 datetime string
        document_filename   (str)  filename hint from OBX-3 or TXA-12
        encoded_payload     (bytes | None)  raw PDF bytes (decoded from b64)
        payload_mime        (str)  ``"application/pdf"`` or ``"text/plain"``
        text_payload        (str | None)  concatenated text for TX mode

    Raises
    ------
    HL7MDMParseError
        If the message is not a valid MDM type or MSH is missing.
    """
    segs = _split_segments(raw)
    if not segs:
        raise HL7MDMParseError("Empty HL7 message")

    msh_info = _parse_msh(segs[0])
    fsep = msh_info["field_sep"]
    csep = msh_info["comp_sep"]
    msh_fields = msh_info["fields"]

    # HL7 v2 MSH field numbering (1-based) where MSH-1 is the field separator.
    # After split('|'): fields[0]="MSH", fields[1]=MSH-2 (enc chars),
    # fields[2]=MSH-3 (sending app), ..., fields[N-1]=MSH-N.
    # So MSH-N maps to fields[N-1] in 0-based list indexing.
    #
    # MSH-9 (msg type, e.g. "MDM^T02") → fields[8]
    # MSH-10 (msg control id)           → fields[9]
    # MSH-3  (sending app)              → fields[2]
    # MSH-4  (sending facility)         → fields[3]

    msg_type_field = _field(msh_fields, 8)
    msg_type = msg_type_field.replace(csep, "^")  # normalise component sep
    if not msg_type.startswith("MDM"):
        raise HL7MDMParseError(
            f"Expected MDM message, got msg_type={msg_type!r}"
        )

    msg_control_id = _field(msh_fields, 9)
    sending_facility = _field(msh_fields, 3)
    sending_app = _field(msh_fields, 2)

    # -----------------------------------------------------------------------
    # Parse remaining segments into a dict of lists (segment_id -> [fields])
    # -----------------------------------------------------------------------
    seg_map: dict[str, list[list[str]]] = {}
    for seg in segs[1:]:
        seg_type = seg[:3]
        fields = seg.split(fsep)
        seg_map.setdefault(seg_type, []).append(fields)

    # -----------------------------------------------------------------------
    # PID — patient identifier
    # -----------------------------------------------------------------------
    patient_external_id = ""
    if "PID" in seg_map:
        pid_fields = seg_map["PID"][0]
        # PID-3 is the patient identifier list (may be a composite CX)
        pid3 = _field(pid_fields, 3)
        patient_external_id = _component(pid3, csep, 0) or pid3

    # -----------------------------------------------------------------------
    # EVN — event type (informational only)
    # -----------------------------------------------------------------------
    event_type_code = ""
    if "EVN" in seg_map:
        evn_fields = seg_map["EVN"][0]
        event_type_code = _field(evn_fields, 1)

    # -----------------------------------------------------------------------
    # TXA — transcription document header
    # -----------------------------------------------------------------------
    document_type = ""
    document_status = ""
    txa_obs_date = ""
    document_filename = ""

    if "TXA" in seg_map:
        txa_fields = seg_map["TXA"][0]
        document_type = _field(txa_fields, 2)
        txa_obs_date = _field(txa_fields, 4)
        document_status = _field(txa_fields, 17)
        # TXA-12: unique document filename hint
        txa12 = _field(txa_fields, 12)
        if txa12:
            document_filename = _component(txa12, csep, 0) or txa12

    # -----------------------------------------------------------------------
    # OBX — observation/result (carries the actual document payload)
    # -----------------------------------------------------------------------
    encoded_payload: bytes | None = None
    payload_mime = "text/plain"
    text_lines: list[str] = []
    obx_obs_date = ""

    for obx_fields in seg_map.get("OBX", []):
        value_type = _field(obx_fields, 2).strip().upper()
        # OBX-3: observation identifier (may contain filename hint)
        obx3 = _field(obx_fields, 3)
        if not document_filename and obx3:
            document_filename = _component(obx3, csep, 1) or _component(obx3, csep, 0)

        # OBX-14: date/time of observation
        obx14 = _field(obx_fields, 14)
        if obx14 and not obx_obs_date:
            obx_obs_date = obx14

        obx5 = _field(obx_fields, 5)

        if value_type in _OBX_TYPE_BINARY or (
            value_type == "" and csep in obx5
        ):
            # Encapsulated data (ED): <source>^<type>^<subtype>^<encoding>^<data>
            components = obx5.split(csep)
            encoding = components[3].strip().upper() if len(components) > 3 else ""
            data_str = components[4] if len(components) > 4 else ""
            sub_type = components[2].strip().lower() if len(components) > 2 else ""
            type_str = components[1].strip().lower() if len(components) > 1 else ""

            if sub_type == "pdf" or type_str == "application":
                payload_mime = "application/pdf"
            else:
                payload_mime = f"{type_str}/{sub_type}" if type_str else "application/octet-stream"

            if encoding == "BASE64" and data_str:
                try:
                    # HL7 allows line-wrapped base64 — strip whitespace
                    encoded_payload = base64.b64decode(
                        re.sub(r"\s+", "", data_str)
                    )
                except Exception as exc:
                    logger.warning("hl7v2_mdm: base64 decode failed: %s", exc)

        elif value_type in _OBX_TYPE_TEXT or value_type == "":
            # Plain text — accumulate continuation lines
            text_lines.append(obx5)

    # Fallback observation date from TXA if OBX-14 was absent
    observation_date = obx_obs_date or txa_obs_date

    text_payload: str | None = None
    if text_lines and encoded_payload is None:
        text_payload = "\n".join(text_lines)
        payload_mime = "text/plain"

    return {
        "msg_type": msg_type,
        "msg_control_id": msg_control_id,
        "sending_app": sending_app,
        "sending_facility": sending_facility,
        "event_type_code": event_type_code,
        "patient_external_id": patient_external_id,
        "document_type": document_type,
        "document_status": document_status,
        "observation_date": observation_date,
        "document_filename": document_filename,
        "encoded_payload": encoded_payload,
        "payload_mime": payload_mime,
        "text_payload": text_payload,
    }
