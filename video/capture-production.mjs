import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const requireFromFrontend = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium } = requireFromFrontend("@playwright/test");

const SCENE_IDS = ["hook", "surface", "trigger", "live", "sponsor", "evidence", "close"];
const SHA = /^[a-f0-9]{40}$/u;
const RUN_ID = /^[1-9][0-9]*$/u;
const root = process.env.MERISMOS_VIDEO_ROOT;
const frontendSha = process.env.MERISMOS_FRONTEND_SHA;
const backendSha = process.env.MERISMOS_BACKEND_SHA;
const deployRunId = process.env.MERISMOS_DEPLOY_RUN_ID;
const frontendRunId = process.env.MERISMOS_FRONTEND_RUN_ID;
const configuredUrl = process.env.MERISMOS_VIDEO_URL || "https://d2qnkmlhs7y5fp.cloudfront.net/";
const appUrl = configuredUrl.endsWith("/") ? configuredUrl : `${configuredUrl}/`;
const slidesUrl = new URL("./slides.html", import.meta.url).href;

if (!root || !SHA.test(frontendSha ?? "") || !SHA.test(backendSha ?? "")) {
  throw new Error(
    "MERISMOS_VIDEO_ROOT plus exact lowercase MERISMOS_FRONTEND_SHA and MERISMOS_BACKEND_SHA are required.",
  );
}
if (!RUN_ID.test(deployRunId ?? "") || !RUN_ID.test(frontendRunId ?? "")) {
  throw new Error("Exact deploy and frontend GitHub Actions run IDs are required.");
}
if (appUrl !== "https://d2qnkmlhs7y5fp.cloudfront.net/") {
  throw new Error("The production capture URL must be the public Merismos CloudFront origin.");
}

const captureDir = path.join(root, "capture");
mkdirSync(path.join(captureDir, "raw"), { recursive: true });
const reviewDir = path.join(root, "review");
mkdirSync(reviewDir, { recursive: true });
const timingPath = path.join(root, "narration", "timing.json");
const timingBytes = readFileSync(timingPath);
const timing = JSON.parse(timingBytes.toString("utf8"));
if (timing.schemaVersion !== "merismos.submission-video-timing/v1") {
  throw new Error("The capture requires the measured Merismos timing contract.");
}
if (JSON.stringify(timing.scenes.map((scene) => scene.id)) !== JSON.stringify(SCENE_IDS)) {
  throw new Error("Narration and capture scene order differ.");
}
const holds = Object.fromEntries(
  timing.scenes.map((scene) => [scene.id, Number(scene.holdSeconds) * 1000]),
);

const browser = await chromium.launch({ args: ["--force-device-scale-factor=1"] });
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
  colorScheme: "dark",
  recordVideo: { dir: path.join(captureDir, "raw"), size: { width: 1920, height: 1080 } },
});

async function jsonResponse(url) {
  const response = await context.request.get(url, {
    headers: { "Cache-Control": "no-cache", Pragma: "no-cache" },
    failOnStatusCode: false,
  });
  if (response.status() !== 200) throw new Error(`${url} returned HTTP ${response.status()}.`);
  return response.json();
}

const release = await jsonResponse(`${appUrl}release.json?video_release=${frontendSha}`);
if (release.commit !== frontendSha) throw new Error("The public release.json is not the frozen frontend SHA.");
const backend = await jsonResponse(`${appUrl}api/version?video_backend=${backendSha}`);
if (
  backend.schema_version !== 1 ||
  backend.application !== "merismos" ||
  backend.commit !== backendSha ||
  backend.status !== "known" ||
  backend.source !== "ci_package"
) {
  throw new Error("The answering backend is not the exact frozen CI package.");
}
const rootResponse = await context.request.get(`${appUrl}?video_release=${frontendSha}`, {
  headers: { "Cache-Control": "no-cache", Pragma: "no-cache" },
  failOnStatusCode: false,
});
if (rootResponse.status() !== 200) throw new Error(`The product root returned HTTP ${rootResponse.status()}.`);
const rootHtml = await rootResponse.text();
const rootCommits = [...rootHtml.matchAll(/<meta name="application-commit" content="([0-9a-f]{40})">/gu)];
if (rootCommits.length !== 1 || rootCommits[0][1] !== frontendSha) {
  throw new Error("The served root HTML is not the frozen SHA.");
}

