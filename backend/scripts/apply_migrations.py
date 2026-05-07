"""Apply every SQL file in database/migrations/ in a deterministic order.

Idempotent: each migration is expected to be safe to re-run (the modern
ones use ``IF NOT EXISTS`` or wrap ALTER calls in stored-procedure
existence checks).  Numbered files (``001_*.sql`` … ``029_*.sql``) run
in numeric order first; un-numbered ``add_*.sql`` files run after in
alphabetical order — they generally extend the schema with optional
features (knowledge graph, recapture audit, etc.) that depend on the
numbered chain having already run.

Usage::
    docker exec raf-backend python /app/scripts/apply_migrations.py
    # or, on the host (uses RAF_DB_* env vars from the running shell):
    python backend/scripts/apply_migrations.py

Reports a per-file PASS / SKIP / FAIL summary.  Re-running on an
already-migrated database should produce all-PASS or all-SKIP.

Honors ``MIGRATIONS_DIR`` if set, defaults to ``database/migrations``
relative to the repo root.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Make ``app`` importable when run inside the backend container.
sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mysql.connector  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = Path(
    os.environ.get("MIGRATIONS_DIR")
    or REPO_ROOT / "database" / "migrations"
)


def _connect():
    return mysql.connector.connect(
        host=os.environ.get("RAF_DB_HOST", "localhost"),
        port=int(os.environ.get("RAF_DB_PORT", "3306")),
        user=os.environ.get("RAF_DB_USER", "root"),
        password=os.environ.get("RAF_DB_PASSWORD", "root"),
        database=os.environ.get("RAF_DB_NAME", "raf_intelligence"),
        autocommit=True,
        client_flags=[mysql.connector.ClientFlag.MULTI_STATEMENTS],
    )


def _ordered_migrations(directory: Path) -> list[Path]:
    """Numbered migrations first (numeric sort), then add_* alphabetically."""
    if not directory.is_dir():
        raise SystemExit(f"Migrations directory not found: {directory}")

    numbered: list[tuple[int, Path]] = []
    addons: list[Path] = []
    for p in directory.glob("*.sql"):
        m = re.match(r"^(\d+)_", p.name)
        if m:
            numbered.append((int(m.group(1)), p))
        else:
            addons.append(p)
    numbered.sort()
    addons.sort()
    return [p for _, p in numbered] + addons


def _classify_error(err: Exception) -> str:
    """Return a short tag the human can grep for in CI logs."""
    msg = str(err).lower()
    if "duplicate column name" in msg or "already exists" in msg:
        return "ALREADY_APPLIED"
    if "duplicate key name" in msg:
        return "ALREADY_APPLIED"
    if "incompatible" in msg and "foreign key" in msg:
        return "FK_TYPE_MISMATCH"
    if "doesn't exist" in msg:
        return "PREREQ_MISSING"
    return "OTHER"


def _strip_comments(sql: str) -> str:
    out = []
    in_block = False
    for line in sql.splitlines():
        s = line.strip()
        if in_block:
            if "*/" in s:
                in_block = False
                line = line[line.index("*/") + 2:]
            else:
                continue
        if s.startswith("/*"):
            if "*/" not in s:
                in_block = True
                continue
        if s.startswith("--") or not s:
            continue
        out.append(line)
    return "\n".join(out)


def _split_statements(sql: str) -> list[str]:
    """Naive ;-splitter that respects DELIMITER directives so stored
    procedures (used by our 028 / 029 migrations) survive."""
    sql = _strip_comments(sql)
    statements: list[str] = []
    delim = ";"
    buf: list[str] = []
    for line in sql.splitlines():
        s = line.strip()
        if s.upper().startswith("DELIMITER "):
            if buf:
                statements.append("\n".join(buf).strip())
                buf = []
            delim = s.split(None, 1)[1].strip()
            continue
        buf.append(line)
        if buf and buf[-1].rstrip().endswith(delim):
            joined = "\n".join(buf).strip()
            # Strip the trailing delimiter (whatever it is).
            if joined.endswith(delim):
                joined = joined[: -len(delim)].rstrip()
            if joined:
                statements.append(joined)
            buf = []
    if buf:
        tail = "\n".join(buf).strip()
        if tail:
            statements.append(tail)
    return statements


def apply_all(directory: Path = DEFAULT_DIR) -> int:
    files = _ordered_migrations(directory)
    if not files:
        print(f"No migrations found in {directory}")
        return 0

    conn = _connect()
    cur = conn.cursor()

    n_pass, n_skip, n_fail = 0, 0, 0
    failures: list[tuple[str, str]] = []

    for f in files:
        statements = _split_statements(f.read_text())
        file_failed = False
        file_skipped_only = True
        for stmt in statements:
            try:
                cur.execute(stmt)
                # Drain any result rows so the connection stays consistent.
                while cur.nextset():
                    pass
                file_skipped_only = False
            except mysql.connector.Error as e:
                tag = _classify_error(e)
                if tag == "ALREADY_APPLIED":
                    # Idempotent: re-applying an existing column / table /
                    # index is fine, just log once at the end.
                    continue
                short = str(e).splitlines()[0][:140]
                failures.append((f"{f.name}", f"[{tag}] {short}"))
                file_failed = True
                file_skipped_only = False
                break  # stop this file but keep going with the next migration

        if file_failed:
            print(f"  FAIL  {f.name}")
            n_fail += 1
        elif file_skipped_only:
            print(f"  SKIP  {f.name} (already applied)")
            n_skip += 1
        else:
            print(f"  PASS  {f.name}")
            n_pass += 1

    cur.close()
    conn.close()

    print(f"\nSummary: {n_pass} pass / {n_skip} skip / {n_fail} fail "
          f"({len(files)} total)")
    if failures:
        print("\nFailures:")
        for name, msg in failures:
            print(f"  {name}: {msg}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(apply_all())
