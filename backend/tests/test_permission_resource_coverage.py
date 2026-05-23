"""AST-driven check that every `require_permission(resource, action)` call
in app/routers/ uses a canonical resource string + action.

Catches the entire bug class where a developer typos the resource name —
the runtime ENUM/check returns False silently and the user gets 403 with
no clue why. This test makes the typo a CI failure instead.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from app.permission_resources import RESOURCE_NAMES, ACTIONS

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ROUTERS_DIR = REPO_ROOT / "app" / "routers"


def _iter_require_permission_calls() -> list[tuple[pathlib.Path, int, str, str | None]]:
    """Walk every .py file under app/routers/ and yield (file, lineno,
    resource, action) for every `require_permission(...)` literal call."""
    found: list[tuple[pathlib.Path, int, str, str | None]] = []
    for py in ROUTERS_DIR.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name)
                else None
            )
            if name != "require_permission":
                continue
            if not node.args:
                continue
            res_node = node.args[0]
            if not isinstance(res_node, ast.Constant) or not isinstance(res_node.value, str):
                # Skip dynamic values (very rare) — they can't be statically checked.
                continue
            action_value: str | None = None
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                if isinstance(node.args[1].value, str):
                    action_value = node.args[1].value
            found.append((py.relative_to(REPO_ROOT), node.lineno, res_node.value, action_value))
    return found


@pytest.mark.parametrize(
    "file,lineno,resource,action",
    _iter_require_permission_calls(),
    ids=lambda v: str(v),
)
def test_require_permission_uses_canonical_resource(
    file: pathlib.Path, lineno: int, resource: str, action: str | None,
) -> None:
    assert resource in RESOURCE_NAMES, (
        f"{file}:{lineno} — require_permission({resource!r}, ...) — "
        f"resource not in canonical RESOURCE_NAMES. "
        f"Add it to app/permission_resources.py or fix the typo."
    )
    if action is not None:
        assert action in ACTIONS, (
            f"{file}:{lineno} — require_permission({resource!r}, {action!r}) — "
            f"action not in canonical ACTIONS={sorted(ACTIONS)}."
        )


def test_require_permission_has_at_least_one_call() -> None:
    """Sanity: if this test sees zero calls, the AST walker is broken."""
    calls = _iter_require_permission_calls()
    assert len(calls) > 20, (
        f"Expected dozens of require_permission(...) call sites; "
        f"found {len(calls)}. AST walker likely broken."
    )
