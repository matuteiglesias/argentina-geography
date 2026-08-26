from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon

from argentina_geography.sources.indec_2022_radio import (
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
                "fid": index + 1,
                "id": index + 100,
                "sag": "fixture",
                "tro": "U",
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
            "jur": "Ciudad Autónoma de Buenos Aires",
            "cpr": 2,
            "cde": "02001",
            "dpto": "Comuna 1",
            "cfn": 1,
            "cro": 1,
            "cod_indec": 20010101,
        },
        {
            "jur": "Entre Ríos",
            "cpr": 30,
            "cde": "30001",
            "dpto": "Fixture ER",
            "cfn": 0,
            "cro": 0,
            "cod_indec": 300010000,
        },
        {
            "jur": "Misiones",
            "cpr": 54,
            "cde": "54001",
            "dpto": "Fixture Misiones",
            "cfn": 0,
            "cro": 0,
            "cod_indec": 540010000,
        },
        {
            "jur": "Chaco",
            "cpr": 22,
            "cde": "140",
            "dpto": "San Fernando",
            "cfn": 20,
            "cro": 10,
            "cod_indec": 221402010,
        },
    ]


def warning_codes(audit: dict) -> set[str]:
    return {warning["code"] for warning in audit["accepted_warnings"]}


def test_indec_2022_uses_cod_indec_as_authority_and_preserves_source_codes(tmp_path):
    frame = make_frame(standard_rows())
    normalized, audit = normalize_source(frame, load_config())

    assert normalized["native_id"].tolist() == [
        "020010101",
        "221402010",
        "300010000",
        "540010000",
    ]
    chaco = normalized.loc[normalized["native_id"] == "221402010"].iloc[0]
    assert chaco["cde"] == "140"
    assert chaco["department_code"] == "22140"
    assert chaco["fraction_code"] == "20"
    assert chaco["radio_code"] == "10"
    assert audit["feature_count"] == 4
    assert audit["adjustment_feature_count"] == 2
    assert audit["cde_local_representation_count"] == 1
    assert audit["stage_decision"] == "PASS_WITH_WARNINGS"
    assert "mixed_source_cde_representation" in warning_codes(audit)

    source = tmp_path / "indec_fixture.geojson"
    frame.to_file(source, driver="GeoJSON")
    release = tmp_path / "release"
    manifest = materialize_from_source(source, release)
    verify_release(release)
    catalog = pd.read_parquet(release / "geography_catalog.parquet")
    assert catalog.iloc[0]["distribution_mode"] == "official_remote_fetch"
    assert catalog.iloc[0]["qa_state"] == "YELLOW"
    assert catalog.iloc[0]["native_id_fields"] == "cod_indec"
    assert manifest["authority_status"] == "official"
    assert manifest["stage_decision"] == "PASS_WITH_WARNINGS"
    assert manifest["run"]["parameters"]["geometry_repair_applied"] is False
    assert Path(release / "geography.parquet").exists()


def test_indec_2022_retains_supporting_code_disagreement_as_warning():
    rows = standard_rows()
    rows[0]["cde"] = "999"
    normalized, audit = normalize_source(make_frame(rows), load_config())
    assert len(normalized) == 4
    assert audit["supporting_code_disagreement_count"] == 1
    assert "supporting_code_disagreement" in warning_codes(audit)


def test_indec_2022_retains_unclassified_zero_code_without_no_data_claim():
    rows = standard_rows()
    rows[0]["cfn"] = 0
    rows[0]["cro"] = 0
    rows[0]["cod_indec"] = 20010000
    normalized, audit = normalize_source(make_frame(rows), load_config())
    row = normalized.loc[normalized["native_id"] == "020010000"].iloc[0]
    assert row["source_unit_status"] == "zero_code_unclassified"
    assert audit["zero_code_unclassified_count"] == 1
    assert "unclassified_zero_code" in warning_codes(audit)


def test_indec_2022_retains_invalid_polygon_but_excludes_it_from_analytical_role():
    frame = make_frame(standard_rows())
    frame.at[0, "geometry"] = Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)])
    normalized, audit = normalize_source(frame, load_config())
    invalid = normalized.loc[normalized["native_id"] == "020010101"].iloc[0]
    assert invalid["geometry_role"] == "source_invalid"
    assert bool(invalid["geometry_valid"]) is False
    assert audit["source_invalid_geometry_count"] == 1
    assert audit["analytical_geometry_count"] == 3
    assert "source_invalid_geometry" in warning_codes(audit)


def test_indec_2022_stops_on_non_areal_geometry():
    frame = make_frame(standard_rows())
    frame.at[0, "geometry"] = Point(0, 0)
    with pytest.raises(ValueError, match="unusable source geometry"):
        normalize_source(frame, load_config())


def test_indec_2022_rejects_duplicate_native_identity():
    rows = standard_rows()
    rows.insert(1, dict(rows[0]))
    with pytest.raises(ValueError, match="native IDs must be unique"):
        normalize_source(make_frame(rows), load_config())


def test_indec_2022_rejects_unbounded_source_department_code():
    rows = standard_rows()
    rows[0]["cde"] = "123456"
    with pytest.raises(ValueError, match="cde must contain at most 5 ASCII digits"):
        normalize_source(make_frame(rows), load_config())
