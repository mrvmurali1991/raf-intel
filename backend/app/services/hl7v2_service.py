"""
HL7v2 Integration Service

Provides HL7v2 message parsing and a lightweight MLLP listener
for receiving real-time ADT, ORU, and DFT messages from legacy EMR systems.

Protocol: MLLP (Minimum Lower Layer Protocol) over TCP
  - Start block: 0x0B (\\x0b)
  - End block:   0x1C 0x0D (\\x1c\\r)
  - Segment delimiter: \\r
  - Field delimiter:   |
  - Component delimiter: ^

Message types handled
---------------------
* ADT^A01/A02/A03/A04/A08  — Admit / Discharge / Transfer / Update
* ORU^R01                   — Observation Result (labs, vitals)
* DFT^P03                   — Detailed Financial Transaction (diagnoses, billing)

Normalised output shapes mirror the ``BaseVendorAdapter`` contract defined in
``vendor_adapters/base.py`` so that downstream consumers (RAF calculator, sync
engine) receive identical structures regardless of transport.
"""
from __future__ import annotations

import logging
import socket
import threading
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MLLP framing constants
# ---------------------------------------------------------------------------

MLLP_START: bytes = b"\x0b"
MLLP_END: bytes = b"\x1c\r"

# Maximum raw message size we will accept from a single TCP read loop.
# 10 MB is extremely generous for HL7v2; real messages rarely exceed 64 KB.
_MAX_MESSAGE_BYTES = 10 * 1024 * 1024

# Socket read chunk size
_CHUNK = 4096


# ---------------------------------------------------------------------------
# HL7v2 message parser
# ---------------------------------------------------------------------------


class HL7ParseError(ValueError):
    """Raised when a raw HL7v2 string cannot be parsed."""


