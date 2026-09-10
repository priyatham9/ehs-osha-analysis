# ehs-osha-analysis

[![tests](https://github.com/priyatham9/ehs-osha-analysis/actions/workflows/tests.yml/badge.svg)](https://github.com/priyatham9/ehs-osha-analysis/actions/workflows/tests.yml)

A reproducible pipeline over the public OSHA Injury Tracking Application (ITA)
Form 300A establishment filings, 2016-2024. It downloads the real files, screens
them for internal plausibility, and quantifies what the implausible ones do to
the aggregate injury rates that the data are normally used to produce. It then
goes beyond the screen: count-model comparison on recordable-case distributions,
establishment-size effects, industry heterogeneity, and the year-over-year
stability of peer-group percentile bands.

Every empirical number below was computed by `scripts/run_analysis.py` from
files downloaded from osha.gov and is transcribed from `outputs/summary.json` or
`outputs/tables/*.csv`; none was carried over from another source or estimated.
The outputs are committed to the repository; regenerate with `make analysis` to update every figure and table. The regression
tests in `tests/test_regression_real_data.py` assert the headline values against
the data, and `tests/test_readme_consistency.py` parses the figures back out of
this file and fails if the prose and the generated tables disagree. That
includes the flag-prevalence, size-band and percentile-stability tables below,
which are checked row by row against their CSVs, with a further check that the
stability table omits no percentile the pipeline computes.

Runs on Python 3.9 with pandas and numpy. No SciPy, no matplotlib, no test
runner beyond stdlib `unittest`.

---

## Why this exists

An incident rate is a ratio:

```
TRIR = 200,000 x recordable cases / hours worked
```

The numerator is bounded by how many people work somewhere. The denominator is a
free-text number on a form that nothing validates. When rates are aggregated
across establishments the usual estimator is a ratio of sums, so a single filing
with an impossible hours value can dominate the denominator of an entire
industry, state or national figure while adding nothing to the numerator. The
aggregate is then biased towards zero, and it looks like good news.

This is not hypothetical. Across the pooled 2016-2024 filings, **one filing
holds 88.8% of all hours ever reported to the ITA** and contributes zero
recordable cases: establishment 90427 in reporting year 2019 declared 7 employees
and 16,831,620,723,179 hours worked. That is roughly 2.4 trillion hours per
employee, against a physical ceiling of 8,760.

## Headline results

Pooled across all nine reporting years, under the default screen
(120-4,500 hours per average employee per year):

| | |
|---|---|
| Filings after deduplication | 2,801,064 |
| Flagged implausible | 57,857 (2.07%) |
| Share of all reported hours they hold | 96.68% |
| Share of all reported cases they hold | 1.37% |
| Aggregate TRIR, unscreened | **0.134** |
| Aggregate TRIR, screened | **3.983** |
| Ratio | **29.7x** |

Per year (`outputs/tables/quality_by_year.csv`):

| Year | Filings | % flagged | % of hours flagged | TRIR unscreened | TRIR screened | Ratio |
|---|---|---|---|---|---|---|
| 2016 | 214,977 | 2.30 | 31.6 | 2.729 | 3.921 | 1.44x |
| 2017 | 259,757 | 1.66 | 35.2 | 2.634 | 3.998 | 1.52x |
| 2018 | 286,884 | 1.56 | 29.1 | 2.920 | 4.069 | 1.39x |
| 2019 | 290,475 | 1.60 | 99.6 | 0.016 | 4.018 | 249.3x |
| 2020 | 293,385 | 1.91 | 38.6 | 2.792 | 4.491 | 1.61x |
| 2021 | 315,936 | 2.60 | 46.1 | 2.385 | 4.368 | 1.83x |
| 2022 | 346,799 | 2.02 | 42.9 | 2.661 | 4.605 | 1.73x |
| 2023 | 394,231 | 2.34 | 56.7 | 1.380 | 3.147 | 2.28x |
| 2024 | 398,620 | 2.37 | 92.4 | 0.280 | 3.642 | 13.0x |

**The most important number in that table is the spread in the last column, not
any single entry.** The screened rate is stable (3.15-4.61 across nine years).
The unscreened rate is not (0.016-2.92), because it depends on whether that
year happened to contain an extreme filing. The size of the aggregate error is
therefore not a fixed multiplier that can be quoted once and reused. It is a
property of the tail of the hours distribution in whatever slice you took.

The screened aggregate is insensitive to where the bounds are drawn. Across a
25-cell grid of lower bounds (100-400 h) and upper bounds (3,500-6,000 h), the
screened aggregate TRIR stays within 3.963-3.993
(`outputs/tables/quality_sensitivity_grid.csv`). The flagged *share* is not
similarly stable - it runs from 1.79% to 4.49% across the same grid - but that
is the point rather than a weakness: the filings that move in and out of the
flagged set as the bounds shift carry almost none of the hours, so the
correction they make to the aggregate is nearly identical. The conclusion is
not an artefact of the threshold choice; the count of flagged filings is.

### Which flag does the work

| Flag | Filings | % of filings | % of all hours |
|---|---|---|---|
| hours per employee > 4,500 | 24,617 | 0.879 | **96.65** |
| hours per employee < 120 | 22,904 | 0.818 | 0.03 |
| employees missing or < 1 | 10,322 | 0.369 | ~0 |
| hours missing or <= 0 | 9,897 | 0.353 | ~0 |
| "no injuries" box contradicts case counts | 301 | 0.011 | ~0 |
| negative case count | 1 | ~0 | ~0 |

One flag carries the entire effect. The low-hours and missing-value flags matter
for establishment-level rates but are irrelevant to the aggregate.

### Zero-recordable filings are heterogeneity, not zero-inflation

Among plausible filings, 37.1% of all establishment-years report zero
recordables; for NAICS 325 (chemical manufacturing) it is 37.4%, rising from
34.1% in 2016 to 41.3% in 2024 (`zero_recordable_share` in
`outputs/summary.json`).
The obvious reading is that a zero-inflated model is required. Fitting the
models says otherwise.

Four intercept-only models with an exposure offset (Poisson, NB2, ZIP, ZINB)
were fitted by maximum likelihood and compared by AIC, BIC and
observed-versus-expected zeros. The industries are not hand-picked: the pipeline
takes the 30 largest NAICS 3-digit groups by establishment count in 2024, every
one with at least 500 establishments, covering 306,711 establishment-filings.
Selection depends only on group size, never on fit quality
(`outputs/tables/count_model_comparison.csv`,
`outputs/tables/count_model_selection_summary.csv`):

| Model | Industries best by AIC (of 30) |
|---|---|
| Poisson | 0 |
| ZIP | 0 |
| NB2 | 15 |
| ZINB | 15 |

Two things follow, and they point in opposite directions.

**Overdispersion is universal and not optional.** Poisson never wins, in any of
the 30 industries. The variance-to-mean ratio of recordable counts runs from 3.0
to 756, against the value of 1 that Poisson assumes. Neither is ZIP ever
selected: adding structural zeros to a Poisson does not rescue it, because the
problem is the spread of the whole distribution, not the zeros alone.

**Zero-inflation is optional and, where present, small.** In 14 of the 30
industries the ZINB zero-inflation parameter collapses to the boundary
(`pi` on the order of 1e-14) and NB2 wins outright on AIC. Where ZINB is
selected, `pi` ranges from 0.001 to 0.069 - a few percent of establishments at
most, not the 37-41% zero share that motivated fitting it. Examples:

Industries are named by their official NAICS 2022 subsector title
(`src/ehs_osha/naics.py`, extracted from the Census Bureau 2022 NAICS structure
file). The establishment-supplied `industry_description` field in the OSHA data
describes a *6-digit* industry, so the modal description inside a 3-digit group
is not that group's name; it is carried in the output tables as
`modal_establishment_industry_description` and is not used as a label.

| NAICS | Subsector | n | Best by AIC | ZINB pi | NB2 obs/exp zeros | var/mean |
|---|---|---|---|---|---|---|
| 238 | Specialty Trade Contractors | 21,951 | **NB2** | 2e-14 (collapses) | 0.96 | 9.9 |
| 445 | Food and Beverage Retailers | 20,872 | **NB2** | 2e-15 (collapses) | 0.89 | 6.9 |
| 332 | Fabricated Metal Product Manufacturing | 9,873 | **NB2** | 2e-15 (collapses) | 0.94 | 7.8 |
| 623 | Nursing and Residential Care Facilities | 20,494 | ZINB | 0.005 | 0.97 | 13.7 |
| 621 | Ambulatory Health Care Services | 12,670 | ZINB | 0.026 | 0.97 | 27.4 |
| 622 | Hospitals | 6,561 | ZINB | 0.027 | 1.22 | 155.2 |

So the high zero share is mostly what a single overdispersed process produces,
not evidence of a separate non-reporting population. NB2 frequently predicts
slightly *more* zeros than are observed (ratios below 1.0 above).

This matters practically. A figure of the form "roughly 38% of chemical plants
report zero recordables" - the prior repository's number, and 37.4% on this
panel - is often read as evidence of a distinct population of non-reporters. These fits do
not support that reading as the main story: once establishment-to-establishment
variation in the underlying rate is allowed for, most of the excess zeros are
accounted for. The residual zero-inflation that survives in half the industries under the
intercept-only fits is real but modest, and it is concentrated in health care
and services rather than manufacturing.

**Covariate adjustment shrinks it further.** Refitting the same four models
with a log-hours offset, establishment size-band dummies and NAICS 4-digit
fixed effects within each 3-digit group (`src/ehs_osha/count_models_covariates.py`,
`outputs/tables/count_model_covariates_summary.csv`, method and limits in
`docs/COUNT_MODELS.md`) leaves overdispersion intact in all 30 industries (NB2
beats Poisson at boundary-corrected p < 0.001 everywhere; NB2 alpha median 0.79,
minimum 0.16) but cuts the ZINB wins from 9 of 30 (converged ZINB wins at boundary p < 0.01 with covariates; 15 of 30 in the earlier intercept-only comparison) to 10 of 30, with the
ZINB-vs-NB2 boundary test below 0.01 in 9. Part of what looked like excess
zeros was mean heterogeneity across size bands and sub-industries. The
statement that survives both specifications is: overdispersion is universal across the 30 industry groups and survives covariate adjustment (NB2 beats Poisson at boundary-corrected p < 0.001 in 30 of 30 with size-band and NAICS-4 effects);
zero inflation beyond NB2 holds in a minority of industries.

This is a statement about distributional shape, not about reporting behaviour.
An overdispersed process and a mixture of compliant and non-compliant reporters
can generate similar count distributions; these data cannot separate them, and
nothing here should be read as evidence that under-reporting is absent. The
ZINB vs NB2 comparison uses a
boundary-corrected likelihood-ratio test (the null puts `pi = 0` on the edge of
the parameter space, so the reference distribution is a 50:50 mixture of a point
mass and chi-square(1), and the p-value is half the naive one). The Vuong test
is deliberately not used; it is not valid for this nested comparison.

### Establishment size

`outputs/tables/size_band_effects.csv`, plausible filings only:

| Size band | n | Zero share | Var/mean | Aggregate TRIR | Median site TRIR |
|---|---|---|---|---|---|
| 1-19 | 535,187 | 0.751 | 3.4 | 4.94 | 0.00 |
| 20-49 | 884,997 | 0.462 | 6.5 | 4.58 | 2.55 |
| 50-99 | 553,610 | 0.239 | 7.9 | 4.98 | 3.35 |
| 100-249 | 493,919 | 0.109 | 11.4 | 4.71 | 3.61 |
| 250-499 | 170,749 | 0.073 | 14.7 | 4.13 | 3.38 |
| 500-999 | 61,329 | 0.082 | 29.5 | 3.37 | 2.38 |
| 1000+ | 43,416 | 0.081 | 241.4 | 3.14 | 2.84 |

The zero share is almost entirely a sample-size artefact: a 10-person site has
little exposure, so zero is the modal outcome. The median establishment TRIR is
0.00 for the smallest band and 3.61 at 100-249 employees. Any benchmark that
compares a site against an industry median without conditioning on size is
comparing against a number driven by how big the other sites are. This is the
argument for the NAICS x size-band peer grouping rather than NAICS alone.

### Percentile bands move on their own

`outputs/tables/percentile_band_stability.csv`. Across eight adjacent year pairs
and roughly 440 matched NAICS-3 x size-band cells per pair:

Every percentile the pipeline computes is shown, not a selection:

| Percentile | Median Spearman rho between years | Median absolute relative change |
|---|---|---|
| p10 | 0.871 | 25.7% |
| p25 | 0.919 | 14.3% |
| p50 | 0.933 | 10.1% |
| p75 | 0.862 | 9.5% |
| p90 | 0.887 | 10.6% |
| p95 | 0.890 | 12.4% |

Peer-group ordering is highly reproducible year to year (rho ~0.86-0.93), and
95.7-98.5% of publishable cells persist between adjacent years
(`outputs/tables/peer_group_persistence.csv`). But the *level* moves: about 10%
a year in the middle of the distribution (p50-p90), and considerably more in the
lower tail, where a small denominator makes the percentile itself unstable
(14.3% at p25, 25.7% at p10). A site sitting exactly on last year's p75 would be
roughly a tenth of the way off this year's p75 without changing anything about
its own performance, and a site near p10 could move two and a half times that
far. Movement across a percentile band of that size is not evidence of
anything.

---

## What this does not show

- **It does not identify which number on a form is wrong.** A filing flagged
  "hours per employee too high" could have correct hours and a mistyped employee
  count, or could be reporting company-wide hours at a site. The screen finds
  filings whose numerator and denominator cannot both be right, which is the
  property that breaks a rate. It is not a fraud detector.
- **It says nothing about causes of injury.** These are annual summary counts.
  There is no case detail, no time of day, no hour of shift, no narrative. OSHA
  publishes Form 300/301 case-detail files separately, starting with the 2023/24
  collection cycle and covering a narrower establishment universe; this
  repository does not use them.
- **The ITA universe is not the US workforce.** Reporting is required from
  establishments with 250+ employees, and from those with 20-249 in listed
  higher-hazard industries (29 CFR 1904 Subpart E). It is a mandated
  administrative collection from a selected slice, not a probability sample. The
  screened aggregate of ~3.98 sits well above the BLS SOII private-industry
  total recordable rate of 2.3 per 100 FTE for 2024, which is what you would
  expect from a universe skewed towards larger establishments in higher-hazard
  industries. The two are not directly comparable and are not compared here.
  OSHA publishes its own ITA-versus-SOII comparison; read it before drawing any
  conclusion about the gap.
- **Zero recordables can mean an incident-free year or an unrecorded one.** The
  count models can measure how many zeros there are and whether they exceed what
  overdispersion predicts. They cannot tell those two causes apart, and nothing
  here attempts to.
- **The count models are intercept-only.** They estimate a rate, a dispersion
  and a zero-inflation probability within an industry-year. They contain no
  covariates and support no causal claim about anything.
- **No standard errors are reported for the model parameters.** Point estimates
  and information criteria only. Adding a numerical Hessian would be
  straightforward and has not been done.
- **Establishment identity across years is not verified.** Deduplication is
  within `(establishment_id, year_filing_for)`. Whether an `establishment_id`
  refers to the same physical site across all nine years has not been checked,
  so no true panel analysis is attempted.

---

## Relationship to ehs-benchmarks

The author's earlier repository, [ehs-benchmarks](https://github.com/priyatham9/ehs-benchmarks),
reports a different set of headline numbers. Both sets are panel-specific, and
neither repository said so until now.

| | ehs-benchmarks (older) | ehs-osha-analysis (this repo) |
|---|---|---|
| Panel | CY2023-2025 ITA files, 1.18M filings | CY2016-2024 ITA files, 2,801,064 filings |
| Screen | 100-4,000 hours per employee | 120-4,500 hours per employee |
| Aggregate TRIR, unscreened | 0.45 | 0.134 |
| Aggregate TRIR, screened | 3.41 | 3.983 |
| Ratio | 7.58x | 29.7x |

`src/ehs_osha/reconcile.py` recomputes the aggregate under the old panel
definition with this repository's loaders and writes
`outputs/tables/reconciliation_panels.csv`. The old panel as available here is
the CY2023 and CY2024 files (the partial CY2025 file is not part of the pinned
catalog and is not on disk), so the "old" row covers 792,851 filings rather
than 1.18M. On those files under the 100-4,000 screen:

| | Recomputed here | Published in ehs-benchmarks | Gap |
|---|---|---|---|
| Aggregate TRIR, unscreened | 0.473 | 0.45 | +5.1% |
| Aggregate TRIR, screened | 3.374 | 3.41 | -1.1% |
| Ratio | 7.14x | 7.58x | -5.8% |

The screened rate reproduces within about 1%. The unscreened rate and the
ratio do not reproduce within the 5% tolerance the script applies; the 5-6%
gaps are consistent with the missing partial CY2025 file and any differences
in the older TypeScript deduplication, but that has not been verified and the
gap is reported as a gap. The ratio on the old years is insensitive to the
screen bounds: across the four combinations of {100, 120} x {4,000, 4,500}
hours per employee it stays between 7.13x and 7.14x. The bounds do not explain
the difference between 7.58x and 29.7x; the years do.

Which figure to quote:

- For the CY2016-2024 pooled aggregate, quote **29.7x** (0.134 to 3.983), and
  say it is dominated by the 2019 file (249x on its own).
- For a recent-years figure comparable to ehs-benchmarks, quote **7.14x** (0.473
  to 3.374) from `reconciliation_panels.csv`, CY2023-2024, 100-4,000 screen.
- Do not quote either multiplier as a property of the ITA data in general. The
  per-year table above is the honest statement: every year moves, by 1.39x to
  249x.

## Relationship to the author's prior work

This extends [github.com/priyatham9/ehs-benchmarks](https://github.com/priyatham9/ehs-benchmarks),
which processed 1.18M OSHA establishment filings and reported that 2.24% of
filings failed a plausibility test while carrying 86.9% of reported hours,
giving an aggregate TRIR of 0.45 against a corrected 3.41, a 7.58x error.

**Those exact figures were not reproduced here, and the difference is
informative rather than a discrepancy to paper over.** This repository pools
2,801,064 filings across 2016-2024 with the screen and deduplication rule
documented below; the prior repository used a different and smaller subset. The
flagged share replicates closely (2.07% here against 2.24% there, and 1.56-2.60%
across individual years). The other three numbers do not, and could not: as the
year table above shows, the hours share held by flagged filings ranges from 29%
to 99.6% and the ratio from 1.39x to 249x depending purely on which years are
included. The closest this repository gets is the CY2023-2024 files under the
older 100-4,000 screen: 0.473 / 3.374 / 7.14x, detailed in the section above.

The finding that survives is the structural one, and it survives in every single
year: a small minority of filings is implausible, those filings hold a
disproportionate share of the denominator, and removing them raises the
aggregate rate substantially. The specific multiplier is not a constant and
should not be quoted as one. That is the correction this repository makes to the
earlier framing.

---

## Methodology

### Data

Nine OSHA ITA Form 300A files, CY2016 through CY2024, downloaded from
`https://www.osha.gov/itadata`. URLs, byte sizes and SHA-256 digests are pinned
in `src/ehs_osha/catalog.py`, verified on 2026-09-03. No API key is needed.
OSHA's CDN rejects a default urllib User-Agent with HTTP 403, so a browser-style
UA is sent; that is the only special handling.

The 2025 file is published but excluded by default: its collection window was
still open at publication, so its counts are not comparable to complete years.
`--include-partial` opts in.

**OSHA revises published files in place.** The 2023, 2024 and 2025 files already
carry `_v2` markers. The downloader records a SHA-256 for every retrieval in
`data/raw/manifest.json`, fails hard on a byte-count mismatch, and warns loudly
on a digest mismatch. Results computed from a republished file are not
comparable to the numbers in this README.

### Fail-loud policy

`scripts/download_data.py` exits non-zero if any file cannot be obtained intact,
and leaves no partial file behind. `scripts/run_analysis.py` calls
`require_local_files()` before doing anything and refuses to start if a file is
missing, naming the command to run. There is no code path in which missing real
data is replaced by generated data. This is covered by tests
(`test_catalog_and_download.py`) that run a local HTTP server and check the 404,
truncation and cleanup paths.

### Harmonisation

Column *names* are stable across 2016-2024; three other things are not, and each
is a silent-wrong-answer trap:

1. **Column order** differs between the 2016-2022 and 2023+ files, and
   `naics_year` appears only from 2023. Reads are by name.
2. **Encoding.** `ITA Data CY 2018.csv` contains bytes that are not valid UTF-8
   (0x92, a Windows-1252 right single quote). Strict UTF-8 raises; the loader
   retries cp1252, then falls back to replacement and warns. A regression test
   asserts this file still needs the fallback.
3. **The `size` field is not comparable across years.** OSHA's summary data
   dictionary (April 2024) documents the codes - 1 = <20 employees, 2 = 20-249,
   21 = 20-99, 22 = 100-249, 3 = 250+ - and states that "code 2 was split to 21
   and 22 with the collection of 2023 data". The files agree: among plausible
   filings code 2 falls from 244,231 in 2022 to 41,343 in 2024 while 21 and 22
   rise to 224,266 combined, and median employee counts are 52 for code 2, 39
   for code 21 and 138 for code 22. The codes are therefore documented, but a
   pooled panel still mixes one 20-249 band with two narrower bands covering
   the same people, so a raw `size` value does not mean the same thing in 2019
   as in 2024. `size` is carried through and never used for grouping; **size
   bands are derived from `annual_average_employees`** so they mean the same
   thing in every year.

Amended filings appear as extra rows carrying a `change_reason`. 4,703 duplicate
`(establishment_id, year_filing_for)` pairs are resolved by keeping the largest
`id`, which is the latest submission: 2,805,767 raw rows become 2,801,064.

Recordable cases are the sum of Form 300A columns G+H+I+J (deaths, days away,
job transfer or restriction, other recordable), which partitions cases exactly
once. `total_injuries` and the illness columns are a *different* partition of the
same cases and are deliberately excluded from the sum; a test asserts this.

### The plausibility screen

Six independent flags, in `src/ehs_osha/quality.py`. A filing is implausible if
any of the first five fires:

- `hours_missing` - hours missing, non-finite or <= 0
- `employees_missing` - employees missing, non-finite or < 1
- `negative_counts` - any case component negative
- `hours_per_employee_high` - above 4,500 (about 86 h/week every week; the
  physical ceiling is 8,760)
- `hours_per_employee_low` - below 120 (about three full-time weeks)
- `no_injury_contradiction` - the self-declared checkbox contradicts the case
  counts. **Reported but excluded from the implausible verdict by default**,
  because it is a real defect that does not corrupt the denominator. OSHA's
  summary data dictionary defines the field as 1 = the establishment had
  injuries or illnesses, 2 = it did not; on that coding the flag fires on 301
  of 2.8M filings, so the checkbox and the counts agree essentially always.

Bounds are configuration, not truth, which is why `sensitivity_grid()` re-runs
the entire comparison across a grid and the result is reported.

### Count models

Four intercept-only models with an exposure offset, exposure measured in
200,000-hour units so the rate parameter is on the TRIR scale.

Industries are chosen by size, not by hand: the 30 largest NAICS 3-digit groups
with at least 500 establishments in the model year. The rule reads only group
sizes, never outcome values or fit statistics, so it cannot select industries
that happen to favour a particular model. Pass `--model-naics3` to override it
with an explicit list, and `--model-top-k` to change the count. Groups larger
than `--model-max-n` (default 60,000) are subsampled with a fixed seed and the
realised `n` is recorded in the output table.

Poisson has a closed-form MLE; NB2, ZIP and ZINB are fitted by multi-start
Nelder-Mead on an
unconstrained parameterisation (log for positive quantities, logit for the
inflation probability), implemented in `src/ehs_osha/optimize.py` because SciPy
is not available. `log Gamma` comes from `math.lgamma`, evaluated on unique
counts only and broadcast. The chi-square tail is computed from the regularised
incomplete gamma function (series plus Lentz continued fraction).

Estimator correctness is tested by generating data from known parameters and
checking recovery: ZINB recovers mu, alpha and pi to within the tolerances in
`tests/test_models_and_stats.py`, NB2 converges to Poisson as alpha goes to
zero, and the chi-square tail is checked against known critical values.

### Peer groups and stability

Peer groups are NAICS 3-digit x size band. Cells with fewer than 30
establishments carrying a computable rate are marked not publishable. The two
coverage numbers in `outputs/summary.json` are computed over different cell
definitions and should be quoted together: on per-year NAICS-3 x size cells the
rule excludes 35.1% of cells and 0.76% of establishments; pooling across years
gives larger cells, and the rule then excludes 28.5% of cells and 0.06% of
establishments. Stability is measured
between adjacent years over cells publishable in both, using Spearman rank
correlation (implemented directly, average ranks for ties) plus median absolute
and median absolute relative change. Cell persistence is reported alongside,
because a benchmark that loses cells between years is unusable regardless of how
stable the survivors look.

---

## Layout

```
src/ehs_osha/
  catalog.py       pinned public URLs, sizes and SHA-256 digests
  download.py      key-free downloader; fails loudly, records provenance
  schema.py        canonical columns and the three documented schema drifts
  load.py          reading, harmonisation, dedup, derived fields
  naics.py         official NAICS 2022 subsector titles (from Census)
  quality.py       plausibility screen, aggregate comparison, sensitivity grid
  peers.py         size bands, NAICS x size peer groups, percentile tables
  optimize.py      Nelder-Mead and golden-section (no SciPy)
  countmodels.py   Poisson / NB2 / ZIP / ZINB MLE, boundary-corrected LRT
  stability.py     Spearman rho, year-pair band stability, cell persistence
  svgplot.py       minimal SVG figure writer (no matplotlib)
  pipeline.py      orchestration; writes every table and figure
scripts/
  download_data.py
  run_analysis.py
synthetic/
  generate_fixture.py   SYNTHETIC data generator, for tests only
tests/                  175 tests, stdlib unittest
outputs/
  tables/               15 CSVs, all script-generated
  figures/              6 SVGs, all script-generated
  summary.json          config, provenance and headline numbers for the run
```

## Running it

```bash
python scripts/download_data.py --list     # show the catalog and URLs
python scripts/download_data.py            # ~170 MB into data/raw
python scripts/run_analysis.py             # ~90 s, writes outputs/
cd tests && python -m unittest discover -s . -p "test_*.py"
```

Or `make data`, `make analysis`, `make test`.

The real-data regression tests skip automatically when `data/raw` is not
populated, so the suite passes on a fresh clone without a network. Every other
test runs offline, including the HTTP tests, which use a local server.

## Synthetic fixture

`synthetic/` contains a generator that produces clearly-labelled fake filings
with known ground-truth parameters. It exists so the pipeline can be exercised
without a network and so the estimators can be checked against an answer known
by construction. Every generated CSV has a sibling `.HEADER.txt` declaring it
synthetic, and `GROUND_TRUTH.json` records the parameters. See
`synthetic/README.md`.

**No number produced from the fixture appears anywhere in this README, and none
should be cited.** Fixture runs write to a separate output directory.

## Data provenance and licensing

Source: US Department of Labor, Occupational Safety and Health Administration,
Injury Tracking Application establishment-specific injury and illness data,
`https://www.osha.gov/itadata`. Field definitions are in OSHA's summary data
dictionary and ITA data users guide, both linked from
`src/ehs_osha/catalog.py`.

Works of the US federal government are generally not subject to copyright under
17 U.S.C. 105. That is not a blanket grant: agency logos and trademarks are
restricted, third-party material hosted on federal sites may be separately
copyrighted, and protection can attach outside the United States. The raw files
are not redistributed in this repository; `scripts/download_data.py` fetches them
from OSHA.

The code in this repository is MIT licensed. See `LICENSE`.


## Regenerating everything

A single command regenerates every table, figure and `summary.json` block, including the
metrics, covariate count-model and reconciliation stages:

```bash
PYTHONPATH=src python3 scripts/run_analysis.py
```

That runs eight stages in order: load, quality screen, peer percentiles, count models
(intercept-only), stability, metrics, covariate-adjusted count models, reconciliation. The
covariate stage runs after the intercept-only one and rewrites `fig04_count_model_fit.svg`
last, so the covariate-adjusted figure - not the intercept-only one - is what ends up on disk;
`count_model_selection_summary.csv` keeps the intercept-only comparison for the record, but the
covariate count models are the ones to quote.

The metrics stage (`ehs_osha.metrics`) is the slow one, roughly 3 minutes on the full data,
because it reloads and rescreens the raw files. Each of the three added stages can be skipped
independently when iterating on the earlier ones:

```bash
PYTHONPATH=src python3 scripts/run_analysis.py --skip-metrics
PYTHONPATH=src python3 scripts/run_analysis.py --skip-count-models-covariates
PYTHONPATH=src python3 scripts/run_analysis.py --skip-reconcile
```

After any pipeline change, also regenerate the published site:

```bash
python3 ../../tools/build_sites.py                          # regenerate docs/index.html
```
