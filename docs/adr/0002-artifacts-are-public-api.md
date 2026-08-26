# ADR 0002 — Artifacts are the stable public API

Status: Accepted for the Argentina Geography program.

## Decision

The stable boundary between Argentina Geography and downstream applications is versioned artifacts, manifests and catalogs. Python/CLI APIs are convenience surfaces for discovering, building and reading those artifacts.

## Rationale

`samplerCensoARG`, `income-modeling-eph`, `indice-pobreza-UBA`, `elecciones-ARG` and third-party research should not require a sibling checkout, repository-relative path or Python import from this producer.

## Consequences

- every scientific handoff is manifest-addressed;
- consumers may remain tabular and GIS-free;
- code refactors inside the producer need not break consumers when product contracts are stable;
- local filesystem paths and notebooks are never product identities.
