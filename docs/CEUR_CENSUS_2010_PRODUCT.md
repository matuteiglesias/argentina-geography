# CEUR Census 2010 V2025-1 geography product

## Product identity

`arggeo.ceur.census.2010.radio@v2025-1-2010-464e9b4c265a`

This is the CEUR-CONICET curated-research Census 2010 radio geography from V2025-1. It is deliberately separate from the official INDEC 2010 product.

## Consumer boundary

Every row exposes the stable zero-preserving fields:

```text
radio_2010_id
department_2010_id
province_2010_id
```

Mapping to provider-native identity is exact:

```text
radio_2010_id      = COD_2010
department_2010_id = PROV + DEPTO = COD_2010[0:5]
province_2010_id   = PROV         = COD_2010[0:2]
```

The provider fields `COD_2010`, `PROV`, `DEPTO`, `FRACC`, `RADIO` and all other native attributes remain present. The source invariant `COD_2010 == PROV+DEPTO+FRACC+RADIO` is a hard validation gate.

## Exact authority and source snapshot

The current CONICET Digital record `11336/149711` was re-checked on 2026-08-26. The adopted source is:

- release: `V2025-1`
- file: `RADIOS_2010_V2025-1.zip`
- current download sequence: 14
- SHA-256: `464e9b4c265a27f46a48e0c5914ef4e833c14e8977b8f0c9c1eaad672f374baa`
- layer: `Radios 2010 v2025-1`
- CRS: `EPSG:3857`
- license: Creative Commons Attribution 2.5 Unported, according to the CONICET record

CEUR describes the series as corrected, completed and standardized longitudinal research cartography. The project therefore records `authority_status=curated_research`; it does not relabel this release as official INDEC.

## Observed rows and QA

The exact source and consumer geography both contain 52,406 unique radio identities. There are 24 province codes and 528 province+department codes.

Twelve polygons are invalid according to the current geometry validity check. They remain present, unchanged, with `geometry_role=source_invalid`; 52,394 rows are immediately analytical. The release applies no topology repair and no source rows are discarded.

Normalized GeoParquet SHA-256:

`d2095144bc31a34bd09c8fc0a130a872f41016541a8b87daddd52aace759a23e`

Final stage decision is `PASS_WITH_WARNINGS`, QA state `YELLOW`, with the single typed warning `source_invalid_geometry`.

## Output bundle

A materialized release contains:

- `geography.parquet`
- `geography_catalog.parquet`
- `identity_contract.json`
- `manifest.json`
- `qa.json`
- `source_metadata.json`
- `limitations.json`
- `checksums.txt`

The detached verifier binds the row grain, stable/native identities, catalog entry, checksums and explicit geometry role.

## EPH boundary

CEUR V2025-1 contains questionnaire/frame-adjacent native attributes such as `BASICO`, `AMPLIADO` and `TIPO`, but it does not publish an authoritative EPH agglomerate identifier in this 2010 layer. The current CONICET record itself says municipality, locality and agglomerate codes/names are planned for a future version.

Therefore A7 must obtain radio-to-agglomerate/frame semantics independently from current official INDEC EPH documentation/files. No spatial EPH reconstruction or agglomerate inference is licensed by this A6 product.
