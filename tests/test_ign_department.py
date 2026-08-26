import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon, box

from argentina_geography.products import sha256_file
from argentina_geography.sources.ign_department import (
    build_wfs_url,
    load_config,
    materialize_from_source,
    normalize_source,
    verify_release,
)


def make_frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "gid": 101,
                "objeto": "Departamento",
                "fna": "Departamento Norte",
                "gna": "Departamento",
                "nam": "Norte",
                "in1": "06001",
                "fdc": "Fixture Catastro",
                "sag": "IGN",
                "geometry": box(0, 0, 1, 1),
            },
            {
                "gid": 102,
                "objeto": "Departamento",
                "fna": "Partido de Sur",
                "gna": "Partido",
                "nam": "Sur",
                "in1": "06002",
                "fdc": "Fixture Catastro",
                "sag": "IGN",
                "geometry": box(1, 0, 2, 1),
            },
            {
                "gid": 103,
                "objeto": "Departamento",
                "fna": "Comuna Centro",
                "gna": "Comuna",
                "nam": "Centro",
                "in1": "02001",
                "fdc": "IGN",
                "sag": "IGN",
                "geometry": box(2, 0, 3, 1),
            },
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )


def fixture_config(tmp_path: Path, source: Path) -> Path:
    config = load_config().copy()
    config["expected_source_sha256"] = sha256_file(source)
    config["expected_source_size_bytes"] = source.stat().st_size
    config["expected_feature_count"] = 3
    config["snapshot_retrieved_at_utc"] = "2026-08-26T00:00:00+00:00"
    path = tmp_path / "ign-fixture-config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_exact_wfs_request_is_bounded_to_department_layer():
    config = load_config()
    assert build_wfs_url(config) == (
        "https://wms.ign.gob.ar/geoserver/ign/ows"
        "?service=WFS&version=2.0.0&request=GetFeature"
        "&typeNames=ign%3Adepartamento&outputFormat=application%2Fjson&srsName=EPSG%3A4326"
    )


def test_ign_department_preserves_native_identifiers_and_source_vocabulary():
    config = load_config().copy()
    config["expected_feature_count"] = 3
    frame = make_frame()
    normalized, audit = normalize_source(
        frame,
        config,
        source_sha256="a" * 64,
    )
    assert normalized["native_id"].tolist() == ["02001", "06001", "06002"]
    assert normalized.loc[0, "in1"] == "02001"
    assert set(normalized["gid"]) == {101, 102, 103}
    assert audit["unique_native_id_count"] == 3
    assert audit["unique_gid_count"] == 3
    assert audit["gna_values"] == ["Comuna", "Departamento", "Partido"]
    assert audit["stage_decision"] == "PASS"
    assert normalized["geo_uid"].str.contains("ign:administrative:department:aaaaaaaaaaaa:").all()


def test_ign_department_release_is_snapshot_addressed_and_detached_verifiable(tmp_path):
    source = tmp_path / "ign-fixture.geojson"
    make_frame().to_file(source, driver="GeoJSON")
    config_path = fixture_config(tmp_path, source)
    release = tmp_path / "release"
    manifest = materialize_from_source(source, release, config_path)
    verify_release(release)

    assert manifest["source_snapshot"]["snapshot_id"] == f"sha256:{sha256_file(source)}"
    assert manifest["run"]["parameters"]["geometry_repair_applied"] is False
    assert manifest["authority_status"] == "official"
    catalog = pd.read_parquet(release / "geography_catalog.parquet")
    assert catalog.iloc[0]["native_id_fields"] == "in1"
    assert catalog.iloc[0]["source_identity_fields"] == "in1,gid"
    assert catalog.iloc[0]["distribution_mode"] == "official_remote_fetch"


def test_ign_department_rejects_snapshot_drift(tmp_path):
    source = tmp_path / "ign-fixture.geojson"
    make_frame().to_file(source, driver="GeoJSON")
    config = load_config().copy()
    config["expected_source_sha256"] = "0" * 64
    config["expected_source_size_bytes"] = source.stat().st_size
    config["expected_feature_count"] = 3
    config_path = tmp_path / "bad-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot SHA-256 drift"):
        materialize_from_source(source, tmp_path / "release", config_path)


def test_ign_department_rejects_duplicate_native_id():
    config = load_config().copy()
    config["expected_feature_count"] = 4
    frame = make_frame()
    duplicate = frame.iloc[[0]].copy()
    duplicate["gid"] = 999
    frame = gpd.GeoDataFrame(pd.concat([frame, duplicate], ignore_index=True), crs=frame.crs)
    with pytest.raises(ValueError, match="native IDs must be unique"):
        normalize_source(frame, config, source_sha256="b" * 64)


def test_ign_department_retains_invalid_geometry_without_repair():
    config = load_config().copy()
    config["expected_feature_count"] = 3
    frame = make_frame()
    frame.at[0, "geometry"] = Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)])
    normalized, audit = normalize_source(frame, config, source_sha256="c" * 64)
    row = normalized.loc[normalized["native_id"].eq("06001")].iloc[0]
    assert row["geometry_role"] == "source_invalid"
    assert bool(row["geometry_valid"]) is False
    assert audit["source_invalid_geometry_count"] == 1
    assert audit["stage_decision"] == "PASS_WITH_WARNINGS"


def test_ign_department_rejects_non_areal_geometry():
    config = load_config().copy()
    config["expected_feature_count"] = 3
    frame = make_frame()
    frame.at[0, "geometry"] = Point(0, 0)
    with pytest.raises(ValueError, match="unusable source geometry"):
        normalize_source(frame, config, source_sha256="d" * 64)


def test_ign_department_rejects_schema_vocabulary_drift():
    config = load_config().copy()
    config["expected_feature_count"] = 3
    frame = make_frame()
    frame.loc[0, "gna"] = "Municipio"
    with pytest.raises(ValueError, match="gna vocabulary drifted"):
        normalize_source(frame, config, source_sha256="e" * 64)
