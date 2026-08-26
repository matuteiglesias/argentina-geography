from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon

from argentina_geography.sources.ceur_2022_v2025_1 import (
    load_config,
    materialize_from_source,
    normalize_source,
    verify_release,
)


def make_frame(rows: list[dict]) -> gpd.GeoDataFrame:
    values = []
    for index, row in enumerate(rows):
        values.append(
            {
                **row,
                "geometry": Polygon(
                    [(index, 0), (index + 0.8, 0), (index + 0.8, 0.8), (index, 0.8)]
                ),
            }
        )
    return gpd.GeoDataFrame(values, geometry="geometry", crs="EPSG:3857")


def standard_rows() -> list[dict]:
    return [
        {
            "COD_2022": "020070101",
            "PROV": "02",
            "DEPTO": "007",
            "FRACC": "01",
            "RADIO": "01",
            "OBS2022": None,
            "VIV_TOT_P": 120,
            "POB_TOT_P": 330,
            "REDATAM": "SI",
        },
        {
            "COD_2022": "060140205",
            "PROV": "06",
            "DEPTO": "014",
            "FRACC": "02",
            "RADIO": "05",
            "OBS2022": "Geometría corregida por la fuente curada.",
            "VIV_TOT_P": 88,
            "POB_TOT_P": 241,
            "REDATAM": "no",
        },
        {
            "COD_2022": "540010101",
            "PROV": "54",
            "DEPTO": "001",
            "FRACC": "01",
            "RADIO": "01",
            "OBS2022": None,
            "VIV_TOT_P": 54,
            "POB_TOT_P": 160,
            "REDATAM": "SI",
        },
    ]


def warning_codes(audit: dict) -> set[str]:
    return {warning["code"] for warning in audit["accepted_warnings"]}


def test_ceur_uses_cod_2022_as_authoritative_identity():
    normalized, audit = normalize_source(make_frame(standard_rows()), load_config())

    assert normalized["native_id"].tolist() == [
        "020070101",
        "060140205",
        "540010101",
    ]
    row = normalized.loc[normalized["native_id"] == "060140205"].iloc[0]
    assert row["province_code"] == "06"
    assert row["department_code"] == "06014"
    assert row["fraction_code"] == "02"
    assert row["radio_code"] == "05"
    assert row["OBS2022"] == "Geometría corregida por la fuente curada."
    assert row["VIV_TOT_P"] == 88
    assert row["POB_TOT_P"] == 241
    assert row["REDATAM"] == "no"
    assert audit["identity_composition_mismatch_count"] == 0
    assert audit["source_annotation_count"] == 1
    assert audit["stage_decision"] == "PASS"


def test_ceur_rejects_component_identity_mismatch():
    rows = standard_rows()
    rows[0]["RADIO"] = "02"
    with pytest.raises(ValueError, match=r"PROV\+DEPTO\+FRACC\+RADIO"):
        normalize_source(make_frame(rows), load_config())


def test_ceur_rejects_duplicate_native_identity():
    rows = standard_rows()
    rows.insert(1, dict(rows[0]))
    with pytest.raises(ValueError, match="native IDs must be unique"):
        normalize_source(make_frame(rows), load_config())


def test_ceur_retains_invalid_polygon_without_repair():
    frame = make_frame(standard_rows())
    original = Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)])
    frame.at[0, "geometry"] = original

    normalized, audit = normalize_source(frame, load_config())
    invalid = normalized.loc[normalized["native_id"] == "020070101"].iloc[0]

    assert invalid.geometry.wkt == original.wkt
    assert invalid["geometry_role"] == "source_invalid"
    assert bool(invalid["geometry_valid"]) is False
    assert audit["source_invalid_geometry_count"] == 1
    assert audit["analytical_geometry_count"] == 2
    assert audit["stage_decision"] == "PASS_WITH_WARNINGS"
    assert "source_invalid_geometry" in warning_codes(audit)


def test_ceur_preserves_driver_warning_as_qa():
    _, audit = normalize_source(
        make_frame(standard_rows()),
        load_config(),
        driver_warnings=["fixture driver warning"],
    )
    assert audit["stage_decision"] == "PASS_WITH_WARNINGS"
    assert "source_driver_warning" in warning_codes(audit)


def test_ceur_stops_on_non_areal_geometry():
    frame = make_frame(standard_rows())
    frame.at[0, "geometry"] = Point(0, 0)
    with pytest.raises(ValueError, match="unusable source geometry"):
        normalize_source(frame, load_config())


def test_ceur_stops_when_required_source_field_is_missing():
    frame = make_frame(standard_rows()).drop(columns=["OBS2022"])
    with pytest.raises(ValueError, match="missing required fields"):
        normalize_source(frame, load_config())


def test_ceur_bundle_is_curated_research_and_detached_verifiable(tmp_path):
    frame = make_frame(standard_rows())
    source = tmp_path / "ceur_fixture.geojson"
    frame.to_file(source, driver="GeoJSON")

    release = tmp_path / "release"
    manifest = materialize_from_source(source, release)
    verify_release(release)

    geography = gpd.read_parquet(release / "geography.parquet")
    catalog = pd.read_parquet(release / "geography_catalog.parquet")

    assert len(geography) == 3
    assert manifest["authority_status"] == "curated_research"
    assert manifest["distribution_mode"] == "redistributed_snapshot"
    assert manifest["run"]["parameters"]["geometry_repair_applied"] is False
    assert manifest["license"]["name"] == "Creative Commons Attribution 2.5 Unported"
    assert manifest["source_snapshot"]["files"][0]["path"] == source.name
    assert catalog.iloc[0]["authority_status"] == "curated_research"
    assert catalog.iloc[0]["distribution_mode"] == "redistributed_snapshot"
    assert catalog.iloc[0]["native_id_fields"] == "COD_2022"
    assert Path(release / "checksums.txt").exists()