const page = await context.newPage();
const video = page.video();
if (!video) throw new Error("Playwright did not create a video recorder.");
const browserErrors = [];
const requestFailures = [];
const onProductOrigin = () => page.url().startsWith(appUrl);
page.on("pageerror", (error) => {
  if (onProductOrigin()) browserErrors.push(`page:${error.name}`);
});
page.on("console", (message) => {
  if (onProductOrigin() && message.type() === "error") browserErrors.push("console:error");
});
page.on("requestfailed", (request) => {
  if (request.url().startsWith(appUrl)) requestFailures.push(new URL(request.url()).pathname);
});

const captureStarted = Date.now();
await page.goto(`${appUrl}?video_release=${frontendSha}`, { waitUntil: "networkidle", timeout: 60_000 });
await page.getByRole("heading", { name: "Dashboard", exact: true }).waitFor();

// Recording preflight: defeat a persisted Live choice and start a genuinely fresh sandbox.
const workspaceMode = page.getByLabel("Workspace", { exact: true });
await workspaceMode.selectOption("sandbox");
const about = page.locator("details.about-demo");
await about.evaluate((element) => { element.open = true; });
await page.getByRole("button", { name: "Start over in a new sandbox", exact: true }).click();
const freshSession = page.waitForResponse(
  (response) => response.url().endsWith("/api/sessions") && response.request().method() === "POST",
);
const freshWorkspace = page.waitForResponse(
  (response) => response.url().includes("/api/workspace?mode=sandbox") && response.status() === 200,
);
await page.getByRole("button", { name: "Yes, start fresh", exact: true }).click();
if ((await freshSession).status() !== 201) throw new Error("Fresh sandbox creation failed.");
await freshWorkspace;
await page.getByRole("heading", { name: "Dashboard", exact: true }).waitFor();
await page.waitForFunction(() => !document.querySelector("#mode")?.hasAttribute("disabled"));
await about.evaluate((element) => { element.open = false; });
await page.evaluate(() => window.scrollTo(0, 0));

// Start the measured story on a source-controlled title scene. The fresh
// deployed sandbox remains active when the next beat returns to the dashboard.
await page.goto(`${slidesUrl}?scene=hook`, { waitUntil: "load", timeout: 60_000 });
await page.getByRole("heading", { name: /One offer\. Several constraints/iu }).waitFor();

const timelineStarted = Date.now();
const observedScenes = [];
let decisionUrl = "";

async function holdScene(id, action) {
  const planned = holds[id];
  if (!Number.isFinite(planned) || planned < 3_000 || planned > 41_000) {
    throw new Error(`Unsafe or missing measured hold for ${id}.`);
  }
  const started = Date.now();
  const observedStart = (started - timelineStarted) / 1000;
  await action(planned);
  await page.screenshot({ path: path.join(reviewDir, `${id}.png`), fullPage: false });
  const actionMilliseconds = Date.now() - started;
  if (actionMilliseconds > planned) {
    throw new Error(
      `Scene ${id} actions took ${(actionMilliseconds / 1000).toFixed(3)}s, longer than its ` +
      `${(planned / 1000).toFixed(3)}s measured narration window.`,
    );
  }
  await page.waitForTimeout(planned - actionMilliseconds);
  observedScenes.push({
    id,
    observedStartSeconds: Number(observedStart.toFixed(3)),
    observedEndSeconds: Number(((Date.now() - timelineStarted) / 1000).toFixed(3)),
    actionSeconds: Number((actionMilliseconds / 1000).toFixed(3)),
  });
}

async function gotoHash(hash, heading) {
  await page.goto(`${appUrl}${hash}`, { waitUntil: "networkidle", timeout: 60_000 });
  await page.getByRole("heading", { name: heading, exact: true }).waitFor();
}

