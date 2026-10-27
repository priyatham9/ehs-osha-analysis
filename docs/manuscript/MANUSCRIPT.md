# Implausible hours worked bias aggregate injury rates in OSHA establishment filings: screening, count models, stability and a pre-registered forecast

**Author:** Priyatham Chimmani (independent; no institutional affiliation is recorded in the repository)

**Status: UNSUBMITTED DRAFT.** This manuscript has not been submitted to any journal, preprint server or other venue, has not been peer reviewed, and must not be cited as published work. Draft date: 2026-10-27. Every number in it is copied from a committed table or document of this repository; Appendix A maps each number to its source file and `tests/test_manuscript.py` re-checks every mapping. References that could not be verified are left out and listed in `docs/manuscript/OPEN_ITEMS.md`.

## Abstract

**Background.** Employers covered by the US Occupational Safety and Health Administration (OSHA) Injury Tracking Application (ITA) report annual hours worked as an unvalidated field, while the usual aggregate injury rate, the total recordable incident rate (TRIR), is a ratio of sums in which hours form the denominator. **Methods.** We pool 2,801,064 deduplicated Form 300A establishment filings for reporting years 2016 to 2024, apply a six-flag plausibility screen with default bounds of 120 and 4,500 hours per average employee, and compare screened and unscreened aggregate TRIR. We fit Poisson, negative binomial (NB2), zero-inflated Poisson and zero-inflated negative binomial (ZINB) models with an exposure offset to the 30 largest three-digit industry groups, measure year-to-year stability of peer-group percentiles, audit the `establishment_id` linkage, and test robustness to the screen bounds, to leaving each year out, and to dropping the filings with the most hours. **Results.** The screen flags 57,857 filings (2.07%), which hold 96.68% of all reported hours but 1.37% of reported cases. Screening raises the pooled aggregate TRIR from 0.134 to 3.983, a factor of 29.7, but the factor is not a constant: by year it runs from 1.39 to 249.3. Across a grid of 25 bound pairs the screened TRIR stays between 3.963 and 3.993 while the flagged share moves from 1.79% to 4.49%. Overdispersion is present in all 30 industries, including after adjusting for establishment size and four-digit industry; zero inflation beyond NB2 is supported in 9 of 30. **Conclusions.** Aggregate rates from unscreened self-reported hours are dominated by a handful of filings, whereas the screened rate is insensitive to the exact bounds and to any single year. We register predictions for the 2025 release before those data exist in the repository.

**Keywords:** occupational injury; OSHA Form 300A; data quality; incident rate; count models; reproducibility; pre-registration.

## 1. Introduction

An incident rate is a ratio. The total recordable incident rate is 200,000 times recordable cases divided by hours worked. The numerator is bounded by the number of people employed, whereas the denominator is a free-text figure on a form. When rates are aggregated over establishments by the common ratio-of-sums estimator, a single filing with an impossible hours value can dominate the denominator of an industry, state or national figure while contributing no cases, which biases the aggregate toward zero and makes it look like good news.

This is not hypothetical in the public ITA data. Across the pooled filings, one filing holds 88.8% of all hours ever reported, and it declares 7 employees and 16,831,620,723,179 hours worked, which is about 2.4 trillion hours per employee against a physical ceiling of 8,760 hours in a year.

This paper integrates the methods and committed results of one reproducible pipeline into a single account. Its contributions are: (i) a transparent plausibility screen and a measurement of the bias that implausible hours introduce into aggregate rates; (ii) an honest statement of how unstable that bias is across years; (iii) count-model evidence on overdispersion and zero inflation, with and without covariates; (iv) peer-group percentile stability; (v) an audit of what the establishment identifier can and cannot support; (vi) robustness of the headline to the screen bounds and to each year; and (vii) a dated pre-registration of predictions for the next data release. The paper makes no causal claim, does not identify which entry on a form is wrong, and does not represent the US workforce.

## 2. Data

**Source.** The data are nine OSHA ITA Form 300A establishment-level files for reporting years 2016 through 2024, downloaded from the OSHA ITA data page (`https://www.osha.gov/itadata`; this host was not reachable from the sandbox in which this draft was prepared, so the download itself is documented but was not re-run here). The files hold 2,805,767 raw rows. Amended submissions appear as extra rows; keeping one row per establishment and year (the one with the largest submission `id`) removes 4,703 duplicates and leaves 2,801,064 filings. These cover 1,238,236 distinct `establishment_id` values. A partial file for a further year is excluded because its collection window was still open.

**Harmonisation.** Column order, text encoding and the OSHA size code differ across years. Reads are by column name, one file needs a legacy Windows text-encoding fallback, and because the OSHA size code was split during the 2023 collection, size bands are rebuilt from the average employee count so that they mean the same thing in every year. Recordable cases are the sum of the four Form 300A case columns (deaths, days away, job transfer or restriction, other recordable), which partitions cases exactly once.

**Datasheet.** The repository's datasheet (`DATASHEET.md`, following the datasheet-for-datasets structure) records the composition, collection process, known errors and uses to avoid, and marks as unknown anything the repository cannot document, including whether the files contain every establishment that was required to file. The raw files are not redistributed; only aggregates are committed, with one 50-row table of the largest implausible filings keyed by `establishment_id`.

## 3. Methods

### 3.1 Plausibility screen

