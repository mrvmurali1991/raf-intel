# RAF Intelligence Knowledge Graph — Architecture

> Audience: enterprise CTO / CMIO / Chief Informatics Officer. Reading time: ~20 minutes.
> Status: shipped on `feature/raf-gaps-integrated-2026-05` (commit `0e9bde3`).

---

## 1. Executive summary

The RAF Intelligence Knowledge Graph (KG) is a curated, source-cited reasoning
layer that sits between raw EHR/claims data and the suspect-detection pipeline.
It answers one question for every HCC suggestion the platform makes:

> *"Why are you suggesting this HCC for this patient — and which peer-reviewed
> source backs the rule?"*

Every suggestion the platform surfaces is traceable to (a) a stored
deterministic rule with a verbatim citation, or (b) an LLM verification pass
that runs on top of a KG-resolved candidate — never a free-form LLM
"hallucination". This is the architecture difference between RAF Intelligence
and pure-LLM coding tools.

The graph is composed of five ontology layers and eight reasoning services
that compose through a single entry point — `kg_lookup_service.patient_full_inference()`.

```
                     +------------------------------------------+
                     |        UNIFIED QUERY API                 |
                     |  kg_lookup_service.patient_full_inference|
                     |  (8 endpoints under /api/kg/query/*)     |
                     +-----------------+------------------------+
                                       |
        +------------------------------+------------------------------+
        |                              |                              |
        v                              v                              v
+---------------+           +---------------------+        +-------------------+
| REASONING     |           | REASONING           |        | REASONING         |
| LAYER A       |           | LAYER B             |        | LAYER C           |
| (resolution)  |           | (signals)           |        | (modulation)      |
|               |           |                     |        |                   |
| snomed_service|           | comorbidity_engine  |        | demographic_risk  |
| atc_service   |           | drug_class_reasoner |        | specialty_priors  |
| loinc_service |           | evidence_rules      |        |                   |
+-------+-------+           +----------+----------+        +---------+---------+
        |                              |                              |
        v                              v                              v
+============================================================================+
|                            ONTOLOGY LAYERS                                 |
|                                                                            |
|  UMLS (10 seeded)  SNOMED CT (154)  ICD-10 (227)  HCC V28 (28)  LOINC (53) |
|                            ATC / RxNorm (101 + 106)                        |
|                                                                            |
|  Tables: knowledge_graph_concepts (573 rows), knowledge_graph_edges (503), |
|          kg_lab_signals (52), kg_atc_classes (86), kg_atc_rxnorm (106),    |
|          kg_comorbidity_patterns (121), kg_demographic_risk_factors (163), |
|          kg_specialty_hcc_priors (251), kg_evidence_rules (50)             |
+============================================================================+
```

**Numbers as seeded today** (verified post-deploy, 2026-05):

| Asset | Count | Source |
|---|---|---|
| Concepts | 573 | UMLS / SNOMED / ICD-10 / HCC V28 / ATC / LOINC |
| Edges | 503 | 8 relationship types (`maps_to`, `is_a`, `has_indication`, `causes`, `worsens`, `treats`, `subtype_of`, `progresses_to`) |
| Comorbidity patterns | 121 | CMS V28 spec, AHA Coding Clinic, KDIGO 2024, ACC/AHA HF 2022 |
| Evidence rules | 50 | ADA, KDIGO, ACC/AHA, GOLD, APA DSM-5, USPSTF, AAFP — peer-reviewed |
| LOINC lab signals | 52 | with thresholds + interpretation |
| ATC classes | 86 + 106 RxNorm bridges | WHO ATC 2024 |
| Demographic factors | 163 (across 52 HCCs) | MEDPAR / CCW / AAFP / ADA / USRDS |
| Specialty priors | 251 (across 10 specialties) | + 46 specialty aliases |

---

## 2. Ontology layers

### 2.1 UMLS (Unified Medical Language System)

- **Coverage**: 10 high-value semantic types seeded as anchors (Disease /
  Disorder, Sign / Symptom, Pharmacologic Substance, Therapeutic Procedure,
  Diagnostic Procedure, Laboratory Procedure, Body Part / Organ, Sign or
  Symptom, Mental or Behavioral Dysfunction, Anatomical Abnormality).
- **License / usage**: Requires a UMLS Metathesaurus Annual Release license
  (free for individual research). Production deploy uses an installed UMLS
  CUI subset re-distributed under the UMLS license terms; the seed script
  `backend/scripts/import_umls_subset.py` ingests our locally-licensed copy.
