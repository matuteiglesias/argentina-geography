# INDEC 2022 national census-radio product

Status: Wave A2 implementation authority, source-proofed 2026-08-26.

## Source

Provider: Instituto Nacional de Estadística y Censos (INDEC).

Official GeoNode resource: `Radios censales`, resource UUID `927226f0-de91-4927-9c2c-522a4bbdbaaf`, metadata publication date 2026-03-20.

The source metadata describes the national radio layer as an integration of cartography produced by the provincial statistical offices and adjusted to IGN provincial limits. INDEC warns that this integration can deform some radios and can exceptionally transfer surface between provinces. It also documents fraction/radio `00` adjustment surfaces in Entre Ríos and Misiones that do not carry census data.

The GeoNode resource is publicly downloadable but currently reports `License: Not Specified`. Argentina Geography therefore adopts `distribution_mode=official_remote_fetch`; repository releases and CI evidence do not redistribute the source geometry.

The normative machine-readable source entry is `config/sources/indec_census_2022_radio.json`. The successful live evidence is recorded at `docs/source-evidence/indec-2022-radio-2026-08-26.md`.

## Product

```text
dataset_id: arggeo.indec.census.2022.radio
geography_id: indec:2022:census:radio
schema: arggeo.geography/v1
authority_status: official
distribution_mode: official_remote_fetch
stage_decision: PASS_WITH_WARNINGS
qa_state: YELLOW
```

A materialized release contains:

```text
geography.parquet
geography_catalog.parquet
manifest.json
qa.json
source_metadata.json
limitations.json
checksums.txt
```

The exact release version incorporates the SHA-256 of the retrieved WFS source snapshot. The manifest preserves the exact WFS request, source hash, size, source CRS, package version, normalized output hash and accepted QA warnings.

## Identity

The authoritative native identity is `cod_indec`, normalized as a zero-preserving nine-digit string. The 2026-08-26 national proof found 66,515 rows, 66,515 unique `cod_indec` values and no missing/duplicate identities.

The source fields `cpr`, `cde`, `cfn` and `cro` remain preserved for audit, but are not used to manufacture a second native identity. The source contains two observed `cde` representations: 66,510 cumulative five-digit values and 5 local three-digit values. Argentina Geography therefore derives stable normalized components from `cod_indec`:

```text
department_code = cod_indec[0:5]
fraction_code   = cod_indec[5:7]
radio_code      = cod_indec[7:9]
```

The project identity is:

```text
indec:2022:census:radio:<cod_indec>
```

A duplicate or missing `cod_indec` remains a stop condition. A disagreement in a supporting source-code representation is retained as explicit QA evidence rather than silently rewriting or dropping the row.

## Geometry

The source CRS (`EPSG:3857` in the source-proofed snapshot) is preserved in canonical GeoParquet. A2 performs no `make_valid`, snapping, buffering or boundary replacement.

The national proof found:

```text
source rows                    66,515
valid analytical geometries   66,512
source-invalid geometries           3
missing / empty / non-areal         0
```

Valid rows receive `geometry_role=analytical`. The three source-invalid polygons are preserved as `geometry_role=source_invalid` and `geometry_valid=false`; they are not eligible for generic spatial-relation kernels unless a future separately governed repair policy is approved.

GDAL/pyogrio also reports noncanonical shapefile ring winding and normalizes ring winding while reading. This is recorded as a non-blocking warning, not misrepresented as an Argentina Geography topology repair.

## Adjustment units

INDEC explicitly documents fraction/radio `00` adjustment surfaces without census data in Entre Ríos and Misiones. The proof observed 11 in Entre Ríos and 15 in Misiones, with no zero-coded rows outside those documented cases.

They are retained and marked:

```text
source_unit_status = adjustment_no_census_data
```

If a future snapshot contains zero-coded units outside the documented cases, they may stage as `zero_code_unclassified` with QA warning; no no-data semantics are inferred without source evidence.

## Acquisition

Network acquisition is explicit and separate from ordinary tests:

```bash
make materialize-indec-2022-radio
```

A previously acquired source can be materialized offline:

```bash
python -m argentina_geography.sources.indec_2022_radio materialize \
  --source /path/to/source.zip \
  --output /path/to/release
```

Ordinary CI remains network-free. `.github/workflows/source-indec-2022-radio.yml` is the source-adoption proof: it profiles and materializes the live official layer, performs detached verification and uploads only non-geometric evidence.

## Stage policy

A source release can be `PASS_WITH_WARNINGS` when warnings are explicit, source-faithful and do not create native-identity ambiguity or data loss. A2 currently accepts:

- `noncanonical_ring_winding`;
- `mixed_source_cde_representation`;
- `source_invalid_geometry` for the three preserved non-analytical polygons.

Stop rather than adapt silently if native identity becomes non-unique/missing, source bytes cannot be snapshot-addressed, source geometry is missing/empty/non-areal at material scale, or progressing would require an unapproved substantive repair or domain interpretation.
