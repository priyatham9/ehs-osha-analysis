# Do implausible-hours filings cluster in the same establishments, or hit at random?

## The question

The plausibility screen in `ehs_osha.quality` flags a small share of OSHA
establishment-year filings for an implausible `hours_per_employee` value (plus
a few other internal-consistency checks), and the resulting TRIR correction
swings from 1.39x to 249x depending on the year. That work does not say why
filings fail the screen. Two explanations compete:

- **Typo hypothesis.** Implausible hours are independent keying errors.
  Knowing an establishment was flagged in year *t* says nothing about year
  *t+1*.
- **System hypothesis.** Certain establishments (or their filing software, or
  a shared corporate parent) systematically misreport hours in the wrong
  unit. Flags cluster in the same establishments across years.

These predict opposite patterns and are worth telling apart: if the system
hypothesis holds, flagged data can potentially be repaired per establishment
rather than only screened out, and the 2019 anomaly (99.6% of reported hours
sit in flagged filings that year) has a candidate mechanism instead of being
an unexplained outlier year.

## Method

1. Load and harmonise all nine published years (2016-2024) with
   `ehs_osha.load.load_ita_300a` and screen every filing with
   `ehs_osha.quality.apply_screen` at its default `PlausibilityConfig` -
   both reused, not reimplemented.
2. Pivot to an establishment x year matrix of the `implausible` flag, keyed on
   `establishment_id` (`ehs_osha.panel.build_flag_panel`).
3. For every pair of consecutive years, restrict to establishments that filed
   in both years and build the 2x2 table of (flagged in year *t-1*) x
   (flagged in year *t*). Compute `P(flagged in t | flagged in t-1)`,
   `P(flagged in t | not flagged in t-1)`, the odds ratio, and Cohen's kappa
   (`kappa = (p_observed - p_expected) / (1 - p_expected)`, implemented
   directly in numpy - no scipy/statsmodels dependency is available or used).
4. **Permutation test (the decisive step).** Under the typo hypothesis, which
   establishment is flagged in a given year is exchangeable with any other
   establishment that filed that year. So: hold the number of flagged filings
   per year fixed, and reassign that many flags uniformly at random among the
   establishments that filed that year - independently, year by year. Recompute
   the pooled (all year-pairs combined) persistence odds ratio on the permuted
   data. Repeat 200 times with a fixed seed (`20260909`) and compare the
   observed odds ratio to that null distribution.
5. Repeat the same co-flagging check specifically around 2019, against the
   adjacent years' baseline flag rates.
6. Check `establishment_id` itself for stability before trusting any of the
   above (see Limitations).

All numbers below come from `outputs/tables/panel_*.csv`, produced by
`python3 -m ehs_osha.panel` (equivalently, `ehs_osha.panel.run`). Nothing here
is simulated data presented as a finding - the permutation *null* is
simulated by construction, but it is compared against the observed real-data
statistic, not substituted for it.

## Coverage (`outputs/tables/panel_coverage.csv`)

Across 2016-2024: **1,238,236** distinct `establishment_id` values,
**614,928** (49.7%) appear in 2 or more years, and **16,307** (1.3%) appear in
all 9 years. No filing has a missing `establishment_id`.

## Transition matrix and persistence (`outputs/tables/panel_transitions.csv`)

Pooled across all eight consecutive year-pairs, restricted each time to
establishments present in both years of the pair (n = 1,436,479
establishment-year-pairs):

| | flagged in year *t* | not flagged in year *t* |
|---|---:|---:|
| **flagged in year *t-1*** | 5,776 | 15,467 |
| **not flagged in year *t-1*** | 13,394 | 1,401,842 |

- `P(flagged in t \| flagged in t-1)` = **27.2%**
- `P(flagged in t \| not flagged in t-1)` = **0.95%**
- Odds ratio = **39.1**
- Cohen's kappa = **0.276**

The pattern holds in every one of the eight individual year-pairs (odds ratios
range 24.7-63.1; see the full table), not just in the pooled figure.

An establishment flagged one year is roughly 29x more likely (by relative
odds) to be flagged the next year than an establishment that was not. Kappa of
0.28 is "fair" agreement by the conventional Landis-Koch bands - real but far
from the near-1.0 that would say the same establishments are flagged every
single year. Both readings point the same direction: more persistence than
chance, but plenty of one-off flags too.

## Permutation test (`outputs/tables/panel_permutation.csv`)

Observed pooled odds ratio: **39.08**.
200 permutations (seed 20260909), each holding every year's flag count fixed
and reassigning it uniformly at random among that year's filers:

- Permutation mean odds ratio: **1.012**
- Permutation 95% interval: **[0.924, 1.092]**
- Fraction of permutations at or above the observed value: **0/200 (0.0%)**

