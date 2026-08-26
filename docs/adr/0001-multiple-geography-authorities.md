# ADR 0001 — Preserve multiple geography authorities

Status: Accepted for the Argentina Geography program.

## Decision

Do not create one canonical/true Argentina geography by overwriting or blending INDEC, CEUR-CONICET, IGN or Tartagalensis identities.

Represent each provider/release as its own Geography Release and create explicit Relation Releases between them when interoperability is needed.

## Rationale

These providers represent different institutional or analytical objects. Differences in boundary geometry, vintage and curation are evidence that may matter scientifically.

## Consequences

- every release carries provider/release/vintage;
- downstream users select an authority appropriate to their question;
- cross-provider conversions are versioned derived products;
- "fix INDEC with IGN" is not an acceptable product description.
