// Browser acceptance for Milestone 3: view a snapshot, click an object, submit a comment, reload, find it.
//
//   node tests/ui/e2e.mjs            (env: BASE_URL, PROJECT, WORKSPACE, SCREENSHOTS)
//
// Runs with the Playwright package resolvable from the current directory or globally.

import { existsSync, readFileSync, readdirSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";

// Playwright comes from NODE_PATH (a global install) or from the UI's node_modules in CI.
const require = createRequire(import.meta.url);
const { chromium } = (() => {
  try {
    return require("playwright");
  } catch {
    return require(resolve("ui/node_modules/playwright"));
  }
})();

const BASE_URL = process.env.BASE_URL ?? "http://127.0.0.1:8765";
const PROJECT = process.env.PROJECT ?? "prf_tuning";
const WORKSPACE = process.env.WORKSPACE ?? "workspace";
const SCREENSHOTS = process.env.SCREENSHOTS ?? "";
const SNAPSHOT = process.env.SNAPSHOT ?? "grown";
const OBJECT = process.env.OBJECT ?? "prf_label";

function assert(condition, message) {
  if (!condition) throw new Error(`assertion failed: ${message}`);
}

async function shot(page, name) {
  if (!SCREENSHOTS) return;
  mkdirSync(SCREENSHOTS, { recursive: true });
  await page.screenshot({ path: join(SCREENSHOTS, `${name}.png`), fullPage: true });
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
page.on("pageerror", (error) => console.error("page error:", error));
try {
  await page.goto(`${BASE_URL}/#/`);
  await page.getByTestId(`project-${PROJECT}`).click();
  await page.getByTestId("project-title").waitFor();
  const title = await page.getByTestId("project-title").textContent();
  console.log("overview:", title);
  await shot(page, "01-overview");

  await page.getByTestId("tab-review").click();
  await page.getByTestId("filmstrip").waitFor();
  await page.getByTestId(`thumb-${SNAPSHOT}`).click();
  await page.getByTestId("snapshot-title").filter({ hasText: SNAPSHOT }).waitFor();
  const badge = await page.locator(".viewer").locator("..").locator(".badge").first().textContent();
  assert(badge.includes("Manim checkpoint"), `kind label present (${badge})`);

  // Click the object's box on the overlay (its centre), which resolves the object from the layout report.
  const box = page.locator(`rect[data-object-id="${OBJECT}"]`);
  await box.waitFor();
  const bounds = await box.boundingBox();
  assert(bounds, "object box has a position");
  await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  const target = await page.getByTestId("target").textContent();
  assert(target.includes(OBJECT), `clicking the image selected the object (${target})`);
  await shot(page, "02-review-selected");

  const text = `UI test comment ${Date.now()}`;
  await page.getByTestId("comment-text").fill(text);
  await page.getByTestId("severity").selectOption("visual");
  await page.getByTestId("submit-comment").click();
  await page.getByTestId("feedback-list").getByText(text).waitFor();
  console.log("comment recorded in the panel");

  // Reload the page: the record comes back from the file through the API.
  await page.reload();
  await page.getByTestId("feedback-list").getByText(text).waitFor();
  await shot(page, "03-review-after-reload");

  const feedbackDir = join(WORKSPACE, "families", "computational_neuroscience", PROJECT, "feedback");
  assert(existsSync(feedbackDir), "feedback directory exists");
  const files = readdirSync(feedbackDir).filter((name) => name.endsWith(".yaml"));
  const matching = files.filter((name) => readFileSync(join(feedbackDir, name), "utf-8").includes(text));
  assert(matching.length === 1, `exactly one YAML record holds the comment (${matching.length})`);
  const record = readFileSync(join(feedbackDir, matching[0]), "utf-8");
  assert(record.includes(`object_id: ${OBJECT}`), "record names the object");
  assert(record.includes("kind: object_comment"), "record is an object comment");
  assert(/revision_id: (working|rev_\d{4})/.test(record), "record is bound to a revision");
  assert(record.includes("image_sha256:"), "record names the displayed image hash");
  console.log("record on disk:", matching[0]);

  // A status mark on the working copy: needs revision is allowed, approval is not.
  assert(!(await page.getByTestId("status-approved").isEnabled()) || !record.includes("revision_id: working"), "approval disabled on the working copy");
  await page.getByTestId("status-needs_revision").click();
  await page.getByTestId("feedback-list").locator(".chip-needs_revision").first().waitFor();

  await page.getByTestId("tab-compare").click();
  await page.getByText("Compare two renders").waitFor();
  await shot(page, "04-compare");
  await page.getByTestId("tab-jobs").click();
  await page.getByText("Worker log", { exact: false }).waitFor({ timeout: 1000 }).catch(() => {});
  await shot(page, "05-jobs");
  console.log("e2e ok");
} finally {
  await browser.close();
}