Under the typo hypothesis, the observed odds ratio should land inside that
permutation distribution - it should look like an odds ratio of about 1,
because there is no mechanism to make this year's flag predict next year's
flag once the per-year flag counts are respected. It does not. The
permutation null is tightly centered at 1.0, and the observed value (39.1) is
nowhere near it - not "somewhat elevated," but a different order of magnitude
than anything chance reassignment produced in 200 tries.

## 2019 (`outputs/tables/panel_2019.csv`)

2019 had 290,475 filers, of which 4,650 (1.6%) were flagged - a small share of
*filings*, consistent with the earlier finding that a small share of filings
carries almost all of 2019's reported hours. The question here is whether that
1.6% is a fresh, unrelated set of establishments each year (broad and shallow)
or the same repeat offenders (narrow and deep):

- Of the 1,654 establishments flagged in 2019 that also filed in 2018,
  **29.3%** were also flagged in 2018 - against a 2018 baseline flag rate of
  1.6%. **Enrichment: 18.8x.**
- Of the 2,079 establishments flagged in 2019 that also filed in 2020,
  **31.3%** were also flagged in 2020 - against a 2020 baseline flag rate of
  1.9%. **Enrichment: 16.4x.**

2019 is not a broad, shallow, one-year event. Its flagged establishments are
markedly more likely than a random filer to also be flagged in the adjacent
years, at a scale consistent with the pooled persistence result above. This
does not explain why 2019 specifically produced a larger *hours* share among
flagged filings than other years (that is a magnitude question the panel does
not address, only the identity-of-who-flags question) - but it rules out "a
fresh crop of typos happened to appear in 2019" as the explanation.

## Which hypothesis does the evidence support

**The system hypothesis.** All three lines of evidence - the transition
matrix, the kappa, and the permutation test - point the same direction, and
the permutation test in particular gives a clean answer: an odds ratio of
39.1 against a null distribution centered at 1.0 with a 95% range of
[0.92, 1.09] is not a borderline result. If bad filings were independent
year-to-year keying errors, this analysis would not distinguish 39.1 from 1;
it distinguishes them easily. The typo hypothesis is not supported as the
dominant mechanism.

This is a qualified result, not an absolute one: kappa of 0.28 says most
flagged filings in any given year are *not* matched by a flag the year
before or after (`P(flagged in t | flagged in t-1)` is 27%, not close to
100%). So both mechanisms likely coexist - a persistent subset of
establishments (or their software, or their parent company) that misreports
repeatedly, plus a residual of one-off errors that behave more like the typo
hypothesis. The evidence says clustering is real and far larger than chance,
not that every flagged filing has a systemic cause.

## Limitations

**`establishment_id` stability was checked, not assumed.** Every filing has a
non-missing `establishment_id` (0 missing across 2.80M deduplicated rows), and
`state` is highly stable under a given ID (only 4,010 of 1,238,236 IDs, 0.3%,
show more than one state across years) - consistent with the ID tracking a
physical location. But `ein` is not: **313,527 of 1,238,236 establishment IDs
(25.3%) appear with more than one distinct EIN across years**, and
**108,855 (8.8%) appear with more than one company name**. This is a genuine
finding, not a data-quality footnote to wave away: it means `establishment_id`
in this dataset tracks something closer to a physical facility than a fixed
legal filer, and that ownership changes, EIN corrections, or filer-side EIN
formatting drift are common. That is consistent with the system hypothesis
being partly about the site or its equipment/software rather than only the
corporate entity that files under it, but it also means a persistence result
keyed on `establishment_id` should not be read as "the same company misreports
repeatedly" - only "the same site, or something tied to it, does." No
substitute key (`ein`, `company_name`+`state`) was used in its place; this
analysis is keyed on `establishment_id` throughout, as instructed, and this
section reports what checking it actually found.

**The plausibility screen is a threshold rule**, not a ground-truth label for
"this filing has an error." An establishment that genuinely runs an unusual
schedule near the 120/4,500 hours-per-employee bounds could be flagged
consistently across years for a real (not erroneous) reason, which would
also show up as persistence. The panel result cannot distinguish "same
establishment keeps making the same data-entry mistake" from "same
establishment has a genuinely unusual, correctly-reported hours profile."
Both produce the same statistical signature.

**Association, not causation.** The permutation test rules out pure chance as
the explanation for the observed clustering. It does not identify a
mechanism - it cannot say whether the cause is filing software, a shared
third-party payroll/EHS vendor, a specific corporate parent, or a genuinely
unusual but correctly reported establishment. Establishing that would require
data this analysis does not have (e.g., filing-software identifiers or
corporate-family linkage beyond EIN).

**Coverage is uneven.** Only 1.3% of establishments appear in all 9 years;
most (50.3%) appear in exactly one year and so contribute nothing to any
transition pair. The transition and permutation results are therefore about
the subset of establishments that file repeatedly, not about the full
population of one-time filers.
