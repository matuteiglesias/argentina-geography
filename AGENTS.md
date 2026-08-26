# Agent operating contract

This repository is evolving from **censo-ign-geografias** into **Argentina Geography**: a reusable producer of versioned Argentine geography artifacts and cross-geography relations.

## Read first

Before changing production code, read in this order:

1. `docs/ARGENTINA_GEOGRAPHY_ARCHITECTURE.md`
2. `docs/SOURCE_AUTHORITY_MATRIX.md`
3. `docs/PRODUCT_MODEL.md`
4. `docs/BUILD_PACK_ARG_GEO_V1.md`
5. the wave-specific brief in `docs/AGENT_EXECUTION_PACK.md`
6. relevant ADRs under `docs/adr/`
7. current source registry/policy and the current executable code

Re-check current `main` and the current upstream source before implementing a wave. Historical notebooks are evidence, never silent authority.

## Product intent

Make authoritative and high-quality Argentine geographies discoverable, reproducible, interoperable and easy to consume by researchers and downstream applications.

The stable public interface is **versioned artifacts plus manifests/catalogs**, not imports from sibling repositories.

## Layer boundaries

`empirical-data-contracts` owns shared identity, provenance, coverage and run envelopes.

`spatial-data-foundation` owns domain-agnostic spatial mechanics: CRS discipline, geometry roles, point membership, areal relations, provider-neutral materialization mechanics and generic presentation helpers.

This repository owns Argentine source knowledge: INDEC, CEUR-CONICET, IGN, EPH geography and Tartagalensis source adapters; native identifier semantics; source-specific QA; normalized geography releases; cross-source relation products; and only those adjudication policies that are explicitly approved here.

Downstream applications own their scientific/domain semantics. In particular, this repository does not own poverty methodology, income modeling, electoral results, sampling policy or statistical estimands.

## Invariants

- There is no single canonical or "true" Argentina geography.
- Preserve provider, source release/snapshot, vintage, native IDs and source limitations.
- Never replace a provider geography with another provider's geometry while retaining the first provider's identity.
- Source geography releases remain semantically faithful to their source.
- Relation facts are distinct from crosswalk/adjudication policy.
- Ambiguity, gaps, multiple matches and source absence are data; do not silently coerce them into assignments.
- No silent `make_valid`, buffering, snapping, nearest-neighbour assignment, centroid assignment or threshold policy.
- Analytical geometry and display geometry remain separate.
- GeoParquet is the preferred canonical analytical geography format; Parquet is preferred for tabular relations/crosswalks; GeoJSON is a derivative/interchange format unless a source is natively GeoJSON.
- All real source bytes used in a release are snapshot-addressed and checksum-verifiable.
- Consumers receive artifacts; they do not need this repository checkout or a sibling path.
- Do not infer data redistribution rights. Distribution mode is explicit per source.
- Do not add provider-specific code to `spatial-data-foundation`.
- A helper may be promoted to `spatial-data-foundation` only under `docs/TOOL_PROMOTION_POLICY.md`.

## Autonomous execution rules

For each wave:

- branch from fresh `main`;
- inspect the exact current source and consumer contracts named by the wave;
- keep one bounded mission per PR;
- state input authority, output artifact, invariants, non-goals, tests and stop conditions in the PR;
- preserve old evidence until a successor product is proven;
- use synthetic fixtures for CI; do not make ordinary tests depend on the network;
- make source acquisition explicit and separately invokable;
- fail closed on source/schema/identity changes;
- attach quantitative QA evidence when real geography is materialized;
- do not modify downstream repositories unless the wave explicitly calls for a consumer proof and the user has authorized it.

Stop for human review when source meaning, licensing, native identity, substantive geometry repair, adjudication policy or claimed compatibility is ambiguous.

## Definition of done

A wave is done only when its artifact/contract is independently verifiable, its tests are green, its limitations are recorded and the next consumer does not need undocumented local knowledge to use it.
