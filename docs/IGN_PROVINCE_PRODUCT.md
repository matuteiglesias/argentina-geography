# IGN province Geography Release — Atlas W3 parent

Status: exact official source archive, canonical 24-feature Geography Release, and deterministic display derivative pinned for `argentina-geography#34`.

## Scope

This product adopts exactly one official Instituto Geográfico Nacional (IGN) layer: **Provincia**. It is the upstream geography parent required by the poverty-atlas W3 fixture. It is not derived from Census radios or IGN departments and applies no dissolve, clipping, topology repair, boundary adjudication, or poverty-data decoration.

The release preserves the source-native first-order administrative geography and exposes one explicit downstream display seam:

```text
geography_id = IN1 = native_id
```

`geography_id` is a zero-preserving two-character string. It is an alias for the source identity inside this exact release, not a replacement for `IN1` or `native_id`.

## Exact source snapshot

- Provider: Instituto Geográfico Nacional (IGN).
- Authority status: `official`.
- Official layer: `Provincia`.
- Official download: `https://www.ign.gob.ar/descargas/geodatos/SHAPES/ign_provincia.zip`.
- Archive member: `Provincia/ign_provincia.shp`.
- Retrieval time anchoring the release: `2026-08-26T11:26:10.513047+00:00`.
- Raw archive SHA-256: `b9fcf6f90f28f1bdfcc713a47ad4ed63e2db0b000c4642611597d4ea8b897c55`.
- Raw archive size: `10,520,464` bytes.
- Repeated live downloads during source proof: byte-identical.
- CRS: `EPSG:4326`.
- Feature count: `24`.
- Geometry types: `Polygon`, `MultiPolygon`.
- Missing / empty / invalid geometry: `0 / 0 / 0`.
- Extent: `[-73.99999999999994, -90.00000002899998, -24.999999999999943, -21.780856763999964]`.

The archive members are dated September 2019. Current IGN metadata records the geometry as last modified on 2019-07-21. The release is therefore described as an **official archive retrieved on 2026-08-26**, not as geometry authored in 2026. IGN does not expose a formal immutable version in the archive filename; the release identity is the exact source URL, retrieval timestamp, byte size, raw SHA-256, and normalized artifact hashes.

## Native identity and atlas compatibility

The source exposes and the normalized release preserves:

```text
OBJECTID, Entidad, Objeto, FNA, GNA, NAM, SAG, FDC, IN1, SHAPE_STAr, SHAPE_STLe
```

`IN1` is the normalized `native_id` and downstream `geography_id`. All 24 values are present, unique, two characters, and equal exactly to the poverty-atlas fixture identity set:

```text
02, 06, 10, 14, 18, 22, 26, 30,
34, 38, 42, 46, 50, 54, 58, 62,
66, 70, 74, 78, 82, 86, 90, 94
```

`OBJECTID` is independently preserved and is also complete and unique for all 24 source features. Names are not used as identity. Source vocabulary is preserved: `Objeto=Provincia`, while `GNA` contains `Ciudad Autónoma` and `Provincia`.

## Normalized Geography Release

- Dataset: `arggeo.ign.administrative.province`.
- Release version: `snapshot-20260826-b9fcf6f90f28`.
- Geography version: `2026-08-26-b9fcf6f90f28`.
- Canonical GeoParquet SHA-256: `3907e1e0e256f2ea768a66e14874266a576787fe724dad0d35eb9308ddc6dd7b`.
- Rows: `24`.
- Analytical rows: `24`.
- Source-invalid rows: `0`.
- Source QA: `PASS` / `GREEN`.

The materializer verifies the raw archive hash and size, exact source schema and vocabulary, exact 24-ID set, exact feature count, CRS, geometry usability, and the pinned normalized GeoParquet hash. Detached verification does not require access to the original source archive.

No source geometry is modified. Missing, empty, or non-areal geometry fails staging. A future explicit snapshot containing invalid areal geometry would retain the source geometry with a non-analytical role and an explicit warning rather than silently repairing it.

## Deterministic display derivative

The release also emits `geography.geojson` as a deterministic geometry-only display derivative suitable for vector-transport preparation.

- GeoJSON SHA-256: `c49be97fef429c9bc473681e6677135bf19307da1141b1d7f6f12c50df366ed3`.
- Features: `24`.
- Feature ID: exact `geography_id`.
- Feature ID rule: `geography_id = IN1 = native_id`.
- CRS: `EPSG:4326`.
- Geometry transform: none.
- Geometry repair / clip / dissolve: `false / false / false`.
- Properties: `geography_id`, `geo_uid`, `native_id`, `FNA`, `GNA`, `NAM`.

No poverty measure, fixture value, styling value, or presentation classification is embedded in either canonical geography or the display derivative. A Mapbox transport can therefore promote `geography_id` as feature identity without coupling the geometry release to a poverty release.

## Distribution, attribution, and limitations

Distribution mode is `official_remote_fetch`: raw source bytes are not committed to the repository. IGN is credited as the source. IGN's official Provincia metadata states free use with appropriate citation of IGN; this release records that evidence without broadening it into claims about unrelated products.

The canonical source is bicontinental and extends to latitude -90 through the Tierra del Fuego, Antártida e Islas del Atlántico Sur feature. It is not clipped merely to make a continental browser view convenient. Any future continental-only visualization must be an explicit governed display transformation with its own identity and QA.

This release does not assert that IGN geometry supersedes, repairs, or is interchangeable with Census statistical geography. The fact that `IN1` is fixture-compatible supplies an identity seam; it does not collapse provider semantics.

## Downstream boundary

The poverty atlas may pin this exact release and derive or publish a Mapbox vector transport whose every feature exposes the exact `geography_id`. The atlas remains responsible for transport/source-layer/tileset configuration and runtime joins, while `argentina-geography` remains responsible for geography identity, source evidence, canonical geometry, QA, limitations, and the deterministic display derivative.
