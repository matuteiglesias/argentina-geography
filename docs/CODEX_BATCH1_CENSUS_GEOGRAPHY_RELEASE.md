# Codex work packet — Batch 1: Census geography release v1

## Mission

Convert this historical Census–IGN reconciliation pipeline into one bounded, reproducible geography release with explicit source vintages, coordinate systems, reconciliation rules, coverage, exceptions, and checksums.

Preserve the repository's legitimate derived-geography authority while making it impossible to confuse the output with current official administrative boundaries.

## Why this matters

Downstream socioeconomic analysis needs stable geographic identifiers and geometries. At present, the repository contains valuable reconciliation logic and snapshots, but its notebook environment, source URLs, exact vintages, exception handling, and outputs have not been revalidated in 2026.

The immediate goal is one trustworthy release slice—not a national geospatial platform redesign.

## Read first

1. Read every applicable `AGENTS.md` file.
2. Read `README.md`, all notebooks, helper modules, environment files, ignored/generated paths, and any source notes.
3. Inventory committed and referenced input/output files without assuming that a recently modified file is current.
4. Inspect `matuteiglesias/Aglomerados-EPH-INDEC` read-only as historical evidence for Census-radio membership in EPH agglomerates.
5. Inspect electoral-geography crosswalk repositories only when they reveal reusable reconciliation rules. Do not modify those repositories from this task.

## Authority and boundaries

This repository owns:

- its derived reconciliation between Census and IGN geographic references;
- its transformation and geometry-normalization logic;
- versioned geography outputs;
- reconciliation exceptions and coverage reports.

It does not own:

- official INDEC, IGN, CEUR-CONICET, electoral, or administrative geography;
- current 2026 boundaries;
- EPH variable harmonization;
- socioeconomic modeling;
- poverty indicators;
- publication deployment.

## Required deliverables

### 1. Repository and lineage characterization

Create `docs/GEOGRAPHY_CHARACTERIZATION.md` documenting:

- every executable notebook or module and its intended order;
- all source datasets, URLs or local paths currently referenced;
- exact or best-evidenced vintages;
- input and output formats;
- input/output CRS where discoverable;
- dissolve, intersection, nearest, overlay, and identifier-repair operations;
- current output inventory and the evidence behind the historical 52,401-unit count;
- implicit manual steps and environment assumptions;
- code worth preserving versus exploratory notebook material.

Clearly label unknowns and inferences.

### 2. Reproducible geospatial environment

Provide one supported environment definition using a modern, reproducible mechanism such as a pinned Conda/Mamba environment, lockfile, or container.

Avoid legacy instructions that depend on manually installed GDAL wheels.

Expose canonical commands equivalent to:

```bash
make install
make check
make test
make smoke
make release-fixture
```

`make check` and `make smoke` must run offline on bounded fixtures.

### 3. Geographic fixture

Create a tiny synthetic or redistributable fixture that contains:

- a valid polygon assigned unambiguously;
- a polygon crossing two candidate administrative units;
- an unmatched polygon;
- an invalid or self-intersecting geometry;
- a duplicate or conflicting identifier;
- at least two CRS inputs when CRS conversion is part of the real pipeline;
- stable IDs and a small population/weight field when needed to test weighted coverage.

The fixture should be visually and numerically inspectable.

### 4. Source registry

Create a machine-readable registry containing, for every source:

- source ID;
- publisher and title;
- source URL or acquisition note;
- geographic level;
- reference year/vintage;
- CRS as published;
- expected identifiers;
- retrieved file checksum when available;
- licensing/redistribution note;
- status: observed, historical snapshot, unavailable, or unresolved.

Do not infer current validity from an old download URL.

### 5. Explicit reconciliation policy

Encode or document the actual rules for:

- CRS transformation;
- geometry validity repair;
- identifier normalization;
- dissolve and aggregation;
- polygon intersection;
- assignment when multiple units intersect;
- area- or population-weighted tie-breaking;
- slivers and tolerance;
- null or invalid geometries;
- duplicate identifiers;
- unmatched units;
- manual overrides.

Every manual override must have an ID, rationale, evidence note, and reviewer status.

