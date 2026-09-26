from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
from empirical_contracts import (
    AuthorityLevel,
    DataLayer,
    DatasetRef,
    GeographySpec,
    GrainSpec,
    QAResult,
    RunManifest,
    SourceSnapshotRef,
)

from argentina_geography.derived.indec_eph_agglomerate import (
    DISPLAY_CRS,
    DISPLAY_PROPERTY_FIELDS,
    EXPECTED_AGGLOMERATE_COUNT,
    REQUIRED_OUTPUT_FILES,
    _id_set_sha256,
    _relation_sha256,
    _write_display_geojson,
    derive_agglomerates,
    verify_release,
)
from argentina_geography.product_writer import package_version
from argentina_geography.products import (
    read_json,
    sha256_file,
    validate_manifest,
    write_checksums,
    write_json,
)
from argentina_geography.sources import indec_eph_2010 as a7


A6_DATASET_ID = "arggeo.indec.census.2010.radio"
G1_DATASET_ID = "arggeo.indec.eph.census2010.agglomerate-footprint"


def _verify_source_equivalent_a6(parent_release: Path, config: dict) -> dict:
    parent_release = parent_release.resolve()
    manifest = validate_manifest(parent_release / "manifest.json")
    expected = config["parent_census_2010"]
    dataset = manifest["dataset"]
    if (
        dataset["dataset_id"] != expected["dataset_id"]
        or dataset["version"] != expected["release_version"]
    ):
        raise ValueError("A6 parent dataset/release identity differs from pinned A7 basis")

    source_snapshot = manifest.get("source_snapshot")
    if not isinstance(source_snapshot, dict):
        run_inputs = (manifest.get("run") or {}).get("inputs") or []
        source_snapshot = run_inputs[0] if len(run_inputs) == 1 else None
    if not isinstance(source_snapshot, dict):
        raise ValueError("A6 parent lacks source snapshot identity")
    snapshot_id = str(source_snapshot.get("snapshot_id", ""))
    expected_snapshot = f"sha256:{expected['source_snapshot_sha256']}"
    if snapshot_id != expected_snapshot:
        raise ValueError(
            f"A6 raw snapshot differs from pinned A7 basis: {snapshot_id} != {expected_snapshot}"
        )

    geography_name = (manifest.get("artifacts") or {}).get("geography")
    if not isinstance(geography_name, str):
        raise ValueError("A6 parent lacks geography artifact")
    geography_path = parent_release / geography_name
    parent_ids = set(
        pd.read_parquet(geography_path, columns=["radio_2010_id"])["radio_2010_id"]
        .astype(str)
    )
    if len(parent_ids) != 52406:
        raise ValueError(f"A6 parent must contain 52,406 radio IDs, got {len(parent_ids)}")
    if not all(len(value) == 9 and value.isdigit() for value in parent_ids):
        raise ValueError("A6 parent radio IDs are not zero-preserving 9-digit identities")

    return {
        "dataset_id": dataset["dataset_id"],
        "release_version": dataset["version"],
        "raw_source_snapshot_sha256": expected["source_snapshot_sha256"],
        "normalized_geography_sha256_observed": dataset["content_sha256"],
        "normalized_geography_sha256_historical": expected["normalized_geography_sha256"],
        "normalized_binary_identity_required": False,
        "radio_count": len(parent_ids),
        "radio_ids": parent_ids,
        "manifest_sha256": sha256_file(parent_release / "manifest.json"),
    }


def _build_exact_a7_tables(
    source_dir: Path,
    config: dict,
    parent_ids: set[str],
) -> tuple[pd.DataFrame, gpd.GeoDataFrame, dict, list[dict], str]:
    source_records, snapshot_sha = a7._acquire_exact_sources(source_dir, config)
    if snapshot_sha != config["expected_snapshot_sha256"]:
        raise ValueError("A7 exact-source snapshot mismatch")

    shapefile_path = source_dir / config["radio_sources"]["shapefile"]["file_name"]
    geojson_path = source_dir / config["radio_sources"]["geojson"]["file_name"]
    shapefile, _ = a7._read_vector(shapefile_path, "shapefile")
    geojson, _ = a7._read_vector(geojson_path, "geojson")
    components = a7._normalized_components(shapefile)
    geojson_components = a7._normalized_components(geojson)

    relation_sha, relation_pairs = a7._relation_sha(components)
    geojson_relation_sha, _ = a7._relation_sha(geojson_components)
    expected_relation = config["expected_radio_to_agglomerate_relation_sha256"]
    if relation_sha != expected_relation or geojson_relation_sha != expected_relation:
        raise ValueError("A7 vector variants differ from pinned direct radio/agglomerate relation")

    frame, geography, audit = a7._build_frame_and_geography(components)
    if len(components) != 26815 or len(frame) != 26417:
        raise ValueError(
            f"A7 exact-source cardinality drift: components={len(components)} radios={len(frame)}"
        )
    expected_missing = ["020011704", "020011706", "500281605"]
    if audit["missing_geometry_radio_2010_ids"] != expected_missing:
        raise ValueError("A7 exact-source missing-geometry identity drift")
    eph_ids = set(frame["radio_2010_id"].astype(str))
    missing_from_a6 = sorted(eph_ids - parent_ids)
    if missing_from_a6:
        raise ValueError(
            f"A7 radios are not a subset of exact-source A6 identity: {missing_from_a6[:20]}"
        )

    source_audit = {
        "a7_source_snapshot_sha256": snapshot_sha,
        "a7_direct_mapping_sha256": relation_sha,
        "a7_direct_mapping_pair_count": len(relation_pairs),
        "a7_radio_count": len(frame),
        "a7_source_component_count": len(components),
        "a7_missing_geometry_radio_ids": expected_missing,
        "a7_radio_missing_from_a6_count": 0,
        "cross_variant_relation_sha256": geojson_relation_sha,
    }
    return frame, geography, source_audit, source_records, snapshot_sha


