from __future__ import annotations

import argparse
import shutil
import tempfile
import warnings
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
DEFAULT_CONFIG = ROOT / "config/sources/indec_census_2022_fraction.json"
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
        raise ValueError("INDEC WFS returned an empty fraction source file")
    if destination.suffix.lower() == ".zip" and destination.read_bytes()[:2] != b"PK":
        raise ValueError("INDEC WFS response is not a ZIP archive; source endpoint may have changed")
    return destination


def _digit_text(value: object, *, field: str, max_width: int) -> str:
    if pd.isna(value):
        raise ValueError(f"{field} must be non-missing")
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text.isascii() or not text.isdigit() or len(text) > max_width:
        raise ValueError(f"{field} must contain at most {max_width} ASCII digits: {value!r}")
    return text


def _normalize_digits(value: object, width: int, field: str) -> str:
    return _digit_text(value, field=field, max_width=width).zfill(width)


def _read_source(path: Path, *, encoding: str | None = None) -> gpd.GeoDataFrame:
    source = f"zip://{path.resolve()}" if path.suffix.lower() == ".zip" else str(path)
    kwargs = {"engine": "pyogrio", "use_arrow": True}
    if encoding and path.suffix.lower() == ".zip":
        kwargs["encoding"] = encoding
    return gpd.read_file(source, **kwargs)


def _normalized_name(value: object) -> str:
    return " ".join(str(value).strip().casefold().split())


def _warning(code: str, message: str, **metrics: object) -> dict:
    item = {"code": code, "stage_decision": "PASS_WITH_WARNINGS", "message": message}
    if metrics:
        item["metrics"] = metrics
    return item


def _driver_warning_items(messages: list[str]) -> list[dict]:
    items = []
    for message in sorted(set(messages)):
        code = "noncanonical_ring_winding" if "winding order" in message.lower() else "source_driver_warning"
        items.append(
            _warning(
                code,
                "The source driver emitted a runtime warning while decoding the provider snapshot; the message is preserved for review.",
                driver_message=message,
            )
        )
    return items


