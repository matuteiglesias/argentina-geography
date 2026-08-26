PYTHON ?= python

.PHONY: install check test smoke release-fixture product-smoke product-fixture build materialize-indec-2022-radio
install:
	$(PYTHON) -m pip install -e ".[dev]"
check:
	$(PYTHON) -m compileall -q src tests
	$(PYTHON) -m json.tool config/source_registry.json >/dev/null
	$(PYTHON) -m json.tool config/reconciliation_policy.json >/dev/null
	$(PYTHON) -m json.tool config/sources/indec_census_2022_radio.json >/dev/null
	$(PYTHON) -m censo_geo.release --check
	$(PYTHON) -m argentina_geography.fixture --check
	$(PYTHON) -m ruff check src tests

test:
	$(PYTHON) -m pytest -q
smoke:
	$(PYTHON) -m censo_geo.release --output $$(mktemp -d)/fixture-v1 --verify
product-smoke:
	$(PYTHON) -m argentina_geography.fixture --output $$(mktemp -d)/product-fixture-v1 --verify
release-fixture:
	$(PYTHON) -m censo_geo.release --output releases/fixture-v1 --verify
product-fixture:
	$(PYTHON) -m argentina_geography.fixture --output releases/product-fixture-v1 --verify
materialize-indec-2022-radio:
	$(PYTHON) -m argentina_geography.sources.indec_2022_radio materialize --output build/indec-2022-radio
build:
	$(PYTHON) -m build