async function clickForResponse(button, ending, expectedStatus = 200) {
  const responsePromise = page.waitForResponse(
    (response) => response.url().endsWith(ending) && response.request().method() === "POST",
  );
  await button.click();
  const response = await responsePromise;
  if (response.status() !== expectedStatus) {
    throw new Error(`${ending} returned HTTP ${response.status()}, expected ${expectedStatus}.`);
  }
}

await holdScene("hook", async (planned) => {
  await page.waitForTimeout(Math.min(4_000, planned * 0.25));
});

await holdScene("surface", async () => {
  await gotoHash("#/dashboard", "Dashboard");
  await page.getByRole("region", { name: "Your next donation" }).waitFor();
  await page.getByRole("link", { name: "+ Add offer", exact: true }).click();
  await page.getByRole("heading", { name: "Add an offer", exact: true }).waitFor();
  await page.getByRole("button", { name: "Try success", exact: true }).click();
  const offerTitle = page.getByLabel("What is being donated?", { exact: true });
  await offerTitle.fill("Evening bakery surplus");
  if ((await offerTitle.inputValue()) !== "Evening bakery surplus") {
    throw new Error("The editable offer title did not retain the recorded change.");
  }
  await clickForResponse(page.getByRole("button", { name: "Add to sandbox", exact: true }), "/api/offers/new");
  await page.getByRole("button", { name: "Work out the split", exact: true }).waitFor();
  decisionUrl = page.url();
});

await holdScene("trigger", async () => {
  const nextDecision = page.getByRole("button", { name: "Go to next decision ↓", exact: true });
  if (await nextDecision.isVisible().catch(() => false)) await nextDecision.click();
  await clickForResponse(
    page.getByRole("button", { name: "Work out the split", exact: true }),
    "/run",
  );
  await page.getByRole("heading", { name: "Approve this exact plan", exact: true }).waitFor();
  await page.waitForTimeout(650);
  await page.getByRole("heading", { name: "Approve this exact plan", exact: true }).scrollIntoViewIfNeeded();
});

await holdScene("live", async () => {
  await page.getByText("Read the exact record text", { exact: true }).click();
  await page.getByLabel(/I have reviewed this exact allocation/iu).check();
  await clickForResponse(page.getByRole("button", { name: "Approve in sandbox", exact: true }), "/approve");
  await page.getByRole("link", { name: "Open collection tasks →", exact: true }).click();
  await page.getByRole("heading", { name: "Pickups", exact: true }).waitFor();
  let pickup = page.getByRole("article").filter({ has: page.getByRole("button", { name: "Claim this share" }) }).first();
  const pickupName = (await pickup.getByRole("heading").first().innerText()).trim();
  await clickForResponse(pickup.getByRole("button", { name: "Claim this share" }), "/pickup");
  pickup = page.getByRole("article").filter({ has: page.getByRole("heading", { name: pickupName, exact: true }) });
  await pickup.getByLabel("This collection actually happened in the simulation.").check();
  await clickForResponse(pickup.getByRole("button", { name: "Confirm collection" }), "/pickup");
  await pickup.getByText("Simulation confirmed", { exact: false }).waitFor();
});

