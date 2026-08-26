import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon, box

from argentina_geography.relations.ceur_2010_2022 import (
    build_pattern_examples,
    build_relation,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/relations/ceur_census_2010_2022_radio.json"


def _invalid_bowtie(x: float) -> Polygon:
    return Polygon([(x, 0), (x + 1, 1), (x, 1), (x + 1, 0), (x, 0)])


def _config() -> dict:
    return {
        "analysis_crs": "EPSG:3857",
        "minimum_overlap_area_m2": 0.0,
        "coverage_tolerance": 1e-9,
        "same_id_mutual_full_overlap_tolerance": 1e-9,
        "derived_examples": {
            "interpretation_version": "test-patterns/v1",
            "stable_mutual_overlap_min": 0.999999,
            "max_example_edges_preferred": 12,
        },
    }


def _frames() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    source = gpd.GeoDataFrame(
        [
            {
                "geo_uid": "ceur:2010:stable",
                "native_id": "000000001",
                "geometry_role": "analytical",
                "geometry": box(0, 0, 1, 1),
            },
            {
                "geo_uid": "ceur:2010:split",
                "native_id": "000000002",
                "geometry_role": "analytical",
                "geometry": box(2, 0, 4, 1),
            },
            {
                "geo_uid": "ceur:2010:merge-a",
                "native_id": "000000003",
                "geometry_role": "analytical",
                "geometry": box(5, 0, 6, 1),
            },
            {
                "geo_uid": "ceur:2010:merge-b",
                "native_id": "000000004",
                "geometry_role": "analytical",
                "geometry": box(6, 0, 7, 1),
            },
            {
                "geo_uid": "ceur:2010:complex-a",
                "native_id": "000000005",
                "geometry_role": "analytical",
                "geometry": box(8, 0, 10, 1),
            },
            {
                "geo_uid": "ceur:2010:complex-b",
                "native_id": "000000006",
                "geometry_role": "analytical",
                "geometry": box(8, 1, 10, 2),
            },
            {
                "geo_uid": "ceur:2010:unmatched",
                "native_id": "000000007",
                "geometry_role": "analytical",
                "geometry": box(20, 0, 21, 1),
            },
            {
                "geo_uid": "ceur:2010:invalid",
                "native_id": "000000008",
                "geometry_role": "source_invalid",
                "geometry": _invalid_bowtie(30),
            },
        ],
        geometry="geometry",
        crs="EPSG:3857",
    )
    target = gpd.GeoDataFrame(
        [
            {
                "geo_uid": "ceur:2022:stable",
                "native_id": "000000001",
                "geometry_role": "analytical",
                "geometry": box(0, 0, 1, 1),
            },
            {
                "geo_uid": "ceur:2022:split-a",
                "native_id": "100000001",
                "geometry_role": "analytical",
                "geometry": box(2, 0, 3, 1),
            },
            {
                "geo_uid": "ceur:2022:split-b",
                "native_id": "100000002",
                "geometry_role": "analytical",
                "geometry": box(3, 0, 4, 1),
            },
            {
                "geo_uid": "ceur:2022:merge",
                "native_id": "100000003",
                "geometry_role": "analytical",
                "geometry": box(5, 0, 7, 1),
            },
            {
                "geo_uid": "ceur:2022:complex-a",
                "native_id": "100000004",
                "geometry_role": "analytical",
                "geometry": box(8, 0, 9, 2),
            },
            {
                "geo_uid": "ceur:2022:complex-b",
                "native_id": "100000005",
                "geometry_role": "analytical",
                "geometry": box(9, 0, 10, 2),
            },
            {
                "geo_uid": "ceur:2022:unreferenced",
                "native_id": "100000006",
                "geometry_role": "analytical",
                "geometry": box(22, 0, 23, 1),
            },
            {
                "geo_uid": "ceur:2022:invalid",
                "native_id": "100000007",
                "geometry_role": "source_invalid",
                "geometry": _invalid_bowtie(40),
            },
        ],
        geometry="geometry",
        crs="EPSG:3857",
    )
    return source, target


def test_relation_keeps_explicit_two_sided_nm_facts_and_coverage():
    source, target = _frames()
    relation, audit = build_relation(source, target, _config())

    assert audit["positive_relation_rows"] == 9
    assert audit["source_invalid_geometry_rows"] == 1
    assert audit["target_invalid_geometry_rows"] == 1
    assert audit["source_multiplicity_distribution"] == {"0": 1, "1": 3, "2": 3}
    assert audit["target_multiplicity_distribution"] == {"0": 1, "1": 3, "2": 3}
    assert audit["component_shape_distribution"] == {
        "1x1": 1,
        "1xN": 1,
        "Nx1": 1,
        "NxM": 1,
    }
    assert audit["source_coverage_counts"] == {
        "zero": 1,
        "partial": 0,
        "near_full": 6,
        "over_one": 0,
    }
    assert audit["target_coverage_counts"] == {
        "zero": 1,
        "partial": 0,
        "near_full": 6,
        "over_one": 0,
    }

    split = relation.loc[relation["source_geo_uid"].eq("ceur:2010:split")]
    assert len(split) == 2
    assert set(split["source_candidate_count"].astype(int)) == {2}
    assert sorted(split["overlap_share_of_source"].astype(float)) == pytest.approx([0.5, 0.5])
    assert set(split["target_candidate_count"].astype(int)) == {1}
    assert set(split["overlap_share_of_target"].astype(float)) == pytest.approx({1.0})

    merge = relation.loc[relation["target_geo_uid"].eq("ceur:2022:merge")]
    assert len(merge) == 2
    assert set(merge["source_candidate_count"].astype(int)) == {1}
    assert set(merge["target_candidate_count"].astype(int)) == {2}
    assert sorted(merge["overlap_share_of_target"].astype(float)) == pytest.approx([0.5, 0.5])

    unmatched = relation.loc[
        relation["source_geo_uid"].eq("ceur:2010:unmatched")
    ].iloc[0]
    assert unmatched["relation_status"] == "unmatched_outside"
    assert pd.isna(unmatched["target_geo_uid"])

    invalid = relation.loc[relation["source_geo_uid"].eq("ceur:2010:invalid")].iloc[0]
    assert invalid["relation_status"] == "invalid_geometry"
    assert pd.isna(invalid["target_geo_uid"])

    prohibited = ("population", "allocation", "transfer_weight", "winner", "canonical")
    assert not any(
        token in column.lower()
        for column in relation.columns
        for token in prohibited
    )
    assert not any("pattern" in column.lower() for column in relation.columns)


def test_examples_are_versioned_separate_interpretations_with_all_four_patterns():
    source, target = _frames()
    relation, _ = build_relation(source, target, _config())
    examples = build_pattern_examples(relation, _config())

    assert examples["interpretation_version"] == "test-patterns/v1"
    assert examples["stored_on_relation_rows"] is False
    assert examples["thresholds"]["stable_mutual_overlap_min"] == 0.999999
    assert examples["derived_pattern_counts"] == {
        "stable": 1,
        "split": 1,
        "merge": 1,
        "complex": 1,
        "one_to_one_below_stable_threshold": 0,
    }
    for pattern in ("stable", "split", "merge", "complex"):
        assert examples["examples"][pattern] is not None
    assert examples["examples"]["complex"]["source_count"] == 2
    assert examples["examples"]["complex"]["target_count"] == 2
    assert examples["examples"]["complex"]["edge_count"] == 4


def test_equal_native_id_does_not_imply_stable_geometry():
    source = gpd.GeoDataFrame(
        [
            {
                "geo_uid": "ceur:2010:same-id",
                "native_id": "000000001",
                "geometry_role": "analytical",
                "geometry": box(0, 0, 1, 1),
            }
        ],
        geometry="geometry",
        crs="EPSG:3857",
    )
    target = gpd.GeoDataFrame(
        [
            {
                "geo_uid": "ceur:2022:same-id",
                "native_id": "000000001",
                "geometry_role": "analytical",
                "geometry": box(0, 0, 2, 1),
            }
        ],
        geometry="geometry",
        crs="EPSG:3857",
    )
    relation, audit = build_relation(source, target, _config())
    row = relation.iloc[0]
    assert bool(row["same_native_id"]) is True
    assert float(row["overlap_share_of_source"]) == pytest.approx(1.0)
    assert float(row["overlap_share_of_target"]) == pytest.approx(0.5)
    assert audit["same_native_id_mutual_full_overlap_rows"] == 0
    assert audit["same_native_id_geometry_difference_rows"] == 1

    examples = build_pattern_examples(relation, _config())
    assert examples["derived_pattern_counts"]["stable"] == 0
    assert examples["derived_pattern_counts"]["one_to_one_below_stable_threshold"] == 1
    assert examples["examples"]["stable"] is None


def test_config_pins_exact_harmonized_parents_and_forbids_allocation_semantics():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert config["source_parent"] == {
        "dataset_id": "arggeo.ceur.census.2010.radio",
        "release_version": "v2025-1-2010-464e9b4c265a",
        "source_snapshot_sha256": "464e9b4c265a27f46a48e0c5914ef4e833c14e8977b8f0c9c1eaad672f374baa",
        "content_sha256": "d2095144bc31a34bd09c8fc0a130a872f41016541a8b87daddd52aace759a23e",
    }
    assert config["target_parent"] == {
        "dataset_id": "arggeo.ceur.census.2022.radio",
        "release_version": "v2025-1-2022-d3a6f4c95102",
        "source_snapshot_sha256": "d3a6f4c951022130d19a894984eb1315b0c9096314afb1fe2ac79eb9c85da3c8",
        "content_sha256": "6ff1fc751585a9c94a7ed73c32b8337d05f0a31cc833b8958425fb4dbb7cb6fe",
    }
    assert config["foundation_kernel"]["commit_sha"] == (
        "0347b5f138d9ca62e903c28bbc7ba3c35ea891d5"
    )
    assert config["policy"] == "geometric_relation_only"
