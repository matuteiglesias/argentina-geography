import copy
import json
import shutil
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon, box

from argentina_geography.products import sha256_file
from argentina_geography.relations.indec_2022_ign_department import (
    build_relation,
    materialize_relation,
    verify_relation,
)
from argentina_geography.sources.ign_department import (
    load_config as load_ign_config,
    materialize_from_source as materialize_ign,
)
from argentina_geography.sources.indec_2022_radio import (
    materialize_from_source as materialize_indec,
)


def _invalid_bowtie(x: float) -> Polygon:
    return Polygon([(x, 0), (x + 1, 1), (x, 1), (x + 1, 0), (x, 0)])


def _relation_frames() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    indec = gpd.GeoDataFrame(
        [
            {
                "geo_uid": "indec:split",
                "native_id": "000000001",
                "geometry_role": "analytical",
                "geometry": box(0, 0, 2, 1),
            },
            {
                "geo_uid": "indec:north",
                "native_id": "000000002",
                "geometry_role": "analytical",
                "geometry": box(0, 1, 1, 2),
            },
            {
                "geo_uid": "indec:unmatched",
                "native_id": "000000003",
                "geometry_role": "analytical",
                "geometry": box(10, 0, 11, 1),
            },
            {
                "geo_uid": "indec:invalid",
                "native_id": "000000004",
                "geometry_role": "source_invalid",
                "geometry": _invalid_bowtie(30),
            },
        ],
        geometry="geometry",
        crs="EPSG:3857",
    )
    ign = gpd.GeoDataFrame(
        [
            {
                "geo_uid": "ign:west",
                "native_id": "06001",
                "geometry_role": "analytical",
                "geometry": box(0, 0, 1, 2),
            },
            {
                "geo_uid": "ign:east",
                "native_id": "06002",
                "geometry_role": "analytical",
                "geometry": box(1, 0, 2, 1),
            },
            {
                "geo_uid": "ign:unreferenced",
                "native_id": "94021",
                "geometry_role": "analytical",
                "geometry": box(20, 0, 21, 1),
            },
            {
                "geo_uid": "ign:invalid",
                "native_id": "99999",
                "geometry_role": "source_invalid",
                "geometry": _invalid_bowtie(40),
            },
        ],
        geometry="geometry",
        crs="EPSG:3857",
    )
    return indec, ign


def _test_config() -> dict:
    return {
        "analysis_crs": "EPSG:3857",
        "minimum_overlap_area_m2": 0.0,
        "coverage_tolerance": 1e-9,
    }


def test_relation_retains_nm_unmatched_invalid_and_target_topology():
    indec, ign = _relation_frames()
    relation, audit = build_relation(indec, ign, _test_config())

    split = relation.loc[relation["source_geo_uid"].eq("indec:split")]
    assert len(split) == 2
    assert set(split["target_geo_uid"]) == {"ign:west", "ign:east"}
    assert set(split["source_candidate_count"].astype(int)) == {2}
    assert sorted(split["overlap_share_of_source"].astype(float)) == pytest.approx([0.5, 0.5])

    west_from_split = split.loc[split["target_geo_uid"].eq("ign:west")].iloc[0]
    assert float(west_from_split["overlap_share_of_target"]) == pytest.approx(0.5)
    assert int(west_from_split["target_candidate_count"]) == 2

    unmatched = relation.loc[relation["source_geo_uid"].eq("indec:unmatched")].iloc[0]
    assert unmatched["relation_status"] == "unmatched_outside"
    assert pd.isna(unmatched["target_geo_uid"])

    invalid = relation.loc[relation["source_geo_uid"].eq("indec:invalid")].iloc[0]
    assert invalid["relation_status"] == "invalid_geometry"
    assert pd.isna(invalid["target_geo_uid"])

    assert audit["matched_single"] == 1
    assert audit["matched_multiple"] == 1
    assert audit["unmatched_outside"] == 1
    assert audit["invalid_source_geometry"] == 1
    assert audit["positive_relation_rows"] == 3
    assert audit["source_multiplicity_distribution"] == {"0": 1, "1": 1, "2": 1}
    assert audit["target_multiplicity_distribution"] == {"0": 1, "1": 1, "2": 1}
    assert audit["referenced_analytical_targets"] == 2
    assert audit["unreferenced_analytical_targets"] == 1
    assert audit["target_invalid_geometry_rows"] == 1
    assert audit["source_coverage_counts"] == {
        "zero": 1,
        "partial": 0,
        "near_full": 2,
        "over_one": 0,
    }
    assert audit["target_coverage_counts"] == {
        "zero": 1,
        "partial": 0,
        "near_full": 2,
        "over_one": 0,
    }

    assert not any(
        token in column.lower()
        for column in relation.columns
        for token in ("winner", "selected", "assigned", "nearest", "replacement")
    )


