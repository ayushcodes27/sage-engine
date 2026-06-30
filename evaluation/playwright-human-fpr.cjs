const fs = require("fs");
const path = require("path");
const { chromium } = require("@playwright/test");

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8083";
const JOURNEYS = Number(process.env.JOURNEYS || 100);
const MIN_REQUESTS_PER_JOURNEY = Number(process.env.MIN_REQUESTS_PER_JOURNEY || 30);
const MAX_ACTIONS_PER_JOURNEY = Number(process.env.MAX_ACTIONS_PER_JOURNEY || 45);
const CONCURRENCY = Number(process.env.CONCURRENCY || 1);
const MAX_FPR = Number(process.env.MAX_FPR || 0.01);
const HEADLESS = process.env.HEADED !== "1";
const REPORT_DIR = path.join(__dirname, "reports");

const BLOCKED_STATUSES = new Set([403, 429, 500, 502, 503, 504]);

function randomHumanIp(index) {
  return `192.168.${20 + (index % 40)}.${10 + (index % 220)}`;
}

function randomProductId() {
  return 1 + Math.floor(Math.random() * 50);
}

function delay(minMs, maxMs) {
  const duration = minMs + Math.random() * (maxMs - minMs);
  return new Promise((resolve) => setTimeout(resolve, duration));
}

async function humanPause(page, minMs = 700, maxMs = 2200) {
  const viewport = page.viewportSize() || { width: 1280, height: 720 };
  await page.mouse.move(
    Math.floor(Math.random() * viewport.width),
    Math.floor(Math.random() * viewport.height),
    { steps: 5 + Math.floor(Math.random() * 15) }
  );
  await delay(minMs, maxMs);
}

async function safeGoto(page, url) {
  const response = await page.goto(url, {
    waitUntil: "domcontentloaded",
    timeout: 20000,
  });

  await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
  return response;
}

async function runJourney(browser, index) {
  const ip = randomHumanIp(index);
  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 },
    extraHTTPHeaders: {
      "X-Forwarded-For": ip,
      "User-Agent": `Mozilla/5.0 HumanBrowser Playwright/${index}`,
    },
  });

  const page = await context.newPage();
  const blocked = [];
  const seenResponses = [];
  const actions = [];

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
    await safeGoto(page, `${GATEWAY_URL}/`);
    actions.push("/");
    await humanPause(page, 1000, 2800);

    for (
      let actionCount = 0;
      seenResponses.length < MIN_REQUESTS_PER_JOURNEY && actionCount < MAX_ACTIONS_PER_JOURNEY;
      actionCount += 1
    ) {
      const productId = randomProductId();
      const actionRoll = Math.random();

      if (actionRoll < 0.34) {
        await safeGoto(page, `${GATEWAY_URL}/products/${productId}`);
        actions.push(`/products/${productId}`);
        await humanPause(page, 900, 2600);
        continue;
      }

      if (actionRoll < 0.54) {
        await safeGoto(page, `${GATEWAY_URL}/api/price/${productId}`);
        actions.push(`/api/price/${productId}`);
        await humanPause(page, 700, 2200);
        continue;
      }

      if (actionRoll < 0.70) {
        await safeGoto(page, `${GATEWAY_URL}/api/inventory/${productId}`);
        actions.push(`/api/inventory/${productId}`);
        await humanPause(page, 900, 2600);
        continue;
      }

      if (actionRoll < 0.84) {
        const terms = ["pro", "smart", "classic", "eco", "premium"];
        const q = terms[Math.floor(Math.random() * terms.length)];
        await safeGoto(page, `${GATEWAY_URL}/api/search?q=${encodeURIComponent(q)}`);
        actions.push(`/api/search?q=${q}`);
        await humanPause(page, 1000, 2800);
        continue;
      }

      if (actionRoll < 0.94) {
        await safeGoto(page, `${GATEWAY_URL}/cart`);
        actions.push("/cart");
        await humanPause(page, 1200, 3200);
        continue;
      }

      await page.evaluate(async () => {
        await fetch("/checkout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source: "playwright-human-fpr" }),
        });
      });
      actions.push("/checkout");
      await humanPause(page, 1200, 3000);
    }
  } catch (error) {
    blocked.push({
      status: "ERROR",
      method: "BROWSER",
      url: error.message,
    });
  } finally {
    await context.close();
  }

  return {
    index,
    ip,
    requestCount: seenResponses.length,
    actionCount: actions.length,
    reachedRequestThreshold: seenResponses.length >= MIN_REQUESTS_PER_JOURNEY,
    blockedCount: blocked.length,
    blocked,
    actions,
  };
}

