from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
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
DEFAULT_CONFIG = ROOT / "config/sources/indec_census_2022_radio.json"
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


def build_wfs_url(config: dict) -> str:
    params = {
        "service": "WFS",
        "version": config["wfs_version"],
        "request": "GetFeature",
        "typeName": config["layer_name"],
        "outputFormat": config["wfs_output_format"],
    }
    return f"{config['wfs_url']}?{urlencode(params)}"


def download_source(destination: Path, config: dict) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(
        build_wfs_url(config),
        headers={"User-Agent": "argentina-geography/0.1 research-data-client"},
    )
    with urlopen(request, timeout=300) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)
    if destination.stat().st_size == 0:
        raise ValueError("INDEC WFS returned an empty source file")
    if destination.suffix.lower() == ".zip" and destination.read_bytes()[:2] != b"PK":
        raise ValueError("INDEC WFS response is not a ZIP archive; source endpoint may have changed")
    return destination


def _normalize_digits(value: object, width: int, field: str) -> str:
    if pd.isna(value):
        raise ValueError(f"{field} must be non-missing")
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text.isascii() or not text.isdigit() or len(text) > width:
        raise ValueError(f"{field} must contain at most {width} ASCII digits: {value!r}")
    return text.zfill(width)


def _read_source(path: Path) -> gpd.GeoDataFrame:
    source = f"zip://{path.resolve()}" if path.suffix.lower() == ".zip" else str(path)
    return gpd.read_file(source, engine="pyogrio", use_arrow=True)


def _normalized_name(value: object) -> str:
    return " ".join(str(value).strip().casefold().split())