def _write_parent_sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    indec = gpd.GeoDataFrame(
        [
            {
                "fid": 1,
                "id": 101,
                "sag": "fixture",
                "tro": "U",
                "jur": "Ciudad Autónoma de Buenos Aires",
                "cpr": 2,
                "cde": "02001",
                "dpto": "Comuna 1",
                "cfn": 1,
                "cro": 1,
                "cod_indec": 20010101,
                "geometry": box(0, 0, 1, 1),
            },
            {
                "fid": 2,
                "id": 102,
                "sag": "fixture",
                "tro": "U",
                "jur": "Buenos Aires",
                "cpr": 6,
                "cde": "06014",
                "dpto": "Fixture",
                "cfn": 2,
                "cro": 5,
                "cod_indec": 60140205,
                "geometry": box(1, 0, 2, 1),
            },
        ],
        geometry="geometry",
        crs="EPSG:3857",
    )
    ign = gpd.GeoDataFrame(
        [
            {
                "OBJECTID": 101,
                "Entidad": 0,
                "Objeto": "Departamento",
                "FNA": "Comuna 1",
                "GNA": "Comuna",
                "NAM": "Comuna 1",
                "SAG": "fixture",
                "FDC": "fixture",
                "IN1": "02001",
                "SHAPE_STAr": 1.0,
                "SHAPE_STLe": 4.0,
                "geometry": box(0, 0, 1, 1),
            },
            {
                "OBJECTID": 102,
                "Entidad": 0,
                "Objeto": "Departamento",
                "FNA": "Partido Fixture",
                "GNA": "Partido",
                "NAM": "Fixture",
                "SAG": "fixture",
                "FDC": "fixture",
                "IN1": "06014",
                "SHAPE_STAr": 1.0,
                "SHAPE_STLe": 4.0,
                "geometry": box(1, 0, 2, 1),
            },
            {
                "OBJECTID": 103,
                "Entidad": 0,
                "Objeto": "Departamento",
                "FNA": "Departamento Fixture",
                "GNA": "Departamento",
                "NAM": "Fixture 2",
                "SAG": "fixture",
                "FDC": "fixture",
                "IN1": "10001",
                "SHAPE_STAr": 1.0,
                "SHAPE_STLe": 4.0,
                "geometry": box(3, 0, 4, 1),
            },
        ],
        geometry="geometry",
        crs="EPSG:3857",
    )
    indec_path = tmp_path / "indec.geojson"
    ign_path = tmp_path / "ign.geojson"
    indec.to_file(indec_path, driver="GeoJSON")
    ign.to_file(ign_path, driver="GeoJSON")

    ign_config = load_ign_config().copy()
    ign_config["expected_source_sha256"] = sha256_file(ign_path)
    ign_config["expected_source_size_bytes"] = ign_path.stat().st_size
    ign_config["expected_normalized_content_sha256"] = None
    ign_config["expected_feature_count"] = 3
    ign_config["snapshot_retrieved_at_utc"] = "2026-08-26T00:00:00+00:00"
    ign_config_path = tmp_path / "ign-config.json"
    ign_config_path.write_text(json.dumps(ign_config), encoding="utf-8")
    return indec_path, ign_path, ign_config_path


def _pin_parent(manifest: dict) -> dict:
    return {
        "dataset_id": manifest["dataset"]["dataset_id"],
        "release_version": manifest["dataset"]["version"],
        "source_snapshot_sha256": manifest["source_snapshot"]["snapshot_id"].removeprefix(
            "sha256:"
        ),
        "content_sha256": manifest["dataset"]["content_sha256"],
    }


def test_relation_bundle_is_detached_verifiable_and_binds_exact_parents(tmp_path):
    indec_source, ign_source, ign_config = _write_parent_sources(tmp_path)
    indec_release = tmp_path / "indec-release"
    ign_release = tmp_path / "ign-release"
    indec_manifest = materialize_indec(indec_source, indec_release)
    ign_manifest = materialize_ign(ign_source, ign_release, ign_config)

    config = {
        "relation_id": "arggeo.relation.indec-2022-radio-ign-department.fixture",
        "source_parent": _pin_parent(indec_manifest),
        "target_parent": _pin_parent(ign_manifest),
        "foundation": {
            "repository": "fixture",
            "commit_sha": "fixture",
            "overlap_blob_sha": "fixture",
            "callable": "spatial_foundation.geography.relate_areal_objects",
        },
        "analysis_crs": "EPSG:3857",
        "minimum_overlap_area_m2": 0.0,
        "coverage_tolerance": 1e-9,
        "interpretation": "fixture geometric relation only",
        "known_limitations": [],
    }
    config_path = tmp_path / "relation-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    release = tmp_path / "relation-release"
    manifest = materialize_relation(
        indec_release,
        ign_release,
        release,
        config_path,
    )
    verify_relation(release, config_path)

    detached = tmp_path / "detached"
    shutil.copytree(release, detached)
    verify_relation(detached, config_path)

    assert manifest["parents"]["source_dataset"]["content_sha256"] == config[
        "source_parent"
    ]["content_sha256"]
    assert manifest["parents"]["target_dataset"]["content_sha256"] == config[
        "target_parent"
    ]["content_sha256"]
    assert manifest["one_target_assignment_applied"] is False
    assert manifest["preferred_boundary_applied"] is False
    summary = (release / "relation_summary.md").read_text(encoding="utf-8")
    assert "## Exact parents" in summary
    assert "## Census-radio side" in summary
    assert "## IGN-target side" in summary

    bad = copy.deepcopy(config)
    bad["target_parent"]["content_sha256"] = "0" * 64
    bad_path = tmp_path / "bad-config.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="content hash mismatch"):
        verify_relation(detached, bad_path)
