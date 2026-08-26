from __future__ import annotations

import hashlib
import json

import geopandas as gpd
import pandas as pd
from empirical_contracts import AuthorityLevel, DataLayer, DatasetRef, GrainSpec

from argentina_geography.electoral.config import _district_bridge
from argentina_geography.electoral.hierarchy import build_electoral_hierarchy
from argentina_geography.electoral.qa import build_province_qa
from argentina_geography.electoral.relation_builders import (
    build_input_status,
    build_nonstandard_coverage_relation,
    build_radio_circuit_relation,
    build_section_department_relation,
)


def _version_payload(
    vintage: str,
    census_dataset: DatasetRef,
    circuit_dataset: DatasetRef,
    config: dict,
) -> str:
    payload = {
        "vintage": vintage,
        "census_dataset": census_dataset.model_dump(mode="json"),
        "circuit_dataset": circuit_dataset.model_dump(mode="json"),
        "relation_ids": {
            key: value.format(vintage=vintage)
            for key, value in config["relation_ids"].items()
        },
        "analysis_crs": config["analysis_crs"],
        "minimum_overlap_area_m2": config["minimum_overlap_area_m2"],
        "district_province_bridge": config["district_province_bridge"],
        "policy_boundary": config["policy_boundary"],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

def _dataset(
    dataset_id: str,
    version: str,
    content_sha256: str,
    grain: tuple[str, ...],
) -> DatasetRef:
    return DatasetRef(
        dataset_id=dataset_id,
        version=version,
        schema_version="arggeo.relation/v1",
        layer=DataLayer.GOLD,
        authority=AuthorityLevel.L2_DERIVED,
        grain=GrainSpec(keys=grain),
        content_sha256=content_sha256,
    )

def _relation_catalog(
    config: dict,
    vintage: str,
    version: str,
    datasets: dict[str, DatasetRef],
    radio_relation: pd.DataFrame,
    section_relation: pd.DataFrame,
) -> pd.DataFrame:
    radio_status = radio_relation.groupby("source_geo_uid")["relation_status"].first()
    section_status = section_relation.groupby(
        "source_electoral_section_uid"
    )["relation_status"].first()
    return pd.DataFrame(
        [
            {
                "relation_id": datasets["radio_circuit"].dataset_id,
                "dataset_id": datasets["radio_circuit"].dataset_id,
                "release_version": version,
                "source_geography_id": "indec:census:2010:radio",
                "target_geography_id": f"tartagalensis:electoral:{vintage}:circuit",
                "relation_type": "areal_overlap",
                "policy_id_or_null": pd.NA,
                "matched_count": int(
                    radio_status.isin(["matched_single", "matched_multiple"]).sum()
                ),
                "ambiguous_count": int(radio_status.eq("matched_multiple").sum()),
                "unmatched_count": int(
                    radio_status.isin(["unmatched_outside", "invalid_geometry"]).sum()
                ),
                "artifact_ref": "relations.parquet",
                "manifest_ref": "manifest.json",
            },
            {
                "relation_id": datasets["section_department"].dataset_id,
                "dataset_id": datasets["section_department"].dataset_id,
                "release_version": version,
                "source_geography_id": f"derived:tartagalensis:{vintage}:section-footprint",
                "target_geography_id": "derived:indec:census:2010:department-footprint",
                "relation_type": "areal_overlap",
                "policy_id_or_null": pd.NA,
                "matched_count": int(
                    section_status.isin(["matched_single", "matched_multiple"]).sum()
                ),
                "ambiguous_count": int(section_status.eq("matched_multiple").sum()),
                "unmatched_count": int(
                    section_status.isin(["unmatched_outside", "invalid_geometry"]).sum()
                ),
                "artifact_ref": "section_department_relations.parquet",
                "manifest_ref": "manifest.json",
            },
            {
                "relation_id": datasets["district_province"].dataset_id,
                "dataset_id": datasets["district_province"].dataset_id,
                "release_version": version,
                "source_geography_id": f"electoral:{vintage}:district",
                "target_geography_id": "indec:census:2010:province",
                "relation_type": "declared_cross_authority_correspondence",
                "policy_id_or_null": pd.NA,
                "matched_count": 24,
                "ambiguous_count": 0,
                "unmatched_count": 0,
                "artifact_ref": "district_province_bridge.parquet",
                "manifest_ref": "manifest.json",
            },
        ]
    )

def build_products(
    census: gpd.GeoDataFrame,
    circuits: gpd.GeoDataFrame,
    vintage: str,
    config: dict,
) -> dict[str, object]:
    bridge = _district_bridge(config, vintage)
    districts, sections, circuits_dim, circuit_footprints, feature_target = (
        build_electoral_hierarchy(circuits, vintage, config)
    )
    radio_relation, radio_audit = build_radio_circuit_relation(
        census, circuit_footprints, bridge, config
    )
    section_relation, section_audit = build_section_department_relation(
        census, circuits, sections, bridge, vintage, config
    )
    nonstandard_relation, nonstandard_audit = build_nonstandard_coverage_relation(
        census, circuits, config
    )
    input_status = build_input_status(census, circuits, feature_target)
    province_qa = build_province_qa(
        census,
        circuits,
        radio_relation,
        section_relation,
        nonstandard_relation,
        sections,
        circuit_footprints,
        bridge,
    )
    qa = {
        "stage_decision": "PASS_WITH_WARNINGS",
        "vintage": vintage,
        "census_radio_count": len(census),
        "raw_tartagalensis_feature_count": len(circuits),
        "electoral_district_count": len(districts),
        "electoral_section_count": len(sections),
        "derived_circuit_target_count": len(circuit_footprints),
        "complete_logical_circuit_count": int(
            circuits_dim["identity_status"].eq("complete_composite").sum()
        ),
        "incomplete_circuit_target_count": int(
            circuits_dim["identity_status"].ne("complete_composite").sum()
        ),
        "radio_circuit": radio_audit,
        "section_department": section_audit,
        "nonstandard_coverage": nonstandard_audit,
        "cross_province_radio_circuit_rows": int(
            (
                radio_relation["target_electoral_uid"].notna()
                & ~radio_relation["province_compatible"].fillna(False)
            ).sum()
        ),
        "cross_province_section_department_rows": int(
            (
                section_relation["target_department_footprint_uid"].notna()
                & ~section_relation["province_compatible"].fillna(False)
            ).sum()
        ),
        "nonstandard_source_feature_count": int(
            (~circuits["source_status"].eq("assigned_circuit")).sum()
        ),
        "nonanalytical_source_feature_count": int(
            (~circuits["geometry_role"].eq("analytical")).sum()
        ),
        "assigned_missing_section_feature_count": int(
            (
                circuits["source_status"].eq("assigned_circuit")
                & circuits["coddepto"].isna()
            ).sum()
        ),
        "adjudication_applied": False,
        "crosswalk_published": False,
        "geometry_repair_applied": False,
    }
    return {
        "bridge": bridge,
        "districts": districts,
        "sections": sections,
        "circuits_dim": circuits_dim,
        "circuit_footprints": circuit_footprints,
        "radio_relation": radio_relation,
        "section_relation": section_relation,
        "nonstandard_relation": nonstandard_relation,
        "input_status": input_status,
        "province_qa": province_qa,
        "qa": qa,
    }

def _summary_text(
    vintage: str,
    qa: dict,
    datasets: dict[str, DatasetRef],
    census_dataset: DatasetRef,
    circuit_dataset: DatasetRef,
    evidence_summaries: dict,
) -> str:
    return f"""# Argentina Geography electoral vertical — {vintage}

This release models the electoral hierarchy as an authority namespace parallel to
Census/statistical geography. It does **not** rename electoral sections into Census
departments or collapse electoral district codes into Census province codes.

## Exact parents

- Census: `{census_dataset.dataset_id}@{census_dataset.version}`
- Circuits: `{circuit_dataset.dataset_id}@{circuit_dataset.version}`

## Published relation products

- `{datasets['district_province'].dataset_id}` — explicit 24-row cross-authority bridge.
- `{datasets['section_department'].dataset_id}` — N:M derived section-footprint ↔
  Census-2010 department-footprint overlap facts.
- `{datasets['radio_circuit'].dataset_id}` — N:M Census-radio ↔ electoral-circuit
  overlap facts.

## QA

- Census radios: **{qa['census_radio_count']:,}**
- Electoral districts: **{qa['electoral_district_count']:,}**
- Electoral sections observed from the circuit source: **{qa['electoral_section_count']:,}**
- Derived circuit relation targets: **{qa['derived_circuit_target_count']:,}**
- Incomplete circuit identities retained at source-feature grain:
  **{qa['incomplete_circuit_target_count']:,}**
- Cross-province radio↔circuit positive rows:
  **{qa['cross_province_radio_circuit_rows']:,}**
- Cross-province section↔department positive rows:
  **{qa['cross_province_section_department_rows']:,}**

## Interpretation boundary

`codprov`, `coddepto`, and `circuito` remain Tartagalensis provider-native fields.
Semantic aliases are published through hierarchy artifacts as electoral district,
section, and circuit codes. Census province/department/radio identifiers remain INDEC
identities. Spatial overlap, historical policy comparisons, and consumer key
compatibility never rewrite either namespace.

Historical one-target policies are preserved only in
`historical_policy_registry.json` and optional regression evidence. No current
winner/nearest/largest-overlap crosswalk is published.

Evidence summaries:

```json
{json.dumps(evidence_summaries, ensure_ascii=False, indent=2, sort_keys=True)}
```
"""
