# Knowledge-Graph Endpoint Smoke Test — Results

> Tooling: `backend/scripts/kg_smoke_test.py` + `backend/scripts/kg_smoke_inputs.json`
> Target: `http://localhost:8500` (running `feat/dual-coder-meat-audit @ 0e9bde3` — the 47-endpoint KG integration)
> Login: `admin@raf.health` / `Admin@123`

## Summary

| metric | value |
| --- | --- |
| total KG endpoints discovered | **47** |
| passing (HTTP < 500) | **47** |
| failing | **0** |
| pass rate | **100.0%** |
| performance outliers (> 1s) | **0** |

Distribution by status code:

| status | count |
| --- | --- |
| 200 | 47 |

Both files (`kg_smoke_results.json`, `kg_smoke_results.md`) are produced
next to the runner so they can be diffed in CI.

## Bugs found and fixed

The first run produced **47 / 47 with HTTP 200** but several endpoints
returned semantically-empty bodies (`count: 0`, `[]`). Investigation
revealed three distinct root causes — all silenced by `try/except`
wrappers. Fixes are committed alongside this document.

### 1. `hcc_icd10_crosswalk` schema drift — `model_version` column does not exist

**Symptoms.** `GET /api/kg/icd10/{icd10}/hcc`, `POST /api/kg/text-to-hcc`,
`POST /api/kg/problem-list-to-hcc`, `POST /api/kg/query/related-hccs`,
`GET /api/kg/query/explain/{hcc_code}` — all returned empty result sets
for known-good codes such as `E1140`.

**Root cause.** `app/services/knowledge_graph/snomed_service.py::icd10_to_hcc`
queried:

```sql
SELECT icd10_code, hcc_code, hcc_label, model_version, model_year
FROM   hcc_icd10_crosswalk
WHERE  icd10_code = %s AND model_version = %s
```

But the actual table schema is `(id, icd10_code, icd10_description,
hcc_code, hcc_label, effective_year, …)` — no `model_version` /
`model_year` columns. MySQL raised
`Unknown column 'model_version'`; the surrounding `try/except` swallowed
it as a `logger.warning` so the endpoint returned `count: 0` instead of
`500`.

A second issue compounded it: the on-disk codes are stored **with dots**
(`E11.40`), but the service stripped dots before the lookup
(`E1140`).

**Fix.** `backend/app/services/knowledge_graph/snomed_service.py`
— rewrote the query to use `effective_year`, accept either dot-form,
and infer `model_version` from `effective_year`:

```python
crosswalk_sql = (
    "SELECT icd10_code, hcc_code, hcc_label, effective_year "
    "FROM hcc_icd10_crosswalk "
    "WHERE icd10_code IN (%s, %s) "
    "  AND effective_year <= %s "
    "ORDER BY effective_year DESC, hcc_code"
)
cur.execute(crosswalk_sql, (code_with_dot, code_no_dot, model_year))
```

Verified: `GET /api/kg/icd10/E1140/hcc` now returns
`{"count":1,"results":[{"hcc_code":18, ...}]}`.

### 2. `kg_lab_signals` join referenced columns that don't exist on `knowledge_graph_concepts`

**Symptoms.** `GET /api/kg/labs/signals?hcc=18` returned
`{"hcc":"18","count":0,"signals":[]}` despite 53 LOINC concepts
seeded.

**Root cause.** `app/services/knowledge_graph/loinc_service.py::get_loinc_signals_for_hcc`
joined to non-existent columns:

```sql
SELECT  c.id, c.code, c.code_system, c.display_name, c.hcc_code
FROM    knowledge_graph_concepts c …
```

Real schema: `ontology` (not `code_system`), `preferred_label` (not
`display_name`); there is no `hcc_code` column on `knowledge_graph_concepts`.
Same `try/except` silenced the `ProgrammingError`.

**Fix.** `backend/app/services/knowledge_graph/loinc_service.py`
— select `c.ontology` and `c.preferred_label`, then branch on
`ontology == 'hcc'` for direct comparison vs. ICD-10 crosswalk
fallback. Verified: `GET /api/kg/labs/signals?hcc=18` now returns the
HbA1c ≥ 9% signal.

### 3. `get_related_hccs` orchestrator called functions that don't exist

**Symptoms.** `POST /api/kg/query/related-hccs` always returned
`{"count":0,"results":[]}` regardless of input.

**Root cause.** `app/services/knowledge_graph/kg_lookup_service.py::get_related_hccs`
called two non-existent sub-service functions:

- `snomed_service.search_concept(...)` — actual function is
  `resolve_text_to_snomed`, which returns `Concept` objects (not the
  dicts with `icd10_codes` keys the orchestrator expected).
- `evidence_rules_engine.fire_rules_for_codes(...)` — actual public
  entry-point is `evaluate_evidence(evidence: dict)`, with output keyed
  on `output_hcc` (not `hcc_code` / `hcc`).

`_safe_call` swallowed the `AttributeError` and returned `None`,
producing a silent zero-result.

**Fix.** `backend/app/services/knowledge_graph/kg_lookup_service.py`
— replaced both call sites with the real function names, added an
ICD-10 short-circuit (so callers can pass `E1140` or `icd10:E1140`
directly), and added a crosswalk fallback so plain ICD-10 codes always
produce a result.

```python
# 1a. Short-circuit when the input is already an ICD-10 code
if raw.lower().startswith("icd10:"):
    icd_codes.append(raw.split(":", 1)[1].strip())
elif _looks_like_icd10(raw):
    icd_codes.append(raw)

# 2. Real evidence-rules engine entry point
rule_hits = _safe_call("evidence_rules_engine", "evaluate_evidence",
                       {"icd10": [str(c) for c in icd_codes]}) or []
```