def normalize_source(
    frame: gpd.GeoDataFrame,
    config: dict,
    *,
    driver_warnings: list[str] | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    missing_fields = sorted(set(config["required_fields"]) - set(frame.columns))
    if missing_fields:
        raise ValueError(f"INDEC 2022 fraction source is missing required fields: {missing_fields}")
    if frame.crs is None:
        raise ValueError("INDEC 2022 fraction source requires an explicit CRS")

    result = frame.copy()
    for field in ("cpr", "cfn", "cod_indec"):
        width = config["component_widths"][field]
        result[field] = result[field].map(
            lambda value, field=field, width=width: _normalize_digits(value, width, field)
        )
    result["cde"] = result["cde"].map(
        lambda value: _digit_text(value, field="cde", max_width=config["source_cde_max_width"])
    )

    if result["cod_indec"].duplicated().any():
        duplicates = sorted(result.loc[result["cod_indec"].duplicated(False), "cod_indec"].unique())
        raise ValueError(
            f"INDEC 2022 fraction native IDs must be unique; duplicates include {duplicates[:10]}"
        )

    result["department_code"] = result["cod_indec"].str[:5]
    result["fraction_code"] = result["cod_indec"].str[5:7]

    qa_warnings = _driver_warning_items(driver_warnings or [])
    cpr_mismatch = result["cpr"].ne(result["cod_indec"].str[:2])
    cfn_mismatch = result["cfn"].ne(result["fraction_code"])
    cde_cumulative = result["cde"].eq(result["department_code"])
    cde_local = result["cde"].str.zfill(3).eq(result["department_code"].str[2:])
    cde_unclassified = ~(cde_cumulative | cde_local)
    local_count = int(cde_local.sum())
    if local_count:
        qa_warnings.append(
            _warning(
                "mixed_source_cde_representation",
                "Source cde includes local three-digit department representations; cod_indec remains authoritative.",
                local_representation_count=local_count,
                cumulative_representation_count=int(cde_cumulative.sum()),
            )
        )
    supporting_disagreement = cpr_mismatch | cfn_mismatch | cde_unclassified
    if supporting_disagreement.any():
        qa_warnings.append(
            _warning(
                "supporting_code_disagreement",
                "Supporting provider code fields disagree with normalized slices of cod_indec; rows are retained and cod_indec remains authoritative.",
                affected_rows=int(supporting_disagreement.sum()),
                cpr_mismatch_count=int(cpr_mismatch.sum()),
                cfn_mismatch_count=int(cfn_mismatch.sum()),
                cde_unclassified_count=int(cde_unclassified.sum()),
            )
        )

    documented_names = {
        _normalized_name(name) for name in config["documented_adjustment_jurisdictions"]
    }
    name_series = result["jur"].map(_normalized_name)
    documented_codes = set(result.loc[name_series.isin(documented_names), "cpr"].unique())
    if len(documented_codes) != len(documented_names):
        qa_warnings.append(
            _warning(
                "adjustment_jurisdiction_name_drift",
                "Not all documented adjustment jurisdictions were resolved from current provider names; zero-coded fractions remain classified conservatively.",
                resolved_jurisdiction_count=len(documented_codes),
                documented_jurisdiction_count=len(documented_names),
            )
        )
    zero_code = result["cfn"].eq("00")
    documented_adjustment = zero_code & result["cpr"].isin(documented_codes)
    unclassified_zero = zero_code & ~result["cpr"].isin(documented_codes)
    if unclassified_zero.any():
        qa_warnings.append(
            _warning(
                "unclassified_zero_code",
                "Zero-coded fractions occur outside the cases explicitly documented in current INDEC metadata; no no-data semantics are inferred for them.",
                affected_rows=int(unclassified_zero.sum()),
            )
        )

    missing_geometry = int(result.geometry.isna().sum())
    empty_geometry = int(result.geometry.is_empty.sum())
    areal = result.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    non_areal_geometry = int((result.geometry.notna() & ~result.geometry.is_empty & ~areal).sum())
    if missing_geometry or empty_geometry or non_areal_geometry:
        raise ValueError(
            "INDEC 2022 fraction geography has unusable source geometry: "
            f"missing={missing_geometry}, empty={empty_geometry}, non_areal={non_areal_geometry}"
        )
    invalid_mask = ~result.geometry.is_valid
    invalid_geometry = int(invalid_mask.sum())
    if invalid_geometry:
        qa_warnings.append(
            _warning(
                "source_invalid_geometry",
                "Source-invalid polygons are retained without repair and excluded from the analytical geometry role.",
                affected_rows=invalid_geometry,
            )
        )

    result["native_id"] = result["cod_indec"]
    result["geo_uid"] = "indec:2022:census:fraction:" + result["native_id"]
    result["source_unit_status"] = "ordinary"
    result.loc[documented_adjustment, "source_unit_status"] = "adjustment_no_census_data"
    result.loc[unclassified_zero, "source_unit_status"] = "zero_code_unclassified"
    result["geometry_valid"] = ~invalid_mask
    result["geometry_role"] = "analytical"
    result.loc[invalid_mask, "geometry_role"] = "source_invalid"

    preserved = [field for field in config["optional_preserved_fields"] if field in result.columns]
    columns = [
        "geo_uid",
        "native_id",
        "jur",
        "cpr",
        "cde",
        "dpto",
        "cfn",
        "cod_indec",
        "department_code",
        "fraction_code",
        *preserved,
        "source_unit_status",
        "geometry_valid",
        "geometry_role",
        result.geometry.name,
    ]
    result = result[columns].sort_values("geo_uid", ignore_index=True)
    adjustment = result["source_unit_status"].eq("adjustment_no_census_data")
    adjustment_by_jurisdiction = (
        result.loc[adjustment]
        .groupby(["cpr", "jur"], dropna=False)
        .size()
        .astype(int)
        .to_dict()
    )
    audit = {
        "stage_decision": "PASS_WITH_WARNINGS" if qa_warnings else "PASS",
        "accepted_warning_count": len(qa_warnings),
        "accepted_warnings": qa_warnings,
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
        "analytical_geometry_count": int(result["geometry_valid"].sum()),
        "source_invalid_geometry_count": invalid_geometry,
        "cde_cumulative_representation_count": int(cde_cumulative.sum()),
        "cde_local_representation_count": local_count,
        "supporting_code_disagreement_count": int(supporting_disagreement.sum()),
        "adjustment_feature_count": int(adjustment.sum()),
        "zero_code_unclassified_count": int(unclassified_zero.sum()),
        "adjustment_by_jurisdiction": [
            {"cpr": key[0], "jur": key[1], "count": value}
            for key, value in sorted(adjustment_by_jurisdiction.items())
        ],
        "bbox": [float(value) for value in result.total_bounds.tolist()],
    }
    return result, audit


def _release_version(config: dict, source_sha256: str) -> str:
    date = config["metadata_publication_date"][:10].replace("-", "")
    return f"2022-national-{date}-{source_sha256[:12]}"


def materialize_from_source(
    source_path: Path, output: Path, config_path: Path = DEFAULT_CONFIG
) -> dict:
    config = load_config(config_path)
    source_sha256 = sha256_file(source_path)
    source_size = source_path.stat().st_size
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        frame = _read_source(source_path, encoding=config.get("source_encoding"))
    driver_messages = [str(item.message) for item in caught if issubclass(item.category, RuntimeWarning)]
    normalized, audit = normalize_source(frame, config, driver_warnings=driver_messages)

    output.mkdir(parents=True, exist_ok=True)
    geography_path = output / "geography.parquet"
    normalized.to_parquet(geography_path, index=False)
    content_sha256 = sha256_file(geography_path)
    release_version = _release_version(config, source_sha256)
    geography = GeographySpec(provider="indec", version="2022", scheme="census", level="fraction")
    dataset = DatasetRef(
        dataset_id="arggeo.indec.census.2022.fraction",
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
        files=(SourceFileRef(path=source_path.name, sha256=source_sha256, size_bytes=source_size),),
    )
    qa_state = "YELLOW" if audit["stage_decision"] == "PASS_WITH_WARNINGS" else "GREEN"
    qa_result = QAResult(
        check_id="indec_2022_fraction_source_contract",
        state=qa_state,
        message=(
            "Official INDEC 2022 fraction source is stageable with recorded non-blocking warnings."
            if qa_state == "YELLOW"
            else "Official INDEC 2022 fraction source satisfies the normalized geography boundary."
        ),
        metrics={
            "feature_count": audit["feature_count"],
            "unique_native_id_count": audit["unique_native_id_count"],
            "invalid_geometry_count": audit["invalid_geometry_count"],
            "analytical_geometry_count": audit["analytical_geometry_count"],
            "adjustment_feature_count": audit["adjustment_feature_count"],
            "accepted_warning_count": audit["accepted_warning_count"],
            "crs": audit["crs"],
        },
    )
    now = datetime.now(UTC)
    run = RunManifest(
        run_id=f"indec-2022-fraction:{source_sha256[:16]}",
        package="argentina-geography",
        package_version=package_version(),
        started_at=now,
        finished_at=now,
        inputs=(source_snapshot,),
        parameters={
            "distribution_mode": config["distribution_mode"],
            "metadata_url": config["metadata_url"],
            "coding_note_url": config["coding_note_url"],
            "source_crs": audit["crs"],
            "source_encoding": config.get("source_encoding"),
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
        "acquisition_url": build_wfs_url(config),
        "retrieved_file_sha256": source_sha256,
        "retrieved_file_size_bytes": source_size,
        "received_crs": audit["crs"],
    }
    limitations = {
        "dataset_id": dataset.dataset_id,
        "release_version": release_version,
        "items": config["known_limitations"],
        "accepted_qa_warnings": audit["accepted_warnings"],
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
                "level": "fraction",
                "source_release": config["metadata_publication_date"],
                "authority_status": "official",
                "feature_count": audit["feature_count"],
                "analytical_feature_count": audit["analytical_geometry_count"],
                "native_id_fields": "cod_indec",
                "source_code_fields": "cpr,cde,cfn",
                "geometry_types": ",".join(audit["geometry_types"]),
                "storage_crs": audit["crs"],
                "coverage_status": "source_layer_as_retrieved",
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
    output: Path, *, source: Path | None = None, config_path: Path = DEFAULT_CONFIG
) -> dict:
    config = load_config(config_path)
    if source is not None:
        return materialize_from_source(source, output, config_path)
    with tempfile.TemporaryDirectory(prefix="arggeo-indec-2022-fraction-") as temporary:
        source_path = Path(temporary) / "indec_fracciones_censales_2022.zip"
        download_source(source_path, config)
        return materialize_from_source(source_path, output, config_path)


def verify_release(output: Path) -> None:
    verify_checksums(output)
    manifest = validate_manifest(output / "manifest.json")
    dataset = manifest["dataset"]
    frame = gpd.read_parquet(output / manifest["artifacts"]["geography"])
    if len(frame) != manifest["row_count"]:
        raise ValueError("INDEC 2022 fraction release row count does not match manifest")
    if sha256_file(output / manifest["artifacts"]["geography"]) != dataset["content_sha256"]:
        raise ValueError("INDEC 2022 fraction geography content hash mismatch")
    if frame["geo_uid"].isna().any() or frame["geo_uid"].duplicated().any():
        raise ValueError("INDEC 2022 fraction geo_uid must be non-missing and unique")
    if frame["native_id"].isna().any() or frame["native_id"].duplicated().any():
        raise ValueError("INDEC 2022 fraction native_id must be non-missing and unique")
    if frame["native_id"].ne(frame["cod_indec"]).any():
        raise ValueError("INDEC 2022 fraction native_id must equal cod_indec")
    if frame["department_code"].ne(frame["cod_indec"].str[:5]).any():
        raise ValueError("INDEC 2022 fraction department_code is inconsistent with cod_indec")
    if frame["fraction_code"].ne(frame["cod_indec"].str[5:7]).any():
        raise ValueError("INDEC 2022 fraction fraction_code is inconsistent with cod_indec")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError("INDEC 2022 fraction release contains missing or empty source geometry")
    non_areal = ~frame.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if non_areal.any():
        raise ValueError("INDEC 2022 fraction release contains non-areal source geometry")
    analytical = frame["geometry_role"].eq("analytical")
    source_invalid = frame["geometry_role"].eq("source_invalid")
    if (~(analytical | source_invalid)).any():
        raise ValueError("INDEC 2022 fraction release has unsupported geometry_role")
    if (~frame.loc[analytical].geometry.is_valid).any():
        raise ValueError("analytical fraction rows must contain valid geometry")
    if frame.loc[source_invalid].geometry.is_valid.any():
        raise ValueError("source_invalid fraction rows must correspond to invalid geometry")
    allowed_status = {"ordinary", "adjustment_no_census_data", "zero_code_unclassified"}
    if not set(frame["source_unit_status"]).issubset(allowed_status):
        raise ValueError("INDEC 2022 fraction release has unsupported source_unit_status")
    catalog = pd.read_parquet(output / manifest["artifacts"]["catalog"])
    if len(catalog) != 1 or catalog.iloc[0]["dataset_id"] != dataset["dataset_id"]:
        raise ValueError("INDEC 2022 fraction catalog does not identify the release")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize the official INDEC 2022 national census-fraction geography."
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
