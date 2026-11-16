import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {AuditError, parseCsv, analyzeDataset, restoreReview} from '../../docs/denominator-model.mjs';

const header = 'year,employees,hours,cases';
const csv = (...rows) => `${header}\n${rows.join('\n')}\n`;
const close = (actual, expected, tolerance = 1e-11) =>
  assert.ok(Math.abs(actual - expected) <= tolerance * Math.max(1, Math.abs(expected)), `${actual} != ${expected}`);
const errorCode = code => error => error instanceof AuditError && error.code === code;

test('BOM, CRLF, quoted commas, quotes and embedded newlines preserve records and identifiers', () => {
  const data = parseCsv('\ufeffyear,employees,hours,cases,filing_id\r\n2023,1,2000,0,"A, ""quoted""\r\nsite"\r\n2024,2,4000,1,B\r\n');
  assert.equal(data.records.length, 2);
  assert.equal(data.records[0].filingId, 'A, "quoted"\r\nsite');
  assert.equal(data.records[1].sourceRow, 4);
  assert.deepEqual(data.records.map(r => r.key), ['row:2', 'row:3']);
});

test('header names are normalized; extra columns do not enter the analysis', () => {
  const data = parseCsv(' Year ,EMPLOYEES,hours,cases,notes\n2023,1,2000,0,unused\n2024,1,2000,1,unused');
  assert.equal(data.records[0].notes, undefined);
  assert.deepEqual(data.years, [2023, 2024]);
});

test('malformed CSV never silently drops rows', () => {
  for (const text of [csv('2023,1,2000,0,extra'), csv('2023,1,2000'), `${header}\n\n2023,1,2000,0`]) {
    assert.throws(() => parseCsv(text), errorCode('COLUMN_COUNT'));
  }
  for (const text of [`${header}\n"2023,1,2000,0`, `${header}\n20"23,1,2000,0`, `${header}\n"2023"x,1,2000,0`]) {
    assert.throws(() => parseCsv(text), errorCode('MALFORMED_CSV'));
  }
});

test('missing/duplicate/empty headers and empty input have displayable errors', () => {
  assert.throws(() => parseCsv(''), errorCode('EMPTY_FILE'));
  assert.throws(() => parseCsv(header), errorCode('NO_RECORDS'));
  assert.throws(() => parseCsv('year,hours,cases\n2023,2000,0'), errorCode('MISSING_HEADER'));
  assert.throws(() => parseCsv('year,year,hours,cases\n2023,1,2000,0'), errorCode('DUPLICATE_HEADER'));
  assert.throws(() => parseCsv('year,,hours,cases\n2023,1,2000,0'), errorCode('INVALID_HEADER'));
});

test('byte limits count UTF8 bytes and row limits reject excess records', () => {
  const text = 'year,employees,hours,cases,note\n2023,1,2000,0,éééé';
  assert.throws(() => parseCsv(text, {maxBytes: text.length}), errorCode('FILE_TOO_LARGE'));
  assert.throws(() => parseCsv(csv('2023,1,2000,0', '2024,1,2000,0'), {maxRows: 1}), errorCode('TOO_MANY_ROWS'));
  assert.throws(() => parseCsv(csv('2023,1,2000,0'), {maxRows: 50001}), errorCode('INVALID_LIMIT'));
});

test('zero cases and fractional positive headcount/hours are valid', () => {
  const data = parseCsv(csv('2023,.5,1000.25,0', '2024,1.25,2500.5,2.0'));
  assert.equal(data.records[0].cases, 0);
  assert.equal(data.records[1].cases, 2);
  assert.equal(analyzeDataset(data).annual[0].nAccepted, 1);
});

