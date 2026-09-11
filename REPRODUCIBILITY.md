# Reproducibility

This document records the inputs, exact commands, measured runtimes, and verifiable outputs needed to reproduce the analysis in this repository.

## 1. Source data

Nine public OSHA Injury Tracking Application (ITA) Form 300A summary datasets, 2016-2024, downloaded from https://www.osha.gov/itadata.

| Filename | Bytes | SHA256 |
|---|---:|---|
| ITA_Data_CY_2016.zip | 12,106,381 | 9f41c720fb02f78788f1090e5fc885fdb09343fc349c4ae4c80cc9165d83742f |
| ITA_Data_CY_2017.zip | 14,682,864 | 354fb246be90d6bac3d4a7c94e44f90d40f1d3ff73f911d37691ae98a87de0fb |
| ITA_Data_CY_2018.zip | 16,970,794 | 0bd2e8475a5766baba8883a1258a92168c43c5ff551c853b1992641814b4dc2f |
| ITA_Data_CY_2019.zip | 18,898,257 | bf93ea7312bfe34d903c1272f15c785a61b8c8bbc6df6e09f0d3fe372205ac6e |
| ITA_Data_CY_2020.zip | 19,480,392 | eb704f2cc343adc7710b48204015ac11c3018fae684f44747158d731e713899b |
| ITA_Data_CY_2021.zip | 19,431,073 | 5a11abc7c085f07f08f130c25bf78c85581b2379fb8b514f728bfcdf5d61b4a3 |
| ITA_Data_CY_2022.zip | 19,730,409 | e396af8038d40d74b96ebb6ee9b561bbcb8907ee66adff089402a676c919e6ef |
| ITA_300A_Summary_Data_2023_through_12-31-2024.zip | 24,143,043 | 25da8bc426db219a7a5fe872e73830afebdfac87c460f8cf6561658e7103b487 |
| ITA_300A_Summary_Data_2024_through_12-31-2025.zip | 23,855,931 | 4cbce7ea32dd4060f442a528670936e552d1b731925f320d9d25a168f9b60b1d |

All nine files are recorded in `data/raw/manifest.json` with their download URLs and retrieval timestamps. No file in that listing has a `digest_matches_catalog` value other than `true`.

## 2. Environment

```
Python 3.9.6
numpy 2.0.2
pandas 2.3.3
```

The `.github/workflows/tests.yml` CI matrix runs on Python 3.9 and 3.12, installing via `python -m pip install --upgrade pip numpy pandas` (no pinned versions in the workflow; minimum supported versions in `requirements.txt` are numpy>=1.20 and pandas>=1.3).

## 3. Commands and measured runtimes

Run all three commands from the repository root:

```
cd "/Users/priyathamchimmani/Claude Code/Research/repos/ehs-osha-analysis"
```

### 3.1. Prepare data

```
make data
```

Downloads the nine public ITA zip files listed above into `data/raw/`. **Requires internet access to osha.gov.** Measured runtime: skipped (network dependent; files already present in test environment).

### 3.2. Run the full pipeline

```
make analysis
```

Reads the nine files from `data/raw/`, screens them for plausibility, computes aggregate metrics by year, fits count models to 30 largest NAICS 3-digit industry groups, produces six SVG figures and 15 CSV tables, and writes `outputs/summary.json`. **Requires `data/raw/` to be populated.**

Measured runtime on this machine (macOS, single-threaded): **93.4 seconds**

### 3.3. Run the test suite

```
make test
```

Equivalent to:

```
cd tests && python3 -m unittest discover -s . -p "test_*.py"
```

Includes real-data regression tests that skip silently if `data/raw/` is empty. Test count: 175 tests total (8 test modules). Real-data tests account for the majority of runtime. Measured runtime on this machine when `data/raw/` is populated: **165 seconds**.

When `data/raw/` is empty, run the synthetic-fixture-only tests:

```
python3 -m unittest discover -s tests -p "test_*.py" -v
```

Measured runtime: **3.5 seconds** for 10 fixture-based tests.

## 4. Verifiable outputs

These eight headline figures appear in `outputs/summary.json` and can be checked by a reader against a fresh pipeline run:

| Metric | JSON path | Committed value |
|---|---|---|
| Pooled TRIR (screened) | `quality.pooled.aggregate_trir_screened` | 3.983078949653959 |
| Pooled filings | `quality.pooled.n_filings` | 2801064 |
| Pooled implausible count | `quality.pooled.n_implausible` | 57857 |
| Ratio screened to unscreened | `quality.pooled.ratio_screened_to_unscreened` | 29.71079556436282 |
| Median establishment TRIR (screened) | `quality.pooled.median_establishment_trir_screened` | 2.468815770795144 |
| Industries fitted (count models) | `count_models.n_industries_fitted` | 30 |
| Industries best by NB2 AIC | `count_models.selection_by_aic.[1].n_industries_best_by_aic` | 15 |
| Industries best by ZINB AIC | `count_models.selection_by_aic.[3].n_industries_best_by_aic` | 15 |

All values were generated at UTC 2026-09-04T05:31:12 and committed to the repository.

## 5. Synthetic fixture pipeline

To verify the pipeline works end-to-end without downloading real data, run:

```
python3 synthetic/generate_fixture.py
python3 -m unittest tests.test_pipeline_on_fixture -v
```

The first command regenerates four years of synthetic establishment filings (2021-2024, 3,000 per year) with ground-truth parameters recorded in `synthetic/fixture/GROUND_TRUTH.json`. The second command asserts:

- The pipeline executes without error
- Count models recover generator parameters
- Outputs are reproducible across runs
- Screened rates match the known corruption rate
- Output tables are valid and non-empty

Measured end-to-end runtime: fixture generation 0.3 seconds + pipeline 3.5 seconds on fixture tests.

## 6. CI verification

The GitHub Actions workflow `.github/workflows/tests.yml` runs the test suite on every push to `main` on Python 3.9 and 3.12. A new job `fixture-pipeline` has been added to the workflow that:

1. Generates the synthetic fixture
2. Runs the pipeline on the fixture
3. Asserts the pipeline exits with status 0
4. Verifies `outputs/summary.json` exists and is valid JSON

This job runs in under 10 seconds and requires no data downloads, making it suitable for fast CI feedback.