async function main() {
  fs.mkdirSync(REPORT_DIR, { recursive: true });

  console.log(`Gateway: ${GATEWAY_URL}`);
  console.log(`Journeys: ${JOURNEYS}`);
  console.log(`Min requests per journey: ${MIN_REQUESTS_PER_JOURNEY}`);
  console.log(`Max actions per journey: ${MAX_ACTIONS_PER_JOURNEY}`);
  console.log(`Concurrency: ${CONCURRENCY}`);
  console.log(`Allowed max journey FPR: ${(MAX_FPR * 100).toFixed(2)}%`);

  const browser = await chromium.launch({ headless: HEADLESS });
  const results = [];

  try {
    for (let batchStart = 0; batchStart < JOURNEYS; batchStart += CONCURRENCY) {
      const batchEnd = Math.min(batchStart + CONCURRENCY, JOURNEYS);
      const batch = [];

      for (let i = batchStart; i < batchEnd; i += 1) {
        batch.push(runJourney(browser, i));
      }

      const batchResults = await Promise.all(batch);
      results.push(...batchResults);

      for (const result of batchResults) {
        if (result.blockedCount > 0) {
          const first = result.blocked[0];
          console.log(
            `FALSE POSITIVE journey=${result.index + 1} ip=${result.ip} first=${first.status} ${first.method} ${first.url}`
          );
        }
      }

      console.log(`Completed ${results.length}/${JOURNEYS} journeys`);
    }
  } finally {
    await browser.close();
  }

  const blockedJourneys = results.filter((result) => result.blockedCount > 0).length;
  const thresholdJourneys = results.filter((result) => result.reachedRequestThreshold).length;
  const totalRequests = results.reduce((sum, result) => sum + result.requestCount, 0);
  const blockedRequests = results.reduce((sum, result) => sum + result.blockedCount, 0);
  const journeyFpr = blockedJourneys / JOURNEYS;
  const requestFpr = totalRequests === 0 ? 0 : blockedRequests / totalRequests;

  const summary = {
    gatewayUrl: GATEWAY_URL,
    journeys: JOURNEYS,
    minRequestsPerJourney: MIN_REQUESTS_PER_JOURNEY,
    concurrency: CONCURRENCY,
    thresholdJourneys,
    blockedJourneys,
    journeyFpr,
    totalRequests,
    blockedRequests,
    requestFpr,
    maxFpr: MAX_FPR,
    passed: journeyFpr <= MAX_FPR,
    generatedAt: new Date().toISOString(),
  };

  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const reportPath = path.join(REPORT_DIR, `playwright-human-fpr-${timestamp}.json`);
  fs.writeFileSync(reportPath, JSON.stringify({ summary, results }, null, 2));

  console.log("\n=== Playwright Human FPR Summary ===");
  console.log(`Human journeys: ${summary.journeys}`);
  console.log(`Journeys crossing request threshold: ${summary.thresholdJourneys}`);
  console.log(`Blocked journeys: ${summary.blockedJourneys}`);
  console.log(`Journey FPR: ${(summary.journeyFpr * 100).toFixed(2)}%`);
  console.log(`Gateway requests observed: ${summary.totalRequests}`);
  console.log(`Blocked requests: ${summary.blockedRequests}`);
  console.log(`Request FPR: ${(summary.requestFpr * 100).toFixed(2)}%`);
  console.log(`Report: ${reportPath}`);

  if (!summary.passed) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
