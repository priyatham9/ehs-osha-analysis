import {
  parseCsv,
  analyzeDataset,
  restoreReview,
} from "./denominator-model.mjs";
const $ = (s) => document.querySelector(s);
const num = (n, d = 2) =>
  n === null || !Number.isFinite(n)
    ? "Not defined"
    : n.toLocaleString("en-US", {
        maximumFractionDigits: d,
        minimumFractionDigits: d,
      });
const integer = (n) => num(n, 0);
const pct = (n) =>
  n === null || !Number.isFinite(n)
    ? "Not defined"
    : `${n > 0 ? "+" : ""}${num(n)}%`;
const esc = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
let dataset = null,
  analysis = null,
  excluded = new Set(),
  page = 0,
  fileName = "",
  kind = "",
  sourceHash = null,
  sequence = 0;
const PAGE_SIZE = 25;
function error(message) {
  if ($("#file-status").textContent.startsWith("Reading"))
    $("#file-status").textContent = "File could not be accepted.";
  $("#error").textContent = message;
  $("#error").hidden = false;
  $("#results").hidden = true;
  $("#empty").hidden = false;
  analysis = null;
}
async function hashBytes(bytes) {
  if (!globalThis.crypto?.subtle) return null;
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
function download(name, body, type) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function clear() {
  sequence++;
  dataset = null;
  analysis = null;
  excluded.clear();
  page = 0;
  fileName = "";
  kind = "";
  sourceHash = null;
  $("#csv-file").value = "";
  $("#settings-fields").disabled = true;
  $("#clear").disabled = true;
  $("#restore-review").disabled = true;
  $("#review-file").value = "";
  $("#results").hidden = true;
  $("#empty").hidden = false;
  $("#error").hidden = true;
  $("#file-status").textContent = "No file loaded.";
  $("#review-note").value = "";
  $("#record-filter").value = "all";
  $("#low").value = "120";
  $("#high").value = "4500";
  $("#records").replaceChildren();
  $("#ledger").replaceChildren();
  for (const id of ["before", "after", "rate-chart"])
    $("#" + id).replaceChildren();
  for (const id of [
    "period-title",
    "data-kind",
    "base-change",
    "review-change",
    "base-rates",
    "review-rates",
    "reversal-count",
    "finding",
    "scenario-count",
    "scenario-consequence",
    "record-count",
    "page-label",
  ])
    $("#" + id).textContent = "";
  $("#rate-chart").setAttribute(
    "aria-label",
    "Screened and review-scenario rates",
  );
}
function load(text, name, type, hash) {
  try {
    const parsed = parseCsv(text);
    if (parsed.years.length < 2)
      throw new Error(
        "Include at least two distinct years to compare a trend.",
      );
    dataset = parsed;
    fileName = name;
    kind = type;
    sourceHash = hash;
    $("#restore-review").disabled = !sourceHash;
    excluded.clear();
    page = 0;
    $("#review-note").value = "";
    $("#record-filter").value = "all";
    for (const id of ["before", "after"])
      $("#" + id).innerHTML = dataset.years
        .map((y) => `<option value="${y}">${y}</option>`)
        .join("");
    $("#before").value = String(dataset.years.at(-2));
    $("#after").value = String(dataset.years.at(-1));
    $("#settings-fields").disabled = false;
    $("#clear").disabled = false;
    $("#file-status").textContent =
      `${name} · ${integer(dataset.records.length)} valid records · ${dataset.years.length} years`;
    run();
  } catch (e) {
    dataset = null;
    $("#settings-fields").disabled = true;
    $("#clear").disabled = false;
    $("#file-status").textContent = "File could not be accepted.";
    error(e.message);
  }
}
function run() {
  if (!dataset) return;
  try {
    if (!$("#settings").checkValidity())
      throw new Error(
        "Enter both finite ratio bounds before running the audit.",
      );
    const years = [Number($("#before").value), Number($("#after").value)];
    if (years[0] >= years[1])
      throw new Error("Choose an earlier year before the later year.");
    analysis = analyzeDataset(dataset, {
      years,
      low: Number($("#low").value),
      high: Number($("#high").value),
      excludedKeys: [...excluded],
    });
    $("#error").hidden = true;
    $("#empty").hidden = true;
    $("#results").hidden = false;
    render();
  } catch (e) {
    error(e.message);
  }
}
function render() {
  const c = analysis.comparison;
  $("#period-title").textContent =
    `${analysis.years[0]} → ${analysis.years[1]}`;
  $("#data-kind").textContent =
    kind === "example" ? "Constructed case · not empirical" : "Your local data";
  $("#base-change").textContent = pct(c.baselineChangePct);
  $("#review-change").textContent = pct(c.reviewChangePct);
  $("#base-rates").textContent =
    `${num(c.baselineBefore, 3)} → ${num(c.baselineAfter, 3)} · Δ ${num(c.baselineChange, 3)} cases / 100 FTE`;
  $("#review-rates").textContent =
    `${num(c.reviewBefore, 3)} → ${num(c.reviewAfter, 3)} · Δ ${num(c.reviewChange, 3)} cases / 100 FTE`;
  const reversals = analysis.records.filter(
    (r) => r.screenPass && r.reversesTrend,
  );
  $("#reversal-count").textContent = integer(reversals.length);
  $("#scenario-count").textContent =
    `${excluded.size} record${excluded.size === 1 ? "" : "s"} excluded in this scenario`;
  $("#scenario-consequence").textContent =
    `Screened ${pct(c.baselineChangePct)} → review ${pct(c.reviewChangePct)}`;
  $("#review-selected").disabled = excluded.size === 0;

  const undefinedRate = c.reviewBefore === null || c.reviewAfter === null;
  const reversed =
    Number.isFinite(c.baselineChange) &&
    Number.isFinite(c.reviewChange) &&
    c.baselineChange * c.reviewChange < 0;
  $("#finding").textContent = undefinedRate
    ? "The review scenario has no remaining exposure in at least one year. Its rate and trend are undefined. Restore at least one included record in each year."
    : excluded.size
      ? `${excluded.size} record${excluded.size === 1 ? "" : "s"} excluded in this review scenario. ${reversed ? "The direction reverses." : "The direction does not reverse."} Absolute rate difference: ${num(c.reviewChange, 3)} cases per 100 FTE. This is sensitivity, not a corrected estimate.`
      : reversals.length
        ? `${integer(reversals.length)} individual record${reversals.length === 1 ? " can" : "s can"} reverse this trend if removed alone. Inspect reporting units, population scope and source records before making an exclusion decision.`
        : "No single screen-passing record reverses this trend. This does not establish robustness to combined exclusions, changing populations, or measurement error.";
  const values = [
    c.baselineBefore,
    c.baselineAfter,
    c.reviewBefore,
    c.reviewAfter,
  ];
  const max = Math.max(0, ...values.filter(Number.isFinite));
  const labels = [
    `${analysis.years[0]} screened`,
    `${analysis.years[1]} screened`,
    `${analysis.years[0]} review`,
    `${analysis.years[1]} review`,
  ];
  $("#rate-chart").innerHTML = values
    .map(
      (v, i) =>
        `<div class="rate-row"><span>${labels[i]}</span><div class="bar-track"><div class="bar ${i > 1 ? "review-bar" : ""}" style="width:${v !== null && max > 0 ? (v / max) * 100 : 0}%"></div></div><strong>${num(v, 3)}</strong></div>`,
    )
    .join("");
  $("#rate-chart").setAttribute(
    "aria-label",
    labels.map((s, i) => `${s}: ${num(values[i], 3)}`).join("; "),
  );
  $("#ledger").innerHTML = analysis.annual
    .map(
      (r) =>
        `<tr><th scope="row">${r.year}</th><td>${integer(r.nTotal)}</td><td>${integer(r.nAccepted)}</td><td>${integer(r.nRejected)}</td><td>${integer(r.nExcluded)}</td><td>${integer(r.reviewCases)}</td><td>${num(r.reviewHours, 2)}</td><td>${num(r.reviewRate, 4)}</td></tr>`,
    )
    .join("");
  renderRecords();
}
function renderRecords() {
  const filter = $("#record-filter").value;
  const rows = analysis.records
    .filter(
      (r) =>
        r.screenPass &&
        (filter !== "reversals" || r.reversesTrend) &&
        (filter !== "selected" || excluded.has(r.key)),
    )
    .sort(
      (a, b) =>
        b.absoluteInfluence - a.absoluteInfluence || a.sourceRow - b.sourceRow,
    );
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  page = Math.max(0, Math.min(page, pages - 1));
  $("#record-count").textContent =
    `${integer(rows.length)} records · ${excluded.size} excluded`;
  $("#page-label").textContent = `Page ${page + 1} of ${pages}`;
  $("#previous").disabled = page === 0;
  $("#next").disabled = page === pages - 1;
  $("#records").innerHTML = rows.length
    ? rows
        .slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
        .map(
          (r) =>
            `<tr class="${excluded.has(r.key) ? "is-selected" : ""}"><td><input type="checkbox" data-key="${esc(r.key)}" ${excluded.has(r.key) ? "checked" : ""} aria-label="Exclude ${esc(r.filingId || r.key)} in ${r.year} from review scenario"></td><td>${esc(r.filingId || r.key)}<small>${r.year} · source row ${r.sourceRow}</small></td><td>${num(r.employees, 2)}</td><td>${num(r.hours, 2)}</td><td>${integer(r.cases)}</td><td>${num(r.hoursPerEmployee, 1)}</td><td>${num(r.yearHoursShare * 100)}%</td><td>${num(r.absoluteInfluence, 5)}</td><td>${pct(r.leaveOneOutTrendChangePct)}${r.reversesTrend ? '<span class="flag">Direction reverses</span>' : ""}</td></tr>`,
        )
        .join("")
    : '<tr><td colspan="9">No records match this view.</td></tr>';
  $("#records")
    .querySelectorAll("[data-key]")
    .forEach((el) =>
      el.addEventListener("change", () => {
        if (el.checked) excluded.add(el.dataset.key);
        else excluded.delete(el.dataset.key);
        run();
        const replacement = [
          ...$("#records").querySelectorAll("[data-key]"),
        ].find((x) => x.dataset.key === el.dataset.key);
        (replacement || $("#record-filter")).focus();
      }),
    );
}
$("#csv-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const ticket = ++sequence;
  dataset = null;
  analysis = null;
  $("#settings-fields").disabled = true;
  $("#clear").disabled = false;
  $("#restore-review").disabled = true;
  $("#file-status").textContent = "Reading file locally…";
  $("#results").hidden = true;
  $("#error").hidden = true;
  if (file.size > 10 * 1024 * 1024) {
    dataset = null;
    $("#settings-fields").disabled = true;
    $("#clear").disabled = false;
    error(
      "This file exceeds the 10 MB limit. Export a smaller scope before auditing.",
    );
    return;
  }
  try {
    const bytes = await file.arrayBuffer();
    const hash = await hashBytes(bytes);
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    if (ticket === sequence) load(text, file.name, "file", hash);
  } catch {
    if (ticket === sequence)
      error(
        "The file could not be read as UTF-8 CSV. Export UTF-8 CSV and try again.",
      );
  }
});
$("#settings").addEventListener("submit", (e) => {
  e.preventDefault();
  excluded.clear();
  page = 0;
  run();
});
for (const id of ["before", "after", "low", "high"])
  $("#" + id).addEventListener("input", () => {
    analysis = null;
    $("#results").hidden = true;
    $("#empty").hidden = false;
    $("#file-status").textContent =
      `${fileName} · settings changed. Run the audit to recalculate.`;
  });