def materialize_exact_sources(
    *,
    census_parent_release: Path,
    source_dir: Path,
    output: Path,
    config_path: Path = a7.DEFAULT_CONFIG,
) -> dict:
    config = a7.load_config(config_path)
    a6 = _verify_source_equivalent_a6(census_parent_release, config)
    frame, geography, source_audit, source_records, snapshot_sha = _build_exact_a7_tables(
        source_dir,
        config,
        a6["radio_ids"],
    )

    agglomerates, relation, audit = derive_agglomerates(frame, geography)
    relation_sha = _relation_sha256(relation)
    if relation_sha != config["expected_radio_to_agglomerate_relation_sha256"]:
        raise ValueError("G1 relation differs from pinned A7 direct mapping")

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("G1 output directory must be empty")

    geography_path = output / "geography.parquet"
    agglomerates.to_parquet(geography_path, index=False)
    geography_sha = sha256_file(geography_path)
    display_path = output / "geography.geojson"
    display_repair_count = _write_display_geojson(agglomerates, display_path)
    display_sha = sha256_file(display_path)
    relation_path = output / "radio_to_agglomerate.parquet"
    relation.to_parquet(relation_path, index=False)

    inventory_fields = [
        "eph_agglomerate_id",
        "display_name",
        "source_name_values",
        "name_variant_count",
        "province_2010_ids",
        "department_2010_ids",
        "source_radio_count",
        "geometry_radio_count",
        "missing_geometry_radio_count",
        "cross_province",
        "cross_department",
    ]
    agglomerates[inventory_fields].to_csv(
        output / "agglomerate_inventory.csv", index=False
    )
    ids = agglomerates["eph_agglomerate_id"].astype(str).tolist()
    inventory_audit = {
        "schema_version": "arggeo.eph-agglomerate-inventory-audit/v1",
        "native_code_count": len(ids),
        "native_code_ids": ids,
        "id_set_sha256": _id_set_sha256(ids),
        "source_name_variant_codes": audit["agglomerates_with_source_name_variants"],
        "public_31_vs_native_32_status": "not_collapsed",
        "note": (
            "The exact pinned A7 raw source contains 32 native eph_codagl identities. "
            "Every native identity is preserved."
        ),
    }

    source_snapshot_payload = {
        "source": config["source_id"],
        "release": config["release"],
        "snapshot_id": f"sha256:{snapshot_sha}",
        "origin": config["source_page"],
        "storage_mode": "external_immutable",
        "files": [
            {
                "path": item["file_name"],
                "sha256": item["sha256"],
                "size_bytes": item["size_bytes"],
            }
            for item in source_records
        ],
    }
    source_snapshot = SourceSnapshotRef.model_validate(source_snapshot_payload)
    release_version = f"exact-sources-{snapshot_sha[:12]}"
    geography_spec = GeographySpec(
        provider="indec",
        version="eph-census2010-frame",
        scheme="eph-derived",
        level="agglomerate",
    )
    dataset = DatasetRef(
        dataset_id=G1_DATASET_ID,
        version=release_version,
        schema_version="arggeo.geography/v1",
        layer=DataLayer.GOLD,
        authority=AuthorityLevel.L1_NORMALIZED,
        grain=GrainSpec(keys=("eph_agglomerate_id",)),
        geography=geography_spec,
        content_sha256=geography_sha,
    )
    qa_result = QAResult(
        check_id="indec_eph_agglomerate_exact_source_contract",
        state="GREEN",
        message=(
            "G1 is reconstructed from byte-pinned official A7 sources and an A6 parent "
            "with the exact pinned raw source snapshot; normalized Parquet byte identity "
            "is not used as a scientific identity gate."
        ),
        metrics={
            "agglomerate_count": len(agglomerates),
            "radio_count": len(relation),
            "relation_sha256": relation_sha,
            "a6_radio_count": a6["radio_count"],
            "cross_province_agglomerate_count": audit["cross_province_agglomerate_count"],
        },
    )
    now = datetime.now(UTC)
    run = RunManifest(
        run_id=f"indec-eph-agglomerate-exact:{snapshot_sha[:16]}",
        package="argentina-geography",
        package_version=package_version(),
        started_at=now,
        finished_at=now,
        inputs=(source_snapshot,),
        parameters={
            "derivation": (
                "exact pinned A7 raw source -> direct radio membership -> agglomerate dissolve"
            ),
            "membership_inference": False,
            "spatial_overlay_for_membership": False,
            "centroid_or_contains_for_membership": False,
            "a6_parent_dataset_id": a6["dataset_id"],
            "a6_parent_release_version": a6["release_version"],
            "a6_raw_source_snapshot_sha256": a6["raw_source_snapshot_sha256"],
            "a6_normalized_binary_identity_required": False,
            "a7_source_snapshot_sha256": snapshot_sha,
            "a7_direct_mapping_sha256": relation_sha,
            "expected_agglomerate_count": EXPECTED_AGGLOMERATE_COUNT,
        },
        outputs=(dataset,),
        qa=(qa_result,),
    )

    audit = {
        **audit,
        **source_audit,
        "stage_decision": "PASS",
        "a6_parent_dataset_id": a6["dataset_id"],
        "a6_parent_release_version": a6["release_version"],
        "a6_raw_source_snapshot_sha256": a6["raw_source_snapshot_sha256"],
        "a6_current_normalized_geography_sha256": a6["normalized_geography_sha256_observed"],
        "a6_historical_normalized_geography_sha256": a6["normalized_geography_sha256_historical"],
        "a6_normalized_parquet_byte_identity_required": False,
    }
    limitations = {
        "dataset_id": G1_DATASET_ID,
        "release_version": release_version,
        "items": [
            "Agglomerate identity is an EPH survey geography and has no administrative parent.",
            "Membership is inherited only from the exact byte-pinned official A7 source fields.",
            "The A6 parent is accepted by exact raw source snapshot, release identity, and radio identity coverage; normalized Parquet byte identity is explicitly not treated as scientific identity.",
            "The source frame is Census-2010-based and must not be treated as a timeless EPH frame claim.",
            "Three official A7 radios have no source geometry; they remain in the membership relation and are audited but cannot contribute polygon area.",
            "No poverty-region semantics are included in argentina-geography.",
        ],
    }
    write_json(output / "inventory_audit.json", inventory_audit)
    write_json(output / "qa.json", audit)
    write_json(output / "limitations.json", limitations)

    manifest = {
        "product_type": "survey_geography",
        "authority_status": "derived_from_exact_official_sources",
        "stage_decision": "PASS",
        "dataset": dataset.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "row_count": len(agglomerates),
        "source_snapshot": source_snapshot.model_dump(mode="json"),
        "source_reconstruction": {
            "mode": "exact_raw_sources",
            "a6": {
                key: value
                for key, value in a6.items()
                if key != "radio_ids"
            },
            "a7_source_snapshot_sha256": snapshot_sha,
            "a7_direct_mapping_sha256": relation_sha,
        },
        "agglomerate_identity": {
            "field": "eph_agglomerate_id",
            "geography_level": "eph_agglomerate",
            "regex": "^[0-9]{2}$",
            "feature_count": len(agglomerates),
            "id_set_sha256": inventory_audit["id_set_sha256"],
            "administrative_parent": None,
        },
        "membership": {
            "artifact": "radio_to_agglomerate.parquet",
            "relation": "radio_2010_id -> eph_agglomerate_id",
            "content_sha256": sha256_file(relation_path),
            "relation_sha256": relation_sha,
            "mode": "direct_official_source_relation",
            "spatial_inference": False,
        },
        "display_derivative": {
            "artifact": "geography.geojson",
            "content_sha256": display_sha,
            "crs": DISPLAY_CRS,
            "feature_count": len(agglomerates),
            "feature_id_field": "geography_id",
            "property_fields": list(DISPLAY_PROPERTY_FIELDS),
            "geometry_transform": (
                "union A7 radios by already-declared eph_agglomerate_id, "
                "then display-only reprojection"
            ),
            "geometry_repair_applied": display_repair_count > 0,
            "geometry_repair_count": display_repair_count,
            "poverty_values_embedded": False,
        },
        "artifacts": {
            "geography": "geography.parquet",
            "display_geojson": "geography.geojson",
            "inventory": "agglomerate_inventory.csv",
            "radio_to_agglomerate": "radio_to_agglomerate.parquet",
            "inventory_audit": "inventory_audit.json",
            "qa": "qa.json",
            "limitations": "limitations.json",
        },
    }
    write_json(output / "manifest.json", manifest)
    write_checksums(output, REQUIRED_OUTPUT_FILES)
    verify_release(output)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize G1 EPH agglomerates from exact pinned official sources."
    )
    parser.add_argument("--census-parent-release", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=a7.DEFAULT_CONFIG)
    args = parser.parse_args()
    materialize_exact_sources(
        census_parent_release=args.census_parent_release,
        source_dir=args.source_dir,
        output=args.output,
        config_path=args.config,
    )


if __name__ == "__main__":
    main()
