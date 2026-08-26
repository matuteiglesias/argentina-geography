from __future__ import annotations

import geopandas as gpd
import pandas as pd

from argentina_geography.electoral.hierarchy import (
    _department_footprints,
    _section_footprints,
)


def _analysis_inventory(
    frame: gpd.GeoDataFrame,
    id_col: str,
    analysis_crs: str,
) -> pd.DataFrame:
    """Classify geometry eligibility in the metric analysis CRS without repair.

    Source geometry is never overwritten. A geometry must be an areal, valid object in
    its input CRS and remain an areal, valid object after projection to be eligible.
    """
    work = frame[[id_col, "geometry"]].reset_index(drop=True).copy()
    geometry = work.geometry
    missing = geometry.isna()
    empty = geometry.is_empty.fillna(False)
    areal = geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    native_valid = ~missing & ~empty & areal & geometry.is_valid.fillna(False)

    status = pd.Series("invalid_geometry", index=work.index, dtype="string")
    status.loc[missing] = "missing_geometry"
    status.loc[~missing & empty] = "empty_geometry"
    status.loc[~missing & ~empty & ~areal] = "non_areal_geometry"

    metric = work.to_crs(analysis_crs)
    metric_geometry = metric.geometry
    metric_eligible = (
        metric_geometry.notna()
        & ~metric_geometry.is_empty.fillna(False)
        & metric_geometry.geom_type.isin(["Polygon", "MultiPolygon"])
        & metric_geometry.is_valid.fillna(False)
    )
    status.loc[native_valid & metric_eligible] = "analytical"
    status.loc[native_valid & ~metric_eligible] = "analysis_crs_invalid_geometry"

    return pd.DataFrame(
        {
            id_col: work[id_col].astype("string"),
            "analysis_crs": analysis_crs,
            "analysis_geometry_status": status,
            "analysis_geometry_eligible": status.eq("analytical"),
        }
    )


def _derived_rows(
    frame: gpd.GeoDataFrame,
    inventory: pd.DataFrame,
    *,
    input_side: str,
    id_col: str,
    native_id_col: str,
    source_status: str,
    province_col: str | None = None,
    district_col: str | None = None,
    section_col: str | None = None,
    circuit_col: str | None = None,
    identity_col: str | None = None,
    relation_target: bool,
) -> pd.DataFrame:
    merged = frame.reset_index(drop=True).merge(inventory, on=id_col, validate="1:1")
    eligible = merged["analysis_geometry_eligible"].fillna(False)
    exclusion = pd.Series(pd.NA, index=merged.index, dtype="string")
    exclusion.loc[~eligible] = merged.loc[~eligible, "analysis_geometry_status"].astype(
        "string"
    )
    return pd.DataFrame(
        {
            "input_side": input_side,
            "input_uid": merged[id_col].astype("string"),
            "native_id": merged[native_id_col].astype("string"),
            "province_code": (
                merged[province_col].astype("string") if province_col else pd.NA
            ),
            "electoral_district_code": (
                merged[district_col].astype("string") if district_col else pd.NA
            ),
            "electoral_section_code": (
                merged[section_col].astype("string") if section_col else pd.NA
            ),
            "electoral_circuit_code": (
                merged[circuit_col].astype("string") if circuit_col else pd.NA
            ),
            "source_status": source_status,
            "identity_status": (
                merged[identity_col].astype("string") if identity_col else "complete"
            ),
            "geometry_role": merged["footprint_status"].astype("string"),
            "eligible_for_primary_relation": eligible,
            "eligible_for_nonstandard_coverage": False,
            "relation_target_uid": (
                merged[id_col].astype("string") if relation_target else pd.NA
            ),
            "exclusion_reason": exclusion,
            "analysis_crs": merged["analysis_crs"].astype("string"),
            "analysis_geometry_status": merged["analysis_geometry_status"].astype(
                "string"
            ),
            "analysis_geometry_eligible": eligible,
        }
    )


def append_relation_analysis_inputs(
    base_status: pd.DataFrame,
    census: gpd.GeoDataFrame,
    circuits: gpd.GeoDataFrame,
    circuit_footprints: gpd.GeoDataFrame,
    sections: pd.DataFrame,
    vintage: str,
    config: dict,
) -> pd.DataFrame:
    """Append derived relation-input geometry status to ``input_status.parquet``.

    These rows make projection-induced invalidity observable at the exact derived
    relation grain. They do not repair geometry, select another target, or mutate either
    parent geography release.
    """
    analysis_crs = config["analysis_crs"]
    status = base_status.copy()
    status["analysis_crs"] = pd.NA
    status["analysis_geometry_status"] = pd.NA
    status["analysis_geometry_eligible"] = pd.NA

    circuit_inventory = _analysis_inventory(
        circuit_footprints, "relation_target_uid", analysis_crs
    )
    circuit_rows = _derived_rows(
        circuit_footprints,
        circuit_inventory,
        input_side="derived_electoral_circuit_relation_target",
        id_col="relation_target_uid",
        native_id_col="relation_target_uid",
        source_status="derived_from_tartagalensis_assigned_features",
        district_col="electoral_district_code",
        section_col="electoral_section_code",
        circuit_col="electoral_circuit_code",
        identity_col="identity_status",
        relation_target=True,
    )

    section_footprints = _section_footprints(circuits, sections, vintage)
    section_inventory = _analysis_inventory(
        section_footprints, "electoral_section_uid", analysis_crs
    )
    section_rows = _derived_rows(
        section_footprints,
        section_inventory,
        input_side="derived_electoral_section_relation_source",
        id_col="electoral_section_uid",
        native_id_col="electoral_section_uid",
        source_status="derived_from_tartagalensis_assigned_features",
        district_col="electoral_district_code",
        section_col="electoral_section_code",
        relation_target=False,
    )

    department_footprints = _department_footprints(census)
    department_inventory = _analysis_inventory(
        department_footprints, "department_footprint_uid", analysis_crs
    )
    department_rows = _derived_rows(
        department_footprints,
        department_inventory,
        input_side="derived_census_department_relation_target",
        id_col="department_footprint_uid",
        native_id_col="department_2010_id",
        source_status="derived_from_indec_census_2010_radios",
        province_col="province_2010_id",
        relation_target=True,
    )

    return pd.concat(
        [status, circuit_rows, section_rows, department_rows],
        ignore_index=True,
        sort=False,
    )
