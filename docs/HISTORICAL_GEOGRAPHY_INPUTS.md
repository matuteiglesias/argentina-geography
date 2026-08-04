# Historical geography input assessment

Assessment date: 2026-08-04. This classification does not confer authority, currency, or redistribution rights.

| Item | Classification | Reason and validation gate |
|---|---|---|
| Committed 1991/2001/2010 CEUR-CONICET radio shapefiles/RARs | **adopt after validation** | Valuable census-vintage geometry, but provenance chain, license, exact publication version, checksums against publisher, topology, and identifier completeness require review. |
| `censos_db_ref/` census lookup CSVs | **adopt after validation** | Useful identifier/name evidence; publisher, extraction procedure, encoding, uniqueness, and counts must be established. |
| Dissolved 1991/2010 shapefiles | **use as regression oracle** | They preserve historical output behavior, including a one-metre buffer that v1 refuses to adopt silently. No 2001 dissolved snapshot is committed. |
| `info/crosw_*`, `info/info*` | **methodological evidence only** | They reveal affected units and intended crosswalk structure, but lack override IDs, rationale/evidence per row, reviewer state, and reproducible generation. |
| `info/censo10_IGN_ref.geojson` | **use as regression oracle** | Historical overlay output with 525 features; its embedded CRS declaration is contradictory and exact IGN vintage is unknown. |
| IGN department download referenced by notebooks | **unresolved** | Files are absent. Exact vintage, checksum, published CRS and redistribution terms cannot be established from the URL. |
| `matuteiglesias/Aglomerados-EPH-INDEC` | **unresolved** | No checkout or immutable snapshot was available inside this repository/environment. Do not infer EPH-agglomerate membership or adopt it without a pinned commit, source lineage, rights review, and census-vintage validation. |
| Census/electoral crosswalk repositories | **unresolved** | None is identified or checked out here. No rule was imported. Future inspection must be read-only and pin the repository and commit. |
| `Notebook.ipynb` and notebook checkpoints | **methodological evidence only** | Preserve historical intent; absolute paths, partial ordering and deliberate stop cells preclude reproduction. |
| Fixture inputs and release | **adopt as source** | Synthetic, bounded, self-contained test data only; never a source for substantive Argentine geography. |

## Decisions deliberately deferred

No conflicting real source vintage was selected. No manual override was approved. No historical identifier was changed. No unmatched real geography was dropped. No population claim is made. Before a live release, a human checkpoint must resolve the IGN vintage/CRS/license, CEUR-CONICET redistribution terms, checksums, topology tolerances, historical override evidence, and any tie-breaking rule whose choice changes assignments.

No external repository was modified or modernized during this assessment.