A filing is flagged implausible if any of five conditions holds: hours missing or non-positive; employees missing or below 1; any negative case component; hours per average employee above 4,500 (about 86 hours a week, every week); or hours per employee below 120 (about three full-time weeks). A sixth flag, in which the self-declared "no injuries" box contradicts the case counts, is reported but excluded from the verdict by default because it does not corrupt the denominator. The bounds are configuration, not truth, which is why they are varied in Section 5.

### 3.2 Aggregate rates

The unscreened aggregate TRIR is 200,000 times total cases divided by total hours over all filings. The screened aggregate uses only filings that pass the screen. Their ratio measures the bias.

### 3.3 Count models

Four models with an exposure offset in 200,000-hour units (Poisson, NB2, ZIP, ZINB) are fitted by maximum likelihood to the 30 largest three-digit industry groups with at least 500 establishments in 2024, chosen on size alone so that selection cannot favour a model. Models are compared by Akaike and Bayesian information criteria and by observed against expected zeros. The test of ZINB against NB2 puts the inflation probability on the boundary of the parameter space, so its null distribution is an equal mixture of a point mass at zero and a chi-square with one degree of freedom, and the reported p-value is half the naive one. A second specification adds establishment size-band dummies and four-digit industry fixed effects to the mean equation, keeping a constant inflation probability. Estimators are checked by recovery of known parameters on synthetic data, which is used for tests only and never for any number reported here.

### 3.4 Peer groups and stability

Peer groups are three-digit industry by establishment size band, and cells with fewer than 30 establishments carrying a computable rate are marked not publishable. Stability between adjacent years is the Spearman rank correlation of cell percentiles (p10, p25, p50, p75, p90, p95) over cells present in both years, plus the median absolute relative change, with cell persistence reported alongside.

### 3.5 Linkage audit

Using only committed tables, we count how many years each `establishment_id` appears in, how much of each adjacent-year pair of filings links, and how often an identifier carries more than one employer identification number, company name or state. Each question is labelled answered, partially bounded, or not answerable from the committed tables.

### 3.6 Threshold robustness

The default bounds are one researcher choice, so all 25 pairs of lower bound (100, 120, 200, 250, 400 hours) and upper bound (3,500, 4,000, 4,500, 5,000, 6,000 hours) in the committed sensitivity grid are examined as a specification curve. Because the flagged sets are nested along each bound, subtracting flagged totals between two cells gives the filings that change status. A threshold-free cross-check drops the filings with the most reported hours and recomputes the rate.

### 3.7 Year stability

The pooled flagged count, hours and cases are sums over years, so the headline without a given year is the sum over the other eight, checked against the pooled table. We also report year-over-year changes and the effect on peer-group rank correlation of removing the pairs that involve the omitted year.

### 3.8 Pre-registration

Predictions for the 2025 release were fixed on 2026-10-27, before any 2025 filing exists in the repository, by one transparent rule: the point prediction is the mean of the last three observed years on a transformed scale, and the 95% interval is a back-tested root-mean-square error scaled by a Student t quantile. The decision rule (a prediction holds if the observed value lies inside its interval) is frozen with the code that produced it.

## 4. Results

### 4.1 Screening and the aggregate-rate bias

The screen flags 57,857 of 2,801,064 filings (2.07%). Those filings hold 96.68% of all reported hours and 1.37% of all reported cases. The pooled aggregate TRIR is 0.134 unscreened and 3.983 screened, a ratio of 29.7. The median establishment TRIR among screened filings is 2.469.

One flag does essentially all of the work. Filings with more than 4,500 hours per employee number 24,617 and hold 96.65% of all hours. Filings with fewer than 120 hours per employee number 22,904 but hold 0.03% of hours. Filings with missing hours (9,897), missing employees (10,322), a contradictory "no injuries" box (301) or a negative case count (1) matter for establishment-level rates but not for the aggregate; the largest hours share among them is 0.00037%.

The size of the bias depends on which years are pooled (Table 1). The screened rate is steady, from 3.147 to 4.605 across the nine years, whereas the unscreened rate runs from 0.016 to 2.920. The yearly ratio runs from 1.39 to 249.3. The 2019 file alone holds 99.60% of its hours in flagged filings, which is why its unscreened rate is 0.016.

**Table 1.** Aggregate TRIR by reporting year.

| Year | Unscreened TRIR | Screened TRIR |
|---|---:|---:|
| 2016 | 2.729 | 3.921 |
| 2017 | 2.634 | 3.998 |
| 2018 | 2.920 | 4.069 |
| 2019 | 0.016 | 4.018 |
| 2020 | 2.792 | 4.491 |
| 2021 | 2.385 | 4.368 |
| 2022 | 2.661 | 4.605 |
| 2023 | 1.380 | 3.147 |
| 2024 | 0.280 | 3.642 |

### 4.2 Count models

In the intercept-only comparison, Poisson and ZIP are never best by AIC in any of the 30 industries; NB2 is best in 15 and ZINB in 15. The variance-to-mean ratio of recordable counts runs from 3.0 to 756.5, against the value of 1 that Poisson assumes. Overdispersion therefore appears in every industry. In 14 of the 30 industries the zero-inflation parameter of ZINB collapses to the boundary.

