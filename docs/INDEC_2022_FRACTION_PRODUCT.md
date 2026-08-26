# INDEC 2022 national census-fraction product

Status: Wave A3 implementation authority; source-proofed 2026-08-26.

## Source

Provider: Instituto Nacional de Estadística y Censos (INDEC).

Official GeoNode resource: `Fracciones censales`, resource UUID `a3b7e165-5db5-42aa-893a-6f5d6dbf83dc`, metadata publication date 2025-01-16. The source coding note defines a census fraction as a seven-digit code: jurisdiction (2), department (3), fraction (2), with Windows-1252/CP1252 source encoding.

The GeoNode metadata currently reports `License: Not Specified`, so Argentina Geography uses `distribution_mode=official_remote_fetch` and does not commit official geometry. The successful live evidence is persisted at `docs/source-evidence/indec-2022-fraction-2026-08-26.md`.

## Product

```text
dataset_id: arggeo.indec.census.2022.fraction
geography_id: indec:2022:census:fraction
schema: arggeo.geography/v1
authority_status: official
distribution_mode: official_remote_fetch
stage_decision: PASS
qa_state: GREEN
```

The source-proofed snapshot contains **6,571** rows and **6,571** unique non-missing `cod_indec` values. `cod_indec` is the authoritative seven-digit native identity and the product derives:

```text
department_code = cod_indec[0:5]
fraction_code   = cod_indec[5:7]
```

Source `cpr`, `cde` and `cfn` remain visible for provider audit. In the proofed snapshot, all 6,571 `cde` values use the cumulative five-digit representation and there are **0** supporting-code disagreements.

## Geometry and staging

The provider CRS is preserved as received (`EPSG:3857` in the proofed snapshot). Missing, empty or non-areal geometry is a stop condition. Invalid polygons may stage source-faithfully as `geometry_role=source_invalid`; valid rows are marked `geometry_role=analytical`. No `make_valid`, buffering, snapping or silent repair is performed.

The live proof found:

```text
source rows                    6,571
analytical geometries          6,571
source-invalid geometries          0
missing / empty / non-areal        0
```

The source-adoption proof profiles raw schema/identity/geometry evidence before materialization, reuses the same downloaded ZIP for the release, detached-verifies the materialized product, and uploads only non-geometric evidence.

## Adjustment units

INDEC documents fraction/radio `00` adjustment surfaces without census data in Entre Ríos and Misiones. The proof observed **11** in Entre Ríos and **15** in Misiones, for **26** total documented adjustment fractions and **0** unclassified zero-coded rows.

Those fractions are retained as:

```text
source_unit_status = adjustment_no_census_data
```

Any future zero-coded fraction outside the documented cases remains visible as `zero_code_unclassified` with QA warning until provider evidence supports a stronger interpretation.

## Stage policy

The proofed 2026-08-26 snapshot passes cleanly:

```text
stage_decision = PASS
qa_state = GREEN
accepted_warning_count = 0
```

`PASS_WITH_WARNINGS` remains an allowed future outcome when warnings are bounded, explicit, source-faithful, and do not lose native identity, source rows, or provenance. A future snapshot only stops when moving forward would require identity guesswork, source loss, or an unapproved substantive geometry/domain policy.
