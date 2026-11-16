/* Evidence UI reads only committed explorer aggregates; it never fabricates row-level records. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const number = (v, digits = 0) =>
    Number(v).toLocaleString("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  const percent = (v) => number(v * 100, 2) + "%";
  const keys = [
    "year",
    "n_filings",
    "n_implausible",
    "implausible_share",
    "hours_share_implausible",
    "trir_unscreened",
    "trir_screened",
    "ratio",
  ];
  const sourceRoot =
    "https://github.com/priyatham9/ehs-osha-analysis/blob/main/";
  let data,
    period = "2019",
    metric = "rate",
    tableScope = "selected";
  function readState() {
    const q = new URLSearchParams(location.search);
    const requested = q.get("period") || q.get("y") || "2019";
    period =
      requested === "pooled" || requested === "all"
        ? "pooled"
        : data.quality_by_year.some((r) => String(r.year) === requested)
          ? requested
          : "2019";
    metric = q.get("metric") === "share" ? "share" : "rate";
    tableScope = q.get("rows") === "annual" ? "annual" : "selected";
  }
  function writeState(replace = false) {
    const url = new URL(location.href);
    url.searchParams.set("period", period);
    url.searchParams.set("metric", metric);
    url.searchParams.set("rows", tableScope);
    if (url.href !== location.href)
      history[replace ? "replaceState" : "pushState"](null, "", url);
  }
  const current = () =>
    period === "pooled"
      ? { year: "2016–2024 pooled", ...data.pooled }
      : data.quality_by_year.find((r) => String(r.year) === period);
  const rows = () =>
    tableScope === "annual" ? data.quality_by_year : [current()];
  const scopeLabel = () =>
    tableScope === "annual"
      ? "9 annual aggregates, 2016–2024"
      : String(current().year);
  function el(tag, text, cls) {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  }
  function stat(label, value, detail) {
    const box = el("div", undefined, "ev-stat");
    box.append(
      el("span", label, "ev-stat-label"),
      el("span", value, "ev-stat-value"),
      el("span", detail, "ev-stat-sub"),
    );
    return box;
  }
  function setPeriod(value) {
    period = value;
    render();
    writeState();
    $("ev-status").textContent =
      "Selected " +
      current().year +
      ". Evidence and selected-aggregate export updated.";
  }
  function render() {
    const r = current();
    $("ev-period").value = period;
    $("ev-stats").replaceChildren(
      stat(
        "Filings in scope",
        number(r.n_filings),
        String(r.year) + " · establishment-years",
      ),
      stat(
        "Filings flagged",
        percent(r.implausible_share),
        number(r.n_implausible) + " fail the hours screen",
      ),
      stat(
        "Hours in flagged filings",
        percent(r.hours_share_implausible),
        "Share of all reported hours",
      ),
      stat(
        "Screened / as-filed rate",
        number(r.ratio, 2) + "×",
        "Effect of changing included filings",
      ),
    );
    $("ev-inspector-title").textContent =
      period === "pooled" ? "2016–2024" : period;
    $("ev-finding").textContent =
      `${percent(r.implausible_share)} of filings hold ${percent(r.hours_share_implausible)} of reported hours. Applying the screen changes aggregate TRIR from ${number(r.trir_unscreened, 3)} to ${number(r.trir_screened, 3)}.`;
    const fields = [
      ["As-filed TRIR", number(r.trir_unscreened, 3)],
      ["Screened TRIR", number(r.trir_screened, 3)],
      ["Flagged filings", number(r.n_implausible)],
      [
        "Period",
        period === "pooled" ? "9 years pooled" : "Calendar year " + period,
      ],
    ];
    $("ev-fields").replaceChildren(
      ...fields.map(([name, value]) => {
        const row = el("div");
        row.append(el("dt", name), el("dd", value));
        return row;
      }),
    );
    document
      .querySelectorAll("[data-metric]")
      .forEach((b) =>
        b.setAttribute("aria-pressed", String(b.dataset.metric === metric)),
      );
    document
      .querySelectorAll("[data-table]")
      .forEach((b) =>
        b.setAttribute("aria-pressed", String(b.dataset.table === tableScope)),
      );
    renderChart();
    renderTable();
  }
  function renderChart() {
    const rate = metric === "rate";
    const first = rate ? "trir_unscreened" : "implausible_share";
    const second = rate ? "trir_screened" : "hours_share_implausible";
    const max = rate
      ? Math.ceil(Math.max(...data.quality_by_year.map((r) => r.trir_screened)))
      : 1;
    const format = rate ? (v) => number(v, 3) : percent;
    const labels = rate
      ? ["As filed", "Screened"]
      : ["Filings flagged", "Hours in flagged filings"];
    $("ev-chart-title").textContent = rate
      ? "Reported and screened rates"
      : "Small filing share. Large hours share.";
    $("ev-chart-unit").textContent = rate
      ? "TRIR · recordable cases per 200,000 hours"
      : "Percent of all filings / all reported hours";
    $("ev-legend").replaceChildren(
      ...labels.map((label) => {
        const s = el("span");
        s.append(el("i"), el("span", label));
        return s;
      }),
    );
    $("ev-chart-axis").replaceChildren(
      ...Array.from({ length: 6 }, (_, i) =>
        el("span", rate ? String((i * max) / 5) : i * 20 + "%"),
      ),
    );
    const existing = new Map(
      [...$("ev-chart").children].map((b) => [b.dataset.year, b]),
    );
    data.quality_by_year.forEach((r) => {
      let button = existing.get(String(r.year));
      if (!button) {
        button = el("button", undefined, "ev-chart-row");
        button.type = "button";
        button.dataset.year = String(r.year);
        button.addEventListener("click", () => setPeriod(String(r.year)));
        $("ev-chart").append(button);
      }
      button.setAttribute("aria-pressed", String(String(r.year) === period));
      button.setAttribute(
        "aria-label",
        `${r.year}: ${labels[0]} ${format(r[first])}; ${labels[1]} ${format(r[second])}. Inspect aggregate.`,
      );
      const bars = el("span", undefined, "ev-bars");
      bars.setAttribute("aria-hidden", "true");
      [first, second].forEach((key) => {
        const bar = el("i");
        bar.style.setProperty("--bar-width", (r[key] / max) * 100 + "%");
        bars.append(bar);
      });
      const values = el("span", undefined, "ev-chart-values");
      values.setAttribute("aria-hidden", "true");
      values.append(
        el("span", format(r[first])),
        el("span", format(r[second])),
      );
      button.replaceChildren(
        el("span", String(r.year), "ev-chart-year"),
        bars,
        values,
      );
    });
    $("ev-chart-caption").textContent =
      period === "pooled"
        ? "The inspector shows the pooled 2016–2024 aggregate. Bars show the nine component years; pooled rates are not an average of these bars."
        : `Highlighted: ${period}. ${rate ? "The same screen is applied in every year; the population of filers can change between years." : "Each bar has its own denominator: filing count or reported hours. These percentages are not injury shares."}`;
  }
  function renderTable() {
    const body = $("ev-table").querySelector("tbody");
    body.replaceChildren(
      ...rows().map((r) => {
        const tr = el("tr");
        if (
          String(r.year) === period ||
          (period === "pooled" && tableScope === "selected")
        )
          tr.className = "ev-selected";
        keys.forEach((k) => tr.append(el("td", String(r[k]))));
        return tr;
      }),
    );
    $("ev-table-count").textContent =
      rows().length +
      (rows().length === 1 ? " row · " : " rows · ") +
      (tableScope === "annual" ? "annual aggregates" : "selected scope");
    $("ev-csv").setAttribute("aria-label", "Export CSV: " + scopeLabel());
    $("ev-note").setAttribute(
      "aria-label",
      "Download review note: " + scopeLabel(),
    );
  }
  function sourceFor(r) {
    return (
      "outputs/tables/" +
      (typeof r.year === "number"
        ? "quality_by_year.csv"
        : "quality_overall.csv")
    );
  }
  function csvCell(value) {
    return '"' + String(value).replace(/"/g, '""') + '"';
  }
  function csvText() {
    const headers = [
      ...keys,
      "source_path",
      "min_hours_per_employee",
      "max_hours_per_employee",
    ];
    return (
      [
        headers,
        ...rows().map((r) => [
          ...keys.map((k) => r[k]),
          sourceFor(r),
          data.screen_rule.min_hours_per_employee,
          data.screen_rule.max_hours_per_employee,
        ]),
      ]
        .map((row) => row.map(csvCell).join(","))
        .join("\r\n") + "\r\n"
    );
  }
  function download(text, type, suffix) {
    const blob = new Blob([text], { type }),
      url = URL.createObjectURL(blob),
      a = el("a");
    a.href = url;
    a.download =
      "osha-evidence-" +
      (tableScope === "annual" ? "annual-2016-2024" : period) +
      suffix;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    $("ev-status").textContent =
      "Downloaded " +
      scopeLabel() +
      (suffix === ".csv"
        ? " as CSV."
        : " with definitions, limitations, and source links.");
  }
  function noteText() {
    return (
      "# OSHA evidence review\n\nScope: " +
      scopeLabel() +
      "\nPopulation: OSHA Injury Tracking Application, self-reported Form 300A summaries.\n\n" +
      rows()
        .map(
          (r) =>
            "## " +
            r.year +
            "\n\n" +
            keys
              .slice(1)
              .map((k) => k + ": " + r[k])
              .join("\n") +
            "\nSource: " +
            sourceRoot +
            sourceFor(r),
        )
        .join("\n\n") +
      "\n\n## Definitions and limitations\n\n" +
      "TRIR = recordable cases × 200,000 ÷ hours worked. Aggregate rates use summed cases and hours, not a mean of establishment rates.\n" +
      "Screen: exclude filings with hours per average employee below " +
      data.screen_rule.min_hours_per_employee +
      " or above " +
      data.screen_rule.max_hours_per_employee +
      ", or missing hours/employees.\n" +
      "implausible_share and hours_share_implausible are fractions (0–1). ratio = screened TRIR ÷ as-filed TRIR.\n" +
      "These are establishment-year aggregates, not unique establishments or individual records. The pooled rate is not the mean of annual rates.\n" +
      "Screening does not verify filings or prove any change in safety. ITA filers do not represent every workplace; these are not BLS national estimates or inspection/citation records. No causal inference is supported.\n" +
      "Source snapshot: committed docs/explore-data.json, generated from the repository tables. Values retain the precision stored in that JSON.\n\n" +
      "View: " +
      location.href +
      "\nData: " +
      new URL("explore-data.json", location.href).href +
      "\nMethod: " +
      sourceRoot +
      "src/ehs_osha/quality.py\n"
    );
  }
  function theme() {
    const dark =
      document.documentElement.dataset.theme === "dark" ||
      (!document.documentElement.dataset.theme &&
        matchMedia("(prefers-color-scheme: dark)").matches);
    $("ev-theme").setAttribute(
      "aria-label",
      "Switch to " + (dark ? "light" : "dark") + " theme",
    );
    $("ev-theme").setAttribute("aria-pressed", String(dark));
  }
  $("ev-theme").addEventListener("click", () => {
    const next =
      $("ev-theme").getAttribute("aria-pressed") === "true" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("pc-theme", next);
    } catch (_) {
      /* Theme remains usable without storage. */
    }
    theme();
  });
  theme();
  fetch("./explore-data.json")
    .then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then((json) => {
      data = json;
      if (
        !Array.isArray(data.quality_by_year) ||
        !data.pooled ||
        !data.screen_rule
      )
        throw new Error("Unexpected aggregate schema");
      readState();
      writeState(true);
      $("ev-period").replaceChildren(
        ...data.quality_by_year.map((r) => {
          const o = el("option", String(r.year));
          o.value = String(r.year);
          return o;
        }),
      );
      const pooled = el("option", "2016–2024 pooled");
      pooled.value = "pooled";
      $("ev-period").append(pooled);
      $("ev-period").disabled = false;
      $("ev-period").addEventListener("change", (e) =>
        setPeriod(e.target.value),
      );
      document.querySelectorAll("[data-metric]").forEach((b) =>
        b.addEventListener("click", () => {
          metric = b.dataset.metric;
          render();
          writeState();
        }),
      );
      document.querySelectorAll("[data-table]").forEach((b) =>
        b.addEventListener("click", () => {
          tableScope = b.dataset.table;
          render();
          writeState();
          $("ev-status").textContent =
            "Table and export scope: " + scopeLabel() + ".";
        }),
      );
      $("ev-inspect-link").addEventListener("click", () => {
        tableScope = "selected";
        render();
        writeState();
        $("ev-data").focus({ preventScroll: true });
      });
      $("ev-csv").addEventListener("click", () =>
        download(csvText(), "text/csv;charset=utf-8", ".csv"),
      );
      $("ev-note").addEventListener("click", () =>
        download(noteText(), "text/markdown;charset=utf-8", "-review.md"),
      );
      $("ev-copy").addEventListener("click", async () => {
        // Peer input edits have a 150ms URL debounce; allow that state to settle first.
        await new Promise((resolve) => setTimeout(resolve, 180));
        try {
          await navigator.clipboard.writeText(location.href);
          $("ev-status").textContent =
            "View link copied, including the selected evidence scope and any peer inputs in the URL.";
        } catch (_) {
          $("ev-status").textContent =
            "Copy the address bar to share this view. It includes the selected scope and any peer inputs.";
        }
      });
      ["ev-csv", "ev-note", "ev-copy"].forEach(
        (id) => ($(id).disabled = false),
      );
      addEventListener("popstate", () => {
        readState();
        render();
      });
      render();
      $("ev-error").hidden = true;
      $("ev-content").hidden = false;
    })
    .catch((error) => {
      $("ev-error").textContent =
        "Aggregate data could not load (" +
        error.message +
        "). Reload to retry, or open the committed source tables linked in Data & method.";
    });
})();
