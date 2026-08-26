import copy
import json
import shutil
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon, box

from argentina_geography.relations.indec_ceur_2022 import (
    build_relation,
    materialize_relation,
    verify_relation,
)
from argentina_geography.sources.ceur_2022_v2025_1 import (
    materialize_from_source as materialize_ceur,
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
                "geo_uid": "indec:contained",
                "native_id": "000000003",
                "geometry_role": "analytical",
                "geometry": box(2, 0, 3, 1),
            },
            {
                "geo_uid": "indec:other",
                "native_id": "000000004",
                "geometry_role": "analytical",
                "geometry": box(3, 0, 4, 1),
            },
            {
                "geo_uid": "indec:full",
                "native_id": "000000007",
                "geometry_role": "analytical",
                "geometry": box(20, 0, 21, 1),
            },
            {
                "geo_uid": "indec:unmatched",
                "native_id": "000000005",
                "geometry_role": "analytical",
                "geometry": box(10, 0, 11, 1),
            },
            {
                "geo_uid": "indec:invalid",
                "native_id": "000000006",
                "geometry_role": "source_invalid",
                "geometry": _invalid_bowtie(30),
            },
        ],
        geometry="geometry",
        crs="EPSG:3857",
    )
    ceur = gpd.GeoDataFrame(
        [
            {
                "geo_uid": "ceur:left",
                "native_id": "000000001",
                "geometry_role": "analytical",
                "geometry": box(0, 0, 1, 1),
            },
            {
                "geo_uid": "ceur:right",
                "native_id": "000000002",
                "geometry_role": "analytical",
                "geometry": box(1, 0, 2, 1),
            },
            {
                "geo_uid": "ceur:wide",
                "native_id": "000000003",
                "geometry_role": "analytical",
                "geometry": box(2, 0, 4, 1),
            },
            {
                "geo_uid": "ceur:full",
                "native_id": "000000007",
                "geometry_role": "analytical",
                "geometry": box(20, 0, 21, 1),
            },
            {
                "geo_uid": "ceur:invalid",
                "native_id": "000000006",
                "geometry_role": "source_invalid",
                "geometry": _invalid_bowtie(30),
            },
        ],
        geometry="geometry",
        crs="EPSG:3857",
    )
    return indec, ceur


def _test_config() -> dict:
    return {
        "analysis_crs": "EPSG:3857",
        "minimum_overlap_area_m2": 0.0,
        "mutual_full_overlap_tolerance": 1e-9,
    }


def test_relation_retains_nm_and_two_sided_topology_facts():
    indec, ceur = _relation_frames()
    relation, audit = build_relation(indec, ceur, _test_config())

    split = relation.loc[relation["source_geo_uid"].eq("indec:split")]
    assert len(split) == 2
    assert set(split["target_geo_uid"]) == {"ceur:left", "ceur:right"}
    assert set(split["source_candidate_count"].astype(int)) == {2}

    wide = relation.loc[
        relation["source_geo_uid"].eq("indec:contained")
        & relation["target_geo_uid"].eq("ceur:wide")
    ].iloc[0]
    assert float(wide["overlap_share_of_source"]) == pytest.approx(1.0)
    assert float(wide["overlap_share_of_target"]) == pytest.approx(0.5)
    assert int(wide["target_candidate_count"]) == 2

    invalid = relation.loc[relation["source_geo_uid"].eq("indec:invalid")].iloc[0]
    assert invalid["relation_status"] == "invalid_geometry"
    assert pd.isna(invalid["target_geo_uid"])
    assert pd.isna(invalid["overlap_area_m2"])

    assert audit["matched_single"] == 3
    assert audit["matched_multiple"] == 1
    assert audit["unmatched_outside"] == 1
    assert audit["invalid_source_geometry"] == 1
    assert audit["source_invalid_geometry_rows"] == 1
    assert audit["target_invalid_geometry_rows"] == 1
    assert audit["positive_relation_rows"] == 5
    assert audit["source_multiplicity_distribution"] == {"0": 1, "1": 3, "2": 1}
    assert audit["target_multiplicity_distribution"] == {"1": 3, "2": 1}
    assert audit["target_matched_single"] == 3
    assert audit["target_matched_multiple"] == 1


