# Build Pack ARG-GEO v1

Purpose: evolve the current repository into a public, reusable Argentina geography interoperability layer through bounded, reviewable waves.

The pack is ordered by architectural dependency, not by enthusiasm for a particular dataset.

## Global completion target

The program is substantially complete when:

- INDEC Census 2010/2022 geographies exist as products where source snapshots are established;
- CEUR 2010/2022 V2025-1 geographies exist as products;
- at least one pinned IGN administrative geography exists;
- official INDEC EPH geography exists as a product;
- Tartagalensis 2021/2025 circuit geographies exist as products;
- geography and relation catalogs discover released artifacts;
- a Census↔Census relation exists;
- a Census↔electoral relation exists;
- a Census↔administrative relation exists;
- `samplerCensoARG`, `income-modeling-eph`, `indice-pobreza-UBA` and `elecciones-ARG` can remain spatially simple;
- legacy EPH/circuit crosswalk repos have explicit successor state;
- an external researcher can reproduce at least one useful public geography product using only repository documentation and commands.

## Wave A0 — architecture authority bundle

**State:** this seed bundle.

Mission:

- establish the successor Argentina Geography mission;
- record authority/source/product boundaries;
- define artifacts/catalogs as public API;
- establish migration and upstream promotion policy.

No production behavior change.

## Wave A1 — product kernel and synthetic catalogs

Mission: refactor the existing fixture so it proves the new product classes without changing historical source claims.

Required outcomes:

- depend on released `empirical-data-contracts` and `spatial-data-foundation` for owned shared mechanics;
- add minimal internal representation/writer for Geography Release and Relation Release bundles;
- create synthetic `geography_catalog` and `relation_catalog` entries from the fixture;
- split relation facts from adjudication/winner policy;
- keep old fixture semantic cases as regression evidence;
- do not introduce a large framework.

Tests:

- offline deterministic build/verify;
- duplicate IDs fail/partition explicitly as governed by fixture policy;
- relation rows remain many-to-many before crosswalk;
- manifests bind exact parent releases;
- clean artifact reader can verify without repository-relative paths.

Stop if adopting upstream contracts would force a schema change not justified by released APIs.

## Wave A2 — first real source: INDEC 2022 radios

Mission: create the first real normalized geography release from the current national INDEC 2022 radio layer.

Inspect live provider metadata first.

Required outcomes:

- source adapter pins acquisition metadata and retrieved bytes/layer identity;
- preserve `cod_indec` and component native identifiers as zero-preserving strings;
- treat documented adjustment units explicitly rather than as ordinary populated radios;
- canonical GeoParquet release;
- source QA: feature count, unique IDs, geometry types, CRS, null/duplicate identity, empty/invalid geometry, bbox;
- manifest + catalog entry;
- distribution mode reflects actual rights evidence; do not infer redistribution permission from public accessibility.

Non-goals:

- CEUR comparison;
- geometry repair;
- Censo↔IGN relation;
- Census statistics join.

## Wave A3 — INDEC 2022 fractions

Mission: add a second official Census 2022 level using the same source/release infrastructure and prove that source adapters do not hard-code radio-only assumptions.

Required outcomes:

- normalized fraction release;
- identity/coverage QA;
- catalog entry;
- verify radio→fraction identity consistency where native codes make that a direct structural check, without deriving geometry ownership policy.

This wave can be combined with A2 only if the PR remains small and both layers share the same acquisition contract.

## Wave A4 — CEUR 2022 V2025-1

Mission: materialize the curated-research CEUR 2022 radio geography as a distinct authority.

Required outcomes:

- exact `V2025-1` file/hash/source citation;
- CC BY attribution metadata;
- native schema/ID characterization;
- normalized GeoParquet release;
- authority status `curated_research`;
- catalog entry.

Do not compare or choose between CEUR and INDEC yet.

## Wave A5 — INDEC 2022 ↔ CEUR 2022 relation/comparison

Mission: produce the first real Gold interoperability artifact.

Required outcomes:

- both exact parent releases pinned;
- areal relation facts generated through `spatial-data-foundation`;
- quantitative coverage/multiplicity distributions;
- identify need for target-side overlap share and topology/diff helpers;
- local helpers allowed only under `TOOL_PROMOTION_POLICY.md`;
- no "winner" geography.

Human-readable evidence should explain where representations differ and distinguish identity differences from geometry differences.

## Wave A6 — Census 2010 backbone

Mission: establish a stable Census 2010 geography identity source for downstream applications and historical relations.

Subtasks may be separated:

- exact INDEC 2010 source snapshot characterization/materialization;
- CEUR `RADIOS_2010_V2025-1` release;
- INDEC↔CEUR 2010 relation/comparison;
- reconciliation of historical repository counts/IDs as evidence, not as a forced target.

