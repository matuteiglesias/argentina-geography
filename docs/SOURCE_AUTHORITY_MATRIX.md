# Source authority matrix

Status: seed authority inventory. **Every production wave must re-check the live source before adoption.** URLs and source metadata are evidence inputs, not guarantees that a remote service will remain unchanged.

## Authority vocabulary

| Authority status | Meaning |
| --- | --- |
| `official` | Produced/published by the responsible public authority for the represented statistical/geographic object. |
| `curated_research` | Research dataset that deliberately harmonizes or corrects an official source for analytical use. |
| `curated_operational` | Maintained external dataset assembled from official sources plus documented expert curation/reconstruction. |
| `derived_geometric_fact` | Reproducible relation/measurement created by this project from explicit source releases. |
| `research_interpretation` | A policy-dependent mapping or classification approved for a stated research purpose. |

Authority is not a quality score. It tells users what sort of claim an artifact can support.

## INDEC — Census 2022

### National census radios

- Provider: Instituto Nacional de Estadística y Censos (INDEC).
- Role: `official` statistical geography.
- Current national layer: `Radios censales`.
- Metadata publication date observed: 2026-03-20.
- Source: https://geonode.indec.gob.ar/layers/geonode_data%3Ageonode%3Aradios_censales2
- Metadata describes the national layer as the integration of DPE cartography adjusted to IGN provincial limits.
- Current fields include jurisdiction, jurisdiction code, department code/name, fraction, radio, radio type and `cod_indec`.
- Metadata explicitly warns that integration against disputed/interprovincial limits can deform some radios and can exceptionally transfer surface between provinces; adjustment radios/fracciones `00` exist in Misiones and Entre Ríos and do not carry census data.
- Portal metadata currently does not specify a reusable license. Do **not** infer redistribution permission. Start with remote acquisition + local immutable snapshot/manifest unless rights are clarified.

Candidate product:

```text
indec:census:2022:radio
```

### National census fractions

- Provider: INDEC.
- Role: `official` statistical geography.
- Source: https://geonode.indec.gob.ar/layers/geonode_data%3Ageonode%3Afracciones_censales
- Metadata publication date observed: 2025-01-16.
- Defined as exhaustive department subdivisions formed from complete radios for the census operation.
- License is not specified in current GeoNode metadata; treat redistribution separately from use/acquisition.

Candidate product:

```text
indec:census:2022:fraction
```

## INDEC — Census 2010

- Provider: INDEC.
- Role: `official` statistical geography of the 2010 operation.
- Historical cartography/codes entry point: https://sitioanterior.indec.gob.ar/nivel4_default.asp?id_tema_1=1&id_tema_2=39&id_tema_3=120
- Historical source material should be treated as operation-vintage evidence, not silently replaced with a later harmonized geometry.
- Before production adoption, identify exact downloadable files, hashes, CRS declarations, expected counts, native identifiers and redistribution terms.

Candidate products:

```text
indec:census:2010:radio
indec:census:2010:fraction
indec:census:2010:department
```

Only materialize levels for which an exact source snapshot is established.

## CEUR-CONICET — longitudinal census radio series

- Dataset: Gonzalo Martín Rodríguez, *Cartografía de radios censales de Argentina corregidos, completados y estandarizados de 1991, 2001, 2010 y 2022*.
- Persistent record: https://ri.conicet.gov.ar/handle/11336/149711
- Role: `curated_research`.
- Current release observed: `V2025-1`.
- Current files:
  - `RADIOS_1991_V2025-1.zip`
  - `RADIOS_2001_V2025-1.zip`
  - `RADIOS_2010_V2025-1.zip`
  - `RADIOS_2022_V2025-1.zip`
  - `NOTAS_VERSION_2025-1.docx`
- Record describes a backward harmonization method: 2022 geometry as the basis for 2010, 2010 for 2001, and 2001 for 1991.
- Record currently states Creative Commons Attribution 2.5 Unported (CC BY 2.5), except where otherwise noted.

