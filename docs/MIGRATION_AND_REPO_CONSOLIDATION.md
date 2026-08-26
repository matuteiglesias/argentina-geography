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

Target successor:

```text
INDEC official EPH geography
       -> argentina-geography source adapter
       -> indec:eph:<release>:radio
```

Do not port the old overlay merely for behavioral compatibility if INDEC already publishes the official radio-level association.

Archive/supersede criteria:

- official EPH release materialized and verified;
- fields needed by downstream EPH users preserved;
- `income-modeling-eph` consumer proof succeeds;
- old repo lifecycle points to the successor and its unique evidence remains accessible.

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

The new repo should eventually maintain a small ledger:

| Legacy asset | Durable idea/evidence | Successor product/module | State |
| --- | --- | --- | --- |
| historical Censo notebooks | ID corrections / source lineage / regression cases | source adapters + QA | pending |
| old Censo↔IGN overlay | relation/adjudication intent | relation release + policy | pending |
| EPH overlay notebook | EPH radio/agglomerate need | official EPH release | pending |
| circuit overlay notebook | Censo↔circuit need and edge cases | electoral relation/crosswalk | pending |

Only mark a row `superseded` after observable successor evidence exists.