$("#clear").addEventListener("click", clear);
$("#record-filter").addEventListener("change", () => {
  page = 0;
  if (analysis) renderRecords();
});
$("#previous").addEventListener("click", () => {
  page--;
  renderRecords();
});
$("#next").addEventListener("click", () => {
  page++;
  renderRecords();
});

$("#review-selected").addEventListener("click", () => {
  $("#record-filter").value = "selected";
  page = 0;
  renderRecords();
  $("#record-filter").focus();
});
$("#reset-review").addEventListener("click", () => {
  excluded.clear();
  page = 0;
  $("#record-filter").value = "all";
  run();
});
$("#template").addEventListener("click", () =>
  download(
    "denominator-audit-template.csv",
    "year,filing_id,employees,hours,cases\n",
    "text/csv",
  ),
);
$("#example").addEventListener("click", async () => {
  const ticket = ++sequence;
  $("#csv-file").value = "";
  $("#low").value = "120";
  $("#high").value = "4500";
  let text = "year,filing_id,employees,hours,cases\n";
  for (const year of [2023, 2024])
    for (let i = 1; i <= 12; i++)
      text += `${year},example-${year}-${i},100,200000,${year === 2023 ? 4 : 3}\n`;
  text += "2023,example-scale-review,10000,20000000,1\n";
  const hash = await hashBytes(new TextEncoder().encode(text));
  if (ticket === sequence)
    load(text, "Constructed scale-invariance case", "example", hash);
});
$("#export-json").addEventListener("click", () => {
  if (!analysis) return;
  download(
    "denominator-review.json",
    JSON.stringify(
      {
        schema_version: "1.0",
        created_at: new Date().toISOString(),
        source: {
          file_name: fileName,
          sha256: sourceHash,
          hash_scope: sourceHash
            ? "Original file bytes; constructed cases use generated UTF-8 CSV bytes."
            : "Unavailable in this browser context.",
          kind,
          record_count: dataset.records.length,
          uploaded: false,
        },
        method:
          "Inclusive ratio screen, exact leave-one-out influence, selected exclusion sensitivity. Not corrected truth.",
        screen: analysis.screen,
        years: analysis.years,
        comparison: analysis.comparison,
        annual: analysis.annual,
        excluded_records: analysis.records.filter((r) => excluded.has(r.key)),
        reviewer_note: $("#review-note").value,
      },
      null,
      2,
    ),
    "application/json",
  );
});
function csvCell(v) {
  let text = v === null || v === undefined ? "" : String(v);
  if (typeof v === "string" && /^[=+\-@\t\r]/.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}
$("#export-csv").addEventListener("click", () => {
  if (!analysis) return;
  const columns = [
    "key",
    "filingId",
    "year",
    "employees",
    "hours",
    "cases",
    "hoursPerEmployee",
    "screenPass",
    "baselineRate",
    "leaveOneOutRate",
    "absoluteInfluence",
    "leaveOneOutTrendChangePct",
    "reversesTrend",
    "excluded",
  ];
  download(
    "denominator-influence.csv",
    [
      columns.join(","),
      ...analysis.records.map((r) =>
        columns.map((c) => csvCell(r[c])).join(","),
      ),
    ].join("\r\n"),
    "text/csv",
  );
});

$("#restore-review").addEventListener("click", () => $("#review-file").click());
$("#review-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const ticket = ++sequence;
  try {
    if (!dataset)
      throw new Error("Load the original CSV before restoring its review.");
    if (file.size > 64 * 1024 * 1024)
      throw new Error("This review exceeds the 64 MB limit.");
    const text = await file.text();
    if (ticket !== sequence) return;
    const restored = restoreReview(dataset, sourceHash, JSON.parse(text));
    $("#before").value = String(restored.options.years[0]);
    $("#after").value = String(restored.options.years[1]);
    $("#low").value = String(restored.options.low);
    $("#high").value = String(restored.options.high);
    excluded = new Set(restored.options.excludedKeys);
    page = 0;
    $("#record-filter").value = "all";
    $("#review-note").value = restored.note;
    analysis = restored.analysis;
    $("#error").hidden = true;
    $("#empty").hidden = true;
    $("#results").hidden = false;
    $("#file-status").textContent =
      `${fileName} · restored review; source SHA-256 matched and all results recomputed.`;
    render();
  } catch (e) {
    if (ticket !== sequence) return;
    $("#error").textContent =
      "Review not restored. " +
      (e instanceof SyntaxError
        ? "This file is not valid review JSON."
        : e.message);
    $("#error").hidden = false;
  } finally {
    if (ticket === sequence) $("#review-file").value = "";
  }
});
