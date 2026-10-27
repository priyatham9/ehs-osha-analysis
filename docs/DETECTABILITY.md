# Rate detectability: how many site-years does a TRIR need?

Method note. Code: `src/ehs_osha/detectability.py`, `scripts/run_detectability.py`.
Output: `outputs/tables/detectability_by_size_band.csv`. Tests: `tests/test_detectability.py`.

## Question

A total recordable incident rate is `200000 * cases / hours`. For a single
establishment-year the case count is small, so the rate is imprecise, and two
rates can only be told apart with enough exposure. This note computes, for each
establishment size band in the committed `outputs/tables/size_band_effects.csv`
(plausible filings, 2016-2024 pooled), how much exposure that takes.

## Method

1. Cases over a fixed exposure are modelled as Poisson with mean
   `rate * hours / 200000`.
2. Interval for a rate: the exact (Garwood) 95% interval for a Poisson mean,
   found by solving the two tail equations, then scaled by `200000 / hours`.
   Checked in the tests against standard published limits (0 cases: upper
   3.689; 1 case: 0.0253 to 5.572; 10 cases: 4.795 to 18.390).
3. "Precise enough": the smallest case count whose interval has upper/lower
   limit ratio of at most 2. That count is 35.
4. Comparing two rates over equal hours: exact conditional test (given the total
   count, one arm's count is Binomial(n, 1/2) under equal rates; two-sided exact
   p-value, alpha 0.05). Power is summed exactly over the total count. The hours
   per arm for 80% power are found by stepping up 1% at a time from below the
   answer, so they are accurate to about 1% and exact power is not assumed
   monotone. A simulation check is in the tests.
5. Per-band inputs come only from the committed table. Mean hours per filing is
   implied: `aggregate_trir = 200000 * sum(cases) / sum(hours)`, so mean hours =
   `mean_recordables * 200000 / aggregate_trir`. A "site-year" below is one
   filing of that mean size, at the band's own aggregate TRIR.

## Results

| Size band | Filings | Mean hours per filing | Aggregate TRIR | TRIR upper bound if zero cases | Site-years for upper/lower <= 2 | Power, one site-year each, 2x difference | Site-years per arm, 80% power, 2x | 1.5x | 1.25x |
|---|---|---|---|---|---|---|---|---|---|
| 001-019 | 535,187 | 15,710 | 4.94 | 46.96 | 90.2 | 0.000 | 64.6 | 211.2 | 752.9 |
| 020-049 | 884,997 | 54,663 | 4.58 | 13.50 | 28.0 | 0.014 | 20.0 | 65.4 | 233.3 |
| 050-099 | 553,610 | 122,733 | 4.98 | 6.01 | 11.5 | 0.094 | 8.2 | 26.8 | 95.6 |
| 100-249 | 493,919 | 261,048 | 4.71 | 2.83 | 5.7 | 0.225 | 4.1 | 13.3 | 47.5 |
| 250-499 | 170,749 | 595,345 | 4.13 | 1.24 | 2.8 | 0.465 | 2.0 | 6.7 | 23.8 |
| 500-999 | 61,329 | 1,209,901 | 3.37 | 0.61 | 1.7 | 0.712 | 1.2 | 4.0 | 14.3 |
| 1000+ | 43,416 | 4,598,278 | 3.14 | 0.16 | 0.5 | 0.998 | 0.3 | 1.1 | 4.0 |

In the six bands below 1000 employees (2,699,791 of 2,743,207 filings, 98.4%),
a site of mean size needs more than one year of its own data to pin its rate to
within a factor of 2, and one site-year per side gives less than 80% power to
detect even a doubling of the rate. A site of 1-19 employees that reports zero
cases cannot rule out a TRIR of 46.96 (exact 95% upper limit), roughly ten times
the band's aggregate rate of 4.94. Detecting a 25% difference at 80% power takes
752.9 site-years per arm in the smallest band.

## Limits

- Poisson is a best case. The same table shows variance-to-mean ratios from 3.4
  (1-19) to 241.4 (1000+) for establishment case counts, far above the Poisson
  value of 1, so real detectability is worse than reported here.
- Band means stand in for establishments. Hours are skewed, so the typical site
  is smaller than the mean and the mean-size result flatters small sites.
- Filings are establishment-years and a site appears in several years; the
  counts are filings, not distinct establishments.
- This is a planning calculation, not a test applied to any real pair of sites.
