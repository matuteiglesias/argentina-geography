from __future__ import annotations

import geopandas as gpd
import pandas as pd
from spatial_foundation.geography import relate_areal_objects

from argentina_geography.electoral.hierarchy import (
    _department_footprints,
    _section_footprints,
)


def _empty_relation(source_ids: pd.Series, source_id_col: str, target_id_col: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            source_id_col: source_ids.astype(str),
            target_id_col: pd.Series([pd.NA] * len(source_ids), dtype="string"),
            "overlap_area_m2": 0.0,
            "overlap_share_of_source": 0.0,
            "overlap_share_of_target": pd.Series([pd.NA] * len(source_ids), dtype="Float64"),
            "source_candidate_count": 0,
            "relation_status": "unmatched_outside",
        }
    )


def _relate(
    source: gpd.GeoDataFrame,
    target: gpd.GeoDataFrame,
    *,
    source_id_col: str,
    target_id_col: str,
    config: dict,
) -> tuple[pd.DataFrame, dict]:
    """Relate objects after making analysis-CRS geometry eligibility explicit.

    The foundation kernel validates target polygons in their input CRS and then projects
    internally for metric intersections. A source-valid polygon can become invalid after
    projection, especially after a derived union. A9 therefore projects *copies* first,
    records any target that becomes invalid in the analysis CRS, and calls the unchanged
    foundation kernel on those metric copies. Parent and derived source geometries are
    never repaired or overwritten.
    """
    source_nonnull = source.loc[source.geometry.notna()].copy()
    target_nonnull = target.loc[target.geometry.notna()].copy()
    analysis_crs = config["analysis_crs"]

    source_metric = source_nonnull[[source_id_col, "geometry"]].to_crs(analysis_crs)
    target_metric = target_nonnull[[target_id_col, "geometry"]].to_crs(analysis_crs)

    target_analysis_valid = (
        target_metric.geometry.notna()
        & ~target_metric.geometry.is_empty
        & target_metric.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
        & target_metric.geometry.is_valid
    )
    invalid_target_ids = (
        target_metric.loc[~target_analysis_valid, target_id_col]
        .astype(str)
        .sort_values()
        .tolist()
    )
    target_metric_eligible = target_metric.loc[target_analysis_valid].copy()

    if target_metric_eligible.empty:
        relation = _empty_relation(source[source_id_col], source_id_col, target_id_col)
        if source.geometry.isna().any():
            missing_source_ids = set(
                source.loc[source.geometry.isna(), source_id_col].astype(str)
            )
            relation.loc[
                relation[source_id_col].astype(str).isin(missing_source_ids),
                "relation_status",
            ] = "invalid_geometry"
        return relation, {
            "input_objects": len(source),
            "input_targets": len(target_nonnull),
            "analysis_eligible_targets": 0,
            "target_analysis_invalid_geometry": len(invalid_target_ids),
            "target_analysis_invalid_ids": invalid_target_ids,
            "matched_single": 0,
            "matched_multiple": 0,
            "unmatched_outside": int(relation["relation_status"].eq("unmatched_outside").sum()),
            "invalid_geometry": int(relation["relation_status"].eq("invalid_geometry").sum()),
            "relation_rows": 0,
        }

    relation, audit = relate_areal_objects(
        source_metric,
        target_metric_eligible,
        object_id_col=source_id_col,
        polygon_id_col=target_id_col,
        area_crs=analysis_crs,
        min_overlap_area_m2=float(config["minimum_overlap_area_m2"]),
    )
    relation = relation.rename(
        columns={
            "overlap_share_of_object": "overlap_share_of_source",
            "overlap_count": "source_candidate_count",
        }
    )

    target_area = target_metric_eligible.set_index(target_id_col).geometry.area
    positive = relation[target_id_col].notna()
    relation["overlap_share_of_target"] = pd.Series(
        pd.NA, index=relation.index, dtype="Float64"
    )
    if positive.any():
        area = relation.loc[positive, target_id_col].map(target_area).astype(float)
        relation.loc[positive, "overlap_share_of_target"] = (
            relation.loc[positive, "overlap_area_m2"].astype(float).to_numpy()
            / area.to_numpy()
        )

    missing_source_ids = set(source[source_id_col].astype(str)) - set(
        relation[source_id_col].astype(str)
    )
    if missing_source_ids:
        missing = _empty_relation(
            pd.Series(sorted(missing_source_ids)), source_id_col, target_id_col
        )
        missing["relation_status"] = "invalid_geometry"
        relation = pd.concat([relation, missing], ignore_index=True)

    audit_record = {
        "input_objects": len(source),
        "input_targets": len(target_nonnull),
        "analysis_eligible_targets": len(target_metric_eligible),
        "target_analysis_invalid_geometry": len(invalid_target_ids),
        "target_analysis_invalid_ids": invalid_target_ids,
        "matched_single": int(audit.matched_single),
        "matched_multiple": int(audit.matched_multiple),
        "unmatched_outside": int(audit.unmatched_outside),
        "invalid_geometry": int(audit.invalid_geometry) + len(missing_source_ids),
        "relation_rows": int(audit.relation_rows),
    }
    return relation, audit_record