class HL7Message:
    """Parsed HL7v2 message.

    Segments are stored as a dict mapping segment-type to a list of parsed
    field lists, preserving repeated segments (multiple DG1, OBX, etc.).

    Example::

        msg = HL7Message(raw_text)
        print(msg.message_type)   # "ADT^A01"
        print(msg.patient_id)     # "12345"
    """

    def __init__(self, raw: str) -> None:
        self.raw: str = raw
        # Map of segment_id -> list of field-lists (each field is a str or list
        # of components when the component separator is present).
        self.segments: dict[str, list[list[Any]]] = {}
        self._field_sep: str = "|"
        self._comp_sep: str = "^"
        self._rep_sep: str = "~"
        self._esc_char: str = "\\"
        self._sub_comp_sep: str = "&"
        self._parse()

    # ------------------------------------------------------------------
    # Internal parsing
    # ------------------------------------------------------------------

    def _parse(self) -> None:
        """Parse raw HL7 text into the ``segments`` mapping."""
        raw = self.raw.replace("\n", "\r")  # normalise LF-only line endings
        lines = [l for l in raw.split("\r") if l.strip()]

        if not lines:
            raise HL7ParseError("Empty HL7 message")

        msh_line = lines[0]
        if not msh_line.startswith("MSH"):
            raise HL7ParseError(f"First segment is not MSH: {msh_line[:20]!r}")

        # MSH-1 is the field separator (the character immediately after "MSH")
        if len(msh_line) < 4:
            raise HL7ParseError("MSH segment too short to contain encoding characters")

        self._field_sep = msh_line[3]
        # MSH-2 is the encoding characters (^~\&) at position 4-7
        if len(msh_line) >= 8:
            encoding = msh_line[4:8]
            self._comp_sep = encoding[0] if len(encoding) > 0 else "^"
            self._rep_sep = encoding[1] if len(encoding) > 1 else "~"
            self._esc_char = encoding[2] if len(encoding) > 2 else "\\"
            self._sub_comp_sep = encoding[3] if len(encoding) > 3 else "&"

        for line in lines:
            if not line:
                continue
            seg_id = line[:3]
            # Split on field separator; for MSH, field 1 *is* the separator
            # so we shift the fields by one to keep indexing consistent.
            if seg_id == "MSH":
                fields_raw = line.split(self._field_sep)
                # Insert a synthetic MSH[1] = "|" so MSH[3] == sending app etc.
                fields_raw.insert(1, self._field_sep)
            else:
                fields_raw = line.split(self._field_sep)

            # Split each field into components
            parsed_fields: list[Any] = []
            for f in fields_raw:
                if self._comp_sep in f:
                    parsed_fields.append(f.split(self._comp_sep))
                else:
                    parsed_fields.append(f)

            self.segments.setdefault(seg_id, []).append(parsed_fields)

    # ------------------------------------------------------------------
    # Field access helpers
    # ------------------------------------------------------------------

    def _field(self, segment: str, field_index: int, seg_index: int = 0) -> str:
        """Return a field value as a plain string, or empty string if absent."""
        segs = self.segments.get(segment)
        if not segs or seg_index >= len(segs):
            return ""
        fields = segs[seg_index]
        if field_index >= len(fields):
            return ""
        val = fields[field_index]
        if isinstance(val, list):
            return val[0] if val else ""
        return val or ""

    def _component(
        self, segment: str, field_index: int, comp_index: int, seg_index: int = 0
    ) -> str:
        """Return a specific component (0-based) within a field."""
        segs = self.segments.get(segment)
        if not segs or seg_index >= len(segs):
            return ""
        fields = segs[seg_index]
        if field_index >= len(fields):
            return ""
        val = fields[field_index]
        if isinstance(val, list):
            return val[comp_index] if comp_index < len(val) else ""
        # No component separator was present — comp 0 is the whole value
        return val if comp_index == 0 else ""

    # ------------------------------------------------------------------
    # High-level properties
    # ------------------------------------------------------------------

    @property
    def message_type(self) -> str:
        """e.g. 'ADT^A01', 'ORU^R01', 'DFT^P03'."""
        # MSH-9 (field index 9 in our adjusted layout)
        segs = self.segments.get("MSH")
        if not segs:
            return ""
        fields = segs[0]
        if len(fields) <= 9:
            return ""
        val = fields[9]
        if isinstance(val, list):
            return "^".join(v for v in val[:2] if v)
        return val or ""

    @property
    def message_control_id(self) -> str:
        """MSH-10 — unique message identifier."""
        return self._field("MSH", 10)

    @property
    def sending_application(self) -> str:
        """MSH-3."""
        return self._field("MSH", 3)

    @property
    def sending_facility(self) -> str:
        """MSH-4."""
        return self._field("MSH", 4)

    @property
    def receiving_application(self) -> str:
        """MSH-5."""
        return self._field("MSH", 5)

    @property
    def receiving_facility(self) -> str:
        """MSH-6."""
        return self._field("MSH", 6)

    @property
    def message_datetime(self) -> str:
        """MSH-7 — raw date-time string from the message."""
        return self._field("MSH", 7)

    @property
    def patient_id(self) -> str:
        """PID-3 component 0 — primary patient identifier."""
        return self._component("PID", 3, 0)

    # ------------------------------------------------------------------
    # Demographic extraction
    # ------------------------------------------------------------------

    def get_patient_demographics(self) -> dict[str, Any]:
        """Extract patient demographics from the PID segment.

        Returns a dict aligned with ``BaseVendorAdapter`` Patient shape::

            {
                "external_id": str,   # PID-3 CX.1
                "mrn":         str,   # PID-3 CX.1 (same source)
                "first_name":  str,   # PID-5 XPN.2
                "last_name":   str,   # PID-5 XPN.1
                "date_of_birth": str, # PID-7 — YYYYMMDD -> YYYY-MM-DD
                "sex":         str,   # PID-8 (M/F/U)
                "address":     str,   # PID-11 XAD.1
                "city":        str,   # PID-11 XAD.3
                "state":       str,   # PID-11 XAD.4
                "zip":         str,   # PID-11 XAD.5
                "phone":       str,   # PID-13
                "ssn":         str,   # PID-19
                "raw":         dict,
            }
        """
        pid_raw = self._field("PID", 19)  # SSN if present

        dob_raw = self._field("PID", 7)
        dob = _parse_hl7_date(dob_raw)

        sex_raw = self._field("PID", 8).upper()
        sex_map = {"M": "M", "F": "F", "O": "U", "U": "U", "A": "U", "N": "U"}
        sex = sex_map.get(sex_raw, "U")

        # PID-5: family^given^middle^suffix^prefix
        last = self._component("PID", 5, 0)
        first = self._component("PID", 5, 1)
        middle = self._component("PID", 5, 2)

        # PID-11: street^other^city^state^zip^country
        address = self._component("PID", 11, 0)
        city = self._component("PID", 11, 2)
        state = self._component("PID", 11, 3)
        zip_code = self._component("PID", 11, 4)

        phone = self._field("PID", 13)
        patient_id = self.patient_id

        return {
            "external_id": patient_id,
            "mrn": patient_id,
            "first_name": first,
            "last_name": last,
            "middle_name": middle,
            "date_of_birth": dob,
            "sex": sex,
            "address": address,
            "city": city,
            "state": state,
            "zip": zip_code,
            "phone": phone,
            "ssn": pid_raw,
            "raw": {
                "segment": "PID",
                "fields": self.segments.get("PID", [[]])[0],
            },
        }

    # ------------------------------------------------------------------
    # Diagnosis extraction
    # ------------------------------------------------------------------

    def get_diagnoses(self) -> list[dict[str, Any]]:
        """Extract ICD-10 codes from all DG1 segments.

        DG1 field layout (HL7 v2.5):
          DG1-1  Set ID
          DG1-2  Diagnosis Coding Method (legacy, usually blank)
          DG1-3  Diagnosis Code — CE/CWE: code^description^coding_system
          DG1-4  Diagnosis Description (legacy — prefer DG1-3.2)
          DG1-5  Diagnosis Date/Time
          DG1-6  Diagnosis Type  (A=admitting, W=working, F=final)

        Returns a list of dicts, each with keys:
            ``icd10_code``, ``description``, ``type``, ``date``, ``raw``
        """
        results: list[dict[str, Any]] = []
        dg1_segs = self.segments.get("DG1", [])

        for idx, fields in enumerate(dg1_segs):
            # DG1-3: code^description^coding_system
            code_field = fields[3] if len(fields) > 3 else ""
            if isinstance(code_field, list):
                code = code_field[0] if len(code_field) > 0 else ""
                desc = code_field[1] if len(code_field) > 1 else ""
                coding_sys = code_field[2] if len(code_field) > 2 else ""
            else:
                code = code_field
                desc = ""
                coding_sys = ""

            # Fall back to DG1-4 description if DG1-3.2 empty
            if not desc:
                desc_field = fields[4] if len(fields) > 4 else ""
                desc = desc_field if isinstance(desc_field, str) else (desc_field[0] if desc_field else "")

            # DG1-5: diagnosis date
            date_raw = fields[5] if len(fields) > 5 else ""
            if isinstance(date_raw, list):
                date_raw = date_raw[0] if date_raw else ""
            diag_date = _parse_hl7_date(str(date_raw))

            # DG1-6: diagnosis type
            dtype_raw = fields[6] if len(fields) > 6 else ""
            if isinstance(dtype_raw, list):
                dtype_raw = dtype_raw[0] if dtype_raw else ""
            dtype = _normalise_diagnosis_type(str(dtype_raw))

            # Normalise ICD-10 code format: remove extra whitespace, uppercase
            icd10 = _normalise_icd10(str(code))

            if icd10:
                results.append(
                    {
                        "icd10_code": icd10,
                        "description": str(desc).strip(),
                        "type": dtype,
                        "date": diag_date,
                        "coding_system": coding_sys,
                        "raw": {"segment": "DG1", "index": idx, "fields": fields},
                    }
                )
            else:
                logger.debug(
                    "hl7v2: DG1[%d] has no parseable ICD code (raw=%r)", idx, code
                )

        return results

    # ------------------------------------------------------------------
    # Observation extraction
    # ------------------------------------------------------------------

    def get_observations(self) -> list[dict[str, Any]]:
        """Extract lab and vital results from OBX segments.

        OBX field layout (HL7 v2.5):
          OBX-1  Set ID
          OBX-2  Value Type (NM, ST, TX, CWE, …)
          OBX-3  Observation Identifier (LOINC: code^description^system)
          OBX-4  Observation Sub-ID
          OBX-5  Observation Value
          OBX-6  Units (CE: code^description)
          OBX-7  Reference Range
          OBX-8  Abnormal Flag (H/L/A/N/…)
          OBX-11 Observation Result Status (F=final, P=preliminary, …)
          OBX-14 Date/Time of Observation

        Returns a list of dicts, each with keys:
            ``code``, ``description``, ``value``, ``units``, ``reference_range``,
            ``abnormal_flag``, ``status``, ``date``, ``raw``
        """
        results: list[dict[str, Any]] = []
        obx_segs = self.segments.get("OBX", [])

        for idx, fields in enumerate(obx_segs):
            # OBX-3: LOINC code^description^system
            obs_id = fields[3] if len(fields) > 3 else ""
            if isinstance(obs_id, list):
                code = obs_id[0] if obs_id else ""
                obs_desc = obs_id[1] if len(obs_id) > 1 else ""
            else:
                code = obs_id
                obs_desc = ""

            # OBX-5: value (may be complex for CWE — take first component)
            value_raw = fields[5] if len(fields) > 5 else ""
            if isinstance(value_raw, list):
                value = value_raw[0] if value_raw else ""
            else:
                value = value_raw

            # OBX-6: units
            units_raw = fields[6] if len(fields) > 6 else ""
            if isinstance(units_raw, list):
                units = units_raw[0] if units_raw else ""
            else:
                units = units_raw

            # OBX-7: reference range
            ref_range = fields[7] if len(fields) > 7 else ""
            if isinstance(ref_range, list):
                ref_range = ref_range[0] if ref_range else ""

            # OBX-8: abnormal flags
            abnormal_raw = fields[8] if len(fields) > 8 else ""
            if isinstance(abnormal_raw, list):
                abnormal_raw = abnormal_raw[0] if abnormal_raw else ""
            abnormal_flag = str(abnormal_raw).strip()

            # OBX-11: result status
            status_raw = fields[11] if len(fields) > 11 else ""
            if isinstance(status_raw, list):
                status_raw = status_raw[0] if status_raw else ""
            obs_status = _normalise_obs_status(str(status_raw))

            # OBX-14: observation date/time
            dt_raw = fields[14] if len(fields) > 14 else ""
            if isinstance(dt_raw, list):
                dt_raw = dt_raw[0] if dt_raw else ""
            obs_date = _parse_hl7_datetime(str(dt_raw))

            results.append(
                {
                    "code": str(code).strip(),
                    "description": str(obs_desc).strip(),
                    "value": str(value).strip(),
                    "units": str(units).strip(),
                    "reference_range": str(ref_range).strip(),
                    "abnormal_flag": abnormal_flag,
                    "status": obs_status,
                    "date": obs_date,
                    "raw": {"segment": "OBX", "index": idx, "fields": fields},
                }
            )

        return results


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def parse_hl7_message(raw: str) -> HL7Message:
    """Parse a raw HL7v2 string and return an :class:`HL7Message`.

    Parameters
    ----------
    raw:
        The raw HL7v2 message text.  May use ``\\r``, ``\\n``, or ``\\r\\n`` as
        segment delimiters — all are normalised internally.

    Raises
    ------
    HL7ParseError
        If the message cannot be parsed (missing MSH, truncated encoding
        characters, etc.).
    """
    if not raw or not raw.strip():
        raise HL7ParseError("Cannot parse empty HL7 message")
    return HL7Message(raw)


