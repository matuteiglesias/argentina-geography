# Researcher interface

The project should be useful to a researcher who has never seen the historical repositories.

This document describes the target user experience; commands are roadmap contracts until implemented.

## Five-minute path

Target installation:

```bash
pip install argentina-geography
```

Discovery:

```bash
arggeo geography list
arggeo relation list
arggeo sources list
```

Inspect one released product:

```bash
arggeo geography inspect indec:census:2022:radio
```

Fetch/materialize it according to the source's allowed distribution mode:

```bash
arggeo geography fetch indec:census:2022:radio --output ./data/arggeo
```

Verify an existing local bundle:

```bash
arggeo verify ./data/arggeo/<release>/
```

Discover bridges from one geography:

```bash
arggeo relation list --from indec:census:2010:radio
```

The CLI is a convenience surface over manifests/catalogs. Do not make the CLI itself the only route to the data contract.

## Python path

Keep the public Python API small. A future interface may look like:

```python
from argentina_geography import catalog

g = catalog.geography("indec:census:2022:radio")
r = catalog.relation(
    "indec:census:2010:radio",
    "tartagalensis:electoral:2025:circuit",
)
```

Return paths/manifest objects or ordinary pandas/GeoPandas objects. Do not build an alternative spatial dataframe abstraction.

## Researcher workflows

### Use one official geography

A demographer who needs 2022 Census radios should be able to obtain the INDEC release, inspect native codes and cite the source without learning anything about CEUR or IGN.

### Compare two authorities

A geographic-methods researcher should be able to request an INDEC↔CEUR relation/comparison release and inspect differences without one provider being silently declared correct.

### Translate observations across vintages

A longitudinal researcher should be able to use a 2010↔2022 relation with explicit N:M overlap weights rather than receiving a fabricated one-to-one dictionary.

### Add electoral context

A political scientist should be able to combine a Census radio product with a Tartagalensis circuit product and use an explicit relation/crosswalk release.

### Use EPH geography without GIS

An EPH modeler should be able to consume an official radio/agglomerate mapping as a table without importing GeoPandas.

## Documentation requirements per product

Every released geography should expose, in human-readable form:

- what it represents;
- provider/source;
- vintage/release;
- native IDs;
- known coverage and exclusions;
- geometry caveats;
- attribution/citation;
- redistribution mode;
- how to verify the artifact;
- whether it is official, curated or derived.

Every relation should explain:

- exact parent geographies;
- relation algorithm/version;
- analysis CRS;
- positive-overlap threshold;
- unmatched/multi-match semantics;
- whether any adjudication policy was applied.

## Citation

The project should never cause users to cite only `argentina-geography` when the substantive geography comes from INDEC, CEUR, IGN or Tartagalensis.

A release should provide both:

1. source citation/attribution;
2. producer/software/release citation when useful.

## Network behavior

Ordinary validation and tests are offline.

Source retrieval is explicit. A command that accesses a live provider must say so, record the exact bytes/layer/response it received and create a snapshot identity before downstream normalization.

No import-time or test-time downloads.

## Data size

Do not commit large national GeoJSON derivatives merely because they are convenient examples.

Use small synthetic fixtures in Git; real artifacts are release outputs or external immutable materializations.

## Failure UX

Prefer messages like:

```text
Source schema changed: expected cod_indec,cpr,cde,cfn,cro; received ...
No release built. Re-inspect provider metadata before updating the adapter.
```

rather than silently renaming/guessing fields.

A user should be able to tell the difference between:

- no source coverage;
- failed acquisition;
- invalid geometry;
- no relation;
- ambiguous relation;
- unsupported crosswalk policy.