test('invalid, negative, nonfinite and unsafe numerics fail the entire dataset', () => {
  for (const value of ['', ' ', 'NaN', 'Infinity', '0x10', '1,000']) {
    assert.throws(() => parseCsv(csv(`2023,1,2000,"${value}"`)), errorCode('INVALID_NUMBER'));
  }
  for (const value of ['1e309', '9007199254740992', '9007199254740991.1', '9.0071992547409911e15']) {
    assert.throws(() => parseCsv(csv(`2023,1,${value},0`)), errorCode('UNSAFE_NUMBER'));
  }
  for (const row of ['2023,0,2000,0', '2023,-1,2000,0', '2023,1,0,0', '2023,1,2000,-1', '0,1,2000,0']) {
    assert.throws(() => parseCsv(csv(row)), errorCode('OUT_OF_RANGE'));
  }
});

test('mathematically fractional case counts cannot round silently to integers', () => {
  for (const value of ['.5', '1.00000000000000001', '1e-999', '123e-2']) {
    assert.throws(() => parseCsv(csv(`2023,1,2000,${value}`)), errorCode('NONINTEGER'));
  }
  for (const value of ['1.0', '100e-2', '0e-999', '2e2']) {
    assert.ok(Number.isSafeInteger(parseCsv(csv(`2023,1,2000,${value}`)).records[0].cases));
  }
});

test('provided IDs are unique within year; internal keys never depend on IDs', () => {
  const h = `${header},filing_id\n`;
  assert.throws(() => parseCsv(h + '2023,1,2000,0,A\n2023,1,2000,1,A'), errorCode('DUPLICATE_ID'));
  const data = parseCsv(h + '2023,1,2000,0,row:3\n2024,1,2000,1,row:3\n2024,1,2000,1,');
  assert.equal(new Set(data.records.map(r => r.key)).size, 3);
  assert.equal(data.records[2].filingId, '');
});

test('screen is inclusive, editable, and rejected rows stay visible', () => {
  const data = parseCsv(csv('2023,1,120,1', '2023,1,4500,0', '2023,1,119.9,0', '2024,1,4500.1,1'));
  const out = analyzeDataset(data);
  assert.deepEqual(out.annual.map(r => [r.nAccepted, r.nRejected]), [[2, 1], [0, 1]]);
  assert.equal(out.records.length, 4);
  assert.equal(out.annual[1].rate, null);
  assert.equal(analyzeDataset(data, {low: 0, high: 10000}).annual[1].nAccepted, 1);
  for (const bounds of [{low: -1, high: 10}, {low: 10, high: 10}, {low: 0, high: Infinity}]) {
    assert.throws(() => analyzeDataset(data, bounds), errorCode('INVALID_SCREEN'));
  }
});

test('year choice is chronological and invalid years are rejected', () => {
  const data = parseCsv(csv('2022,1,2000,1', '2023,1,2000,1', '2024,1,2000,1'));
  assert.deepEqual(analyzeDataset(data).years, [2023, 2024]);
  assert.deepEqual(analyzeDataset(data, {years: ['2024', '2022']}).years, [2022, 2024]);
  for (const years of [[2023], [2023, 2023], [2023, 2025]]) {
    assert.throws(() => analyzeDataset(data, {years}), errorCode('INVALID_YEARS'));
  }
});

test('leave-one-out values equal independent direct removals in both periods', () => {
  const data = parseCsv(csv('2023,100,200000,1', '2023,200,400000,20', '2024,100,200000,3', '2024,200,400000,8'));
  const out = analyzeDataset(data);
  for (const row of out.records) {
    const others = data.records.filter(r => r.year === row.year && r.key !== row.key);
    const expected = 200000 * others.reduce((s, r) => s + r.cases, 0) / others.reduce((s, r) => s + r.hours, 0);
    close(row.leaveOneOutRate, expected);
    close(row.leaveOneOutChange, expected - out.annual.find(r => r.year === row.year).rate);
    const before = row.year === 2023 ? expected : out.comparison.baselineBefore;
    const after = row.year === 2024 ? expected : out.comparison.baselineAfter;
    close(row.leaveOneOutTrendChange, after - before);
    close(row.leaveOneOutTrendChangePct, 100 * (after / before - 1));
  }
  for (const year of out.years) {
    const ranks = out.records.filter(r => r.year === year).sort((a, b) => a.influenceRank - b.influenceRank);
    assert.ok(ranks[0].absoluteInfluence >= ranks[1].absoluteInfluence);
  }
});

