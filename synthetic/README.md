# Synthetic fixture

**Everything in `fixture/` is fabricated. It is not OSHA data, it does not
describe any real establishment, industry or regulator, and no statistic
computed from it may be cited as an empirical finding.**

No number in the top-level `README.md` comes from this fixture. The headline
results there are computed from the real OSHA ITA files by
`scripts/run_analysis.py`, and the regression tests that guard them
(`tests/test_regression_real_data.py`) skip entirely when the real files are
absent rather than falling back to anything here.

## Why it exists

Two reasons, both narrow:

1. **Exercising the pipeline without a network.** The fixture lets the full
   load → screen → peer-group → count-model → stability path run in a test,
   so the plumbing is covered on a fresh clone with no downloads.
2. **Checking the estimators against a known answer.** The count models in
   `src/ehs_osha/countmodels.py` are hand-written maximum-likelihood fits with
   no SciPy to lean on. The only honest way to test them is to generate data
   from parameters chosen in advance and confirm the fitted values come back.
   `GROUND_TRUTH.json` records those parameters;
   `tests/test_pipeline_on_fixture.py` asserts recovery.

That second use is the point. A recovery test on synthetic data says the
optimiser works. It says nothing whatsoever about workplace safety.

## What the generator produces

`generate_fixture.py` writes four years (2021-2024) of 3,000 filings each,
matching the real 2023+ Form 300A column layout so the loader's harmonisation
code is genuinely exercised.

Recordable counts are drawn from a zero-inflated negative binomial with an
exposure offset:

| Parameter | Value | Meaning |
|---|---|---|
| `mu` | 3.2 | rate per 200,000 hours |
| `alpha` | 1.4 | NB2 dispersion |
| `pi` | 0.18 | structural-zero probability |
| `implausible_share` | 0.02 | fraction given corrupted hours |
| `n_per_year` | 3,000 | filings per year |
| `seed` | 12345 | fixed, so output is byte-reproducible |

A 2% slice is deliberately corrupted with impossible hours values so the
plausibility screen has something to find. The generator is seeded, so
regenerating gives identical files.

Note that the generator's `pi = 0.18` is a *choice*, not a measurement. Real
OSHA data does not behave this way: fitted on the 30 largest real industries,
zero-inflation collapses to zero in 14 of them and never exceeds 0.069 in the
rest. The fixture is deliberately more zero-inflated than reality so that the
ZINB-versus-NB2 selection logic is actually put under load by the test.

## Labelling

Every generated CSV has a sibling `.HEADER.txt` carrying an explicit
synthetic-data declaration, and the fabricated values are self-identifying in
the rows themselves (`SYNTHETIC SITE 00000`, `SYNTHETIC COMPANY 00000`,
`SYNTHETIC INDUSTRY`, state `ZZ`, ZIP `00000`). The declaration string is also
stored in `GROUND_TRUTH.json`.

The header is a sidecar rather than a comment line inside the CSV because the
loader must read these files with exactly the same code path it uses for the
real ones; a comment line would mean the fixture was testing a different reader.

## Regenerating

```bash
python3 synthetic/generate_fixture.py
```

Fixture pipeline runs write to their own output directory and never overwrite
`outputs/`.
