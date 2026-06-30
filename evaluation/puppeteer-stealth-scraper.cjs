const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer-extra");
const StealthPlugin = require("puppeteer-extra-plugin-stealth");

puppeteer.use(StealthPlugin());

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8083";
const SESSIONS = Number(process.env.SESSIONS || 60);
const MIN_REQUESTS_PER_SESSION = Number(process.env.MIN_REQUESTS_PER_SESSION || 25);
const MAX_ACTIONS_PER_SESSION = Number(process.env.MAX_ACTIONS_PER_SESSION || 40);
const CONCURRENCY = Number(process.env.CONCURRENCY || 5);
const REQUIRE_THRESHOLD = process.env.REQUIRE_THRESHOLD !== "0";
const HEADLESS = process.env.HEADED !== "1";
const REPORT_DIR = path.join(__dirname, "reports");

const BLOCKED_STATUSES = new Set([403, 429, 500, 502, 503, 504]);

function scraperIp(index) {
  return `172.16.${30 + (index % 80)}.${20 + (index % 200)}`;
}

function randomProductId() {
  return 1 + Math.floor(Math.random() * 50);
}

function delay(minMs, maxMs) {
  const duration = minMs + Math.random() * (maxMs - minMs);
  return new Promise((resolve) => setTimeout(resolve, duration));
}

async function scraperPause(page, minMs = 250, maxMs = 950) {
  const viewport = page.viewport() || { width: 1366, height: 768 };
  await page.mouse.move(
    Math.floor(Math.random() * viewport.width),
    Math.floor(Math.random() * viewport.height),
    { steps: 2 + Math.floor(Math.random() * 6) }
  );
  await delay(minMs, maxMs);
}

async function safeGoto(page, url) {
  const response = await page.goto(url, {
    waitUntil: "domcontentloaded",
    timeout: 20000,
  });

  await page.waitForNetworkIdle({ idleTime: 350, timeout: 5000 }).catch(() => {});
  return response;
}

async function runSession(browser, index) {
  const ip = scraperIp(index);
  const page = await browser.newPage();
  const blocked = [];
  const seenResponses = [];
  const actions = [];

  await page.setViewport({ width: 1366, height: 768 });
  await page.setExtraHTTPHeaders({
    "X-Forwarded-For": ip,
    "Accept-Language": "en-US,en;q=0.9",
  });
  await page.setUserAgent(
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
  );

  page.on("response", (response) => {
    const url = response.url();
    if (!url.startsWith(GATEWAY_URL)) return;

    const record = {
      status: response.status(),
      method: response.request().method(),
      url,
    };

    seenResponses.push(record);

    if (BLOCKED_STATUSES.has(record.status)) {
      blocked.push(record);
    }
  });

  try {
    // Load the landing page once to fetch assets and reduce obvious asset-skip signals.
    await safeGoto(page, `${GATEWAY_URL}/`);
    actions.push("/");
    await scraperPause(page, 700, 1600);

    for (
      let actionCount = 0;
      seenResponses.length < MIN_REQUESTS_PER_SESSION && actionCount < MAX_ACTIONS_PER_SESSION;
      actionCount += 1
    ) {
      const productId = randomProductId();
      const roll = Math.random();

      if (roll < 0.52) {
        await safeGoto(page, `${GATEWAY_URL}/products/${productId}`);
        actions.push(`/products/${productId}`);
        await scraperPause(page, 250, 850);
        continue;
      }

      if (roll < 0.72) {
        await safeGoto(page, `${GATEWAY_URL}/api/price/${productId}`);
        actions.push(`/api/price/${productId}`);
        await scraperPause(page, 180, 700);
        continue;
      }

      if (roll < 0.88) {
        await safeGoto(page, `${GATEWAY_URL}/api/inventory/${productId}`);
        actions.push(`/api/inventory/${productId}`);
        await scraperPause(page, 180, 700);
        continue;
      }

      const terms = ["pro", "smart", "classic", "eco", "premium"];
      const q = terms[Math.floor(Math.random() * terms.length)];
      await safeGoto(page, `${GATEWAY_URL}/api/search?q=${encodeURIComponent(q)}`);
      actions.push(`/api/search?q=${q}`);
      await scraperPause(page, 300, 950);
    }
  } catch (error) {
    blocked.push({
      status: "ERROR",
      method: "BROWSER",
      url: error.message,
    });
  } finally {
    await page.close().catch(() => {});
  }

  return {
    index,
    ip,
    requestCount: seenResponses.length,
    actionCount: actions.length,
    reachedRequestThreshold: seenResponses.length >= MIN_REQUESTS_PER_SESSION,
    blockedCount: blocked.length,
    detected: blocked.length > 0,
    firstBlock: blocked[0] || null,
    blocked,
    actions,
  };
}