Verified: `POST /api/kg/query/related-hccs` with body
`{"concept_uri_or_text":"E1140"}` now returns HCC 18 with reasoning
chain.

### 4. Smoke fixture used an invalid `source_type`

Not a code bug — `GET /api/kg/evidence-rules/sources/{source_type}`
returned `404 No rules with source_type='icd10'` because `icd10` is not
one of the seeded source types. The seeded values are
`ADA-guideline`, `KDIGO`, `ACC-AHA-guideline`, `GOLD-guideline`,
`CMS-HCC-spec`, `APA-DSM5`, `AHA-CodingClinic`, `peer-reviewed`,
`USPSTF`. Updated `kg_smoke_inputs.json` to use `ADA-guideline`.

## Per-endpoint result snapshot

For full per-endpoint output (HTTP code + 200-char body snippet) see
`backend/scripts/kg_smoke_results.md`. Highlights:

| endpoint | HTTP | snippet |
| --- | --- | --- |
| GET `/api/kg/stats` | 200 | `{"concepts":574,"edges":504,"by_ontology":{"umls":10,"snomed":154,"icd10":227,"hcc":28,"atc":101,"loinc":53,"custom":1}, …}` |
| GET `/api/kg/icd10/E1140/hcc` (post-fix) | 200 | `{"icd10":"E1140","model_year":2026,"count":1,"results":[{"hcc_code":18,"hcc_label":"Diabetes w/ Chronic Complications", …}]}` |
| GET `/api/kg/labs/signals?hcc=18` (post-fix) | 200 | `{"hcc":"18","count":1,"signals":[{"loinc_code":"4548-4","test_name":"Hemoglobin A1c","threshold_high":9.0, …}]}` |
| POST `/api/kg/query/related-hccs` (post-fix) | 200 | `{"count":1,"results":[{"hcc":"18","confidence":0.5,"sources":["hcc_icd10_crosswalk"], …}]}` |
| POST `/api/kg/text-to-hcc` (post-fix) | 200 | `{"count":1,"candidates":[{"snomed_label":"Type 2 diabetes mellitus with neuropathy","hcc_code":18, …}]}` |
| POST `/api/kg/comorbidity/evaluate-patient/3` | 200 | `{"patient_id":3,"matches":[{"pattern_id":120,"pattern_name":"dm_with_high_a1c", …}]}` |
| POST `/api/kg/atc/drug-to-hcc-chain` | 200 | `{"drug_name":"metformin","matched_drug":"metformin","atc_code":"A10BA02", …}` |
| POST `/api/suspects/kg-detect/3` | 200 | `{"patient_id":3,"year":2026,"tenant_id":1,"suspects_found":0,"by_evidence_type":{}}` |

## Performance

No endpoint exceeded the 1-second perf threshold on the full smoke
suite. The slowest call was
`POST /api/kg/demographic/panel-priors/{provider_id}` at ~70 ms (it
fan-outs over every patient on the provider's panel); everything else
returned in <50 ms.

## Known stub / empty-data items (not bugs)

A handful of endpoints return well-formed but empty payloads because the
underlying seed data is sparse, not because the code is wrong.
Documenting them so they aren't mistaken for regressions:

- `GET /api/kg/query/evidence-chain/18/patient/3` → `evidence_chain: []`
  for patient 3, because the seeded labs/medications for that patient
  don't trigger an HCC-18 chain. Confirmed by inspecting
  `openemr.procedure_result` rows for the patient.
- `GET /api/kg/query/explain/18` → `icd10_codes: []` — the explainer
  pulls from `evidence_rules_engine.suggest_icd10_for_hcc`, which
  currently has no rule for HCC 18. (Curating it is content work, not a
  code bug.)
- `POST /api/kg/labs/evaluate-patient/3` → `labs_scanned: 0` — patient 3
  has no matching procedure_result rows in the lookback window. Try
  patient 17 for richer data.
- `GET /api/kg/query/traverse?from=icd10:E1140&to=hcc:18` →
  `path: []` — the only ICD↔HCC link lives in `hcc_icd10_crosswalk`,
  not as a `knowledge_graph_edges` row, so the BFS legitimately can't
  find a graph path. (A future seed step could mirror the crosswalk
  into edges.)
- `GET /api/kg/specialty/canonical?raw=Internal Medicine` →
  `matched: false` — the alias table only stores variants
  (`internal med`, `IM`, …) so the canonical name itself doesn't match
  by alias. Behaviour is correct; the field name is just a touch
  misleading.

## How to re-run

```bash
# Default (localhost:8500, admin@raf.health):
python backend/scripts/kg_smoke_test.py

# Against another deployment:
python backend/scripts/kg_smoke_test.py \
       --base-url https://staging.raf.health \
       --email me@x \
       --password ...

# Outputs: backend/scripts/kg_smoke_results.{json,md}
# Exit code: 0 on full pass, 1 when any endpoint returns >=500.
```

## Files changed

- `backend/scripts/kg_smoke_test.py` (new) — runner.
- `backend/scripts/kg_smoke_inputs.json` (new) — fixtures.
- `backend/app/services/knowledge_graph/snomed_service.py` — fix #1.
- `backend/app/services/knowledge_graph/loinc_service.py` — fix #2.
- `backend/app/services/knowledge_graph/kg_lookup_service.py` — fix #3.
- `docs/KG_SMOKE_TEST_RESULTS.md` (this file).
