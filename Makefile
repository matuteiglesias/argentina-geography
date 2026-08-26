PYTHON ?= python

.PHONY: install check test smoke release-fixture product-smoke product-fixture build materialize-indec-2022-radio materialize-indec-2022-fraction materialize-ceur-2022-radio materialize-indec-ceur-2022-relation materialize-tartagalensis-circuits materialize-electoral-vertical
install:
	$(PYTHON) -m pip install -e ".[dev]"
check:
	$(PYTHON) -m compileall -q src tests
	$(PYTHON) -m json.tool config/source_registry.json >/dev/null
	$(PYTHON) -m json.tool config/reconciliation_policy.json >/dev/null
	$(PYTHON) -m json.tool config/sources/indec_census_2022_radio.json >/dev/null
	$(PYTHON) -m json.tool config/sources/indec_census_2022_fraction.json >/dev/null
	$(PYTHON) -m json.tool config/sources/ceur_census_2022_radio_v2025_1.json >/dev/null
	$(PYTHON) -m json.tool config/sources/tartagalensis_electoral_circuits.json >/dev/null
	$(PYTHON) -m json.tool config/relations/indec_ceur_census_2022_radio.json >/dev/null
	$(PYTHON) -m json.tool config/electoral/electoral_vertical.json >/dev/null
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
materialize-indec-2022-fraction:
	$(PYTHON) -m argentina_geography.sources.indec_2022_fraction materialize --output build/indec-2022-fraction
materialize-ceur-2022-radio:
	$(PYTHON) -m argentina_geography.sources.ceur_2022_v2025_1 materialize --output build/ceur-2022-v2025-1-radio
materialize-indec-ceur-2022-relation: materialize-indec-2022-radio materialize-ceur-2022-radio
	$(PYTHON) -m argentina_geography.relations.indec_ceur_2022 materialize \
		--indec-release build/indec-2022-radio \
		--ceur-release build/ceur-2022-v2025-1-radio \
		--output build/indec-ceur-2022-relation
materialize-tartagalensis-circuits:
	$(PYTHON) -m argentina_geography.sources.tartagalensis_circuits materialize \
		--vintage 2021 \
		--output build/tartagalensis-circuits-2021
	$(PYTHON) -m argentina_geography.sources.tartagalensis_circuits materialize \
		--vintage 2025 \
		--output build/tartagalensis-circuits-2025
	$(PYTHON) -m argentina_geography.sources.tartagalensis_circuits compatibility-evidence \
		--release-2021 build/tartagalensis-circuits-2021 \
		--release-2025 build/tartagalensis-circuits-2025 \
		--output build/tartagalensis-circuit-code-compatibility.json
materialize-electoral-vertical:
	mkdir -p build/indec-2010-source
	$(PYTHON) -m argentina_geography.sources.indec_2010_radio materialize \
		--source-dir build/indec-2010-source \
		--output build/indec-2010-radio
	$(MAKE) materialize-tartagalensis-circuits
	$(PYTHON) -m argentina_geography.electoral.vertical materialize \
		--census-release build/indec-2010-radio \
		--circuit-release build/tartagalensis-circuits-2021 \
		--vintage 2021 \
		--output build/electoral-vertical-2021
	$(PYTHON) -m argentina_geography.electoral.vertical materialize \
		--census-release build/indec-2010-radio \
		--circuit-release build/tartagalensis-circuits-2025 \
		--vintage 2025 \
		--output build/electoral-vertical-2025
build:
	$(PYTHON) -m build
