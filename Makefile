# Convenience targets. Everything here is a thin wrapper around a script that
# can also be run directly.

PYTHON ?= python3

.PHONY: help data fixture analysis test clean-outputs list-sources

help:
	@echo "make data      - download the public OSHA ITA files into data/raw"
	@echo "make fixture   - generate the synthetic test fixture"
	@echo "make analysis  - run the full pipeline on the real data"
	@echo "make test      - run the test suite (real-data tests skip if absent)"
	@echo "make list-sources - print the dataset catalog with URLs"

data:
	$(PYTHON) scripts/download_data.py

list-sources:
	$(PYTHON) scripts/download_data.py --list

fixture:
	$(PYTHON) synthetic/generate_fixture.py

analysis:
	$(PYTHON) scripts/run_analysis.py

test:
	cd tests && $(PYTHON) -m unittest discover -s . -p "test_*.py"

clean-outputs:
	rm -rf outputs/tables outputs/figures outputs/summary.json