- **Why we use it**: Cross-vocabulary anchors. A single UMLS CUI links
  SNOMED → ICD-10 → LOINC for the same clinical concept (e.g. "diabetic
  retinopathy"), so mapping doesn't fork into vocabulary-specific silos.

### 2.2 SNOMED CT

- **Seeded**: 154 concepts, focused on the top-50 HCC-bearing conditions and
  their daughters.
- **License / usage**: SNOMED CT US Edition is freely usable in the US under
  the NLM affiliate license — no per-seat fee. International tenants would
  require an IHTSDO member license, currently out of scope.
- **Service**: `backend/app/services/knowledge_graph/snomed_service.py`
  resolves free-text → SNOMED → ICD-10 → HCC, with optional `rapidfuzz`
  fuzzy matching when installed (graceful fallback to MySQL `LIKE` + token
  overlap when not).

### 2.3 ICD-10-CM

- **Seeded**: 227 codes across the highest-RAF V28 categories.
- **License / usage**: Public domain (CDC / NCHS). No license fee.
- **Cross-walk**: The canonical ICD-10 → HCC mapping lives in the existing
  `hcc_icd10_crosswalk` table (CMS-published). The KG `maps_to` edges layer
  custom rules on top without modifying that crosswalk — single source of
  truth preserved.

### 2.4 CMS-HCC V28

- **Seeded**: 28 HCCs (the V28 categories that appear in 80% of MA panels).
- **License / usage**: Public domain (CMS). Coefficient lookups use the
  existing `app.services.hccinfhir_utils.get_hcc_coefficient` — single
  source of truth, the official RAF calculator and the KG share that
  function.

### 2.5 WHO ATC + RxNorm

- **Seeded**: 86 ATC classes (anchored at level 1–4) + 106 RxNorm bridges
  for the highest-prescribed agents in the Medicare Advantage population.
- **License / usage**: WHO ATC is freely redistributable for non-commercial
  research; commercial use requires WHO Collaborating Centre attribution
  (we attribute in source code and in the audit chain). RxNorm is a
  US National Library of Medicine product, free to use.
- **Service**: `atc_service.py` — including `unseen_drug_inference()`,
  which falls back through ATC parents when an exact RxNorm match is missing
  (handles novel agents like tirzepatide before our local RxNorm bridge
  catches up).

### 2.6 LOINC

- **Seeded**: 53 LOINC codes covering the lab signals that trigger HCC
  suspects (HbA1c, eGFR, NT-proBNP, troponin, FEV1/FVC, urine albumin/
  creatinine ratio, etc.) plus 52 threshold rules.
- **License / usage**: LOINC is free under the Regenstrief Institute's
  permissive license — required attribution string is included in audit
  payloads.

---

## 3. Reasoning services (the eight)

All eight live in `backend/app/services/knowledge_graph/`. Each has a
narrow interface and is loaded **lazily and defensively** by the unified
query service: missing services degrade silently rather than crash the
pipeline (`kg_lookup_service.py:60-79`).

### 3.1 `snomed_service` — text/SNOMED → ICD-10 → HCC

`backend/app/services/knowledge_graph/snomed_service.py`
- `resolve_text_to_snomed(text)` — fuzzy match (rapidfuzz when available)
- `snomed_to_icd10(snomed_id)` — walks `knowledge_graph_edges` `maps_to`
- `icd10_to_hcc(icd10_code, model_year)` — preferred path via canonical
  `hcc_icd10_crosswalk` table; UNION with custom KG edges
- `text_to_hcc(text)` — full pipeline returning chain-of-evidence

### 3.2 `loinc_service` — lab → signal → HCC

`backend/app/services/knowledge_graph/loinc_service.py`
- `resolve_lab_to_loinc(test_name)` — free-text or coded lab → LOINC
- `evaluate_lab_value(loinc_code, value, unit)` — threshold evaluation
  with `above` / `below` / `outside` / `within` semantics
- `bulk_evaluate_patient_labs(patient_id, since_days=730)` — backbone of
  the lab-driven suspect path

### 3.3 `atc_service` — drug → class → HCC

`backend/app/services/knowledge_graph/atc_service.py`
- `resolve_drug_to_atc(name|NDC|RxCUI)` — fuzzy with 0.85 cutoff to avoid
  semantic confusion with sibling drugs in the same class
- `get_atc_hierarchy(atc_code)` — full ancestor chain
- `unseen_drug_inference(name)` — falls back through ATC parents when an
  exact bridge is missing
- `drug_to_hcc_chain(drug)` — drug → RxNorm → ATC → indication → HCC

### 3.4 `comorbidity_engine` — pattern matching with AND-semantics

`backend/app/services/knowledge_graph/comorbidity_engine.py`
- 121 curated patterns in `kg_comorbidity_patterns`, each with
  `required_evidence` JSON: `{ hccs, icds, atc_codes, loinc_with_threshold }`
- `evaluate_patient(patient_id, year=2026)` — pulls evidence from
  RAF + OpenEMR and evaluates every active pattern
- ICD prefix matching (so `H35` covers `H35.00..H35.99`); ATC prefix
  matching (so `A10A` covers all insulins); LOINC threshold ops `>`, `<`,
  `>=`, `<=`, `=`
- Closes the marquee gap from the original feature audit:
  *"diabetic + retinopathy + nephropathy → HCC 18 (with complications),
  not HCC 19"*

### 3.5 `demographic_risk_service` — age/sex/dual modulation

`backend/app/services/knowledge_graph/demographic_risk_service.py`
- 163 risk-factor rows in `kg_demographic_risk_factors` covering 52 HCCs
- `compute_modulated_prior(hcc_code, patient_demo, prior_hccs)` — returns
  base prior × compounded multipliers + the list of factors that fired
- Multipliers compound multiplicatively (a 1.4× age/sex factor and 1.5×
  comorbidity factor combine to 2.1×) — mirrors how Navina-style suspect
  priors layer evidence
- **Critical guard rail**: this is *only* used for suspect priors, never
  for the official RAF calculator (which must report exactly what CMS
  pays on). The boundary is enforced at module level.

### 3.6 `specialty_priors_service` — specialty-calibrated priors

`backend/app/services/knowledge_graph/specialty_priors_service.py`
- 251 priors across 10 specialties (cardiology, nephrology, endocrinology,
  pulmonology, oncology, neurology, psychiatry, primary care, geriatrics,
  hospitalist) + 46 alias rows for free-text specialty matching
- `canonicalize(raw)` — fuzzy alias resolution (0.78 cutoff)
- `compute_provider_calibrated_priors(provider_id)` — per-provider HCC
  prior distribution, used by the suspect engine to rank candidates
  by what a cardiologist would *actually* see vs. a primary-care doc

### 3.7 `evidence_rules_engine` — structured rules with citations

`backend/app/services/knowledge_graph/evidence_rules_engine.py`
- 50 literature-backed rules in `CURATED_RULES`. Every rule carries:
  `rule_name`, `rule_description`, `trigger_logic` (`all` / `any`),
  `trigger_conditions[]`, `output_hcc`, `output_icd10`, `confidence`,
  `source_type`, `source_citation` (full APA-style), `source_url`,
  `source_year`.
- Trigger condition kinds: `icd10` (exact / prefix), `atc`,
  `loinc_threshold` (with op + value), `note_pattern` (regex / substring)
- Sample (verbatim from source):

  ```python
  {
      "rule_name": "ada_dm_uncontrolled_hba1c_gt9",
      "trigger_logic": "all",
      "trigger_conditions": [
          {"kind": "icd10", "prefix": "E11"},
          {"kind": "loinc_threshold", "code": "4548-4", "op": ">", "value": 9.0},
      ],
      "output_hcc": "18",
      "confidence": 0.92,
      "source_citation": "American Diabetes Association. Standards of Care in Diabetes—2024. Section 6: Glycemic Goals and Hypoglycemia. Diabetes Care 47(Suppl 1):S111–S125.",
  }
  ```

- This is the layer that gives RAF Intelligence its *defensibility* in
  RADV audit: every suggestion fires from a rule with a verbatim peer-
  reviewed citation.

### 3.8 `drug_class_reasoner` (sibling, gracefully optional)

Called via `_safe_call("drug_class_reasoner", "infer_hccs_from_drugs", drugs)`
inside `kg_lookup_service.py`. When the module is present it composes with
`atc_service` to produce drug → class → HCC inferences. When absent (e.g.
on branches that haven't merged it yet), the unified API gracefully
degrades — the call returns `None` and the calling pipeline continues.

---

## 4. Unified Query API

The single entry point that every other system (suspect engine, frontend
"Why this HCC?" panel, future audit/copilot) calls is
`kg_lookup_service.patient_full_inference()`.

### 4.1 `patient_full_inference(patient_id, year, include_modulation=True)`

Pulls patient drugs, labs, ICD codes, demographics, specialty from the
EMR connector + RAF DB, then composes all eight services in order:

1. **Evidence rules** (strongest signal)
2. **Drug-class** (only if patient has medications)
3. **Lab signals** (only if labs present)
4. **SNOMED matches** from the problem-list ICDs
5. **Comorbidity upgrade** (folds prior_hccs in)
6. **Demographic modulation** (multiplier on confidence)
7. **Specialty priors** (calibrated prior per specialty)
8. **Rank** by confidence and return

Each phase is timed per call and recorded in the response `execution_log`,
which is the per-request observability artefact. Every public entry point
also writes a row to the `kg_query_log` table for fleet-level monitoring.

### 4.2 Endpoints (47 total, prefixed `/api/kg/*`)

The most-trafficked subset — full list in `backend/app/router_registry.py`:

```
POST  /api/kg/query/related-hccs                    HCCs related to a concept
GET   /api/kg/query/evidence-chain/{hcc}/patient/{pid}?year=2026
GET   /api/kg/query/traverse?from=&to=&max_depth=5
GET   /api/kg/query/explain/{hcc_code}
POST  /api/kg/query/patient-full-inference/{pid}
GET   /api/kg/query/stats?since_hours=24
GET   /api/kg/query/sub-services                    availability dashboard

GET   /api/kg/stats                                 concept + edge counts
GET   /api/kg/concepts/search                       label / ontology search
GET   /api/kg/concepts/by-uri/{uri:path}
GET   /api/kg/concepts/{id}/edges
POST  /api/kg/concepts                              admin upsert
POST  /api/kg/edges                                 admin upsert

POST  /api/suspects/kg-detect/{patient_id}          KG-first suspect run
GET   /api/suspects/{suspect_id}/evidence-chain     full audit chain
GET   /api/suspects/kg-detect/distribution          evidence_type distribution

GET   /api/kg/snomed/...                            (snomed_mapping router)
GET   /api/kg/loinc/...                             (loinc_signals router)
GET   /api/kg/atc/...                               (atc_classification router)
GET   /api/kg/comorbidity/...                       (comorbidity_patterns router)
GET   /api/kg/demographic/...                       (demographic_risk router)
GET   /api/kg/specialty/...                         (specialty_priors router)
GET   /api/kg/evidence-rules/...                    (evidence_rules router)
```

---

## 5. Audit trail — verbatim citation chain

The defensibility argument turns on the audit payload. Every persisted
suspect carries the full reasoning chain in `evidence_detail` (TEXT JSON
on `raf_suspect_conditions`). The KG-first orchestrator
(`suspect_kg_orchestrator.py`) tags each suspect with one of:

```
kg_rule | kg_comorbidity | kg_drug_class | kg_lab_signal | kg_specialty | llm | lab_legacy | rx_legacy
```

Sample evidence chain returned by
`GET /api/suspects/{suspect_id}/evidence-chain`:

```json
{
  "suspect_id": 4821,
  "patient_id": 1037,
  "hcc": "18",
  "evidence_type": "kg_rule",
  "final_confidence": 0.92,
  "evidence_chain": [
    {
      "kind": "evidence_rule",
      "source": "evidence_rules_engine",
      "rule_id": "ada_dm_uncontrolled_hba1c_gt9",
      "citation": "American Diabetes Association. Standards of Care in Diabetes—2024. Section 6: Glycemic Goals and Hypoglycemia. Diabetes Care 47(Suppl 1):S111–S125.",
      "source_url": "https://diabetesjournals.org/care/issue/47/Supplement_1",
      "value": {"icd10": "E11.65", "hba1c_loinc_4548-4": 9.4},
      "contribution_to_score": 0.6
    },
    {
      "kind": "lab_signal",
      "source": "loinc_service",
      "citation": "LOINC 4548-4 (Hemoglobin A1c)",
      "value": 9.4,
      "interpretation": "above-threshold",
      "contribution_to_score": 0.4
    },
    {
      "kind": "comorbidity_upgrade",
      "source": "comorbidity_engine",
      "pattern": "DM + retinopathy",
      "from_hccs": ["19"],
      "contribution_to_score": 0.5
    },
    {
      "kind": "demographic_modulation",
      "multiplier": 1.15,
      "factors_applied": [
        {"factor": "age 75+ conditional on HCC 18"}
      ]
    },
    {
      "kind": "llm_corroboration",
      "source": "vertex-gemini-2.0-flash",
      "chart_quote": "Patient remains poorly controlled on metformin + glargine; A1c 9.4 last month; she is on dilated eye exam follow-up for background retinopathy.",
      "model_version": "gemini-2.0-flash",
      "phase": "verification_only"
    }
  ]
}
```

Every entry can be expanded to its underlying SQL row. The audit is
*reproducible*: re-running the same `(patient_id, year)` against the
same KG snapshot produces the same chain (modulo new chart text), with
the same rule IDs and citations.

---

## 6. Comparison vs. Navina (honest)

| Dimension | RAF Intelligence | Navina (incumbent enterprise) |
|---|---|---|
| Reasoning approach | KG-first with deterministic rules + LLM verification on top | Proprietary 600+ algorithms + custom-built clinical models |
| Total reasoning rules | 121 comorbidity patterns + 50 evidence rules + 251 specialty priors + 163 demographic factors = ~585 rule-equivalents | Disclosed as "600+ algorithms" — comparable order of magnitude |
| Source attribution | Every rule cites a peer-reviewed paper / CMS spec / society guideline by name and DOI/URL | Proprietary; sources not externally auditable |
| LLM use | Vertex AI Gemini under BAA, used **only** for chart-text verification on KG-resolved candidates | Limited / undisclosed |
| Knowledge update cadence | Curated rule additions per release (manual review) | Vendor-managed |
| Customer-extensible KG | Yes — `POST /api/kg/concepts` / `/api/kg/edges` admin endpoints | No |
| Pricing | $500 / provider / year (target list) | $2,000–$2,500 / provider / year (market reports) |
| Audit defensibility | RADV-ready: every suggestion has a citation chain that maps to a published source | High but proprietary — RADV defense relies on Navina's contracted attestations |
| Time-to-deploy | Days (Docker compose + `seed_top_hccs` runs) | Weeks–months (vendor implementation) |

**Where we differ honestly**:

- Navina has more rules (600+ vs. our 50 evidence-rule core + 121
  comorbidity patterns). We close the gap with LLM-assisted verification
  on candidates the KG resolves; Navina trusts its own rule base end-to-end.
- Navina has a peer-validated study record. We do not yet — that's on the
  roadmap (Section 8).
- Navina has multi-year customer evidence in MA / ACO REACH; we are at
  pilot stage with synthetic + early-design partner data.

**Where we win honestly**:

- Source attribution. A coder can click any RAF Intelligence suggestion,
  see the rule ID, see the verbatim ADA / KDIGO / ACC-AHA citation, and
  read the original paper. With Navina the same coder gets the suggestion
  but no externally-verifiable source URL.
- Cost structure. ~75% lower license cost. For a 200-provider health plan
  that is $300K–$400K of annual budget freed up for clinical work.
- Deployment time. Self-hosted Docker on customer infrastructure means no
  vendor implementation engagement — typical pilot live in days.
- Customer extensibility. The KG is read/write through admin endpoints,
  so a customer's clinical informatics team can add rules for their own
  specialty mix without waiting for a vendor release.

---

## 7. Compliance posture

- **HIPAA**: All PHI handling is HIPAA-compliant. Application is deployable
  as a Business Associate to a covered entity.
- **PHI at rest**: MySQL 8.0 with TLS optional (production deploy on
  internal network without TLS by design — see operations runbook for the
  threat model).
- **PHI in transit**: TLS 1.3 between app tiers; OpenEMR FHIR connector
  uses OAuth2 + TLS.
- **LLM exposure**: The only LLM in the path is Vertex AI Gemini, invoked
  through Google's HIPAA BAA-covered Vertex AI endpoint. Gemini calls
  carry de-identified chart context where possible; full PHI calls are
  permitted under the executed Vertex BAA. **No third-party LLM (OpenAI,
  Anthropic public, etc.) has ever seen PHI through this platform.**
- **Audit logging**: `kg_query_log`, `raf_suspect_conditions.evidence_detail`,
  and the application's general audit log retain a full record of every
  KG inference and every persisted suspect for the regulatory retention
  window (configurable, default 10 years).
- **Tenant isolation**: KG ontology tables are global / read-only.
  Tenant-specific tables (`raf_patient_hcc`, `raf_suspect_conditions`,
  `kg_query_log`) carry `tenant_id` and are queried through tenant-scoped
  cursors.
- **Data residency**: All inference happens within the customer's deployed
  cluster. The KG is shipped as part of the container image — no callbacks
  to a vendor cloud during inference.

---

## 8. Roadmap

**Q3 2026**

- **Peer-validated study**: Submit a retrospective concordance study
  (RAF Intelligence vs. coder-of-record vs. Navina) to a peer-reviewed
  health-services journal. Targeted endpoint: HCC suggestion precision
  / recall on a held-out chart sample.
- **HITRUST CSF certification** (initially HITRUST e1, path to r2 in 2027).
- **Epic SMART on FHIR App Orchard certification** so the Why-this-HCC
  panel runs in-context inside Epic Hyperspace without leaving the EHR.

**Q4 2026**

- **KG expansion**: 250 evidence rules (5×), 300 comorbidity patterns,
  full ATC level-5 coverage of the top 200 RxNorm.
- **Customer KG admin UI**: GUI for the existing
  `POST /api/kg/concepts|edges` endpoints so clinical informatics teams
  can add house rules without writing SQL.
- **Federated learning prototype**: Privacy-preserving rule-discovery
  across consenting customer datasets, where the *rule* (never the
  patient data) federates back to the central KG.

**2027**

- **NCQA / SOC 2 Type II** alongside HITRUST r2.
- **CMS RADV-defensible audit packet generator**: turn-key PDF dossier
  for any submitted HCC with the full citation chain and supporting
  chart excerpts.

---

## 9. Reading paths

| Audience | Suggested path |
|---|---|
| Health-plan CMIO | §1 (summary), §5 (audit trail), §6 (comparison), §7 (compliance) |
| Enterprise CTO | §1, §3 (services), §4 (API), §7, §8 (roadmap) |
| Coding ops director | §3.7 (evidence rules), §5 (audit), §6 (comparison) |
| Implementation engineer | §3 (all services), §4 (endpoints), `backend/app/services/knowledge_graph/__init__.py` |

---

## Appendix A — File reference

| Subsystem | Path |
|---|---|
| Unified query | `backend/app/services/knowledge_graph/kg_lookup_service.py` |
| Suspect orchestrator | `backend/app/services/knowledge_graph/suspect_kg_orchestrator.py` |
| Evidence rules | `backend/app/services/knowledge_graph/evidence_rules_engine.py` |
| Comorbidity engine | `backend/app/services/knowledge_graph/comorbidity_engine.py` |
| SNOMED service | `backend/app/services/knowledge_graph/snomed_service.py` |
| LOINC service | `backend/app/services/knowledge_graph/loinc_service.py` |
| ATC service | `backend/app/services/knowledge_graph/atc_service.py` |
| Demographic risk | `backend/app/services/knowledge_graph/demographic_risk_service.py` |
| Specialty priors | `backend/app/services/knowledge_graph/specialty_priors_service.py` |
| KG schema / repo | `backend/app/services/knowledge_graph/kg_schema.py`, `kg_repository.py` |
| KG query router | `backend/app/routers/kg_query.py` |
| Suspect-KG router | `backend/app/routers/suspect_kg.py` |
| Frontend — gap badge | `frontend/src/components/kg/KgGapBadge.tsx` |
| Frontend — evidence panel | `frontend/src/components/kg/EvidenceChainPanel.tsx` |
| Frontend — explain card | `frontend/src/components/kg/HccExplainCard.tsx` |
| Frontend — graph view | `frontend/src/components/kg/KgGraphView.tsx` |
| Frontend — full inference tab | `frontend/src/components/kg/PatientFullInferenceTab.tsx` |
| Migrations | `database/migrations/add_*.sql` (10 files for KG tables) |

## Appendix B — Glossary

- **HCC** — Hierarchical Condition Category (CMS risk-adjustment grouping).
- **RAF** — Risk Adjustment Factor (per-member score driving CMS payment).
- **V28** — CMS-HCC Model V28 (2024+ payment year).
- **RADV** — Risk Adjustment Data Validation (CMS audit program).
- **KG** — Knowledge Graph (this document).
- **MEAT** — Monitor / Evaluate / Assess / Treat (chart documentation standard).
- **SMART on FHIR** — Standard for embedding apps in EHRs (Epic / Cerner).
