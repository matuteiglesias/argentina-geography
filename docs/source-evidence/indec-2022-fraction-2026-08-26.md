# INDEC Census 2022 fractions — source proof 2026-08-26

Status: **PASS / GREEN**.

This is non-geometric evidence from the live source-proof for Wave A3. The official geometry is not committed because the GeoNode resource currently reports `License: Not Specified`; the product remains `official_remote_fetch`.

## Exact source snapshot

- Provider: INDEC
- Layer: `geonode:fracciones_censales`
- GeoNode resource UUID: `a3b7e165-5db5-42aa-893a-6f5d6dbf83dc`
- Metadata publication date: `2025-01-16T14:39:00-03:00`
- Retrieval: WFS 1.1.0 `SHAPE-ZIP`
- Source encoding: CP1252 / Windows-1252
- Received CRS: `EPSG:3857`
- Retrieved ZIP size: `37,127,784` bytes
- Retrieved ZIP SHA-256: `180f0990a95f45fae01567f2b2b866cc6ce54f754703f276fc311a964939eaf9`
- Materialized release version: `2022-national-20250116-180f0990a95f`
- Source-proof run: `32919358004`

## Identity evidence

- Source rows: **6,571**
- Unique `cod_indec`: **6,571**
- Missing identity: **0**
- Duplicate `cod_indec`: **0**
- `cde` cumulative five-digit representation: **6,571**
- `cde` local representation: **0**
- Supporting-code disagreements: **0**

`cod_indec` is therefore the authoritative seven-digit native ID for this release. The product derives `department_code=cod_indec[0:5]` and `fraction_code=cod_indec[5:7]` while preserving source `cpr`, `cde`, and `cfn` for audit.

## Geometry evidence

- Geometry types: Polygon, MultiPolygon
- Missing geometry: **0**
- Empty geometry: **0**
- Non-areal geometry: **0**
- Invalid geometry: **0**
- Rows eligible for `geometry_role=analytical`: **6,571**
- Rows retained as `geometry_role=source_invalid`: **0**

No geometry repair, snapping, buffering, or boundary replacement is required or applied.

## Adjustment units

INDEC documents fraction/radio `00` adjustment surfaces without census data in Entre Ríos and Misiones.

Observed release counts:

- Entre Ríos: **11** adjustment fractions
- Misiones: **15** adjustment fractions
- total documented adjustment fractions: **26**
- zero-coded rows outside those documented cases: **0**

These rows remain in the geography and carry `source_unit_status=adjustment_no_census_data`.

## Stage decision

The source passes cleanly with no accepted warnings:

```text
stage_decision = PASS
qa_state       = GREEN
accepted_warning_count = 0
```

The detached product verification also passed against the materialized snapshot. This evidence closes the A3 live-source gate without requiring a new source interpretation or geometry policy.
