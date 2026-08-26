# INDEC Census 2010 radio geography

## Authority and snapshot

This product is the normalized **official INDEC Census 2010** radio geography. It is independent from the CEUR-CONICET V2025-1 longitudinal product and must not be substituted for it or vice versa.

The adopted live source is the 24-file province-by-radio set exposed by INDEC's current `Unidades Geoestadísticas` catalog. The source proof on 2026-08-26 records every file, vector layer, SHA-256, feature count and CRS in `docs/source-evidence/indec-census-2010-2026-08-26.json`.

Exact source snapshot:

- source ID: `indec-census-2010-radio`
- source release: `census-2010-cartography`
- aggregate snapshot SHA-256: `c9184f47fd46c8a47e2c15e5c734b7b6ceb660ce737e18430691f6fbff3c53e8`
- normalized release identity for this snapshot: `arggeo.indec.census.2010.radio@2010-national-c9184f47fd46`
- source CRS: `EPSG:22183`
- source polygon-component rows: `52,408`
- unique official radio identities: `52,406`

## Stable consumer identity

Consumers use only zero-preserving census-vintage strings:

```text
radio_2010_id       = 9-digit official INDEC LINK
department_2010_id  = radio_2010_id[0:5]
province_2010_id    = radio_2010_id[0:2]
```

Leading zeroes are semantic. These names are deliberately vintage-specific; they are not generic contemporary administrative IDs.

### Provider-native mapping

Most province files expose `link` as the radio code and `toponimo_i` as a unique provider row identity. CABA exposes `LINK`, plus explicit `PROV`, `DEPTO`, `FRAC`, `RADIO`, and the unique source-row identity `PAIS0210_I`. For CABA, normalization verifies that `PROV+DEPTO+FRAC+RADIO == LINK` before publishing the stable IDs.

All provider-native row/radio identity fields are retained in `source_components.parquet`.

## Why 52,408 is not 52,401

The old repository CONICET-derived 2010 shapefile contains `52,401` geometry rows. The old `censos_db_ref/2010/RADIO.csv` lookup contains `52,382` rows. Those values are historical evidence, not acceptance targets.

The current official INDEC source contains `52,408` polygon-component rows. It also reveals two CABA radio codes that each occur as two distinct source polygon components:

- `020121607`
- `020130104`

Each pair contains one polygon with census-count fields and one polygon whose census-count fields are null. The components have distinct provider-native row IDs and distinct geometries. No row is discarded to chase an old count.

The release therefore publishes two explicit artifacts:

- `source_components.parquet`: all `52,408` source rows with source geometry and native identity preserved;
- `geography.parquet`: `52,406` unique radio identities. Only source polygons carrying the same official `LINK` are unioned into one consumer radio geometry.

That aggregation is an identity-level component composition, not geometry repair. `make_valid`, snapping, buffering, centroid assignment and other topology repairs are not applied.

## QA and verification

The live source probe characterizes native schemas before normalization. The current 24 files have three schema/geometry variants, all report `EPSG:22183`, and the probe observed no missing, empty or invalid geometries.

Materialization validates:

- the complete 24-province source set;
- one vector layer per ZIP;
- source CRS;
- 9-digit zero-preserving radio identity;
- province/file consistency;
- CABA native component composition;
- source-component uniqueness;
- unique consumer radio identity after explicit component aggregation;
- areal and valid geometry without repair.

Detached verification reopens only the produced release, verifies checksums/manifest/catalog, and re-checks the stable ID composition and geometry validity.

## Scope

This is Census 2010 statistical geography. It carries **no poverty-region semantics** and does not assert that census radio boundaries are general-purpose administrative boundaries. The downstream A7 EPH geography must reference an exact merged 2010 release and should use a declared official radio/agglomerate relation when INDEC supplies one rather than reconstructing membership spatially.
