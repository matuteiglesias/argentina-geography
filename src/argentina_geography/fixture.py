from __future__ import annotations

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import geopandas as gpd
import pandas as pd
from empirical_contracts import GeographySpec

from .fixture_io import prepare_geographies
from .fixture_relations import build_crosswalk, build_relation
from .product_writer import (
    source_snapshot,
    write_crosswalk_bundle,
    write_geography_bundle,
    write_relation_bundle,
)
from .products import (
    read_json,
    sha256_file,
    validate_manifest,
    verify_checksums,
    write_checksums,
    write_json,
)

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "fixtures/census_units.geojson"
ADMINS = ROOT / "fixtures/admin_candidates.geojson"
POLICY = ROOT / "config/reconciliation_policy.json"
OUTPUT = ROOT / "releases/product-fixture-v1"


def _write_catalogs(
    output: Path,
    *,
    census,
    admins,
    census_dataset,
    admin_dataset,
    relation_dataset,
    relation_audit: dict,
) -> None:
    geography_catalog = pd.DataFrame(
        [
            {
                "geography_id": census_dataset.geography.id,
                "dataset_id": census_dataset.dataset_id,
                "release_version": census_dataset.version,
                "schema_version": census_dataset.schema_version,
                "provider": "synthetic",
                "scheme": "census",
                "vintage": "fixture-v1",
                "level": "unit",
                "source_release": "fixture-v1",
                "authority_status": "synthetic_fixture",
                "feature_count": len(census),
                "native_id_fields": "native_id,province_id",
                "geometry_types": ",".join(sorted(census.geom_type.unique())),
                "storage_crs": str(census.crs),
                "coverage_status": "fixture_only",
                "artifact_ref": "geographies/synthetic-census/geography.parquet",
                "manifest_ref": "geographies/synthetic-census/manifest.json",
            },
            {
                "geography_id": admin_dataset.geography.id,
                "dataset_id": admin_dataset.dataset_id,
                "release_version": admin_dataset.version,
                "schema_version": admin_dataset.schema_version,
                "provider": "synthetic",
                "scheme": "admin",
                "vintage": "fixture-v1",
                "level": "unit",
                "source_release": "fixture-v1",
                "authority_status": "synthetic_fixture",
                "feature_count": len(admins),
                "native_id_fields": "native_id,province_id",
                "geometry_types": ",".join(sorted(admins.geom_type.unique())),
                "storage_crs": str(admins.crs),
                "coverage_status": "fixture_only",
                "artifact_ref": "geographies/synthetic-admin/geography.parquet",
                "manifest_ref": "geographies/synthetic-admin/manifest.json",
            },
        ]
    ).sort_values("geography_id", ignore_index=True)
    matched = relation_audit["matched_single"] + relation_audit["matched_multiple"]
    relation_catalog = pd.DataFrame(
        [
            {
                "relation_id": relation_dataset.dataset_id,
                "release_version": relation_dataset.version,
                "source_geography_id": census_dataset.geography.id,
                "source_release_version": census_dataset.version,
                "target_geography_id": admin_dataset.geography.id,
                "target_release_version": admin_dataset.version,
                "relation_type": "areal_positive_overlap",
                "policy_id": pd.NA,
                "matched_count": matched,
                "ambiguous_count": 0,
                "unmatched_count": relation_audit["unmatched_outside"],
                "coverage_share": matched / relation_audit["input_sources"],
                "artifact_ref": "relations/census-admin/relations.parquet",
                "manifest_ref": "relations/census-admin/manifest.json",
            }
        ]
    )
    geography_catalog.to_parquet(output / "geography_catalog.parquet", index=False)
    relation_catalog.to_parquet(output / "relation_catalog.parquet", index=False)