Scientific meaning:

CEUR is not a byte-equivalent mirror of the original census-operation cartography. It is deliberately valuable because it improves/harmonizes geometry for longitudinal research.

Candidate products:

```text
ceur:census:2025-1:1991:radio
ceur:census:2025-1:2001:radio
ceur:census:2025-1:2010:radio
ceur:census:2025-1:2022:radio
```

Primary future use: cross-vintage relations and INDEC↔CEUR comparison.

## IGN — national geographic/administrative reference

- Provider: Instituto Geográfico Nacional (IGN).
- Role: `official` geographic/administrative reference.
- Vector layers: https://www.ign.gob.ar/NuestrasActividades/InformacionGeoespacial/CapasSIG
- IGN also exposes OGC services including WMS/WFS.
- Open-data/service entry point: https://ide.ign.gob.ar/

Production rule:

Never identify an IGN geography only as "current". A real release must pin a retrieval/source snapshot with the exact layer, file/service request, retrieval time and hash/materialized content identity.

Possible products, only after source inspection:

```text
ign:administrative:<snapshot>:province
ign:administrative:<snapshot>:department
ign:administrative:<snapshot>:local-government
```

The Censo↔IGN relation is a product; IGN does not overwrite INDEC Census identity.

## INDEC — EPH geographic coverage

- Provider: INDEC.
- Role: `official` survey geography/frame evidence.
- Current database portal: https://www.indec.gob.ar/Institucional/Indec/BasesDeDatos
- Historical cartography entry point also exposes the EPH geography: https://sitioanterior.indec.gob.ar/nivel4_default.asp?id_tema_1=1&id_tema_2=39&id_tema_3=120
- INDEC publishes EPH coverage at census-radio level according to Census 2010 cartography, plus urban-envelope and entity-level products.

Candidate product:

```text
indec:eph:census2010-frame:radio
```

The product should preserve the official radio→EPH-agglomerate identity instead of reconstructing it through another overlay when the source already provides it.

## Tartagalensis — electoral circuits

- Repository: https://github.com/tartagalensis/circuitos_electorales_AR
- Maintainer: Franco Galeano.
- Role adopted by this project: `curated_operational` circuit geography.
- Current repository provides 24 districts for 2021 and 2025 with a common `circuito`, `codprov`, `coddepto`, geometry schema.
- Current repository states CC BY 4.0 for its dataset and documents upstream source attribution separately.
- The maintainer documents that some provinces require reconstruction from official agreements, polling-place georeferencing and political subdivisions because no single usable official polygon layer exists.
- The repository also documents temporal incompatibilities (notably circuit renaming in Santa Fe and Tierra del Fuego between 2021 and 2025).

Production rule:

Pin an exact commit for every Argentina Geography circuit release; never build a scientific release from floating `main`.

Candidate products:

```text
tartagalensis:electoral:<commit>:2021:circuit
tartagalensis:electoral:<commit>:2025:circuit
```

Preserve curation/reconstruction limitations in the release manifest. Do not downgrade expert reconstruction to an undocumented "official" claim.

## Distribution modes

Every source config must declare one of:

```text
redistributed_snapshot
official_remote_fetch
user_supplied_snapshot
```

A source may be scientifically authoritative while still requiring `official_remote_fetch` because redistribution terms are not established.

## Adoption checklist

Before adding a source geography to the catalog, record:

- provider and title;
- exact release/date/commit/layer;
- persistent origin URL;
- acquisition path;
- retrieved files/layers and SHA-256;
- CRS as received;
- schema and native identifier fields;
- feature count and unique identity count;
- geometry types, empty/invalid counts;
- license/attribution evidence;
- declared authority status;
- known limitations;
- whether the repository may redistribute the bytes.

Source drift in any identity-bearing field is a stop condition, not an invitation to silently adapt.
