/**
 * fixtures.ts — Known stable test data constants.
 *
 * These IDs and codes correspond to the seeded demo dataset that ships
 * with every fresh RAF Intelligence deployment (9 OpenEMR patients).
 *
 * Mutate only when the seed data itself changes.
 */

// ---------------------------------------------------------------------------
// Patient IDs (OpenEMR external IDs are 1-9; internal DB IDs may differ)
// ---------------------------------------------------------------------------

/** Patient guaranteed to have at least one open suspect. */
export const PATIENT_WITH_SUSPECTS = 1;

/** Patient used for HEDIS gap cross-link tests (patient_id=3 in spec). */
export const HEDIS_CROSS_LINK_PATIENT_ID = 3;

/** Patient with a known RADV-eligible encounter. */
export const RADV_PATIENT_ID = 2;

// ---------------------------------------------------------------------------
// HCC codes present in seed data
// ---------------------------------------------------------------------------

/** HCC 19 — Diabetes without Complication */
export const HCC_DIABETES = "HCC19";

/** HCC 85 — Congestive Heart Failure */
export const HCC_CHF = "HCC85";

/** HCC 96 — Specified Heart Arrhythmias */
export const HCC_ARRHYTHMIA = "HCC96";

// ---------------------------------------------------------------------------
// HEDIS measure codes expected in seed data
// ---------------------------------------------------------------------------

/** Breast Cancer Screening (BCS) */
export const HEDIS_BCS = "BCS";

/** Colorectal Cancer Screening (COL) */
export const HEDIS_COL = "COL";

/** Controlling High Blood Pressure (CBP) */
export const HEDIS_CBP = "CBP";

// ---------------------------------------------------------------------------
// RADV sample parameters
// ---------------------------------------------------------------------------

export const RADV_SAMPLE_SIZE = 201;
export const RADV_SAMPLE_METHOD = "stratified_raf_decile";
export const RADV_PAYMENT_YEAR = 2025;

// ---------------------------------------------------------------------------
// Document ingestion
// ---------------------------------------------------------------------------

/** Number of source cards expected on /admin/document-ingestion. */
export const EXPECTED_SOURCE_CARDS = 9;

/** Source name that must appear after clicking the OpenEMR card. */
export const OPENEMR_SOURCE_NAME = "openemr";

// ---------------------------------------------------------------------------
// API base URL (runtime override via env var for CI)
// ---------------------------------------------------------------------------

export const API_BASE = process.env.E2E_BASE_URL ?? "https://raf.comercioit.com";
