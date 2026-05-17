# Model Card — Gemini HCC Suspect Miner

**Model:** `gemini-1.5-pro` (via Google Generative AI API)
**Application:** Surface candidate HCC codes from unstructured clinical notes for **human review** by a credentialed coder.
**Owner:** ML Engineering (kriya@raf.health)
**Version:** v2026.05 (post round-4 fixes)
**Status:** Production-eligible **with mandatory human-in-the-loop gate.** Not autonomous.

---

## 1. Intended use

- **Primary:** Identify ICD-10 / HCC suspects in a patient's clinical notes that may not yet be coded for the measurement year.
- **Secondary:** Pre-fill MEAT evidence sentences with character-level offsets so a coder reviewing a chart can verify provenance.

**Out of scope:** Diagnosis. Treatment. Billing without human review. Real-time CDS without coder oversight. Pediatric coding (V28 trained on adult MA population).

---

## 2. Architecture

```
clinical note (text, ≤ 32k tokens)
  → Gemini 1.5 Pro (few-shot prompt)
  → JSON {suspects: [{hcc_code, icd10, confidence, evidence_sentence, source_offset}]}
  → verbatim-substring guard (rejects hallucinated spans)
  → confidence floor (drop < 0.70)
  → V28 hierarchy trumping (remove dominated codes)
  → already-coded filter (don't re-surface)
  → write to raf_suspect_conditions (status='open')
```

File: `/Users/murali/Desktop/raf-intelligence/backend/app/services/nlp_suspect_extractor.py:67-68, 431-438`.

---

## 3. Training data

We do **not train** Gemini. We prompt it few-shot. Google's training data for `gemini-1.5-pro` is documented at https://ai.google.dev/gemini-api/docs/models/gemini. We use the public API with no fine-tuning.

Our few-shot examples (8 examples baked into the system prompt) are synthesized from public ICD-10 + V28 documentation and do not contain real patient PHI.

---

## 4. Safety controls (in-product)

| Control | File:line | What it does |
|---|---|---|
| Verbatim-substring guard | `nlp_suspect_extractor.py:404-411` | Drops any suspect whose `evidence_sentence` is not a literal substring of the source note. Hallucination floor. |
| Confidence floor at 0.70 | `nlp_suspect_extractor.py:67-68, 431-438` | Anything below this never reaches the coder. |
| Write-back gate at 0.85 | `raf_central.py:1396-1434` | NLP suspects under 0.85 cannot push to OpenEMR Problem List unless a credentialed user signs MEAT. |
| V28 hierarchy trump | `nlp_suspect_extractor.py:222-254` | CKD-stage-5 wins over CKD-stage-3 on the same patient — no junk cards. |
| Already-coded filter | `nlp_suspect_extractor.py:397-402` | Doesn't re-suggest an HCC already coded this measurement year. |
| Server-side MEAT gate | `raf_central.py:1281-1379` | Coder accept requires MEAT documented OR force-accept with ≥20-char reason + MRN re-entry. |
| Immutable audit chain | `immutable_audit.py:65-201` | Every AI suggestion + accept/decline is hash-chained for RADV defense. |

---

## 5. Known limitations

1. **Confidence is uncalibrated.** The model's self-reported confidence is a relative ranking signal, not a probability. We label bands "Strong / Moderate / Weak signal" (not %) in the coder UI for this reason. **Future work:** Platt-scaling once we have a labeled validation set of 5k+ chart pairs.

2. **English-only.** Spanish/Mandarin/Vietnamese notes will degrade. Templates exist for outreach in EN/ES, but the suspect miner is EN-only.

3. **Negation handling is via Chapman/Harkema ConText**, not a learned model. False positives can leak when negation triggers are paraphrased ("we ruled this out" vs "no evidence of").

4. **Family-history vs personal-history** — Apixio/Reveleer have known failures here. Our prompt rejects family history but doesn't catch all phrasings. Real-world recall is ~80% on this axis.

5. **Source attribution to encounter_id**: When OpenEMR returns a note without an explicit encounter id, we look up by (patient_id, note_date) — in RADV strict mode we skip rather than guess. (`meat_evidence_extractor.py:132-171`.)

6. **No bias audit yet.** We have not run a stratified evaluation on race/ethnicity/age/sex. Until we do, the suspect miner output **must** be reviewed by a coder before any write-back. The 0.85 write-back floor is the structural safeguard.

7. **CDS Hooks alert fatigue.** Per-patient-view cap is 3 cards + 24h dedup. Higher patient-volume specialties may still find this noisy. (`cds_hooks.py:281-336`.)

---

## 6. Performance metrics (internal validation)

| Metric | Value | Method | Sample |
|---|---|---|---|
| Precision @ confidence ≥ 0.85 | **~0.92** | Coder accept rate on first 500 suggestions | Demo tenant, 2026 H1 |
| Recall vs manual chart review | **~0.74** | 50 charts double-coded by 2 CRCs | Demo tenant |
| Hallucination rate | **0.0%** | Verbatim guard rejects all hallucinated spans | Tested on 100 synthetic injected hallucinations |
| Latency p50 | **~1.4 s** | Single-note extraction | Production |
| Latency p95 | **~3.8 s** | | Production |

**These numbers are from the demo tenant** and not from a real MA plan. Customer pilots will rebaseline.

---

## 7. Failure modes & customer playbook

| Symptom | Likely cause | Action |
|---|---|---|
| Suspect rate suddenly drops | Gemini rate-limit | Check `gemini_breaker` state at `/api/admin/circuits` |
| All suspects "Strong" confidence | Prompt template drift | Re-validate prompt against golden set |
| MEAT extraction empty | Note doesn't contain the suspect sentence verbatim | Verify chart in OpenEMR; if note has paraphrasing, model is correctly refusing |
| Coder reports "this patient doesn't have X" | False positive | Coder declines; suspect_feedback table captures the decline reason; model card updated quarterly |

---

## 8. Update + retraining policy

- **Prompt version:** stored in `app/services/nlp/prompts.py`; every change requires a PR + retest against 50-chart golden set.
- **Model version:** when Google releases a new Gemini, we A/B test on a staging tenant before flipping production.
- **Quarterly metric refresh:** SRE + Clinical Informatics run the validation set; results filed in `docs/enterprise/model-validation/`.

---

## 9. Compliance posture

- **HIPAA:** Gemini API is covered by Google's BAA. We do **not** send PHI without BAA in effect. Note text is sent over TLS 1.2+ with Google's standard data-residency controls.
- **FDA SaMD:** This system is **clinical decision support**, not a diagnostic device. It surfaces candidate codes for review; it does not diagnose, treat, or directly influence care without a credentialed user signing off. We rely on the 21st Century Cures Act §3060 exemption for non-device CDS.
- **HHS OIG fraud-and-abuse:** Force-accept attestation chain (≥20-char reason, MRN re-entry, immutable audit) provides the documentation trail an OIG/DOJ investigator would expect.

---

## 10. Citation

If quoting this model card in a customer doc: "RAF Intelligence Gemini Suspect Miner v2026.05, model card available at docs/enterprise/MODEL_CARD_GEMINI_SUSPECT_MINER.md."
