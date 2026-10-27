# Pre-registration: predictions for the reporting-year-2025 ITA release

**Registered on 2026-10-27.** At this date no reporting-year-2025 filings exist in this repository: `outputs/tables/` and `data/raw/` stop at filing year 2024. The git history of this file, of `scripts/preregister_2025.py` and of `docs/preregistration_2025_predictions.csv` is the timestamp: the commit that adds them precedes any commit that adds 2025 data or outputs. This page is not edited after that commit except to append a clearly dated results section (see "After the data arrive").

Scope: these are predictions about the repository's own pipeline outputs once 2025 filings are processed, not claims about workplace safety in 2025. They test whether the stability and instability patterns documented in this project (flagged filings are a small share of filings but most of the hours; screened TRIR is stable while unscreened TRIR is not) continue to hold on a year the models have not seen.

## Inputs and model

Inputs are committed tables only, restricted to filing years 2016-2024: `outputs/tables/quality_by_year.csv` and `outputs/tables/peer_percentiles_by_year.csv` (the latter for zero-injury shares by size band, aggregated over NAICS-3 cells weighted by `n_with_metric`; pooled over years this reproduces `size_band_effects.csv` `zero_share` to the printed precision). `metrics_by_year.csv` carries the same screened and unscreened TRIR as `quality_by_year.csv` and is not used separately.

One transparent model for every quantity, on a transformed scale (identity for screened TRIR, logit for shares, log for the unscreened TRIR):

1. Point prediction: mean of the last three observed years (2022-2024).
2. 95% interval: back-test the same rule. For each year with three earlier years (2019-2024) compute the one-step error `x_t - mean(x_{t-3..t-1})`; half-width is 2.4469 (Student t, 0.975 quantile, 6 degrees of freedom) times the root mean square of the six errors. With six errors this is an approximation and the stated 95% is nominal.
3. Q5 is not a trend model but a structural claim: the screened/unscreened TRIR ratio stays strictly above 1.0 (it was above 1.39 in all nine observed years).

## Predictions

| ID | Quantity | Prediction for 2025 | 95% interval (held if inside) |
|---|---|---|---|
| Q1 | flagged-filing share (n_implausible / n_filings) | 0.0224 | 0.0136 to 0.0364 |
| Q2 | aggregate TRIR, screened | 3.7977 | 2.2827 to 5.3127 |
| Q3 | aggregate TRIR, unscreened | 1.0098 | 0.0019 to 523.3899 |
| Q4 | share of reported hours held by flagged filings | 0.6962 | 0.0013 to 0.9997 |
| Q5 | ratio of screened to unscreened aggregate TRIR (structural claim: above 1) | above 1.0 (observed minimum 1.3934) | strictly greater than 1.0 |
| Q6.1 | zero-injury share of establishments, size band 001-019 | 0.7681 | 0.7066 to 0.8199 |
| Q6.2 | zero-injury share of establishments, size band 020-049 | 0.4874 | 0.4171 to 0.5582 |
| Q6.3 | zero-injury share of establishments, size band 050-099 | 0.2584 | 0.2075 to 0.3167 |
| Q6.4 | zero-injury share of establishments, size band 100-249 | 0.1190 | 0.0947 to 0.1485 |
| Q6.5 | zero-injury share of establishments, size band 1000+ | 0.0946 | 0.0487 to 0.1760 |
| Q6.6 | zero-injury share of establishments, size band 250-499 | 0.0785 | 0.0594 to 0.1031 |
| Q6.7 | zero-injury share of establishments, size band 500-999 | 0.0933 | 0.0533 to 0.1582 |

Q6.x rows are the zero-injury share (establishments with zero recordable cases) per establishment size band, with the band in the quantity name.

Known weakness, stated in advance: Q3 and Q4 have very wide intervals because the hours column contains extreme outliers in 2019 and 2024 (that is the finding of this project), so their intervals are close to uninformative; they are registered anyway so the verdict is not chosen after the fact. Q1, Q2 and Q6.x are the informative tests. The 2025 values will also depend on whether the pipeline's inputs and plausibility screen are unchanged; the evaluation uses the repository pipeline as committed at registration.

## Decision rule for "prediction held"

Fixed now, before any 2025 value is seen:

- A prediction (Q1-Q4, Q6.x) **held** if the observed 2025 value lies inside its 95% interval, endpoints included. Otherwise it **did not hold**.
- Q5 **held** if the observed 2025 ratio is strictly greater than 1.0.
- Observed values come from rerunning the committed pipeline with the 2025 release added; the same table columns are read by `scripts/evaluate_preregistration.py`. Intervals are read from the committed CSV, never recomputed.
- Every quantity is reported, held or not. No interval, model or rule is changed afterwards. If the pipeline cannot produce a quantity for 2025 it is reported as "not evaluable", not dropped.
- Calibration reading: there are 12 scored predictions. If the intervals were correct and independent, the chance of at least 1, 2, 3 or 4 misses would be 46%, 12%, 2.0% and 0.2% (binomial, p = 0.05). Independence is not true here (size bands move together, and Q1 and Q4 share the same filings), so these are rough guides, and three or more misses is read as the method being too narrow, not as noise.

## Frozen code

Predictions were produced by `python3 scripts/preregister_2025.py` (deterministic: no random numbers, no clock; reads only the tables above). SHA-256 of `scripts/preregister_2025.py` at registration:

`2beb4e071a5a9c2f1e598b43b963072e059469e03f87a6bdba64121be95e0c53`

`tests/test_preregistration.py` fails if the script no longer matches this hash, if rerunning it does not reproduce `docs/preregistration_2025_predictions.csv` byte for byte, or if this page's table differs from the committed CSV. `python3 scripts/preregister_2025.py --check` does the byte comparison alone. The CSV also stores each series' nine input values and their hash, so the inputs behind each prediction are visible without rerunning anything.

## After the data arrive

1. Add the 2025 files to `data/raw/` and rerun `python3 scripts/run_analysis.py`, which adds 2025 rows to the tables.
2. Run `python3 scripts/evaluate_preregistration.py`. It exits 2 with "nothing to score" until 2025 rows exist, and otherwise prints one verdict per quantity and the held count.
3. Append the output below under a dated "Results" heading in a separate commit. If the tables gain 2025 rows, `tests/test_preregistration.py` still passes, because predictions are rebuilt from years up to 2024 only.