With covariates the picture sharpens (specification in Section 3.3). NB2 beats Poisson at a boundary-corrected p below 0.001 in 30 of 30 industries, with the AIC improvement ranging from 1,712 to 70,072 points; the NB2 dispersion has a median of 0.79 and a minimum of 0.16. Zero inflation is weaker: ZINB is best by AIC in 10 of 30 industries over all fits and in 9 of 30 over converged fits, and the ZINB-versus-NB2 boundary test is below 0.01 in 9. In 13 ZINB fits the inflation probability stays at its lower bound and the fit is flagged unconverged. Part of what looked like excess zeros was therefore mean heterogeneity across size bands and sub-industries. The fitted groups are the largest, not a sample of all industries: of 122 three-digit groups present in 2024, 71 have at least 500 establishments and 30 are fitted, covering 78.8% of screened establishments, 72.1% of hours and 76.0% of recordable cases.

The zero share is mostly an exposure effect. Among plausible filings the share of establishments reporting zero recordable cases is 75.1% in the smallest size band and 8.1% in the largest, and the median establishment TRIR is 0.00 in the smallest band and 3.61 for 100 to 249 employees, so a benchmark that ignores size compares a site with a number driven by how large the other sites are.

### 4.3 Peer-group stability

Across 8 adjacent-year pairs and six percentiles, the Spearman rank correlation of peer-group percentiles runs from 0.840 to 0.946 (mean 0.893), with the lowest value at p75 between 2022 and 2023. The share of a year's peer groups that also appear in the next year runs from 95.7% to 98.5%. The ordering of groups is thus reproducible, but the level is not: the median absolute relative change is 10.1% at p50 and 25.7% at p10, where small denominators make the percentile itself unstable. Movement of a site across a percentile band of that size is not evidence of a change in its own performance.

### 4.4 What the establishment identifier supports

Of 1,238,236 distinct identifiers, 50.3% appear in exactly one year and 1.3% in all nine; identifiers seen in one year account for 22.3% of all filings. Adjacent-year linkage, as a share of the earlier year's filings, runs from 55.8% to 63.3%. Among identifiers present in two or more years, 51.0% carry more than one employer identification number, 17.7% more than one company name and 0.7% more than one state, so `establishment_id` tracks a site more reliably than a legal filer. Two questions are not answerable from committed tables: how many identifiers change industry or size band, and how much of the correction sits in single-appearance establishments. What can be bounded: the single largest filing holds 88.8% of all hours, the 50 largest flagged filings (from 50 distinct identifiers) hold 95.0%, and at most 32,792 of the 57,857 flagged filings (56.7%) belong to identifiers seen in one year, which is a bound on counts and not on the correction, because the correction is dominated by a few filings. By year, 2019 holds 92.6% of pooled flagged hours and 2024 holds 5.4%.

## 5. Robustness

### 5.1 Threshold robustness

Across the 25 bound pairs the screened aggregate TRIR runs from 3.963 to 3.993, a range of 0.030, and the largest departure from the default of 3.983 is 0.50%. The unscreened TRIR is 0.134 in every cell, and the screened rate exceeds it in 25 of 25 cells, with the ratio between 29.56 and 29.79. The flagged share is not stable: it runs from 1.79% (50,180 filings) to 4.49% (125,741 filings), so the statement that 2.07% of filings are flagged is a property of the chosen bounds and should be quoted with its range. What stays fixed is the weight of what is flagged: flagged filings hold 96.67% to 96.71% of all hours and 1.22% to 2.27% of all cases in every cell.

The reason is that the filings that move between cells carry almost no hours. Raising the lower bound from 120 to 400 hours reclassifies 55,448 filings with a band TRIR of 9.663, yet the largest reclassified band (the 12,436 filings that enter the flagged set when the upper bound falls from 4,500 to 3,500 hours) holds only 0.018% of pooled hours. The aggregate is set by the few filings with enormous hours, which every cell flags.

As a check with no hours-per-employee bound at all, dropping only the single filing with the most hours lifts the aggregate TRIR from 0.134 to 1.198, and dropping the 10,000 filings with the most hours (0.357% of filings) gives 4.137, the same order as the screened 3.983. The trim is cruder than the screen and does not converge to it, but it points the same way.

### 5.2 Year stability

Leaving each year out in turn, the screened aggregate TRIR runs from 3.901 to 4.137, and the largest departure from the pooled value is 3.86% (leaving out 2023). The flagged share runs from 2.00% to 2.12%. The unscreened TRIR is not stable: it runs from 0.117 to 1.186, and leaving out 2019 changes it by 785%. The screened-to-unscreened ratio nonetheless exceeds 1 in every pool, ranging from 3.4 to 34.8. Year over year, the screened TRIR has a coefficient of variation of 0.111, a median absolute change of 4.1% and a largest change of 31.7% (2023, which the tables describe but do not explain); the unscreened TRIR spans a factor of 181. The screened rate exceeds the unscreened rate in 9 of 9 years. Leaving out any one year leaves the mean peer-group rank correlation between 0.890 and 0.899, so no single year carries that result.

### 5.3 Pre-registered predictions for 2025

The pre-registration lists 12 scored predictions. Two of the informative ones: the flagged share is predicted at 0.0224 (interval 0.0136 to 0.0364), and the screened aggregate TRIR at 3.7977 (interval 2.2827 to 5.3127). The structural claim is that the screened-to-unscreened ratio stays above 1. The intervals for the unscreened rate and the flagged hours share are close to uninformative because of the extreme filings in 2019 and 2024, which is stated in advance. If the intervals were correct and independent, the chance of three or more misses would be 2.0%; independence does not hold, so three or more misses would be read as the method being too narrow. No 2025 data are in the repository, so none of these predictions has yet been scored.

## 6. Limitations