def build_fixture_products(output: Path) -> dict:
    policy = read_json(POLICY)
    census, admins, geography_audit = prepare_geographies(UNITS, ADMINS, policy)
    relation, relation_audit = build_relation(census, admins, policy)
    crosswalk, crosswalk_audit = build_crosswalk(census, relation, policy)

    census_dataset = write_geography_bundle(
        output / "geographies" / "synthetic-census",
        census,
        dataset_id="arggeo.fixture.census-geography",
        geography=GeographySpec(
            provider="synthetic", version="fixture-v1", scheme="census", level="unit"
        ),
        snapshot=source_snapshot(UNITS, source="synthetic-census-fixture"),
        qa_metrics={
            "input_occurrences": geography_audit["input_census_occurrences"],
            "released_features": geography_audit["released_census_features"],
            "duplicate_occurrences_excluded": geography_audit[
                "duplicate_occurrences_excluded"
            ],
            "repaired_features": geography_audit["repaired_features"],
            "invalid_after_repair": 0,
        },
    )
    admin_dataset = write_geography_bundle(
        output / "geographies" / "synthetic-admin",
        admins,
        dataset_id="arggeo.fixture.admin-geography",
        geography=GeographySpec(
            provider="synthetic", version="fixture-v1", scheme="admin", level="unit"
        ),
        snapshot=source_snapshot(ADMINS, source="synthetic-admin-fixture"),
        qa_metrics={"released_features": geography_audit["released_admin_features"]},
    )
    relation_dataset = write_relation_bundle(
        output / "relations" / "census-admin",
        relation,
        source_dataset=census_dataset,
        target_dataset=admin_dataset,
        qa_metrics=relation_audit,
        policy=policy,
    )
    crosswalk_dataset = write_crosswalk_bundle(
        output / "crosswalks" / "census-admin-largest-overlap",
        crosswalk,
        relation_dataset=relation_dataset,
        qa_metrics=crosswalk_audit,
        policy=policy,
    )

    output.mkdir(parents=True, exist_ok=True)
    _write_catalogs(
        output,
        census=census,
        admins=admins,
        census_dataset=census_dataset,
        admin_dataset=admin_dataset,
        relation_dataset=relation_dataset,
        relation_audit=relation_audit,
    )
    root_manifest = {
        "schema_version": "arggeo.fixture-product-bundle/v1",
        "release_id": "product-fixture-v1",
        "products": {
            "geographies": [
                census_dataset.model_dump(mode="json"),
                admin_dataset.model_dump(mode="json"),
            ],
            "relations": [relation_dataset.model_dump(mode="json")],
            "crosswalks": [crosswalk_dataset.model_dump(mode="json")],
        },
        "catalogs": {
            "geography": "geography_catalog.parquet",
            "relation": "relation_catalog.parquet",
        },
        "fixture_audit": geography_audit,
    }
    write_json(output / "manifest.json", root_manifest)
    write_checksums(
        output, ["geography_catalog.parquet", "relation_catalog.parquet", "manifest.json"]
    )
    return root_manifest


def verify_fixture_products(output: Path) -> None:
    verify_checksums(output)
    root = read_json(output / "manifest.json")
    geography_catalog = pd.read_parquet(output / root["catalogs"]["geography"])
    relation_catalog = pd.read_parquet(output / root["catalogs"]["relation"])
    if len(geography_catalog) != 2 or len(relation_catalog) != 1:
        raise ValueError("fixture catalogs do not enumerate exactly the built products")

    for row in geography_catalog.itertuples(index=False):
        manifest_path = output / row.manifest_ref
        artifact_path = output / row.artifact_ref
        verify_checksums(manifest_path.parent)
        manifest = validate_manifest(manifest_path)
        frame = gpd.read_parquet(artifact_path)
        if len(frame) != manifest["row_count"]:
            raise ValueError(f"geography row count mismatch: {row.dataset_id}")
        if sha256_file(artifact_path) != manifest["dataset"]["content_sha256"]:
            raise ValueError(f"geography content hash mismatch: {row.dataset_id}")

    relation_row = relation_catalog.iloc[0]
    relation_manifest_path = output / relation_row["manifest_ref"]
    verify_checksums(relation_manifest_path.parent)
    relation_manifest = validate_manifest(relation_manifest_path)
    relation = pd.read_parquet(output / relation_row["artifact_ref"])
    if len(relation) != relation_manifest["row_count"]:
        raise ValueError("relation row count mismatch")
    positive = relation[relation["target_geo_uid"].notna()]
    if not positive["source_geo_uid"].duplicated().any():
        raise ValueError("fixture must retain a many-to-many relation before adjudication")

    crosswalk_dir = output / "crosswalks" / "census-admin-largest-overlap"
    verify_checksums(crosswalk_dir)
    crosswalk_manifest = validate_manifest(crosswalk_dir / "manifest.json")
    crosswalk = pd.read_parquet(crosswalk_dir / "crosswalk.parquet")
    if len(crosswalk) != crosswalk_manifest["row_count"]:
        raise ValueError("crosswalk row count mismatch")
    if crosswalk["source_geo_uid"].duplicated().any():
        raise ValueError("crosswalk must contain one row per released source geography")
    if set(crosswalk["assignment_status"]) != {"matched", "unmatched"}:
        raise ValueError("fixture crosswalk statuses changed unexpectedly")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "product-fixture-v1"
            build_fixture_products(path)
            verify_fixture_products(path)
        return
    build_fixture_products(args.output)
    if args.verify:
        verify_fixture_products(args.output)


if __name__ == "__main__":
    main()
