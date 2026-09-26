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
from shapely import union_all
from shapely.geometry import mapping, shape

from argentina_geography.product_writer import package_version
from argentina_geography.products import (
    read_json,
    sha256_file,
    validate_manifest,
    verify_checksums,
    write_checksums,
    write_json,
)
from argentina_geography.sources.indec_eph_2010 import verify_release as verify_a7_release

EXPECTED_AGGLOMERATE_COUNT = 32
DISPLAY_CRS = "EPSG:4326"
REQUIRED_OUTPUT_FILES = [
    "geography.parquet",
    "geography.geojson",
    "agglomerate_inventory.csv",
    "radio_to_agglomerate.parquet",
    "inventory_audit.json",
    "qa.json",
    "limitations.json",
    "manifest.json",
]
DISPLAY_PROPERTY_FIELDS = (
    "geography_id",
    "geo_uid",
    "native_id",
    "eph_agglomerate_id",
    "display_name",
    "source_name_values",
    "name_variant_count",
    "source_radio_count",
    "geometry_radio_count",
    "missing_geometry_radio_count",
    "cross_province",
)


def _id_set_sha256(values: list[str]) -> str:
    payload = "\n".join(sorted(values)) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _relation_sha256(frame: pd.DataFrame) -> str:
    pairs = frame[["radio_2010_id", "eph_agglomerate_id"]].sort_values(
        ["radio_2010_id", "eph_agglomerate_id"], ignore_index=True
    )
    payload = "\n".join(
        f"{row.radio_2010_id}\t{row.eph_agglomerate_id}" for row in pairs.itertuples()
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_names(values: pd.Series) -> list[str]:
    names: set[str] = set()
    for value in values.dropna().astype(str):
        names.update(part.strip() for part in value.split("|") if part.strip())
    return sorted(names)


def derive_agglomerates(
    frame: pd.DataFrame,
    geography: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, dict]:
    required = {
        "radio_2010_id",
        "department_2010_id",
        "province_2010_id",
        "eph_agglomerate_id",
        "native_eph_aglome_values",
    }
    missing_frame = sorted(required - set(frame.columns))
    missing_geo = sorted((required - {"native_eph_aglome_values"}) - set(geography.columns))
    if missing_frame:
        raise ValueError(f"A7 frame is missing required fields: {missing_frame}")
    if missing_geo:
        raise ValueError(f"A7 geography is missing required fields: {missing_geo}")
    if geography.crs is None:
        raise ValueError("A7 geography requires an explicit CRS")
    if frame["radio_2010_id"].duplicated().any() or geography["radio_2010_id"].duplicated().any():
        raise ValueError("A7 radio identity must be unique")
    if not frame["radio_2010_id"].astype(str).str.fullmatch(r"[0-9]{9}").all():
        raise ValueError("A7 radio IDs must preserve nine digits")
    if not frame["eph_agglomerate_id"].astype(str).str.fullmatch(r"[0-9]{2}").all():
        raise ValueError("A7 agglomerate IDs must preserve two digits")

    frame_pairs = frame[["radio_2010_id", "eph_agglomerate_id"]].sort_values(
        "radio_2010_id", ignore_index=True
    )
    geo_pairs = geography[["radio_2010_id", "eph_agglomerate_id"]].sort_values(
        "radio_2010_id", ignore_index=True
    )
    if not frame_pairs.equals(geo_pairs):
        raise ValueError("A7 frame/geography disagree on direct radio-to-agglomerate identity")

    geo_by_radio = geography.set_index("radio_2010_id")
    rows: list[dict] = []
    for agglomerate_id, group in frame.groupby("eph_agglomerate_id", sort=True):
        agglomerate_id = str(agglomerate_id)
        radio_ids = group["radio_2010_id"].astype(str).tolist()
        geo_group = geo_by_radio.loc[radio_ids]
        if isinstance(geo_group, pd.Series):
            geo_group = geo_group.to_frame().T

        names = _source_names(group["native_eph_aglome_values"])
        provinces = sorted(group["province_2010_id"].astype(str).unique().tolist())
        departments = sorted(group["department_2010_id"].astype(str).unique().tolist())
        geometries = [geom for geom in geo_group.geometry.tolist() if geom is not None]
        if not geometries:
            raise ValueError(f"agglomerate {agglomerate_id} has no source geometry")
        dissolved = union_all(geometries)
        if dissolved.is_empty or dissolved.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"agglomerate {agglomerate_id} dissolve produced unusable geometry")
        if not dissolved.is_valid:
            raise ValueError(
                f"agglomerate {agglomerate_id} dissolve would require substantive geometry repair"
            )

        rows.append(
            {
                "geo_uid": f"indec:eph:census2010:agglomerate:{agglomerate_id}",
                "native_id": agglomerate_id,
                "geography_id": agglomerate_id,
                "eph_agglomerate_id": agglomerate_id,
                "display_name": " / ".join(names) if names else agglomerate_id,
                "source_name_values": "|".join(names),
                "name_variant_count": len(names),
                "province_2010_ids": "|".join(provinces),
                "department_2010_ids": "|".join(departments),
                "source_radio_count": len(radio_ids),
                "geometry_radio_count": len(geometries),
                "missing_geometry_radio_count": len(radio_ids) - len(geometries),
                "cross_province": len(provinces) > 1,
                "cross_department": len(departments) > 1,
                "geometry_valid": True,
                "geometry": dissolved,
            }
        )

    result = gpd.GeoDataFrame(rows, geometry="geometry", crs=geography.crs).sort_values(
        "geography_id", ignore_index=True
    )
    if len(result) != EXPECTED_AGGLOMERATE_COUNT:
        raise ValueError(
            f"expected {EXPECTED_AGGLOMERATE_COUNT} native A7 agglomerate codes, found {len(result)}"
        )
    if result["geography_id"].duplicated().any():
        raise ValueError("agglomerate geography IDs must be unique")
    if not result["geography_id"].str.fullmatch(r"[0-9]{2}").all():
        raise ValueError("agglomerate geography IDs must preserve two digits")
    if result.geometry.isna().any() or result.geometry.is_empty.any() or (~result.geometry.is_valid).any():
        raise ValueError("agglomerate release contains unusable geometry")

    relation = frame[
        [
            "radio_2010_id",
            "department_2010_id",
            "province_2010_id",
            "eph_agglomerate_id",
            "native_eph_aglome_values",
        ]
    ].copy()
    relation = relation.sort_values("radio_2010_id", ignore_index=True)
    audit = {
        "stage_decision": "PASS",
        "native_agglomerate_code_count": len(result),
        "radio_count": len(relation),
        "mapped_radio_count": len(relation),
        "cross_province_agglomerate_count": int(result["cross_province"].sum()),
        "cross_province_agglomerate_ids": result.loc[
            result["cross_province"], "eph_agglomerate_id"
        ].tolist(),
        "cross_department_agglomerate_count": int(result["cross_department"].sum()),
        "source_missing_geometry_radio_count": int(result["missing_geometry_radio_count"].sum()),
        "agglomerates_with_source_name_variants": result.loc[
            result["name_variant_count"] > 1, "eph_agglomerate_id"
        ].tolist(),
        "crs": result.crs.to_string(),
        "geometry_types": sorted(result.geom_type.unique().tolist()),
        "invalid_geometry_count": int((~result.geometry.is_valid).sum()),
    }
    return result, relation, audit


