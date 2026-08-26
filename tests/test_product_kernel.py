import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

from argentina_geography.fixture import build_fixture_products, verify_fixture_products


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_product_fixture_separates_geography_relation_and_crosswalk(tmp_path):
    output = tmp_path / "product-fixture-v1"
    build_fixture_products(output)
    verify_fixture_products(output)

    geography_catalog = pd.read_parquet(output / "geography_catalog.parquet")
    relation_catalog = pd.read_parquet(output / "relation_catalog.parquet")
    assert set(geography_catalog["dataset_id"]) == {
        "arggeo.fixture.census-geography",
        "arggeo.fixture.admin-geography",
    }
    assert relation_catalog["relation_id"].tolist() == [
        "arggeo.fixture.census-admin-relation"
    ]
    assert relation_catalog["policy_id"].isna().all()

    relation = pd.read_parquet(output / "relations/census-admin/relations.parquet")
    crossing = relation[
        relation["source_geo_uid"] == "synthetic:fixture-v1:census:unit:00002"
    ]
    assert crossing["target_geo_uid"].notna().sum() == 2
    assert crossing["source_candidate_count"].tolist() == [2, 2]
    assert set(crossing["relation_status"]) == {"matched_multiple"}

    crosswalk = pd.read_parquet(
        output / "crosswalks/census-admin-largest-overlap/crosswalk.parquet"
    )
    selected = crosswalk.loc[
        crosswalk["source_geo_uid"] == "synthetic:fixture-v1:census:unit:00002"
    ].iloc[0]
    assert selected["selected_target_geo_uid"] == (
        "synthetic:fixture-v1:admin:unit:10102"
    )
    assert selected["assignment_status"] == "matched"
    assert selected["candidate_count"] == 2


def test_fixture_source_policy_stays_local_and_auditable(tmp_path):
    output = tmp_path / "product-fixture-v1"
    root = build_fixture_products(output)
    audit = root["fixture_audit"]
    assert audit["input_census_occurrences"] == 6
    assert audit["released_census_features"] == 4
    assert audit["duplicate_occurrences_excluded"] == 2
    assert audit["duplicate_ids"] == ["00005"]
    assert audit["repaired_features"] == 1
    assert audit["repairs"][0]["native_id"] == "00004"

    census = gpd.read_parquet(
        output / "geographies/synthetic-census/geography.parquet"
    )
    assert census["geo_uid"].is_unique
    assert set(census["native_id"]) == {"00001", "00002", "00003", "00004"}
    repaired = census.loc[census["native_id"] == "00004"].iloc[0]
    assert bool(repaired["geometry_repaired"])
    assert repaired.geometry.is_valid


def test_manifests_bind_relation_to_exact_parent_datasets(tmp_path):
    output = tmp_path / "product-fixture-v1"
    build_fixture_products(output)
    relation_manifest = read_json(output / "relations/census-admin/manifest.json")
    crosswalk_manifest = read_json(
        output / "crosswalks/census-admin-largest-overlap/manifest.json"
    )

    assert relation_manifest["relation_method"] == (
        "spatial_foundation.geography.relate_areal_objects"
    )
    assert relation_manifest["run"]["parameters"]["adjudication_applied"] is False
    assert relation_manifest["parents"] == {
        "source_dataset_id": "arggeo.fixture.census-geography",
        "source_version": "fixture-v1",
        "target_dataset_id": "arggeo.fixture.admin-geography",
        "target_version": "fixture-v1",
    }
    assert crosswalk_manifest["parent_relation"]["dataset_id"] == (
        "arggeo.fixture.census-admin-relation"
    )
    assert crosswalk_manifest["policy"]["policy_id"] == (
        "bounded-fixture-largest-overlap-v1"
    )


def test_verify_uses_only_built_artifact_tree(tmp_path):
    output = tmp_path / "product-fixture-v1"
    build_fixture_products(output)
    moved = tmp_path / "detached-product-fixture"
    output.rename(moved)
    verify_fixture_products(moved)