def test_target_share_answers_geometry_question_not_available_from_source_share():
    indec, ceur = _relation_frames()
    relation, audit = build_relation(indec, ceur, _test_config())

    same_contained = relation.loc[
        relation["source_geo_uid"].eq("indec:contained")
        & relation["target_geo_uid"].eq("ceur:wide")
    ].iloc[0]
    same_full = relation.loc[
        relation["source_geo_uid"].eq("indec:full")
        & relation["target_geo_uid"].eq("ceur:full")
    ].iloc[0]

    assert bool(same_contained["same_native_id"]) is True
    assert float(same_contained["overlap_share_of_source"]) == pytest.approx(1.0)
    assert float(same_contained["overlap_share_of_target"]) == pytest.approx(0.5)

    assert bool(same_full["same_native_id"]) is True
    assert float(same_full["overlap_share_of_source"]) == pytest.approx(1.0)
    assert float(same_full["overlap_share_of_target"]) == pytest.approx(1.0)

    assert audit["positive_same_native_id_rows"] == 3
    assert audit["positive_different_native_id_rows"] == 2
    assert audit["same_native_id_mutual_full_overlap_rows"] == 1
    assert audit["same_native_id_geometry_difference_rows"] == 2
    assert audit["target_side_overlap_share_required"] is True

    assert not any(
        token in column.lower()
        for column in relation.columns
        for token in ("winner", "selected", "canonical", "corrected", "nearest")
    )


def _write_parent_sources(tmp_path: Path) -> tuple[Path, Path]:
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
    ceur = gpd.GeoDataFrame(
        [
            {
                "COD_2022": "020010101",
                "PROV": "02",
                "DEPTO": "001",
                "FRACC": "01",
                "RADIO": "01",
                "OBS2022": None,
                "VIV_TOT_P": 100,
                "POB_TOT_P": 300,
                "REDATAM": "SI",
                "geometry": box(0, 0, 1, 1),
            },
            {
                "COD_2022": "060140205",
                "PROV": "06",
                "DEPTO": "014",
                "FRACC": "02",
                "RADIO": "05",
                "OBS2022": None,
                "VIV_TOT_P": 80,
                "POB_TOT_P": 240,
                "REDATAM": "SI",
                "geometry": box(1, 0, 2, 1),
            },
        ],
        geometry="geometry",
        crs="EPSG:3857",
    )
    indec_path = tmp_path / "indec.geojson"
    ceur_path = tmp_path / "ceur.geojson"
    indec.to_file(indec_path, driver="GeoJSON")
    ceur.to_file(ceur_path, driver="GeoJSON")
    return indec_path, ceur_path


def _pin_parent(manifest: dict) -> dict:
    return {
        "dataset_id": manifest["dataset"]["dataset_id"],
        "release_version": manifest["dataset"]["version"],
        "source_snapshot_sha256": manifest["source_snapshot"]["snapshot_id"].removeprefix(
            "sha256:"
        ),
        "content_sha256": manifest["dataset"]["content_sha256"],
    }


def test_relation_bundle_is_detached_verifiable_and_binds_parent_content(tmp_path):
    indec_source, ceur_source = _write_parent_sources(tmp_path)
    indec_release = tmp_path / "indec-release"
    ceur_release = tmp_path / "ceur-release"
    indec_manifest = materialize_indec(indec_source, indec_release)
    ceur_manifest = materialize_ceur(ceur_source, ceur_release)

    config = {
        "relation_id": "arggeo.relation.indec-ceur.census.2022.radio.fixture",
        "source_parent": _pin_parent(indec_manifest),
        "target_parent": _pin_parent(ceur_manifest),
        "analysis_crs": "EPSG:3857",
        "minimum_overlap_area_m2": 0.0,
        "mutual_full_overlap_tolerance": 1e-9,
        "interpretation": "fixture geometric relation only",
        "known_limitations": [],
    }
    config_path = tmp_path / "relation-config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    release = tmp_path / "relation-release"
    manifest = materialize_relation(
        indec_release,
        ceur_release,
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
    summary = (release / "comparison_summary.md").read_text(encoding="utf-8")
    assert "## Identity differences" in summary
    assert "## Geometry differences with the same native ID" in summary

    bad = copy.deepcopy(config)
    bad["source_parent"]["content_sha256"] = "0" * 64
    bad_path = tmp_path / "bad-config.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="content hash mismatch"):
        verify_relation(detached, bad_path)