def build_radio_circuit_relation(
    census: gpd.GeoDataFrame,
    circuit_footprints: gpd.GeoDataFrame,
    bridge: pd.DataFrame,
    config: dict,
) -> tuple[pd.DataFrame, dict]:
    source = census.rename(columns={"geo_uid": "source_geo_uid"}).copy()
    target = circuit_footprints.rename(
        columns={"relation_target_uid": "target_electoral_uid"}
    ).copy()
    target = target.loc[target["footprint_status"].eq("analytical")].copy()

    relation, audit = _relate(
        source,
        target,
        source_id_col="source_geo_uid",
        target_id_col="target_electoral_uid",
        config=config,
    )
    source_meta = source.set_index("source_geo_uid")[
        ["radio_2010_id", "department_2010_id", "province_2010_id"]
    ]
    target_meta = target.set_index("target_electoral_uid")[
        [
            "electoral_circuit_uid",
            "electoral_district_code",
            "electoral_section_code",
            "electoral_circuit_code",
            "identity_status",
            "source_feature_count",
        ]
    ]
    for column in source_meta.columns:
        relation[column] = relation["source_geo_uid"].map(source_meta[column])
    for column in target_meta.columns:
        relation[f"target_{column}"] = relation["target_electoral_uid"].map(
            target_meta[column]
        )

    province_to_district = bridge.set_index("province_2010_id")[
        "electoral_district_code"
    ]
    relation["expected_electoral_district_code"] = relation["province_2010_id"].map(
        province_to_district
    )
    relation["province_compatible"] = pd.Series(
        pd.NA, index=relation.index, dtype="boolean"
    )
    positive = relation["target_electoral_uid"].notna()
    relation.loc[positive, "province_compatible"] = (
        relation.loc[positive, "expected_electoral_district_code"].astype(str).to_numpy()
        == relation.loc[positive, "target_electoral_district_code"].astype(str).to_numpy()
    )

    ordered = [
        "source_geo_uid",
        "radio_2010_id",
        "department_2010_id",
        "province_2010_id",
        "expected_electoral_district_code",
        "target_electoral_uid",
        "target_electoral_circuit_uid",
        "target_electoral_district_code",
        "target_electoral_section_code",
        "target_electoral_circuit_code",
        "target_identity_status",
        "target_source_feature_count",
        "province_compatible",
        "overlap_area_m2",
        "overlap_share_of_source",
        "overlap_share_of_target",
        "source_candidate_count",
        "relation_status",
    ]
    relation = relation[ordered].sort_values(
        ["source_geo_uid", "target_electoral_uid"],
        na_position="last",
        ignore_index=True,
    )
    return relation, audit


def build_nonstandard_coverage_relation(
    census: gpd.GeoDataFrame,
    circuits: gpd.GeoDataFrame,
    config: dict,
) -> tuple[pd.DataFrame, dict]:
    source = census.rename(columns={"geo_uid": "source_geo_uid"}).copy()
    target = circuits.loc[
        ~circuits["source_status"].eq("assigned_circuit")
        & circuits["geometry_role"].eq("analytical")
    ].rename(columns={"geo_uid": "target_source_feature_uid"}).copy()
    relation, audit = _relate(
        source,
        target,
        source_id_col="source_geo_uid",
        target_id_col="target_source_feature_uid",
        config=config,
    )
    source_meta = source.set_index("source_geo_uid")[
        ["radio_2010_id", "province_2010_id"]
    ]
    if not target.empty:
        target_meta = target.set_index("target_source_feature_uid")[
            ["codprov", "coddepto", "circuito", "source_status"]
        ]
    else:
        target_meta = pd.DataFrame()
    for column in source_meta.columns:
        relation[column] = relation["source_geo_uid"].map(source_meta[column])
    for column in ("codprov", "coddepto", "circuito", "source_status"):
        relation[f"target_{column}"] = (
            relation["target_source_feature_uid"].map(target_meta[column])
            if not target_meta.empty
            else pd.NA
        )
    return relation, audit


