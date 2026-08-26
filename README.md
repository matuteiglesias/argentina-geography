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

Wave A1 established a synthetic release surface, `product-fixture-v1`, proving two independent Geography Releases, a many-to-many Relation Release through `spatial-data-foundation`, and a separate policy-bound Crosswalk Release.

```bash
python -m pip install -e ".[dev]"
make check
make test
make product-smoke
```

## First official source product: INDEC 2022 census radios

Wave A2 adds a provider-specific producer for the official national INDEC 2022 census-radio layer. The source is fetched explicitly from INDEC GeoNode or supplied as a local snapshot; ordinary tests never depend on the network.

Because the current GeoNode metadata reports no license, the adopted distribution mode is `official_remote_fetch`: Argentina Geography materializes and verifies a local GeoParquet release but does not redistribute the official geometry.

```bash
make materialize-indec-2022-radio
```

The successful 2026-08-26 national source proof materialized **66,515** unique `cod_indec` radios from a pinned WFS snapshot. `cod_indec` is the authoritative native identity; source `cpr`, `cde`, `cfn` and `cro` remain preserved for audit. The source contains 5 rows using a local three-digit `cde` representation, 3 source-invalid polygons, and 26 documented adjustment radios in Entre Ríos/Misiones. No rows are dropped and no substantive geometry repair is performed.

The release therefore stages as **`PASS_WITH_WARNINGS` / QA `YELLOW`**: 66,512 rows are immediately eligible for `geometry_role=analytical`, while the 3 invalid source polygons remain visible as `geometry_role=source_invalid`. See [`docs/INDEC_2022_RADIO_PRODUCT.md`](docs/INDEC_2022_RADIO_PRODUCT.md) and the pinned [`source-proof evidence`](docs/source-evidence/indec-2022-radio-2026-08-26.md).

## Product boundaries

Argentina Geography publishes artifacts rather than requiring downstream repositories to import its implementation.

- **Geography Release:** one explicit provider/source geography normalized without silently changing its substantive meaning.
- **Relation Release:** geometric facts between two exact geography releases. N:M relationships remain N:M.
- **Crosswalk Release:** an optional interpretation created only when an explicit policy needs one target per source.

`empirical-data-contracts` owns shared provenance/identity envelopes. `spatial-data-foundation` owns provider-neutral spatial mechanics. This repository owns Argentine source knowledge, native identifier semantics, source-specific QA and approved Argentina-specific interpretations.

## Historical executable state: `fixture-v1`

The historical bounded release remains supported as regression evidence. Its normative inputs and decisions are `config/source_registry.json` and `config/reconciliation_policy.json`; it is not suitable for substantive analysis.

Legacy commands remain available:

```bash
make smoke
make release-fixture
```

## Historical product and evidence

The old notebooks intended to generate `radios_IGN_<year>` outputs combining province, department, fraction and radio identifiers/geometries. No such final directories are committed. The historical **52,401** figure is evidenced by the record count in the committed 2010 radio shapefile DBF header, but uniqueness is not independently proven and its lookup CSV count differs. It must not be read as a current-boundary feature count.

Read historical evidence in this order:

1. `docs/GEOGRAPHY_CHARACTERIZATION.md`;
2. `docs/HISTORICAL_GEOGRAPHY_INPUTS.md`;
3. the historical source registry and reconciliation policy;
4. the old fixture manifest and reports.

## Current limitations and stop points

Only synthetic geometry is committed. Real source products are materialized locally from explicit authorities; source distribution rights remain provider-specific. QA warnings may stage when they are explicit and source-faithful, but identity ambiguity, lost units, silent substantive geometry repair or unsupported domain interpretation remain stop conditions.
