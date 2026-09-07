# Secondary rates: DART, LTIR and severity

Source of every number on this page: `outputs/tables/metrics_by_year.csv` and
`outputs/tables/metrics_pooled.csv`, written by `python3 -m ehs_osha.metrics`
(module `src/ehs_osha/metrics.py`, tests in `tests/test_metrics.py`). The same
block is stored under `metrics` in `outputs/summary.json`.

## Definitions

All rates are per 200,000 hours worked (100 full-time workers at 2,000 hours).
Letters are Form 300A columns.

| rate | formula | 300A fields |
|---|---|---|
| TRIR | 200000 x (G + H + I + J) / hours | deaths, days-away cases, restricted/transfer cases, other recordable cases |
| DART | 200000 x (H + I) / hours | days-away cases + restricted/transfer cases |
| LTIR | 200000 x H / hours | days-away cases (lost-time cases) |
| Severity | 200000 x (K + L) / hours | days away + days restricted/transferred |

Each aggregate is a ratio of sums (total numerator over total hours across
filings), not a mean of establishment rates. The by-year TRIR here matches
`quality_by_year.csv` exactly, which is the check that both modules apply the
same screen.

## Screened-panel caveat

"Screened" means filings that pass the plausibility screen in
`ehs_osha.quality` (hours per employee within 120 to 4,500, positive hours,
at least one employee, non-negative counts). "Unscreened" uses every filing.
The screen acts on hours and employee counts only. It does not screen the
day-count fields (K, L), so the severity rate remains exposed to mistyped day
totals that the hours screen cannot see; the year-to-year swings in screened
severity (for example 2022 and 2024 against neighbouring years) should be read
as a reason to build a day-count screen, not as a finding about injuries.
Because the four rates share the same denominator, the screened-to-unscreened
ratio is nearly identical across them (about 29.7 pooled); the screen is a
denominator story.

## Numbers

| year | filings in | TRIR | DART | LTIR | severity | TRIR unscr. | DART unscr. | LTIR unscr. | severity unscr. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2016 | 210,031 | 3.92 | 2.33 | 1.16 | 99.9 | 2.73 | 1.62 | 0.81 | 69.3 |
| 2017 | 255,434 | 4.00 | 2.46 | 1.25 | 122.5 | 2.63 | 1.62 | 0.82 | 80.7 |
| 2018 | 282,417 | 4.07 | 2.50 | 1.26 | 118.1 | 2.92 | 1.79 | 0.91 | 84.4 |
| 2019 | 285,825 | 4.02 | 2.49 | 1.26 | 119.3 | 0.02 | 0.01 | 0.01 | 0.5 |
| 2020 | 287,792 | 4.49 | 3.12 | 2.03 | 131.9 | 2.79 | 1.94 | 1.27 | 81.6 |
| 2021 | 307,719 | 4.37 | 2.96 | 1.82 | 127.0 | 2.39 | 1.62 | 0.99 | 69.1 |
| 2022 | 339,806 | 4.60 | 3.21 | 2.07 | 331.7 | 2.66 | 1.85 | 1.20 | 189.9 |
| 2023 | 384,996 | 3.15 | 2.03 | 1.15 | 87.4 | 1.38 | 0.89 | 0.50 | 38.2 |
| 2024 | 389,187 | 3.64 | 2.33 | 1.28 | 242.1 | 0.28 | 0.18 | 0.10 | 18.5 |
| pooled_all_years | 2,743,207 | 3.98 | 2.58 | 1.47 | 155.6 | 0.13 | 0.09 | 0.05 | 5.2 |

"filings in" is the count of filings passing the screen in that year.

## BLS comparison (not done)

The intended figure `fig07_bls_comparison.svg` (screened and unscreened
aggregate TRIR against the BLS SOII published private-industry total
recordable case rate) was not produced. From this machine the BLS API answers,
but the BLS pages and the `is.series` catalog needed to confirm the exact
series ID return HTTP 403, so no series could be verified and no published
rate was typed in from memory. The fetcher is in `src/ehs_osha/bls.py` (run
with a confirmed `--series-id`); the attempt is logged in
`data/bls/PROVENANCE.txt` and under `bls` in `outputs/summary.json`.

When the comparison is made, exact agreement should not be expected: the ITA
panel covers establishments required to submit electronically (larger and in
higher-hazard industries), while SOII is a sampled survey of private industry
as a whole. A screened ITA aggregate above the SOII rate would be consistent
with that coverage difference; a screened aggregate far below it would point
to a residual denominator problem.