def normalize_source(frame: gpd.GeoDataFrame, config: dict) -> tuple[gpd.GeoDataFrame, dict]:
    missing_fields = sorted(set(config["required_fields"]) - set(frame.columns))
    if missing_fields:
        raise ValueError(f"INDEC 2022 radio source is missing required fields: {missing_fields}")
    if frame.crs is None:
        raise ValueError("INDEC 2022 radio source requires an explicit CRS")

    result = frame.copy()
    for field in ("cpr", "cde", "cfn", "cro", "cod_indec"):
        width = config["component_widths"][field]
        result[field] = result[field].map(
            lambda value, field=field, width=width: _normalize_digits(value, width, field)
        )

    reconstructed = result["cpr"] + result["cde"] + result["cfn"] + result["cro"]
    mismatch = reconstructed.ne(result["cod_indec"])
    if mismatch.any():
        sample = result.loc[mismatch, ["cpr", "cde", "cfn", "cro", "cod_indec"]].head(5)
        raise ValueError(
            "cod_indec is inconsistent with its native components; source identity drift detected: "
            f"{sample.to_dict(orient='records')}"
        )
    if result["cod_indec"].duplicated().any():
        duplicates = sorted(result.loc[result["cod_indec"].duplicated(False), "cod_indec"].unique())
        raise ValueError(f"INDEC 2022 radio native IDs must be unique; duplicates include {duplicates[:10]}")

    documented_names = {
        _normalized_name(name) for name in config["documented_adjustment_jurisdictions"]
    }
    name_series = result["jur"].map(_normalized_name)
    documented_codes = set(result.loc[name_series.isin(documented_names), "cpr"].unique())
    if len(documented_codes) != len(documented_names):
        raise ValueError(
            "Could not resolve the documented Entre Ríos/Misiones adjustment jurisdictions "
            "from current INDEC source names"
        )
    zero_code = result["cfn"].eq("00") | result["cro"].eq("00")
    unexpected_zero = zero_code & ~result["cpr"].isin(documented_codes)
    if unexpected_zero.any():
        sample = result.loc[unexpected_zero, ["jur", "cpr", "cde", "cfn", "cro", "cod_indec"]].head(10)
        raise ValueError(
            "Zero-coded fraction/radio units occur outside the jurisdictions documented by INDEC: "
            f"{sample.to_dict(orient='records')}"
        )

    missing_geometry = int(result.geometry.isna().sum())
    empty_geometry = int(result.geometry.is_empty.sum())
    invalid_geometry = int((result.geometry.notna() & ~result.geometry.is_valid).sum())
    areal = result.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    non_areal_geometry = int((result.geometry.notna() & ~result.geometry.is_empty & ~areal).sum())
    if missing_geometry or empty_geometry or invalid_geometry or non_areal_geometry:
        raise ValueError(
            "INDEC 2022 radio geography is not publishable without a new geometry policy: "
            f"missing={missing_geometry}, empty={empty_geometry}, invalid={invalid_geometry}, "
            f"non_areal={non_areal_geometry}"
        )

    result["native_id"] = result["cod_indec"]
    result["geo_uid"] = "indec:2022:census:radio:" + result["native_id"]
    result["source_unit_status"] = "ordinary"
    result.loc[zero_code, "source_unit_status"] = "adjustment_no_census_data"
    result["geometry_role"] = "analytical"

    preserved = [
        field for field in config["optional_preserved_fields"] if field in result.columns
    ]
    columns = [
        "geo_uid",
        "native_id",
        "jur",
        "cpr",
        "cde",
        "dpto",
        "cfn",
        "cro",
        "tro",
        "cod_indec",
        *preserved,
        "source_unit_status",
        "geometry_role",
        result.geometry.name,
    ]
    result = result[columns].sort_values("geo_uid", ignore_index=True)
    bounds = result.total_bounds.tolist()
    adjustment = result["source_unit_status"].eq("adjustment_no_census_data")
    adjustment_by_jurisdiction = (
        result.loc[adjustment].groupby(["cpr", "jur"], dropna=False).size().astype(int).to_dict()
    )
    audit = {
        "feature_count": len(result),
        "unique_native_id_count": int(result["native_id"].nunique()),
        "crs": result.crs.to_string(),
        "geometry_types": sorted(result.geom_type.unique().tolist()),
        "missing_identity_count": int(result["native_id"].isna().sum()),
        "duplicate_identity_count": int(result["native_id"].duplicated().sum()),
        "missing_geometry_count": missing_geometry,
        "empty_geometry_count": empty_geometry,
        "invalid_geometry_count": invalid_geometry,
        "non_areal_geometry_count": non_areal_geometry,
        "adjustment_feature_count": int(adjustment.sum()),
        "adjustment_by_jurisdiction": [
            {"cpr": key[0], "jur": key[1], "count": value}
            for key, value in sorted(adjustment_by_jurisdiction.items())
        ],
        "bbox": [float(value) for value in bounds],
    }
    return result, audit


def _release_version(config: dict, source_sha256: str) -> str:
    date = config["metadata_publication_date"][:10].replace("-", "")
    return f"2022-national-{date}-{source_sha256[:12]}"


