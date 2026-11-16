/* Run with Playwright installed: node scripts/check_explore_ui.cjs [base URL]
 * Serve docs first: python3 -m http.server 8763 --directory docs
 * Artifacts stay outside the repository unless EHS_UI_ARTIFACTS is set. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const base = process.argv[2] || "http://localhost:8763";
const out = process.env.EHS_UI_ARTIFACTS || "/tmp/ehs-explorer-ui";
(async () => {
  await fs.mkdir(out, { recursive: true });
  const data = JSON.parse(
    await fs.readFile(
      path.join(__dirname, "../docs/explore-data.json"),
      "utf8",
    ),
  );
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1100 },
    permissions: ["clipboard-read", "clipboard-write"],
  });
  const page = await context.newPage(),
    errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  async function loaded(url) {
    await page.goto(url);
    await page.locator("#ev-content").waitFor({ state: "visible" });
    await page.locator("#bandChart svg").waitFor();
    await page.waitForTimeout(220);
  }
  async function values() {
    return page
      .locator("#ev-table tbody tr")
      .first()
      .locator("td")
      .allTextContents();
  }
  await loaded(base + "/explore.html");
  assert.equal(await page.locator("#ev-chart button").count(), 9);
  assert.equal(await page.locator("#trirN").innerText(), "6.67");
  assert.equal(await page.locator("#ev-inspector-title").innerText(), "2019");
  // Chart click -> inspector, exact underlying values, URL, and scoped export.
  await page.locator('[data-year="2024"]').click();
  assert.equal(await page.locator("#ev-inspector-title").innerText(), "2024");
  const row2024 = data.quality_by_year.find((r) => r.year === 2024);
  assert.deepEqual(await values(), Object.values(row2024).map(String));
  assert.equal(new URL(page.url()).searchParams.get("period"), "2024");
  const csvEvent = page.waitForEvent("download");
  await page.locator("#ev-csv").click();
  const csvDownload = await csvEvent;
  const csvPath = path.join(out, csvDownload.suggestedFilename());
  await csvDownload.saveAs(csvPath);
  const csv = await fs.readFile(csvPath, "utf8");
  assert.ok(csv.includes('"0.92415725"'));
  assert.ok(csv.includes("quality_by_year.csv"));
  assert.equal(csv.trim().split("\r\n").length, 2);
  await page.locator('[data-metric="share"]').click();
  assert.equal(
    await page.locator('[data-metric="share"]').getAttribute("aria-pressed"),
    "true",
  );
  assert.ok(
    (
      await page.locator('[data-year="2024"]').getAttribute("aria-label")
    ).includes("92.42%"),
  );
  // Keyboard year selection retains focus after reactive redraw.
  await page.locator('[data-year="2020"]').focus();
  await page.keyboard.press("Enter");
  assert.equal(await page.locator("#ev-inspector-title").innerText(), "2020");
  assert.equal(
    await page.evaluate(() => document.activeElement.dataset.year),
    "2020",
  );
  await page.keyboard.press("Tab");
  assert.equal(
    await page.evaluate(() => document.activeElement.dataset.year),
    "2021",
  );
  await page.locator('[data-table="annual"]').click();
  assert.equal(await page.locator("#ev-table tbody tr").count(), 9);
  const annualEvent = page.waitForEvent("download");
  await page.locator("#ev-csv").click();
  const annual = await annualEvent;
  await annual.saveAs(path.join(out, annual.suggestedFilename()));
  assert.equal(
    (await fs.readFile(path.join(out, annual.suggestedFilename()), "utf8"))
      .trim()
      .split("\r\n").length,
    10,
  );
  // Pooled scope uses its own committed row, not a mean of yearly rates.
  await page.locator("#ev-period").selectOption("pooled");
  await page.locator('[data-table="selected"]').click();
  assert.equal((await values())[1], String(data.pooled.n_filings));
  assert.equal((await values())[7], String(data.pooled.ratio));
  const noteEvent = page.waitForEvent("download");
  await page.locator("#ev-note").click();
  const note = await noteEvent;
  await note.saveAs(path.join(out, note.suggestedFilename()));
  const noteText = await fs.readFile(
    path.join(out, note.suggestedFilename()),
    "utf8",
  );
  assert.ok(noteText.includes("quality_overall.csv"));
  assert.ok(noteText.includes("No causal inference is supported."));
  assert.ok(noteText.includes("0.13406167"));
  await page.locator("#ev-copy").click();
  await page.waitForTimeout(250);
  assert.equal(
    await page.evaluate(() => navigator.clipboard.readText()),
    page.url(),
  );
  // Restore both evidence scope and site inputs from a view link.
  const shared = page.url();
  await page.reload();
  await page.locator("#ev-content").waitFor({ state: "visible" });
  assert.equal(await page.locator("#ev-period").inputValue(), "pooled");
  assert.equal(
    await page.locator('[data-metric="share"]').getAttribute("aria-pressed"),
    "true",
  );
  await page.locator('[data-year="2022"]').click();
  await page.goBack();
  assert.equal(await page.locator("#ev-period").inputValue(), "pooled");
  // Existing calculator, typo screen, validation, and reset still work.
  await page.waitForTimeout(250);
  await page.locator("#btnTypo").click();
  await page.waitForTimeout(200);
  assert.ok(
    (await page.locator("#hpeS").innerText())
      .toLowerCase()
      .includes("fails the screen"),
    (await page.locator("#hpeS").innerText()) + " " + page.url(),
  );
  await page.locator("#btnReset").click();
  assert.equal(await page.locator("#trirN").innerText(), "6.67");
  assert.equal(await page.locator("#ev-period").inputValue(), "pooled");
  await page.locator("#inCases").fill("-1");
  await page.waitForTimeout(950);
  assert.ok(
    (await page.locator("#announce").textContent()).includes(
      "No rate available",
    ),
  );
  assert.equal(
    await page.locator("#inCases").getAttribute("aria-invalid"),
    "true",
  );
  await page.locator("#btnReset").click();
  await page.locator("#naicsCode").fill("abc");
  assert.equal(
    await page.locator("#naicsCode").getAttribute("aria-invalid"),
    "true",
  );
  await page.locator("#btnReset").click();
  await loaded(base + "/explore.html?y=2024");
  assert.equal(await page.locator("#ev-period").inputValue(), "2024");
  await page.reload();
  await page.locator("#ev-content").waitFor({ state: "visible" });
  assert.equal(await page.locator("#ev-period").inputValue(), "2024");
  // Desktop, narrow mobile, and dark-theme visual artifacts; horizontal overflow is confined to table.
  await loaded(base + "/explore.html?period=2019");
  await page.screenshot({
    path: path.join(out, "desktop.png"),
    fullPage: true,
  });
  await page.locator("#ev-theme").click();
  assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
  await page.screenshot({
    path: path.join(out, "desktop-dark.png"),
    fullPage: true,
  });
  await page.locator("#ev-theme").click();
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.waitForTimeout(250);
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    await page.screenshot({
      path: path.join(out, "mobile-" + width + ".png"),
      fullPage: true,
    });
  }
  // Broken data gives a useful failure state and leaves exports unavailable.
  const failure = await context.newPage();
  await failure.route("**/explore-data.json", (r) =>
    r.fulfill({ status: 503, body: "unavailable" }),
  );
  await failure.goto(base + "/explore.html");
  await failure.waitForFunction(() =>
    document.getElementById("ev-error").textContent.includes("could not load"),
  );
  assert.equal(await failure.locator("#ev-csv").isDisabled(), true);
  await failure.close();
  assert.deepEqual(errors, []);
  console.log(
    "PASS: aggregate fidelity, chart and keyboard selection, CSV/review exports, pooled scope, share/back/reload, peer calculator, validation, legacy URL, responsive layouts, dark theme, and load failure. Artifacts: " +
      out,
  );
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
