# Argentina Geography — transition seed

> **Repository transition:** this repository began as `censo-ign-geografias`, a historical Censo↔IGN preparation project. It is now the technical seed for **Argentina Geography**, a broader reusable infrastructure for versioned Argentine geography authorities, normalized releases and cross-geography relations. The repository name/package will change in a later implementation wave; current executable authority remains the bounded historical fixture described below.

The development authority for the new program starts here:

1. [`docs/ARGENTINA_GEOGRAPHY_ARCHITECTURE.md`](docs/ARGENTINA_GEOGRAPHY_ARCHITECTURE.md)
2. [`docs/SOURCE_AUTHORITY_MATRIX.md`](docs/SOURCE_AUTHORITY_MATRIX.md)
3. [`docs/PRODUCT_MODEL.md`](docs/PRODUCT_MODEL.md)
4. [`docs/BUILD_PACK_ARG_GEO_V1.md`](docs/BUILD_PACK_ARG_GEO_V1.md)
5. [`docs/AGENT_EXECUTION_PACK.md`](docs/AGENT_EXECUTION_PACK.md)
6. [`AGENTS.md`](AGENTS.md)

The target layer sits between domain-agnostic `spatial-data-foundation` and simple downstream applications. It will treat INDEC, CEUR-CONICET, IGN, INDEC EPH geography and Tartagalensis circuit geography as explicit, versioned authorities rather than manufacturing one canonical national geometry.

---

# Geografías censales reconciliadas con IGN — current executable state

Proceso histórico de preparación geoespacial que vincula radios y fracciones censales de Argentina con referencias administrativas del Instituto Geográfico Nacional (IGN).

> **Estado y autoridad actual:** productor histórico reutilizable más una release **sintética y acotada** (`fixture-v1`). Ningún artefacto actual se presenta como límite administrativo oficial o corriente de 2026. El repositorio posee sus transformaciones, no las fuentes de INDEC, IGN o CEUR-CONICET.

## Release soportada: `fixture-v1`

Batch 1 provides one offline, deterministic validation slice—not a national data refresh. It exercises an unambiguous polygon, a polygon crossing two candidates, an unmatched polygon, a repaired self-intersection, a conflicting duplicate identifier, synthetic same-vintage weights, and CRS84 → EPSG:3857 → CRS84 conversion.

Committed artifacts are under `releases/fixture-v1/`:

- `geography.geojson`: normalized features in OGC:CRS84, longitude/latitude axis order;
- `coverage.json`: counts, shares, province-level feature and synthetic-weight coverage;
- `exceptions.json`: unmatched, multi-match, repair and duplicate detail;
- `manifest.json`: source/policy/environment lineage plus byte and normalized-semantic SHA-256 checksums.

The normative inputs and decisions for the current fixture are `config/source_registry.json` and `config/reconciliation_policy.json`. This fixture is not suitable for substantive analysis.

## Reproducible environment and commands

The current supported environment is the pinned Python 3.11 Conda/Mamba definition:

```bash
mamba env create -f environment.yml
conda activate censo-geography-release
make install
make check
make test
make smoke
make release-fixture
```

`make check`, `make test`, and `make smoke` use only committed bounded inputs and require no network. `make release-fixture` recreates the committed release and verifies a second build byte-for-byte.

## Historical product and evidence

The historical notebooks intend to generate `radios_IGN_<year>` outputs combining province, department, fraction and radio identifiers/geometries. No such final directories are committed. The historical **52,401** figure is evidenced by the record count in the committed 2010 radio shapefile’s DBF header, but uniqueness is not independently proven and its lookup CSV count differs. It must not be read as a current-boundary feature count.

Read historical evidence in this order:

1. `docs/GEOGRAPHY_CHARACTERIZATION.md` for notebooks, sources, CRS evidence, counts and unsafe assumptions;
2. `docs/HISTORICAL_GEOGRAPHY_INPUTS.md` for adopt/regression/method-only classifications;
3. the source registry and reconciliation policy;
4. the artifact manifest and reports.

## Fixture reconciliation rules

The existing fixture uses fixed-width digit IDs, explicit duplicate exclusion, audited `make_valid`, positive-area intersections, a minimum winner share and tie policy. These rules validate the old bounded harness; they are **not** automatically the methodology of future real Argentina Geography releases.

The new architecture explicitly separates source Geography Releases, geometric Relation Releases and policy-dependent Crosswalk Releases. Future waves will progressively move generic intersection mechanics to released `spatial-data-foundation` APIs while keeping source/domain policy here.

## Current limitations and stop points

The present source registry predates the new authority investigation and should not be read as a current source landscape. New waves will re-characterize INDEC 2010/2022, CEUR V2025-1, IGN, official EPH geography and pinned Tartagalensis circuit snapshots before producing substantive releases.

Stop for review before changing a consumed identifier, silently repairing real geometry, selecting a substantive tie-break, dropping a real unmatched unit, making a population claim, replacing a provider's source identity or asserting redistribution rights not supported by source evidence.