def materialize_from_source(source_path: Path, output: Path, config_path: Path = DEFAULT_CONFIG) -> dict:
    config = load_config(config_path)
    source_sha256 = sha256_file(source_path)
    source_size = source_path.stat().st_size
    frame = _read_source(source_path)
    normalized, audit = normalize_source(frame, config)

    output.mkdir(parents=True, exist_ok=True)
    geography_path = output / "geography.parquet"
    normalized.to_parquet(geography_path, index=False)
    content_sha256 = sha256_file(geography_path)
    release_version = _release_version(config, source_sha256)
    geography = GeographySpec(provider="indec", version="2022", scheme="census", level="radio")
    dataset = DatasetRef(
        dataset_id="arggeo.indec.census.2022.radio",
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
        release=f"2022-national:{config['metadata_publication_date']}",
        snapshot_id=f"sha256:{source_sha256}",
        origin=build_wfs_url(config),
        storage_mode="external_immutable",
        files=(
            SourceFileRef(
                path=source_path.name,
                sha256=source_sha256,
                size_bytes=source_size,
            ),
        ),
    )
    qa_result = QAResult(
        check_id="indec_2022_radio_source_contract",
        state="GREEN",
        message="Official INDEC 2022 radio source satisfies the normalized geography boundary.",
        metrics={
            "feature_count": audit["feature_count"],
            "unique_native_id_count": audit["unique_native_id_count"],
            "invalid_geometry_count": audit["invalid_geometry_count"],
            "adjustment_feature_count": audit["adjustment_feature_count"],
            "crs": audit["crs"],
        },
    )
    now = datetime.now(UTC)
    run = RunManifest(
        run_id=f"indec-2022-radio:{source_sha256[:16]}",
        package="argentina-geography",
        package_version=package_version(),
        started_at=now,
        finished_at=now,
        inputs=(source_snapshot,),
        parameters={
            "distribution_mode": config["distribution_mode"],
            "metadata_url": config["metadata_url"],
            "source_crs": audit["crs"],
            "geometry_repair_applied": False,
        },
        outputs=(dataset,),
        qa=(qa_result,),
    )
    source_metadata = {
        **config,
        "acquisition_url": build_wfs_url(config),
        "retrieved_file_sha256": source_sha256,
        "retrieved_file_size_bytes": source_size,
        "received_crs": audit["crs"],
    }
    limitations = {
        "dataset_id": dataset.dataset_id,
        "release_version": release_version,
        "items": config["known_limitations"],
        "adjustment_unit_semantics": config["documented_adjustment_semantics"],
    }
    catalog = pd.DataFrame(
        [
            {
                "geography_id": geography.id,
                "dataset_id": dataset.dataset_id,
                "release_version": dataset.version,
                "schema_version": dataset.schema_version,
                "provider": "indec",
                "scheme": "census",
                "vintage": "2022",
                "level": "radio",
                "source_release": config["metadata_publication_date"],
                "authority_status": "official",
                "feature_count": audit["feature_count"],
                "native_id_fields": "cod_indec,cpr,cde,cfn,cro",
                "geometry_types": ",".join(audit["geometry_types"]),
                "storage_crs": audit["crs"],
                "coverage_status": "source_layer_as_retrieved",
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
        "dataset": dataset.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "row_count": len(normalized),
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


def acquire_and_materialize(output: Path, *, source: Path | None = None, config_path: Path = DEFAULT_CONFIG) -> dict:
    config = load_config(config_path)
    if source is not None:
        return materialize_from_source(source, output, config_path)
    with tempfile.TemporaryDirectory(prefix="arggeo-indec-2022-") as temporary:
        source_path = Path(temporary) / "indec_radios_censales_2022.zip"
        download_source(source_path, config)
        return materialize_from_source(source_path, output, config_path)


def verify_release(output: Path) -> None:
    verify_checksums(output)
    manifest = validate_manifest(output / "manifest.json")
    dataset = manifest["dataset"]
    frame = gpd.read_parquet(output / manifest["artifacts"]["geography"])
    if len(frame) != manifest["row_count"]:
        raise ValueError("INDEC 2022 radio release row count does not match manifest")
    if sha256_file(output / manifest["artifacts"]["geography"]) != dataset["content_sha256"]:
        raise ValueError("INDEC 2022 radio geography content hash mismatch")
    if frame["geo_uid"].isna().any() or frame["geo_uid"].duplicated().any():
        raise ValueError("INDEC 2022 radio release geo_uid must be non-missing and unique")
    if frame["native_id"].isna().any() or frame["native_id"].duplicated().any():
        raise ValueError("INDEC 2022 radio release native_id must be non-missing and unique")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any() or (~frame.geometry.is_valid).any():
        raise ValueError("INDEC 2022 radio release contains unusable analytical geometry")
    allowed_status = {"ordinary", "adjustment_no_census_data"}
    if not set(frame["source_unit_status"]).issubset(allowed_status):
        raise ValueError("INDEC 2022 radio release has unsupported source_unit_status")
    catalog = pd.read_parquet(output / manifest["artifacts"]["catalog"])
    if len(catalog) != 1 or catalog.iloc[0]["dataset_id"] != dataset["dataset_id"]:
        raise ValueError("INDEC 2022 radio catalog does not identify the materialized release")


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize the official INDEC 2022 national census-radio geography.")
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
