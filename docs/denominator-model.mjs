/** Local-only CSV parsing and deterministic exposure influence accounting.
 * No row is repaired or classified as erroneous. All analysis uses the selected
 * years; influence is measured against the ratio-screened baseline, before
 * manual review exclusions. IEEE-754 arithmetic is used for fractional hours.
 */
export class AuditError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = 'AuditError';
    this.code = code;
    Object.assign(this, details);
  }
}

const MAX_SAFE = Number.MAX_SAFE_INTEGER;
const DEFAULT_MAX_BYTES = 10 * 1024 * 1024;
const DEFAULT_MAX_ROWS = 50000;
const MAX_COLUMNS = 128;
const REQUIRED = ['year', 'employees', 'hours', 'cases'];
const NUMBER_PATTERN = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
const fail = (code, message, details) => { throw new AuditError(code, message, details); };

// Number('1.00000000000000001') rounds to 1. Check the decimal's mathematical
// integrality before accepting counts/years, not just Number.isInteger(result).
function isExactDecimalInteger(text) {
  const parts = text.replace(/^[+-]/, '').toLowerCase().split('e');
  const mantissa = parts[0];
  const exponent = parts.length === 2 ? Number(parts[1]) : 0;
  const fractionLength = mantissa.includes('.') ? mantissa.length - mantissa.indexOf('.') - 1 : 0;
  const digits = mantissa.replace('.', '');
  if (/^0+$/.test(digits)) return true;
  const shift = exponent - fractionLength;
  if (shift >= 0) return true;
  const trailingCount = -shift;
  if (trailingCount > digits.length) return false;
  return /^0+$/.test(digits.slice(digits.length - trailingCount));
}

function exceedsExactSafeMagnitude(text) {
  const parts = text.replace(/^[+-]/, '').toLowerCase().split('e');
  const mantissa = parts[0], exponent = parts.length === 2 ? Number(parts[1]) : 0;
  const fractionLength = mantissa.includes('.') ? mantissa.length - mantissa.indexOf('.') - 1 : 0;
  const digits = mantissa.replace('.', '').replace(/^0+/, '');
  if (!digits) return false;
  const integerLength = digits.length + exponent - fractionLength;
  if (integerLength !== 16) return integerLength > 16;
  const integerPart = digits.slice(0, 16).padEnd(16, '0');
  const ceiling = String(MAX_SAFE);
  return integerPart > ceiling || (integerPart === ceiling && /[1-9]/.test(digits.slice(16)));
}

function numeric(text, field, row, {integer = false, allowZero = false} = {}) {
  const valueText = text.trim();
  const detail = {row, field};
  if (!valueText || !NUMBER_PATTERN.test(valueText)) {
    fail('INVALID_NUMBER', `Row ${row}: ${field} must contain a numeric value.`, detail);
  }
  const value = Number(valueText);
  if (!Number.isFinite(value) || Math.abs(value) > MAX_SAFE || exceedsExactSafeMagnitude(valueText)) {
    fail('UNSAFE_NUMBER', `Row ${row}: ${field} must be finite and within the safe numeric range.`, detail);
  }
  if (integer && (!Number.isSafeInteger(value) || !isExactDecimalInteger(valueText))) {
    fail('NONINTEGER', `Row ${row}: ${field} must be a whole number within the safe numeric range.`, detail);
  }
  if (allowZero ? value < 0 : value <= 0) {
    fail('OUT_OF_RANGE', `Row ${row}: ${field} must be ${allowZero ? 'zero or positive' : 'positive'}.`, detail);
  }
  return value;
}