- **Identification of errors.** The screen finds filings whose numerator and denominator cannot both be right. It does not identify which entry is wrong and is not a fraud detector.
- **Not the US workforce.** The ITA covers a mandated, selected slice of establishments (larger employers and listed higher-hazard industries). The screened aggregate is not comparable with national survey rates and is not compared with them here.
- **Zeros are ambiguous.** The count models measure how many zeros exceed what overdispersion predicts. They cannot separate an incident-free year from an unrecorded one, and nothing here shows that under-reporting is absent.
- **Count-model scope.** Fits cover the 30 largest industries in one year, with a constant inflation probability and no standard errors for model parameters; coefficients are descriptive, not causal. The four largest groups are subsampled for runtime.
- **Linkage.** Establishment identity across years is not verified against any substitute key, and the share of the correction in single-appearance establishments is not answerable from committed tables.
- **Robustness is not correctness.** Insensitivity to the bounds and to each year does not show that every flagged filing is wrong or that the screened rate equals a true rate. The grid covers bounds from 100 to 400 and 3,500 to 6,000 hours only, varies one variable, and reports no sampling uncertainty.
- **Years are not independent samples.** The same establishments file repeatedly and the set of filers grows each year, so year-to-year differences mix real change and composition.
- **Source files change.** OSHA revises published files in place; results from a republished file are not comparable to these.
- **Single author, no external validation.** The pipeline has not been independently replicated, and the literature review is deliberately absent (see `docs/manuscript/OPEN_ITEMS.md`).

## 7. Reproducibility statement

All code, committed output tables and tests are in the public repository cited below, at the commit named there. The raw files are public but not redistributed; `make data` downloads them and records a cryptographic digest for each, and the nine digests are listed in `REPRODUCIBILITY.md`. `make analysis` regenerates every table, figure and `outputs/summary.json` (measured runtime 93.4 seconds on the authoring machine) with random seed 20260903 and Python 3.9. The seed governs only the subsampling of the largest count-model groups. Every number in this manuscript is registered in Appendix A with its source file and a machine-checkable locator, and `tests/test_manuscript.py` fails if a number drifts from its source, if a number in the text is not registered, or if a registered number is not used. A fixed-seed synthetic fixture exercises the pipeline without network access; no number from it appears here. The code is MIT licensed; the OSHA files are works of a US federal agency, subject to the caveats in the repository README. The 2025 predictions are frozen by a script hash that a test checks.

## 8. Discussion

For anyone who computes injury rates from self-reported hours, two practical points follow. A pooled unscreened rate is a statement about the tail of the hours distribution, not about safety, and its error is not a fixed multiplier. A screened rate near four per hundred full-time workers is, in these data, robust to where the bounds are drawn and to which single year is left out, but the share of filings called implausible is not, and both should be reported together. For benchmarking, peer groups should condition on establishment size, and percentile movements of around a tenth from one year to the next should not be read as performance change.

## References

1. Chimmani, P. *ehs-osha-analysis: a reproducible pipeline over the OSHA Injury Tracking Application 300A filings*. Software and committed outputs, version 0.1.0 plus unreleased additions. https://github.com/priyatham9/ehs-osha-analysis (base commit `d57c11b1465c020fdc7a1b15dc0807eeb08fe472`; existence of the repository verified through raw.githubusercontent.com on the date of this draft).

No journal or book references are cited. The ones considered could not be verified from the sandbox (only GitHub hosts were reachable) and are listed as unverified in `docs/manuscript/OPEN_ITEMS.md`.

## Appendix A. Number to source file

Each row gives a number exactly as written in the text above, the committed file it is copied from, and a locator that `tests/test_manuscript.py` evaluates. Locator syntax: `col=X` names the column (for `summary.json`, `path=a.b.c`); `where k=v, k2!=v2` filters rows; `agg=min|max|median|mean|sum` aggregates the filtered rows (default: exactly one row); `x100` multiplies by 100 (shares shown as percent); `abs` takes the absolute value; `grep` means the literal number string must occur in the named document. The check passes if the value rounds to the number at the number's own printed precision.

