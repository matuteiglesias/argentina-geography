from __future__ import annotations

import argparse
import hashlib
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
from shapely.geometry import mapping, shape

from argentina_geography.electoral.hierarchy import _department_footprints
from argentina_geography.product_writer import package_version
from argentina_geography.products import (
    read_json,
    sha256_file,
    validate_manifest,
    verify_checksums,
    write_checksums,
    write_json,
)
from argentina_geography.sources.indec_2010_radio import verify_release as verify_radio_release

EXPECTED_DEPARTMENT_COUNT = 525
EXPECTED_PROVINCE_COUNT = 24
DISPLAY_CRS = "EPSG:4326"
REQUIRED_OUTPUT_FILES = [
    "geography.parquet",
    "geography.geojson",
    "geography_catalog.parquet",
    "qa.json",
    "limitations.json",
    "manifest.json",
]
DISPLAY_PROPERTY_FIELDS = (
    "geography_id",
    "geo_uid",
    "native_id",
    "department_2010_id",
    "province_2010_id",
)


def _id_set_sha256(values: list[str]) -> str:
    payload = "\n".join(sorted(values)) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def derive_department_footprints(census: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Derive exact Census-2010 department footprints from governed radio geometry."""
    required = {"radio_2010_id", "department_2010_id", "province_2010_id", "geometry"}
    missing = sorted(required - set(census.columns))
    if missing:
        raise ValueError(f"Census radio parent is missing required fields: {missing}")
    if census.crs is None:
        raise ValueError("Census radio parent requires an explicit CRS")
    if census["radio_2010_id"].duplicated().any():
        raise ValueError("Census radio parent must contain unique radio_2010_id")
    if not census["radio_2010_id"].astype(str).str.fullmatch(r"[0-9]{9}").all():
        raise ValueError("Census radio parent IDs must be zero-preserving 9-digit strings")
    if not census["department_2010_id"].astype(str).str.fullmatch(r"[0-9]{5}").all():
        raise ValueError("Census department IDs must be zero-preserving 5-digit strings")
    if not census["department_2010_id"].eq(census["radio_2010_id"].str[:5]).all():
        raise ValueError("Census department identity disagrees with radio identity")
    if not census["province_2010_id"].eq(census["radio_2010_id"].str[:2]).all():
        raise ValueError("Census province identity disagrees with radio identity")

    derived = _department_footprints(census).copy()
    if derived["department_2010_id"].duplicated().any():
        raise ValueError("derived department IDs must be unique")
    if not derived["department_2010_id"].str.fullmatch(r"[0-9]{5}").all():
        raise ValueError("derived department IDs must preserve five digits")
    if not derived["province_2010_id"].str.fullmatch(r"[0-9]{2}").all():
        raise ValueError("derived province IDs must preserve two digits")
    if not derived["department_2010_id"].str[:2].eq(derived["province_2010_id"]).all():
        raise ValueError("derived department prefix disagrees with province identity")
    if not derived["footprint_status"].eq("analytical").all():
        bad = derived.loc[
            ~derived["footprint_status"].eq("analytical"),
            ["department_2010_id", "footprint_status"],
        ].to_dict(orient="records")
        raise ValueError(f"department dissolve produced non-analytical geometry: {bad[:20]}")

    derived["geo_uid"] = derived["department_footprint_uid"]
    derived["native_id"] = derived["department_2010_id"]
    derived["geography_id"] = derived["department_2010_id"]
    derived["geometry_valid"] = derived.geometry.is_valid
    if not derived["geometry_valid"].all():
        raise ValueError("derived department release contains invalid geometry")

    columns = [
        "geo_uid",
        "native_id",
        "geography_id",
        "department_2010_id",
        "province_2010_id",
        "source_radio_count",
        "footprint_status",
        "geometry_valid",
        derived.geometry.name,
    ]
    return derived[columns].sort_values("geography_id", ignore_index=True)


def _write_display_geojson(frame: gpd.GeoDataFrame, path: Path) -> None:
    display = frame.to_crs(DISPLAY_CRS)
    features = []
    for _, row in display.sort_values("geography_id").iterrows():
        properties = {field: row[field] for field in DISPLAY_PROPERTY_FIELDS}
        features.append(
            {
                "type": "Feature",
                "id": row["geography_id"],
                "properties": properties,
                "geometry": mapping(row.geometry),
            }
        )
    path.write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": features},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def materialize_from_parent(parent_release: Path, output: Path) -> dict:
    verify_radio_release(parent_release)
    parent_manifest = read_json(parent_release / "manifest.json")
    parent_dataset = parent_manifest["dataset"]
    if parent_dataset["dataset_id"] != "arggeo.indec.census.2010.radio":
        raise ValueError("department footprint parent must be official INDEC Census 2010 radio")
    census = gpd.read_parquet(
        parent_release / parent_manifest["artifacts"]["geography"]
    )
    departments = derive_department_footprints(census)

    if len(departments) != EXPECTED_DEPARTMENT_COUNT:
        raise ValueError(
            f"expected {EXPECTED_DEPARTMENT_COUNT} Census-2010 departments, found {len(departments)}"
        )
    if departments["province_2010_id"].nunique() != EXPECTED_PROVINCE_COUNT:
        raise ValueError(
            f"expected {EXPECTED_PROVINCE_COUNT} province IDs in department parent"
        )

    ids = departments["geography_id"].astype(str).tolist()
    ids_sha256 = _id_set_sha256(ids)
    parent_manifest_sha256 = sha256_file(parent_release / "manifest.json")

    output.mkdir(parents=True, exist_ok=True)
    geography_path = output / "geography.parquet"
    departments.to_parquet(geography_path, index=False)
    content_sha256 = sha256_file(geography_path)
    display_path = output / "geography.geojson"
    _write_display_geojson(departments, display_path)
    display_sha256 = sha256_file(display_path)

    release_version = f"derived-{parent_dataset['version']}"
    geography = GeographySpec(
        provider="indec",
        version=parent_dataset["version"],
        scheme="census-derived",
        level="department",
    )
    dataset = DatasetRef(
        dataset_id="arggeo.indec.census.2010.department-footprint",
        version=release_version,
        schema_version="arggeo.geography/v1",
        layer=DataLayer.GOLD,
        authority=AuthorityLevel.L1_NORMALIZED,
        grain=GrainSpec(keys=("department_2010_id",)),
        geography=geography,
        content_sha256=content_sha256,
    )
    qa = {
        "stage_decision": "PASS",
        "feature_count": len(departments),
        "unique_department_count": int(departments["department_2010_id"].nunique()),
        "province_count": int(departments["province_2010_id"].nunique()),
        "department_id_set_sha256": ids_sha256,
        "department_id_prefix_consistency": bool(
            departments["department_2010_id"].str[:2].eq(
                departments["province_2010_id"]
            ).all()
        ),
        "source_radio_count": int(departments["source_radio_count"].sum()),
        "min_source_radios_per_department": int(departments["source_radio_count"].min()),
        "max_source_radios_per_department": int(departments["source_radio_count"].max()),
        "crs": departments.crs.to_string(),
        "geometry_types": sorted(departments.geom_type.unique().tolist()),
        "missing_geometry_count": int(departments.geometry.isna().sum()),
        "empty_geometry_count": int(departments.geometry.is_empty.sum()),
        "invalid_geometry_count": int((~departments.geometry.is_valid).sum()),
        "bbox": [float(value) for value in departments.total_bounds.tolist()],
    }
    qa_result = QAResult(
        check_id="indec_2010_department_footprint_contract",
        state="GREEN",
        message=(
            "Derived Census-2010 department footprints preserve the exact governed "
            "five-digit identity and analytical geometry."
        ),
        metrics={
            "feature_count": qa["feature_count"],
            "province_count": qa["province_count"],
            "department_id_set_sha256": qa["department_id_set_sha256"],
            "source_radio_count": qa["source_radio_count"],
        },
    )
    now = datetime.now(UTC)
    source_snapshot = SourceSnapshotRef.model_validate(parent_manifest["source_snapshot"])
    run = RunManifest(
        run_id=f"indec-2010-department:{content_sha256[:16]}",
        package="argentina-geography",
        package_version=package_version(),
        started_at=now,
        finished_at=now,
        inputs=(source_snapshot,),
        parameters={
            "derivation": "union official Census-2010 radio geometry by department_2010_id",
            "parent_dataset_id": parent_dataset["dataset_id"],
            "parent_release_version": parent_dataset["version"],
            "parent_content_sha256": parent_dataset["content_sha256"],
            "parent_manifest_sha256": parent_manifest_sha256,
            "geometry_repair_applied": False,
            "geometry_clip_applied": False,
            "expected_department_count": EXPECTED_DEPARTMENT_COUNT,
        },
        outputs=(dataset,),
        qa=(qa_result,),
    )

    limitations = {
        "dataset_id": dataset.dataset_id,
        "release_version": release_version,
        "items": [
            (
                "This is a derived Census-2010 statistical footprint produced by unioning "
                "the exact official radio parent. It is not relabeled as an official "
                "general-purpose administrative boundary."
            ),
            "No geometry repair, buffering, snapping, clipping or poverty-data decoration is applied.",
            "Display names are intentionally not identity-bearing in this release.",
        ],
    }
    catalog = pd.DataFrame(
        [
            {
                "geography_id": geography.id,
                "dataset_id": dataset.dataset_id,
                "release_version": dataset.version,
                "schema_version": dataset.schema_version,
                "provider": "indec",
                "scheme": "census-derived",
                "vintage": "2010",
                "level": "department",
                "authority_status": "derived_geometric_fact",
                "feature_count": len(departments),
                "native_id_fields": "department_2010_id",
                "display_identity_field": "geography_id",
                "geometry_types": ",".join(qa["geometry_types"]),
                "storage_crs": qa["crs"],
                "coverage_status": "exact_official_radio_parent",
                "artifact_ref": "geography.parquet",
                "display_artifact_ref": "geography.geojson",
                "manifest_ref": "manifest.json",
            }
        ]
    )
    catalog.to_parquet(output / "geography_catalog.parquet", index=False)
    write_json(output / "qa.json", qa)
    write_json(output / "limitations.json", limitations)
    manifest = {
        "product_type": "geography",
        "authority_status": "derived_geometric_fact",
        "stage_decision": "PASS",
        "dataset": dataset.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "row_count": len(departments),
        "parent_release": {
            "dataset_id": parent_dataset["dataset_id"],
            "release_version": parent_dataset["version"],
            "content_sha256": parent_dataset["content_sha256"],
            "manifest_sha256": parent_manifest_sha256,
        },
        "department_identity": {
            "field": "department_2010_id",
            "regex": "^[0-9]{5}$",
            "feature_count": len(departments),
            "id_set_sha256": ids_sha256,
            "province_field": "province_2010_id",
            "province_count": qa["province_count"],
            "prefix_rule": "department_2010_id[:2] == province_2010_id",
        },
        "display_derivative": {
            "artifact": "geography.geojson",
            "content_sha256": display_sha256,
            "crs": DISPLAY_CRS,
            "feature_count": len(departments),
            "feature_id_field": "geography_id",
            "property_fields": list(DISPLAY_PROPERTY_FIELDS),
            "geometry_transform": "department union in source CRS, then display-only reprojection to EPSG:4326",
            "geometry_repair_applied": False,
            "geometry_clip_applied": False,
            "poverty_values_embedded": False,
        },
        "artifacts": {
            "geography": "geography.parquet",
            "display_geojson": "geography.geojson",
            "catalog": "geography_catalog.parquet",
            "qa": "qa.json",
            "limitations": "limitations.json",
        },
    }
    write_json(output / "manifest.json", manifest)
    write_checksums(output, REQUIRED_OUTPUT_FILES)
    verify_release(output)
    return manifest


def verify_release(output: Path) -> None:
    verify_checksums(output)
    manifest = validate_manifest(output / "manifest.json")
    dataset = manifest["dataset"]
    if dataset["dataset_id"] != "arggeo.indec.census.2010.department-footprint":
        raise ValueError("unexpected Census-2010 department footprint dataset_id")
    frame = gpd.read_parquet(output / manifest["artifacts"]["geography"])
    if len(frame) != EXPECTED_DEPARTMENT_COUNT or len(frame) != manifest["row_count"]:
        raise ValueError("department footprint release must contain exactly 525 rows")
    if frame["geography_id"].duplicated().any():
        raise ValueError("department footprint geography_id must be unique")
    if not frame["geography_id"].astype(str).str.fullmatch(r"[0-9]{5}").all():
        raise ValueError("department footprint geography_id must preserve five digits")
    if not frame["geography_id"].eq(frame["department_2010_id"]).all():
        raise ValueError("department footprint geography_id must equal department_2010_id")
    if not frame["native_id"].eq(frame["department_2010_id"]).all():
        raise ValueError("department footprint native_id must equal department_2010_id")
    if not frame["department_2010_id"].str[:2].eq(frame["province_2010_id"]).all():
        raise ValueError("department footprint province prefix is inconsistent")
    if frame["province_2010_id"].nunique() != EXPECTED_PROVINCE_COUNT:
        raise ValueError("department footprint release must contain 24 province IDs")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError("department footprint release contains missing or empty geometry")
    if (~frame.geometry.is_valid).any():
        raise ValueError("department footprint release contains invalid geometry")
    ids_sha256 = _id_set_sha256(frame["geography_id"].astype(str).tolist())
    if ids_sha256 != manifest["department_identity"]["id_set_sha256"]:
        raise ValueError("department footprint ID inventory hash mismatch")
    if sha256_file(output / manifest["artifacts"]["geography"]) != dataset["content_sha256"]:
        raise ValueError("department footprint geography content hash mismatch")

    display_path = output / manifest["artifacts"]["display_geojson"]
    display = json.loads(display_path.read_text(encoding="utf-8"))
    features = display.get("features", [])
    if display.get("type") != "FeatureCollection" or len(features) != EXPECTED_DEPARTMENT_COUNT:
        raise ValueError("department display GeoJSON must contain exactly 525 features")
    display_ids = {feature.get("id") for feature in features}
    if display_ids != set(frame["geography_id"].astype(str)):
        raise ValueError("department display GeoJSON ID set mismatch")
    if manifest["display_derivative"].get("crs") != DISPLAY_CRS:
        raise ValueError("department display GeoJSON must declare EPSG:4326")
    for feature in features:
        properties = feature.get("properties", {})
        if set(properties) != set(DISPLAY_PROPERTY_FIELDS):
            raise ValueError("department display GeoJSON has unexpected properties")
        if properties.get("geography_id") != feature.get("id"):
            raise ValueError("department display feature property/id mismatch")
        geometry = shape(feature.get("geometry"))
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError("department display GeoJSON contains unusable geometry")
        minx, miny, maxx, maxy = geometry.bounds
        if not (-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90):
            raise ValueError("department display GeoJSON is not longitude/latitude bounded")
    if sha256_file(display_path) != manifest["display_derivative"]["content_sha256"]:
        raise ValueError("department display GeoJSON content hash mismatch")
    if manifest["display_derivative"].get("poverty_values_embedded") is not False:
        raise ValueError("department display transport must remain poverty-free")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize or verify derived INDEC Census-2010 department footprints."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--parent-release", type=Path, required=True)
    materialize.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--release", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "materialize":
        materialize_from_parent(args.parent_release, args.output)
    else:
        verify_release(args.release)


if __name__ == "__main__":
    main()