def build_section_department_relation(
    census: gpd.GeoDataFrame,
    circuits: gpd.GeoDataFrame,
    sections: pd.DataFrame,
    bridge: pd.DataFrame,
    vintage: str,
    config: dict,
) -> tuple[pd.DataFrame, dict]:
    section_footprints = _section_footprints(circuits, sections, vintage)
    departments = _department_footprints(census)

    source = section_footprints.rename(
        columns={"electoral_section_uid": "source_electoral_section_uid"}
    )
    target = departments.rename(
        columns={"department_footprint_uid": "target_department_footprint_uid"}
    )
    source_analytical = source.loc[source["footprint_status"].eq("analytical")].copy()
    target_analytical = target.loc[target["footprint_status"].eq("analytical")].copy()

    relation, audit = _relate(
        source_analytical,
        target_analytical,
        source_id_col="source_electoral_section_uid",
        target_id_col="target_department_footprint_uid",
        config=config,
    )
    source_meta = source.set_index("source_electoral_section_uid")[
        ["electoral_district_code", "electoral_section_code", "footprint_status"]
    ]
    target_meta = target.set_index("target_department_footprint_uid")[
        ["department_2010_id", "province_2010_id", "source_radio_count"]
    ]
    for column in source_meta.columns:
        relation[column] = relation["source_electoral_section_uid"].map(
            source_meta[column]
        )
    for column in target_meta.columns:
        relation[f"target_{column}"] = relation[
            "target_department_footprint_uid"
        ].map(target_meta[column])

    district_to_province = bridge.set_index("electoral_district_code")[
        "province_2010_id"
    ]
    relation["expected_province_2010_id"] = relation[
        "electoral_district_code"
    ].map(district_to_province)
    relation["province_compatible"] = pd.Series(
        pd.NA, index=relation.index, dtype="boolean"
    )
    positive = relation["target_department_footprint_uid"].notna()
    relation.loc[positive, "province_compatible"] = (
        relation.loc[positive, "expected_province_2010_id"].astype(str).to_numpy()
        == relation.loc[positive, "target_province_2010_id"].astype(str).to_numpy()
    )
    return relation.sort_values(
        ["source_electoral_section_uid", "target_department_footprint_uid"],
        na_position="last",
        ignore_index=True,
    ), audit


def build_input_status(
    census: gpd.GeoDataFrame,
    circuits: gpd.GeoDataFrame,
    feature_target: pd.DataFrame,
) -> pd.DataFrame:
    source_rows = pd.DataFrame(
        {
            "input_side": "census_radio",
            "input_uid": census["geo_uid"].astype(str),
            "native_id": census["radio_2010_id"].astype(str),
            "province_code": census["province_2010_id"].astype(str),
            "electoral_district_code": pd.NA,
            "electoral_section_code": pd.NA,
            "electoral_circuit_code": pd.NA,
            "source_status": "census_radio",
            "identity_status": "complete",
            "geometry_role": census["geometry_role"].astype(str),
            "eligible_for_primary_relation": census["geometry_role"].eq("analytical"),
            "eligible_for_nonstandard_coverage": False,
            "relation_target_uid": pd.NA,
            "exclusion_reason": pd.NA,
        }
    )

    target = circuits.merge(feature_target, on="geo_uid", how="left", validate="1:1")
    assigned = target["source_status"].eq("assigned_circuit")
    analytical = target["geometry_role"].eq("analytical")
    eligible = assigned & analytical
    nonstandard_eligible = (~assigned) & analytical
    reason = pd.Series(pd.NA, index=target.index, dtype="string")
    reason.loc[~analytical] = target.loc[~analytical, "geometry_role"].astype(str)
    reason.loc[analytical & ~assigned] = target.loc[
        analytical & ~assigned, "source_status"
    ].astype(str)
    target_rows = pd.DataFrame(
        {
            "input_side": "tartagalensis_source_feature",
            "input_uid": target["geo_uid"].astype(str),
            "native_id": target["native_id"].astype(str),
            "province_code": pd.NA,
            "electoral_district_code": target["codprov"].astype(str),
            "electoral_section_code": target["coddepto"].astype("string"),
            "electoral_circuit_code": target["circuito"].astype(str),
            "source_status": target["source_status"].astype(str),
            "identity_status": target["identity_status"].astype(str),
            "geometry_role": target["geometry_role"].astype(str),
            "eligible_for_primary_relation": eligible,
            "eligible_for_nonstandard_coverage": nonstandard_eligible,
            "relation_target_uid": target["relation_target_uid"].astype("string"),
            "exclusion_reason": reason,
        }
    )
    return pd.concat([source_rows, target_rows], ignore_index=True)
