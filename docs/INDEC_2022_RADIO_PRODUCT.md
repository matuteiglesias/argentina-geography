# INDEC 2022 national census-radio product

Status: Wave A2 implementation authority.

## Source

Provider: Instituto Nacional de Estadística y Censos (INDEC).

Official GeoNode resource: `Radios censales`, resource UUID `927226f0-de91-4927-9c2c-522a4bbdbaaf`, metadata publication date 2026-03-20.

The source metadata describes the national radio layer as an integration of cartography produced by the provincial statistical offices and adjusted to IGN provincial limits. INDEC warns that this integration can deform some radios and can exceptionally transfer surface between provinces. It also documents fraction/radio `00` adjustment surfaces in Entre Ríos and Misiones that do not carry census data.

The GeoNode resource is publicly downloadable but currently reports `License: Not Specified`. Argentina Geography therefore adopts `distribution_mode=official_remote_fetch`; repository releases and CI evidence do not redistribute the source geometry.

The normative machine-readable source entry is `config/sources/indec_census_2022_radio.json`.

## Product

```text
dataset_id: arggeo.indec.census.2022.radio
geography_id: indec:2022:census:radio
schema: arggeo.geography/v1
authority_status: official
distribution_mode: official_remote_fetch
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

The exact release version incorporates the SHA-256 of the retrieved WFS source snapshot. The manifest preserves the exact WFS request, source hash, size, source CRS, package version and normalized output hash.

## Identity

The native identity is `cod_indec`, normalized as a zero-preserving nine-digit string. The adapter also preserves the source components `cpr`, `cde`, `cfn` and `cro` and requires:

```text
cod_indec == cpr + cde + cfn + cro
```

A mismatch or duplicate native ID is source drift and fails closed.

The project identity is:

```text
indec:2022:census:radio:<cod_indec>
```

## Geometry

The source CRS is preserved in the canonical GeoParquet product. A2 performs no geometry repair, snapping, buffering or boundary replacement. Missing, empty, invalid or non-areal source geometry stops materialization and requires a new reviewed policy rather than an automatic fix.

## Adjustment units

Zero-coded fraction/radio units documented by INDEC in Entre Ríos and Misiones are retained and marked:

```text
source_unit_status = adjustment_no_census_data
```

They are not dropped and are not assigned census measurements. Zero-coded units outside the documented jurisdictions are a stop condition.

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

Ordinary CI remains network-free. `.github/workflows/source-indec-2022-radio.yml` is a source-adoption proof that materializes the live official layer and uploads only manifest/QA/source metadata evidence, never the geometry.

## Stop conditions

Stop rather than adapt silently if:

- required identity fields disappear/change meaning;
- `cod_indec` no longer equals its normalized native components;
- native IDs are duplicated;
- zero-coded radios/fracciones appear outside the currently documented adjustment jurisdictions;
- geometry requires substantive repair;
- the source CRS is absent;
- license/redistribution evidence changes the adopted distribution boundary.
