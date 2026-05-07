/**
 * RAF Intelligence -- sales demo flow.
 *
 * 9 narrative scenes inside ONE test, sharing a single browser context
 * and page across the entire flow.  This eliminates the
 * storageState-cookie-handoff problem that plagued v1/v2 -- the scenes
 * are just a guided tour of the same authenticated session.
 *
 * Pre-flight is part of the test:
 *   1. UI login (using the "Demo Login -- Fill Credentials" button)
 *   2. POST /api/emr/demo-connect to populate the panel
 *   3. Walk the 9 scenes
 *   4. Generate storyboard.png composite (3x3 grid)
 *
 * The narration follows the PM-grade structure:
 *   "PAIN -> MOMENT -> PROOF -> SO WHAT"
 * Every scene leads with the buyer's pain, lands the moment that
 * solves it, points at the visible proof, and closes with what it
 * means for revenue / audit defense / clinician time.
 *
 * Env knobs:
 *   DEMO_REGENERATE=1  -- force-overwrite all existing storyboard PNGs
 *   DEMO_VIDEO=1       -- record a .webm for the full run
 */
import { test, type Page, type APIRequestContext } from "@playwright/test";
import * as path from "path";
import {
  API_URL,
  BASE_URL,
  EMAIL,
  PASSWORD,
  SHOT_DIR,
  ensureDir,
  narrate,
  status,
  shot,
  annotatedShot,
  waitForFirst,
  softAssertVisible,
  probeDataReadiness,
  logReadiness,
  generateStoryboard,
  SCENE_REGISTRY,
} from "./demo-helpers";

// One test, run start-to-finish, ~8 minutes at conversational pace.
test.describe.configure({ mode: "serial" });

