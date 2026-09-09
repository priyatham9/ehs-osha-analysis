# Contributing

## Running Tests

```bash
cd /path/to/ehs-osha-analysis
python3 -m unittest discover -s tests -p "test_*.py"
```

The real-data regression tests skip automatically when `data/raw` is not populated, so the suite passes on a fresh clone without a network. Every other test runs offline, including the HTTP tests, which use a local server.

## Dependency Policy

This project uses Python 3.9 or later with:
- Standard library only
- pandas 2.3.3
- numpy 2.0.2

No other runtime dependencies. No scipy, no matplotlib, no yaml or any third-party config libraries.

## Numbers in the Repository

Every empirical number in this repository must be produced by a committed script rather than typed by hand. Specifically:

1. All headline figures quoted in README.md are computed by `scripts/run_analysis.py` and transcribed from `outputs/summary.json` or `outputs/tables/*.csv`
2. The regression tests in `tests/test_regression_real_data.py` and `tests/test_readme_consistency.py` assert these values against the generated data
3. No number may be carried over from another source or estimated; all are regenerated on every run
4. The README consistency test parses the figures back out of the README and fails if the prose and generated tables disagree

## Synthetic Data

`synthetic/` contains a generator that produces clearly-labelled fake filings with known ground-truth parameters. Every generated CSV has a sibling `.HEADER.txt` declaring it synthetic, and `GROUND_TRUTH.json` records the parameters.

- Synthetic data is for testing the pipeline without a network and validating estimators against known parameters
- **No number produced from the fixture appears anywhere in the README** and none should be cited
- Fixture runs write to a separate output directory to prevent accidental mixing with real-data outputs

## Random number generation

The synthetic fixture under `synthetic/fixture/` is committed so the test suite runs
offline, and a test asserts it still matches what the generator produces. That only
works if generation is reproducible on any machine.

NumPy's NEP 19 freezes the legacy `np.random.RandomState` stream permanently, but makes
no such guarantee for `np.random.default_rng` / `Generator`: methods such as `gamma`,
`poisson` and `binomial` may draw different values on a different NumPy release. Use
`RandomState` in `synthetic/generate_fixture.py`. Elsewhere, where output is not
committed and compared, `default_rng` is fine.
