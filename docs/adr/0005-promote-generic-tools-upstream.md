# ADR 0005 — Incubate locally, promote generic tools upstream by evidence

Status: Accepted for the Argentina Geography program.

## Decision

New topology/comparison/audit helpers required by Argentine geography products may be implemented first in this repository. Promote a helper to `spatial-data-foundation` only after it is used by at least two independent source/product families, contains no Argentine/provider semantics and can be specified/tested generically.

After upstream release adoption, remove the local duplicate.

## Rationale

This gives real workflows room to discover useful primitives without turning `spatial-data-foundation` into a speculative GIS framework.

## Consequences

Likely candidates include partition topology audit, geography diff and two-sided overlap facts, but none is pre-approved. Provider adapters, identifier rules and domain adjudication policies never promote upstream.
