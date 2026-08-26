# Product model

This document defines the minimum product vocabulary for Argentina Geography. Keep it small.

## Design goals

Products must be:

- source-addressed;
- independently verifiable;
- explicit about authority and vintage;
- usable without sibling repository paths;
- friendly to tabular consumers that do not need geometry;
- composable across providers without pretending providers share one canonical boundary system.

## 1. Geography release

A normalized representation of one explicit source geography.

### Required conceptual metadata

```text
geography_id
release_version
schema_version
provider
source_snapshot
scheme
vintage
level
authority_status
coverage
artifact files
QA
limitations
```

Use `empirical-data-contracts` wherever the shared model already fits (`SourceSnapshotRef`, `GeographySpec`, `DatasetRef`, `CoverageContract`, `RunManifest`, `QAResult`). Do not create competing shared contract classes merely to rename fields.

### Required row identity

Every feature must expose:

```text
geo_uid
native_id
```

plus the provider-native components needed to audit identity.

`geo_uid` MUST be stable within the declared geography release and MUST NOT depend on row order, local path or wall-clock time.

### Geometry

Canonical analytical geometry is GeoParquet unless a wave documents a stronger reason otherwise.

A normalized release may change encoding/CRS/storage representation. It may not silently perform substantive geometry repair. If a provider geometry needs repair to become analytically usable, the repair is a separately governed transformation with explicit before/after QA and acceptance criteria.

## 2. Relation release

A relation release binds **two exact geography releases**.

### Required conceptual identity

```text
relation_id
source_geography_id
source_release_version
target_geography_id
target_release_version
relation_method
relation_parameters
producer version
```

### Minimum relation facts

For areal relations, target schema should converge toward:

```text
source_geo_uid
target_geo_uid
overlap_area_m2
overlap_share_of_source
overlap_share_of_target
source_candidate_count
target_candidate_count
relation_status
```

`spatial-data-foundation` currently supplies source-side overlap facts. Target-side share/count may initially be implemented here if needed, under the promotion policy, until a generic upstream contract is justified.

Rows with no positive-area relation must remain observable through status/audit outputs rather than disappearing silently.

### Relation order is non-semantic

Candidate row ordering never determines a winner. Deterministic serialization may sort at the artifact boundary, not as policy.

## 3. Crosswalk / interpretation release

Crosswalks are optional Gold products created only when a consumer needs one target per source or another explicit interpretation.

Minimum fields:

```text
source_geo_uid
selected_target_geo_uid
policy_id
policy_version
candidate_count
winner_share
assignment_status
manual_override_id_or_null
```

The crosswalk manifest MUST identify its parent relation release.

Valid statuses should distinguish at least:

```text
matched
unmatched
ambiguous
excluded
```

Do not overload missing target ID to carry all four meanings.

## 4. Geography catalog

A compact, machine-readable index of released geographies.

Candidate schema v1:

```text
geography_id
release_version
schema_version
provider
scheme
vintage
level
source_release
authority_status
feature_count
native_id_fields
geometry_types
storage_crs
coverage_status
artifact_ref
manifest_ref
```

The catalog contains **released products**, not aspirational registry entries.

## 5. Relation catalog

Candidate schema v1:

```text
relation_id
release_version
source_geography_id
source_release_version
target_geography_id
target_release_version
relation_type
policy_id
matched_count
ambiguous_count
unmatched_count
coverage_share
artifact_ref
manifest_ref
```

A purely geometric relation has `policy_id = null`.

## 6. Artifact bundle

A geography release bundle should normally contain:

```text
manifest.json
geography.parquet
qa.json
limitations.md or limitations.json
checksums.txt or equivalent manifested hashes
```

Optional:

```text
geography.geojson        # interchange/presentation derivative
source_metadata.json
inspection/              # bounded human QA evidence
```

A relation release should normally contain:

```text
manifest.json
relations.parquet
qa.json
checksums
```

and optional crosswalk products in their own release boundary rather than silently adding winner columns to `relations.parquet`.

## 7. Authority metadata

Allowed seed vocabulary:

```text
official
curated_research
curated_operational
derived_geometric_fact
research_interpretation
```

The authority label belongs in metadata/catalogs, not repeated on every row unless a product has mixed row-level authority and that mixture is meaningful.

## 8. Distribution metadata

Every Geography Release declares:

```text
distribution_mode = redistributed_snapshot |
                    official_remote_fetch |
                    user_supplied_snapshot
```

and the attribution/citation requirement known at release time.

A release can exist as a reproducible local artifact even when the project cannot legally or confidently redistribute the source bytes.

## 9. Compatibility products

Compatibility with a downstream application is evidence, not a new shared ontology.

Examples:

```text
samplerCensoARG requires radio_2010 + department_2010 identity
income-modeling-eph requires authoritative EPH agglomerate lineage
elecciones-ARG requires district/section/circuit key compatibility
indice-pobreza-UBA optionally consumes department geometry for publication
```

Consumer proofs should be small and explicit; do not import downstream scientific rules into this product model.

## 10. Versioning rules

Increment a geography release when any of these change materially:

- source snapshot/release;
- persisted schema;
- identity normalization;
- substantive geometry;
- acceptance/repair policy;
- coverage semantics.

A new upstream provider snapshot is normally a new geography release identity/version, not an in-place overwrite.

A relation release is invalidated when either parent geography release changes.