async function main() {
  fs.mkdirSync(REPORT_DIR, { recursive: true });

  console.log(`Gateway: ${GATEWAY_URL}`);
  console.log(`Stealth scraper sessions: ${SESSIONS}`);
  console.log(`Min requests per session: ${MIN_REQUESTS_PER_SESSION}`);
  console.log(`Max actions per session: ${MAX_ACTIONS_PER_SESSION}`);
  console.log(`Concurrency: ${CONCURRENCY}`);
  console.log(`Require all sessions to cross threshold: ${REQUIRE_THRESHOLD}`);

  const browser = await puppeteer.launch({
    headless: HEADLESS,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  const results = [];

  try {
    for (let batchStart = 0; batchStart < SESSIONS; batchStart += CONCURRENCY) {
      const batchEnd = Math.min(batchStart + CONCURRENCY, SESSIONS);
      const batch = [];

      for (let i = batchStart; i < batchEnd; i += 1) {
        batch.push(runSession(browser, i));
      }

      const batchResults = await Promise.all(batch);
      results.push(...batchResults);

      for (const result of batchResults) {
        if (!result.reachedRequestThreshold) {
          console.log(
            `UNDER THRESHOLD session=${result.index + 1} ip=${result.ip} requests=${result.requestCount} actions=${result.actionCount}`
          );
        }

        if (result.detected) {
          const first = result.firstBlock;
          console.log(
            `DETECTED session=${result.index + 1} ip=${result.ip} first=${first.status} ${first.method} ${first.url}`
          );
        }
      }

      console.log(`Completed ${results.length}/${SESSIONS} sessions`);
    }
  } finally {
    await browser.close();
  }

  const detectedSessions = results.filter((result) => result.detected).length;
  const thresholdSessions = results.filter((result) => result.reachedRequestThreshold).length;
  const totalRequests = results.reduce((sum, result) => sum + result.requestCount, 0);
  const blockedRequests = results.reduce((sum, result) => sum + result.blockedCount, 0);
  const sessionBlockRate = detectedSessions / SESSIONS;
  const requestBlockRate = totalRequests === 0 ? 0 : blockedRequests / totalRequests;

  const summary = {
    gatewayUrl: GATEWAY_URL,
    sessions: SESSIONS,
    minRequestsPerSession: MIN_REQUESTS_PER_SESSION,
    maxActionsPerSession: MAX_ACTIONS_PER_SESSION,
    concurrency: CONCURRENCY,
    requireThreshold: REQUIRE_THRESHOLD,
    thresholdSessions,
    detectedSessions,
    sessionBlockRate,
    totalRequests,
    blockedRequests,
    requestBlockRate,
    generatedAt: new Date().toISOString(),
  };

  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const reportPath = path.join(REPORT_DIR, `puppeteer-stealth-scraper-${timestamp}.json`);
  fs.writeFileSync(reportPath, JSON.stringify({ summary, results }, null, 2));

  console.log("\n=== Puppeteer Stealth Scraper Summary ===");
  console.log(`Scraper sessions: ${summary.sessions}`);
  console.log(`Sessions crossing request threshold: ${summary.thresholdSessions}`);
  console.log(`Detected sessions: ${summary.detectedSessions}`);
  console.log(`Session block rate: ${(summary.sessionBlockRate * 100).toFixed(2)}%`);
  console.log(`Gateway requests observed: ${summary.totalRequests}`);
  console.log(`Blocked requests: ${summary.blockedRequests}`);
  console.log(`Request block rate: ${(summary.requestBlockRate * 100).toFixed(2)}%`);
  console.log(`Report: ${reportPath}`);

  if (REQUIRE_THRESHOLD && thresholdSessions !== SESSIONS) {
    console.error(
      `ERROR: ${SESSIONS - thresholdSessions} sessions did not reach ${MIN_REQUESTS_PER_SESSION} observed gateway requests. ` +
        "Increase MAX_ACTIONS_PER_SESSION or lower concurrency before documenting this run."
    );
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
