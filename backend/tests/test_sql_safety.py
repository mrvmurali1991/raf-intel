"""Tests for backend/app/services/sql_safety.py."""
from __future__ import annotations

import pytest

from app.services.sql_safety import (
    UnsafeIdentifierError,
    safe_ident,
    safe_in_clause,
    safe_qualified,
)


class TestSafeIdent:
    def test_accepts_simple_name(self) -> None:
        assert safe_ident("patients") == "patients"

    def test_accepts_underscores_and_digits(self) -> None:
        assert safe_ident("raf_patient_demographics_v2") == "raf_patient_demographics_v2"

    def test_rejects_drop_table(self) -> None:
        with pytest.raises(UnsafeIdentifierError):
            safe_ident("DROP TABLE x")

    def test_rejects_semicolon(self) -> None:
        with pytest.raises(UnsafeIdentifierError):
            safe_ident("patients; --")

    def test_rejects_quote(self) -> None:
        with pytest.raises(UnsafeIdentifierError):
            safe_ident("patients'")

    def test_rejects_dot_for_safe_ident(self) -> None:
        # safe_ident is strict — dotted needs safe_qualified
        with pytest.raises(UnsafeIdentifierError):
            safe_ident("schema.table")

    def test_rejects_empty(self) -> None:
        with pytest.raises(UnsafeIdentifierError):
            safe_ident("")

    def test_rejects_starts_with_digit(self) -> None:
        with pytest.raises(UnsafeIdentifierError):
            safe_ident("1abc")

    def test_rejects_non_string(self) -> None:
        with pytest.raises(UnsafeIdentifierError):
            safe_ident(None)  # type: ignore[arg-type]


class TestSafeQualified:
    def test_single_part(self) -> None:
        assert safe_qualified("patients") == "patients"

    def test_two_part(self) -> None:
        assert safe_qualified("raf_intelligence.patients") == "raf_intelligence.patients"

    def test_three_part(self) -> None:
        assert safe_qualified("raf_intelligence.patients.id") == "raf_intelligence.patients.id"

    def test_too_many_parts(self) -> None:
        with pytest.raises(UnsafeIdentifierError):
            safe_qualified("a.b.c.d")

    def test_one_bad_part(self) -> None:
        with pytest.raises(UnsafeIdentifierError):
            safe_qualified("schema.dr;op")


class TestSafeInClause:
    def test_int_list(self) -> None:
        assert safe_in_clause([1, 2, 3]) == "(1,2,3)"

    def test_empty_raises(self) -> None:
        with pytest.raises(UnsafeIdentifierError):
            safe_in_clause([])

    def test_int_with_string_coerce_fails(self) -> None:
        # 'malicious; DROP' cannot coerce to int → propagates ValueError
        with pytest.raises((UnsafeIdentifierError, ValueError)):
            safe_in_clause(["malicious; DROP"], "int")

    def test_str_with_single_quote_rejected(self) -> None:
        with pytest.raises(UnsafeIdentifierError):
            safe_in_clause(["a'b"], "str")

    def test_str_normal(self) -> None:
        assert safe_in_clause(["foo", "bar"], "str") == "('foo','bar')"

    def test_unknown_type(self) -> None:
        with pytest.raises(UnsafeIdentifierError):
            safe_in_clause([1, 2], "uuid")  # type: ignore[arg-type]