| Number | Source file | Locator | Used for |
|---|---|---|---|
| 2,801,064 | outputs/tables/quality_overall.csv | col=n_filings | pooled deduplicated filings |
| 2,805,767 | outputs/summary.json | path=load_report.rows_raw | raw rows in nine files |
| 4,703 | outputs/summary.json | path=load_report.duplicate_rows_dropped | duplicate establishment-years dropped |
| 1,238,236 | outputs/tables/panel_coverage.csv | col=value; where metric=distinct_establishments | distinct establishment_id values |
| 57,857 | outputs/tables/quality_overall.csv | col=n_implausible | flagged filings |
| 2.07 | outputs/tables/quality_overall.csv | col=implausible_share; x100 | flagged share, percent |
| 96.68 | outputs/tables/quality_overall.csv | col=hours_share_implausible; x100 | share of hours in flagged filings, percent |
| 1.37 | outputs/tables/quality_overall.csv | col=cases_share_implausible; x100 | share of cases in flagged filings, percent |
| 0.134 | outputs/tables/quality_overall.csv | col=aggregate_trir_unscreened | pooled unscreened aggregate TRIR |
| 3.983 | outputs/tables/quality_overall.csv | col=aggregate_trir_screened | pooled screened aggregate TRIR |
| 29.7 | outputs/tables/quality_overall.csv | col=ratio_screened_to_unscreened | pooled screened/unscreened ratio |
| 2.469 | outputs/tables/quality_overall.csv | col=median_establishment_trir_screened | median screened establishment TRIR |
| 1.39 | outputs/tables/quality_by_year.csv | col=ratio_screened_to_unscreened; agg=min | smallest yearly ratio |
| 249.3 | outputs/tables/quality_by_year.csv | col=ratio_screened_to_unscreened; agg=max | largest yearly ratio (2019) |
| 3.963 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=trir_screened_min | minimum screened TRIR over 25 bound pairs |
| 3.993 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=trir_screened_max | maximum screened TRIR over 25 bound pairs |
| 1.79 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=implausible_share_min; x100 | minimum flagged share over grid, percent |
| 4.49 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=implausible_share_max; x100 | maximum flagged share over grid, percent |
| 30 | outputs/tables/count_model_covariates_summary.csv | col=value; where statistic=n_industries_fitted | industries fitted |
| 9 | outputs/tables/count_model_covariates_summary.csv | col=value; where statistic=n_industries_zinb_beats_nb2_p_boundary_lt_0.01 | industries where ZINB beats NB2 at boundary p<0.01 (converged) |
| 1 | README.md | grep=value of 1 that Poisson assumes | variance-to-mean value under Poisson; also ratio threshold of 1 |
| 7 | README.md | grep=declared 7 employees | employees declared by the largest filing |
| 16,831,620,723,179 | outputs/tables/quality_top50_implausible_hours.csv | col=total_hours_worked; where year_filing_for=2019, naics_code=238140 | hours declared by that filing |
| 7 | outputs/tables/quality_top50_implausible_hours.csv | col=annual_average_employees; where year_filing_for=2019, naics_code=238140 | employees declared by that filing |
| 2.4 | outputs/tables/quality_top50_implausible_hours.csv | col=hours_per_employee; where year_filing_for=2019, naics_code=238140; x1e-12 | trillion hours per employee |
| 8,760 | README.md | grep=physical ceiling of 8,760 | hours in a year |
| 88.8 | outputs/tables/quality_hours_concentration.csv | col=hours_share; where top_n_filings_by_hours=1; x100 | share of all hours in the single largest filing |
| 200,000 | README.md | grep=TRIR = 200,000 x recordable cases | TRIR constant |
| 86 | README.md | grep=about 86 h/week | weekly hours at the upper bound |
| 120 | outputs/summary.json | path=config.plausibility.min_hours_per_employee | lower bound hours per employee |
| 4,500 | outputs/summary.json | path=config.plausibility.max_hours_per_employee | upper bound hours per employee |
| 30 | outputs/summary.json | path=config.min_group_n | peer-cell minimum establishments |
| 500 | outputs/summary.json | path=config.model_min_group_n | minimum establishments for a fitted industry |
| 93.4 | outputs/summary.json | path=runtime_seconds | measured pipeline runtime, seconds |
| 20260903 | outputs/summary.json | path=config.random_seed | random seed |
| 3.9 | README.md | grep=Runs on Python 3.9 | Python version |
| 50 | outputs/tables/quality_top50_implausible_hours.csv | col=year_filing_for; agg=count | rows in the 50-filing table; also number of largest flagged filings |
| 100 | docs/THRESHOLD_ROBUSTNESS.md | grep=lower bound (100, 120, 200, 250, 400) | lower bounds of the grid |
| 250 | docs/THRESHOLD_ROBUSTNESS.md | grep=lower bound (100, 120, 200, 250, 400) | lower bounds of the grid |
| 400 | docs/THRESHOLD_ROBUSTNESS.md | grep=lower bound (100, 120, 200, 250, 400) | lower bounds of the grid |
| 120 | docs/THRESHOLD_ROBUSTNESS.md | grep=lower bound (100, 120, 200, 250, 400) | lower bounds of the grid |
| 200 | docs/THRESHOLD_ROBUSTNESS.md | grep=lower bound (100, 120, 200, 250, 400) | lower bounds of the grid |
| 3,500 | docs/THRESHOLD_ROBUSTNESS.md | grep=upper bound (3,500, 4,000, 4,500, 5,000, 6,000) | upper bounds of the grid |
| 4,000 | docs/THRESHOLD_ROBUSTNESS.md | grep=upper bound (3,500, 4,000, 4,500, 5,000, 6,000) | upper bounds of the grid |
| 5,000 | docs/THRESHOLD_ROBUSTNESS.md | grep=upper bound (3,500, 4,000, 4,500, 5,000, 6,000) | upper bounds of the grid |
| 6,000 | docs/THRESHOLD_ROBUSTNESS.md | grep=upper bound (3,500, 4,000, 4,500, 5,000, 6,000) | upper bounds of the grid |
| 25 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=n_specifications | bound pairs in the grid |
| 24,617 | outputs/tables/quality_flag_prevalence.csv | col=n; where flag=flag_hours_per_employee_high | filings above upper bound |
| 96.65 | outputs/tables/quality_flag_prevalence.csv | col=hours_share; where flag=flag_hours_per_employee_high; x100 | hours share of that flag, percent |
| 22,904 | outputs/tables/quality_flag_prevalence.csv | col=n; where flag=flag_hours_per_employee_low | filings below lower bound |
| 0.03 | outputs/tables/quality_flag_prevalence.csv | col=hours_share; where flag=flag_hours_per_employee_low; x100 | hours share of that flag, percent |
| 9,897 | outputs/tables/quality_flag_prevalence.csv | col=n; where flag=flag_hours_missing | missing or non-positive hours |
| 10,322 | outputs/tables/quality_flag_prevalence.csv | col=n; where flag=flag_employees_missing | missing employees |
| 301 | outputs/tables/quality_flag_prevalence.csv | col=n; where flag=flag_no_injury_contradiction | contradictory no-injuries box |
| 1 | outputs/tables/quality_flag_prevalence.csv | col=n; where flag=flag_negative_counts | negative case count |
| 0.00037 | outputs/tables/quality_flag_prevalence.csv | col=hours_share; where flag=flag_employees_missing; x100 | largest hours share among the minor flags, percent |
| 3.147 | outputs/tables/quality_by_year.csv | col=aggregate_trir_screened; agg=min | lowest yearly screened TRIR |
| 4.605 | outputs/tables/quality_by_year.csv | col=aggregate_trir_screened; agg=max | highest yearly screened TRIR |
| 0.016 | outputs/tables/quality_by_year.csv | col=aggregate_trir_unscreened; agg=min | lowest yearly unscreened TRIR |
| 2.920 | outputs/tables/quality_by_year.csv | col=aggregate_trir_unscreened; agg=max | highest yearly unscreened TRIR |
| 99.60 | outputs/tables/quality_by_year.csv | col=hours_share_implausible; where label=2019.0; x100 | 2019 hours share in flagged filings, percent |
| 2.729 | outputs/tables/quality_by_year.csv | col=aggregate_trir_unscreened; where label=2016.0 | Table 1, 2016 unscreened |
| 3.921 | outputs/tables/quality_by_year.csv | col=aggregate_trir_screened; where label=2016.0 | Table 1, 2016 screened |
| 2.634 | outputs/tables/quality_by_year.csv | col=aggregate_trir_unscreened; where label=2017.0 | Table 1, 2017 unscreened |
| 3.998 | outputs/tables/quality_by_year.csv | col=aggregate_trir_screened; where label=2017.0 | Table 1, 2017 screened |
| 4.069 | outputs/tables/quality_by_year.csv | col=aggregate_trir_screened; where label=2018.0 | Table 1, 2018 screened |
| 4.018 | outputs/tables/quality_by_year.csv | col=aggregate_trir_screened; where label=2019.0 | Table 1, 2019 screened |
| 2.792 | outputs/tables/quality_by_year.csv | col=aggregate_trir_unscreened; where label=2020.0 | Table 1, 2020 unscreened |
| 4.491 | outputs/tables/quality_by_year.csv | col=aggregate_trir_screened; where label=2020.0 | Table 1, 2020 screened |
| 2.385 | outputs/tables/quality_by_year.csv | col=aggregate_trir_unscreened; where label=2021.0 | Table 1, 2021 unscreened |
| 4.368 | outputs/tables/quality_by_year.csv | col=aggregate_trir_screened; where label=2021.0 | Table 1, 2021 screened |
| 2.661 | outputs/tables/quality_by_year.csv | col=aggregate_trir_unscreened; where label=2022.0 | Table 1, 2022 unscreened |
| 1.380 | outputs/tables/quality_by_year.csv | col=aggregate_trir_unscreened; where label=2023.0 | Table 1, 2023 unscreened |
| 0.280 | outputs/tables/quality_by_year.csv | col=aggregate_trir_unscreened; where label=2024.0 | Table 1, 2024 unscreened |
| 3.642 | outputs/tables/quality_by_year.csv | col=aggregate_trir_screened; where label=2024.0 | Table 1, 2024 screened |
| 15 | outputs/tables/count_model_selection_summary.csv | col=n_industries_best_by_aic; where model=nb2 | industries where NB2 is best, intercept-only (ZINB also 15) |
| 3.0 | outputs/tables/count_model_comparison.csv | col=variance_to_mean_ratio; agg=min | minimum variance-to-mean ratio |
| 756.5 | outputs/tables/count_model_comparison.csv | col=variance_to_mean_ratio; agg=max | maximum variance-to-mean ratio |
| 14 | outputs/tables/count_model_comparison.csv | col=zero_inflation_pi; where model=zinb, zero_inflation_pi<1e-10; agg=count | industries where ZINB pi collapses to boundary |
| 0.001 | outputs/tables/count_model_covariates_summary.csv | grep=n_industries_nb2_beats_poisson_p_boundary_lt_0.001 | p threshold in statistic name |
| 1,712 | outputs/tables/count_model_covariates_summary.csv | col=value; where statistic=max_delta_aic_nb2_minus_poisson; abs | smallest AIC gain of NB2 over Poisson (absolute) |
| 70,072 | outputs/tables/count_model_covariates_summary.csv | col=value; where statistic=min_delta_aic_nb2_minus_poisson; abs | largest AIC gain of NB2 over Poisson (absolute) |
| 0.79 | outputs/tables/count_model_covariates_summary.csv | col=value; where statistic=median_alpha_nb2 | median NB2 dispersion with covariates |
| 0.16 | outputs/tables/count_model_covariates_summary.csv | col=value; where statistic=min_alpha_nb2 | minimum NB2 dispersion with covariates |
| 10 | outputs/tables/count_model_covariates_summary.csv | col=value; where statistic=n_industries_best_by_aic_zinb | industries where ZINB is best by AIC, all fits |
| 0.01 | outputs/tables/count_model_covariates_summary.csv | grep=n_industries_zinb_beats_nb2_p_boundary_lt_0.01 | p threshold in statistic name |
| 13 | outputs/tables/count_model_covariates_summary.csv | col=value; where statistic=n_zinb_fits_unconverged_pi_at_boundary | unconverged ZINB fits |
| 122 | outputs/tables/count_model_covariates_coverage.csv | col=value; where statistic=n_naics3_groups_total | three-digit groups present in 2024 |
| 71 | outputs/tables/count_model_covariates_coverage.csv | col=value; where statistic=n_naics3_groups_at_least_min_group_n | groups with at least 500 establishments |
| 78.8 | outputs/tables/count_model_covariates_coverage.csv | col=value; where statistic=share_establishments_in_fitted_groups; x100 | establishment coverage of fitted groups, percent |
| 72.1 | outputs/tables/count_model_covariates_coverage.csv | col=value; where statistic=share_hours_in_fitted_groups; x100 | hours coverage, percent |
| 76.0 | outputs/tables/count_model_covariates_coverage.csv | col=value; where statistic=share_recordable_cases_in_fitted_groups; x100 | case coverage, percent |
| 75.1 | outputs/tables/size_band_effects.csv | col=zero_share; where size_band=001-019; x100 | zero share, smallest band, percent |
| 8.1 | outputs/tables/size_band_effects.csv | col=zero_share; where size_band=1000+; x100 | zero share, largest band, percent |
| 0.00 | outputs/tables/size_band_effects.csv | col=median_establishment_trir; where size_band=001-019 | median site TRIR, smallest band |
| 3.61 | outputs/tables/size_band_effects.csv | col=median_establishment_trir; where size_band=100-249 | median site TRIR, 100 to 249 band |
| 249 | README.md | grep=3.61 at 100-249 employees | upper edge of the 100 to 249 size band |
| 100 | README.md | grep=3.61 at 100-249 employees | lower edge of the 100 to 249 size band |
| 0.840 | outputs/tables/year_stability_summary.csv | col=value; where metric=rho_min | minimum adjacent-year Spearman rho |
| 0.946 | outputs/tables/year_stability_summary.csv | col=value; where metric=rho_max | maximum rho |
| 0.893 | outputs/tables/year_stability_summary.csv | col=value; where metric=rho_mean | mean rho |
| 95.7 | outputs/tables/year_stability_summary.csv | col=value; where metric=matched_share_min; x100 | minimum peer-group persistence, percent |
| 98.5 | outputs/tables/year_stability_summary.csv | col=value; where metric=matched_share_max; x100 | maximum peer-group persistence, percent |
| 8 | outputs/tables/year_stability_summary.csv | col=value; where metric=n_year_pairs | adjacent year pairs |
| 10.1 | outputs/tables/percentile_band_stability.csv | col=median_abs_rel_change; where percentile=p50; agg=median; x100 | median absolute relative change at p50, percent |
| 25.7 | outputs/tables/percentile_band_stability.csv | col=median_abs_rel_change; where percentile=p10; agg=median; x100 | median absolute relative change at p10, percent |
| 50.3 | outputs/tables/panel_linkage_audit.csv | col=share; where metric=ids_in_exactly_1_years; x100 | ids appearing in one year, percent |
| 1.3 | outputs/tables/panel_linkage_audit.csv | col=share; where metric=ids_in_exactly_9_years; x100 | ids appearing in all nine years, percent |
| 22.3 | outputs/tables/panel_linkage_audit.csv | col=share; where metric=filings_from_ids_in_exactly_1_years; x100 | filings from single-year ids, percent |
| 55.8 | outputs/tables/panel_linkage_audit.csv | col=share; where section=adjacent_year_linkage; agg=min; x100 | minimum adjacent-year linkage, percent |
| 63.3 | outputs/tables/panel_linkage_audit.csv | col=share; where section=adjacent_year_linkage; agg=max; x100 | maximum adjacent-year linkage, percent |
| 51.0 | outputs/tables/panel_linkage_audit.csv | col=share; where metric=ids_with_more_than_one_ein, share_basis=ids in 2+ years (only these can change); x100 | ids with more than one EIN, percent |
| 17.7 | outputs/tables/panel_linkage_audit.csv | col=share; where metric=ids_with_more_than_one_company_name, share_basis=ids in 2+ years (only these can change); x100 | ids with more than one company name, percent |
| 0.7 | outputs/tables/panel_linkage_audit.csv | col=share; where metric=ids_with_more_than_one_state, share_basis=ids in 2+ years (only these can change); x100 | ids with more than one state, percent |
| 95.0 | outputs/tables/panel_linkage_audit.csv | col=share; where metric=all_reported_hours_in_top50_flagged_filings; x100 | hours share of 50 largest flagged filings, percent |
| 32,792 | outputs/tables/panel_linkage_audit.csv | col=value; where metric=flagged_filings_from_single_year_ids_at_most | upper bound on flagged filings from single-year ids |
| 56.7 | outputs/tables/panel_linkage_audit.csv | col=share; where metric=flagged_filings_from_single_year_ids_at_most; x100 | that bound as share of flagged filings, percent |
| 92.6 | outputs/tables/panel_linkage_audit.csv | col=share; where metric=flagged_hours_in_2019; x100 | 2019 share of pooled flagged hours, percent |
| 5.4 | outputs/tables/panel_linkage_audit.csv | col=share; where metric=flagged_hours_in_2024; x100 | 2024 share of pooled flagged hours, percent |
| 50 | outputs/tables/panel_linkage_audit.csv | col=value; where metric=distinct_ids_among_top50_flagged_filings | distinct ids among top 50 flagged filings |
| 0.030 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=trir_screened_range | range of screened TRIR over grid |
| 0.50 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=trir_screened_max_abs_pct_from_default | largest departure from default, percent |
| 29.56 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=ratio_min | smallest ratio over grid |
| 29.79 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=ratio_max | largest ratio over grid |
| 50,180 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=n_implausible_min | fewest flagged filings over grid |
| 125,741 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=n_implausible_max | most flagged filings over grid |
| 96.67 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=hours_share_flagged_min; x100 | minimum hours share flagged, percent |
| 96.71 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=hours_share_flagged_max; x100 | maximum hours share flagged, percent |
| 1.22 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=cases_share_flagged_min; x100 | minimum cases share flagged, percent |
| 2.27 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=cases_share_flagged_max; x100 | maximum cases share flagged, percent |
| 55,448 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=lower_bound_120_to_400_filings | filings reclassified, lower bound 120 to 400 |
| 9.663 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=lower_bound_120_to_400_trir | band TRIR for that move |
| 12,436 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=upper_bound_3500_to_4500_filings | filings entering flagged set, upper bound 4,500 to 3,500 |
| 0.018 | docs/THRESHOLD_ROBUSTNESS.md | grep=The largest band holds 0.018% | hours share of largest reclassified band, percent |
| 1.198 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=drop_top_1_by_hours_trir | TRIR after dropping the largest filing |
| 4.137 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=drop_top_10000_by_hours_trir | TRIR after dropping the 10,000 largest filings |
| 0.357 | outputs/tables/threshold_robustness_summary.csv | col=value; where metric=drop_top_10000_by_hours_share_of_filings; x100 | share of filings dropped, percent |
| 10,000 | outputs/tables/quality_hours_concentration.csv | col=top_n_filings_by_hours; agg=max | largest trim size |
| 3.901 | outputs/tables/year_stability_summary.csv | col=value; where metric=trir_screened_loyo_min | minimum leave-one-year-out screened TRIR |
| 4.137 | outputs/tables/year_stability_summary.csv | col=value; where metric=trir_screened_loyo_max | maximum leave-one-year-out screened TRIR |
| 3.86 | outputs/tables/year_stability_summary.csv | col=value; where metric=trir_screened_loyo_max_abs_pct_from_pooled | largest departure from pooled, percent |
| 2.00 | outputs/tables/year_stability_summary.csv | col=value; where metric=implausible_share_loyo_min; x100 | minimum leave-one-out flagged share, percent |
| 2.12 | outputs/tables/year_stability_summary.csv | col=value; where metric=implausible_share_loyo_max; x100 | maximum leave-one-out flagged share, percent |
| 0.117 | outputs/tables/year_stability_summary.csv | col=value; where metric=trir_unscreened_loyo_min | minimum leave-one-out unscreened TRIR |
| 1.186 | outputs/tables/year_stability_summary.csv | col=value; where metric=trir_unscreened_loyo_max | maximum leave-one-out unscreened TRIR |
| 785 | outputs/tables/year_stability_summary.csv | col=value; where metric=trir_unscreened_loyo_max_abs_pct_from_pooled | change when 2019 is left out, percent |
| 3.4 | outputs/tables/year_stability_summary.csv | col=value; where metric=loyo_ratio_min | smallest leave-one-out ratio |
| 34.8 | outputs/tables/year_stability_summary.csv | col=value; where metric=loyo_ratio_max | largest leave-one-out ratio |
| 0.111 | outputs/tables/year_stability_summary.csv | col=value; where metric=trir_screened_cv | coefficient of variation of yearly screened TRIR |
| 4.1 | outputs/tables/year_stability_summary.csv | col=value; where metric=trir_screened_median_abs_pct_change | median absolute year-over-year change, percent |
| 31.7 | outputs/tables/year_stability_summary.csv | col=value; where metric=trir_screened_max_abs_pct_change | largest year-over-year change, percent |
| 181 | outputs/tables/year_stability_summary.csv | col=value; where metric=trir_unscreened_max_over_min | max/min of yearly unscreened TRIR |
| 9 | outputs/tables/year_stability_summary.csv | col=value; where metric=years_screened_above_unscreened | years with screened above unscreened |
| 0.890 | outputs/tables/year_stability_loyo.csv | col=peer_mean_spearman_rho; where left_out_year!=all; agg=min | minimum mean rho with one year left out |
| 0.899 | outputs/tables/year_stability_loyo.csv | col=peer_mean_spearman_rho; where left_out_year!=all; agg=max | maximum mean rho with one year left out |
| 12 | docs/PREREGISTRATION_2025.md | grep=there are 12 scored predictions | scored predictions |
| 0.0224 | docs/preregistration_2025_predictions.csv | col=pred; where id=Q1 | predicted flagged share |
| 0.0136 | docs/preregistration_2025_predictions.csv | col=lo95; where id=Q1 | interval low |
| 0.0364 | docs/preregistration_2025_predictions.csv | col=hi95; where id=Q1 | interval high |
| 3.7977 | docs/preregistration_2025_predictions.csv | col=pred; where id=Q2 | predicted screened TRIR |
| 2.2827 | docs/preregistration_2025_predictions.csv | col=lo95; where id=Q2 | interval low |
| 5.3127 | docs/preregistration_2025_predictions.csv | col=hi95; where id=Q2 | interval high |
| 2.0 | docs/PREREGISTRATION_2025.md | grep=46%, 12%, 2.0% and 0.2% | chance of three or more misses, percent |
| 95 | docs/PREREGISTRATION_2025.md | grep=95% interval | interval coverage level, percent |
