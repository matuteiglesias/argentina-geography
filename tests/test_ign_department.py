import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon, box

from argentina_geography.products import sha256_file
from argentina_geography.sources.ign_department import (
    load_config,
    materialize_from_source,
    normalize_source,
    verify_release,
)


def make_frame() -> gpd.GeoDataFrame:
    rows = []
    specs = [
        (101, "06001", "Departamento", "Departamento Norte", "Norte", box(0, 0, 1, 1)),
        (102, "06002", "Partido", "Partido de Sur", "Sur", box(1, 0, 2, 1)),
        (103, "02001", "Comuna", "Comuna Centro", "Centro", box(2, 0, 3, 1)),
    ]
    for object_id, in1, gna, fna, nam, geometry in specs:
        rows.append(
            {
                "OBJECTID": object_id,
                "Entidad": 0,
                "Objeto": "Departamento",
                "FNA": fna,
                "GNA": gna,
                "NAM": nam,
                "SAG": "Fixture source agency",
                "FDC": "Fixture capture method",
                "IN1": in1,
                "SHAPE_STAr": float(object_id),
                "SHAPE_STLe": float(object_id) / 10,
                "geometry": geometry,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def fixture_config(tmp_path: Path, source: Path) -> Path:
    config = load_config().copy()
    config["expected_source_sha256"] = sha256_file(source)
    config["expected_source_size_bytes"] = source.stat().st_size
    config["expected_normalized_content_sha256"] = None
    config["expected_feature_count"] = 3
    config["snapshot_retrieved_at_utc"] = "2026-08-26T00:00:00+00:00"
    path = tmp_path / "ign-fixture-config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_exact_archive_identity_is_pinned():
    config = load_config()
    assert config["source_url"] == (
        "https://www.ign.gob.ar/descargas/geodatos/SHAPES/ign_departamento.zip"
    )
    assert config["archive_member"] == "ign_departamento/ign_departamento.shp"
    assert config["expected_source_sha256"] == (
        "33871350bd2da7e146e3daa9f696351b167c5feabeee0673d43b6671e10cb42c"
    )
    assert config["expected_source_size_bytes"] == 23697566


def test_ign_department_preserves_native_identifiers_and_source_vocabulary():
    config = load_config().copy()
    config["expected_feature_count"] = 3
    normalized, audit = normalize_source(make_frame(), config, source_sha256="a" * 64)
    assert normalized["native_id"].tolist() == ["02001", "06001", "06002"]
    assert normalized.loc[0, "IN1"] == "02001"
    assert set(normalized["OBJECTID"]) == {101, 102, 103}
    assert set(config["preserved_native_fields"]).issubset(normalized.columns)
    assert audit["unique_native_id_count"] == 3
    assert audit["unique_secondary_source_id_count"] == 3
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
    assert catalog.iloc[0]["native_id_fields"] == "IN1"
    assert catalog.iloc[0]["source_identity_fields"] == "IN1,OBJECTID"
    assert catalog.iloc[0]["distribution_mode"] == "official_remote_fetch"


def test_ign_department_rejects_snapshot_drift(tmp_path):
    source = tmp_path / "ign-fixture.geojson"
    make_frame().to_file(source, driver="GeoJSON")
    config = load_config().copy()
    config["expected_source_sha256"] = "0" * 64
    config["expected_source_size_bytes"] = source.stat().st_size
    config["expected_normalized_content_sha256"] = None
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
    duplicate["OBJECTID"] = 999
    frame = gpd.GeoDataFrame(
        pd.concat([frame, duplicate], ignore_index=True),
        geometry="geometry",
        crs=frame.crs,
    )
    with pytest.raises(ValueError, match="native IDs must be unique"):
        normalize_source(frame, config, source_sha256="b" * 64)


def test_ign_department_rejects_duplicate_secondary_source_id():
    config = load_config().copy()
    config["expected_feature_count"] = 3
    frame = make_frame()
    frame.loc[1, "OBJECTID"] = frame.loc[0, "OBJECTID"]
    with pytest.raises(ValueError, match="OBJECTID must be non-missing and unique"):
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
    frame.loc[0, "GNA"] = "Municipio"
    with pytest.raises(ValueError, match="GNA vocabulary drifted"):
        normalize_source(frame, config, source_sha256="e" * 64)