/** Parse RFC-style quoted CSV with explicit resource and data validation. */
export function parseCsv(text, {maxBytes = DEFAULT_MAX_BYTES, maxRows = DEFAULT_MAX_ROWS} = {}) {
  if (typeof text !== 'string') fail('INVALID_INPUT', 'Choose a CSV text file.');
  if (!Number.isSafeInteger(maxBytes) || maxBytes <= 0 || maxBytes > DEFAULT_MAX_BYTES ||
      !Number.isSafeInteger(maxRows) || maxRows <= 0 || maxRows > DEFAULT_MAX_ROWS) {
    fail('INVALID_LIMIT', 'CSV limits must be positive and no larger than 10 MB and 50,000 records.');
  }
  if (text.length > maxBytes || new TextEncoder().encode(text).byteLength > maxBytes) {
    fail('FILE_TOO_LARGE', `CSV exceeds the ${maxBytes.toLocaleString('en-US')}-byte limit.`);
  }
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  if (!text.length) fail('EMPTY_FILE', 'The CSV is empty. Include the required column headers and records.');
  const rows = [];
  let cells = [], cell = '', quoted = false, afterQuote = false, line = 1, startLine = 1;
  let recordStarted = false;
  const pushCell = () => {
    cells.push(cell);
    cell = '';
    afterQuote = false;
    if (cells.length > MAX_COLUMNS) fail('TOO_MANY_COLUMNS', `Row ${startLine}: at most ${MAX_COLUMNS} columns are supported.`, {row: startLine});
  };
  const pushRow = () => {
    pushCell();
    rows.push({cells, sourceRow: startLine});
    if (rows.length - 1 > maxRows) fail('TOO_MANY_ROWS', `CSV exceeds the ${maxRows.toLocaleString('en-US')}-record limit.`);
    cells = [];
    recordStarted = false;
  };
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') { cell += '"'; i++; }
        else { quoted = false; afterQuote = true; }
      } else if (ch === '\r') {
        cell += ch;
        if (text[i + 1] === '\n') { cell += '\n'; i++; }
        line++;
      } else { cell += ch; if (ch === '\n') line++; }
      continue;
    }
    if (afterQuote && ch !== ',' && ch !== '\r' && ch !== '\n') {
      fail('MALFORMED_CSV', `Row ${startLine}: unexpected text after a closing quote.`, {row: startLine});
    }
    if (ch === '"') {
      if (cell.length || afterQuote) fail('MALFORMED_CSV', `Row ${startLine}: quote inside an unquoted field.`, {row: startLine});
      quoted = true;
      recordStarted = true;
    } else if (ch === ',') {
      pushCell();
      recordStarted = true;
    } else if (ch === '\r' || ch === '\n') {
      pushRow();
      if (ch === '\r' && text[i + 1] === '\n') i++;
      line++;
      startLine = line;
    } else {
      cell += ch;
      recordStarted = true;
    }
  }
  if (quoted) fail('MALFORMED_CSV', `Row ${startLine}: a quoted field is not closed.`, {row: startLine});
  if (recordStarted || cells.length || cell.length || afterQuote) pushRow();
  const header = rows.shift();
  if (!header) fail('EMPTY_FILE', 'The CSV is empty.');
  const columns = header.cells.map(value => value.trim().toLowerCase());
  if (columns.some(value => !value || value.length > 128)) {
    fail('INVALID_HEADER', 'Column names must be nonempty and at most 128 characters.');
  }
  if (new Set(columns).size !== columns.length) fail('DUPLICATE_HEADER', 'The CSV contains duplicate column names.');
  const positions = new Map(columns.map((name, i) => [name, i]));
  const missing = REQUIRED.filter(name => !positions.has(name));
  if (missing.length) fail('MISSING_HEADER', `Missing required columns: ${missing.join(', ')}.`);
  if (!rows.length) fail('NO_RECORDS', 'The CSV has headers but no records.');
  const idsByYear = new Map();
  const records = rows.map(({cells: values, sourceRow}, index) => {
    if (values.length !== columns.length) fail('COLUMN_COUNT', `Row ${sourceRow}: expected ${columns.length} fields; found ${values.length}.`, {row: sourceRow});
    const get = name => values[positions.get(name)];
    const year = numeric(get('year'), 'year', sourceRow, {integer: true});
    const employees = numeric(get('employees'), 'employees', sourceRow);
    const hours = numeric(get('hours'), 'hours', sourceRow);
    const cases = numeric(get('cases'), 'cases', sourceRow, {integer: true, allowZero: true});
    const filingId = positions.has('filing_id') ? get('filing_id').trim() : '';
    if (filingId.length > 512) fail('IDENTIFIER_TOO_LONG', `Row ${sourceRow}: filing_id must be at most 512 characters.`, {row: sourceRow, field: 'filing_id'});
    if (filingId) {
      if (!idsByYear.has(year)) idsByYear.set(year, new Set());
      const known = idsByYear.get(year);
      if (known.has(filingId)) fail('DUPLICATE_ID', `Row ${sourceRow}: filing_id repeats within the same year.`, {row: sourceRow, field: 'filing_id'});
      known.add(filingId);
    }
    return {key: `row:${index + 2}`, sourceRow, filingId, year, employees, hours, cases};
  });
  return {columns, records, years: [...new Set(records.map(r => r.year))].sort((a, b) => a - b)};
}

function sum(values) {
  let total = 0, correction = 0;
  for (const value of values) {
    const adjusted = value - correction;
    const next = total + adjusted;
    correction = (next - total) - adjusted;
    total = next;
  }
  return total;
}