test('dominant-row cancellation does not erase the remaining exposure', () => {
  const data = parseCsv(csv('2023,1e12,1e15,0', '2023,.00001,.01,1', '2024,1,1000,1', '2024,1,1000,1'));
  const out = analyzeDataset(data);
  close(out.records[0].leaveOneOutRate, 200000 / .01);
  assert.ok(Number.isFinite(out.records[0].leaveOneOutRate));
});

test('manual exclusions remove cases and hours and keep baseline influence fixed', () => {
  const data = parseCsv(csv('2023,100,200000,1', '2023,200,400000,20', '2024,100,200000,3', '2024,200,400000,8'));
  const unchanged = JSON.stringify(data);
  const baseline = analyzeDataset(data);
  const out = analyzeDataset(data, {excludedKeys: [data.records[0].key]});
  assert.equal(out.annual[0].nExcluded, 1);
  assert.equal(out.annual[0].reviewHours, 400000);
  assert.equal(out.annual[0].reviewCases, 20);
  assert.equal(out.annual[0].reviewRate, 10);
  close(out.records[0].leaveOneOutChange, baseline.records[0].leaveOneOutChange);
  assert.equal(JSON.stringify(data), unchanged);
  assert.equal(out.annual[0].hours, 600000);
});

test('unknown review keys fail; known out-of-period or rejected keys do not affect totals', () => {
  const data = parseCsv(csv('2022,1,2000,1', '2023,1,2,1', '2023,1,2000,1', '2024,1,2000,1'));
  assert.throws(() => analyzeDataset(data, {excludedKeys: ['not-a-key']}), errorCode('UNKNOWN_KEY'));
  const out = analyzeDataset(data, {excludedKeys: [data.records[0].key, data.records[1].key]});
  assert.equal(out.annual.reduce((s, r) => s + r.nExcluded, 0), 0);
});

test('all-excluded years and sole accepted rows produce null rates, never Infinity', () => {
  const data = parseCsv(csv('2023,1,2000,1', '2024,1,2000,1'));
  const out = analyzeDataset(data, {excludedKeys: data.records.map(r => r.key)});
  assert.equal(out.comparison.reviewChange, null);
  assert.equal(out.comparison.reviewChangePct, null);
  assert.ok(out.annual.every(r => r.reviewRate === null && r.reviewN === 0));
  assert.ok(out.records.every(r => r.leaveOneOutRate === null && !r.reversesTrend));
});

test('zero baseline case counts preserve absolute changes and suppress undefined percentages', () => {
  const out = analyzeDataset(parseCsv(csv('2023,1,2000,0', '2023,1,2000,0', '2024,1,2000,1', '2024,1,2000,1')));
  assert.equal(out.comparison.baselineChange, 100);
  assert.equal(out.comparison.baselineChangePct, null);
  assert.ok(out.records.filter(r => r.year === 2024).every(r => r.leaveOneOutTrendChangePct === null));
});

test('unsafe aggregates and rates throw bounded displayable errors', () => {
  const unsafe = parseCsv(csv('2023,1e12,5e15,0', '2023,1e12,5e15,0', '2024,1,2000,0'));
  assert.throws(() => analyzeDataset(unsafe, {high: 10000}), errorCode('UNSAFE_AGGREGATE'));
  const overflow = parseCsv(csv('2023,1e-303,1e-300,1e15', '2024,1,2000,0'));
  assert.throws(() => analyzeDataset(overflow), errorCode('UNSAFE_RATE'));
});

