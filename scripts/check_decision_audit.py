"""Check decision audit interactions in Chromium; starts its own static server."""

import asyncio
import csv
import io
import json
import math
from pathlib import Path
from playwright.async_api import async_playwright

from browser_support import browser_target


async def main(base, out):
    async with async_playwright() as p:
        b = await p.chromium.launch()
        page = await b.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        await page.goto(base, wait_until="networkidle")
        await page.locator("#loaded").wait_for(state="visible")
        assert "+15.73%" in await page.locator("#delta-readout").inner_text()
        await page.locator("input[value=selected]").check()
        assert "-3.81%" in await page.locator("#delta-readout").inner_text()
        await page.locator('[data-exclude="2465032"]').uncheck()
        assert "-1.30%" in await page.locator("#delta-readout strong").inner_text()
        await page.locator('[data-exclude="2156121"]').uncheck()
        assert "+15.73%" in await page.locator("#delta-readout").inner_text()
        await page.locator("input[value=symmetric]").check()
        assert "-3.83%" in await page.locator("#delta-readout").inner_text()
        await page.locator("#top-k").select_option("100")
        assert "-3.94%" in await page.locator("#delta-readout").inner_text()
        await page.reload(wait_until="networkidle")
        assert await page.locator("#top-k").input_value() == "100"
        await page.locator("#scale-factor").select_option("100")
        assert "Still passes" in await page.locator("#scale-result").inner_text()
        async with page.expect_download() as d:
            await page.locator("#export-csv").click()
        await (await d.value).save_as(out / "calculation.csv")
        assert "symmetric" in (out / "calculation.csv").read_text()
        await page.locator("#review-note").fill(
            "<script>window.unwanted=1</script> Verify denominator scale."
        )
        async with page.expect_download() as d:
            await page.locator("#export-review").click()
        await (await d.value).save_as(out / "review.json")
        export = json.loads((out / "review.json").read_text())
        assert export["symmetric_top_k"] == 100
        artifact = json.loads(
            (Path(__file__).resolve().parents[1] / "docs/decision-audit-data.json").read_text()
        )
        assert export["provenance"] == artifact["provenance"]
        assert export["raw_provenance"] == artifact["raw_provenance"]
        csv_text = (out / "calculation.csv").read_text()
        rows = list(csv.DictReader(io.StringIO(
            "\n".join(line for line in csv_text.splitlines() if not line.startswith("#"))
        )))
        assert len(rows) == len(export["selected_calculation"]) == 3
        for row, annual in zip(rows, export["selected_calculation"]):
            assert {key: float(value) for key, value in row.items()} == annual
            assert math.isclose(annual["rate"], annual["cases"] * 200000 / annual["hours"])
        before, after = export["selected_calculation"][-2:]
        assert math.isclose(
            export["change_2023_2024_pct"], (after["rate"] / before["rate"] - 1) * 100
        )
        assert "<script>" in export["reviewer_note"]
        assert await page.evaluate("window.unwanted") is None
        await page.locator("#reset").click()
        assert "+15.73%" in await page.locator("#delta-readout").inner_text()
        for width in [1440, 390, 320]:
            await page.set_viewport_size({"width": width, "height": 1000})
            await page.wait_for_timeout(200)
            assert not await page.evaluate("document.documentElement.scrollWidth>innerWidth")
            await page.screenshot(path=str(out / f"audit-{width}.png"), full_page=True)
        fail = await b.new_page()
        await fail.route(
            "**/decision-audit-data.json", lambda r: r.fulfill(status=503, body="unavailable")
        )
        await fail.goto(base)
        await fail.wait_for_function(
            "document.querySelector('#load-status').textContent.includes('could not be loaded')"
        )
        assert await fail.locator("#loaded").is_hidden()
        assert not errors, errors
        print(
            "PASS: exact trend, individual exclusions, symmetric top-k, URL, scaling, exports, note safety, responsive and load failure"
        )
        await b.close()


if __name__ == "__main__":
    with browser_target("decision-audit.html", "AUDIT_URL") as target:
        asyncio.run(main(*target))
