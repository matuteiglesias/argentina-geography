from __future__ import annotations

import argparse
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

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
    SourceFileRef,
    SourceSnapshotRef,
)

from argentina_geography.product_writer import package_version
from argentina_geography.products import (
    read_json,
    sha256_file,
    validate_manifest,
    verify_checksums,
    write_checksums,
    write_json,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config/sources/ign_administrative_department.json"
REQUIRED_OUTPUT_FILES = [
    "geography.parquet",
    "geography_catalog.parquet",
    "qa.json",
    "source_metadata.json",
    "limitations.json",
    "manifest.json",
]


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    return read_json(path)


def download_source(destination: Path, config: dict) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(
        config["source_url"],
        headers={"User-Agent": "argentina-geography/0.1 research-data-client"},
    )
    with urlopen(request, timeout=300) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)
    if destination.stat().st_size == 0:
        raise ValueError("IGN department archive download returned an empty file")
    return destination


def _identity_text(value: object, *, field: str, width: int) -> str:
    if pd.isna(value):
        raise ValueError(f"{field} must be non-missing")
    text = str(value).strip()
    if not text.isascii() or not text.isdigit() or len(text) != width:
        raise ValueError(f"{field} must contain exactly {width} ASCII digits: {value!r}")
    return text


def _read_source(path: Path, config: dict) -> gpd.GeoDataFrame:
    if path.suffix.lower() == ".zip":
        member = config["archive_member"]
        source = f"/vsizip/{path.resolve()}/{member}"
    else:
        source = str(path)
    return gpd.read_file(source, engine="pyogrio", use_arrow=True)


def _warning(code: str, message: str, **metrics: object) -> dict:
    item = {"code": code, "stage_decision": "PASS_WITH_WARNINGS", "message": message}
    if metrics:
        item["metrics"] = metrics
    return item


