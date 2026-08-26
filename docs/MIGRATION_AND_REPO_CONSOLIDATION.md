# Migration and repository consolidation

## Destination

`censo-ign-geografias` is the technical seed for **Argentina Geography** because it already has an executable package, source registry, fixture policy, deterministic release, QA reports and tests.

The eventual repository rename should be:

```text
censo-ign-geografias -> argentina-geography
```

Do the rename only after the architecture/product vocabulary is present on `main` and the first new-style release path is underway. A repository rename is not itself a modernization wave.

## What survives from this repository

Preserve as evidence:

- historical notebooks;
- historical CEUR/CONICET source snapshots already committed;
- reference/crosswalk files;
- characterization documents;
- fixture release and tests until successor parity is proven.

Promote/refactor:

- source registry concept;
- explicit policy files;
- deterministic manifests/hashes;
- repair auditing;
- coverage/exceptions reports;
- reproducible fixture commands.

Retire from production authority after replacement:

- local scalar geometry intersection mechanics already owned by `spatial-data-foundation`;
- monolithic `release.py` responsibilities;
- the assumption that Censo→IGN reconciliation defines the repo's primary purpose;
- any source inventory that still treats the old CEUR snapshot as the latest available authority.

## `Aglomerados-EPH-INDEC`

Historical value:

- preserves EPH geography observations;
- contains a historical radio↔agglomerate overlay workflow;
- captures older assumptions and source artifacts.

Successor:

```text
INDEC official EPH geography
       -> argentina-geography
       -> arggeo.indec.eph.census2010.radio_frame
```

The migration is now complete. A7 publishes the exact successor:

```text
release         census2010-frame-9b372c33aa68
source snapshot 9b372c33aa6827705e354f9be3545bf80bd668e44acfb602b6b63aabbe2704b8
frame SHA       ea0f5a749cfe0863e71d06064814d003607a43547398d0baa192aea26b18f675
geography SHA   243a448071bf03e08d69208b585a7e63f22a228a8ac5fba5e1ff44f07a899b68
direct mapping  2fdf263982639b6dc7ebfbeeaec3cecc971801debe8adde6ba48043e48641052
```

It preserves all 26,815 source rows, exposes the official 26,417-radio / 32-agglomerate frame, binds it to the exact official Census 2010 parent, and has detached verification plus a read-only `income-modeling-eph` compatibility proof.

The old overlay is not ported for behavioral compatibility because INDEC directly publishes `eph_codagl`. The historical repository remains useful as regression/method evidence, including the notebook-era 26,418-radio inferred result and its geographic-CRS area calculation, but it is no longer a production authority.

Archive/supersede criteria:

- official EPH release materialized and verified — **satisfied**;
- fields needed by downstream EPH users preserved — **satisfied**;
- `income-modeling-eph` consumer proof succeeds — **satisfied**;
- old repo lifecycle points to the successor and its unique evidence remains accessible — **satisfied by the 2026-08-26 decommissioning change**.

Disposition: **superseded; archive recommended**.

## `censo2010-circuitos-electorales`

Historical value:

- preserves previous Censo radio→circuit workflow;
- contains manual corrections and edge cases that should inform regression/QA;
- documents an earlier relationship with Tartagalensis data.

Target successor:

```text
Tartagalensis pinned circuit geography
          +
Census 2010 geography release
          |
          v
spatial-data-foundation relation facts
          |
          v
argentina-geography relation/crosswalk release
```

Do not copy notebook-era geographic area calculations or source-cloning behavior into the successor.

Archive/supersede criteria:

- pinned 2021/2025 circuit releases exist;
- Censo↔circuit relation product exists;
- historical-vs-modern regression evidence is documented;
- `elecciones-ARG` compatibility proof succeeds;
- lifecycle points to the successor.

## Downstream repositories remain separate

### `samplerCensoARG`

Should consume stable Census radio/department identity artifacts. It should not build geography.

Its poverty-region classification is not an official geography and should ultimately be a separate policy/mapping input.

### `income-modeling-eph`

Should consume explicit EPH geography lineage; no generic GIS responsibilities move into the modeling package.

### `indice-pobreza-UBA`

Should remain primarily tabular/scientific. Geography is optional publication context after the poverty kernel.

### `elecciones-ARG`

Remains authority for electoral tabular facts/dimensions. Circuit geometry lives in Argentina Geography and is joined by explicit compatible keys/vintage.

## Historical repo rule

Do not rewrite or delete old repository history simply to make the new architecture look clean.

The migration pattern is:

```text
inspect -> extract durable knowledge -> prove successor -> mark superseded
```

not:

```text
move every old file -> delete source repo
```

## Migration ledger

| Legacy asset | Durable idea/evidence | Successor product/module | State |
| --- | --- | --- | --- |
| historical Censo notebooks | ID corrections / source lineage / regression cases | source adapters + QA | pending |
| old Censo↔IGN overlay | relation/adjudication intent | relation release + policy | pending |
| EPH overlay notebook | EPH radio/agglomerate need + historical regression evidence | `arggeo.indec.eph.census2010.radio_frame@census2010-frame-9b372c33aa68` | **superseded** |
| circuit overlay notebook | Censo↔circuit need and edge cases | electoral relation/crosswalk | pending |

Only mark a row `superseded` after observable successor evidence exists.
