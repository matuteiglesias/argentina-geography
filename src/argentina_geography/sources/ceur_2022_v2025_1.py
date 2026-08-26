from __future__ import annotations

import argparse
import tempfile
import warnings
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
DEFAULT_CONFIG = ROOT / "config/sources/ceur_census_2022_radio_v2025_1.json"
REQUIRED_SOURCE_FIELDS = (
    "COD_2022",
    "PROV",
    "DEPTO",
    "FRACC",
    "RADIO",
    "OBS2022",
    "VIV_TOT_P",
    "POB_TOT_P",
    "REDATAM",
)
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
        config["download_url"],
        headers={"User-Agent": "argentina-geography/0.1 research-data-client"},
    )
    with urlopen(request, timeout=300) as response, destination.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    if destination.stat().st_size == 0:
        raise ValueError("CEUR V2025-1 download returned an empty source file")
    if destination.read_bytes()[:2] != b"PK":
        raise ValueError("CEUR V2025-1 response is not a ZIP archive; source endpoint may have changed")
    return destination


def _read_source(path: Path) -> gpd.GeoDataFrame:
    source = f"zip://{path.resolve()}" if path.suffix.lower() == ".zip" else str(path)
    layers = gpd.list_layers(source)
    if len(layers) != 1:
        records = layers.astype(object).where(layers.notna(), None).to_dict(orient="records")
        raise ValueError(
            "CEUR V2025-1 source must contain exactly one vector layer; "
            f"observed {len(layers)}: {records}"
        )
    return gpd.read_file(
        source,
        layer=layers.iloc[0]["name"],
        engine="pyogrio",
        use_arrow=True,
    )


def _normalize_digits(value: object, width: int, field: str) -> str:
    if pd.isna(value):
        raise ValueError(f"{field} must be non-missing")
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text.isascii() or not text.isdigit() or len(text) > width:
        raise ValueError(f"{field} must contain at most {width} ASCII digits: {value!r}")
    return text.zfill(width)


def _warning(code: str, message: str, **metrics: object) -> dict:
    item = {"code": code, "stage_decision": "PASS_WITH_WARNINGS", "message": message}
    if metrics:
        item["metrics"] = metrics
    return item


def _driver_warning_items(messages: list[str]) -> list[dict]:
    return [
        _warning(
            "source_driver_warning",
            "The source driver emitted a runtime warning while decoding the CEUR snapshot; "
            "the message is preserved for review.",
            driver_message=message,
        )
        for message in sorted(set(messages))
    ]


