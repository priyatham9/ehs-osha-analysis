"""Exercise local-file review, export safety, and state transitions in Chromium.

Requires Playwright. Starts an isolated local server unless --base-url is supplied.
No private fixture data are used.
"""

import asyncio
import csv
import hashlib
import io
import json

from playwright.async_api import async_playwright

from browser_support import browser_target


async def upload(page, csv):
    await page.locator("#csv-file").set_input_files(
        {"name": "local-test.csv", "mimeType": "text/csv", "buffer": csv.encode("utf-8")}
    )
    await page.wait_for_function(
        "() => !document.querySelector('#file-status').textContent.includes('Reading')"
    )


async def check_source_bound_restore(page, out):
    # BOM/CRLF are part of the fingerprint. Include another period and a
    # screen-rejected row to prove that the viewing filter is not export scope.
    source = (
        "\ufeffyear,filing_id,employees,hours,cases\r\n"
        "2022,old,100,200000,1\r\n"
        "2023,A,100,200000,4\r\n"
        "2023,B,1000,2000000,0\r\n"
        "2023,rejected,100,1,0\r\n"
        "2024,C,100,200000,3\r\n"
        "2024,D,100,200000,3\r\n"
    )
    await upload(page, source)
    await page.locator('#records input[data-key="row:4"]').check()
    await page.locator("#review-note").fill("Review source scale before deciding.")
    await page.locator("#record-filter").select_option("selected")
    assert await page.locator("#records tr").count() == 1
    async with page.expect_download() as pending:
        await page.locator("#export-json").click()
    await (await pending.value).save_as(out / "source-bound-review.json")
    review = json.loads((out / "source-bound-review.json").read_text())
    assert review["source"]["sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert review["comparison"]["reviewChangePct"] == -25
    async with page.expect_download() as pending:
        await page.locator("#export-csv").click()
    await (await pending.value).save_as(out / "filtered-view.csv")
    rows = list(csv.reader(io.StringIO((out / "filtered-view.csv").read_text())))
    assert len(rows) == 6  # Header and all five selected-period records.
    assert any("rejected" in row for row in rows)
    assert not any("old" in row for row in rows)
    await page.locator("#reset-review").click()
    forged = {
        **review,
        "comparison": {"reviewChangePct": 999999},
        "annual": [{"year": 2023, "rate": 999999}],
        "excluded_records": [
            {**row, "cases": 999999, "hours": 1} for row in review["excluded_records"]
        ],
    }
    await page.locator("#review-file").set_input_files({
        "name": "altered-stored-results.json", "mimeType": "application/json",
        "buffer": json.dumps(forged).encode(),
    })
    await page.wait_for_function(
        "() => document.querySelector('#file-status').textContent.includes('all results recomputed')"
    )
    assert await page.locator("#review-change").inner_text() == "-25.00%"
    assert await page.locator("#review-note").input_value() == review["reviewer_note"]
    assert await page.locator("#record-filter").input_value() == "all"
    before = await page.locator("#ledger").inner_text()
    await page.locator("#review-file").set_input_files({
        "name": "mismatched-source.json", "mimeType": "application/json",
        "buffer": json.dumps({**review, "source": {"sha256": "f" * 64}}).encode(),
    })
    await page.wait_for_function(
        "() => document.querySelector('#error').textContent.includes('different source file')"
    )
    assert await page.locator("#ledger").inner_text() == before
    assert await page.locator("#review-change").inner_text() == "-25.00%"


async def main(base, out):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        await page.goto(base, wait_until="networkidle")
        requests = []
        page.on("request", lambda r: requests.append((r.method, r.url)))
        await page.locator("#example").click()
        await page.locator("#results").wait_for(state="visible")
        assert await page.locator("#base-change").inner_text() == "+585.71%"
        await page.locator("#records input").first.check()
        assert await page.locator("#review-change").inner_text() == "-25.00%"
        assert "-25.00%" in await page.locator("#scenario-consequence").inner_text()
        await page.locator("#records tr").last.scroll_into_view_if_needed()
        assert await page.locator(".review-controls").evaluate(
            "(e) => e.getBoundingClientRect().top >= -1"
        )
        await page.locator("#review-selected").click()
        assert await page.locator("#records input").count() == 1
        await page.locator("#record-filter").select_option("all")
        await page.locator("summary").first.click()
        assert "2,400,000.00" in await page.locator("#ledger").inner_text()
        await page.locator("#review-note").fill("<script>window.changed=1</script> Verify units.")
        async with page.expect_download() as pending:
            await page.locator("#export-json").click()
        await (await pending.value).save_as(out / "review.json")
        review = json.loads((out / "review.json").read_text())
        assert review["comparison"]["reviewChangePct"] == -25
        assert len(review["excluded_records"]) == 1
        example = "year,filing_id,employees,hours,cases\n"
        for year in [2023, 2024]:
            for i in range(1, 13):
                example += f"{year},example-{year}-{i},100,200000,{4 if year == 2023 else 3}\n"
        example += "2023,example-scale-review,10000,20000000,1\n"
        assert review["source"]["sha256"] == hashlib.sha256(example.encode()).hexdigest()
        assert review["annual"][0]["reviewHours"] == 2400000
        assert "<script>" in review["reviewer_note"]
        assert await page.evaluate("window.changed") is None
        await page.locator("#reset-review").click()
        await page.locator("#review-file").set_input_files(str(out / "review.json"))
        await page.wait_for_function(
            "() => document.querySelector('#file-status').textContent.includes('source SHA-256 matched')"
        )
        assert await page.locator("#review-change").inner_text() == "-25.00%"
        assert "<script>" in await page.locator("#review-note").input_value()
        tampered = dict(review)
        tampered["source"] = {**review["source"], "sha256": "b" * 64}
        await page.locator("#review-file").set_input_files(
            {
                "name": "wrong-source.json",
                "mimeType": "application/json",
                "buffer": json.dumps(tampered).encode(),
            }
        )
        await page.wait_for_function(
            "() => document.querySelector('#error').textContent.includes('different source file')"
        )
        assert await page.locator("#review-change").inner_text() == "-25.00%"

        await check_source_bound_restore(page, out)

        await page.locator("#low").fill("")
        assert await page.locator("#results").is_hidden()
        await upload(page, "year,employees,hours,cases\n2023,10,20000,1\n2024,10,20000,2\n")
        assert await page.locator("#error").is_visible()
        await page.locator("#low").fill("120")
        await page.locator("button[type=submit]").click()
        assert await page.locator("#base-change").inner_text() == "+100.00%"
        await upload(
            page,
            "year,filing_id,employees,hours,cases\n2023,=1+1,1,2000,0\n2024,<img src=x onerror=alert(1)>,1,2000,1\n",
        )
        assert await page.locator("#base-change").inner_text() == "Not defined"
        assert "Δ 100.000" in await page.locator("#base-rates").inner_text()
        assert await page.locator("#records img").count() == 0
        async with page.expect_download() as pending:
            await page.locator("#export-csv").click()
        await (await pending.value).save_as(out / "influence.csv")
        assert "'=1+1" in (out / "influence.csv").read_text()
        await page.locator("#records input").first.check()
        assert await page.locator("#review-change").inner_text() == "Not defined"
        assert "no remaining exposure" in await page.locator("#finding").inner_text()
        await upload(page, "year,employees,hours,cases\n2023,10,20000,0.5\n2024,10,20000,2\n")
        assert await page.locator("#error").is_visible()
        assert await page.locator("#results").is_hidden()
        await page.locator("#example").click()
        await page.locator("#results").wait_for(state="visible")
        for width in [1440, 390, 320]:
            await page.set_viewport_size({"width": width, "height": 1000})
            assert not await page.evaluate("document.documentElement.scrollWidth > innerWidth")
            await page.screenshot(path=str(out / f"denominator-{width}.png"), full_page=True)
        await page.locator("#clear").click()
        assert await page.locator("#results").is_hidden()
        assert await page.locator("#csv-file").input_value() == ""
        assert await page.locator("#records").inner_text() == ""
        assert await page.locator("#review-note").input_value() == ""
        assert await page.locator("#review-file").input_value() == ""
        assert await page.locator("#restore-review").is_disabled()
        csp = await page.locator('meta[http-equiv="Content-Security-Policy"]').get_attribute("content")
        assert "connect-src 'none'" in csp
        assert not requests, requests
        assert not errors, errors
        print(
            "PASS: local import, exclusion arithmetic, ledger, exports, injection safety, invalid/zero states, responsive layout, no network requests, clear"
        )
        await browser.close()


if __name__ == "__main__":
    with browser_target("denominator-audit.html", "DENOMINATOR_URL") as target:
        asyncio.run(main(*target))