def extract_patient(msg: HL7Message) -> dict[str, Any]:
    """Return a normalised patient dict from *msg*.

    The returned structure matches ``BaseVendorAdapter`` Patient shape so it
    can be passed directly to the RAF calculator and sync engine.

    Parameters
    ----------
    msg:
        A parsed :class:`HL7Message`.

    Returns
    -------
    dict with keys: ``external_id``, ``mrn``, ``first_name``, ``last_name``,
    ``date_of_birth``, ``sex``, ``raw``.
    """
    demo = msg.get_patient_demographics()
    return {
        "external_id": demo.get("external_id", ""),
        "mrn": demo.get("mrn", ""),
        "first_name": demo.get("first_name", ""),
        "last_name": demo.get("last_name", ""),
        "middle_name": demo.get("middle_name", ""),
        "date_of_birth": demo.get("date_of_birth", ""),
        "sex": demo.get("sex", "U"),
        "address": demo.get("address", ""),
        "city": demo.get("city", ""),
        "state": demo.get("state", ""),
        "zip": demo.get("zip", ""),
        "phone": demo.get("phone", ""),
        "raw": demo.get("raw", {}),
    }


def extract_diagnoses(msg: HL7Message) -> list[dict[str, Any]]:
    """Return a list of normalised diagnosis dicts from DG1 segments.

    Each dict contains:
        ``icd10_code``, ``description``, ``type``, ``date``, ``raw``

    The ``type`` field is normalised to one of:
        ``admitting``, ``working``, ``final``, ``unknown``
    """
    return msg.get_diagnoses()


