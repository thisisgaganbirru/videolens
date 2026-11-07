// README screenshots (docs/images/readme-*.png), taken from a local production
// build with every /api call mocked, the same approach as the web QA suite
// (docs/qa/web-app-test-cases.md). The result shown is a fixture, not a real run.
//
//   cd frontend && npm run build && npx next start -p 3016 &
//   node scripts/readme-screenshots.js docs/images      # from the repo root
//
// Needs `playwright` resolvable from this file (it is not a project
// dependency: `npm i -g playwright` or run from a machine that has it) and a
// Chromium it can launch. Light theme, 2x device scale; the desktop shots are
// clipped so the empty band under the content is not in the image.
const { chromium } = require("playwright");
const path = require("path");
const OUT = process.argv[2];
const BASE = "http://localhost:3016";

const result = {
  title: "How HTTP caching actually works",
  summary:
    "Browsers and CDNs reuse a response only when the server says they may. Cache-Control sets the rules, ETag lets a stale copy be revalidated with one cheap request, and most slow pages are slow because nobody set either.",
  transcript:
    "Every time your browser asks for a file, the server can tell it how long to keep it. That is Cache-Control. max-age is the number of seconds the copy is good for. When it runs out the browser does not throw it away, it asks the server if it changed. That is what the ETag is for. If the ETag matches, the server answers 304 and sends nothing. So a well cached site costs almost no bandwidth after the first visit. The mistake I see most is no header at all, which means the browser guesses, and it guesses short.",
  transcript_segments: [
    { start_seconds: 0, end_seconds: 6, text: "Every time your browser asks for a file, the server can tell it how long to keep it." },
    { start_seconds: 6, end_seconds: 12, text: "That is Cache-Control. max-age is the number of seconds the copy is good for." },
    { start_seconds: 12, end_seconds: 20, text: "When it runs out the browser does not throw it away, it asks the server if it changed. That is what the ETag is for." },
    { start_seconds: 20, end_seconds: 27, text: "If the ETag matches, the server answers 304 and sends nothing." },
    { start_seconds: 27, end_seconds: 35, text: "So a well cached site costs almost no bandwidth after the first visit." },
    { start_seconds: 35, end_seconds: 44, text: "The mistake I see most is no header at all, which means the browser guesses, and it guesses short." },
  ],
  screen_text:
    "Cache-Control: max-age=86400\nETag: \"5d8c72a5edda8d6a\"\nIf-None-Match: \"5d8c72a5edda8d6a\"\nHTTP/1.1 304 Not Modified",
  screen_text_segments: [
    { start_seconds: 4, end_seconds: 12, text: "Cache-Control: max-age=86400" },
    { start_seconds: 14, end_seconds: 20, text: "ETag: \"5d8c72a5edda8d6a\"" },
    { start_seconds: 20, end_seconds: 24, text: "If-None-Match: \"5d8c72a5edda8d6a\"" },
    { start_seconds: 24, end_seconds: 30, text: "HTTP/1.1 304 Not Modified" },
  ],
  markdown:
    "## Key takeaways\n\n- `Cache-Control: max-age=N` tells the browser how many seconds a response stays fresh.\n- A stale copy is **revalidated**, not discarded: the browser sends `If-None-Match` with the `ETag`.\n- A matching ETag gets `304 Not Modified` and an empty body.\n- No caching headers means the browser guesses a short lifetime.\n\n## Checklist\n\n1. Set `Cache-Control` on every static asset.\n2. Use long `max-age` plus hashed filenames for JS and CSS.\n3. Keep HTML short-lived but add an `ETag`.",
};

const run = {
  run_id: "demo-run",
  status: "complete",
  stage: null,
  result,
  source_metadata: {
    platform: "youtube",
    source_url: "https://www.youtube.com/shorts/demo",
    title: "HTTP caching in 45 seconds",
    uploader: "Backend Basics",
    uploader_url: "https://www.youtube.com/@backendbasics",
    description: "Cache-Control and ETag explained with one request.",
    upload_date: "20261028",
    like_count: 12840,
    view_count: 301552,
    comment_count: 214,
  },
  completeness: "full",
  error: null,
  source_kind: "link",
  platform: "youtube",
  duration_seconds: 45,
  thumbnail: null,
  width: 1080,
  height: 1920,
  orientation: "portrait",
};

async function mock(context) {
  await context.route("**/api/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const p = url.pathname;
    const json = (body, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (p === "/api/free-runs")
      return json({ device_token: "demo.token", enabled: true, limit: 3, used: 1, remaining: 2, resets_at: "2026-11-08T00:00:00Z" });
    if (p === "/api/capabilities")
      return json({
        state: "ok",
        mode: "distributed",
        capabilities: ["media_tools", "url_download", "analysis_engine", "run_store", "object_storage", "daily_budget"].map((name) => ({
          name, state: "ok", detail: "", probed: true,
        })),
      });
    if (p === "/api/releases") return json({ latest: null, releases: [] });
    if (p === "/api/runs" && req.method() === "POST") return json({ run_id: "demo-run", status: "queued" }, 202);
    if (p === "/api/runs") return json({ runs: [] });
    if (p === "/api/runs/demo-run") return json(run);
    return route.fulfill({ status: 404, contentType: "application/json", body: '{"detail":"not found"}' });
  });
}

async function shoot(browser, { name, viewport, shell, mobile, actions, clipHeight }) {
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 2,
    isMobile: !!mobile,
    hasTouch: !!mobile,
    colorScheme: "light",
  });
  await mock(context);
  await context.addInitScript((s) => {
    try {
      localStorage.setItem("videolens_theme", "light");
      if (s) localStorage.setItem("videolens_shell", s);
      localStorage.setItem("videolens-welcome-v1", "seen");
      localStorage.setItem("videolens-media-terms-v1", "accepted");
      sessionStorage.setItem("videolens-splash-session", "1");
      sessionStorage.setItem("videolens-welcome-session", "1");
    } catch {}
  }, shell || "");
  const page = await context.newPage();
  await actions(page);
  await page.waitForTimeout(600);
  await page.screenshot({
    path: path.join(OUT, name),
    clip: clipHeight ? { x: 0, y: 0, width: viewport.width, height: clipHeight } : undefined,
  });
  await context.close();
  console.log("wrote", name);
}

async function runDemo(page) {
  await page.goto(`${BASE}/app`, { waitUntil: "networkidle" });
  await page.fill("#media-url", "https://www.youtube.com/shorts/demo");
  await page.getByRole("button", { name: "Analyze link" }).click();
  await page.getByRole("tab", { name: /Notes|TL;DR/ }).first().waitFor({ timeout: 20000 });
  await page.waitForTimeout(800);
}

(async () => {
  const browser = await chromium.launch();
  await shoot(browser, {
    name: "readme-landing.png",
    viewport: { width: 1280, height: 800 },
    clipHeight: 740,
    actions: async (page) => page.goto(`${BASE}/`, { waitUntil: "networkidle" }),
  });
  await shoot(browser, {
    name: "readme-results.png",
    viewport: { width: 1280, height: 860 },
    clipHeight: 630,
    actions: runDemo,
  });
  await shoot(browser, {
    name: "readme-phone.png",
    viewport: { width: 390, height: 844 },
    shell: "app",
    mobile: true,
    actions: runDemo,
  });
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
