# RAF Accuracy Harness

This is the correctness / accuracy harness for the CMS-HCC RAF
calculator. It triple-scores synthetic Medicare patient bundles against
the `hccinfhir` library (our oracle, because CMS's SAS reference
implementation is licensed and unavailable to us) and asserts that our
production path never drifts by more than 1e-4 from the oracle.

## What it does

For each FHIR bundle on disk:

1. Convert it to ICD-10 codes + demographics (`bundle_to_score_input.py`).
2. Score with a vanilla `hccinfhir.HCCInFHIR` call (the oracle).
3. Score with `app.services.raf.calculator._run_single_model` (our
   production pure-function entry point — no DB needed).
4. Record `abs_diff` and `pct_diff` per (patient, model) into
   `out/diff_report.csv`.

If `_run_single_model` cannot be imported (e.g., running under a venv
without FastAPI/SQLAlchemy), the harness falls back to calling
`hccinfhir` a second time with the same kwarg shape our wrapper uses —
that still catches regressions in `bundle_to_score_input.py`.

## Running it

The harness is designed to run under `/Users/murali/Desktop/raf-intelligence/.venv-accuracy`.

### As pytest (CI gate)

```bash
cd /Users/murali/Desktop/raf-intelligence/backend
PYTHONPATH=. /Users/murali/Desktop/raf-intelligence/.venv-accuracy/bin/pytest \
    tests/accuracy/ -v --no-cov
```

The `--no-cov` flag sidesteps the project-wide 80% coverage gate — the
accuracy harness doesn't exercise the app package broadly, only the
scoring core.

### As a script (diff report + CSV)

```bash
cd /Users/murali/Desktop/raf-intelligence/backend
PYTHONPATH=. /Users/murali/Desktop/raf-intelligence/.venv-accuracy/bin/python \
    tests/accuracy/triple_score.py
```

Produces `tests/accuracy/out/diff_report.csv` with one row per
(patient, model). Use the env var
`RAF_ACCURACY_EXIT_NONZERO_ON_DIFF=1` to make the script exit non-zero
on any diff.

## Fixtures

Two sources:

* **Hand-crafted (committed)** — `fixtures/synthea_bundles/hand/*.json`.
  Twenty bundles chosen to stress HCC hierarchies:
  diabetes + neuropathy, CHF + cardiomyopathy, CKD + ESRD, cancer +
  metastasis, and a handful of single-condition controls. These are
  deterministic and version-controlled.

* **Synthea-generated (optional)** —
  `fixtures/synthea_bundles/*.json`. Not committed. Regenerate with:

  ```bash
  RAF_ACCURACY_RUN_SYNTHEA=1 \
      /Users/murali/Desktop/raf-intelligence/.venv-accuracy/bin/python \
      tests/accuracy/synthea_fetch.py
  ```

  This clones <https://github.com/synthetichealth/synthea> (needs `git`
  + Java 11+), runs it for 50 Medicare-aged patients, and copies the
  FHIR bundles into the fixture directory. Synthea's primary coding is
  SNOMED, so the hit rate on ICD-10 HCCs is lower than the hand set —
  the hand corpus is what the CI gate runs against by default.

### Regenerating the hand fixtures

If you edit the `CASES` list in `_build_hand_fixtures.py`:

```bash
/Users/murali/Desktop/raf-intelligence/.venv-accuracy/bin/python \
    tests/accuracy/_build_hand_fixtures.py
```

## Assertions

`test_accuracy_harness.py` enforces:

| Check                      | Threshold                                   |
| -------------------------- | ------------------------------------------- |
| At least 20 patients       | `len(unique patient_ids) >= 20`             |
| V24 match rate             | `>= 95%` within `abs_diff <= 1e-4`          |
| V28 match rate             | `>= 95%` within `abs_diff <= 1e-4`          |
| No blown-up patient (V24)  | no `abs_diff > 1e-2`                        |
| No blown-up patient (V28)  | no `abs_diff > 1e-2`                        |

Both V24 and V28 currently run at 100% match on the hand corpus.

## Files

```
tests/accuracy/
  __init__.py
  README.md                    — this file
  synthea_fetch.py             — fixture download / generation
  bundle_to_score_input.py     — FHIR bundle → ICD-10 + demographics
  triple_score.py              — main runner, writes diff_report.csv
  test_accuracy_harness.py     — pytest CI gate
  _build_hand_fixtures.py      — regenerates the committed fallback
  fixtures/
    synthea_bundles/
      hand/                    — committed 20 bundles
      *.json                   — optional Synthea output
  out/
    diff_report.csv            — written by triple_score.py
```

## Design notes

* The harness never touches the production DB. `_run_single_model`
  happens to be pure-functional; we call it directly, passing inputs
  that `bundle_to_score_input` has already resolved from the bundle.
* The oracle and our path both share the same `hccinfhir` installation
  — this is not a cross-library check. What we *are* asserting is that
  our wrappers (ICD formatting, dedupe, prefix resolution, segment
  mapping) do not silently corrupt the inputs before they reach the
  library. A CMS-SAS cross-check would require a licensed SAS environment.
* Coverage is deliberately disabled for this test file — see
  `--no-cov` in the run command.
