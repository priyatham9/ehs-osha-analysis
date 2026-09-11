# Datasheet for ehs-osha-analysis

This datasheet documents the screened dataset derived from the OSHA Injury Tracking Application Form 300A filings, following the structure of Gebru et al. (2021).

## Motivation

**For what purpose was the dataset created?** To quantify the effect of implausible hours-per-employee values on aggregate injury rates computed from the public OSHA ITA Form 300A establishment filings, 2016-2024. The analysis screens filings for internal plausibility (hours between 120 and 4,500 per employee per year), isolates the filings that fail the screen, and measures what the aggregate TRIR would be if those filings were excluded. [README.md]

**Who created the dataset and on behalf of which entity?** The dataset was created by processing publicly available OSHA filings downloaded from https://www.osha.gov/itadata. No dataset has been created independent of OSHA; this work only screens, partitions, and re-aggregates OSHA's own published files. [data/raw/manifest.json; README.md]

**Who funded the creation of the dataset?** Not recorded. [README.md, docs/PANEL.md, synthetic/README.md, outputs/summary.json]

## Composition

**What do the instances in this dataset represent?** Establishment-years: a single OSHA ITA Form 300A filing from one establishment in one calendar year. Each row carries establishment identifiers (establishment_id, state, EIN), company name, NAICS industry code, the number of employees on average during the year, total hours worked, recordable injury counts by type (OSHA 300 line e, h, j, k), days of lost work, and derived fields (hours per employee, recordable-case totals, injury rate). [README.md; src/ehs_osha/schema.py]

**How many instances are there in total?** 2,801,064 filings after deduplication (2,805,767 rows raw, 4,703 duplicates dropped). [outputs/summary.json: quality.pooled.rows_after_dedup]

**Does the dataset contain all possible instances, or a sample?** All deduplicated rows from nine published years (CY 2016-2024) of Form 300A filings available at the time of analysis. The universe of establishments that filed in those years is not known, so it cannot be said whether non-filers are excluded; only that every file published by OSHA at https://www.osha.gov/itadata was included. [README.md]

**What data does each instance consist of?** For each establishment-year:

- Identifiers: establishment_id, state, EIN, company name, 6-digit industry description
- Exposure: average number of employees, total hours worked, hours per employee
- Outcomes: total recordable cases, deaths, days-away-from-work cases, job-transfer cases, other recordable cases, days of lost work
- Derived: recordable-case rate per 200,000 hours (TRIR), DART (days-away + job-transfer cases), LTIR (lost-time cases), severity (days per 200,000 hours)

Additional field: implausible flag (Boolean), indicating whether the filing fails any of six internal-consistency checks described in the Preprocessing section below. [src/ehs_osha/schema.py; README.md]

**Is there a label or target associated with each instance?** Yes. The binary `implausible` flag marks filings that fail a plausibility screen. The flag is deterministic, not assigned by human annotators, and reflects whether the filing violates one or more of six threshold or consistency rules. [README.md; ehs_osha.quality]

**Is any information missing from individual instances?** All required columns are present in every row (no missing establishment_id, no missing hours_worked when employees>0). Missing values do occur in optional columns (e.g., some filings carry no information in fields that are not part of the 300A). These are not dropped. The `implausible` flag explicitly flags rows where required fields are missing (e.g., employees=0 or missing). [outputs/summary.json: load_report.files_read; tests/test_schema_and_load.py]

**Are there any known errors, sources of noise, or redundancies in the dataset?** Yes, several:

1. establishment_id is not stable across years. 313,527 of 1,238,236 IDs (25.3%) appear with more than one distinct EIN across years, and 108,855 (8.8%) with more than one company name. The ID is keyed to a physical facility rather than a fixed legal entity. [docs/PANEL.md: Limitations]

2. The `size_field` is not comparable across years; the employee-band definitions changed between publication sets. Comparisons across the 2016-2022 vs. 2023+ splits should use the derived hours_per_employee rather than the size_field. [test_regression_real_data.py: test_size_field_is_not_comparable_across_years]

3. The `no_injury` checkbox on some filings contradicts the recorded injury counts (e.g., checkbox says no injuries but counts > 0). This is recorded as a flag but not used to drop the row. [README.md; ehs_osha.quality.flag_no_injury_contradiction]

4. Five of the nine years (CY2019, CY2024, and the 2023+ bundle) hold a disproportionate share of hours in a small number of implausible filings. Whether these represent data-entry errors, non-standard reporting practices, or genuine reporting artifacts is not determined by this analysis. [README.md; docs/PANEL.md]

## Collection process

