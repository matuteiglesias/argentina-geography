from __future__ import annotations

from collections.abc import Iterable

import geopandas as gpd
import pandas as pd
from shapely import union_all

from argentina_geography.electoral.config import _district_bridge


def _safe_union(geometries: Iterable) -> tuple[object | None, str]:
    items = [geometry for geometry in geometries if geometry is not None and not geometry.is_empty]
    if not items:
        return None, "missing_geometry"
    geometry = union_all(items)
    if geometry is None or geometry.is_empty:
        return None, "empty_derived_geometry"
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        return None, f"non_areal_derived_geometry:{geometry.geom_type}"
    if not geometry.is_valid:
        return None, "invalid_derived_geometry"
    return geometry, "analytical"

def build_electoral_hierarchy(
    circuits: gpd.GeoDataFrame,
    vintage: str,
    config: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, gpd.GeoDataFrame, pd.DataFrame]:
    bridge = _district_bridge(config, vintage)
    districts = bridge[
        [
            "electoral_district_uid",
            "vintage",
            "electoral_district_code",
            "electoral_district_name",
        ]
    ].copy()

    section_rows: list[dict] = []
    for (codprov, coddepto), group in circuits.loc[circuits["coddepto"].notna()].groupby(
        ["codprov", "coddepto"], dropna=False, sort=True
    ):
        assigned = group["source_status"].eq("assigned_circuit")
        analytical = group["geometry_role"].eq("analytical")
        complete = assigned & group["identity_status"].eq("complete_composite")
        section_rows.append(
            {
                "electoral_section_uid": (
                    f"electoral:{vintage}:section:{codprov}:{coddepto}"
                ),
                "vintage": vintage,
                "electoral_district_code": str(codprov),
                "electoral_section_code": str(coddepto),
                "source_codprov": str(codprov),
                "source_coddepto": str(coddepto),
                "source_feature_count": len(group),
                "assigned_feature_count": int(assigned.sum()),
                "analytical_assigned_feature_count": int((assigned & analytical).sum()),
                "nonstandard_feature_count": int((~assigned).sum()),
                "complete_logical_circuit_count": int(
                    group.loc[complete, "circuit_uid"].nunique()
                ),
            }
        )
    sections = pd.DataFrame(section_rows).sort_values(
        ["electoral_district_code", "electoral_section_code"], ignore_index=True
    )

    circuit_rows: list[dict] = []
    footprint_rows: list[dict] = []
    feature_target_map: list[dict] = []

    assigned = circuits.loc[circuits["source_status"].eq("assigned_circuit")].copy()
    complete = assigned["circuit_uid"].notna()
    for circuit_uid, group in assigned.loc[complete].groupby("circuit_uid", sort=True):
        identity = group.iloc[0]
        analytical_group = group.loc[group["geometry_role"].eq("analytical")]
        geometry, footprint_status = _safe_union(analytical_group.geometry.tolist())
        row = {
            "electoral_circuit_uid": str(circuit_uid),
            "relation_target_uid": str(circuit_uid),
            "vintage": vintage,
            "electoral_district_code": str(identity["codprov"]),
            "electoral_section_code": str(identity["coddepto"]),
            "electoral_circuit_code": str(identity["circuito"]),
            "source_codprov": str(identity["codprov"]),
            "source_coddepto": str(identity["coddepto"]),
            "source_circuito": str(identity["circuito"]),
            "identity_status": "complete_composite",
            "source_feature_count": len(group),
            "analytical_source_feature_count": len(analytical_group),
            "footprint_status": footprint_status,
        }
        circuit_rows.append(row)
        footprint_rows.append({**row, "geometry": geometry})
        for feature_uid in group["geo_uid"].astype(str):
            feature_target_map.append(
                {
                    "geo_uid": feature_uid,
                    "relation_target_uid": str(circuit_uid),
                    "relation_target_grain": "logical_circuit",
                }
            )

    for row in assigned.loc[~complete].itertuples():
        relation_target_uid = f"source-feature:{row.geo_uid}"
        geometry = row.geometry if row.geometry_role == "analytical" else None
        footprint_status = "analytical" if geometry is not None else str(row.geometry_role)
        circuit_row = {
            "electoral_circuit_uid": pd.NA,
            "relation_target_uid": relation_target_uid,
            "vintage": vintage,
            "electoral_district_code": str(row.codprov),
            "electoral_section_code": pd.NA,
            "electoral_circuit_code": str(row.circuito),
            "source_codprov": str(row.codprov),
            "source_coddepto": pd.NA,
            "source_circuito": str(row.circuito),
            "identity_status": "missing_coddepto",
            "source_feature_count": 1,
            "analytical_source_feature_count": int(geometry is not None),
            "footprint_status": footprint_status,
        }
        circuit_rows.append(circuit_row)
        footprint_rows.append({**circuit_row, "geometry": geometry})
        feature_target_map.append(
            {
                "geo_uid": str(row.geo_uid),
                "relation_target_uid": relation_target_uid,
                "relation_target_grain": "source_feature_incomplete_identity",
            }
        )

    circuits_dim = pd.DataFrame(circuit_rows).sort_values(
        ["electoral_district_code", "electoral_section_code", "electoral_circuit_code"],
        na_position="last",
        ignore_index=True,
    )
    footprints = gpd.GeoDataFrame(
        footprint_rows, geometry="geometry", crs=circuits.crs
    )
    feature_target = pd.DataFrame(feature_target_map)

    return districts, sections, circuits_dim, footprints, feature_target

def _department_footprints(census: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    rows: list[dict] = []
    for department_id, group in census.groupby("department_2010_id", sort=True):
        provinces = group["province_2010_id"].astype(str).unique().tolist()
        if len(provinces) != 1:
            raise ValueError(f"Census department spans multiple province IDs: {department_id}")
        geometry, status = _safe_union(group.geometry.tolist())
        rows.append(
            {
                "department_footprint_uid": f"indec:census:2010:department-footprint:{department_id}",
                "department_2010_id": str(department_id),
                "province_2010_id": provinces[0],
                "source_radio_count": len(group),
                "footprint_status": status,
                "geometry": geometry,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=census.crs)

def _section_footprints(
    circuits: gpd.GeoDataFrame,
    sections: pd.DataFrame,
    vintage: str,
) -> gpd.GeoDataFrame:
    rows: list[dict] = []
    source = circuits.loc[
        circuits["coddepto"].notna()
        & circuits["source_status"].eq("assigned_circuit")
        & circuits["geometry_role"].eq("analytical")
    ].copy()
    grouped = {
        (str(codprov), str(coddepto)): group
        for (codprov, coddepto), group in source.groupby(
            ["codprov", "coddepto"], sort=True
        )
    }
    for section in sections.itertuples():
        key = (
            str(section.electoral_district_code),
            str(section.electoral_section_code),
        )
        group = grouped.get(key)
        geometry, status = _safe_union([] if group is None else group.geometry.tolist())
        rows.append(
            {
                "electoral_section_uid": section.electoral_section_uid,
                "vintage": vintage,
                "electoral_district_code": section.electoral_district_code,
                "electoral_section_code": section.electoral_section_code,
                "footprint_status": status,
                "geometry": geometry,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=circuits.crs)
