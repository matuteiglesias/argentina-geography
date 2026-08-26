# Official INDEC EPH Census-2010 radio frame

A7 publishes the current official INDEC EPH radio-level coverage as a source-faithful survey-frame product. It is based on Census 2010 cartography and is not a Census 2022 geography.

## Exact release

- Dataset: `arggeo.indec.eph.census2010.radio_frame`
- Release: `census2010-frame-9b372c33aa68`
- Source snapshot SHA-256: `9b372c33aa6827705e354f9be3545bf80bd668e44acfb602b6b63aabbe2704b8`
- `frame.parquet` SHA-256: `ea0f5a749cfe0863e71d06064814d003607a43547398d0baa192aea26b18f675`
- `geography.parquet` SHA-256: `243a448071bf03e08d69208b585a7e63f22a228a8ac5fba5e1ff44f07a899b68`
- `source_components.parquet` SHA-256: `d48e06c98cebfc59ddd61830f294689107eebd40967b3f148c8ba5d6b54f28f3`
- CRS: EPSG:22183

The source snapshot pins `radios_eph.zip`, `radios_eph_json.zip`, `estructura_radios_eph.xls` and `localidades_aglomerados_eph.xls`; exact per-file hashes are in `docs/source-evidence/indec-eph-census2010-frame-2026-08-26.json`.

## Direct identity, not a reconstructed overlay

INDEC directly publishes the EPH agglomerate code in `eph_codagl`. The release therefore uses the declared source relation and does **not** spatially reconstruct radio→agglomerate membership.

Stable identity is:

```text
radio_2010_id      = codprov + coddepto + frac2010 + radio2010
department_2010_id = codprov + coddepto
province_2010_id   = codprov
eph_agglomerate_id = zero-preserving eph_codagl
```

Both distributed vector variants yield exactly 26,417 distinct radio/agglomerate pairs and the same deterministic relation SHA-256 `2fdf263982639b6dc7ebfbeeaec3cecc971801debe8adde6ba48043e48641052`.

## Source rows and radio grain

The provider layer contains 26,815 rows but 26,417 unique radios. There are 236 multi-component radios and 398 source rows beyond unique radio grain, with at most four source components for one radio. All original rows are retained in `source_components.parquet`; `frame.parquet` is the geometry-free one-radio-per-row consumer boundary. `geography.parquet` unions only source components already sharing the same direct official radio identity. No geometry repair is applied.

Three official frame radios have no geometry in either source vector variant: `020011704`, `020011706`, and `500281605`. They remain present in `frame.parquet` and in the geography artifact with `geometry_role=source_missing`; A7 does not fill them from another provider or from the Census parent.

The source contains 32 native `eph_codagl` codes. Native names are preserved rather than silently standardized; code 38 is observed with two spelling variants for San Nicolás–Villa Constitución.

## Exact Census parent proof

The live source proof independently rebuilt and detached-verified the exact merged A6 parent `arggeo.indec.census.2010.radio@2010-national-c9184f47fd46`, content SHA-256 `762b825f27e3b6e8c1c3f63ae2a5f9aecfa80784b0f56d6739755d02ee749019`. All 26,417 A7 radio IDs are present in its 52,406-radio identity set; missing count is zero.

## Frame and temporal limitations

This product records the currently published Census-2010-based EPH coverage/frame. It must not be read as evidence that one frame definition applies unchanged to every historical EPH quarter. INDEC documentation records later coverage review and incorporation of previously missing areas into regular fieldwork. Consumers doing time-specific EPH work must match their survey vintage to the applicable official frame documentation.

## `income-modeling-eph` compatibility

A read-only proof pins `matuteiglesias/income-modeling-eph` at commit `48cf614fc6e05c1b4b0b595dfe949dcbe8b1e138`. Its existing optional `AGLOMERADO` geography column can reference the release through the tabular projection `AGLOMERADO = int(eph_agglomerate_id)`. The round-trip code check passes; GIS logic is not required and no model features, estimands, training data, splits or scientific methodology are modified.

## Verification

Live source-proof run `32928410734` passed acquisition, source characterization, exact A6 parent rebuild/verification, A7 materialization and detached verification. General CI run `32928413472` passed Python 3.11 and 3.12 checks, tests, product smoke and distribution build.
