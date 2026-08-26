# Repository and lineage characterization

**Inspection date:** 2026-08-04. **Scope:** committed repository contents only. No download URL was treated as evidence of current validity. “Observed” below means inspected locally, not endorsed as authoritative.

## Executable inventory and intended order

1. `legacy/notebooks/01 - Descarga de geometrias (IGN, Censo CONICET).ipynb` downloads the three CEUR-CONICET RARs and an IGN department ZIP, installs unpacking tools from inside a cell, disables TLS verification for one request, and extracts into `censos_shp_CONICET/` and `IGN_shp/`. It is historical acquisition evidence, **not a supported executable**.
2. `legacy/notebooks/02 - Disolución de áreas del Censo.ipynb` reads the census radios, applies a one-metre buffer, repairs the 2010 Formosa department field from `COD_2010[2:5]`, dissolves by province/department/fraction and then province/department, and writes shapefiles under `censos_shp_CONICET_dissolved/`. It contains useful logic but the unconditional buffer changes geometry and is not adopted by v1.
3. `legacy/notebooks/03 - Radios censales en Departamentos IGN.ipynb` reads reference CSVs and both geometry families, reprojects census departments to the IGN CRS for an initial overlay, overlays changed departments/radios, selects the largest intersection, applies identifier repairs, and writes `radios_IGN_<year>`. It contains deliberate stop cells (`xx`), inconsistent relative paths, manual crosswalk preparation, and plotting; it is not end-to-end executable.
4. `legacy/notebooks/Notebook.ipynb` is an older exploratory predecessor, with absolute `/media/...` inputs, sibling-repository IGN paths, repeated/partially ordered code and stop cells. Preserve it as methodological evidence only.
5. Historical `.ipynb_checkpoints/*` entries were redundant editor snapshots, not additional pipeline stages; they were removed from the active tree during repository-root cleanup.
6. `src/censo_geo/release.py` is the sole supported Batch 1 executable. It reads only the bounded fixtures and registries, transforms both inputs into EPSG:3857, validates/repairs, intersects, reports, transforms output to CRS84, normalizes and serializes. It never downloads or mutates historical inputs.

## Sources, paths, formats, vintages, and CRS

The complete machine-readable account is `config/source_registry.json`. Key evidence:

| Input | Observed path/reference | Format | Vintage evidence | CRS evidence | Status |
|---|---|---|---|---|---|
| Census radios | `censos_shp_CONICET/{1991,2001,2010}_RADIOS ARGENTINA/` and committed RARs | ESRI Shapefile/RAR | names, `COD_<year>` and census reference tables establish census year, but publication/retrieval dates are unknown | every `.prj` says POSGAR 94 Argentina zone 3, best matched to EPSG:22183; this is an evidence-based identification, not a publisher EPSG declaration | historical snapshot; rights unresolved |
| Census reference tables | `censos_db_ref/{year}/*.csv` | semicolon CSV | directory/table names: 1991, 2001, 2010 | not spatial | historical snapshot; publisher/acquisition metadata unresolved |
| IGN departments | notebook URL and missing `IGN_shp/`; notebook also references sibling paths | ZIP/Shapefile | **unknown**; URL alone does not establish vintage | **unknown** because downloaded files are absent | unresolved/unavailable locally |
| Derived dissolved census geography | `censos_shp_CONICET_dissolved/` | Shapefile | filenames say 1991/2010; 2001 outputs absent | `.prj`: POSGAR 1994 Argentina zone 3 | historical derived snapshot |
| Crosswalk/support files | `info/*.csv`, `info/censo10_IGN_ref.geojson` | CSV/GeoJSON | year in names; authorship/review state absent | GeoJSON embeds a compound/legacy CRS name mentioning EPSG:4326 and ESRI:105700, which is contradictory/unsafe for reuse | regression oracle only |
| Batch 1 fixtures | `fixtures/*.geojson` | GeoJSON | synthetic fixture-v1 | units CRS84; candidates EPSG:3857 | observed, redistributable synthetic data |