def normalize_source(
    frame: gpd.GeoDataFrame,
    config: dict,
    *,
    driver_warnings: list[str] | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    missing_fields = sorted(set(REQUIRED_SOURCE_FIELDS) - set(frame.columns))
    if missing_fields:
        raise ValueError(f"CEUR 2022 V2025-1 source is missing required fields: {missing_fields}")
    if frame.crs is None:
        raise ValueError("CEUR 2022 V2025-1 source requires an explicit CRS")

    result = frame.copy()
    widths = {
        "COD_2022": 9,
        "PROV": 2,
        "DEPTO": 3,
        "FRACC": 2,
        "RADIO": 2,
    }
    for field, width in widths.items():
        result[field] = result[field].map(
            lambda value, field=field, width=width: _normalize_digits(value, width, field)
        )

    if result["COD_2022"].duplicated().any():
        duplicates = sorted(
            result.loc[result["COD_2022"].duplicated(False), "COD_2022"].unique()
        )
        raise ValueError(
            "CEUR 2022 V2025-1 native IDs must be unique; "
            f"duplicates include {duplicates[:10]}"
        )

    reconstructed = result["PROV"] + result["DEPTO"] + result["FRACC"] + result["RADIO"]
    identity_mismatch = result["COD_2022"].ne(reconstructed)
    if identity_mismatch.any():
        sample = result.loc[
            identity_mismatch, ["COD_2022", "PROV", "DEPTO", "FRACC", "RADIO"]
        ].head(10)
        raise ValueError(
            "COD_2022 is inconsistent with PROV+DEPTO+FRACC+RADIO; "
            f"source identity drift detected: {sample.to_dict(orient='records')}"
        )

    missing_geometry = int(result.geometry.isna().sum())
    empty_geometry = int(result.geometry.is_empty.sum())
    areal = result.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    non_areal_geometry = int(
        (result.geometry.notna() & ~result.geometry.is_empty & ~areal).sum()
    )
    if missing_geometry or empty_geometry or non_areal_geometry:
        raise ValueError(
            "CEUR 2022 V2025-1 geography has unusable source geometry: "
            f"missing={missing_geometry}, empty={empty_geometry}, "
            f"non_areal={non_areal_geometry}"
        )

    qa_warnings = _driver_warning_items(driver_warnings or [])
    invalid_mask = ~result.geometry.is_valid
    invalid_geometry = int(invalid_mask.sum())
    if invalid_geometry:
        qa_warnings.append(
            _warning(
                "source_invalid_geometry",
                "Source-invalid CEUR polygons are retained without repair and excluded "
                "from the analytical geometry role.",
                affected_rows=invalid_geometry,
            )
        )

    result["native_id"] = result["COD_2022"]
    result["geo_uid"] = "ceur:v2025-1:census:2022:radio:" + result["native_id"]
    result["province_code"] = result["PROV"]
    result["department_code"] = result["PROV"] + result["DEPTO"]
    result["fraction_code"] = result["FRACC"]
    result["radio_code"] = result["RADIO"]
    result["geometry_valid"] = ~invalid_mask
    result["geometry_role"] = "analytical"
    result.loc[invalid_mask, "geometry_role"] = "source_invalid"

    columns = [
        "geo_uid",
        "native_id",
        "COD_2022",
        "PROV",
        "DEPTO",
        "FRACC",
        "RADIO",
        "province_code",
        "department_code",
        "fraction_code",
        "radio_code",
        "OBS2022",
        "VIV_TOT_P",
        "POB_TOT_P",
        "REDATAM",
        "geometry_valid",
        "geometry_role",
        result.geometry.name,
    ]
    result = result[columns].sort_values("geo_uid", ignore_index=True)

    annotation_count = int(result["OBS2022"].notna().sum())
    redatam_counts = (
        result["REDATAM"]
        .astype(str)
        .value_counts(dropna=False)
        .sort_index()
        .astype(int)
        .to_dict()
    )
    audit = {
        "stage_decision": "PASS_WITH_WARNINGS" if qa_warnings else "PASS",
        "accepted_warning_count": len(qa_warnings),
        "accepted_warnings": qa_warnings,
        "feature_count": len(result),
        "unique_native_id_count": int(result["native_id"].nunique()),
        "missing_identity_count": int(result["native_id"].isna().sum()),
        "duplicate_identity_count": int(result["native_id"].duplicated().sum()),
        "identity_composition_mismatch_count": int(identity_mismatch.sum()),
        "crs": result.crs.to_string(),
        "geometry_types": sorted(result.geom_type.unique().tolist()),
        "missing_geometry_count": missing_geometry,
        "empty_geometry_count": empty_geometry,
        "invalid_geometry_count": invalid_geometry,
        "non_areal_geometry_count": non_areal_geometry,
        "analytical_geometry_count": int(result["geometry_valid"].sum()),
        "source_invalid_geometry_count": invalid_geometry,
        "source_annotation_count": annotation_count,
        "redatam_value_counts": {
            str(key): int(value) for key, value in redatam_counts.items()
        },
        "bbox": [float(value) for value in result.total_bounds.tolist()],
    }
    return result, audit


def _release_version(config: dict, source_sha256: str) -> str:
    release = config["release"].lower()
    return f"{release}-2022-{source_sha256[:12]}"


def materialize_from_source(
    source_path: Path, output: Path, config_path: Path = DEFAULT_CONFIG
) -> dict:
    config = load_config(config_path)
    source_sha256 = sha256_file(source_path)
    source_size = source_path.stat().st_size

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        frame = _read_source(source_path)
    driver_messages = [
        str(item.message) for item in caught if issubclass(item.category, RuntimeWarning)
    ]
    normalized, audit = normalize_source(frame, config, driver_warnings=driver_messages)

    output.mkdir(parents=True, exist_ok=True)
    geography_path = output / "geography.parquet"
    normalized.to_parquet(geography_path, index=False)
    content_sha256 = sha256_file(geography_path)
    release_version = _release_version(config, source_sha256)

    geography = GeographySpec(
        provider="ceur",
        version="2022-v2025-1",
        scheme="census",
        level="radio",
    )
    dataset = DatasetRef(
        dataset_id="arggeo.ceur.census.2022.radio",
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
        release=config["release"],
        snapshot_id=f"sha256:{source_sha256}",
        origin=config["record_uri"],
        storage_mode="external_immutable",
        files=(
            SourceFileRef(
                path=config["file_name"],
                sha256=source_sha256,
                size_bytes=source_size,
            ),
        ),
    )
    qa_state = "YELLOW" if audit["stage_decision"] == "PASS_WITH_WARNINGS" else "GREEN"
    qa_result = QAResult(
        check_id="ceur_2022_v2025_1_radio_source_contract",
        state=qa_state,
        message=(
            "CEUR Census 2022 V2025-1 radio source is stageable with recorded "
            "non-blocking warnings."
            if qa_state == "YELLOW"
            else "CEUR Census 2022 V2025-1 radio source satisfies the normalized "
            "geography boundary."
        ),
        metrics={
            "feature_count": audit["feature_count"],
            "unique_native_id_count": audit["unique_native_id_count"],
            "invalid_geometry_count": audit["invalid_geometry_count"],
            "analytical_geometry_count": audit["analytical_geometry_count"],
            "source_annotation_count": audit["source_annotation_count"],
            "accepted_warning_count": audit["accepted_warning_count"],
            "crs": audit["crs"],
        },
    )
    now = datetime.now(UTC)
    run = RunManifest(
        run_id=f"ceur-2022-v2025-1:{source_sha256[:16]}",
        package="argentina-geography",
        package_version=package_version(),
        started_at=now,
        finished_at=now,
        inputs=(source_snapshot,),
        parameters={
            "distribution_mode": config["distribution_mode"],
            "record_uri": config["record_uri"],
            "source_file": config["file_name"],
            "source_crs": audit["crs"],
            "identity_field": "COD_2022",
            "identity_composition": "PROV+DEPTO+FRACC+RADIO",
            "geometry_repair_applied": False,
            "stage_decision": audit["stage_decision"],
            "accepted_qa_warnings": audit["accepted_warnings"],
            "license_name": config["license_name"],
            "license_url": config["license_url"],
            "citation": config["citation"],
        },
        outputs=(dataset,),
        qa=(qa_result,),
    )
    source_metadata = {
        **config,
        "acquisition_url": config["download_url"],
        "retrieved_file_sha256": source_sha256,
        "retrieved_file_size_bytes": source_size,
        "received_crs": audit["crs"],
        "native_identity_field": "COD_2022",
        "native_identity_composition": "PROV+DEPTO+FRACC+RADIO",
    }
    limitations = {
        "dataset_id": dataset.dataset_id,
        "release_version": release_version,
        "items": config["known_limitations"],
        "accepted_qa_warnings": audit["accepted_warnings"],
        "attribution": config["attribution"],
        "citation": config["citation"],
        "license_name": config["license_name"],
        "license_url": config["license_url"],
    }
    catalog = pd.DataFrame(
        [
            {
                "geography_id": geography.id,
                "dataset_id": dataset.dataset_id,
                "release_version": dataset.version,
                "schema_version": dataset.schema_version,
                "provider": "ceur",
                "scheme": "census",
                "vintage": "2022",
                "level": "radio",
                "source_release": config["release"],
                "authority_status": "curated_research",
                "feature_count": audit["feature_count"],
                "analytical_feature_count": audit["analytical_geometry_count"],
                "native_id_fields": "COD_2022",
                "source_code_fields": "PROV,DEPTO,FRACC,RADIO",
                "geometry_types": ",".join(audit["geometry_types"]),
                "storage_crs": audit["crs"],
                "coverage_status": "source_layer_as_retrieved",
                "qa_state": qa_state,
                "stage_decision": audit["stage_decision"],
                "artifact_ref": "geography.parquet",
                "manifest_ref": "manifest.json",
                "distribution_mode": config["distribution_mode"],
                "license": config["license_name"],
            }
        ]
    )
    catalog.to_parquet(output / "geography_catalog.parquet", index=False)
    write_json(output / "qa.json", audit)
    write_json(output / "source_metadata.json", source_metadata)
    write_json(output / "limitations.json", limitations)
    manifest = {
        "product_type": "geography",
        "authority_status": "curated_research",
        "distribution_mode": config["distribution_mode"],
        "stage_decision": audit["stage_decision"],
        "dataset": dataset.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "row_count": len(normalized),
        "analytical_row_count": audit["analytical_geometry_count"],
        "source_snapshot": source_snapshot.model_dump(mode="json"),
        "license": {
            "name": config["license_name"],
            "url": config["license_url"],
            "attribution": config["attribution"],
        },
        "citation": config["citation"],
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
    output: Path, *, source: Path | None = None, config_path: Path = DEFAULT_CONFIG
) -> dict:
    config = load_config(config_path)
    if source is not None:
        return materialize_from_source(source, output, config_path)
    with tempfile.TemporaryDirectory(prefix="arggeo-ceur-2022-v2025-1-") as temporary:
        source_path = Path(temporary) / config["file_name"]
        download_source(source_path, config)
        return materialize_from_source(source_path, output, config_path)


def verify_release(output: Path) -> None:
    verify_checksums(output)
    manifest = validate_manifest(output / "manifest.json")
    dataset = manifest["dataset"]
    frame = gpd.read_parquet(output / manifest["artifacts"]["geography"])

    if len(frame) != manifest["row_count"]:
        raise ValueError("CEUR 2022 V2025-1 release row count does not match manifest")
    if sha256_file(output / manifest["artifacts"]["geography"]) != dataset["content_sha256"]:
        raise ValueError("CEUR 2022 V2025-1 geography content hash mismatch")
    if frame["geo_uid"].isna().any() or frame["geo_uid"].duplicated().any():
        raise ValueError("CEUR 2022 V2025-1 geo_uid must be non-missing and unique")
    if frame["native_id"].isna().any() or frame["native_id"].duplicated().any():
        raise ValueError("CEUR 2022 V2025-1 native_id must be non-missing and unique")
    if frame["native_id"].ne(frame["COD_2022"]).any():
        raise ValueError("CEUR 2022 V2025-1 native_id must equal COD_2022")

    reconstructed = frame["PROV"] + frame["DEPTO"] + frame["FRACC"] + frame["RADIO"]
    if frame["COD_2022"].ne(reconstructed).any():
        raise ValueError("CEUR 2022 V2025-1 identity composition no longer holds")
    if frame["province_code"].ne(frame["PROV"]).any():
        raise ValueError("CEUR 2022 V2025-1 province_code is inconsistent with PROV")
    if frame["department_code"].ne(frame["PROV"] + frame["DEPTO"]).any():
        raise ValueError("CEUR 2022 V2025-1 department_code is inconsistent with PROV+DEPTO")
    if frame["fraction_code"].ne(frame["FRACC"]).any():
        raise ValueError("CEUR 2022 V2025-1 fraction_code is inconsistent with FRACC")
    if frame["radio_code"].ne(frame["RADIO"]).any():
        raise ValueError("CEUR 2022 V2025-1 radio_code is inconsistent with RADIO")

    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError("CEUR 2022 V2025-1 release contains missing or empty source geometry")
    non_areal = ~frame.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if non_areal.any():
        raise ValueError("CEUR 2022 V2025-1 release contains non-areal source geometry")

    analytical = frame["geometry_role"].eq("analytical")
    source_invalid = frame["geometry_role"].eq("source_invalid")
    if (~(analytical | source_invalid)).any():
        raise ValueError("CEUR 2022 V2025-1 release has unsupported geometry_role")
    if (~frame.loc[analytical].geometry.is_valid).any():
        raise ValueError("analytical CEUR rows must contain valid geometry")
    if frame.loc[source_invalid].geometry.is_valid.any():
        raise ValueError("source_invalid CEUR rows must correspond to invalid geometry")
    if frame["geometry_valid"].astype(bool).ne(analytical).any():
        raise ValueError("CEUR 2022 V2025-1 geometry_valid disagrees with geometry_role")

    catalog = pd.read_parquet(output / manifest["artifacts"]["catalog"])
    if len(catalog) != 1 or catalog.iloc[0]["dataset_id"] != dataset["dataset_id"]:
        raise ValueError("CEUR 2022 V2025-1 catalog does not identify the release")
    if manifest.get("authority_status") != "curated_research":
        raise ValueError("CEUR 2022 V2025-1 release must remain curated_research")
    if manifest.get("distribution_mode") != "redistributed_snapshot":
        raise ValueError("CEUR 2022 V2025-1 distribution boundary changed unexpectedly")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize the CEUR Census 2022 radio V2025-1 geography."
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
        acquire_and_materialize(args.output, source=args.source, config_path=args.config)
        verify_release(args.output)
    else:
        verify_release(args.release)


if __name__ == "__main__":
    main()
