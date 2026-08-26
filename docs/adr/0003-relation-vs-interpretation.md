# ADR 0003 — Separate relation facts from interpretation

Status: Accepted for the Argentina Geography program.

## Decision

Geometric relations and policy-dependent crosswalks are distinct products.

A Relation Release reports spatial facts such as positive intersection area and overlap shares. It may remain many-to-many.

A Crosswalk/Interpretation Release may select or classify relations only under an explicit, versioned policy and must identify its parent relation.

## Rationale

Largest-overlap winners, thresholds and tie breaks are substantive choices. Embedding them inside generic spatial joins makes ambiguity invisible and blocks reuse for other scientific purposes.

## Consequences

- relation artifacts never imply ownership/allocation;
- ambiguity and multiple candidates survive to QA;
- different scientific consumers can derive different governed interpretations from one relation;
- generic relation mechanics remain promotable to `spatial-data-foundation`.
