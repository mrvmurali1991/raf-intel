<!--
  Default PR template. The sections below are always required.
  If this PR touches CMS coefficients, manifest values, frailty tables, or
  any file under backend/app/services/raf/, also fill in the
  "CMS coefficient-change gate" section. Reviewers must tick every box.
-->

## Summary

<!-- 1–3 sentences. Why this change, what it does, what it does not do. -->

## Test plan

- [ ] `backend/.venv/bin/python -m pytest -q` passes locally.
- [ ] `backend/.venv/bin/python scripts/verify_raf_drift.py` passes locally.
- [ ] For UI changes: walked the golden path + one edge case in the browser.

## CI checklist (required checks for merge)

- [ ] **lint** job green (`ruff check backend/` + `mypy backend/app --ignore-missing-imports`)
- [ ] **unit-test** job green (or `continue-on-error` acknowledged and tracked as issue)
- [ ] **security-scan** job green (`bandit` + `pip-audit` clean)
- [ ] **docker-build** job green (image builds + Trivy HIGH/CRITICAL = 0)

## PHI / Privacy

- [ ] No PHI appears in logs, error messages, or client-side state
- [ ] New API endpoints returning patient data are behind `require_auth` + tenant scope
- [ ] New PHI columns documented in the data dictionary

## Auth / Security

- [ ] New routes require authentication
- [ ] No secrets committed — all via environment variables / GitHub secrets
- [ ] `bandit -r backend/app/ -ll -ii` passes locally

## Database Migrations

- [ ] Migration is backward-compatible (additive, nullable or with DEFAULT)
- [ ] Rollback is safe without data loss
- [ ] No DROP COLUMN / TRUNCATE without explicit sign-off

## Risk / rollout

<!-- What breaks if this is wrong? Is there a feature flag? How do we roll back? -->

---

## CMS coefficient-change gate

> **Required whenever any of the following change:**
> - Files under `backend/app/services/raf/`
> - Any file named `*_manifest.json`, `*_coefficient_snapshot.json`, or
>   `frailty_adjuster.py`
> - The pinned `hccinfhir` version in `pyproject.toml` / `requirements.txt`
> - Anything under `backend/tests/fixtures/` that locks CMS values

**If this PR does NOT change any of those files, delete this section.**

### Source citation

- [ ] The CMS document this value comes from is linked below
      (Final Rate Announcement, Advance Notice, or Social Security Act §).
- [ ] The table/row/column number in that document is quoted in the diff
      (e.g. "Table I-7, V28 normalization factor row").
- [ ] The payment year the value applies to is stated explicitly in code
      or in the manifest.

**CMS source link(s):**

<!-- e.g. https://www.cms.gov/files/document/2026-announcement.pdf#page=42 -->

### Reproducibility

- [ ] If an `hccinfhir` version changed, `coefficients_manifest.json`
      `coefficient_source` field was updated to match.
- [ ] If a snapshot fixture changed, the regeneration command is in the
      PR description and `scripts/verify_raf_drift.py` still passes.
- [ ] Every changed numeric value has at least one test that locks it
      (see `tests/test_cms_factor_citations.py` for the pattern).

### Blast radius

- [ ] All reconciliation scenarios in
      `backend/tests/fixtures/raf_reconciliation_v28.json` still pass
      within the declared tolerance.
- [ ] SBOM emission (`provenance_sbom`) is unchanged or the new fields
      are backwards-compatible with consumers.
- [ ] A ledger entry describing the change is added to the PR body
      below (what CMS published, what we changed, what prior value was).

### Ledger

<!--
Example:

| Field                                    | Before | After | CMS source                      |
|------------------------------------------|--------|-------|---------------------------------|
| normalization_factors.v28.2026           | 1.058  | 1.067 | 2026 Final Rate Announcement    |
| maci_factors.v28.2026                    | 0.059  | 0.059 | (unchanged — SSA §1853)         |
-->
