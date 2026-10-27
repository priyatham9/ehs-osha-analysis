# Datasheet for the ehs-osha-analysis analytic panel

Structure follows Gebru et al., "Datasheets for Datasets" (2021). Every statement below is checked against a file in this repository; the source file is named in brackets. Where the repository does not record an answer the entry says **unknown**. The column-level companion is [docs/data_dictionary.csv](docs/data_dictionary.csv) (table, column, type, units, source, derivation, known issues), and `tests/test_data_dictionary.py` fails if a committed table gains a column that the dictionary does not document or if the counts quoted here drift from the committed tables.

## What "the dataset" is

Two layers, and only the second is committed:

1. **The analytic frame** (not committed): the 2016-2024 OSHA Injury Tracking Application (ITA) Form 300A establishment filings, harmonised across years, deduplicated, with derived fields and plausibility flags. It is rebuilt in memory by `make data && make analysis` and is gitignored with the raw files [`.gitignore`; README.md "Data provenance and licensing"].
2. **The committed tables** (30 CSV files in `outputs/tables/`, plus `outputs/summary.json`): aggregates computed from the frame. No row of the committed tables is a single filing except `quality_top50_implausible_hours.csv` (50 filings, identified by `establishment_id` only) [docs/LINEAGE.md].

The data dictionary documents both layers: rows with table `analytic_frame` describe the in-memory frame, all other rows describe a committed CSV.

## Motivation

**For what purpose was the dataset created?** To measure how much implausible hours-worked values distort aggregate injury rates computed from the public Form 300A filings, and to provide a screened basis for peer benchmarks and count-model comparisons [README.md].

**Who created the dataset, and on behalf of whom?** Priyatham Chimmani, as an independent project; the repository does not record an employer or sponsoring institution [CITATION.cff].

**Who funded it?** Unknown. The repository records no funding source.

## Composition

**What do the instances represent?** In the frame, one instance is one establishment-year filing (one Form 300A for one `establishment_id` and one reporting year). In the committed tables, an instance is a stratum (year, NAICS group, size band, model fit, and so on); each table's grain is given in the dictionary.

**How many instances are there?** After deduplication, 2,801,064 filings; the raw files hold 2,805,767 rows, so 4,703 were dropped [outputs/summary.json: `load_report`]. The default plausibility screen flags 57,857 filings (2.07%) and leaves 2,743,207 screened-in filings [outputs/tables/quality_overall.csv; metrics_pooled.csv]. They cover 1,238,236 distinct `establishment_id` values [outputs/tables/panel_coverage.csv].

| Year | Filings | Flagged |
|---|---:|---:|
| 2016 | 214,977 | 4,946 |
| 2017 | 259,757 | 4,323 |
| 2018 | 286,884 | 4,467 |
| 2019 | 290,475 | 4,650 |
| 2020 | 293,385 | 5,593 |
| 2021 | 315,936 | 8,217 |
| 2022 | 346,799 | 6,993 |
| 2023 | 394,231 | 9,235 |
| 2024 | 398,620 | 9,433 |

[outputs/tables/quality_by_year.csv]

**Is it a sample or the full set?** It uses every row of the nine published files that the repository's catalog lists for 2016-2024; no sampling is applied except the capped random subsample inside the count-model fits (`n` in the model tables). Whether the published files contain every establishment that was required to file is **unknown** from the repository. The 2024 reporting year comes from a file named `ITA_300A_Summary_Data_2024_through_12-31-2025_v2`; whether it is final for 2024 is **unknown** here [src/ehs_osha/catalog.py].

**What data does each instance consist of?** Frame columns are listed one by one in the dictionary: identifiers (`id`, `establishment_id`, `ein`, names, city, state, ZIP), industry (`naics_code`, `naics_year`, `industry_description`), size (`annual_average_employees`, OSHA `size` code), exposure (`total_hours_worked`), Form 300A case and day counts (columns G to L plus injury and illness type counts), and derived fields (`recordable_cases`, `hours_per_employee`, `trir`, NAICS prefixes, six flags, `implausible`, `size_band`, `peer_group`) [src/ehs_osha/schema.py; load.py; quality.py; peers.py].

