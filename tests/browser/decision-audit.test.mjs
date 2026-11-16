import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  scenarioRows,
  change,
  scaleStress,
} from "../../docs/decision-audit-model.mjs";
const d = JSON.parse(
  readFileSync(new URL("../../docs/decision-audit-data.json", import.meta.url)),
);
test("UI exclusion calculations reproduce independent raw-source analysis", () => {
  for (const mode of ["baseline", "selected", "symmetric"]) {
    const rows = scenarioRows(
      d,
      mode,
      d.suspect_filings.map((r) => r.filing_id),
      2,
    );
    for (const r of rows) {
      const name = {
        baseline: "baseline",
        selected: "exclude_two_2023_filings",
        symmetric: "exclude_top_2_hours_each_year",
      }[mode];
      const ref = d.exclusion_sensitivity.find(
        (v) => v.year === r.year && v.scenario === name,
      );
      assert.equal(r.hours, ref.remaining_hours);
      assert.equal(r.cases, ref.remaining_cases);
      assert.ok(Math.abs(r.rate - ref.rate) < 1e-12);
    }
  }
  assert.ok(change(scenarioRows(d)) > 0);
  assert.ok(
    change(
      scenarioRows(
        d,
        "selected",
        d.suspect_filings.map((r) => r.filing_id),
      ),
    ) < 0,
  );
});
test("selection deduplicates IDs and symmetric rules match every precomputed k", () => {
  const id = d.suspect_filings[0].filing_id;
  assert.deepEqual(
    scenarioRows(d, "selected", [id, id]),
    scenarioRows(d, "selected", [id]),
  );
  for (const k of [...new Set(d.exposure_concentration.map((r) => r.top_n))])
    for (const row of scenarioRows(d, "symmetric", [], k)) {
      const ref = d.exposure_concentration.find(
        (r) => r.year === row.year && r.top_n === k,
      );
      assert.ok(Math.abs(row.rate - ref.rate_after_exclusion) < 1e-12);
    }
  assert.throws(() => scenarioRows(d, "invented"));
  assert.throws(() => scenarioRows(d, "selected", [999]));
  assert.throws(() => scenarioRows(d, "symmetric", [], 3));
});
test("joint scale leaves ratio invariant and moves rate inversely", () => {
  for (const r of d.suspect_filings)
    for (const factor of [0.01, 0.1, 1, 10, 100]) {
      const s = scaleStress(r, factor);
      assert.equal(s.hoursPerEmployee, r.hours / r.employees);
      assert.ok(
        Math.abs(s.rate * factor - (r.cases / r.hours) * 200000) < 1e-12,
      );
      assert.equal(s.cases, r.cases);
    }
  assert.throws(() => scaleStress(d.suspect_filings[0], 0));
});