def extract_observations(msg: HL7Message) -> list[dict[str, Any]]:
    """Return a list of normalised observation dicts from OBX segments.

    Each dict contains:
        ``code``, ``description``, ``value``, ``units``, ``reference_range``,
        ``abnormal_flag``, ``status``, ``date``, ``raw``

    The ``status`` field is normalised to one of:
        ``final``, ``preliminary``, ``corrected``, ``cancelled``, ``unknown``
    """
    return msg.get_observations()


# ---------------------------------------------------------------------------
# MLLP TCP listener
# ---------------------------------------------------------------------------


class MLLPListener:
    """Lightweight TCP listener for HL7v2 MLLP-framed messages.

    Runs a background daemon thread that accepts TCP connections and reads
    MLLP-framed HL7v2 messages.  Each complete message is passed to the
    *handler* callable, and an HL7 ACK is sent back to the sender.

    Usage::

        def my_handler(msg: HL7Message, address: tuple) -> None:
            logger.info("Received %s from %s", msg.message_type, address)

        listener = MLLPListener(host="0.0.0.0", port=2575, handler=my_handler)
        listener.start()
        # … later …
        listener.stop()

    Thread safety
    -------------
    ``start()`` and ``stop()`` are safe to call from any thread.
    The handler is called from a per-connection daemon thread; it must be
    thread-safe if it accesses shared state.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 2575,
        handler: Callable[[HL7Message, tuple[str, int]], None] | None = None,
        connection_id: int | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.handler: Callable[[HL7Message, tuple[str, int]], None] = (
            handler or self._default_handler
        )
        self.connection_id = connection_id
        self._server_socket: socket.socket | None = None
        self._running: bool = False
        self._thread: threading.Thread | None = None
        self._lock: threading.Lock = threading.Lock()
        # Counts for the status endpoint
        self.messages_received: int = 0
        self.messages_errored: int = 0
        self.started_at: datetime | None = None

    # ------------------------------------------------------------------
    # Public lifecycle API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the MLLP listener in a background daemon thread.

        Raises
        ------
        RuntimeError
            If the listener is already running.
        OSError
            If the TCP port cannot be bound (e.g. already in use, permission
            denied for ports < 1024 without CAP_NET_BIND_SERVICE).
        """
        with self._lock:
            if self._running:
                raise RuntimeError(
                    f"MLLPListener is already running on {self.host}:{self.port}"
                )

            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                srv.bind((self.host, self.port))
            except OSError as exc:
                srv.close()
                raise OSError(
                    f"MLLPListener: cannot bind to {self.host}:{self.port} — {exc}"
                ) from exc

            srv.listen(10)
            srv.settimeout(1.0)  # allows _accept_loop to check _running flag
            self._server_socket = srv
            self._running = True
            self.started_at = datetime.now(timezone.utc)
            self.messages_received = 0
            self.messages_errored = 0

        self._thread = threading.Thread(
            target=self._accept_loop,
            name=f"mllp-listener-{self.port}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "hl7v2: MLLP listener started on %s:%s (connection_id=%s)",
            self.host,
            self.port,
            self.connection_id,
        )

    def stop(self) -> None:
        """Stop the MLLP listener and close the server socket."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            if self._server_socket:
                try:
                    self._server_socket.close()
                except OSError:
                    pass
                self._server_socket = None

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        logger.info(
            "hl7v2: MLLP listener stopped on %s:%s (connection_id=%s)",
            self.host,
            self.port,
            self.connection_id,
        )

    @property
    def is_running(self) -> bool:
        """True if the listener is currently accepting connections."""
        return self._running

    def status(self) -> dict[str, Any]:
        """Return a status dict suitable for the REST status endpoint."""
        return {
            "running": self._running,
            "host": self.host,
            "port": self.port,
            "connection_id": self.connection_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "messages_received": self.messages_received,
            "messages_errored": self.messages_errored,
        }

    # ------------------------------------------------------------------
    # Internal accept / connection loop
    # ------------------------------------------------------------------

    def _accept_loop(self) -> None:
        """Main server loop — accepts TCP connections until stopped."""
        while self._running:
            try:
                client_sock, address = self._server_socket.accept()  # type: ignore[union-attr]
            except socket.timeout:
                continue
            except OSError:
                # Socket closed by stop() — exit cleanly
                break

            t = threading.Thread(
                target=self._handle_connection,
                args=(client_sock, address),
                daemon=True,
            )
            t.start()

    def _handle_connection(
        self, client_socket: socket.socket, address: tuple[str, int]
    ) -> None:
        """Read MLLP-framed messages from a single client connection."""
        logger.debug("hl7v2: accepted connection from %s:%s", *address)
        try:
            with client_socket:
                client_socket.settimeout(30.0)
                buf = b""
                while self._running:
                    try:
                        chunk = client_socket.recv(_CHUNK)
                    except socket.timeout:
                        logger.debug(
                            "hl7v2: read timeout from %s:%s — closing connection",
                            *address,
                        )
                        break
                    except OSError as exc:
                        logger.warning(
                            "hl7v2: socket error reading from %s:%s: %s", *address, exc
                        )
                        break

                    if not chunk:
                        break  # client disconnected

                    buf += chunk

                    if len(buf) > _MAX_MESSAGE_BYTES:
                        logger.error(
                            "hl7v2: message from %s:%s exceeds %d bytes — dropping connection",
                            *address,
                            _MAX_MESSAGE_BYTES,
                        )
                        break

                    # Process all complete MLLP frames in the buffer
                    while True:
                        start_idx = buf.find(MLLP_START)
                        end_idx = buf.find(MLLP_END)

                        if start_idx == -1 or end_idx == -1:
                            break  # wait for more data

                        if end_idx < start_idx:
                            # Framing error — discard bytes before start
                            logger.warning(
                                "hl7v2: framing error from %s:%s — discarding %d bytes",
                                *address,
                                end_idx + len(MLLP_END),
                            )
                            buf = buf[end_idx + len(MLLP_END):]
                            continue

                        raw_bytes = buf[start_idx + len(MLLP_START): end_idx]
                        buf = buf[end_idx + len(MLLP_END):]

                        ack_bytes = self._process_message(raw_bytes, address)
                        try:
                            client_socket.sendall(ack_bytes)
                        except OSError as exc:
                            logger.warning(
                                "hl7v2: failed to send ACK to %s:%s: %s",
                                *address,
                                exc,
                            )
        except Exception as exc:
            logger.exception(
                "hl7v2: unexpected error handling connection from %s:%s: %s",
                *address,
                exc,
            )

    def _process_message(
        self, raw_bytes: bytes, address: tuple[str, int]
    ) -> bytes:
        """Decode, parse, dispatch to handler, and return MLLP-framed ACK."""
        ack_code = "AA"  # Application Accept
        parsed_msg: HL7Message | None = None

        try:
            raw_text = raw_bytes.decode("utf-8", errors="replace")
            parsed_msg = parse_hl7_message(raw_text)
        except (HL7ParseError, UnicodeDecodeError) as exc:
            logger.error(
                "hl7v2: parse error for message from %s:%s: %s", *address, exc
            )
            self.messages_errored += 1
            ack_code = "AE"  # Application Error

        if parsed_msg is not None:
            try:
                self.handler(parsed_msg, address)
                self.messages_received += 1
                logger.debug(
                    "hl7v2: processed %s from %s:%s (patient=%s)",
                    parsed_msg.message_type,
                    *address,
                    parsed_msg.patient_id,
                )
            except Exception as exc:
                logger.exception(
                    "hl7v2: handler raised exception for message from %s:%s: %s",
                    *address,
                    exc,
                )
                self.messages_errored += 1
                ack_code = "AE"

        ack_text = self._build_ack(parsed_msg, ack_code)
        return MLLP_START + ack_text.encode("utf-8") + MLLP_END

    # ------------------------------------------------------------------
    # ACK builder
    # ------------------------------------------------------------------

    def _build_ack(
        self,
        original_msg: HL7Message | None,
        ack_code: str = "AA",
    ) -> str:
        """Build an HL7v2 ACK message in MLLP-ready text form.

        Parameters
        ----------
        original_msg:
            The parsed inbound message.  When ``None`` (parse failure), a
            generic ACK with empty control ID is generated.
        ack_code:
            ``AA`` — Application Accept (success)
            ``AE`` — Application Error
            ``AR`` — Application Reject
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        ack_msg_id = f"RAF{ts}"

        if original_msg is not None:
            sending_app = original_msg.sending_application
            sending_fac = original_msg.sending_facility
            orig_ctrl_id = original_msg.message_control_id
        else:
            sending_app = "UNKNOWN"
            sending_fac = "UNKNOWN"
            orig_ctrl_id = ""

        msh = (
            f"MSH|^~\\&|RAF|INTELLIGENCE"
            f"|{sending_app}|{sending_fac}"
            f"|{ts}||ACK|{ack_msg_id}|P|2.5"
        )
        msa = f"MSA|{ack_code}|{orig_ctrl_id}"

        return f"{msh}\r{msa}\r"

    # ------------------------------------------------------------------
    # Default handler
    # ------------------------------------------------------------------

    @staticmethod
    def _default_handler(msg: HL7Message, address: tuple[str, int]) -> None:
        """Log the message type and patient ID — replace with real handler."""
        logger.info(
            "hl7v2: received %s for patient=%s from %s:%s",
            msg.message_type,
            msg.patient_id,
            *address,
        )