Do not silently use `buffer(0)`, centroid assignment, nearest-neighbor matching, or largest-overlap rules without reporting their effects.

### 6. Coverage and exception reports

Emit deterministic reports containing:

- input and output feature counts;
- counts and shares matched, unmatched, multiply matched, repaired, dropped, and manually overridden;
- coverage by province and geographic level;
- population-weighted coverage only when the population field and vintage are defensible;
- area coverage and overlap when meaningful;
- invalid geometry counts before and after repair;
- all ambiguous and unmatched IDs;
- differences from any committed historical snapshot.

Do not report population coverage from an unrelated vintage without explicit qualification.

### 7. Deterministic geography output

Define and test:

- stable feature ordering;
- identifier types and zero-padding;
- CRS and axis order;
- geometry normalization/precision policy;
- attribute schema;
- serialization settings;
- output naming;
- behavior for empty, invalid, or unsupported geometries.

A repeated fixture release must produce stable semantic content and, where the selected format permits deterministic serialization, identical hashes.

### 8. Artifact manifest

Emit a manifest containing:

- schema and release version;
- release ID;
- declared reference vintage;
- source-registry version and hashes;
- input file hashes;
- environment and library versions;
- producing Git commit and command;
- output CRS and schema;
- feature counts;
- geometry and attribute file hashes;
- coverage and exception report paths/hashes;
- limitations and current-boundary disclaimer.

Conceptually the release should be consumable as a versioned geography artifact, not as an implicit sibling path.

### 9. Historical-input assessment

Create `docs/HISTORICAL_GEOGRAPHY_INPUTS.md` summarizing what remains useful from:

- `Aglomerados-EPH-INDEC`;
- census/electoral crosswalk repositories encountered during characterization;
- historical committed outputs in this repository.

Classify each item as:

```text
adopt as source
adopt after validation
use as regression oracle
methodological evidence only
obsolete or superseded
unresolved
```

Do not modify or modernize those other repositories in this work packet.

## Ordered execution

1. Characterize notebooks, sources, vintages, and existing outputs.
2. Establish the environment and run only non-mutating inspection.
3. Extract stable reconciliation helpers only where this reduces notebook dependence without changing semantics.
4. Add the bounded fixture and characterization tests.
5. Encode source and reconciliation registries.
6. Add deterministic coverage and exception reporting.
7. Produce a fixture release and manifest.
8. Compare the new fixture behavior with historical rules and snapshots.
9. Reconcile README and system declarations with demonstrated behavior.

## Human checkpoints

Stop for review before:

- selecting among conflicting source vintages;
- approving a manual override;
- choosing a substantive tie-breaking rule;
- dropping unmatched geographies;
- replacing a historical snapshot;
- claiming population coverage;
- publishing or labeling a release as current;
- changing geographic identifiers consumed downstream.

## Non-goals

- No national current-boundary refresh unless separately authorized.
- No Atlas deployment.
- No poverty or income modeling.
- No Mapbox upload.
- No bulk migration of all notebooks.
- No mutation of `Aglomerados-EPH-INDEC` or electoral repositories.
- No large geometry commit without explicit review.
- No claim of official geographic authority.

## Stop conditions

Stop rather than guess when:

- a source vintage cannot be established;
- CRS is missing or contradictory;
- different reconciliation rules materially change assignments;
- a topology repair changes geometry beyond a bounded tolerance;
- population weights cannot be tied to the same geographic vintage;
- source rights or redistribution terms are unclear.

## Acceptance criteria

```text
one clean reproducible geospatial environment is documented
bounded offline geography tests pass
source vintages and CRS are explicit
reconciliation and invalid-geometry policies are explicit
coverage, unmatched, ambiguous, repair, and override reports are emitted
one fixture release and manifest are deterministic and checksummed
historical inputs are classified without being silently adopted
README states the supported release and its limitations truthfully
no current-boundary or official-authority claim is made
```

## Completion report

The final response and PR description must state:

- sources and vintages actually inspected;
- environment and exact commands run;
- fixture cases and reconciliation rules tested;
- coverage and exception counts;
- files and outputs produced;
- unresolved source, CRS, topology, or override decisions;
- confirmation that no external repository, production publication, or large live dataset was mutated.