function exposureSums(records, field, reverse = false) {
  const out = new Float64Array(records.length + 1);
  let total = 0, correction = 0;
  for (let step = 0; step < records.length; step++) {
    const i = reverse ? records.length - 1 - step : step;
    const adjusted = records[i][field] - correction;
    const next = total + adjusted;
    correction = (next - total) - adjusted;
    total = next;
    out[reverse ? i : i + 1] = total;
  }
  return out;
}

function totals(records, year) {
  const hours = sum(records.map(r => r.hours));
  const cases = sum(records.map(r => r.cases));
  if (!Number.isFinite(hours) || hours > MAX_SAFE || !Number.isSafeInteger(cases)) {
    fail('UNSAFE_AGGREGATE', `Year ${year}: summed hours or cases exceed the safe numeric range.`);
  }
  return {hours, cases, rate: rateFor(cases, hours, year)};
}

function rateFor(cases, hours, year) {
  if (hours <= 0) return null;
  const value = (cases / hours) * 200000;
  if (!Number.isFinite(value)) fail('UNSAFE_RATE', `Year ${year}: the rate exceeds finite arithmetic; inspect the exposure values.`);
  return value;
}

function comparison(before, after) {
  const change = before !== null && after !== null ? after - before : null;
  const percentage = before !== null && before > 0 && after !== null ? 100 * (after / before - 1) : null;
  return {change, changePct: percentage !== null && Number.isFinite(percentage) ? percentage : null};
}

/** Analyze two years without altering input data or silently discarding bad rows. */
export function analyzeDataset(dataset, {years, low = 120, high = 4500, excludedKeys = []} = {}) {
  if (!dataset || !Array.isArray(dataset.records) || !dataset.records.length) fail('INVALID_DATASET', 'Load a validated CSV dataset first.');
  if (!Number.isFinite(low) || !Number.isFinite(high) || low < 0 || high <= low) {
    fail('INVALID_SCREEN', 'Screen bounds must be finite and satisfy 0 ≤ lower < upper.');
  }
  const availableYears = [...new Set(dataset.records.map(r => r.year))].sort((a, b) => a - b);
  const selectedYears = (years === undefined ? availableYears.slice(-2) : years);
  if (!Array.isArray(selectedYears) || selectedYears.length !== 2) fail('INVALID_YEARS', 'Choose exactly two distinct years.');
  const selected = selectedYears.map(Number).sort((a, b) => a - b);
  if (selected[0] === selected[1] || selected.some(year => !Number.isSafeInteger(year) || !availableYears.includes(year))) {
    fail('INVALID_YEARS', 'Choose two distinct years present in this CSV.');
  }
  if (!Array.isArray(excludedKeys)) fail('INVALID_EXCLUSIONS', 'Review selections must be a list of row keys.');
  const knownKeys = new Set(dataset.records.map(r => r.key));
  if (knownKeys.size !== dataset.records.length) fail('DUPLICATE_KEY', 'Dataset row keys are not unique; reload the CSV.');
  if (excludedKeys.some(key => !knownKeys.has(key))) fail('UNKNOWN_KEY', 'A review selection refers to a row not present in this dataset.');
  const excluded = new Set(excludedKeys);
  const records = dataset.records.filter(r => selected.includes(r.year)).map(r => {
    if (![r.employees, r.hours, r.cases, r.year].every(Number.isFinite) ||
        r.employees <= 0 || r.hours <= 0 || r.cases < 0 || !Number.isSafeInteger(r.cases) ||
        r.hours > MAX_SAFE || r.employees > MAX_SAFE || !Number.isSafeInteger(r.year)) {
      fail('INVALID_DATASET', 'The loaded dataset contains an invalid numeric record; reload the CSV.');
    }
    const hoursPerEmployee = r.hours / r.employees;
    const screenPass = hoursPerEmployee >= low && hoursPerEmployee <= high;
    return {...r, hoursPerEmployee, screenPass, excluded: screenPass && excluded.has(r.key),
      baselineRate: null, leaveOneOutRate: null, leaveOneOutChange: null,
      leaveOneOutTrendChange: null, leaveOneOutTrendChangePct: null,
      absoluteInfluence: null, influenceRank: null, reversesTrend: false,
      yearHoursShare: null, influenceBasis: 'screened_baseline'};
  });
  const annual = selected.map(year => {
    const all = records.filter(r => r.year === year);
    const accepted = all.filter(r => r.screenPass);
    const retained = accepted.filter(r => !r.excluded);
    const base = totals(accepted, year), review = totals(retained, year);
    const prefixHours = exposureSums(accepted, 'hours');
    const suffixHours = exposureSums(accepted, 'hours', true);
    const prefixCases = exposureSums(accepted, 'cases');
    const suffixCases = exposureSums(accepted, 'cases', true);
    accepted.forEach((r, i) => {
      // Avoid total-minus-dominant-row cancellation: sum the two remaining sides.
      const remainingHours = sum([prefixHours[i], suffixHours[i + 1]]);
      const remainingCases = prefixCases[i] + suffixCases[i + 1];
      r.baselineRate = base.rate;
      r.yearHoursShare = r.hours / base.hours;
      if (remainingHours > 0) {
        r.leaveOneOutRate = rateFor(remainingCases, remainingHours, year);
        r.leaveOneOutChange = r.leaveOneOutRate - base.rate;
        r.absoluteInfluence = Math.abs(r.leaveOneOutChange);
      }
    });
    accepted.filter(r => r.absoluteInfluence !== null)
      .sort((a, b) => b.absoluteInfluence - a.absoluteInfluence || a.sourceRow - b.sourceRow)
      .forEach((r, i) => { r.influenceRank = i + 1; });
    return {year, nTotal: all.length, nAccepted: accepted.length, nRejected: all.length - accepted.length,
      nExcluded: accepted.length - retained.length, ...base,
      reviewN: retained.length, reviewHours: review.hours, reviewCases: review.cases, reviewRate: review.rate};
  });
  const [before, after] = annual;
  const baseChange = comparison(before.rate, after.rate);
  const reviewChange = comparison(before.reviewRate, after.reviewRate);
  for (const r of records) {
    if (!r.screenPass || r.leaveOneOutRate === null || baseChange.change === null) continue;
    const newBefore = r.year === before.year ? r.leaveOneOutRate : before.rate;
    const newAfter = r.year === after.year ? r.leaveOneOutRate : after.rate;
    const changed = comparison(newBefore, newAfter);
    r.leaveOneOutTrendChange = changed.change;
    r.leaveOneOutTrendChangePct = changed.changePct;
    r.reversesTrend = changed.change * baseChange.change < 0;
  }
  return {years: selected, screen: {low, high}, annual, records,
    comparison: {baselineBefore: before.rate, baselineAfter: after.rate,
      baselineChange: baseChange.change, baselineChangePct: baseChange.changePct,
      reviewBefore: before.reviewRate, reviewAfter: after.reviewRate,
      reviewChange: reviewChange.change, reviewChangePct: reviewChange.changePct},
    reviewCandidates: records.filter(r => r.reversesTrend)};
}

