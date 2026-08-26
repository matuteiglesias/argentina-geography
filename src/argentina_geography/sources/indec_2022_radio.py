from __future__ import annotations

import argparse
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


def normalize_source(frame: gpd.GeoDataFrame, config: dict) -> tuple[gpd.GeoDataFrame, dict]:
    missing_fields = sorted(set(config["required_fields"]) - set(frame.columns))
    if missing_fields:
        raise ValueError(f"INDEC 2022 radio source is missing required fields: {missing_fields}")
    if frame.crs is None:
        raise ValueError("INDEC 2022 radio source requires an explicit CRS")

    result = frame.copy()
    for field in ("cpr", "cfn", "cro", "cod_indec"):
        width = config["component_widths"][field]
        result[field] = result[field].map(
            lambda value, field=field, width=width: _normalize_digits(value, width, field)
        )
    result["cde"] = result["cde"].map(
        lambda value: _digit_text(
            value, field="cde", max_width=config["source_cde_max_width"]
        )
    )

    if result["cod_indec"].duplicated().any():
        duplicates = sorted(
            result.loc[result["cod_indec"].duplicated(False), "cod_indec"].unique()
        )
        raise ValueError(
            f"INDEC 2022 radio native IDs must be unique; duplicates include {duplicates[:10]}"
        )

    result["department_code"] = result["cod_indec"].str[:5]
    result["fraction_code"] = result["cod_indec"].str[5:7]
    result["radio_code"] = result["cod_indec"].str[7:9]

    warnings = list(config.get("accepted_qa_warnings", []))
    cpr_mismatch = result["cpr"].ne(result["cod_indec"].str[:2])
    cfn_mismatch = result["cfn"].ne(result["fraction_code"])
    cro_mismatch = result["cro"].ne(result["radio_code"])
    cde_cumulative = result["cde"].eq(result["department_code"])
    cde_local = result["cde"].str.zfill(3).eq(result["department_code"].str[2:])
    cde_unclassified = ~(cde_cumulative | cde_local)
    cde_local_count = int(cde_local.sum())
    if cde_local_count:
        warnings.append(
            _warning(
                "mixed_source_cde_representation",
                "Source cde mixes cumulative five-digit and local three-digit department representations; cod_indec remains the authoritative identity.",
                local_representation_count=cde_local_count,
                cumulative_representation_count=int(cde_cumulative.sum()),
            )
        )
    component_mismatch_count = int(
        (cpr_mismatch | cfn_mismatch | cro_mismatch | cde_unclassified).sum()
    )
    if component_mismatch_count:
        warnings.append(
            _warning(
                "supporting_code_disagreement",
                "One or more supporting source code fields disagree with the corresponding slice of cod_indec; rows are retained and cod_indec remains authoritative.",
                affected_rows=component_mismatch_count,
                cpr_mismatch_count=int(cpr_mismatch.sum()),
                cfn_mismatch_count=int(cfn_mismatch.sum()),
                cro_mismatch_count=int(cro_mismatch.sum()),
                cde_unclassified_count=int(cde_unclassified.sum()),
            )
        )

    documented_names = {
        _normalized_name(name) for name in config["documented_adjustment_jurisdictions"]
    }
    name_series = result["jur"].map(_normalized_name)
    documented_codes = set(result.loc[name_series.isin(documented_names), "cpr"].unique())
    if len(documented_codes) != len(documented_names):
        warnings.append(
            _warning(
                "adjustment_jurisdiction_name_drift",
                "Not all documented adjustment jurisdictions were resolved from current source names; zero-coded rows remain classified conservatively.",
                resolved_jurisdiction_count=len(documented_codes),
                documented_jurisdiction_count=len(documented_names),
            )
        )
    zero_code = result["cfn"].eq("00") | result["cro"].eq("00")
    documented_adjustment = zero_code & result["cpr"].isin(documented_codes)
    unclassified_zero = zero_code & ~result["cpr"].isin(documented_codes)
    if unclassified_zero.any():
        warnings.append(
            _warning(
                "unclassified_zero_code",
                "Zero-coded source units occur outside the adjustment cases explicitly documented in current INDEC metadata; no no-data semantics are inferred for them.",
                affected_rows=int(unclassified_zero.sum()),
            )
        )

    missing_geometry = int(result.geometry.isna().sum())
    empty_geometry = int(result.geometry.is_empty.sum())
    areal = result.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    non_areal_geometry = int(
        (result.geometry.notna() & ~result.geometry.is_empty & ~areal).sum()
    )
    if missing_geometry or empty_geometry or non_areal_geometry:
        raise ValueError(
            "INDEC 2022 radio geography has unusable source geometry: "
            f"missing={missing_geometry}, empty={empty_geometry}, non_areal={non_areal_geometry}"
        )
    invalid_mask = ~result.geometry.is_valid
    invalid_geometry = int(invalid_mask.sum())
    if invalid_geometry:
        warnings.append(
            _warning(
                "source_invalid_geometry",
                "Source-invalid polygons are retained without repair and are not marked analytical; downstream spatial relations must exclude them or apply an explicitly governed repair policy.",
                affected_rows=invalid_geometry,
            )
        )

    result["native_id"] = result["cod_indec"]
    result["geo_uid"] = "indec:2022:census:radio:" + result["native_id"]
    result["source_unit_status"] = "ordinary"
    result.loc[documented_adjustment, "source_unit_status"] = "adjustment_no_census_data"
    result.loc[unclassified_zero, "source_unit_status"] = "zero_code_unclassified"
    result["geometry_valid"] = ~invalid_mask
    result["geometry_role"] = "analytical"
    result.loc[invalid_mask, "geometry_role"] = "source_invalid"

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
        "department_code",
        "fraction_code",
        "radio_code",
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
        "stage_decision": "PASS_WITH_WARNINGS" if warnings else "PASS",
        "accepted_warning_count": len(warnings),
        "accepted_warnings": warnings,
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
        "cde_local_representation_count": cde_local_count,
        "supporting_code_disagreement_count": component_mismatch_count,
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
    frame = _read_source(source_path, encoding=config.get("source_encoding"))
    normalized, audit = normalize_source(frame, config)

    output.mkdir(parents=True, exist_ok=True)
    geography_path = output / "geography.parquet"
    normalized.to_parquet(geography_path, index=False)
    content_sha256 = sha256_file(geography_path)
    release_version = _release_version(config, source_sha256)
    geography = GeographySpec(
        provider="indec", version="2022", scheme="census", level="radio"
    )
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
                path=source_path.name, sha256=source_sha256, size_bytes=source_size
            ),
        ),
    )
    qa_state = "YELLOW" if audit["stage_decision"] == "PASS_WITH_WARNINGS" else "GREEN"
    qa_result = QAResult(
        check_id="indec_2022_radio_source_contract",
        state=qa_state,
        message=(
            "Official INDEC 2022 radio source is stageable with recorded non-blocking warnings."
            if qa_state == "YELLOW"
            else "Official INDEC 2022 radio source satisfies the normalized geography boundary."
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
        run_id=f"indec-2022-radio:{source_sha256[:16]}",
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
                "level": "radio",
                "source_release": config["metadata_publication_date"],
                "authority_status": "official",
                "feature_count": audit["feature_count"],
                "analytical_feature_count": audit["analytical_geometry_count"],
                "native_id_fields": "cod_indec",
                "source_code_fields": "cpr,cde,cfn,cro",
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
    if frame["native_id"].ne(frame["cod_indec"]).any():
        raise ValueError("INDEC 2022 radio release native_id must equal authoritative cod_indec")
    if frame["department_code"].ne(frame["cod_indec"].str[:5]).any():
        raise ValueError("INDEC 2022 radio department_code is inconsistent with cod_indec")
    if frame["fraction_code"].ne(frame["cod_indec"].str[5:7]).any():
        raise ValueError("INDEC 2022 radio fraction_code is inconsistent with cod_indec")
    if frame["radio_code"].ne(frame["cod_indec"].str[7:9]).any():
        raise ValueError("INDEC 2022 radio radio_code is inconsistent with cod_indec")
    if frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError("INDEC 2022 radio release contains missing or empty source geometry")
    non_areal = ~frame.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if non_areal.any():
        raise ValueError("INDEC 2022 radio release contains non-areal source geometry")
    analytical = frame["geometry_role"].eq("analytical")
    source_invalid = frame["geometry_role"].eq("source_invalid")
    if (~(analytical | source_invalid)).any():
        raise ValueError("INDEC 2022 radio release has unsupported geometry_role")
    if (~frame.loc[analytical].geometry.is_valid).any():
        raise ValueError("analytical rows must contain valid geometry")
    if frame.loc[source_invalid].geometry.is_valid.any():
        raise ValueError("source_invalid rows must correspond to source-invalid geometry")
    if frame.loc[analytical, "geometry_valid"].ne(True).any():
        raise ValueError("analytical geometry_valid flags are inconsistent")
    if frame.loc[source_invalid, "geometry_valid"].ne(False).any():
        raise ValueError("source-invalid geometry_valid flags are inconsistent")
    allowed_status = {
        "ordinary",
        "adjustment_no_census_data",
        "zero_code_unclassified",
    }
    if not set(frame["source_unit_status"]).issubset(allowed_status):
        raise ValueError("INDEC 2022 radio release has unsupported source_unit_status")
    catalog = pd.read_parquet(output / manifest["artifacts"]["catalog"])
    if len(catalog) != 1 or catalog.iloc[0]["dataset_id"] != dataset["dataset_id"]:
        raise ValueError("INDEC 2022 radio catalog does not identify the materialized release")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize the official INDEC 2022 national census-radio geography."
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