def _write_display_geojson(frame: gpd.GeoDataFrame, path: Path) -> int:
    display = frame.to_crs(DISPLAY_CRS)
    invalid = ~display.geometry.is_valid
    repair_count = int(invalid.sum())
    if repair_count:
        geometry_name = display.geometry.name
        display.loc[invalid, geometry_name] = display.loc[invalid].geometry.make_valid()
    if display.geometry.isna().any() or display.geometry.is_empty.any() or (~display.geometry.is_valid).any():
        raise ValueError("agglomerate display reprojection produced unusable geometry")
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
    return repair_count


def materialize_from_parent(parent_release: Path, output: Path) -> dict:
    verify_a7_release(parent_release)
    parent_manifest = read_json(parent_release / "manifest.json")
    parent_dataset = parent_manifest["dataset"]
    if parent_dataset["dataset_id"] != "arggeo.indec.eph.census2010.radio_frame":
        raise ValueError("agglomerate product requires the exact official A7 EPH radio frame")

    frame = pd.read_parquet(parent_release / parent_manifest["artifacts"]["frame"])
    geography = gpd.read_parquet(parent_release / parent_manifest["artifacts"]["geography"])
    agglomerates, relation, audit = derive_agglomerates(frame, geography)
    relation_sha = _relation_sha256(relation)
    parent_relation_sha = read_json(
        parent_release / parent_manifest["artifacts"]["source_metadata"]
    )["expected_radio_to_agglomerate_relation_sha256"]
    if relation_sha != parent_relation_sha:
        raise ValueError("derived direct mapping differs from A7 pinned relation")

    output.mkdir(parents=True, exist_ok=True)
    geography_path = output / "geography.parquet"
    agglomerates.to_parquet(geography_path, index=False)
    geography_sha = sha256_file(geography_path)
    display_path = output / "geography.geojson"
    display_repair_count = _write_display_geojson(agglomerates, display_path)
    display_sha = sha256_file(display_path)
    relation.to_parquet(output / "radio_to_agglomerate.parquet", index=False)

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
            "The exact A7 source contains 32 native eph_codagl identities. "
            "This derived product preserves every native identity and does not merge, drop, "
            "or reinterpret a code merely to match the separate public phrase '31 aglomerados urbanos'."
        ),
    }

    release_version = f"derived-{parent_dataset['version']}"
    geography_spec = GeographySpec(
        provider="indec",
        version=parent_dataset["version"],
        scheme="eph-derived",
        level="agglomerate",
    )
    dataset = DatasetRef(
        dataset_id="arggeo.indec.eph.census2010.agglomerate-footprint",
        version=release_version,
        schema_version="arggeo.geography/v1",
        layer=DataLayer.GOLD,
        authority=AuthorityLevel.L1_NORMALIZED,
        grain=GrainSpec(keys=("eph_agglomerate_id",)),
        geography=geography_spec,
        content_sha256=geography_sha,
    )
    parent_manifest_sha = sha256_file(parent_release / "manifest.json")
    now = datetime.now(UTC)
    qa_result = QAResult(
        check_id="indec_eph_agglomerate_footprint_contract",
        state="GREEN",
        message=(
            "Agglomerate membership is inherited only from A7 direct official radio identity; "
            "geometry is a dissolve for display/aggregation, never a membership inference."
        ),
        metrics={
            "agglomerate_count": len(agglomerates),
            "radio_count": len(relation),
            "relation_sha256": relation_sha,
            "cross_province_agglomerate_count": audit["cross_province_agglomerate_count"],
        },
    )
    run = RunManifest(
        run_id=f"indec-eph-agglomerate:{geography_sha[:16]}",
        package="argentina-geography",
        package_version=package_version(),
        started_at=now,
        finished_at=now,
        inputs=(SourceSnapshotRef.model_validate(parent_manifest["source_snapshot"]),),
        parameters={
            "derivation": (
                "group exact A7 radio membership by eph_agglomerate_id and union only those "
                "already-assigned official radio geometries"
            ),
            "membership_inference": False,
            "spatial_overlay_for_membership": False,
            "centroid_or_contains_for_membership": False,
            "parent_dataset_id": parent_dataset["dataset_id"],
            "parent_release_version": parent_dataset["version"],
            "parent_manifest_sha256": parent_manifest_sha,
            "parent_direct_mapping_sha256": parent_relation_sha,
            "expected_agglomerate_count": EXPECTED_AGGLOMERATE_COUNT,
        },
        outputs=(dataset,),
        qa=(qa_result,),
    )

    limitations = {
        "dataset_id": dataset.dataset_id,
        "release_version": release_version,
        "items": [
            "Agglomerate identity is an EPH survey geography and has no administrative parent.",
            "Cross-province and cross-department agglomerates are preserved rather than forced into an administrative hierarchy.",
            "The source frame is Census-2010-based and must not be treated as a timeless EPH frame claim.",
            "Three A7 radios have source-missing geometry; they remain in the direct relation and are counted in each agglomerate audit, but cannot contribute polygon area.",
            "Native source spelling variants are preserved in source_name_values; display_name is a deterministic presentation string and is not identity-bearing.",
            "No poverty-region semantics are included in argentina-geography.",
        ],
    }
    write_json(output / "inventory_audit.json", inventory_audit)
    write_json(output / "qa.json", audit)
    write_json(output / "limitations.json", limitations)

    manifest = {
        "product_type": "survey_geography",
        "authority_status": "derived_from_official_direct_membership",
        "stage_decision": "PASS",
        "dataset": dataset.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "row_count": len(agglomerates),
        "parent_release": {
            "dataset_id": parent_dataset["dataset_id"],
            "release_version": parent_dataset["version"],
            "manifest_sha256": parent_manifest_sha,
            "direct_mapping_sha256": parent_relation_sha,
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
            "content_sha256": sha256_file(output / "radio_to_agglomerate.parquet"),
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
            "geometry_transform": "union A7 radios by already-declared eph_agglomerate_id, then display-only reprojection",
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


def verify_release(output: Path) -> None:
    verify_checksums(output)
    manifest = validate_manifest(output / "manifest.json")
    if manifest["dataset"]["dataset_id"] != "arggeo.indec.eph.census2010.agglomerate-footprint":
        raise ValueError("unexpected EPH agglomerate footprint dataset_id")
    frame = gpd.read_parquet(output / manifest["artifacts"]["geography"])
    relation = pd.read_parquet(output / manifest["artifacts"]["radio_to_agglomerate"])
    if len(frame) != EXPECTED_AGGLOMERATE_COUNT or len(frame) != manifest["row_count"]:
        raise ValueError("EPH agglomerate release must contain exactly 32 native codes")
    if frame["geography_id"].duplicated().any():
        raise ValueError("EPH agglomerate geography_id must be unique")
    if not frame["geography_id"].astype(str).str.fullmatch(r"[0-9]{2}").all():
        raise ValueError("EPH agglomerate geography_id must preserve two digits")
    if not frame["geography_id"].eq(frame["eph_agglomerate_id"]).all():
        raise ValueError("EPH agglomerate geography_id must equal eph_agglomerate_id")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any() or (~frame.geometry.is_valid).any():
        raise ValueError("EPH agglomerate release contains unusable geometry")
    if relation["radio_2010_id"].duplicated().any():
        raise ValueError("EPH radio-to-agglomerate relation must be functional")
    if not relation["radio_2010_id"].astype(str).str.fullmatch(r"[0-9]{9}").all():
        raise ValueError("EPH relation radio IDs must preserve nine digits")
    if not relation["eph_agglomerate_id"].astype(str).str.fullmatch(r"[0-9]{2}").all():
        raise ValueError("EPH relation agglomerate IDs must preserve two digits")
    if set(relation["eph_agglomerate_id"]) != set(frame["eph_agglomerate_id"]):
        raise ValueError("EPH relation/geography agglomerate inventories differ")
    if _relation_sha256(relation) != manifest["membership"]["relation_sha256"]:
        raise ValueError("EPH direct membership relation hash mismatch")
    if _id_set_sha256(frame["eph_agglomerate_id"].astype(str).tolist()) != manifest[
        "agglomerate_identity"
    ]["id_set_sha256"]:
        raise ValueError("EPH agglomerate ID inventory hash mismatch")
    if manifest["agglomerate_identity"].get("administrative_parent") is not None:
        raise ValueError("EPH agglomerate must not declare an administrative parent")
    if manifest["membership"].get("spatial_inference") is not False:
        raise ValueError("EPH agglomerate membership must remain non-spatial/direct")
    display_path = output / manifest["artifacts"]["display_geojson"]
    display = json.loads(display_path.read_text(encoding="utf-8"))
    features = display.get("features", [])
    if display.get("type") != "FeatureCollection" or len(features) != EXPECTED_AGGLOMERATE_COUNT:
        raise ValueError("EPH agglomerate display GeoJSON must contain exactly 32 features")
    if {feature.get("id") for feature in features} != set(frame["geography_id"]):
        raise ValueError("EPH agglomerate display ID set mismatch")
    for feature in features:
        properties = feature.get("properties", {})
        if set(properties) != set(DISPLAY_PROPERTY_FIELDS):
            raise ValueError("EPH agglomerate display has unexpected properties")
        geometry = shape(feature.get("geometry"))
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError("EPH agglomerate display contains unusable geometry")
    if sha256_file(display_path) != manifest["display_derivative"]["content_sha256"]:
        raise ValueError("EPH agglomerate display content hash mismatch")
    if manifest["display_derivative"].get("poverty_values_embedded") is not False:
        raise ValueError("EPH agglomerate geography must remain poverty-free")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize or verify first-class INDEC EPH agglomerate geography."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("materialize")
    build.add_argument("--parent-release", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--release", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "materialize":
        materialize_from_parent(args.parent_release, args.output)
    else:
        verify_release(args.release)


if __name__ == "__main__":
    main()