def normalize_source(
    frame: gpd.GeoDataFrame,
    config: dict,
    *,
    source_sha256: str,
) -> tuple[gpd.GeoDataFrame, dict]:
    missing_fields = sorted(set(config["required_fields"]) - set(frame.columns))
    if missing_fields:
        raise ValueError(f"IGN department source is missing required fields: {missing_fields}")
    if frame.crs is None:
        raise ValueError("IGN department source requires an explicit CRS")

    result = frame.copy()
    identity_field = config["identity_field"]
    width = int(config["identity_width"])
    result[identity_field] = result[identity_field].map(
        lambda value: _identity_text(value, field=identity_field, width=width)
    )
    if result[identity_field].duplicated().any():
        duplicates = sorted(
            result.loc[result[identity_field].duplicated(False), identity_field].unique()
        )
        raise ValueError(
            f"IGN department native IDs must be unique; duplicates include {duplicates[:10]}"
        )

    secondary_id = config["secondary_source_identifier"]
    if result[secondary_id].isna().any() or result[secondary_id].duplicated().any():
        raise ValueError(f"IGN department {secondary_id} must be non-missing and unique")

    object_field = config["object_field"]
    object_values = set(result[object_field].dropna().astype(str).str.strip().unique())
    if object_values != {config["expected_object_value"]}:
        raise ValueError(
            f"IGN department {object_field} field drifted: expected "
            f"{config['expected_object_value']!r}, found {sorted(object_values)}"
        )
    gna_field = config["gna_field"]
    gna_values = set(result[gna_field].dropna().astype(str).str.strip().unique())
    expected_gna = set(config["expected_gna_values"])
    if gna_values != expected_gna:
        raise ValueError(
            f"IGN department {gna_field} vocabulary drifted: expected {sorted(expected_gna)}, "
            f"found {sorted(gna_values)}"
        )

    missing_geometry = int(result.geometry.isna().sum())
    empty_geometry = int(result.geometry.is_empty.sum())
    areal = result.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    non_areal_geometry = int(
        (result.geometry.notna() & ~result.geometry.is_empty & ~areal).sum()
    )
    if missing_geometry or empty_geometry or non_areal_geometry:
        raise ValueError(
            "IGN department geography has unusable source geometry: "
            f"missing={missing_geometry}, empty={empty_geometry}, "
            f"non_areal={non_areal_geometry}"
        )

    invalid_mask = ~result.geometry.is_valid
    invalid_geometry = int(invalid_mask.sum())
    warnings = []
    if invalid_geometry:
        warnings.append(
            _warning(
                "source_invalid_geometry",
                "Source-invalid IGN polygons are retained without repair and excluded from "
                "the analytical role used by geometric relations.",
                affected_rows=invalid_geometry,
            )
        )

    expected_count = int(config["expected_feature_count"])
    if len(result) != expected_count:
        raise ValueError(
            f"IGN department feature count drifted: expected {expected_count}, found {len(result)}"
        )

    snapshot_token = source_sha256[:12]
    result["native_id"] = result[identity_field]
    result["geo_uid"] = (
        f"ign:administrative:department:{snapshot_token}:" + result["native_id"].astype(str)
    )
    result["source_unit_status"] = "ordinary"
    result["geometry_valid"] = ~invalid_mask
    result["geometry_role"] = "analytical"
    result.loc[invalid_mask, "geometry_role"] = "source_invalid"

    columns = [
        "geo_uid",
        "native_id",
        *config["preserved_native_fields"],
        "source_unit_status",
        "geometry_valid",
        "geometry_role",
        result.geometry.name,
    ]
    result = result[columns].sort_values("geo_uid", ignore_index=True)

    audit = {
        "stage_decision": "PASS_WITH_WARNINGS" if warnings else "PASS",
        "accepted_warning_count": len(warnings),
        "accepted_warnings": warnings,
        "feature_count": len(result),
        "unique_native_id_count": int(result["native_id"].nunique()),
        "unique_secondary_source_id_count": int(result[secondary_id].nunique(dropna=True)),
        "crs": result.crs.to_string(),
        "geometry_types": sorted(result.geom_type.unique().tolist()),
        "missing_identity_count": int(result["native_id"].isna().sum()),
        "duplicate_identity_count": int(result["native_id"].duplicated().sum()),
        "missing_geometry_count": missing_geometry,
        "empty_geometry_count": empty_geometry,
        "invalid_geometry_count": invalid_geometry,
        "non_areal_geometry_count": non_areal_geometry,
        "analytical_geometry_count": int(result["geometry_valid"].sum()),
        "source_invalid_geometry_count": invalid_geometry,
        "gna_values": sorted(gna_values),
        "object_values": sorted(object_values),
        "source_lineage_value_count": int(result["SAG"].nunique(dropna=True)),
        "source_capture_method_value_count": int(result["FDC"].nunique(dropna=True)),
        "source_capture_method_null_count": int(result["FDC"].isna().sum()),
        "bbox": [float(value) for value in result.total_bounds.tolist()],
    }
    return result, audit


def _release_version(config: dict, source_sha256: str) -> str:
    date = config["snapshot_retrieved_at_utc"][:10].replace("-", "")
    return f"snapshot-{date}-{source_sha256[:12]}"


def _verify_source_snapshot(source_path: Path, config: dict) -> tuple[str, int]:
    source_sha256 = sha256_file(source_path)
    source_size = source_path.stat().st_size
    expected_sha = config["expected_source_sha256"]
    expected_size = int(config["expected_source_size_bytes"])
    if source_sha256 != expected_sha:
        raise ValueError(
            f"IGN source snapshot SHA-256 drift: expected {expected_sha}, found {source_sha256}"
        )
    if source_size != expected_size:
        raise ValueError(
            f"IGN source snapshot size drift: expected {expected_size}, found {source_size}"
        )
    return source_sha256, source_size