await holdScene("sponsor", async (planned) => {
  await page.goto(`${slidesUrl}?scene=architecture`, { waitUntil: "load", timeout: 60_000 });
  await page.getByRole("heading", { name: /Rules first\. Strands when eligible/iu }).waitFor();
  await page.waitForTimeout(Math.min(3_500, planned * 0.18));
  await page.screenshot({ path: path.join(reviewDir, "sponsor-architecture-slide.png"), fullPage: false });
  await gotoHash("#/architecture", "AWS architecture");
  const dwell = Math.min(1_300, Math.max(450, planned * 0.06));
  await page.getByRole("button", { name: /CloudFront \+ S3 SPA/iu }).click();
  await page.waitForTimeout(dwell);
  await page.getByRole("button", { name: /Four Lambdas, one package/iu }).click();
  await page.waitForTimeout(dwell);
  await page.getByRole("button", { name: /Strands agents/iu }).click();
  const inspector = page.getByRole("heading", { name: /Strands agents \(Strands Agents SDK/iu });
  await inspector.waitFor();
  await inspector.scrollIntoViewIfNeeded();
});

await holdScene("evidence", async () => {
  if (!decisionUrl.startsWith(appUrl)) throw new Error("The recorded decision URL is missing.");
  await page.goto(decisionUrl, { waitUntil: "networkidle", timeout: 60_000 });
  await page.getByText("Evidence bundle and recovery", { exact: true }).click();
  const evidence = page.getByLabel("Evidence bundle", { exact: true });
  await evidence.waitFor();
  await evidence.scrollIntoViewIfNeeded();
});

await holdScene("close", async (planned) => {
  await gotoHash("#/impact", "Impact and limits");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(Math.min(2_500, planned * 0.18));
  await page.getByText("WHAT IS NOT MEASURED", { exact: true }).evaluate((element) => {
    element.scrollIntoView({ behavior: "smooth", block: "center" });
  });
  await page.waitForTimeout(Math.min(1_500, planned * 0.1));
  await page.goto(`${slidesUrl}?scene=close`, { waitUntil: "load", timeout: 60_000 });
  await page.getByRole("heading", { name: /The allocation, its reasons/iu }).waitFor();
});

// Fail if either deployed surface moved while the measured story was recorded.
const closingToken = `${frontendSha}-${Date.now()}`;
const closingRelease = await jsonResponse(`${appUrl}release.json?video_release_end=${closingToken}`);
const closingBackend = await jsonResponse(`${appUrl}api/version?video_backend_end=${closingToken}`);
if (closingRelease.commit !== frontendSha) {
  throw new Error("The frontend release changed during production capture.");
}
if (
  closingBackend.schema_version !== 1 ||
  closingBackend.application !== "merismos" ||
  closingBackend.commit !== backendSha ||
  closingBackend.status !== "known" ||
  closingBackend.source !== "ci_package"
) {
  throw new Error("The answering backend changed during production capture.");
}
const closingRootResponse = await context.request.get(`${appUrl}?video_release_end=${closingToken}`, {
  headers: { "Cache-Control": "no-cache", Pragma: "no-cache" },
  failOnStatusCode: false,
});
if (closingRootResponse.status() !== 200) {
  throw new Error(`The closing product root returned HTTP ${closingRootResponse.status()}.`);
}
const closingRootHtml = await closingRootResponse.text();
const closingRootCommits = [
  ...closingRootHtml.matchAll(/<meta name="application-commit" content="([0-9a-f]{40})">/gu),
];
if (closingRootCommits.length !== 1 || closingRootCommits[0][1] !== frontendSha) {
  throw new Error("The served root HTML changed during production capture.");
}

const timelineSeconds = (Date.now() - timelineStarted) / 1000;
await context.close();
await browser.close();
const rawPath = await video.path();
const finalPath = path.join(captureDir, "production.webm");
renameSync(rawPath, finalPath);
const bytes = readFileSync(finalPath);
const receipt = {
  schemaVersion: "merismos.submission-video-capture/v2",
  frontendSha,
  backendSha,
  deployRunId: Number(deployRunId),
  frontendRunId: Number(frontendRunId),
  sourceUrl: appUrl,
  servedFrontendCommit: closingRelease.commit,
  answeringBackendCommit: closingBackend.commit,
  releaseVerifiedBeforeAndAfter: true,
  sceneCount: SCENE_IDS.length,
  sceneIds: SCENE_IDS,
  scenes: observedScenes,
  trimLeadSeconds: Number(((timelineStarted - captureStarted) / 1000).toFixed(3)),
  timelineSeconds: Number(timelineSeconds.toFixed(3)),
  narrationTimingSha256: createHash("sha256").update(timingBytes).digest("hex"),
  pageErrors: browserErrors,
  requestFailures,
  bytes: bytes.length,
  sha256: createHash("sha256").update(bytes).digest("hex"),
};
writeFileSync(path.join(captureDir, "capture-receipt.json"), `${JSON.stringify(receipt, null, 2)}\n`);
if (browserErrors.length !== 0 || requestFailures.length !== 0) {
  throw new Error(
    `Production journey emitted ${browserErrors.length} browser errors and ` +
    `${requestFailures.length} failed product requests.`,
  );
}
console.log(JSON.stringify(receipt));
