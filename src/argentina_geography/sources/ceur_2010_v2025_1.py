from __future__ import annotations

import argparse
import warnings
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
from argentina_geography.sources.ceur_2010_v2025_1_probe import download_source

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config/sources/ceur_census_2010_radio_v2025_1.json"
REQUIRED_SOURCE_FIELDS = (
    "COD_2010",
    "PROV",
    "DEPTO",
    "FRACC",
    "RADIO",
    "SEGMENTOS",
    "OBS2010",
    "BASICO",
    "AMPLIADO",
    "TIPO",
)
REQUIRED_OUTPUT_FILES = [
    "geography.parquet",
    "geography_catalog.parquet",
    "identity_contract.json",
    "qa.json",
    "source_metadata.json",
    "limitations.json",
    "manifest.json",
]


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    return read_json(path)


def _read_source(path: Path) -> tuple[gpd.GeoDataFrame, str, list[str]]:
    source = f"zip://{path.resolve()}" if path.suffix.lower() == ".zip" else str(path)
    layers = gpd.list_layers(source)
    if len(layers) != 1:
        records = layers.astype(object).where(layers.notna(), None).to_dict(orient="records")
        raise ValueError(
            "CEUR 2010 V2025-1 source must contain exactly one vector layer; "
            f"observed {len(layers)}: {records}"
        )
    layer_name = str(layers.iloc[0]["name"])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        frame = gpd.read_file(
            source,
            layer=layer_name,
            engine="pyogrio",
            use_arrow=True,
        )
    driver_warnings = sorted(
        {str(item.message) for item in caught if issubclass(item.category, RuntimeWarning)}
    )
    return frame, layer_name, driver_warnings


def _digits(value: object, width: int, field: str) -> str:
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


