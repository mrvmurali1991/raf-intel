/**
 * page-help.ts — Contextual help content keyed by route pathname.
 *
 * Each entry provides:
 *   - purpose: one-sentence overview shown as the panel subtitle
 *   - sections: array of { heading, body } displayed as accordion-style blocks
 *
 * Used by HelpPanel and the HelpButton mounted in every page header.
 */

export interface HelpSection {
  heading: string;
  body: string;
}

export interface PageHelp {
  title: string;
  purpose: string;
  sections: HelpSection[];
}

export const PAGE_HELP: Record<string, PageHelp> = {
  "/": {
    title: "Dashboard",
    purpose: "Population Health Intelligence — your real-time overview of RAF score performance, revenue opportunity, and care-gap status across your entire panel.",
    sections: [
      {
        heading: "Purpose",
        body: "The Dashboard aggregates every key metric in one place so care teams and administrators can spot trends, identify high-risk patients, and act before the payment year closes.",
      },
      {
        heading: "Key Terms",
        body: "RAF Score (Risk Adjustment Factor): a numerical weight CMS assigns to a patient based on their documented chronic conditions; higher scores = higher capitation revenue.\n\nHCC (Hierarchical Condition Category): CMS groupings of ICD-10 diagnoses used in the RAF model; e.g. HCC 18 = Diabetes with Chronic Complications.\n\nRevenue Opportunity: estimated additional annual revenue if all open care gaps are addressed before the submission deadline.\n\nSuspects: AI-flagged conditions that are likely present but not yet coded this payment year.",
      },
      {
        heading: "How to Use",
        body: "1. Check the KPI strip at the top — RAF Score, Revenue Opportunity, Open Gaps, and Suspects give you a daily pulse.\n2. Scroll to the top-opportunity list to see which patients represent the highest uncaptured revenue.\n3. Click any patient row to open their RAF Central panel for a full clinical summary.\n4. Use the Year selector (top-right) to compare the current and prior payment years.\n5. The Suspects tile links directly to the AI review queue.",
      },
      {
        heading: "Common Questions",
        body: "Q: Why is my RAF score different from last year?\nA: RAF scores reset annually; every chronic condition must be re-documented each payment year. Conditions coded last year that were not re-coded this year reduce the score.\n\nQ: What does the Revenue Opportunity number mean?\nA: It is the estimated CMS capitation revenue recoverable if every open HCC gap is closed before the payment year ends — calculated at ~$11,015 per full RAF point.\n\nQ: Why do some patients show as 'Suspects' but not 'Gaps'?\nA: Suspects are AI-inferred conditions not yet documented; Gaps are historically coded conditions from prior years that have not yet been re-coded in the current year.",
      },
    ],
  },

  "/worklist": {
    title: "Worklist",
    purpose: "Daily prioritized patient queue — the patients your team should contact or review today, ranked by RAF capture urgency.",
    sections: [
      {
        heading: "Purpose",
        body: "The Worklist surfaces the highest-priority patients each day so coders, care coordinators, and physicians focus their limited time on the encounters that will have the greatest revenue and quality impact before the payment year closes.",
      },
      {
        heading: "Key Terms",
        body: "Priority Score: composite rank based on open HCC gap count, revenue impact, days until the payment year deadline, and AWV (Annual Wellness Visit) status.\n\nAWV (Annual Wellness Visit): a CMS-covered visit that satisfies many quality measures and is the ideal opportunity to re-document chronic conditions.\n\nGap: a chronic condition coded in a prior year that has not yet appeared in a claim or note this payment year.\n\nBulk Close: send multiple HCC gaps to attestation in a single action.",
      },
      {
        heading: "How to Use",
        body: "1. Review the summary strip — total patients, open gaps, and estimated revenue at risk.\n2. Click a patient card to expand their gap details.\n3. Check the checkbox on one or more cards to select patients, then use the bulk action bar to schedule AWVs or send to attestation.\n4. Use Shift+Click to select a range; Cmd/Ctrl+A to select all visible patients.\n5. The provider filter pills (admin/manager only) let you scope the queue to a single provider.",
      },
      {
        heading: "Common Questions",
        body: "Q: Why is the list different every day?\nA: Patients are re-ranked nightly based on updated claims, approaching deadlines, and new suspect signals.\n\nQ: What does 'Overdue AWV' mean on a card?\nA: The patient's last Annual Wellness Visit was more than 12 months ago — scheduling one now allows documentation of all chronic conditions in one encounter.\n\nQ: Can I assign patients to a specific provider?\nA: Not directly from the Worklist — use the outreach campaign tools or the patient record to assign follow-up.",
      },
    ],
  },

  "/recapture": {
    title: "Recapture Gaps",
    purpose: "Find prior-year HCCs not yet billed this year — chronic conditions that must be re-coded annually to maintain RAF score accuracy and associated revenue.",
    sections: [
      {
        heading: "Purpose",
        body: "Medicare Advantage plans lose revenue every year when chronic conditions coded in the prior year are not re-documented in the current payment year. Recapture Gaps identifies every such condition across your panel so coders and clinicians can close them before the CMS submission deadline.",
      },
      {
        heading: "Key Terms",
        body: "Recapture Gap: a condition mapped to an HCC that appeared in a claim or problem list last year but has no matching code in any current-year claim or encounter note.\n\nOnset Date: when the condition was first documented — used to distinguish chronic from transient conditions.\n\nICD-10 Code: the clinical classification code used in claims; e.g. E11.65 = Type 2 Diabetes with Hyperglycemia.\n\nRevenue at Risk: the total estimated CMS capitation revenue that will be lost if these gaps remain unclosed at year-end.",
      },
      {
        heading: "How to Use",
        body: "1. Select the measurement year from the top-right selector.\n2. Review the summary cards — total gaps, patients affected, and revenue at risk.\n3. Browse the gap table; use the search box to filter by patient name or condition.\n4. Click a patient row to open their RAF Central panel and add a note or attestation.\n5. Export the full list as CSV for batch coding workflows.",
      },
      {
        heading: "Common Questions",
        body: "Q: Why does a gap appear even though the condition is on the problem list?\nA: CMS requires a diagnosis code on a claim or qualifying encounter note dated within the current payment year — a problem-list entry alone does not satisfy the requirement.\n\nQ: What counts as 'closing' a recapture gap?\nA: A claim containing the matching ICD-10 code with a service date in the current payment year, or an attestation approved within the platform.\n\nQ: How often is the gap list refreshed?\nA: Nightly, after claims and encounter data are ingested from your connected EMR.",
      },
    ],
  },

  "/suspects": {
    title: "Suspect HCCs",
    purpose: "AI-flagged HCC diagnoses awaiting coder review — conditions the model believes are clinically present but not yet coded this payment year.",
    sections: [
      {
        heading: "Purpose",
        body: "The Suspects queue surfaces conditions the AI model infers from clinical notes, lab results, medication lists, and imaging reports. Coders review each suspect and either accept it (triggering an outreach to the ordering physician) or dismiss it (with a reason code for audit trail).",
      },
      {
        heading: "Key Terms",
        body: "Suspect: an AI-inferred HCC condition that has evidence in the clinical record but no matching claim code in the current payment year.\n\nConfidence: model probability (0–100%) that the condition is clinically present; higher confidence suspects should be reviewed first.\n\nEvidence Type: the clinical signal that triggered the suspect — e.g. Lab Result, Medication, Clinical Note, Imaging.\n\nMEAT: Documentation standard requiring that each HCC condition be supported by evidence of Monitoring, Evaluation, Assessment, or Treatment.",
      },
      {
        heading: "How to Use",
        body: "1. Use the status tabs (Pending / Accepted / Dismissed) to focus your queue.\n2. Click a suspect row to expand the evidence panel showing the source note or lab result.\n3. Press A to accept the focused suspect or D to dismiss — keyboard shortcuts speed up batch review.\n4. Accepted suspects are queued for physician attestation or coder documentation.\n5. Use the filter bar to scope by HCC category, evidence type, or confidence threshold.",
      },
      {
        heading: "Common Questions",
        body: "Q: What happens after I accept a suspect?\nA: An outreach task is created for the responsible provider to document or confirm the diagnosis in an encounter note or claim within the current payment year.\n\nQ: Can I bulk-accept suspects?\nA: Yes — use the checkbox column to select multiple rows, then click the bulk-accept button in the toolbar.\n\nQ: What does the AI use to generate suspects?\nA: The model analyzes ICD-10 codes from prior claims, active medications, lab values, and de-identified clinical note text using a CMS-HCC mapping layer.",
      },
    ],
  },

  "/v28-impact": {
    title: "V28 Impact",
    purpose: "Compare CMS-HCC V24 vs V28 portfolio impact — understand which patients gain or lose RAF score under the new model and quantify the revenue effect.",
    sections: [
      {
        heading: "Purpose",
        body: "CMS phased in the V28 HCC model starting in 2024, replacing V24. V28 dropped ~2,000 ICD-10 codes and added new HCC groupings. This page shows how the transition affects your panel's total RAF score and associated revenue.",
      },
      {
        heading: "Key Terms",
        body: "V24: the legacy CMS-HCC risk adjustment model used through 2023 and partially phased out in 2024–2026.\n\nV28: the current CMS-HCC model that removed low-value HCCs and rebalanced coefficients; fully effective from plan year 2026.\n\nRAF Delta: the difference between a patient's V24 and V28 RAF score; negative deltas mean revenue erosion.\n\nHCC Erosion: the dollar-value revenue reduction caused by conditions that map to V24 HCCs but have no equivalent in V28.",
      },
      {
        heading: "How to Use",
        body: "1. Review the top KPI cards showing total V24 score, V28 score, revenue delta, and erosion percentage.\n2. Examine the delta histogram to understand the distribution of per-patient score changes.\n3. Use the 'Top Eroded Patients' table to prioritize clinical outreach — these patients need compensating codes.\n4. Click a patient row to open their profile and review dropped HCCs.\n5. Export the full table to plan coding remediation campaigns.",
      },
      {
        heading: "Common Questions",
        body: "Q: Is V28 already in effect?\nA: CMS phased in V28 at one-third weight in 2024, two-thirds in 2025, and full weight from 2026 onward.\n\nQ: Can lost V28 HCCs be recovered?\nA: In some cases, yes — V28 added new conditions (e.g. expanded mental health HCCs) that can partially offset losses from removed codes.\n\nQ: Why does my total V28 score appear higher for some patients?\nA: V28 raised coefficients for certain conditions (e.g. chronic kidney disease stages) — patients with those conditions may actually see a score increase.",
      },
    ],
  },

  "/radv": {
    title: "RADV Audit Defense",
    purpose: "CMS RADV audit defense — sampling, defensibility scoring, chart requests, and exposure simulation for Risk Adjustment Data Validation audits.",
    sections: [
      {
        heading: "Purpose",
        body: "CMS conducts Risk Adjustment Data Validation (RADV) audits to verify that HCC diagnoses submitted for payment are supported by medical record documentation. This page manages audit runs, tracks chart review decisions, and estimates financial exposure.",
      },
      {
        heading: "Key Terms",
        body: "RADV: Risk Adjustment Data Validation — CMS audit program that extrapolates findings from a sample to the full plan year.\n\nDefensibility Score: the platform's assessment (0–100) of how well each HCC is documented against CMS MEAT criteria.\n\nSampling Method: strategy for selecting which patient-HCC pairs to include in a simulated audit — random, stratified by HCC, or high-risk-first.\n\nExposure: estimated repayment amount if audit findings are extrapolated across the full payment year population.",
      },
      {
        heading: "How to Use",
        body: "1. Click 'New Audit Run' to create a simulated RADV audit with your chosen sample size and method.\n2. Open an existing run to enter the three-column review workflow: record list, clinical decision panel, exposure simulator.\n3. For each record, mark it 'Defensible', 'Undefensible', or 'Needs Remediation'.\n4. Monitor the exposure simulator as you review — it updates in real time.\n5. Export the final audit package as a PDF/ZIP for submission or internal compliance use.",
      },
      {
        heading: "Common Questions",
        body: "Q: What is the difference between a simulated and a real RADV audit?\nA: A simulated run uses your own data to prepare for a CMS audit; it has no regulatory effect. A real CMS RADV audit would be conducted by a CMS contractor using their sample.\n\nQ: What score means a record is 'defensible'?\nA: CMS does not publish a numeric threshold, but internally the platform flags records with a defensibility score below 60 as high risk.\n\nQ: How is financial exposure calculated?\nA: The platform uses the CMS extrapolation methodology — the undefensible rate in the sample is applied to the full-year payment population.",
      },
    ],
  },

  "/audit": {
    title: "Compliance & Audit",
    purpose: "Immutable SHA-256 audit chain — generate, download, and verify tamper-proof audit packages for every patient and payment year.",
    sections: [
      {
        heading: "Purpose",
        body: "Every coding decision, attestation, and data change in the platform is recorded in a cryptographically chained audit log. This page lets you generate downloadable audit packages for a patient or year, and verify that the chain has not been tampered with.",
      },
      {
        heading: "Key Terms",
        body: "Audit Package: a ZIP containing the full event log for a patient + payment year, signed with a SHA-256 hash chain.\n\nHash Chain: each audit record includes the SHA-256 hash of the previous record, making retroactive modification detectable.\n\nChain Integrity: a verification check that replays the hash chain and confirms all entries are consistent.\n\nIRR (Inter-Rater Reliability): statistical measure of coder agreement used to demonstrate consistent documentation practices.",
      },
      {
        heading: "How to Use",
        body: "1. Select a patient from the search box (or leave blank for a full-year package).\n2. Choose the payment year from the selector.\n3. Click 'Generate Package' — the platform compiles the audit trail and produces a downloadable file.\n4. Use 'Verify Chain' to run an integrity check and confirm no records have been altered.\n5. Download the package and store it in your compliance document management system.",
      },
      {
        heading: "Common Questions",
        body: "Q: How long are audit packages retained?\nA: Packages are retained for 10 years per CMS documentation retention requirements.\n\nQ: Can an audit package be generated for a deleted patient?\nA: Yes — all events are written to the immutable log even after a patient record is archived.\n\nQ: What does a failed chain integrity check mean?\nA: It means at least one audit record was modified outside the platform's normal write path, which should be escalated to your compliance officer.",
      },
    ],
  },

  "/goals": {
    title: "Quarterly Goals",
    purpose: "Quarterly RAF capture goal tracking — set targets for RAF captures, revenue, and gaps closed; monitor progress in real time.",
    sections: [
      {
        heading: "Purpose",
        body: "Goals lets administrators and managers set quarterly performance targets for the coding and care management teams, then track actual vs target across three key metrics: RAF captures, revenue generated, and care gaps closed.",
      },
      {
        heading: "Key Terms",
        body: "RAF Capture: a successful re-documentation of an HCC condition in the current payment year, either through a new claim or an accepted attestation.\n\nPeriod: the quarter a goal applies to, formatted as YYYY-QN (e.g. 2026-Q2).\n\nOn Track: the platform's assessment based on the current rate of progress vs the days remaining in the quarter.\n\nTarget vs Actual: the goal value set at creation vs the measured value from production data.",
      },
      {
        heading: "How to Use",
        body: "1. Click 'Set Goal' to create a new quarterly target — choose the metric, period, and target value.\n2. Existing goals display as cards showing actual vs target, progress bar, and on-track status.\n3. Goals update automatically as captures and attestations are processed.\n4. Use the colour coding: green = complete, amber = behind pace, blue = on track.\n5. Share goal summaries with leadership using the Export button on the Reports page.",
      },
      {
        heading: "Common Questions",
        body: "Q: Can I set goals for individual providers?\nA: The current version sets goals at the tenant (organisation) level; per-provider targets are on the roadmap.\n\nQ: What happens to a goal after the quarter ends?\nA: It remains visible for historical reference with its final actual value locked.\n\nQ: How is 'On Track' determined?\nA: The platform divides the current actual by the expected linear progress through the quarter — falling below 85% of expected pace triggers an amber warning.",
      },
    ],
  },

  "/reports": {
    title: "Analytics & Reports",
    purpose: "Revenue, scorecards, HCC distribution, provider performance, and CMS benchmarks — the full analytics suite for population health intelligence.",
    sections: [
      {
        heading: "Purpose",
        body: "The Reports page consolidates every analytic view into one tabbed interface: clinical tabs (Revenue, Patient Scorecard, HCC Distribution, Provider Performance, Quality) and analytics tabs (Longitudinal Trends, CMS Benchmarks, Settlement Projection, Scheduled Reports, Recapture Gaps).",
      },
      {
        heading: "Key Terms",
        body: "Revenue Report: aggregated capitation revenue by HCC category and provider, estimated from RAF scores and CMS payment rates.\n\nPatient Scorecard: per-patient RAF score, gap count, and quality measure compliance.\n\nHCC Distribution: frequency chart of the most prevalent HCC categories across your panel — used to benchmark against CMS national averages.\n\nSettlement Projection: forward-looking estimate of plan-year revenue given current capture rates and remaining time.",
      },
      {
        heading: "How to Use",
        body: "1. Use the Clinical / Analytics tab groups to switch between operational and strategic views.\n2. Select the measurement year from the top-right selector to compare periods.\n3. Click the Export (CSV) or Print buttons to share data outside the platform.\n4. The CMS Benchmarks tab overlays your panel's performance against national averages.\n5. Use Scheduled Reports to configure automated email delivery of key reports.",
      },
      {
        heading: "Common Questions",
        body: "Q: Is the revenue number in Reports the same as in the Dashboard?\nA: The Dashboard shows real-time opportunity; Reports shows actuals based on submitted and accepted claims. Differences reflect in-flight attestations.\n\nQ: Can I filter reports by provider or specialty?\nA: Yes — the Provider Performance tab includes provider and specialty filters. Other tabs will add filtering in future releases.\n\nQ: How far back does historical data go?\nA: The platform retains up to 3 prior payment years by default; longer retention is available in enterprise plans.",
      },
    ],
  },

  "/patients": {
    title: "Patient Roster",
    purpose: "Patient roster with risk filters — search, filter, and manage your entire enrolled population by RAF score, HCC count, and risk tier.",
    sections: [
      {
        heading: "Purpose",
        body: "The Patients page is the master roster for your enrolled Medicare Advantage population. Every patient's current RAF score, open gap count, risk tier, and last encounter date are visible at a glance, with deep links into individual clinical records.",
      },
      {
        heading: "Key Terms",
        body: "Risk Tier: colour-coded classification (High / Medium / Low / Unscored) based on RAF score relative to the panel median.\n\nHCC Count: total number of active HCC conditions coded in the current payment year.\n\nRAF Score: the patient's current CMS risk adjustment factor computed from accepted HCC codes.\n\nLast Encounter: most recent service date in any connected EMR or claims feed.",
      },
      {
        heading: "How to Use",
        body: "1. Use the search box (or press / on your keyboard) to find patients by name or ID.\n2. Click the risk filter chips (High / Medium / Low) to scope the table by risk tier.\n3. Click any column header to sort the roster by that attribute.\n4. Select patients using the checkboxes for bulk actions: export CSV, bulk close gaps, or schedule AWVs.\n5. Click a patient row to open their full RAF Central panel.",
      },
      {
        heading: "Common Questions",
        body: "Q: Why does a patient appear as 'Unscored'?\nA: The patient has no HCC codes accepted in the current payment year — either no claims have been received yet or all conditions are unsubmitted.\n\nQ: Can I import new patients from my EMR?\nA: Yes — use the Import CSV button (top-right) to upload a roster file, or connect your EMR in the EMR Config page for automatic sync.\n\nQ: How do I view a patient's full clinical history?\nA: Click the patient row to open the RAF Central panel, then select the History tab for a longitudinal view of HCC codes, claims, and notes.",
      },
    ],
  },
};

/** Resolve help content for a given pathname.
 *  Strips trailing slashes and query params for matching. */
export function getPageHelp(pathname: string): PageHelp | null {
  const clean = pathname.replace(/\?.*$/, "").replace(/\/$/, "") || "/";
  return PAGE_HELP[clean] ?? null;
}
