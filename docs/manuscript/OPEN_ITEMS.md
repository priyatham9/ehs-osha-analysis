# Manuscript open items (TODO list)

Status of `MANUSCRIPT.md`: unsubmitted draft. Nothing here has been sent anywhere.

## Unverified references (left out of the manuscript)

The authoring sandbox could reach only GitHub hosts; doi.org, Crossref, arXiv, PubMed, OpenAlex, Wikipedia and osha.gov all refused the connection, so none of the following could be checked and none is cited. Each is **unverified**: confirm title, authors, venue and DOI by hand before adding it.

- Datasheets for Datasets (Gebru et al., 2021): named in `DATASHEET.md`; cite for the datasheet structure.
- Self and Liang (1987), asymptotic distribution of likelihood-ratio statistics when parameters lie on the boundary: cite for the 50:50 mixture null in the ZINB-versus-NB2 test.
- Lambert (1992), zero-inflated Poisson regression: cite for ZIP.
- Cameron and Trivedi, regression analysis of count data: cite for NB2 and count-model practice.
- Akaike (1974), information criterion: cite for AIC.
- Garwood (1936), exact Poisson intervals: cite for the detectability planner (not used in the manuscript).
- Simonsohn, Simmons and Nelson (2020), specification curve analysis: cite for Section 3.6.
- Nosek et al. (2018), the preregistration revolution: cite for Section 3.8.
- OSHA Injury Tracking Application data page and summary data dictionary (`https://www.osha.gov/itadata`): the data source; host not reachable from the sandbox, so the URL appears in the text as a data location, not as a verified reference.
- 29 CFR 1904 Subpart E (who must submit): the README states it; the text of the regulation was not retrieved.
- The author's earlier repository ehs-benchmarks: its README returned HTTP 404 from the raw-content host, so it is not cited.

## Open items before any submission decision

- Add a related-work paragraph once the references above are verified.
- Decide whether to score the 2025 predictions (`scripts/evaluate_preregistration.py`) before submission; they are unscored in this draft.
- Independent replication of the pipeline has not been done.
