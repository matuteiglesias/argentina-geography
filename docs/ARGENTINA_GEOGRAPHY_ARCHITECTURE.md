# Argentina Geography — architecture evolution

Status: **seed architecture for the next development program**.

This repository currently carries a historical Censo↔IGN reconciliation pipeline plus a bounded synthetic release. Its intended successor identity is **Argentina Geography**.

## Mission

Provide a reproducible interoperability layer between Argentine geography authorities and research/application consumers.

The project should let a researcher answer four questions without reconstructing old notebooks:

1. **What geography releases are available?**
2. **Where did each release come from and what exactly does it mean?**
3. **What governed relations already exist between two geographies?**
4. **How can I obtain and verify the relevant artifact without adopting a whole application stack?**

The repository is therefore primarily a **data-product producer**. Python code exists to acquire, validate, normalize, relate and package geography products; the stable public boundary is the produced artifacts, their manifests and their catalogs.

## Position in the ecosystem

```text
empirical-data-contracts
  identity / provenance / coverage / run envelopes
                |
                v
spatial-data-foundation
  CRS / geometry / indexed relations / generic QA mechanics
                |
                v
+------------------------------------------+
|           argentina-geography            |
|                                          |
|  INDEC / CEUR / IGN / Tartagalensis     |
|  EPH geography                           |
|                                          |
|  source snapshots                        |
|  normalized geography releases           |
|  relation releases                       |
|  governed crosswalks                     |
|  Argentina/source-specific QA            |
|  geography + relation catalogs           |
+--------------------+---------------------+
                     |
        +------------+-------------+
        |            |             |
        v            v             v
 samplerCensoARG  income-modeling  elecciones-ARG
        |            |             |
        +------------+-------------+
                     v
            poverty / atlas / research
```

`argentina-geography` uses `spatial-data-foundation`; it is also an incubation zone for spatial helpers that might later become generic enough to move upstream. Promotion is by evidence, not by anticipation.

## No single canonical geography

The system MUST NOT collapse INDEC, CEUR-CONICET and IGN into a single purportedly true boundary system.

They answer different questions:

- **INDEC Census geography** describes the statistical geography of a census operation.
- **CEUR-CONICET harmonized census geography** is a research-oriented, corrected and longitudinally harmonized representation.
- **IGN geography** is the national geographic/administrative reference maintained by the geographic authority.
- **INDEC EPH geography** describes the spatial coverage/frame relevant to the survey.
- **Tartagalensis circuit geography** is the adopted operational curated representation of electoral circuits, combining official source material and documented reconstruction where necessary.

Their differences are useful evidence. The glue layer publishes relations between authorities; it does not erase those differences.

## Three product classes

### 1. Geography release

A source-specific normalized geography that remains semantically faithful to its provider.

Examples:

```text
indec:census:2022:radio
indec:census:2022:fraction
ceur:census:2025-1:2010:radio
ign:administrative:<snapshot>:department
indec:eph:<release>:radio
tartagalensis:electoral:2021:circuit
tartagalensis:electoral:2025:circuit
```

### 2. Relation release

Provider-neutral geometric facts between two explicit geography releases.

Example:

```text
source_geo_uid,target_geo_uid,overlap_area_m2,
source_overlap_share,target_overlap_share,relation_status
```

A relation is allowed to remain many-to-many.

### 3. Crosswalk / interpretation release

An explicit domain policy that turns candidate relations into an operational mapping when a consumer truly needs one.

Example:

```text
source_geo_uid,selected_target_geo_uid,policy_id,
winner_share,candidate_count,assignment_status
```

The distinction is fundamental:

```text
relation fact:  A overlaps B 62% and C 38%
interpretation: under policy P, A is assigned to B
```

## Bronze / Silver / Gold

### Bronze — source evidence

Keep the exact provenance needed to reconstruct a source snapshot:

- provider and title;
- source release/date/commit when available;
- origin URL or repository;
- acquisition method;
- file/layer identity;
- SHA-256 and byte size;
- retrieval time;
- licensing/attribution state;
- source documentation links.

Bronze does not imply that source bytes must be redistributed by this repository.

### Silver — normalized source geography

One provider/release at a time. Preserve native identity while adding a stable interoperable identity.

Typical columns:

```text
geo_uid
provider
source_release
scheme
vintage
level
native_id
<source-native identity components>
geometry
geometry_role
source_snapshot_id
```

Silver normalization may standardize type, zero-preserving identifiers, geometry column naming, storage CRS and metadata. It must not silently change substantive geometry meaning.

### Gold — interoperability products

Cross-source outputs:

- geography relations;
- explicitly governed crosswalks;
- cross-vintage relations;
- coverage/comparison products;
- compatibility declarations.

Gold never deletes the Silver source evidence from which it derives.

## Canonical storage

Preferred analytical boundaries:

```text
GeoParquet  -> canonical geography geometry artifacts
Parquet     -> relation and crosswalk artifacts
JSON        -> manifests, QA and compact catalogs
GeoJSON     -> optional exchange/presentation derivative
```

Do not require a downstream tabular consumer to load geometry merely to obtain IDs or mappings.

## Identity

A common `geo_uid` is an interoperability key, not a replacement for native identifiers.

Every release preserves enough provider-native identity to let a researcher check a row against source material.

Illustrative identity:

```text
geo_uid = indec:2022:census:radio:020010101
native_id = 020010101
province_code = 02
department_code = 001
fraction_code = 01
radio_code = 01
```

Exact encoding belongs in the versioned product schema, not in undocumented string slicing scattered across consumers.

## Catalogs as discovery APIs

Two small first-class artifacts make the system discoverable.

### Geography catalog

At minimum:

```text
geography_id
provider
scheme
vintage
level
source_release
release_version
feature_count
native_id_fields
geometry_types
storage_crs
authority_status
coverage_status
artifact_ref
manifest_ref
```

### Relation catalog

At minimum:

```text
relation_id
source_geography_id
target_geography_id
relation_type
policy_id_or_null
matched_count
ambiguous_count
unmatched_count
coverage_share
artifact_ref
manifest_ref
```

These catalogs make the collection behave as a geography graph rather than as a pile of files.

## QA ownership

### `spatial-data-foundation`

Generic geometric facts:

- CRS/unit discipline;
- geometry validity mechanics;
- spatial membership/overlap;
- candidate relations;
- generic geometry roles;
- generic presentation helpers.

### `argentina-geography`

Source/domain facts:

- INDEC identifier structure;
- provider schema drift;
- known source adjustment units;
- circuit composite keys;
- source-vintage compatibility;
- authority/curation labels;
- source-specific coverage interpretation.

### downstream applications

Scientific validity:

- whether coverage supports an estimand;
- whether an election can use a particular circuit vintage;
- whether a poverty output should be reported for a geography;
- whether modeled estimates may be interpreted at a requested level.

## Researcher-facing principle

A researcher should be able to use a release without:

- cloning sibling repositories;
- reproducing notebook state;
- guessing a CRS;
- re-parsing native identifiers;
- deciding which source is the "real" one;
- writing a spatial join that the producer has already governed.

## Evolution principle

Prefer deletion of duplicated geographic work downstream over addition of convenience layers here.

The architecture succeeds when `samplerCensoARG`, `income-modeling-eph`, `indice-pobreza-UBA` and `elecciones-ARG` become simpler because they consume explicit geography identities and releases.
