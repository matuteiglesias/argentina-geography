# Agent execution pack — Argentina Geography v1

Copy-ready briefs for bounded autonomous execution. Agents must also obey repository `AGENTS.md`.

## Common preamble for every agent

Start from current `main`; do not assume this document's implementation state is current. Read the architecture, source matrix, product model, build pack and relevant source/consumer files. Inspect the exact external source at execution time when the wave depends on a live authority. Keep the PR bounded and human-mergeable. Do not silently repair or reinterpret provider geometry. Ordinary tests must remain network-free.

Every PR description must include:

```text
Mission
Input authorities
Output artifacts/contracts
Source evidence
Foundation boundary
Argentina/domain boundary
Tests/evidence
Non-goals
Stop conditions encountered
Definition of done
```

## Agent A1 — product kernel and fixture migration

**Branch:** `feat/arggeo-product-kernel`

**Mission:** turn the existing synthetic fixture into proof of the new Geography Release / Relation Release / optional Crosswalk architecture.

Inspect first:

- `src/censo_geo/release.py`;
- fixture inputs/release/tests;
- `empirical-data-contracts` released API;
- `spatial-data-foundation` current released API.

Required:

- use foundation areal relation mechanics instead of the local generic scalar intersection loop;
- preserve existing fixture edge-case intent;
- keep source-specific repair/adjudication policy local;
- persist relation facts independently from winner selection;
- add small geography/relation catalogs containing only actually built fixture products;
- preserve deterministic verify path.

Do not:

- fetch live sources;
- rename the repo yet unless explicitly included by the human;
- generalize provider adapters;
- move fixture-specific winner policy upstream.

DoD: offline tests prove many-to-many relation facts and separately governed crosswalk behavior.

## Agent A2 — INDEC 2022 radio source

**Branch:** `feat/indec-2022-radio-geography`

**Mission:** publish the first real source Geography Release from the national INDEC 2022 radios layer.

Inspect current provider metadata and download/service options first. Pin exact retrieved content.

Required:

- source snapshot record;
- native schema characterization;
- zero-preserving IDs;
- adjustment-unit handling based on source metadata;
- canonical GeoParquet output;
- QA and catalog entry;
- no inferred redistribution rights.

Hard stop:

- identity-bearing schema changed unexpectedly;
- download cannot be made snapshot-verifiable;
- source semantics for adjustment units/native code are unclear;
- substantive repair appears necessary.

## Agent A3 — INDEC 2022 fractions

**Branch:** `feat/indec-2022-fraction-geography`

**Mission:** add the official INDEC 2022 fraction Geography Release and prove the product kernel supports another Census level without radio-specific hacks.

Reuse acquisition/product mechanics only where genuinely shared. Do not invent a generic INDEC framework beyond current evidence.

DoD: normalized release, QA, catalog entry and direct identity consistency checks where supported by native codes.

## Agent A4 — CEUR 2022 V2025-1

**Branch:** `feat/ceur-2022-geography`

**Mission:** materialize CEUR `RADIOS_2022_V2025-1.zip` as a distinct curated-research Geography Release.

Required:

- pin persistent CONICET record and exact bytes/hash;
- carry citation/license metadata;
- characterize native schema and geometry;
- no comparison/winner semantics;
- catalog entry.

DoD: another researcher can distinguish CEUR 2022 from INDEC 2022 by identity and metadata even if geometries happen to coincide in a location.

## Agent A5 — INDEC↔CEUR 2022 relation

**Branch:** `feat/indec-ceur-2022-relation`

**Mission:** create the first real relation/comparison product between exact A2 and A4 parent releases.

Required:

- foundation relation kernel;
- quantitative multiplicity/coverage evidence;
- determine whether target-side overlap share is needed;
- bounded local comparison/topology helpers only when current output cannot answer a concrete QA question;
- human-readable comparison summary.

Do not choose a canonical provider.

Any helper that appears generic must remain local in this PR and be assessed separately under the promotion policy.

## Agent A6 — Census 2010 backbone

**Branch:** `feat/census-2010-geography-backbone`

**Mission:** establish clean 2010 geography identity products needed by sampler/electoral work.

Inspect official INDEC 2010 source files and CEUR V2025-1 separately. Split the PR if both source acquisitions make it large.

