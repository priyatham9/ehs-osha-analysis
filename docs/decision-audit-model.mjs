export function scenarioRows(data, mode = "baseline", excluded = [], topK = 2) {
  if (!["baseline", "selected", "symmetric"].includes(mode))
    throw new RangeError("Unknown inclusion rule");
  const selected = new Set(excluded.map(Number));
  if (
    [...selected].some(
      (id) => !data.suspect_filings.some((r) => r.filing_id === id),
    )
  )
    throw new RangeError("Unknown filing");
  return data.annual_rates
    .filter((r) => r.year >= 2022)
    .map((r) => {
      let hours = 0,
        cases = 0,
        count = 0;
      if (mode === "selected" && r.year === 2023) {
        const records = data.suspect_filings.filter((v) =>
          selected.has(v.filing_id),
        );
        hours = records.reduce((s, v) => s + v.hours, 0);
        cases = records.reduce((s, v) => s + v.cases, 0);
        count = records.length;
      }
      if (mode === "symmetric") {
        const c = data.exposure_concentration.find(
          (v) => v.year === r.year && v.top_n === topK,
        );
        if (!c) throw new RangeError("Unsupported deletion count");
        hours = c.excluded_hours;
        cases = c.excluded_cases;
        count = topK;
      }
      const remainingHours = r.hours - hours,
        remainingCases = r.cases - cases;
      if (remainingHours <= 0 || remainingCases < 0)
        throw new RangeError("Invalid remainder");
      return {
        year: r.year,
        filings: r.n_filings - count,
        cases: remainingCases,
        hours: remainingHours,
        rate: (remainingCases / remainingHours) * 200000,
        removedHours: hours,
        removedCases: cases,
        removedFilings: count,
      };
    });
}
export function change(rows, before = 2023, after = 2024) {
  const a = rows.find((r) => r.year === before),
    b = rows.find((r) => r.year === after);
  if (!a || !b || a.rate <= 0) throw new RangeError("Missing comparison");
  return (b.rate / a.rate - 1) * 100;
}
export function scaleStress(row, factor) {
  if (!Number.isFinite(factor) || factor <= 0)
    throw new RangeError("Scale must be positive");
  return {
    hours: row.hours * factor,
    employees: row.employees * factor,
    cases: row.cases,
    hoursPerEmployee: row.hours / row.employees,
    rate: (row.cases / (row.hours * factor)) * 200000,
  };
}
