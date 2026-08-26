# Argentina Geography

**Argentina Geography** is evolving into a reusable infrastructure for versioned Argentine geography authorities, normalized releases and cross-geography relations.

The repository began as `censo-ign-geografias`, a historical Censo↔IGN preparation project. The old notebooks and `fixture-v1` remain preserved as evidence/regression material, but the active architecture is now broader: explicit provider geographies, reproducible source snapshots, relation products and policy-separated crosswalks.

Development authority:

1. [`docs/ARGENTINA_GEOGRAPHY_ARCHITECTURE.md`](docs/ARGENTINA_GEOGRAPHY_ARCHITECTURE.md)
2. [`docs/SOURCE_AUTHORITY_MATRIX.md`](docs/SOURCE_AUTHORITY_MATRIX.md)
3. [`docs/PRODUCT_MODEL.md`](docs/PRODUCT_MODEL.md)
4. [`docs/BUILD_PACK_ARG_GEO_V1.md`](docs/BUILD_PACK_ARG_GEO_V1.md)
5. [`docs/AGENT_EXECUTION_PACK.md`](docs/AGENT_EXECUTION_PACK.md)
6. [`AGENTS.md`](AGENTS.md)

The target layer sits between domain-agnostic `spatial-data-foundation` and simple downstream applications. INDEC, CEUR-CONICET, IGN, INDEC EPH geography and Tartagalensis circuit geography are treated as explicit, versioned authorities rather than inputs to one manufactured "true" national geometry.

## Current executable product kernel

Wave A1 adds a second synthetic release surface, `product-fixture-v1`, whose purpose is to prove the target architecture before any live source is adopted.

It builds two independent synthetic **Geography Releases**, a many-to-many **Relation Release** using `spatial-data-foundation.geography.relate_areal_objects`, and a separate policy-bound **Crosswalk Release**. It also emits truthful geography/relation catalogs containing only those products actually built.

```bash
python -m pip install -e ".[dev]"
make check
make test
make product-smoke
```

To materialize the new fixture bundle locally:

```bash
make product-fixture
```

The bundle is written under `releases/product-fixture-v1/` and contains:

```text
geographies/
  synthetic-census/
  synthetic-admin/
relations/
  census-admin/
crosswalks/
  census-admin-largest-overlap/
geography_catalog.parquet
relation_catalog.parquet
manifest.json
```

The Geography and Relation products use GeoParquet/Parquet; every sub-bundle carries manifests, QA and checksums. Verification works from the detached artifact tree and does not require sibling repository paths.

The fixture deliberately preserves source-specific behavior locally: duplicate census IDs are excluded under the fixture policy, one invalid polygon is explicitly repaired and audited, and the largest-overlap winner rule is applied only when constructing the separate crosswalk. None of those fixture policies become generic `spatial-data-foundation` behavior.

## Historical executable state: `fixture-v1`

The historical bounded release remains supported as regression evidence. It exercises an unambiguous polygon, a polygon crossing two candidates, an unmatched polygon, a repaired self-intersection, a conflicting duplicate identifier, synthetic same-vintage weights, and CRS84 → EPSG:3857 → CRS84 conversion.

Committed artifacts are under `releases/fixture-v1/`:

- `geography.geojson`: normalized features in OGC:CRS84;
- `coverage.json`: counts, shares and synthetic fixture coverage;
- `exceptions.json`: unmatched, multi-match, repair and duplicate detail;
- `manifest.json`: source/policy/environment lineage plus hashes.

The normative inputs and decisions for this historical fixture are `config/source_registry.json` and `config/reconciliation_policy.json`. It is not suitable for substantive analysis.

Legacy commands remain available:

```bash
make smoke
make release-fixture
```

## Product boundaries

Argentina Geography publishes artifacts rather than requiring downstream repositories to import its implementation.

- **Geography Release:** one explicit provider/source geography normalized without silently changing its substantive meaning.
- **Relation Release:** geometric facts between two exact geography releases. N:M relationships remain N:M.
- **Crosswalk Release:** an optional interpretation created only when an explicit policy needs one target per source.

`empirical-data-contracts` owns shared provenance/identity envelopes. `spatial-data-foundation` owns provider-neutral spatial mechanics. This repository owns Argentine source knowledge, native identifier semantics, source-specific QA and approved Argentina-specific interpretations.

## Historical product and evidence

The old notebooks intended to generate `radios_IGN_<year>` outputs combining province, department, fraction and radio identifiers/geometries. No such final directories are committed. The historical **52,401** figure is evidenced by the record count in the committed 2010 radio shapefile DBF header, but uniqueness is not independently proven and its lookup CSV count differs. It must not be read as a current-boundary feature count.

Read historical evidence in this order:

1. `docs/GEOGRAPHY_CHARACTERIZATION.md`;
2. `docs/HISTORICAL_GEOGRAPHY_INPUTS.md`;
3. the historical source registry and reconciliation policy;
4. the old fixture manifest and reports.

## Current limitations and stop points

No substantive national Argentina Geography release is produced yet. The current source registry predates the refreshed source-authority program. Later waves must re-characterize INDEC 2010/2022, CEUR V2025-1, IGN, official EPH geography and pinned Tartagalensis circuit snapshots before adoption.

Stop for review before changing a consumed identifier, silently repairing real geometry, selecting a substantive tie-break, dropping a real unmatched unit, making a population claim, replacing a provider's source identity or asserting redistribution rights not supported by source evidence.
