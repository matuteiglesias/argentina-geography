# CEUR Census 2022 radio product — V2025-1

Status: Wave A4 implementation authority; source-proofed 2026-08-26.

## Authority

This product represents the CEUR-CONICET dataset *Cartografía de radios censales de Argentina corregidos, completados y estandarizados de 1991, 2001, 2010 y 2022*, release `V2025-1`.

It is deliberately classified as:

```text
authority_status = curated_research
```

CEUR's cartography is scientifically valuable precisely because it is curated, corrected, completed and standardized for research. Argentina Geography does not relabel it as official INDEC cartography and does not choose it as a canonical replacement for INDEC.

## Source and distribution

Persistent record: `http://hdl.handle.net/11336/149711`.

Adopted file: `RADIOS_2022_V2025-1.zip`.

The CONICET Digital record states Creative Commons Attribution 2.5 Unported (CC BY 2.5), except where otherwise noted. The product therefore uses:

```text
distribution_mode = redistributed_snapshot
```

Attribution, citation, license name and license URL are carried in the release metadata. The repository does not need to commit the large raw ZIP merely because redistribution is permitted; exact source bytes remain snapshot-addressed by SHA-256.

## Product identity

```text
dataset_id: arggeo.ceur.census.2022.radio
geography_id: ceur:2022-v2025-1:census:radio
schema: arggeo.geography/v1
release_version: v2025-1-2022-<source-sha-prefix>
```

The source-proofed V2025-1 snapshot has 66,502 rows and 66,502 unique non-missing `COD_2022` values.

The authoritative native identity contract is:

```text
COD_2022 = PROV[2] + DEPTO[3] + FRACC[2] + RADIO[2]
```

Normalized convenience fields are derived without overwriting provider fields:

```text
province_code   = PROV
department_code = PROV + DEPTO
fraction_code   = FRACC
radio_code      = RADIO
```

A missing/duplicate `COD_2022` or a composition mismatch is source identity drift and stops materialization.

## Preserved source attributes

A4 preserves:

```text
OBS2022
VIV_TOT_P
POB_TOT_P
REDATAM
```

`OBS2022` contains CEUR curation annotations on a small set of rows. The source-proofed snapshot contains 89 populated annotations. These remain source evidence; they are not converted into Argentina Geography repair rules.

Likewise, A4 does not interpret `VIV_TOT_P`, `POB_TOT_P` or `REDATAM` as cross-source adjudication inputs. A5 may inspect them only if a concrete comparison question requires it and the semantics are explicit.

## Geometry and QA

The source CRS is preserved (`EPSG:3857` in the proofed snapshot). Missing, empty or non-areal geometry is a stop condition.

Source-invalid areal geometry is preserved rather than silently repaired or dropped. The live V2025-1 proof found:

```text
source rows                    66,502
analytical geometries          66,489
source-invalid geometries          13
missing / empty / non-areal         0
```

Rows are classified as:

```text
geometry_role=analytical
geometry_role=source_invalid
```

No `make_valid`, snapping, buffering, nearest assignment or boundary substitution occurs in A4.

The exact proofed release therefore has:

```text
stage_decision = PASS_WITH_WARNINGS
qa_state = YELLOW
accepted warning = source_invalid_geometry (13 rows)
```

This warning is intentionally non-blocking: all source rows, identity and provenance remain intact, while analytical consumers can filter to valid geometry until a separately governed repair product exists.

## Materialization

```bash
make materialize-ceur-2022-radio
```

Or from already acquired exact source bytes:

```bash
python -m argentina_geography.sources.ceur_2022_v2025_1 materialize \
  --source /path/to/RADIOS_2022_V2025-1.zip \
  --output /path/to/release
```

The release bundle contains canonical GeoParquet, catalog, manifest, QA, source metadata, limitations and checksums. Detached verification is available through the same module's `verify` command.

The quantitative live evidence for the adopted source snapshot is persisted at `docs/source-evidence/ceur-2022-v2025-1-2026-08-26.md`.

## Non-goals

A4 does not:

- compare CEUR against INDEC;
- select a preferred provider;
- create an INDEC↔CEUR crosswalk;
- repair the 13 source-invalid polygons;
- interpret CEUR source annotations as general repair policy;
- use population/housing attributes to alter geometry;
- build a generic source-adapter framework.

Those boundaries keep A5 focused on reproducible relation/comparison facts between two independently inspectable parent Geography Releases.