def normalize_source(
    frame: gpd.GeoDataFrame,
    config: dict,
    *,
    driver_warnings: list[str] | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    missing = sorted(set(REQUIRED_SOURCE_FIELDS) - set(frame.columns))
    if missing:
        raise ValueError(f"CEUR 2010 V2025-1 source is missing required fields: {missing}")
    if frame.crs is None:
        raise ValueError("CEUR 2010 V2025-1 source requires an explicit CRS")

    result = frame.copy()
    for field, width in {
        "COD_2010": 9,
        "PROV": 2,
        "DEPTO": 3,
        "FRACC": 2,
        "RADIO": 2,
    }.items():
        result[field] = result[field].map(
            lambda value, field=field, width=width: _digits(value, width, field)
        )

    if result["COD_2010"].duplicated().any():
        duplicates = sorted(
            result.loc[result["COD_2010"].duplicated(False), "COD_2010"].unique()
        )
        raise ValueError(
            "CEUR 2010 V2025-1 native IDs must be unique; "
            f"duplicates include {duplicates[:10]}"
        )

    reconstructed = result["PROV"] + result["DEPTO"] + result["FRACC"] + result["RADIO"]
    mismatch = result["COD_2010"].ne(reconstructed)
    if mismatch.any():
        sample = result.loc[
            mismatch, ["COD_2010", "PROV", "DEPTO", "FRACC", "RADIO"]
        ].head(10)
        raise ValueError(
            "CEUR 2010 COD_2010 disagrees with PROV+DEPTO+FRACC+RADIO; "
            f"source identity drift: {sample.to_dict(orient='records')}"
        )

    geometry = result.geometry
    missing_geometry = int(geometry.isna().sum())
    empty_geometry = int(geometry.is_empty.sum())
    areal = geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    non_areal = int((geometry.notna() & ~geometry.is_empty & ~areal).sum())
    if missing_geometry or empty_geometry or non_areal:
        raise ValueError(
            "CEUR 2010 V2025-1 source has unusable geometry: "
            f"missing={missing_geometry} empty={empty_geometry} non_areal={non_areal}"
        )

    invalid_mask = geometry.notna() & ~geometry.is_valid
    invalid_ids = sorted(result.loc[invalid_mask, "COD_2010"].tolist())
    qa_warnings = [
        _warning(
            "source_driver_warning",
            "The source driver emitted a runtime warning while decoding CEUR V2025-1.",
            driver_message=message,
        )
        for message in (driver_warnings or [])
    ]
    if invalid_ids:
        qa_warnings.append(
            _warning(
                "source_invalid_geometry",
                "Source-invalid CEUR polygons are retained byte-semantically without topology repair and excluded from the analytical geometry role.",
                affected_rows=len(invalid_ids),
                radio_2010_ids=invalid_ids,
            )
        )

    result["native_id"] = result["COD_2010"]
    result["radio_2010_id"] = result["COD_2010"]
    result["department_2010_id"] = result["PROV"] + result["DEPTO"]
    result["province_2010_id"] = result["PROV"]
    result["fraction_2010_id"] = result["PROV"] + result["DEPTO"] + result["FRACC"]
    result["geo_uid"] = "ceur:v2025-1:census:2010:radio:" + result["radio_2010_id"]
    result["geometry_valid"] = ~invalid_mask
    result["geometry_role"] = "analytical"
    result.loc[invalid_mask, "geometry_role"] = "source_invalid"

    native_columns = [column for column in frame.columns if column != frame.geometry.name]
    output_columns = [
        "geo_uid",
        "native_id",
        "radio_2010_id",
        "department_2010_id",
        "province_2010_id",
        "fraction_2010_id",
        *native_columns,
        "geometry_valid",
        "geometry_role",
        result.geometry.name,
    ]
    result = result[output_columns].sort_values("geo_uid", ignore_index=True)

    audit = {
        "stage_decision": "PASS_WITH_WARNINGS" if qa_warnings else "PASS",
        "accepted_warning_count": len(qa_warnings),
        "accepted_warnings": qa_warnings,
        "feature_count": len(result),
        "unique_radio_2010_id_count": int(result["radio_2010_id"].nunique()),
        "province_count": int(result["province_2010_id"].nunique()),
        "department_count": int(result["department_2010_id"].nunique()),
        "identity_composition_mismatch_count": int(mismatch.sum()),
        "crs": result.crs.to_string(),
        "geometry_types": sorted(result.geom_type.unique().tolist()),
        "missing_geometry_count": missing_geometry,
        "empty_geometry_count": empty_geometry,
        "non_areal_geometry_count": non_areal,
        "invalid_geometry_count": len(invalid_ids),
        "invalid_radio_2010_ids": invalid_ids,
        "analytical_geometry_count": int(result["geometry_valid"].sum()),
        "source_annotation_count": int(result["OBS2010"].notna().sum()),
        "basic_flag_counts": {str(k): int(v) for k, v in result["BASICO"].value_counts().sort_index().items()},
        "extended_flag_counts": {str(k): int(v) for k, v in result["AMPLIADO"].value_counts().sort_index().items()},
        "tipo_counts": {str(k): int(v) for k, v in result["TIPO"].value_counts().sort_index().items()},
        "bbox": [float(value) for value in result.total_bounds.tolist()],
    }
    return result, audit


def _release_version(config: dict, source_sha256: str) -> str:
    return f"v2025-1-2010-{source_sha256[:12]}"


def materialize_from_source(
    source_path: Path,
    output: Path,
    config_path: Path = DEFAULT_CONFIG,
) -> dict:
    config = load_config(config_path)
    source_sha256 = sha256_file(source_path)
    source_size = source_path.stat().st_size
    frame, layer_name, driver_warnings = _read_source(source_path)
    normalized, audit = normalize_source(frame, config, driver_warnings=driver_warnings)

    output.mkdir(parents=True, exist_ok=True)
    geography_path = output / "geography.parquet"
    normalized.to_parquet(geography_path, index=False)
    content_sha256 = sha256_file(geography_path)
    release_version = _release_version(config, source_sha256)

    geography = GeographySpec(
        provider="ceur",
        version="2010-v2025-1",
        scheme="census",
        level="radio",
    )
    dataset = DatasetRef(
        dataset_id="arggeo.ceur.census.2010.radio",
        version=release_version,
        schema_version="arggeo.geography/v1",
        layer=DataLayer.SILVER,
        authority=AuthorityLevel.L1_NORMALIZED,
        grain=GrainSpec(keys=("radio_2010_id",)),
        geography=geography,
        content_sha256=content_sha256,
    )
    source_snapshot = SourceSnapshotRef(
        source=config["source_id"],
        release=config["release"],
        snapshot_id=f"sha256:{source_sha256}",
        origin=config["record_uri"],
        storage_mode="external_immutable",
        files=(SourceFileRef(path=config["file_name"], sha256=source_sha256, size_bytes=source_size),),
    )
    qa_state = "YELLOW" if audit["stage_decision"] == "PASS_WITH_WARNINGS" else "GREEN"
    qa_result = QAResult(
        check_id="ceur_2010_v2025_1_radio_source_contract",
        state=qa_state,
        message=(
            "CEUR Census 2010 V2025-1 satisfies the identity boundary with explicit retained source-geometry warnings."
            if qa_state == "YELLOW"
            else "CEUR Census 2010 V2025-1 satisfies the normalized geography boundary."
        ),
        metrics={
            "feature_count": audit["feature_count"],
            "invalid_geometry_count": audit["invalid_geometry_count"],
            "analytical_geometry_count": audit["analytical_geometry_count"],
            "province_count": audit["province_count"],
            "department_count": audit["department_count"],
            "crs": audit["crs"],
        },
    )
    now = datetime.now(UTC)
    run = RunManifest(
        run_id=f"ceur-2010-v2025-1:{source_sha256[:16]}",
        package="argentina-geography",
        package_version=package_version(),
        started_at=now,
        finished_at=now,
        inputs=(source_snapshot,),
        parameters={
            "distribution_mode": config["distribution_mode"],
            "record_uri": config["record_uri"],
            "source_file": config["file_name"],
            "source_layer": layer_name,
            "source_crs": audit["crs"],
            "native_identity_field": "COD_2010",
            "native_identity_composition": "PROV+DEPTO+FRACC+RADIO",
            "consumer_identity_fields": ["radio_2010_id", "department_2010_id", "province_2010_id"],
            "geometry_repair_applied": False,
            "stage_decision": audit["stage_decision"],
            "accepted_qa_warnings": audit["accepted_warnings"],
            "license_name": config["license_name"],
            "license_url": config["license_url"],
        },
        outputs=(dataset,),
        qa=(qa_result,),
    )
    identity_contract = {
        "dataset_id": dataset.dataset_id,
        "release_version": release_version,
        "consumer_fields": {
            "radio_2010_id": "COD_2010 (zero-preserving 9-digit CEUR native code)",
            "department_2010_id": "PROV+DEPTO = radio_2010_id[0:5]",
            "province_2010_id": "PROV = radio_2010_id[0:2]",
        },
        "provider_native_identity": {
            "radio": "COD_2010",
            "components": ["PROV", "DEPTO", "FRACC", "RADIO"],
            "composition": "COD_2010 == PROV+DEPTO+FRACC+RADIO",
        },
        "authority_boundary": "CEUR curated-research identity is preserved independently of official INDEC 2010 authority.",
    }
    source_metadata = {
        **config,
        "acquisition_url": config["download_url"],
        "retrieved_file_sha256": source_sha256,
        "retrieved_file_size_bytes": source_size,
        "source_layer": layer_name,
        "received_crs": audit["crs"],
        "native_columns": frame.columns.tolist(),
        "native_identity_field": "COD_2010",
        "native_identity_composition": "PROV+DEPTO+FRACC+RADIO",
    }
    limitations = {
        "dataset_id": dataset.dataset_id,
        "release_version": release_version,
        "items": config["known_limitations"],
        "accepted_qa_warnings": audit["accepted_warnings"],
        "geometry_note": "Source-invalid polygons are retained unchanged and marked geometry_role=source_invalid; no topology repair is applied.",
        "attribution": config["attribution"],
        "citation": config["citation"],
        "license_name": config["license_name"],
        "license_url": config["license_url"],
    }
    catalog = pd.DataFrame([
        {
            "geography_id": geography.id,
            "dataset_id": dataset.dataset_id,
            "release_version": dataset.version,
            "schema_version": dataset.schema_version,
            "provider": "ceur",
            "scheme": "census",
            "vintage": "2010",
            "level": "radio",
            "source_release": config["release"],
            "authority_status": "curated_research",
            "feature_count": audit["feature_count"],
            "analytical_feature_count": audit["analytical_geometry_count"],
            "native_id_fields": "COD_2010;PROV,DEPTO,FRACC,RADIO",
            "consumer_id_fields": "radio_2010_id,department_2010_id,province_2010_id",
            "geometry_types": ",".join(audit["geometry_types"]),
            "storage_crs": audit["crs"],
            "qa_state": qa_state,
            "manifest_ref": "manifest.json",
            "distribution_mode": config["distribution_mode"],
        }
    ])
    catalog.to_parquet(output / "geography_catalog.parquet", index=False)
    write_json(output / "identity_contract.json", identity_contract)
    write_json(output / "qa.json", audit)
    write_json(output / "source_metadata.json", source_metadata)
    write_json(output / "limitations.json", limitations)
    manifest = {
        "product_type": "geography",
        "authority_status": "curated_research",
        "stage_decision": audit["stage_decision"],
        "dataset": dataset.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "row_count": len(normalized),
        "analytical_row_count": audit["analytical_geometry_count"],
        "source_snapshot": source_snapshot.model_dump(mode="json"),
        "artifacts": {
            "geography": "geography.parquet",
            "catalog": "geography_catalog.parquet",
            "identity_contract": "identity_contract.json",
            "qa": "qa.json",
            "source_metadata": "source_metadata.json",
            "limitations": "limitations.json",
        },
    }
    write_json(output / "manifest.json", manifest)
    write_checksums(output, REQUIRED_OUTPUT_FILES)
    return manifest


def verify_release(output: Path) -> None:
    verify_checksums(output)
    manifest = validate_manifest(output / "manifest.json")
    frame = gpd.read_parquet(output / manifest["artifacts"]["geography"])
    if len(frame) != manifest["row_count"]:
        raise ValueError("CEUR 2010 row count does not match manifest")
    required = {"radio_2010_id", "department_2010_id", "province_2010_id", "COD_2010"}
    if not required.issubset(frame.columns):
        raise ValueError("CEUR 2010 stable/native identity fields are missing")
    if frame["radio_2010_id"].duplicated().any():
        raise ValueError("CEUR 2010 detached release has duplicate radio_2010_id")
    if not frame["radio_2010_id"].str.match(r"^[0-9]{9}$").all():
        raise ValueError("CEUR 2010 radio IDs must be zero-preserving 9-digit strings")
    if not frame["radio_2010_id"].eq(frame["COD_2010"]).all():
        raise ValueError("CEUR 2010 consumer radio ID disagrees with COD_2010")
    if not frame["department_2010_id"].eq(frame["radio_2010_id"].str[:5]).all():
        raise ValueError("CEUR 2010 department IDs disagree with radio IDs")
    if not frame["province_2010_id"].eq(frame["radio_2010_id"].str[:2]).all():
        raise ValueError("CEUR 2010 province IDs disagree with radio IDs")
    invalid = ~frame.geometry.is_valid
    if not frame.loc[invalid, "geometry_role"].eq("source_invalid").all():
        raise ValueError("CEUR 2010 invalid geometries are not explicitly marked source_invalid")
    if not frame.loc[~invalid, "geometry_role"].eq("analytical").all():
        raise ValueError("CEUR 2010 valid geometries are not explicitly marked analytical")
    catalog = pd.read_parquet(output / manifest["artifacts"]["catalog"])
    if len(catalog) != 1 or catalog.iloc[0]["dataset_id"] != manifest["dataset"]["dataset_id"]:
        raise ValueError("CEUR 2010 catalog does not identify the detached release")


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize CEUR Census 2010 radio V2025-1 geography.")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("materialize")
    build.add_argument("--source", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    verify = sub.add_parser("verify")
    verify.add_argument("--release", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "materialize":
        materialize_from_source(args.source, args.output, args.config)
    else:
        verify_release(args.release)


if __name__ == "__main__":
    main()