The acquisition notebook references HTTP CEUR URLs and HTTP/HTTPS IGN URLs. None were revalidated. The exact IGN snapshot used historically, its checksum, CRS, and licensing note remain unresolved, so this release does not adopt it.

## Operations and implicit decisions

Historical code performs identifier zero-padding; a hard-coded `60441` → `06441` repair; exclusion of `94021` and `94028`; reconstruction of 2010 Formosa department IDs from the compound code; a 2010 CABA code multiplication; one-metre polygon buffering; dissolve/union; reprojection; overlay/intersection; and largest-area assignment. Another exploratory branch first accepts same-code departments only where two intersection/area ratios are within 0.1 of unity. There is **no nearest-neighbour operation**. No complete, reviewed override register explains all CSV crosswalk rows. Silent row dropping (`dropna`), warning suppression, manual plotting, directory creation, archive extraction, crosswalk editing, and deliberate `xx` errors are implicit steps.

The supported fixture policy differs deliberately: `make_valid` is reported, no buffer/centroid/nearest operation occurs, duplicate occurrences are all excluded, only positive intersections above tolerance count, a unique largest overlap must cover at least half the input, and ties remain ambiguous. These are fixture rules, not approval to replace historical semantics. `config/reconciliation_policy.json` is normative.

## Current output inventory and the 52,401 claim

Committed geometry includes census-radio shapefile snapshots (DBF header counts: 40,160 for 1991; 46,591 for 2001; **52,401 for 2010**), dissolved 1991 departments/fragments, dissolved 2010 departments/fragments, and a 525-feature `info/censo10_IGN_ref.geojson`. There are no committed `radios_IGN_<year>` outputs.

The README’s historical **52,401 unique units** is directly supported as a feature count by the committed 2010 shapefile DBF header. It is not independently established as a unique-ID count: the 2010 reference `RADIO.csv` has 52,383 physical lines including the header (52,382 data rows). Thus 52,401 is documented as the historical geometry feature count, while uniqueness and the CSV discrepancy remain unresolved. Batch 1 explicitly reports no comparable historical fixture snapshot.

## Environment assumptions and preservation decision

The notebooks assume Jupyter/IPython, pandas, GeoPandas, Matplotlib, GDAL/Fiona, Shapely, PyProj, requests, RAR extraction via `pyunpack`/`patool`, network access, writable sibling directories, and source files absent from this repository. Their saved kernels show a former Python 3.11 environment but do not pin library versions.

Preserve: compound-code slicing, zero-padding, the evidence of known Formosa/CABA/La Plata issues, explicit CRS reprojection before overlay, dissolve group keys, intersection measurement, and missing-unit checks. Treat as exploratory or unsafe until reviewed: runtime package installation, disabled TLS checks, absolute/sibling paths, warnings suppression, `buffer(1)`, unconditional largest-overlap selection, silent null drops, plotting loops, and manually prepared CSVs without override records.

## Batch 1 robustness boundaries

`fixture-v1` uses largest overlap only as an explicitly versioned synthetic-fixture policy. Deterministic execution is not evidence that the rule is substantively correct for Argentina. Any real-data threshold or tie-break requires human approval and a new methodology version recorded in the policy and manifest.

Repair auditing records the validity reason, before/after geometry type and part count, before/after area, absolute/relative delta, empty status, and tolerance outcome. Relative tolerance applies to positive-area inputs; an explicit absolute tolerance applies to effectively zero-area inputs. Exceeding either fails before publication.

The manifest includes a byte SHA-256 for exact artifact reproduction plus semantic geometry and semantic content SHA-256 values. Semantic hashing independently normalizes precision, ring orientation and starting vertex, multipart/hole order, feature order, and attribute order. This reduces—but cannot eliminate—cross-build differences caused by PROJ transforms or GEOS algorithms; byte determinism remains required within the pinned supported environment.

Coverage distinguishes a mutually exclusive terminal partition from orthogonal flags such as multi-match and repair, allowing every input occurrence to reconcile without treating flags as terminal outcomes.
