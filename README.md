# Geografías censales reconciliadas con IGN

Proceso histórico de preparación geoespacial que vincula radios y fracciones censales de Argentina con referencias administrativas del Instituto Geográfico Nacional (IGN).

> **Estado y autoridad:** productor histórico reutilizable más una release **sintética y acotada** (`fixture-v1`). Ningún artefacto se presenta como límite administrativo oficial o corriente de 2026. El repositorio posee sus transformaciones, no las fuentes de INDEC, IGN o CEUR-CONICET.

## Release soportada: `fixture-v1`

Batch 1 provides one offline, deterministic validation slice—not a national data refresh. It exercises an unambiguous polygon, a polygon crossing two candidates, an unmatched polygon, a repaired self-intersection, a conflicting duplicate identifier, synthetic same-vintage weights, and CRS84 → EPSG:3857 → CRS84 conversion.

Committed artifacts are under `releases/fixture-v1/`:

- `geography.geojson`: normalized features in OGC:CRS84, longitude/latitude axis order;
- `coverage.json`: counts, shares, province-level feature and synthetic-weight coverage;
- `exceptions.json`: unmatched, multi-match, repair and duplicate detail;
- `manifest.json`: source/policy/environment lineage plus byte and normalized-semantic SHA-256 checksums.

The normative inputs and decisions are `config/source_registry.json` and `config/reconciliation_policy.json`. This fixture is not suitable for substantive analysis.

## Reproducible environment and commands

The supported environment is the pinned Python 3.11 Conda/Mamba definition:

```bash
mamba env create -f environment.yml
conda activate censo-geography-release
make install
make check
make test
make smoke
make release-fixture
```

`make check`, `make test`, and `make smoke` use only committed bounded inputs and require no network. `make release-fixture` recreates the committed release and verifies a second build byte-for-byte. Installation may require access to the configured package channel; no manual GDAL wheels or notebook runtime installs are supported.

## Historical product and evidence

The historical notebooks intend to generate `radios_IGN_<year>` outputs combining province, department, fraction and radio identifiers/geometries. No such final directories are committed. The historical **52,401** figure is evidenced by the record count in the committed 2010 radio shapefile’s DBF header, but uniqueness is not independently proven and its lookup CSV count differs. It must not be read as a current-boundary feature count.

Read in this order before using historical material:

1. `docs/GEOGRAPHY_CHARACTERIZATION.md` for notebooks, sources, CRS evidence, counts and unsafe assumptions;
2. `docs/HISTORICAL_GEOGRAPHY_INPUTS.md` for adopt/regression/method-only classifications;
3. the source registry and reconciliation policy;
4. the artifact manifest and reports.

## Fixture reconciliation rules

All IDs are digit strings with fixed zero-padding. Candidate geometry is already EPSG:3857; census fixture geometry is converted from CRS84 with `always_xy`. Invalid polygons are repaired with `make_valid` and reported. Duplicate-ID occurrences are all excluded. Positive-area intersections below tolerance are ignored. A unique largest overlap is assigned only when it covers at least 50% of the input; a tolerance tie is ambiguous. Unmatched units remain in the output with a null assignment. No buffer, centroid, nearest-neighbour or manual override is used. Geometry is returned to CRS84, precision-normalized, oriented and stably ordered before deterministic JSON serialization.

These rules validate the harness; adopting them for historical/live geography requires human approval and a new methodology version. Coverage separates mutually exclusive terminal dispositions from orthogonal repair/multi-match flags. Repair records expose before/after types, parts and areas plus tolerance outcomes; an exceeded tolerance stops the release.

## Limitations and stop points

Exact historical IGN vintage, checksum, published CRS and redistribution rights remain unresolved. CEUR-CONICET snapshot provenance and redistribution terms also need validation. Population coverage is deliberately null; the fixture’s `weight` is synthetic and explicitly not population. No historical override is approved.

Stop for review before selecting a real source vintage, changing a consumed identifier, accepting a substantive tie-break, dropping a real unmatched unit, claiming population coverage, replacing a snapshot, or labeling any release current/official.