**Is there a label or target?** The `implausible` flag is a deterministic output of the screen, not a human label. By default it is the OR of five flags: missing hours, missing employees, negative counts, hours per employee above 4,500, and hours per employee below 120. A sixth flag (the `no_injuries_illnesses` checkbox contradicting the case counts) is computed and reported but does not feed `implausible` unless `treat_contradiction_as_implausible` is set [src/ehs_osha/quality.py].

**Is any information missing?** Yes. `naics_year` exists only in the 2023 and later files. Counts and hours can be unparsable; the loader turns these into missing values and the screen counts them (9,897 filings with missing or non-positive hours, 10,322 with employees below 1) [src/ehs_osha/load.py; outputs/tables/quality_flag_prevalence.csv]. The `street_address` column is dropped on load [outputs/summary.json: `load_report.columns_dropped`].

**Are there errors, noise or redundancies?** Yes, documented and measured:

- Hours are free text. One 2019 filing reports about 1.68e13 hours for 7 employees, and the single largest filing holds 88.8% of all reported hours; flagged filings hold 96.7% of hours but 1.4% of cases [outputs/tables/quality_top50_implausible_hours.csv; quality_hours_concentration.csv; quality_overall.csv].
- `establishment_id` is not a stable entity key: 313,527 ids (25.3%) carry more than one EIN across years, 108,855 (8.8%) more than one company name, 4,010 more than one state [outputs/tables/panel_coverage.csv; docs/PANEL_AUDIT.md].
- The OSHA `size` code is not comparable across years (code 2 was split into 21 and 22 with the 2023 collection), so size bands are built from `annual_average_employees` [src/ehs_osha/schema.py].
- 301 filings have a `no_injuries_illnesses` checkbox that contradicts their case counts [outputs/tables/quality_flag_prevalence.csv].
- NAICS vintage (2012, 2017 or 2022) varies by file and is not harmonised [src/ehs_osha/naics.py].

**Does it rely on external resources?** Yes: OSHA's published files at https://www.osha.gov/itadata, which can change or disappear. Archival copies are not kept in this repository; the nine SHA256 digests are recorded so a re-download can be checked [REPRODUCIBILITY.md].

**Confidential or sensitive data? Individuals?** The frame holds company names, establishment names, cities, states and ZIP codes of employers, plus employer identification numbers; there are no worker-level records, only per-establishment counts. The committed tables contain no names, only `establishment_id` in one 50-row table. Whether any employer-identifying field is sensitive under a given policy is **unknown** here; the raw files are public OSHA releases.

## Collection process

**How was the data acquired?** Downloaded from OSHA by `scripts/download_data.py` using the catalog in `src/ehs_osha/catalog.py`; REPRODUCIBILITY.md records file names, byte sizes and SHA256 digests for the nine archives. The download manifest (`data/raw/manifest.json`) is created locally and is not committed, so retrieval timestamps cannot be re-verified from the repository. The committed `outputs/summary.json` was generated at 2026-09-04T05:31:12+00:00.

**Who collected the original data and how?** OSHA collected the filings through its Injury Tracking Application; the details of the reporting obligation and OSHA's own validation are **unknown** from the repository beyond the field definitions linked from `src/ehs_osha/catalog.py` (OSHA's summary data dictionary and ITA data users guide).

**Over what time frame?** Reporting years 2016 to 2024 [outputs/summary.json: `years_present`].

**Ethical review?** None recorded.

## Preprocessing/cleaning/labeling

