# Count models with covariates

This note documents the covariate-adjusted count-model comparison that
replaces the intercept-only comparison in the establishment count-model
section. Everything here is produced by
`src/ehs_osha/count_models_covariates.py` (run as
`python3 -m ehs_osha.count_models_covariates` from `src/`), which writes
`outputs/tables/count_model_covariates.csv`,
`outputs/tables/count_model_covariates_summary.csv`,
`outputs/tables/count_model_covariates_fit_detail.csv` and
`outputs/figures/fig04_count_model_fit.svg`. The older intercept-only tables
(`count_model_comparison.csv`, `count_model_selection_summary.csv`) are kept
so the two can be compared.

## Why the intercept-only comparison was not enough

An intercept-only NB2 can beat an intercept-only Poisson for two different
reasons: the conditional count is genuinely overdispersed, or the
establishments in the group simply have different mean rates (size, sub-industry)
and the model has no way to express that except through the dispersion
parameter. Only the first is "overdispersion" in the sense the paper claimed.
The fix is to put the observable structure into the mean and ask whether
the variance still exceeds the mean afterwards.

## Specification

Mean equation, all four models:

    log E[y_i | x_i] = log(hours_i / 200000) + x_i' beta

- `y_i` is recordable cases for establishment `i` in the 2024 reporting year.
- The log-hours offset has a fixed coefficient of one, so `exp(x_i' beta)` is a
  rate on the TRIR scale (cases per 200,000 hours).
- `x_i` = intercept + establishment size-band dummies (reference: the smallest
  band) + NAICS 4-digit fixed effects within the NAICS 3-digit group being
  fitted (reference: the modal 4-digit code). Within one 3-digit industry the
  3-digit code is constant, so 4-digit dummies are the within-group fixed
  effects. They are dummy-coded, not a random-intercept approximation: each
  fit has between 7 and 16 columns, well within dense NumPy linear algebra.

Variance / zero structure:

| Model   | Extra parameters | Var(y | x)                     |
|---------|------------------|--------------------------------|
| Poisson | none             | m                              |
| NB2     | alpha            | m + alpha m^2                  |
| ZIP     | pi               | Poisson with structural zeros  |
| ZINB    | alpha, pi        | NB2 with structural zeros      |

## Identification of the zero-inflation parameter

`pi` is a single constant per fit; the inflation equation carries no
covariates. That is a deliberate restriction. With covariates in both the
count and inflation equations the two are separated only by functional form
(the log link versus the logit link), and on a panel dominated by small
establishments with low expected counts that separation is weak. A constant
`pi` is identified from the excess of observed zeros over what the
covariate-adjusted count component predicts, is comparable one-for-one with
the intercept-only `pi`, and puts `pi = 0` on the boundary, so the
ZINB-vs-NB2 and ZIP-vs-Poisson likelihood-ratio tests use the 50:50
mixture null (half the naive chi-square tail), exactly as in the
intercept-only module.

Estimation: Poisson by Newton-Raphson with step halving; NB2 by alternating
Newton steps on `beta` at fixed `alpha` and golden-section search on
`log alpha`; ZIP and ZINB by EM over the latent structural-zero indicator
with a weighted Poisson / NB2 M-step. The reported log-likelihood is always
the observed-data likelihood. `converged = False` on a ZINB fit means the EM
stalled with `pi` at its lower bound; in every such case in the table the
ZINB AIC is within about 5.5 points of the NB2 AIC (differences from about
-1.5 to about +5.4), which is the signature of ZINB collapsing to NB2 with
one wasted parameter.

## Selection and sample

Industries: the 30 largest NAICS 3-digit groups with at least 500 screened
establishments in 2024, chosen on size alone. Groups above 20,000
establishments were subsampled to 20,000 with a fixed seed for runtime
(four groups: 238, 445, 423, 623). Rows failing the plausibility screen are
excluded, as everywhere else in the repository.

## What changed and what did not

Read the numbers from `count_model_covariates_summary.csv` and
`count_model_covariates.csv`; the statements below describe those files.

- Overdispersion survives covariate adjustment in every one of the 30
  industries. NB2 beats Poisson with a boundary-corrected p below 0.001 in
  all 30, and the AIC improvement of NB2 over Poisson ranges from about
  1,700 to about 70,000 points. The NB2 dispersion `alpha` after adjustment
  has a median of about 0.79 and a minimum of about 0.16; none is close to
  zero. On this point the original conclusion stands, and now stands on a
  specification that cannot be explained away by size or sub-industry mix.
- Zero inflation does change. Intercept-only, ZINB was best by AIC in
  15 of 30 industries. With covariates, ZINB is best by AIC in 10 of 30 and
  NB2 in 20 of 30 over all fits; one of those 10 (NAICS 531) is an unconverged
  ZINB fit with pi at its lower bound and an AIC only 1.5 below NB2, so over
  converged fits only the split is ZINB 9, NB2 21
  (`n_industries_best_by_aic_converged_only_*` in
  count_model_covariates_summary.csv). The ZINB-vs-NB2 boundary test is
  below 0.01 in 9 industries, all converged; for the 13 unconverged ZINB fits
  the p-value is not interpretable and is NaN in
  `p_boundary_zinb_vs_nb2_converged_only`. In
  the remaining industries `pi` collapses to (near) zero and ZINB adds
  nothing. Part of what looked like excess zeros in the intercept-only fits
  was mean heterogeneity across size bands and 4-digit sub-industries.
- Poisson and ZIP are never selected.

The honest summary of section 6.5 is therefore: overdispersion is
universal across the large industries, and zero inflation beyond NB2 is
present in a minority of them after conditioning on size and sub-industry.

## Limits

- No causal reading. The coefficients on size band and sub-industry are
  descriptive contrasts within a screened administrative panel; they are not
  effects of size on injury risk.
- Screened-panel conditioning. Every fit conditions on passing the
  plausibility screen and on filing with OSHA at all. Excess zeros in
  particular cannot be split between genuinely incident-free operation and
  under-recording; the model measures the excess, not its source.
- Single year, single specification of the inflation equation. Adding
  covariates to the inflation equation is possible in principle but was not
  done for the identification reason above.
- `pi` at the boundary is reported as `converged = False` rather than
  silently rounded to zero.
- Subsampling of the four largest groups affects absolute log-likelihoods
  and AIC differences there, not the sign of the comparisons.

## Which industries are fitted, and which are not

The 30 fitted NAICS-3 groups are the 30 largest with at least 500 screened
establishments in 2024, chosen on size alone. Groups below 500 establishments
and eligible groups beyond the 30th are not fitted, so the 30-of-30 result is
a statement about large industries, not about every industry. The count of
groups present, eligible, fitted and dropped, and the share of establishments,
hours and recordable cases the fitted groups cover, is written by
`python3 -m ehs_osha.count_models_covariates --coverage-only` to
`outputs/tables/count_model_covariates_coverage.csv`; quote that file rather
than treating the fitted set as representative.

As generated: 122 NAICS-3 groups are present in the 2024 screened panel, 71
have at least 500 establishments, 30 are fitted, 41 eligible groups are left
out beyond the top 30, and 51 fall below the floor. The fitted groups hold
78.8 percent of screened establishments, 72.1 percent of hours and 76.0
percent of recordable cases (count_model_covariates_coverage.csv).
