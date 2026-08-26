# Tool promotion policy

Argentina Geography is allowed to incubate new spatial audits/helpers needed to build its products. This is intentional. It prevents speculative bloat in `spatial-data-foundation` while giving real workflows room to discover reusable primitives.

## Promotion lifecycle

```text
Argentina-specific need
        |
        v
implement locally with explicit domain boundary
        |
        v
use in >= 2 independent source/product families
        |
        v
separate all provider/domain assumptions
        |
        v
prove generic behavior with synthetic fixtures
        |
        v
candidate upstream PR to spatial-data-foundation
        |
        v
remove local duplicate after release adoption
```

Promotion is not copy/paste. The final step is replacement of the local helper by the released generic primitive.

## Eligibility tests

A helper is eligible for promotion only if all are true:

1. **Independent reuse:** at least two distinct provider/product workflows need the same mechanic (for example INDEC↔CEUR and Tartagalensis topology), not two calls inside one adapter.
2. **No Argentine ontology:** its API does not contain `cod_indec`, province codes, EPH agglomerates, circuit identifiers or provider names.
3. **Generic inputs/outputs:** ordinary GeoDataFrames/arrays plus neutral parameters are sufficient.
4. **Semantics are geometric/mechanical:** the helper reports facts, not domain ownership, scientific validity or policy decisions.
5. **Synthetic contract:** behavior can be completely tested with synthetic geometry.
6. **Measured need:** the abstraction removes real duplication or establishes a shared invariant. "Might be useful" is insufficient.
7. **Small API:** adding the helper does not require a provider framework or large new configuration system upstream.

## Likely incubation candidates

These are hypotheses, not commitments.

### Partition topology audit

Potential facts:

```text
invalid/empty geometry count
internal overlap area/count
gap area against explicit reference boundary
coverage share
boundary-only contacts
```

A source-specific interpretation such as "INDEC adjustment radio 00 is allowed" remains downstream.

### Geography comparison

Potential generic facts:

```text
left-only identity
right-only identity
same identity / exact-equivalent geometry
same identity / changed geometry
symmetric-difference area
changed share
```

Provider identity matching and what constitutes a meaningful change remain outside.

### Two-sided areal overlap facts

`spatial-data-foundation` currently exposes source-side overlap share. Cross-vintage work may justify target-side share/count as a generic extension.

### Bounded topology presentation

If multiple independent workflows repeatedly need the same neutral inspection map mechanics, a small presentation helper may be eligible. Provider-specific annotations remain here.

## Non-promotable examples

Keep in Argentina Geography:

- zero-padding/slicing INDEC codes;
- Tartagalensis circuit key construction;
- deciding that a circuit snapshot is compatible with an election;
- treating a CEUR release as preferred for a longitudinal analysis;
- Censo→IGN winner thresholds;
- EPH agglomerate interpretation;
- Argentine province exceptions;
- source-specific download URLs/schema parsing.

Keep in downstream science:

- population allocation across overlap shares;
- poverty-region policy;
- electoral inference;
- modeled socioeconomic aggregation;
- treatment/exposure definitions.

## Upstream PR standard

An upstream proposal to `spatial-data-foundation` should include:

- two concrete independent downstream uses;
- the local duplicated implementations being replaced;
- neutral API and invariants;
- adversarial synthetic tests;
- performance evidence if it touches relation hot paths;
- explicit non-goals;
- downstream migration plan.

Do not create an upstream issue solely to reserve a future idea.

## A11 promotion assessment — two-sided areal overlap facts

A11 confirms that the `Two-sided areal overlap facts` hypothesis above is now a measured reuse case rather than a speculative one.

The same neutral mechanics are implemented locally in three independent Argentina Geography products:

- A5 INDEC 2022 ↔ CEUR 2022: target-side overlap share and target multiplicity are needed to distinguish mutual geometry agreement from one-sided containment;
- A10 INDEC 2022 radio ↔ IGN department: target-side share, target multiplicity and two-sided coverage are needed for bounded administrative-relation QA;
- A11 CEUR 2010 ↔ CEUR 2022: target-side share and target multiplicity are required to distinguish split, merge and genuinely N:M longitudinal structure.

The repeated mechanic has no Argentine ontology: given positive areal overlap rows plus target polygon areas, compute `overlap_share_of_target` and target-side overlap counts. Synthetic fixtures cover the behavior. This therefore satisfies the policy's independent-reuse, generic-input, geometric-semantics, synthetic-contract and measured-need tests.

**Assessment:** eligible for a future small `spatial-data-foundation` proposal, ideally as an extension of `relate_areal_objects` or a neutral post-processing helper that emits two-sided shares/counts. A11 deliberately keeps the implementation local because this thread does not own upstream foundation changes. Any promotion should separately benchmark the relation hot path and then replace the A5/A10/A11 local duplicates after a released foundation version is adopted.

The connected-component inspection used only to select A11's human-readable `stable/split/merge/complex` examples is **not yet proposed for promotion**. It currently serves one longitudinal interpretation artifact and has not demonstrated independent reuse.
