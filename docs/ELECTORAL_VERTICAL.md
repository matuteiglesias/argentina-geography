# Electoral vertical — authoritative contract

Status: **active design for A9 and later electoral work**.

This document supersedes the earlier narrow A9 brief that described A9 only as a
Census-radio ↔ circuit overlay. The updated architecture treats Argentine electoral
territory as a parallel authority namespace and carries forward the durable capability
found in `censo2010-circuitos-electorales` without importing its implicit adjudications.

## Why the vertical exists

Argentina exposes two analogous but independent territorial hierarchies:

```text
Census/statistical                     Electoral

province                               district
department / partido / comuna         section
fraction                               circuit
radio                                  mesa / election event
```

The hierarchies often correspond closely. They are not interchangeable identity
systems.

Examples already observed in historical work:

- Census province codes `02, 06, 10, ... 94` coexist with electoral district codes
  `01..24`;
- historical section→department bridges had to be computed explicitly;
- Lezama/Chascomús, CABA, Tierra del Fuego and other cases exposed source-vintage or
  authority differences;
- historical code used more than one one-target rule to turn ambiguous
  section↔department relations into operational mappings.

Therefore a code or name coincidence is never sufficient evidence of shared identity.

## What Argentina Geography owns

### Source-faithful electoral geography

A8 publishes exact pinned Tartagalensis circuit geography releases for 2021 and 2025.

The provider-native identity remains:

```text
codprov
coddepto
circuito
```

The minimum complete logical circuit identity is the composite of all three fields.
`circuito` alone is not globally unique. Missing `coddepto`, no-data polygons, grey
zones, source-invalid/unreadable geometry and reconstructed/curated limitations remain
observable.

### Electoral hierarchy artifacts

From an exact circuit release Argentina Geography may expose normalized hierarchy
dimensions:

```text
electoral district
electoral section
electoral circuit
```

These are semantic aliases/derived identities for the electoral namespace. They do not
turn `codprov` into an INDEC province code or `coddepto` into an administrative
department code.

A logical circuit footprint may union multiple physical source features that share a
complete circuit identity. This is a derived footprint for relation computation; source
features remain inspectable.

An assigned circuit with incomplete composite identity may remain usable at pinned
source-feature relation grain, with the incomplete identity explicit.

### District ↔ province relation

The 24 electoral districts and 24 Census provinces have an explicit curated
cross-authority correspondence. It is published as a relation/bridge with both native
codes, never by numeric equality.

Historical `provs.csv`, Tartagalensis district metadata and current `elecciones-ARG`
dimension evidence are regression/corroboration sources for this bridge. None of those
turns the two namespaces into one namespace.

### Section ↔ department relation

Electoral section and Census/administrative department correspondence is N:M before
interpretation.

For the A9 Census-2010 vertical, current section footprints are derived from exact
assigned Tartagalensis circuit geometry and current department footprints are derived
from exact official INDEC Census 2010 radio geometry. The product is therefore named as
a relation between **derived footprints**, not as an official section or department
boundary release.

A later IGN product may add a separate section↔IGN-department relation. It must not
rewrite the Census-derived relation.

### Radio ↔ circuit relation

A9 publishes direct metric-CRS overlap facts between exact official Census 2010 radios
and exact pinned 2021/2025 electoral circuit products.

The relation is N:M. It retains:

- positive overlap facts;
- multiplicity;
- unmatched radios;
- invalid/unusable inputs;
- province/district compatibility QA;
- nonstandard source territory as separate coverage evidence.

No largest-overlap target is selected.

## Historical policies

`censo2010-circuitos-electorales` is a valuable scientific regression archive. Its
durable policies are named explicitly:

1. `historical.largest-overlap.radio-to-circuit`
   - one circuit chosen per radio using largest polygon overlap;
2. `historical.majority-circuit-count.section-to-department`
   - one administrative department chosen for a section using the largest count of
     circuit features;
3. `historical.majority-radio-count.section-to-department`
   - one administrative department chosen for a section using the largest count of
     intersecting Census radios.

These policies remain `regression_only` unless a future consumer explicitly adopts one
through a separate governed crosswalk product.

A9 may compare historical assignments with current relation candidates and current
metric-area maxima. Such a comparison is diagnostic evidence, not publication of a new
winner.

## `elecciones-ARG` boundary

`elecciones-ARG` is a downstream election-domain system.

Argentina Geography owns geographic/electoral territorial identities and relation
products that can simplify it.

`elecciones-ARG` continues to own:

- `eleccion_id` and election-event identity;
- vote/recount/padron semantics;
- candidacies, lists and cargos;
- mesa-level facts;
- election-specific dimensions such as `seccionprovincial_id` unless an independent
  geographic authority is later adopted.

A9 publishes a read-only compatibility proof against a pinned `elecciones-ARG` circuit
table. The proof may project source electoral codes into the consumer's formatting
conventions (for example numeric circuit zero-padding) and measure matches. It does not
make `elecciones-ARG` the geography authority and does not rewrite source identity.

## A9 deliverables

For **each** of 2021 and 2025 A9 publishes one electoral-vertical release containing:

- `electoral_districts.parquet`
- `electoral_sections.parquet`
- `electoral_circuits.parquet`
- `district_province_bridge.parquet`
- `section_department_relations.parquet`
- `relations.parquet` — Census radio ↔ electoral circuit
- `nonstandard_coverage_relations.parquet`
- `input_status.parquet`
- `province_qa.parquet`
- `relation_catalog.parquet`
- `historical_policy_registry.json`
- `qa.json`
- `summary.md`
- `manifest.json`

When exact external regression/consumer inputs are supplied, the release also carries:

- historical radio-assignment comparison;
- historical section→department comparison;
- `elecciones-ARG` key compatibility evidence.

No crosswalk artifact is published by default.

## Stop conditions

Stop rather than invent policy if:

- a complete electoral identity cannot be interpreted from the source;
- a source-vintage difference requires deciding which authority is “correct”;
- a one-target assignment is needed to make a result pass;
- a geometry repair would change substantive source meaning;
- an election-specific semantic is required but only geography evidence is available.

## Legacy repository disposition

After A9 live proof succeeds:

### Capability expected to be superseded by `argentina-geography`

- pinned electoral circuit acquisition through the adopted Tartagalensis releases;
- explicit electoral district/province namespace bridge;
- section↔department relation facts;
- Census-radio ↔ circuit relation facts;
- province coverage/multiplicity QA;
- reproducible historical-assignment regression;
- downstream electoral-key compatibility proof.

### Capability that may remain only as archive/regression evidence

- historical notebooks;
- historical derived CSV snapshots;
- old source-era manual diagnostics;
- implicit one-target policy experiments.

### Capability that should stay elsewhere

- election results, mesas, candidates and election-event modeling → `elecciones-ARG`;
- generic geometry mechanics → `spatial-data-foundation`;
- future official/IGN administrative releases → their own Argentina Geography source
  products/relations.

Once the new releases are evidence-backed and detached-verifiable,
`censo2010-circuitos-electorales` can be frozen as a historical archive rather than
remaining an operational dependency.
