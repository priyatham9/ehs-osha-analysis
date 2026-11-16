import { scenarioRows, change, scaleStress } from "./decision-audit-model.mjs";
const $ = (s) => document.querySelector(s);
const int = (n) => n.toLocaleString("en-US", { maximumFractionDigits: 0 });
const dec = (n, d = 2) =>
  n.toLocaleString("en-US", {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
const sign = (n) => (n > 0 ? "+" : "") + dec(n) + "%";
const esc = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
let data,
  mode = "baseline",
  selected = new Set(),
  topK = 2;
function readState() {
  const q = new URLSearchParams(location.search);
  mode = ["selected", "symmetric"].includes(q.get("rule"))
    ? q.get("rule")
    : "baseline";
  const ids = q.has("exclude")
    ? q.get("exclude").split(",").map(Number)
    : data.suspect_filings.map((r) => r.filing_id);
  selected = new Set(
    ids.filter((id) => data.suspect_filings.some((r) => r.filing_id === id)),
  );
  const k = Number(q.get("k"));
  topK =
    data.exposure_concentration.some((r) => r.top_n === k) && k > 0 ? k : 2;
}
function syncState() {
  const u = new URL(location.href);
  u.searchParams.set("rule", mode);
  u.searchParams.set("exclude", [...selected].join(","));
  u.searchParams.set("k", topK);
  history.replaceState(null, "", u);
}
function resultRows() {
  return scenarioRows(data, mode, [...selected], topK);
}
function render() {
  document
    .querySelectorAll("[name=scenario]")
    .forEach((e) => (e.checked = e.value === mode));
  $("#record-controls").hidden = mode !== "selected";
  $("#top-controls").hidden = mode !== "symmetric";
  $("#top-k").value = topK;
  document
    .querySelectorAll("[data-exclude]")
    .forEach((e) => (e.checked = selected.has(Number(e.dataset.exclude))));
  const rows = resultRows();
  renderChart(rows);
  const r23 = rows.find((r) => r.year === 2023),
    r24 = rows.find((r) => r.year === 2024);
  const casesChange = (r24.cases / r23.cases - 1) * 100;
  const hoursChange = (r24.hours / r23.hours - 1) * 100;
  $("#numerator-context").innerHTML =
    `<strong>Read numerator and denominator together.</strong> Under this rule, included cases change ${sign(casesChange)} and included hours change ${sign(hoursChange)} from 2023 to 2024. A rate can rise while reported case counts fall.`;
  const delta = change(rows);
  $("#delta-readout").innerHTML =
    `<strong>${sign(delta)}</strong><p>2023 → 2024 under <b>${mode === "baseline" ? "the existing screen" : mode === "selected" ? "the selected record exclusion" : `symmetric top-${topK} exclusion`}</b>.<br>${mode === "baseline" ? "Test an exclusion rule to see whether this direction holds." : "This is a sensitivity result, not a corrected injury trend."}</p>`;
  $("#calculation-table tbody").innerHTML = rows
    .map(
      (r) =>
        `<tr><th scope="row">${r.year}</th><td>${int(r.filings)}</td><td>${int(r.cases)}</td><td>${int(r.hours)}</td><td>${dec(r.rate, 6)}</td><td>${int(r.removedHours)}</td></tr>`,
    )
    .join("");
}
function renderChart(rows) {
  const width = $("#trend-chart").clientWidth < 500 ? 360 : 650,
    height = 330,
    l = 46,
    r = 35,
    t = 35,
    b = 45,
    plotW = width - l - r,
    plotH = height - t - b;
  const x = (i) => l + (i * plotW) / 2,
    y = (v) => t + plotH * (1 - v / 5);
  const base = data.annual_rates.filter((v) => v.year >= 2022);
  let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="trend-title trend-desc"><title id="trend-title">Screened rate and selected sensitivity, 2022 to 2024</title><desc id="trend-desc">${rows.map((v) => `${v.year}: ${v.rate.toFixed(6)} cases per 200000 hours`).join(". ")}. Exact numerators and denominators appear in the table.</desc>`;
  for (let n = 0; n <= 5; n++)
    svg += `<line x1="${l}" x2="${width - r}" y1="${y(n)}" y2="${y(n)}" stroke="#e0e5e5"/><text x="${l - 12}" y="${y(n) + 4}" text-anchor="end" font-size="11" fill="#566369">${n}</text>`;
  svg += `<polyline points="${base.map((v, i) => `${x(i)},${y(v.rate)}`).join(" ")}" fill="none" stroke="#1d272b" stroke-width="2"/>`;
  base.forEach(
    (v, i) =>
      (svg += `<circle cx="${x(i)}" cy="${y(v.rate)}" r="4" fill="#1d272b"/><text x="${x(i)}" y="${y(v.rate) + 22}" text-anchor="middle" font-size="12" fill="#1d272b">${dec(v.rate, 3)}</text><text x="${x(i)}" y="${height - 10}" text-anchor="middle" font-size="12" fill="#566369">${v.year}</text>`),
  );
  if (mode !== "baseline") {
    svg += `<polyline points="${rows.map((v, i) => `${x(i)},${y(v.rate)}`).join(" ")}" fill="none" stroke="#2457a5" stroke-width="3" stroke-dasharray="7 4"/>`;
    rows.forEach(
      (v, i) =>
        (svg += `<circle cx="${x(i)}" cy="${y(v.rate)}" r="5" fill="white" stroke="#2457a5" stroke-width="2"/><text x="${x(i)}" y="${y(v.rate) - 14}" text-anchor="middle" font-size="12" font-weight="600" fill="#2457a5">${dec(v.rate, 3)}</text>`),
    );
  }
  $("#trend-chart").innerHTML = svg + "</svg>";
}
function populate() {
  const h = data.headline;
  $("#headline-base").textContent = sign(h.reported_2023_2024_change_pct);
  $("#headline-sensitive").textContent = sign(
    h.two_filing_exclusion_2023_2024_change_pct,
  );
  $("#headline-hours").textContent = dec(h.two_filings_hours_share * 100) + "%";
  $("#exclude-list").innerHTML = data.suspect_filings
    .map(
      (r) =>
        `<label class="record-toggle"><input type="checkbox" data-exclude="${r.filing_id}"><span>Filing ${r.filing_id}<br><span class="muted">${dec(r.hours / 1e9, 2)} billion reported hours</span></span></label>`,
    )
    .join("");
  const ks = [...new Set(data.exposure_concentration.map((r) => r.top_n))]
    .filter((k) => k > 0)
    .sort((a, b) => a - b);
  $("#top-k").innerHTML = ks
    .map(
      (k) =>
        `<option value="${k}">${k} filing${k === 1 ? "" : "s"} per year</option>`,
    )
    .join("");
  $("#records-table tbody").innerHTML = data.suspect_filings
    .map(
      (r) =>
        `<tr><th scope="row">${r.filing_id}</th><td>${int(r.employees)}</td><td>${int(r.hours)}</td><td>${r.cases}</td><td>${dec(r.hours_per_employee)}</td><td>Passes ratio check</td></tr>`,
    )
    .join("");
  $("#linked-table tbody").innerHTML = data.linked_filings
    .map(
      (r) =>
        `<tr><th scope="row">${r.year}</th><td>${r.establishment_id}</td><td>${r.filing_id}</td><td>${int(r.employees)}</td><td>${int(r.hours)}</td><td>${dec(r.hours_per_employee)}</td></tr>`,
    )
    .join("");
  $("#scale-row").innerHTML = data.suspect_filings
    .map((r) => `<option value="${r.filing_id}">Filing ${r.filing_id}</option>`)
    .join("");
  const lows = [...new Set(data.threshold_survival.map((r) => r.low))],
    highs = [...new Set(data.threshold_survival.map((r) => r.high))];
  $("#threshold-description").textContent =
    `The two records pass all ${data.threshold_survival.length} tested screens. Recomputing the entire population under each screen still leaves the same sign reversal.`;
  $("#threshold-grid").innerHTML =
    '<span class="grid-label">Lower ↓ / Upper →</span>' +
    highs.map((v) => `<span class="grid-label">${int(v)}</span>`).join("") +
    lows
      .map(
        (lo) =>
          `<span class="grid-label">${lo}</span>` +
          highs
            .map((hi) => {
              const r = data.threshold_trend_sensitivity.find(
                (v) => v.low === lo && v.high === hi,
              );
              return `<button type="button" class="threshold-cell" data-low="${lo}" data-high="${hi}" aria-label="Bounds ${lo} to ${hi}: reported ${sign(r.change_pct)}, excluding two ${sign(r.exclusion_change_pct)}"><span>${sign(r.change_pct)}</span><strong>${sign(r.exclusion_change_pct)}</strong></button>`;
            })
            .join(""),
      )
      .join("");
  const showThreshold = (lo, hi) => {
    const r = data.threshold_trend_sensitivity.find(
      (v) => v.low === lo && v.high === hi,
    );
    $("#threshold-detail").textContent =
      `${lo}–${int(hi)} hours per employee: ${int(r.n_2023)} filings in 2023; ${int(r.n_2024)} in 2024. Reported rates ${dec(r.rate_2023, 3)} → ${dec(r.rate_2024, 3)}. Excluding the two: ${dec(r.exclusion_rate_2023, 3)} → ${dec(r.exclusion_rate_2024, 3)} cases per 100 FTE.`;
    document
      .querySelectorAll(".threshold-cell")
      .forEach((b) =>
        b.setAttribute(
          "aria-pressed",
          String(Number(b.dataset.low) === lo && Number(b.dataset.high) === hi),
        ),
      );
  };
  document
    .querySelectorAll(".threshold-cell")
    .forEach((b) =>
      b.addEventListener("click", () =>
        showThreshold(Number(b.dataset.low), Number(b.dataset.high)),
      ),
    );
  showThreshold(lows[0], highs[0]);
  $("#robust-table tbody").innerHTML = [0, ...ks]
    .map((k) => {
      const rows = scenarioRows(data, k ? "symmetric" : "baseline", [], k);
      return `<tr><th scope="row">${k}</th><td>${dec(rows.find((r) => r.year === 2023).rate, 3)}</td><td>${dec(rows.find((r) => r.year === 2024).rate, 3)}</td><td>${sign(change(rows))}</td></tr>`;
    })
    .join("");
  const pairs = data.decomposition.filter((r) => r.scenario === "all_cells");
  $("#pair-year").innerHTML = pairs
    .map(
      (r) =>
        `<option value="${r.year_after}" ${r.year_after === 2024 ? "selected" : ""}>${r.year_before} → ${r.year_after}</option>`,
    )
    .join("");
  $("#limits").innerHTML = data.limitations
    .map((s) => `<li>${esc(s)}</li>`)
    .join("");
  $("#source-list").innerHTML = data.raw_provenance
    .map(
      (s) =>
        `<div class="source-entry"><a href="${esc(s.url)}">OSHA ${s.year} source archive ↗︎</a><code>SHA-256 ${esc(s.sha256)}</code></div>`,
    )
    .join("");
  const influence = data.influence_audit;
  const context = influence.concentration_context;
  $("#concentration-summary").textContent =
    `The largest two filings hold ${dec(context.year_2023_top_two_hours_share * 100)}% of screened 2023 hours. In the other eight years, that share ranges from ${dec(context.other_years_top_two_hours_share_min * 100, 3)}% to ${dec(context.other_years_top_two_hours_share_max * 100, 3)}%.`;
  $("#concentration-bars").innerHTML = influence.annual
    .map(
      (r) =>
        `<div class="concentration-row ${r.year === 2023 ? "highlight" : ""}"><span>${r.year}</span><div><i style="width:${((r.top_two_hours_share * 100) / 20) * 100}%"></i></div><strong>${dec(r.top_two_hours_share * 100, 2)}%</strong></div>`,
    )
    .join("");
  $("#concentration-bars").setAttribute(
    "aria-label",
    influence.annual
      .map((r) => `${r.year}: ${dec(r.top_two_hours_share * 100, 3)} percent`)
      .join("; "),
  );
  const candidate = influence.review_candidates.find(
    (r) => r.year_before === 2023 && r.year_after === 2024,
  );
  const comparison = influence.decision_fragility.find(
    (r) => r.year_before === 2023,
  );
  $("#single-review-summary").textContent =
    `Among ${int(comparison.n_filings_tested)} screen-passing records across 2023 and 2024, filing ${candidate.filing_id} alone changes the trend from ${sign(candidate.original_change_pct)} to ${sign(candidate.review_change_pct)}. No individual deletion reverses any of the other seven adjacent-year comparisons.`;
  renderScale();
  renderDecomposition();
}
function renderScale() {
  const row = data.suspect_filings.find(
    (r) => r.filing_id === Number($("#scale-row").value),
  );
  const f = Number($("#scale-factor").value),
    s = scaleStress(row, f);
  $("#scale-result").innerHTML = [
    ["Hours / employee", dec(s.hoursPerEmployee)],
    ["Ratio-screen result", "Still passes"],
    ["Implied employees", dec(s.employees, f < 1 ? 2 : 0)],
    ["Implied hours", dec(s.hours, f < 1 ? 2 : 0)],
    ["Cases (unchanged)", s.cases],
    ["Implied TRIR", dec(s.rate, 9)],
  ]
    .map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`)
    .join("");
}
function renderDecomposition() {
  const d = data.decomposition.find(
    (r) =>
      r.scenario === "all_cells" &&
      r.year_after === Number($("#pair-year").value),
  );
  const values = [
    ["Within-cell component", d.within_effect],
    ["Composition component", d.composition_effect],
    ["Support residual", d.support_residual],
    ["Full aggregate change", d.full_change],
  ];
  const max = Math.max(...values.map((v) => Math.abs(v[1])));
  $("#decomposition").innerHTML =
    `<div class="decomp-bars">${values.map(([label, v], i) => `<div class="decomp-row ${i === 3 ? "total" : ""}"><span>${label}</span><div class="decomp-track" aria-hidden="true"><i style="left:${v < 0 ? 50 - (Math.abs(v) / max) * 48 : 50}%;width:${(Math.abs(v) / max) * 48}%"></i></div><strong>${v > 0 ? "+" : ""}${dec(v, 4)}</strong></div>`).join("")}</div><p class="chart-note">${int(d.n_cells_matched)} matched industry × size cells; ${int(d.declining_cells)} have lower rates. Hours coverage: ${dec(d.hours_coverage_before * 100, 3)}% before / ${dec(d.hours_coverage_after * 100, 3)}% after.</p><p class="chart-note"><strong>Weighting matters.</strong> Within-cell effect using earlier-year weights: ${d.within_effect_before_weights > 0 ? "+" : ""}${dec(d.within_effect_before_weights, 4)}. Using later-year weights: ${d.within_effect_after_weights > 0 ? "+" : ""}${dec(d.within_effect_after_weights, 4)}. Their signs can differ; the symmetric convention does not establish a unique fixed-composition trend.</p>`;
}
function download(body, type, name) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  $("#action-status").textContent =
    "Exported locally. No records were changed.";
}
function bind() {
  document.querySelectorAll("[name=scenario]").forEach((e) =>
    e.addEventListener("change", () => {
      mode = e.value;
      syncState();
      render();
    }),
  );
  document.querySelectorAll("[data-exclude]").forEach((e) =>
    e.addEventListener("change", () => {
      const id = Number(e.dataset.exclude);
      e.checked ? selected.add(id) : selected.delete(id);
      syncState();
      render();
    }),
  );
  $("#top-k").addEventListener("change", () => {
    topK = Number($("#top-k").value);
    syncState();
    render();
  });
  $("#reset").addEventListener("click", () => {
    mode = "baseline";
    selected = new Set(data.suspect_filings.map((r) => r.filing_id));
    topK = 2;
    syncState();
    render();
  });
  $("#scale-row").addEventListener("change", renderScale);
  $("#scale-factor").addEventListener("change", renderScale);
  $("#pair-year").addEventListener("change", renderDecomposition);
  $("#export-csv").addEventListener("click", () => {
    const columns = [
      "year",
      "filings",
      "cases",
      "hours",
      "rate",
      "removedHours",
      "removedCases",
      "removedFilings",
    ];
    const text = [
      "# Inclusion rule: " + mode,
      "# Excluded 2023 filing IDs: " +
        (mode === "selected" ? [...selected].join(" ") : "not applicable"),
      "# Symmetric top k per year: " +
        (mode === "symmetric" ? topK : "not applicable"),
      "# Sensitivity analysis; not corrected truth.",
      columns.join(","),
      ...resultRows().map((r) => columns.map((k) => r[k]).join(",")),
    ].join("\n");
    download(text, "text/csv;charset=utf-8", "osha-trend-sensitivity.csv");
  });
  $("#export-review").addEventListener("click", () => {
    const body = {
      title: "Screen-passing denominator influence audit",
      statement:
        "The reported trend is sensitive to a small number of high-influence filings. Exclusion does not establish the corrected trend.",
      rule: mode,
      excluded_filing_ids: mode === "selected" ? [...selected] : [],
      symmetric_top_k: mode === "symmetric" ? topK : null,
      selected_calculation: resultRows(),
      change_2023_2024_pct: change(resultRows()),
      reviewer_note: $("#review-note").value,
      limitations: data.limitations,
      provenance: data.provenance,
      raw_provenance: data.raw_provenance,
    };
    download(
      JSON.stringify(body, null, 2),
      "application/json",
      "osha-influence-review.json",
    );
  });
  $("#copy-link").addEventListener("click", async () => {
    syncState();
    try {
      await navigator.clipboard.writeText(location.href);
      $("#action-status").textContent =
        "Investigation link copied. Your review note is not included.";
    } catch {
      $("#action-status").textContent = "Copy this link: " + location.href;
    }
  });
  window.addEventListener("popstate", () => {
    readState();
    render();
  });
  let timer;
  window.addEventListener("resize", () => {
    clearTimeout(timer);
    timer = setTimeout(() => renderChart(resultRows()), 100);
  });
}
try {
  const response = await fetch("decision-audit-data.json");
  if (!response.ok) throw new Error("Findings unavailable");
  data = await response.json();
  if (!data.headline || !data.raw_provenance?.length)
    throw new Error("Incomplete findings");
  readState();
  populate();
  bind();
  $("#loaded").hidden = false;
  render();
  $("#load-status").textContent = "";
} catch (error) {
  $("#loaded").hidden = true;
  $("#load-status").textContent =
    "The findings could not be loaded. Reload this page or download decision-audit-data.json to inspect the underlying artifact.";
  console.error(error);
}
