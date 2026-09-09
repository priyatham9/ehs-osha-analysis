# Changelog

All notable changes to this project are documented here. The format follows
Keep a Changelog and this project uses semantic versioning.

## [0.1.0] - 2026-09-09

### Added
- Reproducible pipeline over public OSHA Injury Tracking Application Form 300A establishment filings from 2016-2024 (2.8M filings)
- Plausibility screen identifying implausible filings by hours per employee, missing values, and case count consistency
- Comprehensive analysis showing screened aggregate TRIR stable at 3.98 across 9 years while unscreened varies 1.39x to 249x depending on year composition
- Count model comparison (Poisson, NB2, ZIP, ZINB) demonstrating overdispersion is universal and zero-inflation optional across 30 largest industries
- Peer-group analysis by NAICS 3-digit and establishment size band with percentile stability measured by Spearman rank correlation and absolute relative change
- Sensitivity grid demonstrating screened rate insensitive to plausibility threshold choice while flagged share moves by design
