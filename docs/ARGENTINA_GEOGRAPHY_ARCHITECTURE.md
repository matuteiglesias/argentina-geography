# Argentina Geography — architecture

Status: **active interoperability architecture**.

`argentina-geography` is a data-product producer for reproducible Argentine geography
releases, relations, and explicitly governed interpretations. Its public API is the
artifacts, manifests, catalogs, and verification paths produced by the repository.

## Mission

A researcher or downstream application should be able to answer:

1. what geography releases exist;
2. which authority/source and exact snapshot each release represents;
3. which relations between releases have already been computed;
4. which ambiguities remain facts rather than being silently adjudicated; and
5. how to verify an artifact without reproducing historical notebooks.

## Ecosystem boundary

```text
empirical-data-contracts
        |
        v
spatial-data-foundation
  generic CRS / geometry / relation mechanics
        |
        v
+--------------------------------------------------+
|               argentina-geography                |
|                                                  |
| source-faithful geography releases               |
| derived hierarchy/footprint products             |
| cross-authority relation releases                |
| explicitly governed crosswalks when required     |
| Argentina-specific identity + QA                 |
+--------------------------+-----------------------+
                           |
          +----------------+----------------+
          |                |                |
          v                v                v
   samplerCensoARG   income-modeling   elecciones-ARG
```

The repository may incubate a helper that later belongs in `spatial-data-foundation`,
but promotion is by repeated evidence, not anticipation.

## No single canonical geography

INDEC Census, CEUR-CONICET, IGN, INDEC EPH, and electoral authorities/curators answer
different questions. Their identifiers and boundaries must not be collapsed into a
single allegedly canonical system.

A relation between two authorities is useful evidence precisely because the two
authorities remain independently inspectable.

## Parallel statistical and electoral hierarchies

The electoral vertical is a first-class parallel territorial system.

```text
statistical / administrative          electoral

province                              electoral district
  |                                    |
department / partido / comuna        electoral section
  |                                    |
fraction                              electoral circuit
  |                                    |
radio                                 mesa / election facts
```

Similarity of level does **not** imply shared identity.

In particular:

- INDEC `province_2010_id` and electoral district codes are separate namespaces even
  though a governed 24-row correspondence exists;
- Tartagalensis `coddepto` is treated as a provider-native electoral-section component,
  not as an INDEC/IGN department identifier;
- electoral section ↔ administrative department correspondence is allowed to be N:M;
- Census radio ↔ electoral circuit correspondence is allowed to be N:M;
- election-event dimensions such as `eleccion_id`, vote totals, candidacies, mesas, and
  `seccionprovincial_id` remain in election-domain systems unless an independent
  geographic authority is acquired.

`docs/ELECTORAL_VERTICAL.md` is the authoritative detailed contract for this vertical
and supersedes the earlier narrow A9 interpretation.

## Product classes

### Geography release

A source-specific normalized geography faithful to a provider/release. Examples:

```text
indec:census:2010:radio
indec:census:2022:radio
ceur:census:v2025-1:2010:radio
indec:eph:<release>:radio
tartagalensis:electoral:2021:circuit
tartagalensis:electoral:2025:circuit
```

Native identity and source limitations remain observable.

### Relation release

Provider-neutral facts between two explicit geographies or derived footprints.

```text
source_uid
target_uid
overlap_area_m2
overlap_share_of_source
overlap_share_of_target
relation_status
```

Relations may remain many-to-many. Ambiguity, unmatched units, invalid geometry, and
coverage gaps are data.

### Crosswalk / interpretation release

A crosswalk is a separate policy product that selects or interprets relation candidates
for a concrete consumer. For example, “largest overlap” is not relation truth.

```text
relation fact:  radio R overlaps circuits A and B
policy fact:    under policy P, R is assigned to A
```

No crosswalk exists merely because historical code once chose a target.

## Bronze / Silver / Gold

**Bronze** preserves exact source evidence: provider, release/commit, URL, file/layer,
hash, retrieval evidence, license, citation, and documentation.

**Silver** normalizes one source/release at a time while preserving native identity and
source geometry meaning.

**Gold** publishes interoperability: relations, hierarchy/coverage evidence, explicit
compatibility declarations, and separately governed crosswalks.

Gold never deletes the Silver evidence from which it derives.

## Derived footprints are not new authorities

A higher-level footprint may be derived by unioning lower-level source geometry for a
specific relation question, for example:

- Census 2010 department footprints derived from exact official Census radios;
- electoral section footprints derived from assigned Tartagalensis circuits.

Such a footprint must be named as derived. It is not silently promoted to an official
administrative or electoral boundary. If the source is incomplete or nonstandard,
that limitation remains visible.

## Identity

`geo_uid` and other interoperability IDs do not replace native provider identifiers.
Every product must preserve enough native identity to trace a row back to its source.

Electoral source fields remain source-native:

```text
codprov
coddepto
circuito
```

Semantic hierarchy artifacts may additionally expose:

```text
electoral_district_code
electoral_section_code
electoral_circuit_code
```

Those aliases do not convert them into Census/IGN codes.

## Catalogs

Geography and relation catalogs are discovery APIs. They identify exact parents,
release versions, authority status, relation type, ambiguity/unmatched counts, and
artifact references. A catalog must list only products actually built.

## QA ownership

### `spatial-data-foundation`

- CRS/unit discipline;
- validity mechanics;
- spatial overlap/membership;
- generic relation candidates and geometry roles.

### `argentina-geography`

- INDEC/CEUR/IGN/Tartagalensis source semantics;
- native identifier structure;
- electoral composite identity;
- explicit namespace bridges;
- source-vintage compatibility;
- Argentina-specific coverage and multiplicity QA;
- historical-policy regression evidence.

### downstream applications

- whether an estimand is supported by coverage;
- which circuit vintage an election may use;
- whether a one-target mapping is scientifically/operationally acceptable;
- election-event and vote semantics.

## Legacy migration principle

Historical repositories may be frozen or decommissioned when their durable geography
capabilities are reproduced here with exact provenance and verification. Their notebooks
may remain as regression/archive evidence. Specialized application behavior should not
be imported merely to make a legacy repository empty.

## Researcher-facing principle

A user should not need to clone sibling repositories, reproduce notebook state, guess a
CRS, equate authority codes, or rewrite a spatial join already governed here.

Prefer deletion of duplicated geography work downstream over addition of hidden
convenience policy inside this repository.
