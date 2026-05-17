"""Centralized SQL identifier safety.

For LITERAL VALUES: always use parameterized queries — `cursor.execute(sql, params)`.

For SQL IDENTIFIERS (table/column/index names) that must be interpolated
into a query string (NOT from user input): route them through these helpers.
They allow only `[a-zA-Z_][a-zA-Z0-9_]{0,63}` and raise on anything else.
"""
from __future__ import annotations

import re

_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


class UnsafeIdentifierError(ValueError):
    """Raised when an identifier fails the safe pattern check."""


def safe_ident(name: str) -> str:
    """Validate an identifier and return it unchanged.

    NEVER use on user-controlled input — even after validation, identifier
    interpolation should only ever come from code-side constants.
    """
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise UnsafeIdentifierError(f"Unsafe SQL identifier: {name!r}")
    return name


def safe_qualified(name: str) -> str:
    """Validate a dotted identifier (schema.table or schema.table.column)."""
    parts = name.split(".")
    if not 1 <= len(parts) <= 3:
        raise UnsafeIdentifierError(f"Too many parts in {name!r}")
    return ".".join(safe_ident(p) for p in parts)


def safe_in_clause(items: list, item_type: str = "int") -> str:
    """Build a parenthesized IN(..) fragment from a Python list.

    For string items, single-quote and reject single quotes inside. Prefer
    parameterized queries when possible; this is a fallback for dynamic
    list sizes where DBAPI placeholders are awkward.
    """
    if not items:
        raise UnsafeIdentifierError("IN clause requires at least one item")
    if item_type == "int":
        return "(" + ",".join(str(int(x)) for x in items) + ")"
    if item_type == "str":
        out: list[str] = []
        for x in items:
            s = str(x)
            if "'" in s or "\\" in s or "\x00" in s:
                raise UnsafeIdentifierError(f"Unsafe string in IN clause: {s!r}")
            out.append(f"'{s}'")
        return "(" + ",".join(out) + ")"
    raise UnsafeIdentifierError(f"Unsupported IN item_type: {item_type}")


__all__ = [
    "UnsafeIdentifierError",
    "safe_ident",
    "safe_qualified",
    "safe_in_clause",
]
