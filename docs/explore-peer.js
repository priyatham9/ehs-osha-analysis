/* Denominator explorer. Every figure is read from explore-data.json, which
   scripts/build_explore_data.py builds from committed outputs/ tables. */
(function () {
  "use strict";
  var DATA = null;
  var SVGNS = "http://www.w3.org/2000/svg";
  var EXAMPLE = {
    naics: "493",
    band: "050-099",
    emp: 60,
    hours: 120000,
    cases: 4,
    typo: false,
  };
  var PKEYS = ["p10", "p25", "p50", "p75", "p90", "p95"];
  var S = { naics: "", band: "", emp: "", hours: "", cases: "", typo: false };
  var isExample = true;
  var selYear = 2019;

  function $(id) {
    return document.getElementById(id);
  }
  function nf(v, d) {
    return Number(v).toLocaleString("en-US", {
      minimumFractionDigits: d || 0,
      maximumFractionDigits: d || 0,
    });
  }
  function pct(v, d) {
    return (v * 100).toFixed(d == null ? 1 : d) + "%";
  }
  function rate(v) {
    return v >= 100
      ? nf(v, 0)
      : v >= 10
        ? v.toFixed(1)
        : v >= 0.1
          ? v.toFixed(2)
          : v.toFixed(3);
  }
  function svg(tag, attrs, parent) {
    var e = document.createElementNS(SVGNS, tag);
    for (var k in attrs)
      if (attrs[k] != null) e.setAttribute(k, String(attrs[k]));
    if (parent) parent.appendChild(e);
    return e;
  }
  function t(parent, x, y, s, attrs) {
    var a = {
      x: x,
      y: y,
      fill: "var(--ink-2)",
      "font-size": 13,
      "font-family": "var(--font-mono)",
    };
    for (var k in attrs) a[k] = attrs[k];
    var n = svg("text", a, parent);
    n.textContent = s;
    return n;
  }
  function h(tag, attrs, parent) {
    var e = document.createElement(tag);
    for (var k in attrs) {
      if (k === "text") e.textContent = attrs[k];
      else if (k === "html") e.innerHTML = attrs[k];
      else e.setAttribute(k, attrs[k]);
    }
    if (parent) parent.appendChild(e);
    return e;
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function widthOf(node) {
    return Math.max(
      280,
      Math.round(node.getBoundingClientRect().width || node.clientWidth || 600),
    );
  }
  function title(code) {
    return DATA.titles[code] || "";
  }
  function bandFor(emp) {
    var edges = [1, 20, 50, 100, 250, 500, 1000];
    if (!(emp >= 1)) return null;
    for (var i = edges.length - 1; i >= 0; i--)
      if (emp >= edges[i]) return DATA.size_bands[i];
    return null;
  }
  function num(v) {
    if (v === "" || v == null) return NaN;
    var n = Number(v);
    return isFinite(n) ? n : NaN;
  }

  /* ---------------- state and URL ---------------- */
  function readUrl() {
    var q = new URLSearchParams(location.search);
    var has = false;
    ["naics", "band", "emp", "hours", "cases"].forEach(function (k) {
      if (q.has(k)) {
        S[k] = q.get(k);
        has = true;
      }
    });
    if (q.get("typo") === "1") {
      S.typo = true;
      has = true;
    }
    var y = q.get("y");
    if (y === "all") selYear = 0;
    else if (
      y &&
      DATA.quality_by_year.some(function (r) {
        return String(r.year) === y;
      })
    )
      selYear = +y;
    return has;
  }
  function loadExample() {
    S.naics = EXAMPLE.naics;
    S.band = EXAMPLE.band;
    S.emp = String(EXAMPLE.emp);
    S.hours = String(EXAMPLE.hours);
    S.cases = String(EXAMPLE.cases);
    S.typo = false;
  }
  var urlTimer = null;
  var pushNext = false;
  function writeUrl(push) {
    if (push) pushNext = true;
    if (urlTimer) clearTimeout(urlTimer);
    urlTimer = setTimeout(function () {
      var q = new URLSearchParams(location.search);
      ["naics", "band", "emp", "hours", "cases", "typo", "y"].forEach(
        function (k) {
          q.delete(k);
        },
      );
      q.set("naics", S.naics);
      q.set("band", S.band);
      if (S.emp !== "") q.set("emp", S.emp);
      if (S.hours !== "") q.set("hours", S.hours);
      if (S.cases !== "") q.set("cases", S.cases);
      if (S.typo) q.set("typo", "1");

      var url = location.pathname + "?" + q.toString() + location.hash;
      var same = url === location.pathname + location.search + location.hash;
      try {
        if (pushNext && !same) history.pushState(null, "", url);
        else history.replaceState(null, "", url);
      } catch (e) {
        /* file:// or sandboxed frame */
      }
      pushNext = false;
    }, 150);
  }
  function pushToForm() {
    $("naics3").value = S.naics;
    $("sizeband").value = S.band;
    $("naicsCode").value = S.naics;
    $("inEmp").value = S.emp;
    $("inHours").value = S.hours;
    $("inCases").value = S.cases;
    $("btnTypo").setAttribute("aria-pressed", S.typo ? "true" : "false");
  }

  /* ---------------- selects ---------------- */
  function populateSelects() {
    var sel = $("naics3");
    var titled = DATA.naics3_list
      .filter(function (c) {
        return title(c);
      })
      .sort(function (a, b) {
        return title(a).localeCompare(title(b));
      });
    var other = DATA.naics3_list.filter(function (c) {
      return !title(c);
    });
    var g1 = h("optgroup", { label: "NAICS 2022 subsectors" }, sel);
    titled.forEach(function (c) {
      h("option", { value: c, text: title(c) + " (" + c + ")" }, g1);
    });
    var g2 = h(
      "optgroup",
      { label: "Codes with no 2022 subsector title, as filed" },
      sel,
    );
    other.forEach(function (c) {
      h("option", { value: c, text: c + " (no 2022 title)" }, g2);
    });
    var sb = $("sizeband");
    DATA.size_bands.forEach(function (b) {
      h("option", { value: b, text: bandLabel(b) }, sb);
    });
  }
  function cell() {
    for (var i = 0; i < DATA.peers.length; i++) {
      var p = DATA.peers[i];
      if (p.naics3 === S.naics && p.size_band === S.band) return p;
    }
    return null;
  }

  /* ---------------- where a rate sits among stored percentiles ---------------- */
  function place(c, v) {
    if (v === 0)
      return {
        txt: "zero, like " + pct(c.zero_share, 0) + " of these peer filings",
        lo: null,
        hi: null,
        zero: true,
      };
    var prev = null;
    for (var i = 0; i < PKEYS.length; i++) {
      var k = PKEYS[i];
      if (v <= c[k]) {
        if (!prev) return { txt: "below the 10th percentile", lo: null, hi: k };
        return {
          txt: "between the " + ord(prev) + " and " + ord(k) + " percentile",
          lo: prev,
          hi: k,
        };
      }
      prev = k;
    }
    return { txt: "above the 95th percentile", lo: "p95", hi: null, top: true };
  }
  function ord(k) {
    var n = +k.slice(1);
    return n === 50 ? "50th (median)" : n + "th";
  }

  /* ---------------- render: the tool ---------------- */
  function render() {
    var c = cell();
    var emp = num(S.emp),
      hours0 = num(S.hours),
      cases = num(S.cases);
    var hours = S.typo && isFinite(hours0) ? hours0 * 1000 : hours0;
    var okH = isFinite(hours) && hours > 0,
      okC = isFinite(cases) && cases >= 0 && Math.floor(cases) === cases;
    var okE = isFinite(emp) && emp > 0;
    /* inline validation: a message next to the field, never only a colour */
    setErr(
      "inEmp",
      S.emp === ""
        ? touched.inEmp
          ? "Add average employees to run the hours check."
          : ""
        : !okE || Math.floor(emp) !== emp
          ? "Enter a whole number of people, 1 or more."
          : "",
      S.emp === "",
    );
    setErr(
      "inHours",
      S.hours === ""
        ? touched.inHours
          ? "Enter the hours worked in the year to compute a rate."
          : ""
        : !(isFinite(hours0) && hours0 > 0)
          ? "Hours must be a number above zero."
          : "",
    );
    setErr(
      "inCases",
      S.cases === ""
        ? touched.inCases
          ? "Enter the recordable cases, 0 or more."
          : ""
        : !okC
          ? "Enter a whole number of cases, 0 or more."
          : okE && cases > emp
            ? "More recordable cases than employees is unusual. Check the count; the rate below uses it as entered."
            : "",
      okC && okE && cases > emp,
    );

    var ex = $("example");
    ex.setAttribute("data-mode", isExample ? "example" : "own");
    ex.innerHTML = isExample
      ? "<span><b>Worked example.</b> A " +
        EXAMPLE.emp +
        "-person warehouse, " +
        nf(EXAMPLE.hours) +
        " hours (2,000 each), " +
        EXAMPLE.cases +
        " recordable cases. Type over it, or clear it to start from blank fields.</span>"
      : "<span><b>Your numbers.</b> Nothing is sent anywhere; the link below carries them.</span>";

    /* TRIR */
    var trir = okH && okC ? (cases * 200000) / hours : NaN;
    var trirRaw =
      S.typo && isFinite(hours0) && hours0 > 0 && okC
        ? (cases * 200000) / hours0
        : NaN;
    $("trirN").innerHTML = isFinite(trir) ? rate(trir) : "-";
    $("trirS").textContent = !isFinite(trir)
      ? "Enter hours above zero and a whole number of cases."
      : S.typo
        ? "As typed, with three extra zeros. The real rate is " +
          rate(trirRaw) +
          ", so the typo reduces the reported rate by a factor of " +
          nf(1000) +
          "."
        : "Recordable cases \u00d7 200,000 \u00f7 hours worked: cases per 100 full-time workers for a year.";
    $("vTrir").classList.toggle("is-bad", !!S.typo && isFinite(trir));

    /* hours check */
    var lo = DATA.screen_rule.min_hours_per_employee,
      hi = DATA.screen_rule.max_hours_per_employee;
    var hpe = okH && okE ? hours / emp : NaN;
    var fail = isFinite(hpe) && (hpe < lo || hpe > hi);
    var hpeTxt;
    if (!isFinite(hpe)) {
      $("hpeN").innerHTML = '<span class="pill na">not checked</span>';
      hpeTxt = okH
        ? "Add average employees to run the screen the pipeline uses."
        : "Enter hours and employees.";
    } else {
      $("hpeN").innerHTML = nf(hpe, 0) + "<small> h / employee</small>";
      hpeTxt =
        (fail
          ? '<span class="pill bad">Fails the screen</span> '
          : '<span class="pill ok">Passes</span> ') +
        (hpe > hi
          ? "More than " +
            nf(hi) +
            " hours per person a year. There are only 8,760 hours in a year; a full-time year is about 2,000."
          : hpe < lo
            ? "Fewer than " +
              nf(lo) +
              " hours per person a year: about three weeks of full-time work."
            : "Inside " +
              nf(lo) +
              " to " +
              nf(hi) +
              " hours per person a year.");
    }
    $("hpeS").innerHTML = hpeTxt;
    $("vScreen").classList.toggle("is-bad", fail);

    /* readout sentence */
    var ro = $("readout");
    if (!c) {
      ro.innerHTML =
        "No screened filings exist for this industry and size band. Try a neighbouring size band.";
    } else if (!isFinite(trir)) {
      ro.innerHTML = "Enter hours and recordable cases to place a rate.";
    } else {
      var pl = place(c, trir);
      var who =
        (title(c.naics3) || "NAICS " + c.naics3) +
        ", " +
        bandLabel(c.size_band);
      var s;
      if (fail) {
        s =
          '<span class="warnw">This filing would be excluded.</span> Its hours per employee fail the screen, so the pipeline leaves it out of every rate and every peer table. As filed, its rate would read ' +
          pl.txt +
          " of " +
          esc(who) +
          ".";
        if (S.typo)
          s +=
            " That is how a keying error turns into a flattering benchmark when nobody screens.";
      } else {
        s =
          "A rate of <b>" +
          rate(trir) +
          "</b> sits <b>" +
          pl.txt +
          "</b> of " +
          nf(c.n) +
          " screened filings in " +
          esc(who) +
          ".";
        if (!pl.zero && c.p50 > 0)
          s +=
            " That is " +
            (trir / c.p50).toFixed(1) +
            " times the peer median of " +
            rate(c.p50) +
            ".";
        if (!pl.zero && c.zero_share >= 0.25)
          s +=
            " " +
            pct(c.zero_share, 0) +
            " of these peers reported zero cases, so a single injury moves a site a long way.";
        if (pl.zero && c.zero_share >= 0.25)
          s +=
            " At this size a clean year is common; one case would move this site well up the table.";
      }
      if (!c.publishable)
        s +=
          ' <span class="warnw">Only ' +
          nf(c.n) +
          " filings in this cell, under the 30 needed to publish it.</span>";
      ro.innerHTML = s;
    }
    announce(
      !c
        ? ro.textContent
        : !isFinite(trir)
          ? "No rate available. Enter valid hours and a whole number of recordable cases."
          : "TRIR " +
            rate(trir) +
            ". " +
            (isFinite(hpe)
              ? fail
                ? "Fails the hours check. "
                : "Passes the hours check. "
              : "") +
            "Sits " +
            place(c, trir).txt +
            " of " +
            nf(c.n) +
            " screened peer filings.",
    );

    var mr = $("miniRes");
    mr.innerHTML = isFinite(trir)
      ? "TRIR <b>" +
        rate(trir) +
        "</b> &middot; " +
        (isFinite(hpe)
          ? fail
            ? "fails the hours check"
            : "passes the hours check"
          : "hours not checked") +
        (c ? " &middot; " + place(c, trir).txt.replace(/,.*$/, "") : "") +
        " &darr;"
      : "Enter your numbers to see a result &darr;";
    renderBand(c, trir, fail);
    writeUrl();
  }
  var touched = {};
  function setErr(id, msg, soft) {
    var e = $(id + "-err"),
      inp = $(id);
    if (e) {
      e.textContent = msg;
      e.classList.toggle("is-soft", !!soft && !!msg);
    }
    inp.setAttribute("aria-invalid", msg && !soft ? "true" : "false");
  }
  var annT = null,
    lastAnn = "";
  function announce(msg) {
    if (annT) clearTimeout(annT);
    annT = setTimeout(function () {
      if (msg && msg !== lastAnn) {
        lastAnn = msg;
        $("announce").textContent = msg;
      }
    }, 900);
  }
  function bandLabel(b) {
    return (
      (b === "1000+"
        ? "1,000 or more"
        : b.replace(/^0+/, "").replace(/-0*/, " to ")) + " employees"
    );
  }

  function renderBand(c, trir, fail) {
    var wrap = $("bandChart"),
      cap = $("bandCaption"),
      tbl = $("bandTable");
    wrap.innerHTML = "";
    tbl.innerHTML = "";
    if (!c) {
      cap.textContent = "";
      return;
    }
    var W = widthOf(wrap),
      narrow = W < 520;
    var H = narrow ? 180 : 172;
    var L = 14,
      R = 18,
      midY = narrow ? 92 : 84;
    var hasT = isFinite(trir);
    var maxV = Math.max(c.p95, 1) * 1.08;
    var over = hasT && trir > maxV;
    function X(v) {
      return L + (Math.min(v, maxV) / maxV) * (W - L - R);
    }
    var s = svg(
      "svg",
      {
        viewBox: "0 0 " + W + " " + H,
        width: W,
        height: H,
        role: "img",
        "aria-label":
          "Screened TRIR percentiles for " +
          (title(c.naics3) || "NAICS " + c.naics3) +
          ", " +
          bandLabel(c.size_band) +
          ": p10 " +
          rate(c.p10) +
          ", p25 " +
          rate(c.p25) +
          ", median " +
          rate(c.p50) +
          ", p75 " +
          rate(c.p75) +
          ", p90 " +
          rate(c.p90) +
          ", p95 " +
          rate(c.p95) +
          (hasT
            ? ". Your rate " +
              rate(trir) +
              (fail ? ", which would fail the hours screen" : "")
            : "") +
          ".",
      },
      wrap,
    );
    var nt = narrow ? 3 : 5;
    for (var i = 0; i <= nt; i++) {
      var v = (maxV * i) / nt,
        x = X(v);
      svg(
        "line",
        {
          x1: x,
          x2: x,
          y1: midY - 34,
          y2: midY + 30,
          stroke: "var(--rule-soft)",
          "stroke-width": 1,
        },
        s,
      );
      t(s, x, midY + 58, v.toFixed(v < 10 ? 1 : 0), {
        "text-anchor": i === 0 ? "start" : i === nt ? "end" : "middle",
        fill: "var(--muted)",
      });
    }
    t(s, L, H - 6, "screened TRIR, cases per 200,000 hours", {
      fill: "var(--muted)",
      "font-size": 13,
    });
    svg(
      "rect",
      {
        x: X(c.p10),
        y: midY - 18,
        width: Math.max(X(c.p90) - X(c.p10), 2),
        height: 36,
        fill: "var(--s1)",
        opacity: 0.22,
      },
      s,
    );
    svg(
      "rect",
      {
        x: X(c.p25),
        y: midY - 12,
        width: Math.max(X(c.p75) - X(c.p25), 2),
        height: 24,
        fill: "var(--s1)",
        opacity: 0.5,
      },
      s,
    );
    svg(
      "line",
      {
        x1: X(c.p50),
        x2: X(c.p50),
        y1: midY - 20,
        y2: midY + 20,
        stroke: "var(--s1)",
        "stroke-width": 3,
      },
      s,
    );
    svg(
      "circle",
      {
        cx: X(c.p95),
        cy: midY,
        r: 4,
        fill: "var(--surface)",
        stroke: "var(--s1)",
        "stroke-width": 2,
      },
      s,
    );
    /* percentile labels on alternating rows so they never collide */
    var lastX = { top: -99, bot: -99 };
    PKEYS.forEach(function (k, i) {
      var x = X(c[k]);
      var row = i % 2 ? "bot" : "top";
      if (x - lastX[row] < (narrow ? 34 : 40)) return;
      lastX[row] = x;
      t(s, x, row === "top" ? midY - 26 : midY + 34, k === "p50" ? "med" : k, {
        "text-anchor": "middle",
        "font-size": 13,
        fill: "var(--ink-2)",
        "font-weight": 600,
      });
    });
    if (hasT) {
      var mx = X(trir),
        col = fail ? "var(--warn)" : "var(--s2)";
      svg(
        "line",
        {
          x1: mx,
          x2: mx,
          y1: midY - 40,
          y2: midY + 24,
          stroke: col,
          "stroke-width": 3,
        },
        s,
      );
      svg(
        "polygon",
        {
          points:
            mx -
            7 +
            "," +
            (midY - 50) +
            " " +
            (mx + 7) +
            "," +
            (midY - 50) +
            " " +
            mx +
            "," +
            (midY - 40),
          fill: col,
        },
        s,
      );
      var lab =
        (fail ? "excluded: " : "you: ") +
        rate(trir) +
        (over ? " (off scale)" : "");
      var anchor = mx > W * 0.7 ? "end" : mx < W * 0.3 ? "start" : "middle";
      t(
        s,
        mx + (anchor === "end" ? 8 : anchor === "start" ? -8 : 0),
        midY - 56,
        lab,
        {
          "text-anchor": anchor,
          fill: col,
          "font-weight": 700,
          "font-size": 14,
        },
      );
    }
    cap.textContent =
      nf(c.n) +
      " screened establishment-year filings, 2016 to 2024. " +
      pct(c.zero_share, 0) +
      " reported zero recordable cases. " +
      (c.publishable
        ? "Meets the pipeline's 30-filing publishing threshold."
        : "Below the pipeline's 30-filing publishing threshold: read with caution.");
    var tb = h("table", {}, tbl),
      tr = h("tr", {}, h("thead", {}, tb));
    ["Percentile", "Screened TRIR"].forEach(function (x) {
      h("th", { scope: "col", text: x }, tr);
    });
    var body = h("tbody", {}, tb);
    PKEYS.forEach(function (k) {
      var r = h("tr", {}, body);
      h("td", { text: k }, r);
      h("td", { text: c[k].toFixed(2) }, r);
    });
    var r2 = h("tr", {}, body);
    h("td", { text: "zero-case share" }, r2);
    h("td", { text: pct(c.zero_share, 1) }, r2);
    var r3 = h("tr", {}, body);
    h("td", { text: "filings (n)" }, r3);
    h("td", { text: nf(c.n) }, r3);
  }

  /* ---------------- wiring ---------------- */
  function markOwn() {
    if (isExample) {
      isExample = false;
    }
  }
  function bind() {
    $("naics3").addEventListener("change", function () {
      S.naics = this.value;
      $("naicsCode").value = S.naics;
      setErr("naicsCode", "");
      markOwn();
      render();
      writeUrl(true);
    });
    $("sizeband").addEventListener("change", function () {
      S.band = this.value;
      markOwn();
      render();
      writeUrl(true);
    });
    $("naicsCode").addEventListener("input", function () {
      var v = this.value.trim();
      if (v === "") {
        setErr("naicsCode", "");
        return;
      }
      if (!/^\d+$/.test(v)) {
        setErr("naicsCode", "Use digits only, like 493 or 493110.");
        return;
      }
      if (v.length < 3) {
        setErr("naicsCode", "Keep typing: at least 3 digits.");
        return;
      }
      var c3 = v.slice(0, 3);
      if (DATA.naics3_list.indexOf(c3) < 0) {
        setErr(
          "naicsCode",
          "No screened filings for NAICS " +
            c3 +
            ". Check the code, or pick an industry below.",
        );
        return;
      }
      setErr("naicsCode", "");
      if (c3 !== S.naics) {
        S.naics = c3;
        $("naics3").value = c3;
        markOwn();
        render();
        writeUrl(true);
      }
    });
    ["inEmp", "inHours", "inCases"].forEach(function (id) {
      $(id).addEventListener("blur", function () {
        touched[id] = true;
        render();
      });
      $(id).addEventListener("change", function () {
        writeUrl(true);
      });
    });
    $("btnClear").addEventListener("click", function () {
      S.emp = "";
      S.hours = "";
      S.cases = "";
      S.typo = false;
      isExample = false;
      touched = {};
      pushToForm();
      $("btnTypo").textContent = "Add three zeros to the hours";
      render();
      writeUrl(true);
      $("copyStatus").textContent =
        "Fields cleared. Start with average employees.";
      $("inEmp").focus();
    });
    window.addEventListener("popstate", function () {
      if (location.search) {
        S.emp = "";
        S.hours = "";
        S.cases = "";
        S.typo = false;
      } else loadExample();
      selYear = 2019;
      readUrl();
      if (DATA.naics3_list.indexOf(S.naics) < 0) S.naics = EXAMPLE.naics;
      if (DATA.size_bands.indexOf(S.band) < 0)
        S.band = bandFor(num(S.emp)) || EXAMPLE.band;
      isExample =
        S.naics === EXAMPLE.naics &&
        S.band === EXAMPLE.band &&
        S.emp === String(EXAMPLE.emp) &&
        S.hours === String(EXAMPLE.hours) &&
        S.cases === String(EXAMPLE.cases) &&
        !S.typo;
      pushToForm();
      $("btnTypo").textContent = S.typo
        ? "Remove the three zeros"
        : "Add three zeros to the hours";
      render();
    });
    var cta = $("ctaRank");
    if (cta)
      cta.addEventListener("click", function () {
        setTimeout(function () {
          try {
            $("naicsCode").focus({ preventScroll: true });
          } catch (e) {
            $("naicsCode").focus();
          }
        }, 450);
      });
    $("inEmp").addEventListener("input", function () {
      S.emp = this.value.trim();
      markOwn();
      var b = bandFor(num(S.emp));
      if (b && b !== S.band) {
        S.band = b;
        $("sizeband").value = b;
      }
      render();
    });
    $("inHours").addEventListener("input", function () {
      S.hours = this.value.trim();
      markOwn();
      render();
    });
    $("inCases").addEventListener("input", function () {
      S.cases = this.value.trim();
      markOwn();
      render();
    });
    $("btnTypo").addEventListener("click", function () {
      S.typo = !S.typo;
      this.setAttribute("aria-pressed", String(S.typo));
      this.textContent = S.typo
        ? "Remove the three zeros"
        : "Add three zeros to the hours";
      render();
      writeUrl(true);
    });
    $("btnReset").addEventListener("click", function () {
      loadExample();
      isExample = true;
      touched = {};
      selYear = 2019;
      pushToForm();
      setErr("naicsCode", "");
      $("btnTypo").textContent = "Add three zeros to the hours";
      render();
      writeUrl(true);
      $("copyStatus").textContent = "Worked example restored.";
    });
    $("btnCopy").addEventListener("click", function () {
      writeUrl();
      setTimeout(function () {
        var url = location.href,
          st = $("copyStatus");
        function done(ok) {
          st.textContent = ok
            ? "Link copied. It opens this exact view."
            : "Copy the address bar to share this view.";
        }
        if (navigator.clipboard && navigator.clipboard.writeText)
          navigator.clipboard.writeText(url).then(
            function () {
              done(true);
            },
            function () {
              done(false);
            },
          );
        else done(false);
      }, 170);
    });
    $("tool-form").addEventListener("submit", function (e) {
      e.preventDefault();
    });
    var rt = null,
      lastW = window.innerWidth;
    window.addEventListener(
      "resize",
      function () {
        if (rt) clearTimeout(rt);
        rt = setTimeout(function () {
          if (window.innerWidth === lastW) return;
          lastW = window.innerWidth;
          render();
        }, 150);
      },
      { passive: true },
    );
  }

  function init() {
    $("result").setAttribute("aria-busy", "true");
    fetch("./explore-data.json")
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (json) {
        DATA = json;
        populateSelects();
        var fromUrl = readUrl();
        if (!fromUrl) loadExample();
        else {
          if (DATA.naics3_list.indexOf(S.naics) < 0) S.naics = EXAMPLE.naics;
          if (DATA.size_bands.indexOf(S.band) < 0)
            S.band = bandFor(num(S.emp)) || EXAMPLE.band;
          isExample =
            S.naics === EXAMPLE.naics &&
            S.band === EXAMPLE.band &&
            S.emp === String(EXAMPLE.emp) &&
            S.hours === String(EXAMPLE.hours) &&
            S.cases === String(EXAMPLE.cases) &&
            !S.typo;
        }
        pushToForm();
        if (S.typo) $("btnTypo").textContent = "Remove the three zeros";
        bind();
        render();

        $("result").removeAttribute("aria-busy");
      })
      .catch(function (err) {
        $("result").removeAttribute("aria-busy");
        var ro = $("readout");
        ro.classList.add("is-error");
        ro.textContent =
          "The peer table did not load (" +
          err.message +
          "). Reload the page to try again. If you opened this file directly, serve the docs folder over HTTP.";
      });
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