def materialize_from_source(
    source_path: Path,
    output: Path,
    config_path: Path = DEFAULT_CONFIG,
) -> dict:
    config = load_config(config_path)
    source_sha256, source_size = _verify_source_snapshot(source_path, config)
    frame = _read_source(source_path, config)
    normalized, audit = normalize_source(frame, config, source_sha256=source_sha256)

    output.mkdir(parents=True, exist_ok=True)
    geography_path = output / "geography.parquet"
    normalized.to_parquet(geography_path, index=False)
    content_sha256 = sha256_file(geography_path)
    expected_content = config.get("expected_normalized_content_sha256")
    if expected_content and content_sha256 != expected_content:
        raise ValueError(
            "IGN normalized geography content drift: "
            f"expected {expected_content}, found {content_sha256}"
        )

    release_version = _release_version(config, source_sha256)
    geography_version = f"{config['snapshot_retrieved_at_utc'][:10]}-{source_sha256[:12]}"
    geography = GeographySpec(
        provider="ign",
        version=geography_version,
        scheme="administrative",
        level="department",
    )
    dataset = DatasetRef(
        dataset_id="arggeo.ign.administrative.department",
        version=release_version,
        schema_version="arggeo.geography/v1",
        layer=DataLayer.SILVER,
        authority=AuthorityLevel.L1_NORMALIZED,
        grain=GrainSpec(keys=("geo_uid",)),
        geography=geography,
        content_sha256=content_sha256,
    )
    source_snapshot = SourceSnapshotRef(
        source=config["source_id"],
        release=f"retrieved:{config['snapshot_retrieved_at_utc']}",
        snapshot_id=f"sha256:{source_sha256}",
        origin=config["source_url"],
        storage_mode="external_immutable",
        files=(
            SourceFileRef(
                path=source_path.name,
                sha256=source_sha256,
                size_bytes=source_size,
            ),
        ),
    )
    qa_state = "YELLOW" if audit["stage_decision"] == "PASS_WITH_WARNINGS" else "GREEN"
    qa_result = QAResult(
        check_id="ign_department_source_contract",
        state=qa_state,
        message=(
            "Exact IGN department archive is stageable with explicit geometry warnings."
            if qa_state == "YELLOW"
            else "Exact IGN department archive satisfies the normalized geography boundary."
        ),
        metrics={
            "feature_count": audit["feature_count"],
            "unique_native_id_count": audit["unique_native_id_count"],
            "invalid_geometry_count": audit["invalid_geometry_count"],
            "analytical_geometry_count": audit["analytical_geometry_count"],
            "crs": audit["crs"],
        },
    )
    now = datetime.now(UTC)
    run = RunManifest(
        run_id=f"ign-department:{source_sha256[:16]}",
        package="argentina-geography",
        package_version=package_version(),
        started_at=now,
        finished_at=now,
        inputs=(source_snapshot,),
        parameters={
            "source_url": config["source_url"],
            "archive_member": config["archive_member"],
            "snapshot_retrieved_at_utc": config["snapshot_retrieved_at_utc"],
            "identity_field": config["identity_field"],
            "geometry_repair_applied": False,
            "stage_decision": audit["stage_decision"],
            "accepted_qa_warnings": audit["accepted_warnings"],
        },
        outputs=(dataset,),
        qa=(qa_result,),
    )

    source_metadata = {
        **config,
        "acquisition_url": config["source_url"],
        "retrieved_file_sha256": source_sha256,
        "retrieved_file_size_bytes": source_size,
        "received_crs": audit["crs"],
        "normalized_content_sha256": content_sha256,
    }
    limitations = {
        "dataset_id": dataset.dataset_id,
        "release_version": release_version,
        "items": config["known_limitations"],
        "accepted_qa_warnings": audit["accepted_warnings"],
    }
    catalog = pd.DataFrame(
        [
            {
                "geography_id": geography.id,
                "dataset_id": dataset.dataset_id,
                "release_version": dataset.version,
                "schema_version": dataset.schema_version,
                "provider": "ign",
                "scheme": "administrative",
                "vintage": config["source_data_vintage_statement"],
                "level": "department",
                "source_release": f"archive-sha256:{source_sha256}",
                "authority_status": "official",
                "feature_count": audit["feature_count"],
                "analytical_feature_count": audit["analytical_geometry_count"],
                "native_id_fields": config["identity_field"],
                "source_identity_fields": ",".join(
                    [config["identity_field"], config["secondary_source_identifier"]]
                ),
                "geometry_types": ",".join(audit["geometry_types"]),
                "storage_crs": audit["crs"],
                "coverage_status": "source_archive_as_retrieved",
                "qa_state": qa_state,
                "stage_decision": audit["stage_decision"],
                "artifact_ref": "geography.parquet",
                "manifest_ref": "manifest.json",
                "distribution_mode": config["distribution_mode"],
            }
        ]
    )
    catalog.to_parquet(output / "geography_catalog.parquet", index=False)
    write_json(output / "qa.json", audit)
    write_json(output / "source_metadata.json", source_metadata)
    write_json(output / "limitations.json", limitations)
    manifest = {
        "product_type": "geography",
        "authority_status": "official",
        "distribution_mode": config["distribution_mode"],
        "stage_decision": audit["stage_decision"],
        "dataset": dataset.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "row_count": len(normalized),
        "analytical_row_count": audit["analytical_geometry_count"],
        "source_snapshot": source_snapshot.model_dump(mode="json"),
        "artifacts": {
            "geography": "geography.parquet",
            "catalog": "geography_catalog.parquet",
            "qa": "qa.json",
            "source_metadata": "source_metadata.json",
            "limitations": "limitations.json",
        },
    }
    write_json(output / "manifest.json", manifest)
    write_checksums(output, REQUIRED_OUTPUT_FILES)
    return manifest