test('published real totals reproduce the single-row reversal in an arithmetic-only fixture', () => {
  const saved = JSON.parse(fs.readFileSync(new URL('../../docs/decision-audit-data.json', import.meta.url), 'utf8'));
  const a = saved.annual_rates.find(r => r.year === 2023), b = saved.annual_rates.find(r => r.year === 2024);
  const top = saved.suspect_filings.find(r => r.filing_id === 2156121);
  // The second and third rows aggregate the remaining real totals solely to
  // test the arithmetic. They are not individual filings or product examples.
  const data = parseCsv(csv(`2023,${top.employees},${top.hours},${top.cases}`,
    `2023,${(a.hours-top.hours)/2000},${a.hours-top.hours},${a.cases-top.cases}`,
    `2024,${b.hours/2000},${b.hours},${b.cases}`));
  const out = analyzeDataset(data);
  close(out.comparison.baselineChangePct, saved.headline.reported_2023_2024_change_pct);
  assert.equal(out.records[0].reversesTrend, true);
  assert.ok(out.records[0].leaveOneOutTrendChangePct < 0);
});

test('50,000-record limit is usable and larger input fails explicitly', () => {
  const lines = Array.from({length: 50000}, (_, i) => `${2023+i%2},1,2000,${i%3}`);
  const data = parseCsv(`${header}\n${lines.join('\n')}`);
  const out = analyzeDataset(data);
  assert.equal(out.records.length, 50000);
  assert.deepEqual(out.annual.map(r => r.nAccepted), [25000, 25000]);
  assert.throws(() => parseCsv(`${header}\n${lines.join('\n')}\n2024,1,2000,0`), errorCode('TOO_MANY_ROWS'));
});

test('oversized identifiers stop before rendering or exporting the dataset', () => {
  assert.throws(() => parseCsv('year,employees,hours,cases,filing_id\n2023,1,2000,0,' + 'x'.repeat(513)), e => e.code === 'IDENTIFIER_TOO_LONG');
});


test('source-bound restoration recomputes results and ignores supplied totals', () => {
  const data = parseCsv('year,employees,hours,cases\n2023,100,200000,4\n2023,10000,20000000,1\n2024,100,200000,3');
  const digest = 'a'.repeat(64);
  const review = {schema_version:'1.0',source:{sha256:digest},years:[2023,2024],screen:{low:120,high:4500},excluded_records:[{key:'row:3',hours:1}],reviewer_note:'<b>verify</b>',comparison:{reviewChangePct:99999}};
  const restored = restoreReview(data,digest,review);
  assert.equal(restored.analysis.comparison.reviewChangePct,-25);
  assert.equal(restored.analysis.annual[0].reviewHours,200000);
  assert.equal(restored.note,'<b>verify</b>');
  assert.deepEqual(restored.options.excludedKeys,['row:3']);
  assert.throws(()=>restoreReview(data,'b'.repeat(64),review),e=>e.code==='SOURCE_MISMATCH');
  assert.throws(()=>restoreReview(data,null,review),e=>e.code==='UNBOUND_SOURCE');
});

test('restored reviews reject invalid scope, duplicate keys and oversized notes', () => {
  const data=parseCsv('year,employees,hours,cases\n2023,100,200000,4\n2024,100,200000,3\n2025,100,200000,2');
  const digest='c'.repeat(64);
  const review={schema_version:'1.0',source:{sha256:digest},years:[2023,2024],screen:{low:120,high:4500},excluded_records:[],reviewer_note:''};
  for(const patch of [{screen:{}},{screen:[]},{screen:{low:120}},{screen:{high:4500}},{screen:{low:'120',high:4500}},{schema_version:'9'},{years:[2024,2023]},{years:['2023',2024]},{excluded_records:[{key:'row:2'},{key:'row:2'}]},{excluded_records:[{key:'row:4'}]},{reviewer_note:'x'.repeat(4001)}]){
    assert.throws(()=>restoreReview(data,digest,{...review,...patch}),AuditError);
  }
});