- **Column handling:** names are lowercased and stripped, columns are selected by name (order differs between 2016-2022 and 2023+ files), `street_address` is dropped, numeric columns are coerced with failures becoming missing values [src/ehs_osha/schema.py; load.py].
- **Encoding:** the 2018 file is read as cp1252, the others as UTF-8 [outputs/summary.json: `load_report.encodings_used`].
- **Deduplication:** one row is kept per (`establishment_id`, `year_filing_for`), the one with the largest `id`; amended submissions are the intended case. This removed 4,703 rows. It is a key-based rule, not an exact-row match [src/ehs_osha/load.py `deduplicate`].
- **Derived fields:** `recordable_cases` = deaths + days-away + job-transfer/restriction + other recordable cases; `hours_per_employee`; per-filing `trir` and `dart_rate`; NAICS 2-, 3- and 4-digit prefixes; `size_band` from employee count [src/ehs_osha/load.py; peers.py].
- **Screen:** thresholds 120 and 4,500 hours per employee are configuration, not truth. The 25-cell sensitivity grid moves the flagged share from 1.79% to 4.49% while the screened aggregate TRIR stays between 3.963 and 3.993 [outputs/tables/threshold_robustness_summary.csv].
- **Raw data saved?** Not in the repository (gitignored). Digests are recorded for re-download checks.
- **Software available?** Yes, `src/ehs_osha/`, runs on Python 3.9 and 3.12 with numpy and pandas [README.md; .github/workflows/tests.yml].

## Uses

**Existing uses:** aggregate TRIR, DART, LTIR and severity with and without the screen (29.7x pooled correction, 0.134 to 3.983); peer percentile tables by NAICS 3-digit and size band; intercept-only and covariate-adjusted count-model comparison across 30 industries; flag-persistence panel (pooled odds ratio 39.1); detectability and threshold-robustness views; a dated pre-registration of 2025 predictions [README.md; docs/].

**Appropriate uses:** studying the sensitivity of reported injury rates to the hours denominator; methodological work on count models for establishment-level injury counts; benchmarking cells that meet the 30-filing floor, with the caveats in the dictionary.

**Uses to avoid:**

- Treating unscreened aggregates as population rates (the unscreened pooled TRIR is 0.134 against 3.983 screened).
- Ranking individual establishments by raw TRIR; small sites report zero cases in most filings (75.1% in the 001-019 band) [outputs/tables/size_band_effects.csv].
- Following a company over time through `establishment_id` (see the EIN drift above).
- Causal claims: the data hold counts and days, not circumstances.
- Inferring the national workforce: coverage of non-filers is **unknown**.
- Reading the screen as a fraud detector or as ground truth about which entry is wrong [src/ehs_osha/quality.py].

## Distribution

**Distributed to third parties?** The repository is public on GitHub (https://github.com/priyatham9/ehs-osha-analysis) and the committed tables are readable there [CITATION.cff]. The raw OSHA files and the filing-level frame are not redistributed.

**Licence and restrictions:** the code and committed tables are under the MIT licence [LICENSE]. The source is a US federal agency release; the README notes that works of the US government are generally not subject to US copyright (17 U.S.C. 105) while agency marks and any third-party material may be restricted [README.md "Data provenance and licensing"]. Whether any further terms apply to OSHA's files is **unknown** beyond that note.

**DOI or archive:** none yet. `.zenodo.json` and `codemeta.json` are prepared for archiving, and no release or DOI exists [CHANGELOG.md; CITATION.cff].

## Maintenance

**Who maintains it?** The repository owner, priyatham9 [CITATION.cff]. Issues and pull requests on GitHub are the stated route for corrections; a contact address is in `CITATION.cff` and `SECURITY.md`.

**Updates:** a new OSHA release is added by updating the catalog, rerunning `make data && make analysis`, and committing regenerated tables; tests and the data-health checks (`make health`, 268 expectations per README.md) fail on drift [README.md; Makefile]. A pre-registration fixes predictions for the 2025 release before it is loaded [docs/PREREGISTRATION_2025.md]. Whether OSHA will keep the files at their current URLs is **unknown**.

**Versioning:** git history; the package version in `CITATION.cff` is 0.1.0. Older table versions are recoverable from git, not shipped separately.

**Obsolescence plan:** none recorded; no end-of-support date is stated.

## Known limitations of this datasheet

- Retrieval timestamps and file digests beyond those in REPRODUCIBILITY.md cannot be checked from the repository because the manifest is not committed.
- Meanings of OSHA codes such as `establishment_type` are not documented in the repository and are marked unknown in the dictionary; the injury and illness type counts (`total_injuries` and the five illness columns) are carried but unused, and their definitions are not verified here.
- The dictionary describes columns as they are written to the committed files; most integer-valued columns are stored with a `.0` suffix, which the dictionary notes.