/** Restore only inputs from a source-bound review. Stored results are never trusted. */
export function restoreReview(dataset, sourceHash, review) {
  if (!review || typeof review !== 'object' || Array.isArray(review) || review.schema_version !== '1.0') {
    fail('INVALID_REVIEW', 'Choose a review JSON exported by this audit tool.');
  }
  if (typeof sourceHash !== 'string' || !/^[a-f0-9]{64}$/.test(sourceHash)) {
    fail('UNBOUND_SOURCE', 'Load the original CSV in a browser context that supports SHA-256 before restoring a review.');
  }
  if (review.source?.sha256 !== sourceHash) {
    fail('SOURCE_MISMATCH', 'This review belongs to a different source file. Load the exact original CSV, then restore the review again.');
  }
  if (!Array.isArray(review.years) || review.years.length !== 2 || !review.years.every(Number.isSafeInteger) || review.years[0] >= review.years[1]) {
    fail('INVALID_REVIEW', 'The review must specify two chronological years.');
  }
  if (!review.screen || typeof review.screen !== 'object' || Array.isArray(review.screen) ||
      !Object.hasOwn(review.screen, 'low') || !Object.hasOwn(review.screen, 'high') ||
      !Number.isFinite(review.screen.low) || !Number.isFinite(review.screen.high) ||
      !Array.isArray(review.excluded_records) || review.excluded_records.length > DEFAULT_MAX_ROWS) {
    fail('INVALID_REVIEW', 'The review is missing its screen or record selections.');
  }
  const keys = review.excluded_records.map(row => row?.key);
  if (keys.some(key => typeof key !== 'string') || new Set(keys).size !== keys.length) {
    fail('INVALID_REVIEW', 'The review contains missing or duplicate record keys.');
  }
  if (typeof review.reviewer_note !== 'string' || review.reviewer_note.length > 4000) {
    fail('INVALID_REVIEW', 'The reviewer note must be text of at most 4,000 characters.');
  }
  const options = {years: [...review.years], low: review.screen.low, high: review.screen.high, excludedKeys: keys};
  const result = analyzeDataset(dataset, options);
  if (result.records.filter(row => row.excluded).length !== keys.length) {
    fail('INVALID_REVIEW', 'A selected record is outside the review periods or ratio screen.');
  }
  return {options, analysis: result, note: review.reviewer_note};
}
