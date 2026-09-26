# G1 handoff — first-class EPH agglomerate geography

This product promotes the official A7 radio/agglomerate relation into a first-class
survey geography without reconstructing membership spatially.

## Identity

Logical geography level:

```text
eph_agglomerate
```

Canonical ID:

```text
eph_agglomerate_id
```

The ID is the zero-preserving two-digit native `eph_codagl` inherited from the
official A7 source. It has **no administrative parent**.

Administrative views and EPH survey geography are parallel:

```text
radio_2010_id
├── province_2010_id
├── department_2010_id
└── eph_agglomerate_id
```

A cross-province agglomerate is therefore valid and must never be forced beneath
one province or department.

## Membership authority

The only membership relation is the exact A7 direct relation:

```text
radio_2010_id -> eph_agglomerate_id
```

No overlay, centroid, point-in-polygon, nearest-neighbour, majority-area or
administrative-parent inference is allowed.

The derived polygon is a union of radio geometries **after** membership is known.
Geometry does not decide membership.

## Artifacts

`python -m argentina_geography.derived.indec_eph_agglomerate materialize ...`
writes:

```text
geography.parquet
geography.geojson
agglomerate_inventory.csv
radio_to_agglomerate.parquet
inventory_audit.json
qa.json
limitations.json
manifest.json
checksums.sha256
```

`agglomerate_inventory.csv` is the human-readable census of native IDs, source
name values, crossed administrative jurisdictions and radio counts.

`radio_to_agglomerate.parquet` republishes the exact A7 relation as the explicit
consumer seam.

## 31 vs 32

A7 contains 32 native `eph_codagl` identities. This product preserves all of
them. It does not merge, drop or reinterpret a native code merely to match the
separate public phrase "31 aglomerados urbanos".

`inventory_audit.json` exposes the exact native inventory so the nomenclature
question can be resolved descriptively from the source evidence without changing
identity.

## Geometry caveat

A7 retains three source radios without geometry. They remain valid membership
rows in `radio_to_agglomerate.parquet`. The agglomerate geometry uses all
available source radio geometries and reports missing-geometry radio counts per
agglomerate. No geometry is filled from another provider.

## Non-ownership

This product contains no poverty values, poverty-line regions, population
calibration or model semantics. Poverty-region binding remains a downstream
scientific policy artifact.
