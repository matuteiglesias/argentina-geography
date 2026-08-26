from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon, box

from argentina_geography.electoral.config import DEFAULT_CONFIG, load_config
from argentina_geography.electoral.hierarchy import build_electoral_hierarchy
from argentina_geography.electoral.input_status import (
    _analysis_inventory,
    append_relation_analysis_inputs,
)
from argentina_geography.electoral.relation_builders import build_input_status


def _census() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "geo_uid": "census:r1",
                "radio_2010_id": "020010101",
                "department_2010_id": "02001",
                "province_2010_id": "02",
                "geometry_role": "analytical",
                "geometry": box(0.0, 0.0, 1.0, 1.0),
            }
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )


def _circuits() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "geo_uid": "feature:a1",
                "circuit_uid": "tartagalensis:2021:circuit:01:001:00001",
                "codprov": "01",
                "coddepto": "001",
                "circuito": "00001",
                "native_id": "01|001|00001",
                "source_status": "assigned_circuit",
                "identity_status": "complete_composite",
                "geometry_role": "analytical",
                "geometry": box(0.0, 0.0, 1.0, 1.0),
            }
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )


def _projected_bowtie() -> Polygon:
    return Polygon([(0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (1.0, 0.0), (0.0, 0.0)])


def test_analysis_inventory_exposes_projection_induced_invalidity(monkeypatch) -> None:
    source = gpd.GeoDataFrame(
        [{"uid": "target:1", "geometry": box(0.0, 0.0, 1.0, 1.0)}],
        geometry="geometry",
        crs="EPSG:4326",
    )
    original_to_crs = gpd.GeoDataFrame.to_crs

    def fake_to_crs(self, *args, **kwargs):
        projected = original_to_crs(self, *args, **kwargs)
        projected.loc[projected.index[0], "geometry"] = _projected_bowtie()
        return projected

    monkeypatch.setattr(gpd.GeoDataFrame, "to_crs", fake_to_crs)
    inventory = _analysis_inventory(source, "uid", "EPSG:6933")

    assert inventory.loc[0, "analysis_geometry_status"] == "analysis_crs_invalid_geometry"
    assert not bool(inventory.loc[0, "analysis_geometry_eligible"])


def test_input_status_exposes_derived_invalid_relation_targets(monkeypatch) -> None:
    config = load_config(DEFAULT_CONFIG)
    census = _census()
    circuits = _circuits()
    _, sections, _, circuit_footprints, feature_target = build_electoral_hierarchy(
        circuits, "2021", config
    )
    base_status = build_input_status(census, circuits, feature_target)
    original_to_crs = gpd.GeoDataFrame.to_crs

    def fake_to_crs(self, *args, **kwargs):
        projected = original_to_crs(self, *args, **kwargs)
        if "relation_target_uid" in projected.columns:
            projected.loc[projected.index[0], "geometry"] = _projected_bowtie()
        if "department_footprint_uid" in projected.columns:
            projected.loc[projected.index[0], "geometry"] = _projected_bowtie()
        return projected

    monkeypatch.setattr(gpd.GeoDataFrame, "to_crs", fake_to_crs)
    status = append_relation_analysis_inputs(
        base_status,
        census,
        circuits,
        circuit_footprints,
        sections,
        "2021",
        config,
    )

    circuit_target = status.loc[
        status["input_side"].eq("derived_electoral_circuit_relation_target")
    ].iloc[0]
    assert circuit_target["input_uid"] == "tartagalensis:2021:circuit:01:001:00001"
    assert circuit_target["analysis_geometry_status"] == "analysis_crs_invalid_geometry"
    assert circuit_target["exclusion_reason"] == "analysis_crs_invalid_geometry"
    assert not bool(circuit_target["eligible_for_primary_relation"])

    department_target = status.loc[
        status["input_side"].eq("derived_census_department_relation_target")
    ].iloc[0]
    assert department_target["input_uid"] == "indec:census:2010:department-footprint:02001"
    assert department_target["analysis_geometry_status"] == "analysis_crs_invalid_geometry"
    assert not bool(department_target["eligible_for_primary_relation"])

    parent_rows = status.loc[
        status["input_side"].isin(["census_radio", "tartagalensis_source_feature"])
    ]
    assert len(parent_rows) == len(base_status)
