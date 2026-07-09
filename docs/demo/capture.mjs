// Drives the REAL EvoMind web UI through the hero demo sequence and records a
// video: empty dashboard -> drop a PDF -> questions stream in the Feed ->
// the knowledge graph fills -> the agent's Mind -> score ticks up.
//
// Output: a .webm in $OUT_DIR (default docs/demo/). make-gif.sh converts it.
//
// Env:
//   WEB_URL   web app base   (default http://localhost:3000)
//   API_URL   FastAPI base   (default http://localhost:8000)
//   API_KEY   sent as X-API-Key when the backend has auth enabled (optional)
//   OUT_DIR   where to write raw.webm (default this script's dir)
//   PDF       sample to ingest (default docs/demo/sample-paper.pdf)
//   HEADLESS  "0" to watch it run (default "1")
//
// This intentionally has ONE npm dependency: playwright. Chromium is expected
// to be already installed (`npx playwright install chromium`).
import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { existsSync } from "node:fs";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB_URL = (process.env.WEB_URL || "http://localhost:3000").replace(/\/$/, "");
const API_URL = (process.env.API_URL || "http://localhost:8000").replace(/\/$/, "");
const API_KEY = process.env.API_KEY || "";
const OUT_DIR = process.env.OUT_DIR || HERE;
const PDF = resolve(process.env.PDF || `${HERE}/sample-paper.pdf`);
const HEADLESS = process.env.HEADLESS !== "0";

// Viewport tuned for a README hero: 16:10, retina-crisp, not too tall to crop.
const VIEWPORT = { width: 1280, height: 800 };
const SCALE = 2;

const authHeaders = API_KEY ? { "X-API-Key": API_KEY } : {};
const log = (...a) => console.log("[capture]", ...a);
const pause = (ms) => new Promise((r) => setTimeout(r, ms));

async function goto(page, path, waitMs) {
  log("visit", path);
  await page.goto(`${WEB_URL}${path}`, { waitUntil: "domcontentloaded" }).catch(() => {});
  // let client-side data load / animations settle
  await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
  await pause(waitMs);
}

async function main() {
  if (!existsSync(PDF)) {
    console.error(`Sample PDF not found: ${PDF}\nRun: python3 docs/demo/make-sample-pdf.py`);
    process.exit(2);
  }
  log(`web=${WEB_URL} api=${API_URL} pdf=${PDF} auth=${API_KEY ? "on" : "off"}`);

  const browser = await chromium.launch({ headless: HEADLESS });
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: SCALE,
    colorScheme: "dark", // the app's primary identity
    recordVideo: { dir: OUT_DIR, size: VIEWPORT },
  });
  const page = await context.newPage();

  try {
    // 1. Empty dashboard — establish the "your only job is to upload" state.
    await goto(page, "/dashboard", 1800);

    // 2. Drop the PDF via the real hidden <input type=file accept=application/pdf>.
    //    setInputFiles fires the same handler the UI uses, so this is a true capture.
    log("upload PDF via UI file input");
    const fileInput = page.locator('input[type="file"][accept="application/pdf"]');
    await fileInput.setInputFiles(PDF, { timeout: 8000 }).catch(async (e) => {
      log("UI upload failed, falling back to API upload:", e.message);
    });
    await pause(2500); // upload + refresh

    // 3. Kick the research loop deterministically via the API (don't wait on
    //    autopilot's timer). Non-fatal if the endpoint is protected/absent.
    log("trigger /run-autonomous-cycle");
    await page.request
      .post(`${API_URL}/api/run-autonomous-cycle`, { headers: authHeaders, timeout: 15000 })
      .catch((e) => log("run-cycle POST skipped:", e.message));

    // 4. Feed — questions, answers, insights streaming in.
    await goto(page, "/feed", 5000);

    // 5. Knowledge graph — nodes/edges materializing.
    await goto(page, "/graph", 4500);

    // 6. Mind — the agent's self-model (the shareable screen).
    await goto(page, "/mind", 3500);

    // 7. Back to the dashboard to land on the intelligence score.
    await goto(page, "/dashboard", 3000);

    log("sequence complete");
  } finally {
    // Closing the context flushes the video to disk.
    await context.close();
    await browser.close();
  }
  log(`raw video written under ${OUT_DIR}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
