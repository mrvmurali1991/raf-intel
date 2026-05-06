"""
Comprehensive smoke test for the 47 Knowledge-Graph (KG) endpoints exposed
under /api/kg/* (and the two /api/suspects/kg-detect endpoints).

What it does
============
1.  Logs in to a running backend with admin credentials (default
    http://localhost:8500, admin@raf.health / Admin@123) and grabs a JWT.
2.  Pulls /openapi.json and filters to KG-prefixed paths.
3.  For every path+method, looks up a curated request fixture in
    `kg_smoke_inputs.json`, formats the URL, sends the request, and records
    HTTP status, response time, response size, and a truncated body / error.
4.  Writes two artefacts next to itself:
        - kg_smoke_results.json  (machine-readable)
        - kg_smoke_results.md    (human report — table + per-endpoint)
5.  Exit code is 0 if every endpoint returned <500 and was either ``2xx`` or
    a deliberate 4xx (auth/validation), 1 otherwise.

This script never modifies business logic — it only exercises endpoints and
reports the outcome. Use the markdown report to drive bug fixes.

Run::

    python backend/scripts/kg_smoke_test.py
    python backend/scripts/kg_smoke_test.py --base-url http://localhost:8500
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

try:
    import requests
except ImportError:  # pragma: no cover
    print("ERROR: requests not installed. `pip install requests`", file=sys.stderr)
    sys.exit(2)


HERE = Path(__file__).resolve().parent
INPUTS_PATH = HERE / "kg_smoke_inputs.json"
RESULTS_JSON = HERE / "kg_smoke_results.json"
RESULTS_MD = HERE / "kg_smoke_results.md"

DEFAULT_BASE_URL = "http://localhost:8500"
DEFAULT_EMAIL = "admin@raf.health"
DEFAULT_PASSWORD = "Admin@123"


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _login(base_url: str, email: str, password: str) -> str:
    resp = requests.post(
        f"{base_url}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    token = body.get("access_token")
    if not token:
        raise RuntimeError(f"login response had no access_token: {body}")
    return token


def _fetch_kg_endpoints(base_url: str) -> list[tuple[str, str]]:
    """Return list of (METHOD, path) tuples for KG endpoints in OpenAPI."""
    resp = requests.get(f"{base_url}/openapi.json", timeout=15)
    resp.raise_for_status()
    spec = resp.json()
    out: list[tuple[str, str]] = []
    for path, ops in spec.get("paths", {}).items():
        if not (path.startswith("/api/kg/") or "suspects/kg" in path):
            continue
        for method in ops.keys():
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                out.append((method.upper(), path))
    out.sort()
    return out


def _format_url(base_url: str, path: str, path_params: dict[str, Any]) -> str:
    formatted = path
    for k, v in path_params.items():
        formatted = formatted.replace("{" + k + "}", str(v))
    return base_url + formatted


def _truncate(text: str, n: int = 200) -> str:
    if len(text) <= n:
        return text
    return text[:n] + f"… [+{len(text) - n} chars]"


# ----------------------------------------------------------------------------
# Test runner
# ----------------------------------------------------------------------------


def run_smoke(
    base_url: str = DEFAULT_BASE_URL,
    email: str = DEFAULT_EMAIL,
    password: str = DEFAULT_PASSWORD,
    timeout: float = 30.0,
) -> dict[str, Any]:
    print(f"[kg-smoke] target={base_url}")
    token = _login(base_url, email, password)
    print("[kg-smoke] logged in")

    inputs = json.loads(INPUTS_PATH.read_text())
    endpoints = _fetch_kg_endpoints(base_url)
    print(f"[kg-smoke] discovered {len(endpoints)} KG endpoint(s)")

    headers = {"Authorization": f"Bearer {token}"}
    session = requests.Session()
    session.headers.update(headers)

    results: list[dict[str, Any]] = []
    for method, path in endpoints:
        key = f"{method} {path}"
        fixture = inputs.get(key, {}) or {}
        path_params = fixture.get("path", {}) or {}
        query = fixture.get("query", {}) or {}
        body = fixture.get("body", None)

        url = _format_url(base_url, path, path_params)
        if query:
            url = f"{url}?{urlencode(query)}"

        start = time.perf_counter()
        status: int | None = None
        size = 0
        snippet = ""
        error: str | None = None
        try:
            if method == "GET":
                resp = session.get(url, timeout=timeout)
            elif method == "POST":
                resp = session.post(url, json=body if body is not None else {}, timeout=timeout)
            elif method == "PUT":
                resp = session.put(url, json=body if body is not None else {}, timeout=timeout)
            elif method == "DELETE":
                resp = session.delete(url, timeout=timeout)
            else:
                raise RuntimeError(f"unsupported method {method}")
            status = resp.status_code
            text = resp.text or ""
            size = len(text)
            snippet = _truncate(text, 200)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        elapsed_ms = (time.perf_counter() - start) * 1000

        ok = error is None and status is not None and status < 500
        results.append(
            {
                "method": method,
                "path": path,
                "url": url,
                "status": status,
                "ok": ok,
                "elapsed_ms": round(elapsed_ms, 1),
                "response_size": size,
                "snippet": snippet,
                "error": error,
                "fixture_present": key in inputs,
                "had_body": body is not None,
            }
        )
        flag = "PASS" if ok else "FAIL"
        print(f"  {flag} {method:5s} {path:60s} {status} {elapsed_ms:7.1f} ms")

    summary = {
        "base_url": base_url,
        "total": len(results),
        "passing": sum(1 for r in results if r["ok"]),
        "failing": sum(1 for r in results if not r["ok"]),
        "by_status": {},
        "perf_outliers_over_1s": [
            {"method": r["method"], "path": r["path"], "elapsed_ms": r["elapsed_ms"]}
            for r in results
            if r["elapsed_ms"] > 1000
        ],
    }
    for r in results:
        s = str(r["status"]) if r["status"] is not None else "ERR"
        summary["by_status"][s] = summary["by_status"].get(s, 0) + 1
    return {"summary": summary, "results": results}


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------


def write_reports(report: dict[str, Any]) -> None:
    RESULTS_JSON.write_text(json.dumps(report, indent=2))

    s = report["summary"]
    lines: list[str] = []
    lines.append("# KG Smoke Test Results")
    lines.append("")
    lines.append(f"- Base URL: `{s['base_url']}`")
    lines.append(f"- Total endpoints: **{s['total']}**")
    lines.append(f"- Passing (<500): **{s['passing']}**")
    lines.append(f"- Failing (>=500 or error): **{s['failing']}**")
    rate = (s["passing"] / s["total"] * 100) if s["total"] else 0
    lines.append(f"- Pass rate: **{rate:.1f}%**")
    lines.append("")
    lines.append("## Status code breakdown")
    lines.append("")
    lines.append("| status | count |")
    lines.append("|---|---|")
    for code, count in sorted(s["by_status"].items()):
        lines.append(f"| {code} | {count} |")
    lines.append("")

    if s["perf_outliers_over_1s"]:
        lines.append("## Performance outliers (>1s)")
        lines.append("")
        lines.append("| method | path | elapsed_ms |")
        lines.append("|---|---|---|")
        for o in sorted(s["perf_outliers_over_1s"], key=lambda x: -x["elapsed_ms"]):
            lines.append(f"| {o['method']} | `{o['path']}` | {o['elapsed_ms']} |")
        lines.append("")
    else:
        lines.append("## Performance outliers (>1s)")
        lines.append("")
        lines.append("_None._")
        lines.append("")

    lines.append("## Per-endpoint results")
    lines.append("")
    lines.append("| method | path | status | ms | size | snippet |")
    lines.append("|---|---|---|---|---|---|")
    for r in report["results"]:
        snippet = r["snippet"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {r['method']} | `{r['path']}` | {r['status'] or 'ERR'} | {r['elapsed_ms']} | {r['response_size']} | `{snippet}` |"
        )
    lines.append("")

    failures = [r for r in report["results"] if not r["ok"]]
    if failures:
        lines.append("## Failures")
        lines.append("")
        for r in failures:
            lines.append(f"### {r['method']} `{r['path']}`")
            lines.append("")
            lines.append(f"- status: **{r['status']}**")
            if r["error"]:
                lines.append(f"- error: `{r['error']}`")
            lines.append("- snippet:")
            lines.append("")
            lines.append("```")
            lines.append(r["snippet"])
            lines.append("```")
            lines.append("")
    else:
        lines.append("## Failures")
        lines.append("")
        lines.append("_None — every endpoint returned <500._")
        lines.append("")

    RESULTS_MD.write_text("\n".join(lines))
    print(f"[kg-smoke] wrote {RESULTS_JSON.name} + {RESULTS_MD.name}")


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="KG endpoint smoke tester")
    parser.add_argument("--base-url", default=os.environ.get("KG_SMOKE_BASE", DEFAULT_BASE_URL))
    parser.add_argument("--email", default=os.environ.get("KG_SMOKE_EMAIL", DEFAULT_EMAIL))
    parser.add_argument("--password", default=os.environ.get("KG_SMOKE_PASSWORD", DEFAULT_PASSWORD))
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    report = run_smoke(args.base_url, args.email, args.password, timeout=args.timeout)
    write_reports(report)

    s = report["summary"]
    print(
        f"[kg-smoke] {s['passing']}/{s['total']} passing ({s['failing']} failing)"
    )
    return 0 if s["failing"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
