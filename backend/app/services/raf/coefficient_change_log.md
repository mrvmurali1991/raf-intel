# Coefficient Change Log

Every change that alters the SHA-256 of `coefficients_manifest.json`
MUST land alongside a new entry in this file. CI enforces the
existence of an entry whose `hash` matches the current manifest hash.

## Entry format

Each entry is an H2 heading, followed by a fenced YAML block:

```yaml
hash: <64-char lowercase SHA-256 of coefficients_manifest.json>
payment_year: <YYYY>
effective_date: <YYYY-MM-DD>
cms_source: <URL or citation>
changed_by: <GitHub handle>
summary: <one-line change description>
```

Optional free-form commentary may follow the YAML block.

## Why this file exists

- An auditor three years from now needs to explain why a 2026 score
  was 1.067× normalized rather than 1.058×. Without a human-readable
  log, the only artifact is the git history — slow to read, easy to
  miss if file renames obscure the diff.
- CMS publishes new factors annually (Final Rate Announcement in
  April). This log is the bridge between "CMS published X on date Y"
  and "our manifest reflects that change from commit Z onward".

---

## 2026-04-17 — Initial coefficient manifest lock

```yaml
hash: 1967981c1e911b6c9581deec35ba9440149946e42a5100550b05aeed9cf58e64
payment_year: 2026
effective_date: 2026-01-01
cms_source: CMS CY2026 Final Rate Announcement — https://www.cms.gov/medicare/payment/medicare-advantage-rates-statistics/announcements-and-documents
changed_by: mrvmurali1991
summary: Initial baseline — V28 normalization 1.067, V24 1.153, V22 legacy 1.187, MACI 5.9%, PACE blend 90/10 legacy/V28, non-PACE 100% V28.
```

This is the baseline we ship with. Every subsequent CMS rate-notice
refresh adds a new entry above this one.