**How was the data associated with each instance acquired?** The nine datasets were downloaded from the OSHA public data portal (https://www.osha.gov/itadata) between 2026-09-04T04:42:25 and 2026-09-04T04:42:29 UTC. All nine files match OSHA's published cryptographic digests. OSHA itself collects the data via mandatory reporting (29 CFR 1904) from establishments with 10+ employees (or 5+ in specified high-hazard industries) in specified industry groups. [data/raw/manifest.json]

**Was the data directly observable (as opposed to derived, computed, or estimated)?** Mostly yes, with caveats. The days-away and days-of-lost-work figures are derived by OSHA from the Form 300 at submission time; the Form 300A itself (and the ITA dataset) carry the OSHA-computed totals, not the raw case-by-case line items. The hours_per_employee field used in the screen is derived from total hours and average employees in this analysis, not carried as a direct field in the OSHA data. [README.md; src/ehs_osha/schema.py]

**What mechanisms or procedures were used to collect the data from the source?** Direct HTTP download of ZIP files from osha.gov URLs. Each file is downloaded, its SHA256 digest is verified against OSHA's published digest, and the CSV inside is extracted and loaded. No data transformation is applied during collection. [scripts/download_data.py; data/raw/manifest.json]

**If the data is a sample, what is the sampling procedure?** Not a sample. All nine published annual datasets are included. Within each dataset, no sampling was applied; all rows are retained (subject only to deduplication on a canonical row key). [README.md]

**Who was involved in the data collection process, and how were they compensated?** Not recorded. The data originates from OSHA's mandatory reporting system; compensation of individual filers is not recorded in the published dataset. [README.md]

**Over what time period(s) was the data collected?** OSHA Form 300A filings for calendar years 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, and 2024. The data files themselves were published on osha.gov and downloaded on 2026-09-04. [data/raw/manifest.json]

**Were there any conflicts of interest in the data collection process?** Not recorded. [README.md; docs/PANEL.md; synthetic/README.md]

## Preprocessing/cleaning/labeling

**Was any preprocessing applied to the data?** Yes, minimal but explicit:

1. Deduplication: 4,703 exact-row duplicates (2,805,767 raw - 2,801,064 after dedup) were dropped, keeping the latest occurrence when a row appears multiple times. [outputs/summary.json: load_report.duplicate_rows_dropped]

2. Column selection: The `street_address` column is dropped from all nine years to reduce size. [outputs/summary.json: load_report.columns_dropped]

3. Encoding: Most years use UTF-8; CY 2018 requires cp1252 decoding. The loader detects and applies the appropriate encoding. [outputs/summary.json: load_report.encodings_used]

4. Derived fields: hours_per_employee, total_recordables (sum of deaths, DAFW, JTR, other), and injury rates (TRIR, DART, LTIR, severity per 200,000 hours) are computed from the source columns. [src/ehs_osha/schema.py]

**Was the "raw" data saved in addition to the processed data?** Yes. The raw ZIP files are preserved in data/raw/; the loader can re-extract and re-process them. However, only the processed CSV tables and derived metrics are committed to the repository. [.gitignore; README.md]

**Is the software that generated the cleaned data available?** Yes. The loader is in src/ehs_osha/load.py; the screening logic is in src/ehs_osha/quality.py. Both are Python 3.9 standard library only (no external build requirements). [src/ehs_osha/]

**Any other preprocessing, cleaning, or labeling of the data?** The `implausible` flag is computed deterministically from six rules (not by hand-labeling). These rules are configurable via a PlausibilityConfig object; the default config applies min/max thresholds on hours_per_employee (120-4,500) plus five boolean checks. See README.md for the prevalence of each flag. [ehs_osha.quality.PlausibilityConfig; README.md]

## Uses

**Has the dataset been used for any tasks already? If so, which tasks and by whom?** Yes. The screened dataset (filings flagged as plausible, n=2,743,207) is used to compute aggregate injury rates (TRIR, DART, LTIR, severity) by year and by NAICS 3-digit industry group. Count models (Poisson, negative binomial, zero-inflated Poisson, zero-inflated NB) are fitted to recordable-case distributions within each of the 30 largest industries. Year-over-year stability of establishment percentile ranks within peer groups (same size band and industry) is computed to show whether the ranking changes when implausible filings are excluded. [README.md; outputs/summary.json: metrics, count_models, stability]

**What tasks would the dataset be appropriate for?** 

- Epidemiologic questions about the prevalence and types of recordable injuries in the US occupational workforce, stratified by industry, establishment size, and year (conditional on the caveats under Limitations).
- Investigations of establishment-level or industry-level safety performance and trends (conditional on robust handling of hours-denominator implausibilities).
- Methodological studies of count-model selection and zero-inflation in overdispersed outcomes.

**What tasks would the dataset NOT be appropriate for?** 

- Any analysis that treats the unscreened dataset (including implausible filings) as valid. The unscreened aggregate TRIR can swing by an order of magnitude depending on whether that year's data happen to contain one or two extreme outliers. Any usage of unscreened rates must acknowledge this sensitivity.
- Cross-establishment comparisons or rankings of safety performance based on raw TRIR, without adjustment for hours-denominator implausibilities, because a single establishment's filing error can dominate that establishment's apparent rate.
- Inferences about incident causation or prevention, because the dataset records injury counts only, not incident types, root causes, circumstances, or outcomes beyond days of lost work.
- Applications that require consistent establishment identifiers or company relationships across years, because establishment_id is not legally stable (25% carry more than one EIN across years).
- Analyses assuming zero-inflation as the dominant feature of the outcome distribution; the evidence (from fitting 30 industries) shows overdispersion is universal but structural zero-inflation is optional and small where present. [README.md; outputs/summary.json: count_models.selection_by_aic]

## Distribution

**Will the dataset be distributed to third parties outside of the entity on behalf of which the dataset was created?** Yes. The repository is public on GitHub (https://github.com/priyatham9/ehs-osha-analysis); the screened tables are committed and available in outputs/tables/*.csv. [README.md; .github/]

**How will the dataset be distributed?** Via GitHub repository, committed CSV files, and committed summary.json. All outputs are regenerable from the source files via make analysis. [Makefile; README.md]

**When will/did the dataset be distributed?** The analysis is complete and the repository is public as of 2026-09-09 (per SITEMAP.md). [.git history]

**Will the dataset be distributed under a license? If so, which?** Yes, under the MIT License. [LICENSE]

**Have any third parties imposed IP-based or other restrictions on the data associated with instances?** No. The underlying OSHA data are in the public domain (federal government work). No restrictions beyond the license apply. [LICENSE; README.md]

**Do any institutional review boards or similar ethics review bodies need to be consulted?** Not recorded. The data are public filings without personal identifiers (no names of injured workers, no personal health information beyond aggregate case counts and days of lost work). No IRB approval was sought or is believed necessary. [README.md; data schema]

## Maintenance

**Who is responsible for the continued maintenance and update of the dataset?** The owner of the repository (priyatham9) is responsible for maintenance. Updates depend on OSHA's continued publication of the Form 300A filings. [README.md; GitHub repository]

**How will updates and corrections be managed?** Updates will be pulled via make data (which downloads the latest published files from osha.gov and updates the manifest) and re-run via make analysis (which regenerates all outputs). Corrections to the analysis logic (e.g., to the screening rules or model fits) will be made to the source code in src/ehs_osha/ and propagated to outputs via make analysis. Both are tracked in git. [Makefile; src/; scripts/]

**If others want to extend, augment, or build on this dataset, how should they communicate with you?** GitHub issues or pull requests on the repository. Contact via email (priyatham9@gmail.com) is an alternative for work not suited to a public pull request. [README.md; repository]

**How long will the dataset be maintained?** Not formally specified. OSHA's ITA portal has been stable since at least 2016; barring removal by OSHA, new years will be added as published. The repository will be maintained at minimum through publication of the associated paper. [README.md; SITEMAP.md]

**Will older versions of the dataset continue to be supported and hosted?** Yes. Git history is preserved; all prior commits are available. Outputs committed at each analysis run (tables, figures, summary.json) are stored in the repository and are not deleted when regenerated. [.git history; outputs/]

**Are there any known limitations, risks, or biases that should be considered by users?** Yes:

1. **Scope:** The dataset covers only establishments filing with OSHA (roughly 130,000 per year nationally, per OSHA's public counts). Establishments below the reporting threshold (typically <10 employees), non-covered industries, and non-compliant filers are absent. [README.md; docs/PANEL.md]

2. **Denominator stability:** Approximately 50% of establishment_id values appear in only one year; only 1.3% appear in all nine years. Year-to-year comparisons must account for entry and exit. [docs/PANEL.md: Coverage]

3. **Assignment ambiguity:** The plausibility screen cannot distinguish a genuine but unusual reporting practice (e.g., a very low-hours summer-employment employer) from a data-entry error. Both look the same in aggregate statistics. The screen is a threshold rule, not a ground-truth label. [docs/PANEL.md: Limitations]

4. **Cause-and-effect inferences are not supported.** The dataset records injury counts only, not circumstances. No causal claim about what leads to injury can be made from this dataset alone. [README.md]

5. **The paper's main result (39.1x odds of persistence in flags across years) comes from the screened panel (docs/PANEL.md), not from aggregate rates. It concerns the identity of flagged establishments, not the validity of the screen itself.** [docs/PANEL.md]
