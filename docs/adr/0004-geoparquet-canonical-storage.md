# ADR 0004 — Prefer GeoParquet/Parquet for analytical artifacts

Status: Accepted direction; individual source waves may document exceptions.

## Decision

Prefer GeoParquet for canonical analytical geography releases and Parquet for relation/crosswalk tables. Use JSON for manifests/QA/catalogs. Treat GeoJSON as an interchange or presentation derivative unless it is retained as exact Bronze source material.

## Rationale

National radio/circuit layers and many-to-many relation tables are large. GeoParquet supports efficient typed storage and column projection, while tabular consumers can avoid loading geometry.

## Consequences

- historical large GeoJSON/shapefiles remain evidence but are not the target interchange format;
- a source-native format can be preserved in Bronze without becoming the normalized Silver format;
- deterministic verification relies on manifested hashes/schema/content checks rather than assuming textual GeoJSON is the only reproducible representation.