Required final boundary:

```text
radio_2010_id
department_2010_id
province_2010_id
```

Preserve native IDs and explain any mapping to these stable names. Reconcile historical 52,401/lookup-count evidence descriptively; do not force current sources to reproduce an unexplained old count.

No poverty-region classification.

## Agent A7 — official EPH geography

**Branch:** `feat/indec-eph-geography`

**Mission:** publish INDEC's official EPH radio-level geography/frame product based on Census 2010 and replace the need for historical inferred overlay.

Inspect first:

- current INDEC EPH coverage files/documentation;
- `Aglomerados-EPH-INDEC` as historical evidence;
- current `income-modeling-eph` geography fields/lineage.

Required:

- source snapshot and normalized product;
- official radio/agglomerate identity preserved;
- temporal/frame limitations documented;
- no spatial join when source directly declares the mapping;
- one read-only consumer compatibility proof for `income-modeling-eph`.

Do not modify model features/science.

## Agent A8 — Tartagalensis circuit releases

**Branch:** `feat/tartagalensis-circuit-geographies`

**Mission:** publish pinned 2021 and 2025 circuit Geography Releases from `tartagalensis/circuitos_electorales_AR`.

Required:

- exact source commit;
- 24-district coverage check;
- composite identity validation;
- preserve no-data/grey-zone source features with explicit source status;
- geometry/schema QA;
- curation/reconstruction limitations carried into metadata;
- separate 2021/2025 products and catalog entries.

Do not create cross-vintage circuit equivalences or Census relations here.

## Agent A9 — Census↔circuit relation

**Branch:** `feat/census-electoral-relations`

**Mission:** relate the exact Census 2010 product to pinned 2021/2025 circuit products.

Inspect historical `censo2010-circuitos-electorales` for regression cases, never as computational authority.

Required:

- metric-CRS areal relation facts;
- coverage/multiplicity QA by province;
- old-vs-new behavioral comparison for known edge cases;
- relation products before any crosswalk;
- if a crosswalk is required, place policy in a separate manifest/artifact;
- one bounded `elecciones-ARG` key compatibility proof.

Hard stop on a policy decision that changes ambiguous assignments without an approved rule.

## Agent A10 — IGN administrative product and relation

**Branch:** `feat/ign-administrative-relation`

**Mission:** create one exact pinned IGN administrative Geography Release and a neutral relation to one Census geography.

Required:

- exact IGN layer/snapshot provenance;
- normalized provider identity;
- relation facts;
- no "corrected Census" language or mutation;
- crosswalk only on concrete consumer demand.

DoD: both INDEC/CEUR Census and IGN remain independently inspectable parent releases.

## Agent A11 — longitudinal 2010↔2022 proof

**Branch:** `feat/longitudinal-census-relation`

**Mission:** use CEUR's harmonized 2010/2022 products to create the first cross-vintage radio relation.

Required:

- exact parent releases;
- two-sided overlap evidence if needed for split/merge diagnosis;
- explicit N:M relation retained;
- optional versioned derived classification (`stable`, `split`, `merge`, `complex`) with documented thresholds;
- no population transfer/allocation assumptions;
- assess any repeated generic helper for upstream promotion.

## Agent A12 — researcher release surface

**Branch:** `feat/researcher-interface-v1`

**Mission:** make released products discoverable, fetchable/materializable and verifiable by a third-party researcher.

Inspect existing command surface before adding a CLI framework. Keep dependencies small.

Required:

- list geographies/relations;
- inspect product metadata;
- explicit source retrieval/materialization where allowed;
- verify local artifact;
- source + project citation guidance;
- one short public-source tutorial;
- clean-environment test.

Do not build a web platform or GIS abstraction.

## Integration reviewer

After any multi-wave stretch, reconstruct current state from `main` and answer:

- Which released geographies exist now?
- Which relations/crosswalks exist now?
- Are catalogs truthful?
- Are source/authority labels supported by evidence?
- Has any source-specific logic leaked into `spatial-data-foundation`?
- Has any downstream scientific policy leaked into Argentina Geography?
- Which legacy repository can now be safely marked superseded?
- Did a local helper earn an upstream promotion, or should it stay local?
- What is the smallest next wave that creates observable value?

Do not create work merely to complete the numbering in this document.
