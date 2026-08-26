# INDEC 2022 national census-fraction product

Status: Wave A3 implementation authority; live source proof pending.

## Source

Provider: Instituto Nacional de Estadística y Censos (INDEC).

Official GeoNode resource: `Fracciones censales`, resource UUID `a3b7e165-5db5-42aa-893a-6f5d6dbf83dc`, metadata publication date 2025-01-16. The source coding note defines a census fraction as a seven-digit code: jurisdiction (2), department (3), fraction (2), with Windows-1252/CP1252 source encoding.

The GeoNode metadata currently reports `License: Not Specified`, so Argentina Geography uses `distribution_mode=official_remote_fetch` and does not commit official geometry.

## Product

```text
dataset_id: arggeo.indec.census.2022.fraction
geography_id: indec:2022:census:fraction
schema: arggeo.geography/v1
authority_status: official
distribution_mode: official_remote_fetch
```

The product keeps `cod_indec` as the authoritative seven-digit native identity and derives:

```text
department_code = cod_indec[0:5]
fraction_code   = cod_indec[5:7]
```

Source `cpr`, `cde` and `cfn` remain visible for provider audit. Following the evidence learned in A2, representation differences in supporting code fields become explicit QA warnings rather than a second manufactured identity.

## Geometry and staging

The provider CRS is preserved as received. Missing, empty or non-areal geometry is a stop condition. Invalid polygons can stage source-faithfully as `geometry_role=source_invalid`, with valid rows marked `geometry_role=analytical`; no `make_valid`, buffering, snapping or silent repair is performed.

The source-adoption proof profiles raw schema/identity/geometry evidence before materialization and reuses the same downloaded ZIP for the release. It uploads only non-geometric evidence.

## Adjustment units

INDEC documents fraction/radio `00` adjustment surfaces without census data in Entre Ríos and Misiones. Those fractions are retained as `adjustment_no_census_data`. Any other zero-coded fraction remains visible as `zero_code_unclassified` with QA warning until provider evidence supports a stronger interpretation.

## Expected stage policy

`PASS_WITH_WARNINGS` is acceptable when warnings are bounded and do not lose native identity, source rows or provenance. The live source proof determines the actual warning set and quantitative QA before merge.
