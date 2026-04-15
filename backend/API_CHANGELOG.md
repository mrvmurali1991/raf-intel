# RAF Intelligence API Changelog

This document records all notable API changes including additions, deprecations,
and breaking changes. The API follows [Semantic Versioning](https://semver.org/)
for its version number and [Keep a Changelog](https://keepachangelog.com/) conventions
for this file.

---

## Versioning Policy

### URL Structure

| Pattern | Description |
|---------|-------------|
| `/api/v1/<resource>` | Versioned URL — recommended for all new integrations |
| `/api/<resource>` | Unversioned alias — backward-compatible, tracks v1 |

Both URL forms resolve to identical handlers. The `/api/` unversioned alias
exists exclusively for backward compatibility and will never be removed.

### Version Header

Every response carries `X-API-Version: v1`. Consumers should read this header
to confirm which version they are interacting with.

### Breaking Change Policy

A **breaking change** is any API modification that requires existing, correctly
written client code to change in order to continue working. Examples:

- Removing an endpoint
- Renaming or removing a field in a response body
- Changing a field type (e.g. `string` -> `integer`)
- Changing HTTP method or URL path of an existing endpoint
- Changing required authentication scopes
- Altering pagination behaviour in a non-additive way

Breaking changes ALWAYS trigger a new major version (v1 -> v2). They are
NEVER introduced into an existing version.

### Deprecation Timeline

When an endpoint or field is superseded by a newer version:

1. The deprecated path is listed in `_DEPRECATED_V1_PATHS` in `backend/app/main.py`.
2. All responses from that path include `Deprecation: true` and `Sunset: <date>`.
3. The `Link` header points to the successor resource.
4. Deprecated endpoints remain fully functional for a **minimum of 12 months**
   after the deprecation notice is published.
5. The sunset date is never moved forward (only backward, in emergencies with
   advance notice).

---

## [v1.0.0] — 2026-04-14

### Initial stable release

This is the first formally versioned release of the RAF Intelligence API.
All 194 endpoints across 40+ routers are included in v1.

#### Infrastructure

- URL-based versioning introduced: `/api/v1/` prefix now routes to all v1 handlers
  via transparent path rewriting. `/api/` remains as the unversioned alias.
- `X-API-Version: v1` header added to every API response.
- `Deprecation`, `Sunset`, and `Link` response headers implemented for future
  endpoint deprecation signalling (no endpoints are deprecated in v1.0.0).

#### Response Envelope

All endpoints now document and support the standardised `APIResponse` envelope:

```json
{
  "success": true | false,
  "data":    <payload> | null,
  "error":   null | { "code": "...", "message": "...", "details": [...] },
  "meta":    null | { "page": 1, "limit": 20, "total": 157, "request_id": "..." }
}
```

New schema modules:

| Module | Purpose |
|--------|---------|
| `app.schemas.response` | `APIResponse`, `ErrorDetail`, `MetaInfo`, `ok()`, `err()` |
| `app.schemas.pagination` | `PaginationParams`, `PaginatedResponse`, `cursor_meta()` |

#### Validation Errors

`422 Unprocessable Entity` responses now return structured field-level errors
instead of a generic message:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed. Check the 'details' list for field-level errors.",
    "details": [
      { "field": "dob", "message": "must be a valid ISO-8601 date", "value": "not-a-date" }
    ]
  },
  "meta": { "request_id": "a1b2c3d4-..." }
}
```

#### OpenAPI / Swagger

- OpenAPI `info.version` updated to `1.0.0` (was `2.0.0` — that was the
  application version, now correctly separated from the API spec version).
- `termsOfService`, full `contact.url`, and `license_info` added to the spec.
- Extended `description` with versioning reference table, response envelope
  documentation, authentication flow summary, and rate limiting guidance.

#### Endpoints (v1 surface — no changes from pre-release)

| Tag | Endpoints |
|-----|-----------|
| auth | Login, logout, refresh, register, me, password reset |
| patients | List, get, import, encounters, medications, diagnoses, procedures |
| raf | Score calculation, history, crosswalk, payment analysis |
| analysis | Clinical note NLP, HCC extraction, MEAT documentation |
| suspects | Suspect conditions CRUD and workflow |
| attestations | Provider sign-off for HCC suspects |
| chart-chase | Chart request management |
| documents | Upload, Gemini Vision analysis |
| ccda | C-CDA ingestion, parsing, export |
| claims | 837P/837I/CSV ingestion |
| fhir | FHIR R4 patient sync, condition, encounter resources |
| smart_fhir | SMART on FHIR EHR-launch and standalone-launch |
| providers | Management, scorecards |
| submissions | CMS RAPS/EDPS submission management |
| prospective | Prospective RAF management |
| awv | Annual Wellness Visit scheduling and results |
| quality | HEDIS measures and STARS |
| benchmarks | Performance benchmarking |
| care_gaps | Care gap closure workflow |
| recapture_gaps | Prior-year HCC recapture analysis |
| cohorts | Dynamic patient population management |
| adt | HL7v2 MLLP ADT feed |
| webhooks | Event subscriptions |
| notifications | Email configuration |
| direct_messaging | S/MIME secure provider-to-provider messaging |
| jobs | Background job management |
| pipeline | Pipeline run history and status |
| reports | Analytics and reporting |
| audit | HIPAA compliance audit packages |
| radv | RADV audit trail and MEAT compliance |
| bi_export | Tableau/PowerBI/Looker/Metabase export |
| worklist | Coder and provider worklists |
| realtime | SSE/WebSocket dashboard streams |
| health | Health checks and system status |
| icd10 | ICD-10-CM code lookup |
| admin | Data retention and purge |

---

## Future Roadmap

### Planned for v1.1.0

- Apply `PaginatedResponse` envelope to patient list, audit log, and pipeline
  run endpoints (additive only — existing fields preserved).
- Add `Link` header with `rel=next` and `rel=prev` for paginated list endpoints.
- Expand error codes to cover domain-specific cases (e.g. `RAF_CALCULATION_FAILED`).

### Planned for v2.0.0 (no earlier than 2027-Q4)

- GraphQL endpoint alongside REST for complex nested queries.
- Async job submission pattern for long-running operations (RAF batch calc,
  CCDA bulk ingestion) replacing synchronous blocking calls.
- Cursor-based pagination replacing offset pagination for high-volume lists.
- Consolidated FHIR R4 resource endpoints conforming to US Core IG.

---

## Support

- Email: support@raf.health
- Status: https://status.raf.health
- API reference: `/docs` (development/demo environments only)