Primary consumer boundary:

```text
radio_2010_id
department_2010_id
province_2010_id
```

Do not insert poverty-region semantics.

## Wave A7 — official EPH geography

Mission: replace inferred historical radio→agglomerate mechanics with the official INDEC EPH geographic product where possible.

Required outcomes:

- exact official source snapshot;
- normalized radio/agglomerate identity table/geography as appropriate;
- catalog entry;
- explicit survey-frame/census-2010 basis;
- no recomputation by overlay when the source directly provides the mapping;
- characterize temporal coverage/revisions relevant to use.

Consumer proof:

- demonstrate that `income-modeling-eph` can reference/use this release without importing GIS logic.

Only after consumer proof should `Aglomerados-EPH-INDEC` be marked superseded.

## Wave A8 — Tartagalensis circuit geographies

Mission: adopt pinned Tartagalensis circuit snapshots for 2021 and 2025.

Required outcomes:

- pin exact repository commit;
- preserve composite native identity (`codprov`, `coddepto`, `circuito`);
- preserve nonstandard/no-data source features with explicit status instead of silently dropping territory;
- keep reconstructed/source-quality limitations in metadata;
- produce separate 2021 and 2025 releases;
- catalog entries;
- explicit evidence that circuit codes are not globally unique and that certain districts are not directly code-compatible between vintages.

No Census relation in this wave.

## Wave A9 — Census 2010 ↔ circuit relations

Mission: produce governed geometric relation releases between Census 2010 radios and each circuit snapshot.

Required outcomes:

- relation facts first;
- coverage/ambiguous/multi-candidate QA by province;
- compare against historical `censo2010-circuitos-electorales` behavior as regression evidence;
- any one-target crosswalk is a separate explicit policy artifact;
- never calculate areal winner semantics in geographic degrees.

Consumer proof:

- demonstrate join compatibility with `elecciones-ARG` circuit dimensions for one bounded election/district scenario without importing electoral facts into this repo.

## Wave A10 — IGN administrative release + Census relation

Mission: restore the valuable Census↔IGN idea in its new neutral form.

Required outcomes:

- pin one exact IGN administrative source snapshot/layer;
- produce normalized IGN geography release;
- produce Census↔IGN relation facts;
- preserve both authorities independently;
- adjudicated crosswalk only if a concrete consumer requires it.

Do not describe IGN as a correction of Census geography.

## Wave A11 — longitudinal geography proof

Mission: produce the first Census cross-vintage relation, initially CEUR 2010↔2022 because CEUR explicitly provides a harmonized longitudinal series.

Required outcomes:

- two-sided overlap evidence where required;
- classify candidate patterns (`stable`, `split`, `merge`, `complex`) only as a versioned derived interpretation;
- quantify relation coverage;
- document limitations of transferring measurements across changing geographies;
- assess local helpers against the upstream promotion policy.

No population allocation method unless separately approved by a scientific consumer.

## Wave A12 — researcher-ready release surface

Mission: make at least one public source/product reproducible by a third party.

Required outcomes:

- installable package/CLI if justified by current implementation;
- `geography list`, `relation list`, `inspect`, `fetch/materialize`, `verify` or equivalent small command surface;
- citation/attribution instructions;
- distribution-mode behavior;
- one concise tutorial using only public inputs;
- no network in ordinary tests;
- release validation from a clean environment.

## Optional upstream promotion wave

This wave exists only if A5/A9/A11 produce evidence that a helper meets `TOOL_PROMOTION_POLICY.md`.

Possible targets:

- topology audit;
- geography diff;
- target-side overlap share/count;
- bounded neutral inspection helpers.

If there is no proven duplication, do not create upstream work.

## Execution graph

```text
A0 architecture
 |
 v
A1 product kernel
 |
 +--> A2 INDEC 2022 radio --> A3 fractions
 |             |
 |             +--> A5 INDEC/CEUR relation <-- A4 CEUR 2022
 |
 +--> A6 Census 2010 backbone
 |        |
 |        +--> A7 EPH --> EPH consumer proof
 |        |
 |        +--> A9 Census/circuit relation <-- A8 circuits
 |        |
 |        +--> A10 Census/IGN
 |        |
 |        +--> A11 longitudinal
 |
 +----------------------------------> A12 researcher surface
```

A source wave may run in parallel with another source wave after A1, but relation waves wait for their exact parent releases.

## Program non-goals

- no national "master polygon";
- no forced migration of every historical dataset;
- no generic provider framework in `spatial-data-foundation`;
- no poverty calculation;
- no electoral results pipeline;
- no Census microdata distribution;
- no automatic source mutation when schemas drift;
- no live-source dependency in CI;
- no large web application required for v1.
