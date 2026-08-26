# A6 — Census 2010 backbone handoff

This handoff is the dependency boundary for A7, A9 and A11. It becomes authoritative only after the CEUR V2025-1 bounded PR is merged.

## Stable downstream identity

Both 2010 geography products expose the same zero-preserving consumer field names:

```text
radio_2010_id
department_2010_id
province_2010_id
```

Those names are a join/interface convention, **not** a claim that INDEC and CEUR geometries or authorities are interchangeable.

## Official INDEC parent

```text
dataset_id       arggeo.indec.census.2010.radio
release          2010-national-c9184f47fd46
authority        official
source snapshot  c9184f47fd46c8a47e2c15e5c734b7b6ceb660ce737e18430691f6fbff3c53e8
geography SHA    762b825f27e3b6e8c1c3f63ae2a5f9aecfa80784b0f56d6739755d02ee749019
CRS              EPSG:22183
radios           52,406
departments      525
provinces        24
```

`radio_2010_id` is the official zero-preserving 9-digit `link/LINK`. `department_2010_id` and `province_2010_id` are the first five and first two digits respectively.

The official source snapshot contains 52,408 polygon components because CABA radios `020121607` and `020130104` each have two source components. All components remain preserved; the consumer radio geography aggregates components to the 52,406 unique official radio identities.

A7 must use this exact merged product as its Census 2010 parent.

## CEUR-CONICET V2025-1 parent

```text
dataset_id       arggeo.ceur.census.2010.radio
release          v2025-1-2010-464e9b4c265a
authority        curated_research
source file      RADIOS_2010_V2025-1.zip
source layer     Radios 2010 v2025-1
source SHA       464e9b4c265a27f46a48e0c5914ef4e833c14e8977b8f0c9c1eaad672f374baa
geography SHA    d2095144bc31a34bd09c8fc0a130a872f41016541a8b87daddd52aace759a23e
CRS              EPSG:3857
radios           52,406
analytical       52,394
source-invalid   12
departments      528
provinces        24
```

CEUR native identity is `COD_2010`, with the verified invariant:

```text
COD_2010 == PROV + DEPTO + FRACC + RADIO
```

The stable mapping is `radio_2010_id=COD_2010`, `department_2010_id=PROV+DEPTO`, `province_2010_id=PROV`.

The 12 source-invalid polygons are retained without repair and explicitly excluded from the analytical geometry role.

## Historical count evidence

The repository's old CONICET-derived geometry has 52,401 rows and the old `RADIO.csv` lookup has 52,382 rows. Those counts remain useful historical/regression evidence, but neither is forced onto the current official INDEC or current CEUR V2025-1 products.

## A7 gate

A7 may branch fresh only after this handoff and both A6 authority products are on `main`. For EPH:

- treat official INDEC EPH geography/frame documentation as the authority;
- preserve official radio and agglomerate native IDs;
- prefer an explicit INDEC radio→agglomerate relation over any spatial reconstruction;
- do not infer EPH membership from CEUR `BASICO`, `AMPLIADO`, `TIPO`, or geometry;
- bind the output to the exact official INDEC 2010 parent release above.

Machine-readable equivalent: `docs/A6_CENSUS_2010_HANDOFF.json`.
