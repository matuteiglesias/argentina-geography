from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon

from argentina_geography.sources.ceur_2010_v2025_1 import (
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
            "COD_2010": "020070101",
            "PROV": "02",
            "DEPTO": "007",
            "FRACC": "01",
            "RADIO": "01",
            "SEGMENTOS": 3,
            "OBS2010": None,
            "BASICO": "SI",
            "AMPLIADO": "SI",
            "TIPO": "100% Ampliado",
        },
        {
            "COD_2010": "060140205",
            "PROV": "06",
            "DEPTO": "014",
            "FRACC": "02",
            "RADIO": "05",
            "SEGMENTOS": 4,
            "OBS2010": "Geometría corregida por la fuente curada.",
            "BASICO": "SI",
            "AMPLIADO": "no",
            "TIPO": "Solo basico",
        },
        {
            "COD_2010": "540010101",
            "PROV": "54",
            "DEPTO": "001",
            "FRACC": "01",
            "RADIO": "01",
            "SEGMENTOS": 2,
            "OBS2010": None,
            "BASICO": "SI",
            "AMPLIADO": "SI",
            "TIPO": "Ampliado por muestra",
        },
    ]


def warning_codes(audit: dict) -> set[str]:
    return {warning["code"] for warning in audit["accepted_warnings"]}


def test_ceur_2010_v2025_1_source_identity_is_pinned() -> None:
    config = load_config()
    assert config["authority_status"] == "curated_research"
    assert config["release"] == "V2025-1"
    assert config["file_name"] == "RADIOS_2010_V2025-1.zip"
    assert config["target_vintage"] == "2010"
    assert config["download_url"].endswith(
        "RADIOS_2010_V2025-1.zip?isAllowed=y&sequence=14"
    )


def test_ceur_2010_uses_native_code_and_stable_consumer_ids() -> None:
    normalized, audit = normalize_source(make_frame(standard_rows()), load_config())

    assert normalized["radio_2010_id"].tolist() == [
        "020070101",
        "060140205",
        "540010101",
    ]
    row = normalized.loc[normalized["radio_2010_id"] == "060140205"].iloc[0]
    assert row["native_id"] == "060140205"
    assert row["COD_2010"] == "060140205"
    assert row["department_2010_id"] == "06014"
    assert row["province_2010_id"] == "06"
    assert row["fraction_2010_id"] == "0601402"
    assert row["OBS2010"] == "Geometría corregida por la fuente curada."
    assert audit["identity_composition_mismatch_count"] == 0
    assert audit["source_annotation_count"] == 1
    assert audit["stage_decision"] == "PASS"


def test_ceur_2010_preserves_zero_padded_identity() -> None:
    normalized, _ = normalize_source(make_frame(standard_rows()), load_config())
    assert normalized.iloc[0]["radio_2010_id"] == "020070101"
    assert normalized.iloc[0]["province_2010_id"] == "02"
    assert normalized.iloc[0]["department_2010_id"] == "02007"


def test_ceur_2010_rejects_component_identity_mismatch() -> None:
    rows = standard_rows()
    rows[0]["RADIO"] = "02"
    with pytest.raises(ValueError, match=r"PROV\+DEPTO\+FRACC\+RADIO"):
        normalize_source(make_frame(rows), load_config())


def test_ceur_2010_rejects_duplicate_native_identity() -> None:
    rows = standard_rows()
    rows.insert(1, dict(rows[0]))
    with pytest.raises(ValueError, match="native IDs must be unique"):
        normalize_source(make_frame(rows), load_config())


def test_ceur_2010_retains_invalid_polygon_without_repair() -> None:
    frame = make_frame(standard_rows())
    original = Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)])
    frame.at[0, "geometry"] = original

    normalized, audit = normalize_source(frame, load_config())
    invalid = normalized.loc[normalized["radio_2010_id"] == "020070101"].iloc[0]

    assert invalid.geometry.wkt == original.wkt
    assert invalid["geometry_role"] == "source_invalid"
    assert bool(invalid["geometry_valid"]) is False
    assert audit["invalid_geometry_count"] == 1
    assert audit["analytical_geometry_count"] == 2
    assert audit["stage_decision"] == "PASS_WITH_WARNINGS"
    assert "source_invalid_geometry" in warning_codes(audit)


def test_ceur_2010_preserves_driver_warning_as_qa() -> None:
    _, audit = normalize_source(
        make_frame(standard_rows()),
        load_config(),
        driver_warnings=["fixture driver warning"],
    )
    assert audit["stage_decision"] == "PASS_WITH_WARNINGS"
    assert "source_driver_warning" in warning_codes(audit)


def test_ceur_2010_stops_on_non_areal_geometry() -> None:
    frame = make_frame(standard_rows())
    frame.at[0, "geometry"] = Point(0, 0)
    with pytest.raises(ValueError, match="unusable geometry"):
        normalize_source(frame, load_config())


def test_ceur_2010_stops_when_required_source_field_is_missing() -> None:
    frame = make_frame(standard_rows()).drop(columns=["OBS2010"])
    with pytest.raises(ValueError, match="missing required fields"):
        normalize_source(frame, load_config())


def test_ceur_2010_bundle_is_curated_research_and_detached_verifiable(tmp_path) -> None:
    frame = make_frame(standard_rows())
    source = tmp_path / "ceur_2010_fixture.geojson"
    frame.to_file(source, driver="GeoJSON")

    release = tmp_path / "release"
    manifest = materialize_from_source(source, release)
    verify_release(release)

    geography = gpd.read_parquet(release / "geography.parquet")
    catalog = pd.read_parquet(release / "geography_catalog.parquet")

    assert len(geography) == 3
    assert manifest["authority_status"] == "curated_research"
    assert manifest["dataset"]["dataset_id"] == "arggeo.ceur.census.2010.radio"
    assert manifest["run"]["parameters"]["distribution_mode"] == "redistributed_snapshot"
    assert manifest["run"]["parameters"]["geometry_repair_applied"] is False
    assert manifest["run"]["parameters"]["consumer_identity_fields"] == [
        "radio_2010_id",
        "department_2010_id",
        "province_2010_id",
    ]
    assert catalog.iloc[0]["authority_status"] == "curated_research"
    assert catalog.iloc[0]["native_id_fields"] == "COD_2010;PROV,DEPTO,FRACC,RADIO"
    assert catalog.iloc[0]["consumer_id_fields"] == (
        "radio_2010_id,department_2010_id,province_2010_id"
    )
    assert Path(release / "checksums.txt").exists()
