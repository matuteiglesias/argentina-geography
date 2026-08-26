# A7 handoff — official INDEC EPH Census-2010 frame

A7 is complete after merge with one official, directly declared EPH radio/agglomerate frame product.

## Dependency identity

```text
arggeo.indec.eph.census2010.radio_frame@census2010-frame-9b372c33aa68
source snapshot: 9b372c33aa6827705e354f9be3545bf80bd668e44acfb602b6b63aabbe2704b8
frame:           ea0f5a749cfe0863e71d06064814d003607a43547398d0baa192aea26b18f675
geography:       243a448071bf03e08d69208b585a7e63f22a228a8ac5fba5e1ff44f07a899b68
components:      d48e06c98cebfc59ddd61830f294689107eebd40967b3f148c8ba5d6b54f28f3
direct mapping:  2fdf263982639b6dc7ebfbeeaec3cecc971801debe8adde6ba48043e48641052
```

Stable Census-2010 IDs are `radio_2010_id`, `department_2010_id`, and `province_2010_id`. Official EPH identity is `eph_agglomerate_id`, directly normalized from native `eph_codagl`.

The frame has 26,417 radios and 32 native agglomerate codes. It preserves all 26,815 source rows separately. Three source radios lack geometry (`020011704`, `020011706`, `500281605`) and are retained explicitly rather than filled or dropped.

## Exact A6 parent

A7 is proven against `arggeo.indec.census.2010.radio@2010-national-c9184f47fd46`, content SHA-256 `762b825f27e3b6e8c1c3f63ae2a5f9aecfa80784b0f56d6739755d02ee749019`. All A7 radio IDs are present in the 52,406-radio A6 identity set.

## Consumer boundary

`income-modeling-eph` commit `48cf614fc6e05c1b4b0b595dfe949dcbe8b1e138` can reference the release tabularly through `AGLOMERADO = int(eph_agglomerate_id)`. No GIS logic or scientific-model change is required.

A9/A11 should bind the exact IDs and hashes above rather than re-deriving A7 identity. The EPH mapping is a direct official source relation, not a spatial crosswalk.

Evidence: `docs/source-evidence/indec-eph-census2010-frame-2026-08-26.json`. Live source + detached verification run: `32928410734`. General CI: `32928413472`.