def acquire_and_materialize(
    output: Path,
    *,
    source: Path | None = None,
    config_path: Path = DEFAULT_CONFIG,
) -> dict:
    config = load_config(config_path)
    if source is not None:
        return materialize_from_source(source, output, config_path)
    with tempfile.TemporaryDirectory(prefix="arggeo-ign-department-") as temporary:
        source_path = Path(temporary) / "ign_departamento.zip"
        download_source(source_path, config)
        return materialize_from_source(source_path, output, config_path)


def verify_release(output: Path) -> None:
    verify_checksums(output)
    manifest = validate_manifest(output / "manifest.json")
    dataset = manifest["dataset"]
    frame = gpd.read_parquet(output / manifest["artifacts"]["geography"])
    if dataset["dataset_id"] != "arggeo.ign.administrative.department":
        raise ValueError("IGN department release has unexpected dataset_id")
    if len(frame) != manifest["row_count"]:
        raise ValueError("IGN department release row count does not match manifest")
    if sha256_file(output / manifest["artifacts"]["geography"]) != dataset["content_sha256"]:
        raise ValueError("IGN department geography content hash mismatch")
    if frame["geo_uid"].isna().any() or frame["geo_uid"].duplicated().any():
        raise ValueError("IGN department geo_uid must be non-missing and unique")
    if frame["native_id"].isna().any() or frame["native_id"].duplicated().any():
        raise ValueError("IGN department native_id must be non-missing and unique")
    if frame["native_id"].ne(frame["IN1"]).any():
        raise ValueError("IGN department native_id must preserve source IN1")
    if frame["OBJECTID"].isna().any() or frame["OBJECTID"].duplicated().any():
        raise ValueError("IGN department source OBJECTID must be non-missing and unique")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError("IGN department release contains missing or empty geometry")
    non_areal = ~frame.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if non_areal.any():
        raise ValueError("IGN department release contains non-areal geometry")
    analytical = frame["geometry_role"].eq("analytical")
    source_invalid = frame["geometry_role"].eq("source_invalid")
    if (~(analytical | source_invalid)).any():
        raise ValueError("IGN department release has unsupported geometry_role")
    if (~frame.loc[analytical].geometry.is_valid).any():
        raise ValueError("IGN analytical rows must contain valid geometry")
    if frame.loc[source_invalid].geometry.is_valid.any():
        raise ValueError("IGN source_invalid rows must correspond to invalid geometry")
    if frame.loc[analytical, "geometry_valid"].ne(True).any():
        raise ValueError("IGN analytical geometry_valid flags are inconsistent")
    if frame.loc[source_invalid, "geometry_valid"].ne(False).any():
        raise ValueError("IGN source-invalid geometry_valid flags are inconsistent")
    catalog = pd.read_parquet(output / manifest["artifacts"]["catalog"])
    if len(catalog) != 1 or catalog.iloc[0]["dataset_id"] != dataset["dataset_id"]:
        raise ValueError("IGN department catalog does not identify the materialized release")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize or verify the exact IGN department archive Geography Release."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--output", type=Path, required=True)
    materialize.add_argument("--source", type=Path)
    materialize.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--release", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "materialize":
        acquire_and_materialize(
            args.output,
            source=args.source,
            config_path=args.config,
        )
        verify_release(args.output)
    else:
        verify_release(args.release)


if __name__ == "__main__":
    main()
