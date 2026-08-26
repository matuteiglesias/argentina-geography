import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon, box

from argentina_geography.products import sha256_file
from argentina_geography.sources.ign_province import (
    DISPLAY_PROPERTY_FIELDS,
    load_config,
    materialize_from_source,
    normalize_source,
    verify_release,
)

EXPECTED_IDS = [
    "02",
    "06",
    "10",
    "14",
    "18",
    "22",
    "26",
    "30",
    "34",
    "38",
    "42",
    "46",
    "50",
    "54",
    "58",
    "62",
    "66",
    "70",
    "74",
    "78",
    "82",
    "86",
    "90",
    "94",
]


def make_frame() -> gpd.GeoDataFrame:
    rows = []
    for index, province_id in enumerate(EXPECTED_IDS):
        is_caba = province_id == "02"
        rows.append(
            {
                "OBJECTID": 400 + index,
                "Entidad": 0,
                "Objeto": "Provincia",
                "FNA": (
                    "Ciudad Autónoma de Buenos Aires"
                    if is_caba
                    else f"Provincia fixture {province_id}"
                ),
                "GNA": "Ciudad Autónoma" if is_caba else "Provincia",
                "NAM": "Ciudad Autónoma de Buenos Aires" if is_caba else f"Fixture {province_id}",
                "SAG": "IGN",
                "FDC": "Geografía",
                "IN1": province_id,
                "SHAPE_STAr": float(index + 1),
                "SHAPE_STLe": float(index + 1) / 10,
                "geometry": box(index, 0, index + 0.8, 0.8),
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def fixture_config(tmp_path: Path, source: Path) -> Path:
    config = load_config().copy()
    config["expected_source_sha256"] = sha256_file(source)
    config["expected_source_size_bytes"] = source.stat().st_size
    config["expected_normalized_content_sha256"] = None
    config["snapshot_retrieved_at_utc"] = "2026-08-26T00:00:00+00:00"
    path = tmp_path / "ign-province-fixture-config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_exact_archive_identity_and_atlas_ids_are_pinned():
    config = load_config()
    assert config["source_url"] == (
        "https://www.ign.gob.ar/descargas/geodatos/SHAPES/ign_provincia.zip"
    )
    assert config["archive_member"] == "Provincia/ign_provincia.shp"
    assert config["expected_source_sha256"] == (
        "b9fcf6f90f28f1bdfcc713a47ad4ed63e2db0b000c4642611597d4ea8b897c55"
    )
    assert config["expected_source_size_bytes"] == 10520464
    assert config["expected_feature_count"] == 24
    assert config["expected_native_ids"] == EXPECTED_IDS


def test_ign_province_preserves_native_identity_and_fixture_seam():
    normalized, audit = normalize_source(make_frame(), load_config(), source_sha256="a" * 64)
    assert normalized["native_id"].tolist() == EXPECTED_IDS
    assert normalized["geography_id"].tolist() == EXPECTED_IDS
    assert normalized["IN1"].tolist() == EXPECTED_IDS
    assert normalized["geo_uid"].str.contains("ign:administrative:province:aaaaaaaaaaaa:").all()
    assert audit["feature_count"] == 24
    assert audit["unique_native_id_count"] == 24
    assert audit["atlas_fixture_id_compatibility"] is True
    assert audit["gna_values"] == ["Ciudad Autónoma", "Provincia"]
    assert audit["stage_decision"] == "PASS"


def test_ign_province_release_is_snapshot_addressed_and_detached_verifiable(tmp_path):
    source = tmp_path / "ign-province-fixture.geojson"
    make_frame().to_file(source, driver="GeoJSON")
    config_path = fixture_config(tmp_path, source)
    release = tmp_path / "release"
    manifest = materialize_from_source(source, release, config_path)
    verify_release(release)

    assert manifest["source_snapshot"]["snapshot_id"] == f"sha256:{sha256_file(source)}"
    assert manifest["dataset"]["dataset_id"] == "arggeo.ign.administrative.province"
    assert manifest["run"]["parameters"]["geometry_repair_applied"] is False
    assert manifest["run"]["parameters"]["geometry_clip_applied"] is False
    assert manifest["run"]["parameters"]["geometry_dissolve_applied"] is False
    assert manifest["display_derivative"]["feature_id_field"] == "geography_id"
    assert manifest["display_derivative"]["geometry_transform"] == "none"

    catalog = pd.read_parquet(release / "geography_catalog.parquet")
    assert catalog.iloc[0]["level"] == "province"
    assert catalog.iloc[0]["native_id_fields"] == "IN1"
    assert catalog.iloc[0]["source_identity_fields"] == "IN1,OBJECTID"
    assert catalog.iloc[0]["display_identity_field"] == "geography_id"
    assert catalog.iloc[0]["distribution_mode"] == "official_remote_fetch"

    display = json.loads((release / "geography.geojson").read_text(encoding="utf-8"))
    assert [feature["id"] for feature in display["features"]] == EXPECTED_IDS
    assert all(
        set(feature["properties"]) == set(DISPLAY_PROPERTY_FIELDS)
        for feature in display["features"]
    )


def test_ign_province_rejects_snapshot_drift(tmp_path):
    source = tmp_path / "ign-province-fixture.geojson"
    make_frame().to_file(source, driver="GeoJSON")
    config = load_config().copy()
    config["expected_source_sha256"] = "0" * 64
    config["expected_source_size_bytes"] = source.stat().st_size
    config["expected_normalized_content_sha256"] = None
    config_path = tmp_path / "bad-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot SHA-256 drift"):
        materialize_from_source(source, tmp_path / "release", config_path)


def test_ign_province_rejects_duplicate_native_id():
    frame = make_frame()
    frame.loc[1, "IN1"] = frame.loc[0, "IN1"]
    with pytest.raises(ValueError, match="native IDs must be unique"):
        normalize_source(frame, load_config(), source_sha256="b" * 64)


def test_ign_province_rejects_wrong_fixture_id_set():
    frame = make_frame()
    frame.loc[1, "IN1"] = "04"
    with pytest.raises(ValueError, match="native ID set drifted"):
        normalize_source(frame, load_config(), source_sha256="c" * 64)


def test_ign_province_rejects_duplicate_secondary_source_id():
    frame = make_frame()
    frame.loc[1, "OBJECTID"] = frame.loc[0, "OBJECTID"]
    with pytest.raises(ValueError, match="OBJECTID must be non-missing and unique"):
        normalize_source(frame, load_config(), source_sha256="d" * 64)


def test_ign_province_retains_invalid_geometry_without_repair():
    frame = make_frame()
    frame.at[0, "geometry"] = Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)])
    normalized, audit = normalize_source(frame, load_config(), source_sha256="e" * 64)
    row = normalized.loc[normalized["native_id"].eq("02")].iloc[0]
    assert row["geometry_role"] == "source_invalid"
    assert bool(row["geometry_valid"]) is False
    assert audit["source_invalid_geometry_count"] == 1
    assert audit["stage_decision"] == "PASS_WITH_WARNINGS"


def test_ign_province_rejects_non_areal_geometry():
    frame = make_frame()
    frame.at[0, "geometry"] = Point(0, 0)
    with pytest.raises(ValueError, match="unusable source geometry"):
        normalize_source(frame, load_config(), source_sha256="f" * 64)


def test_ign_province_rejects_source_vocabulary_drift():
    frame = make_frame()
    frame.loc[1, "GNA"] = "Jurisdicción"
    with pytest.raises(ValueError, match="GNA vocabulary drifted"):
        normalize_source(frame, load_config(), source_sha256="0" * 64)
