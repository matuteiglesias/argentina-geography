# IGN department Geography Release — A10

Status: exact source archive and normalized release identity pinned; national Census relation proof is wired separately.

## Scope

A10 adopts exactly one administratively useful IGN layer: **Departamento**. The official Capas SIG
surface currently exposes it as a downloadable vector product and also serves a related live WFS
layer. The bounded release here is the static official archive, not a provider-wide IGN ingestion
framework.

## Exact source snapshot

- Provider: Instituto Geográfico Nacional (IGN).
- Authority status: `official`.
- Official download: `https://www.ign.gob.ar/descargas/geodatos/SHAPES/ign_departamento.zip`.
- Archive member: `ign_departamento/ign_departamento.shp`.
- Retrieval time: `2026-08-26T04:21:30+00:00`.
- Raw archive SHA-256: `33871350bd2da7e146e3daa9f696351b167c5feabeee0673d43b6671e10cb42c`.
- Raw archive size: `23,697,566` bytes.
- Repeated same-run downloads: byte-identical.
- Feature count: `529`.
- CRS: `EPSG:4326`.
- Geometry types: `Polygon`, `MultiPolygon`.
- Missing / empty / invalid geometry: `0 / 0 / 0`.
- Extent: `[-73.99999999999994, -90.00000001699999, -24.999999999999943, -21.781134793999968]`.

The archive members carry November 2019 timestamps. A10 therefore describes this as an **official
archive retrieved on 2026-08-26**, not as geometry authored in 2026. IGN does not expose a formal
immutable release identifier in the archive filename, so source identity is the exact URL,
retrieval time, byte size and raw SHA-256.

A live WFS request was also inspected:

```text
https://wms.ign.gob.ar/geoserver/ign/ows?service=WFS&version=2.0.0&request=GetFeature&typeNames=ign%3Adepartamento&outputFormat=application%2Fjson&srsName=EPSG%3A4326
```

It returned a related 529-feature layer, but two exact requests serialized to different raw byte
hashes (`e8a7065c…` and `ad3bfd62…`). The WFS is therefore corroborating service evidence rather
than the Geography Release source anchor.

## Native identity and schema

The archive exposes and the normalized release preserves:

```text
OBJECTID, Entidad, Objeto, FNA, GNA, NAM, SAG, FDC, IN1, SHAPE_STAr, SHAPE_STLe
```

`IN1` is the normalized `native_id`: all 529 values are present, unique and five digits.
`OBJECTID` is independently preserved and is also present and unique for all rows. Names are not
identity: `FNA` has 473 unique values and `NAM` 449 for 529 features.

The source administrative vocabulary is preserved. `GNA` contains `Departamento`, `Partido`, and
`Comuna`; those labels are not collapsed into a locally invented category. `SAG` exposes 22 source
lineage values. `FDC` has three observed non-null values but is missing for 477 rows, so no uniform
capture provenance is inferred from it.

## Normalized Geography Release

- Dataset: `arggeo.ign.administrative.department`.
- Release version: `snapshot-20260826-33871350bd2d`.
- Geography version: `2026-08-26-33871350bd2d`.
- Normalized GeoParquet SHA-256: `b54381bf3dedaf67746824dad80b60020f93aca5a98c2b2f4a1385c745eb6f0a`.
- Rows: `529`.
- Analytical rows: `529`.
- Source-invalid rows: `0`.
- Source QA: `PASS` / `GREEN`.

`geo_uid` combines provider, administrative level, the exact source snapshot token and `IN1`.
The materializer verifies both the raw archive hash and the normalized GeoParquet hash, preserves
all native fields above, emits `geography_catalog.parquet`, and supports verification from a copied
release directory without access to the original source archive.

Normalization does not repair geometry. Missing, empty or non-areal geometry fails staging;
source-invalid areal geometry, if encountered in a future explicit snapshot, would be retained with
an explicit non-analytical geometry role rather than modified in place.

## Distribution, attribution and limitations

Distribution mode is `official_remote_fetch`: the source archive and normalized geometry are not
committed to this repository. IGN is credited as the source. Current IGN publication metadata makes
the Departamento vector layer available for download and states free use of its demarcation data
with appropriate IGN citation; A10 records that evidence without extending it into a broader claim
about unrelated IGN products.

The source extent includes Argentina's bicontinental/Antarctic representation. Census 2022
statistical geography need not cover every administrative target, so unreferenced IGN targets are a
valid relation outcome. Census statistical boundaries and IGN administrative boundaries remain
separate parent products throughout.

## Relation boundary

A10 binds this exact IGN Geography Release to the already released exact
`arggeo.indec.census.2022.radio` parent:

- INDEC release: `2022-national-20260320-a390c8403850`.
- INDEC normalized geography SHA-256: `6a4b0bc3db5a92567eed7d643670e06c9916f4640a5247c5bfc022c1fb93dbce`.
- INDEC source snapshot SHA-256: `a390c84038509eb3e6125a5968c72f57fbfae757cda2a2344a14defb5ac18a7b`.

The relation uses the exact pinned `spatial_foundation.geography.relate_areal_objects` kernel,
retains N:M positive-area facts, computes both source- and target-side overlap shares for
quantitative QA, and keeps unmatched, invalid and unreferenced cases observable. Neither parent is
mutated, and the relation applies neither a preferred-boundary decision nor a one-target
assignment.
