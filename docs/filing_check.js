/* Evaluate one Form 300A filing against plausibility_rules.json.
   Mirrors src/ehs_osha/filing_check.py; tests/test_filing_check_parity.py checks agreement. */
(function (root) {
  "use strict";

  function num(v) {
    if (v === null || v === undefined || typeof v === "boolean" || v === "") return NaN;
    var x = Number(v);
    return isFinite(x) ? x : NaN;
  }

  function evalFlag(flag, rec, params, cases) {
    var x, i;
    switch (flag.kind) {
      case "missing_or_at_most":
        x = num(rec[flag.field]);
        return isNaN(x) || x <= flag.value;
      case "missing_or_below":
        x = num(rec[flag.field]);
        return isNaN(x) || x < flag.value;
      case "negative_or_incomplete_cases":
        if (isNaN(cases)) return true;
        for (i = 0; i < flag.fields.length; i++) {
          x = num(rec[flag.fields[i]]);
          if (!isNaN(x) && x < 0) return true;
        }
        return false;
      case "ratio_above":
      case "ratio_below": {
        var n = num(rec[flag.numerator]), d = num(rec[flag.denominator]);
        if (isNaN(n) || isNaN(d) || !(d > flag.denominator_must_exceed)) return false;
        var bound = params[flag.param];
        return flag.kind === "ratio_above" ? n / d > bound : n / d < bound;
      }
      case "checkbox_contradiction":
        x = num(rec[flag.field]);
        if (isNaN(x) || isNaN(cases)) return false;
        for (i = 0; i < flag.contradictions.length; i++) {
          var c = flag.contradictions[i];
          if (x === c.value && ((c.when === "cases_positive" && cases > 0) ||
                                (c.when === "cases_zero" && cases === 0))) return true;
        }
        return false;
      default:
        throw new Error("unknown rule kind: " + flag.kind);
    }
  }

  function checkFiling(record, rules, overrides) {
    var params = Object.assign({}, rules.params, overrides || {});
    var cases = 0, i;
    for (i = 0; i < rules.case_fields.length; i++) cases += num(record[rules.case_fields[i]]);
    var flags = {}, messages = [], implausible = false;
    rules.flags.forEach(function (flag) {
      var hit = evalFlag(flag, record, params, cases);
      var counts = flag.counts_toward_implausible;
      if (typeof counts === "string") counts = !!params[counts.split(":")[1]];
      flags[flag.id] = hit;
      if (hit) { messages.push(flag.message); implausible = implausible || counts; }
    });
    return { flags: flags, implausible: implausible, messages: messages };
  }

  var api = { checkFiling: checkFiling };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.FilingCheck = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
