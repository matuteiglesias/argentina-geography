from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

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
                "tro": "URBANO",
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
            "cde": 2001,
            "dpto": "Comuna 1",
            "cfn": 1,
            "cro": 1,
            "cod_indec": 20010101,
        },
        {
            "jur": "Entre Ríos",
            "cpr": 30,
            "cde": 30001,
            "dpto": "Fixture ER",
            "cfn": 0,
            "cro": 0,
            "cod_indec": 300010000,
        },
        {
            "jur": "Misiones",
            "cpr": 54,
            "cde": 54001,
            "dpto": "Fixture Misiones",
            "cfn": 0,
            "cro": 0,
            "cod_indec": 540010000,
        },
    ]


def test_indec_2022_normalization_preserves_native_identity_and_adjustments(tmp_path):
    frame = make_frame(standard_rows())
    normalized, audit = normalize_source(frame, load_config())
    assert normalized["native_id"].tolist() == ["020010101", "300010000", "540010000"]
    assert normalized["cde"].tolist() == ["02001", "30001", "54001"]
    assert normalized["geo_uid"].tolist()[0] == "indec:2022:census:radio:020010101"
    assert audit["feature_count"] == 3
    assert audit["adjustment_feature_count"] == 2
    assert audit["stage_decision"] == "PASS_WITH_WARNINGS"
    assert set(normalized.loc[normalized["cfn"] == "00", "source_unit_status"]) == {
        "adjustment_no_census_data"
    }

    source = tmp_path / "indec_fixture.geojson"
    frame.to_file(source, driver="GeoJSON")
    release = tmp_path / "release"
    manifest = materialize_from_source(source, release)
    verify_release(release)
    catalog = pd.read_parquet(release / "geography_catalog.parquet")
    assert catalog.iloc[0]["distribution_mode"] == "official_remote_fetch"
    assert catalog.iloc[0]["qa_state"] == "YELLOW"
    assert manifest["authority_status"] == "official"
    assert manifest["distribution_mode"] == "official_remote_fetch"
    assert manifest["stage_decision"] == "PASS_WITH_WARNINGS"
    assert manifest["run"]["parameters"]["geometry_repair_applied"] is False
    assert Path(release / "geography.parquet").exists()


def test_indec_2022_rejects_component_identity_drift():
    rows = standard_rows()
    rows[0]["cod_indec"] = 999999999
    with pytest.raises(ValueError, match="cod_indec is inconsistent"):
        normalize_source(make_frame(rows), load_config())


def test_indec_2022_rejects_department_prefix_drift():
    rows = standard_rows()
    rows[0]["cde"] = 30001
    with pytest.raises(ValueError, match="jurisdiction prefix"):
        normalize_source(make_frame(rows), load_config())


def test_indec_2022_rejects_unexpected_zero_code():
    rows = standard_rows()
    rows[0]["cfn"] = 0
    rows[0]["cro"] = 0
    rows[0]["cod_indec"] = 20010000
    with pytest.raises(ValueError, match="outside the jurisdictions documented"):
        normalize_source(make_frame(rows), load_config())


def test_indec_2022_rejects_invalid_geometry_without_repair():
    frame = make_frame(standard_rows())
    frame.at[0, "geometry"] = Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)])
    with pytest.raises(ValueError, match="not publishable without a new geometry policy"):
        normalize_source(frame, load_config())


def test_indec_2022_rejects_duplicate_native_identity():
    rows = standard_rows()
    rows.insert(1, dict(rows[0]))
    with pytest.raises(ValueError, match="native IDs must be unique"):
        normalize_source(make_frame(rows), load_config())