test("RAF Intelligence -- full sales demo flow", async ({ page, request }) => {
  ensureDir(SHOT_DIR);
  test.setTimeout(480_000); // 8 min hard cap (9 scenes)

  // -----------------------------------------------------------------------
  // PRE-FLIGHT  ::  UI login + connect demo EMR + readiness probe
  // -----------------------------------------------------------------------

  await test.step("Pre-flight: log in and connect demo EMR", async () => {
    await loginViaUiResilient(page);
    await connectDemoEmr(request, page);
    const readiness = await probeDataReadiness(page);
    logReadiness(readiness);
  });

  // -----------------------------------------------------------------------
  // SCENE 1  ::  "Monday morning"  ->  /worklist
  // -----------------------------------------------------------------------

  await test.step("Scene 1 -- Today's worklist", async () => {
    narrate(
      "Scene 1",
      "PAIN: Your providers waste the first 40 minutes of every Monday hunting through patient charts looking for who actually needs to be seen this week.",
    );
    await page.goto(`${BASE_URL}/worklist`);
    await waitForFirst(page, [
      "Today's worklist",
      "Patients to see",
      "patients prioritized",
      "You're caught up",
    ]);

    narrate(
      "Scene 1",
      "MOMENT: The single screen they actually want -- patients ranked by priority score, every card showing open gaps and revenue at risk.",
    );

    await shot(page, "01-worklist", { fullPage: true });
    await annotatedShot(
      page,
      "01-worklist",
      [
        page.getByText(/Patients to see/i),
        page.getByText(/Today's worklist/i),
      ],
      {
        caption: "Priority-ranked worklist -- open gaps + revenue at risk",
        sceneNum: 1,
        storyCaption: "Monday morning worklist -- priority-ranked patients",
      },
    );

    narrate(
      "Scene 1",
      "SO WHAT: 40 minutes of chart hunting -> 40 minutes of patient care.  Repeated across 1,200 PCPs in a 50K-member plan, that's 800 provider-hours back per week.",
    );
  });

  // -----------------------------------------------------------------------
  // SCENE 2  ::  "Why this HCC?"  ->  /recapture + KG hover
  // -----------------------------------------------------------------------

  await test.step("Scene 2 -- Why this HCC? KG explainability", async () => {
    narrate(
      "Scene 2",
      "PAIN: Apixio and Navina hand you a black box.  When the auditor asks 'why did you code HCC 19?', you answer 'because the model said so' -- and you lose the appeal.",
    );
    await page.goto(`${BASE_URL}/recapture`);
    await waitForFirst(page, ["Recapture Gaps", "Total Gaps", "Most Common"]);

    await shot(page, "02a-recapture-overview", { fullPage: true });

    narrate(
      "Scene 2",
      "MOMENT: Every HCC chip is hoverable.  We trace ICD-10 -> SNOMED CT -> HCC with the exact peer-reviewed citations the rule was derived from.",
    );

    const hccChip = page.getByRole("button", { name: /HCC \d/i }).first();
    if (await hccChip.count()) {
      await hccChip.scrollIntoViewIfNeeded();
      await hccChip.hover();
      await page.waitForTimeout(900);
      await shot(page, "02b-hcc-popover");
      await annotatedShot(
        page,
        "02b-hcc-popover",
        [
          page.getByRole("dialog"),
          page.getByText(/SNOMED|ICD-10|Why this/i),
          hccChip,
        ],
        {
          caption: "ICD-10 -> SNOMED CT -> HCC trace with citations",
          sceneNum: 2,
          storyCaption: "KG explainability -- ICD-10 -> HCC with citations",
        },
      );
    } else {
      status("no HCC chips rendered -- recapture table is empty");
      await annotatedShot(
        page,
        "02a-recapture-overview",
        [page.getByText(/Recapture|Total Gaps/i)],
        {
          sceneNum: 2,
          storyCaption: "KG explainability -- ICD-10 -> HCC with citations",
        },
      );
    }

    narrate(
      "Scene 2",
      "SO WHAT: When CMS asks for justification, you show citations -- not chat-completions.  This is the difference between getting paid and getting clawed back.",
    );
  });

  // -----------------------------------------------------------------------
  // SCENE 3  ::  Calibrated confidence  ->  /suspects
  // -----------------------------------------------------------------------

  await test.step("Scene 3 -- Calibrated confidence", async () => {
    narrate(
      "Scene 3",
      "PAIN: Your coders learn to ignore the model's confidence number because it's miscalibrated -- 78% means anywhere from 50% to 95% in practice.",
    );
    await page.goto(`${BASE_URL}/suspects`);
    await waitForFirst(page, [
      "Suspect",
      "Confidence",
      "Suspected Condition",
      "No suspects",
    ]);

    narrate(
      "Scene 3",
      "MOMENT: We trained Platt scaling on a held-out fixture.  Raw ECE was 0.22 -- calibrated ECE is 0.03.  When you see 78% on this page, it actually means 78%.",
    );

    await shot(page, "03-suspects-overview", { fullPage: true });

    const calChip = page.getByText(/calibrated/i).first();
    await softAssertVisible(calChip, "calibrated-confidence chip");
    await annotatedShot(
      page,
      "03-suspects-calibrated",
      [
        page.getByText(/calibrated/i),
        page.getByText(/Confidence/i).first(),
      ],
      {
        caption: "Platt-scaled confidence -- ECE 0.03 (was 0.22)",
        sceneNum: 3,
        storyCaption: "Calibrated confidence -- 78% really means 78%",
      },
    );

    narrate(
      "Scene 3",
      "SO WHAT: Coders trust the score, filter by threshold, hit higher throughput.  No competitor ships calibrated probabilities -- they ship raw logits.",
    );
  });

  // -----------------------------------------------------------------------
  // SCENE 4  ::  Audit defense  ->  /recapture (RADV section)
  // -----------------------------------------------------------------------

  await test.step("Scene 4 -- Audit defense (RADV + Cohen's kappa)", async () => {
    narrate(
      "Scene 4",
      "PAIN: A failed RADV audit costs an MA plan $10-50M.  Your current defense is a coder's word against a CMS auditor's.",
    );
    await page.goto(`${BASE_URL}/recapture`);
    await waitForFirst(page, ["Recapture", "RADV Audit Defense", "Audit Ready"]);

    const auditHeader = page
      .getByRole("heading", { name: /RADV Audit Defense|Audit Ready/i })
      .first();
    if (await auditHeader.count()) {
      await auditHeader.scrollIntoViewIfNeeded();
      await page.waitForTimeout(600);
    }

    narrate(
      "Scene 4",
      "MOMENT: Dual-coder MEAT workflow with Cohen's kappa for inter-rater reliability -- not naive agreement-percentage.  Every gap shows the timestamp, primary coder, secondary coder, and the verbatim chart phrase.",
    );

    await shot(page, "04-audit-readiness");
    const irrTile = page.getByText(/Inter-rater reliability/i).first();
    await softAssertVisible(irrTile, "Cohen's kappa IRR tile");
    await annotatedShot(
      page,
      "04-audit-readiness",
      [
        page.getByText(/Inter-rater reliability/i),
        page.getByText(/Audit Ready/i),
        auditHeader,
      ],
      {
        caption: "Cohen's kappa IRR + dual-coder MEAT timestamps",
        sceneNum: 4,
        storyCaption: "RADV audit defense -- Cohen's kappa IRR",
      },
    );

    narrate(
      "Scene 4",
      "SO WHAT: When CMS challenges a code, you export the audit-ready PDF in one click.  Auditor sees evidence, signs off, you keep the revenue.",
    );
  });

  // -----------------------------------------------------------------------
  // SCENE 5  ::  Velocity & decay  ->  /recapture (KPI strip)
  // -----------------------------------------------------------------------

  await test.step("Scene 5 -- Velocity & decay", async () => {
    narrate(
      "Scene 5",
      "PAIN: Most plans discover in November they're behind on recapture and panic-spam providers.  Year-end cliff = $5M of unrecaptured RAF.",
    );
    // Force a hard reload -- Next.js client-router was retaining the
    // dashboard view from a previous scene's redirect chain.
    await page.goto("about:blank");
    await page.goto(`${BASE_URL}/recapture`);
    await waitForFirst(page, ["Recapture", "Total Gaps"]);

    const velocityHeader = page
      .getByRole("heading", { name: /velocity|decay/i })
      .first();
    if (await velocityHeader.count()) {
      await velocityHeader.scrollIntoViewIfNeeded();
      await page.waitForTimeout(600);
    }

    narrate(
      "Scene 5",
      "MOMENT: Velocity strip shows YTD recaptured, projected vs budget, and avg days-to-close.  Decay curve below shows the cumulative-closure rate by month.",
    );

    await shot(page, "05-velocity-decay");
    await softAssertVisible(velocityHeader, "Recapture velocity & decay header");
    await annotatedShot(
      page,
      "05-velocity-decay",
      [
        page.getByText(/Avg Days to Close/i),
        page.getByText(/YE Projected/i),
        velocityHeader,
      ],
      {
        caption: "YTD velocity + projected-vs-budget decay curve",
        sceneNum: 5,
        storyCaption: "Recapture velocity -- catch the cliff in February",
      },
    );

    narrate(
      "Scene 5",
      "SO WHAT: You see the gap in February, intervene in May, hit the target in October.  No more November fire-drill.",
    );
  });

  // -----------------------------------------------------------------------
  // SCENE 6  ::  CFO summary  ->  /recapture (CFO section)
  // -----------------------------------------------------------------------

  await test.step("Scene 6 -- CFO executive summary", async () => {
    narrate(
      "Scene 6",
      "PAIN: Your CFO wants one number for the board: 'how much MA revenue do we have at risk this cycle?' -- and the answer takes 3 weeks to assemble.",
    );
    // Force a hard reload -- Next.js client-router was retaining the
    // dashboard view from a previous scene's redirect chain.
    await page.goto("about:blank");
    await page.goto(`${BASE_URL}/recapture`);
    await waitForFirst(page, ["Recapture", "Total Gaps"]);

    const cfoHeader = page
      .getByRole("heading", { name: /CFO executive summary|Projected/i })
      .first();
    if (await cfoHeader.count()) {
      await cfoHeader.scrollIntoViewIfNeeded();
      await page.waitForTimeout(600);
    }

    narrate(
      "Scene 6",
      "MOMENT: One screen.  Quarterly $ projection, top 5 conditions by revenue contribution, top 5 providers driving lift, year-over-year comparison.  Amber 'PROJECTED' badge so the CFO can never confuse forecast with actual.",
    );

    await shot(page, "06-cfo-summary");
    await softAssertVisible(cfoHeader, "CFO executive summary header");
    await annotatedShot(
      page,
      "06-cfo-summary",
      [
        page.getByText(/PROJECTED/),
        page.getByText(/Q1|Q2|Q3|Q4/i).first(),
        cfoHeader,
      ],
      {
        caption: "Quarterly $ projection + top-5 conditions by revenue",
        sceneNum: 6,
        storyCaption: "CFO self-serve summary -- updated nightly",
      },
    );

    narrate(
      "Scene 6",
      "SO WHAT: The CFO stops asking finance for a revenue-at-risk model.  Self-serve.  Updated nightly.",
    );
  });

  // -----------------------------------------------------------------------
  // SCENE 7  ::  Mobile  ->  /worklist on phone + tablet
  // -----------------------------------------------------------------------

  await test.step("Scene 7 -- Mobile (iPad in the exam room)", async () => {
    narrate(
      "Scene 7",
      "PAIN: Doctors chart on iPads at the bedside.  If your tool only works on a 27-inch monitor, you've lost the workflow.",
    );

    // Phone
    await page.setViewportSize({ width: 414, height: 896 });
    await page.goto(`${BASE_URL}/worklist`);
    await waitForFirst(page, [
      "Today's worklist",
      "You're caught up",
      "AI-Powered Risk Adjustment",
    ]);
    await shot(page, "07a-worklist-phone", { fullPage: true });

    // Tablet
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.reload();
    await waitForFirst(page, [
      "Today's worklist",
      "You're caught up",
      "AI-Powered Risk Adjustment",
    ]);
    await shot(page, "07b-worklist-tablet", { fullPage: true });

    await annotatedShot(
      page,
      "07b-worklist-tablet",
      [
        page.getByText(/Today's worklist|You're caught up|AI-Powered/i).first(),
      ],
      {
        caption: "Responsive -- single/two/three column on phone/tablet/desktop",
        sceneNum: 7,
        storyCaption: "Mobile-first -- same KG popovers on iPad",
      },
    );

    narrate(
      "Scene 7",
      "MOMENT: Same worklist, same KG popovers, same MEAT workflow -- single column on phone, two on tablet, three on desktop.  No separate mobile app to maintain.",
    );

    // Reset for any post-test debugging.
    await page.setViewportSize({ width: 1440, height: 900 });
  });

  // -----------------------------------------------------------------------
  // SCENE 8  ::  "Dual-coder review queue"  ->  /review-queue
  // -----------------------------------------------------------------------

  await test.step("Scene 8 -- Dual-coder review queue", async () => {
    narrate(
      "Scene 8",
      "PAIN: Coders disagree silently -- there's no audit trail of who decided what when.  One coder accepts, another dismisses the same suspect next month.",
    );

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE_URL}/review-queue`);
    await waitForFirst(
      page,
      [
        "Review",
        "HCC Candidates",
        "Suspects",
        "Provider Queries",
        "review queue",
        "candidates",
      ],
      15_000,
    );

    narrate(
      "Scene 8",
      "MOMENT: Every gap shows the primary coder, secondary coder, and timestamp of each decision.  Status pills (open / accepted / dismissed) are colour-coded so discrepancies jump out.",
    );

    await shot(page, "08-review-queue", { fullPage: false });

    const statusPill = page
      .getByText(/open|accepted|dismissed|pending/i)
      .first();
    const actorTimestamp = page
      .getByText(/coder|reviewer|primary|secondary|\d{2}:\d{2}/i)
      .first();

    await annotatedShot(
      page,
      "08-review-queue",
      [statusPill, actorTimestamp, page.getByText(/HCC Candidate|Suspect/i).first()],
      {
        caption: "Status pills + actor timestamps -- full dual-coder audit trail",
        sceneNum: 8,
        storyCaption: "Dual-coder review queue -- who decided what, when",
      },
    );

    narrate(
      "Scene 8",
      "SO WHAT: When the external auditor asks 'who accepted this code and why?', you pull the timestamped log in two clicks.  No more 'we think it was Janet'.",
    );
  });

  // -----------------------------------------------------------------------
  // SCENE 9  ::  Patient detail + KG inference  ->  /patients/{id}
  // -----------------------------------------------------------------------

  await test.step("Scene 9 -- Patient detail with KG inference panel", async () => {
    narrate(
      "Scene 9",
      "PAIN: Apixio gives you a list of suspect conditions with no explanation.  When you ask 'why does the model think this patient has CHF?', the answer is a logit.",
    );

    const patientId = await discoverPatientId(page);
    const patientUrl = `${BASE_URL}/patients/${patientId}`;

    await page.goto(patientUrl);
    await waitForFirst(
      page,
      [
        "RAF Score",
        "HCC Count",
        "RAF Central",
        "Model Segment",
        "Overview",
      ],
      20_000,
    );

    narrate(
      "Scene 9",
      "MOMENT: Every HCC candidate in the RAF Central tab has its full evidence chain inline -- ICD-10 code, SNOMED concept, CMS HCC mapping, and the verbatim phrase from the source note.",
    );

    // Give React Query time to load the breakdown.
    await page.waitForTimeout(2000);

    await shot(page, "09-patient-detail", { fullPage: false });

    const rafScore = page.getByText(/RAF Score/i).first();
    const hccEvidence = page
      .getByText(/HCC|evidence|ICD-10|SNOMED|candidate/i)
      .first();
    const kgSection = page
      .getByText(/RAF Central|KG|Knowledge Graph|inference/i)
      .first();

    await annotatedShot(
      page,
      "09-patient-detail",
      [hccEvidence, kgSection, rafScore],
      {
        caption: "HCC candidates with full ICD-10 -> SNOMED -> HCC evidence chain",
        sceneNum: 9,
        storyCaption: "Patient KG panel -- every candidate has evidence inline",
      },
    );

    narrate(
      "Scene 9",
      "SO WHAT: Coders understand why a suspect was flagged without reading the full chart.  Review time per chart drops from 14 minutes to 4 minutes.",
    );
  });

  // -----------------------------------------------------------------------
  // STORYBOARD COMPOSITE  ::  tile all 9 scenes into storyboard.png
  // -----------------------------------------------------------------------

  await test.step("Generate storyboard composite", async () => {
    const outPath = path.join(SHOT_DIR, "storyboard.png");
    narrate("Storyboard", `Generating 3x3 composite -> ${outPath}`);
    try {
      await generateStoryboard(SCENE_REGISTRY, outPath);
      narrate("Storyboard", `Done. ${SCENE_REGISTRY.length} scenes tiled.`);
    } catch (e) {
      status(`storyboard generation failed: ${(e as Error).message}`);
    }
  });

  // -----------------------------------------------------------------------
  // CLOSE
  // -----------------------------------------------------------------------

  // eslint-disable-next-line no-console
  console.log(`\n  Demo run complete.\n  Storyboard: ${SHOT_DIR}/storyboard.png\n  Shots dir:  ${SHOT_DIR}\n`);
});

// ---------------------------------------------------------------------------
// Local helpers
// ---------------------------------------------------------------------------

/** Resilient UI login that survives the React-form hydrate-and-detach
 * race.  Strategy: prefer the "Demo Login -- Fill Credentials" button if
 * it's present, otherwise type with pressSequentially. */
async function loginViaUiResilient(page: Page): Promise<void> {
  await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });

  const submit = page.getByRole("button", {
    name: /^Secure Sign In$|^Sign In$/i,
  });
  await submit.waitFor({ state: "visible", timeout: 15_000 });
  await page.waitForTimeout(800);

  const demoFill = page.getByRole("button", {
    name: /Demo Login.*Fill Credentials/i,
  });
  if (await demoFill.count()) {
    await demoFill.click();
    await page.waitForTimeout(400);
  } else {
    const email = page.locator('input[type="email"]').first();
    const pw = page.locator('input[type="password"]').first();
    await email.click();
    await email.pressSequentially(EMAIL, { delay: 25 });
    await pw.click();
    await pw.pressSequentially(PASSWORD, { delay: 25 });
  }
  await submit.click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), {
    timeout: 30_000,
  });
}

/** Connect the bundled demo OpenEMR and trigger a full sync. */
async function connectDemoEmr(
  request: APIRequestContext,
  page: Page,
): Promise<void> {
  try {
    const login = await request.post(`${API_URL}/api/auth/login`, {
      data: { email: EMAIL, password: PASSWORD },
    });
    if (!login.ok()) {
      status(`demo-connect skipped -- login returned ${login.status()}`);
      return;
    }
    const { access_token } = (await login.json()) as { access_token: string };
    const auth = { Authorization: `Bearer ${access_token}` };

    const stats = await request.get(`${API_URL}/api/dashboard/stats`, {
      headers: auth,
    });
    if (stats.ok()) {
      const body = (await stats.json()) as { total_patients?: number };
      if ((body.total_patients ?? 0) > 0) {
        status(`patient panel present (${body.total_patients}); skipping sync`);
        return;
      }
    }

    const conn = await request.post(`${API_URL}/api/emr/demo-connect`, {
      headers: auth,
    });
    if (!conn.ok()) {
      status(`demo-connect returned ${conn.status()} -- non-fatal`);
      return;
    }
    const connBody = (await conn.json()) as {
      connection_id?: number;
      display_name?: string;
    };
    status(
      `demo EMR connected: ${connBody.display_name ?? "(active)"} ` +
        `id=${connBody.connection_id ?? "?"}`,
    );

    if (connBody.connection_id) {
      const sync = await request.post(
        `${API_URL}/api/emr/connections/${connBody.connection_id}/sync?sync_type=full`,
        { headers: auth },
      );
      status(`sync trigger: ${sync.status()}`);
      const deadline = Date.now() + 30_000;
      while (Date.now() < deadline) {
        const s = await request.get(`${API_URL}/api/dashboard/stats`, {
          headers: auth,
        });
        if (s.ok()) {
          const body = (await s.json()) as { total_patients?: number };
          if ((body.total_patients ?? 0) > 0) {
            status(`sync delivered ${body.total_patients} patients`);
            break;
          }
        }
        await page.waitForTimeout(2000);
      }
    }
  } catch (e) {
    status(`demo-connect threw: ${(e as Error).message}`);
  }
}

/**
 * Discover a real patient ID so Scene 9 can navigate to a concrete URL.
 * Falls back to "1" if no patient is found.
 */
async function discoverPatientId(page: Page): Promise<string> {
  try {
    const resp = await page.request.get(`${API_URL}/api/patients?limit=1`);
    if (resp.ok()) {
      const body = (await resp.json()) as
        | { patients?: Array<{ id?: number; patient_id?: number }> }
        | Array<{ id?: number; patient_id?: number }>;
      const list = Array.isArray(body) ? body : (body.patients ?? []);
      if (list.length > 0) {
        const p = list[0];
        const id = p.id ?? p.patient_id;
        if (id) {
          status(`patient ID discovered via API: ${id}`);
          return String(id);
        }
      }
    }
  } catch {
    // fall through to DOM strategy
  }

  try {
    await page.goto(`${BASE_URL}/patients`, { waitUntil: "domcontentloaded" });
    await waitForFirst(page, ["patient", "RAF", "HCC", "Name"], 10_000);

    const patientLink = page.locator('a[href*="/patients/"]').first();
    if (await patientLink.count()) {
      const href = await patientLink.getAttribute("href");
      const match = href?.match(/\/patients\/(\d+)/);
      if (match) {
        status(`patient ID discovered via DOM link: ${match[1]}`);
        return match[1];
      }
    }
  } catch {
    // fall through to last resort
  }

  status("patient ID discovery failed -- falling back to ID 1");
  return "1";
}
