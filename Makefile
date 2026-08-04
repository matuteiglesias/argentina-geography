PYTHON ?= python

.PHONY: install check test smoke release-fixture
install:
	$(PYTHON) -m pip install -r requirements.lock
	$(PYTHON) -m pip install --no-deps -e .
check:
	$(PYTHON) -m compileall -q src tests
	$(PYTHON) -m json.tool config/source_registry.json >/dev/null
	$(PYTHON) -m json.tool config/reconciliation_policy.json >/dev/null
	$(PYTHON) -m censo_geo.release --check

test:
	$(PYTHON) -m pytest -q
smoke:
	$(PYTHON) -m censo_geo.release --output $$(mktemp -d)/fixture-v1 --verify
release-fixture:
	$(PYTHON) -m censo_geo.release --output releases/fixture-v1 --verify
