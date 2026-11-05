# Convenience targets. Everything here is a thin wrapper around a script that
# can also be run directly.

PYTHON ?= python3

.PHONY: help data fixture analysis test clean-outputs list-sources ontology health flag-concentration

help:
	@echo "make data      - download the public OSHA ITA files into data/raw"
	@echo "make fixture   - generate the synthetic test fixture"
	@echo "make analysis  - run the full pipeline on the real data"
	@echo "make test      - run the test suite (real-data tests skip if absent)"
	@echo "make list-sources - print the dataset catalog with URLs"
	@echo "make ontology  - build the ontology on the fixture, export to build/ontology"
	@echo "make flag-concentration - rebuild outputs/flag_concentration*.csv, docs/flag_concentration.md and its SVG"
	@echo "make health    - validate lineage, run data expectations, regenerate docs/LINEAGE.md and docs/DATA_HEALTH.md"

data:
	$(PYTHON) scripts/download_data.py

list-sources:
	$(PYTHON) scripts/download_data.py --list

fixture:
	$(PYTHON) synthetic/generate_fixture.py

analysis:
	$(PYTHON) scripts/run_analysis.py

ontology:
	PYTHONPATH=src $(PYTHON) -m ehs_osha.ontology --out build/ontology

health:
	PYTHONPATH=src $(PYTHON) -m ehs_osha.health

flag-concentration:
	$(PYTHON) scripts/build_flag_concentration.py

test:
	cd tests && $(PYTHON) -m unittest discover -s . -p "test_*.py"

clean-outputs:
	rm -rf outputs/tables outputs/figures outputs/summary.json