# ---------------------------------------------------------------------------
# In-process listener registry (keyed by connection_id)
# ---------------------------------------------------------------------------

_listener_registry: dict[int, MLLPListener] = {}
_registry_lock = threading.Lock()


def get_listener(connection_id: int) -> MLLPListener | None:
    """Return the running :class:`MLLPListener` for *connection_id*, or None."""
    with _registry_lock:
        return _listener_registry.get(connection_id)


def register_listener(connection_id: int, listener: MLLPListener) -> None:
    """Register *listener* under *connection_id*.  Replaces any existing entry."""
    with _registry_lock:
        _listener_registry[connection_id] = listener


def unregister_listener(connection_id: int) -> None:
    """Remove the listener entry for *connection_id* (does not stop it)."""
    with _registry_lock:
        _listener_registry.pop(connection_id, None)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_hl7_date(raw: str) -> str:
    """Convert an HL7 date/datetime string to ``YYYY-MM-DD`` or empty string."""
    raw = raw.strip()
    # HL7 dates: YYYY, YYYYMM, YYYYMMDD, YYYYMMDDHHmmss[.S][±ZZZZ]
    # Strip timezone offset if present
    for sep in ("+", "-"):
        if len(raw) > 8 and sep in raw[8:]:
            raw = raw[: raw.index(sep, 8)]
            break
    # Strip fractional seconds
    if "." in raw:
        raw = raw[: raw.index(".")]

    if len(raw) >= 8:
        try:
            dt = datetime.strptime(raw[:8], "%Y%m%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def _parse_hl7_datetime(raw: str) -> str:
    """Convert an HL7 datetime string to ISO-8601 or empty string."""
    raw = raw.strip()
    date_part = _parse_hl7_date(raw)
    if not date_part:
        return ""

    if len(raw) >= 12:
        try:
            dt = datetime.strptime(raw[:12], "%Y%m%d%H%M")
            return dt.strftime("%Y-%m-%dT%H:%M:00")
        except ValueError:
            pass

    return date_part


def _normalise_icd10(code: str) -> str:
    """Strip whitespace and normalise ICD-10 code format."""
    code = code.strip().upper()
    # Remove spaces within code (some systems send "E11 .9")
    code = code.replace(" ", "")
    return code


def _normalise_diagnosis_type(raw: str) -> str:
    """Map HL7 DG1-6 value to a human-readable type string."""
    mapping: dict[str, str] = {
        "A": "admitting",
        "W": "working",
        "F": "final",
        "": "unknown",
    }
    return mapping.get(raw.strip().upper(), "unknown")


def _normalise_obs_status(raw: str) -> str:
    """Map HL7 OBX-11 result status to a normalised string."""
    mapping: dict[str, str] = {
        "F": "final",
        "P": "preliminary",
        "C": "corrected",
        "X": "cancelled",
        "I": "pending",
        "R": "entered_in_error",
        "S": "partial",
        "U": "final",   # U = results entered — treat as final
        "": "unknown",
    }
    return mapping.get(raw.strip().upper(), "unknown")
