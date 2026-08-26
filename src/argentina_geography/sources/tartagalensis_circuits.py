from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

import geopandas as gpd
import pandas as pd
from shapely.errors import GEOSException
from shapely.geometry import shape

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
DEFAULT_CONFIG = ROOT / "config/sources/tartagalensis_electoral_circuits.json"
REQUIRED_OUTPUT_FILES = [
    "geography.parquet",
    "geography_catalog.parquet",
    "qa.json",
    "source_metadata.json",
    "limitations.json",
    "manifest.json",
]
VALID_VINTAGES = ("2021", "2025")
ASSIGNED_STATUS = "assigned_circuit"
VALID_SOURCE_STATUSES = {
    ASSIGNED_STATUS,
    "no_data",
    "grey_zone",
    "unassigned_unknown",
    "other_nonstandard",
}
VALID_IDENTITY_STATUSES = {
    "complete_composite",
    "missing_coddepto",
    "nonstandard_source_feature",
}
VALID_GEOMETRY_ROLES = {
    "analytical",
    "source_invalid",
    "source_non_areal_or_zero_area",
    "source_unreadable_geometry",
}
VALID_GEOMETRY_PARSE_STATUSES = {"parsed", "unreadable", "missing"}


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    return read_json(path)


def _district_map(config: dict) -> dict[str, dict]:
    districts = {item["codprov"]: item for item in config["districts"]}
    if len(districts) != 24:
        raise ValueError("Tartagalensis source config must define exactly 24 districts")
    expected = {f"{value:02d}" for value in range(1, 25)}
    if set(districts) != expected:
        raise ValueError(
            "Tartagalensis district coverage config must be codprov 01..24; "
            f"observed={sorted(districts)}"
        )
    return districts


def _raw_url(config: dict, vintage: str, filename: str) -> str:
    return config["raw_url_template"].format(
        repository=config["repository"],
        commit_sha=config["commit_sha"],
        vintage=vintage,
        filename=filename,
    )


def download_vintage(destination: Path, vintage: str, config: dict) -> Path:
    if vintage not in VALID_VINTAGES:
        raise ValueError(f"unsupported Tartagalensis vintage: {vintage}")
    destination.mkdir(parents=True, exist_ok=True)
    for item in _district_map(config).values():
        path = destination / item["filename"]
        request = Request(
            _raw_url(config, vintage, item["filename"]),
            headers={"User-Agent": "argentina-geography/0.1 research-data-client"},
        )
        with urlopen(request, timeout=300) as response, path.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if path.stat().st_size == 0:
            raise ValueError(f"Tartagalensis download returned an empty file: {path.name}")
        if path.read_bytes()[:1] not in {b"{", b"["}:
            raise ValueError(
                f"Tartagalensis response is not GeoJSON-like JSON: {vintage}/{path.name}"
            )
    return destination


def _source_file_records(source_dir: Path, vintage: str, config: dict) -> tuple[list[dict], str]:
    records = []
    for codprov, item in sorted(_district_map(config).items()):
        local_path = source_dir / item["filename"]
        if not local_path.exists():
            raise ValueError(
                "Tartagalensis source snapshot is incomplete; "
                f"missing {vintage}/{item['filename']}"
            )
        source_path = config["source_path_template"].format(
            vintage=vintage, filename=item["filename"]
        )
        records.append(
            {
                "codprov": codprov,
                "path": source_path,
                "filename": item["filename"],
                "sha256": sha256_file(local_path),
                "size_bytes": local_path.stat().st_size,
            }
        )
    payload = json.dumps(
        [
            {"path": item["path"], "sha256": item["sha256"], "size_bytes": item["size_bytes"]}
            for item in records
        ],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return records, hashlib.sha256(payload).hexdigest()



def _canonical_geometry_payload(geometry_payload: object) -> tuple[str, str]:
    canonical = json.dumps(
        geometry_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _assert_geojson_wgs84(document: dict, source_label: str) -> None:
    crs = document.get("crs")
    if crs is None:
        return
    crs_text = json.dumps(crs, ensure_ascii=False, sort_keys=True).upper()
    if "4326" not in crs_text and "CRS84" not in crs_text:
        raise ValueError(
            f"Tartagalensis source CRS drift detected for {source_label}: {crs}"
        )


def _read_vintage_source(source_dir: Path, vintage: str, config: dict) -> gpd.GeoDataFrame:
    rows: list[dict] = []
    expected_properties = set(config["source_schema"]) - {"geometry"}

    for codprov, item in sorted(_district_map(config).items()):
        path = source_dir / item["filename"]
        document = json.loads(path.read_text(encoding="utf-8"))
        source_label = f"{vintage}/{item['filename']}"
        if document.get("type") != "FeatureCollection":
            raise ValueError(f"Tartagalensis source is not a FeatureCollection: {source_label}")
        _assert_geojson_wgs84(document, source_label)
        features = document.get("features")
        if not isinstance(features, list) or not features:
            raise ValueError(f"Tartagalensis source has no feature list: {source_label}")

        for source_feature_index, feature in enumerate(features):
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise ValueError(
                    f"Tartagalensis source contains a non-Feature at "
                    f"{source_label}#{source_feature_index}"
                )
            properties = feature.get("properties")
            if not isinstance(properties, dict) or set(properties) != expected_properties:
                observed = (
                    sorted(properties)
                    if isinstance(properties, dict)
                    else type(properties).__name__
                )
                raise ValueError(
                    "Tartagalensis source schema drift detected for "
                    f"{source_label}#{source_feature_index}: "
                    f"expected properties={sorted(expected_properties)}, observed={observed}"
                )
            observed_codprov = properties.get("codprov")
            if observed_codprov != codprov:
                raise ValueError(
                    f"{source_label} must contain only codprov={codprov}; "
                    f"observed={observed_codprov!r} at feature {source_feature_index}"
                )

            geometry_payload = feature.get("geometry")
            geometry_json, geometry_sha256 = _canonical_geometry_payload(geometry_payload)
            geometry_type = (
                geometry_payload.get("type")
                if isinstance(geometry_payload, dict)
                else None
            )
            parsed_geometry = None
            parse_status = "missing"
            parse_error = None
            if geometry_payload is not None:
                try:
                    parsed_geometry = shape(geometry_payload)
                    parse_status = "parsed"
                except (GEOSException, ValueError, TypeError) as exc:
                    parse_status = "unreadable"
                    parse_error = f"{type(exc).__name__}: {exc}"

            rows.append(
                {
                    "circuito": properties["circuito"],
                    "codprov": properties["codprov"],
                    "coddepto": properties["coddepto"],
                    "source_path": source_label,
                    "source_feature_index": source_feature_index,
                    "source_geometry_type": geometry_type,
                    "source_geometry_sha256": geometry_sha256,
                    "source_geometry_parse_status": parse_status,
                    "source_geometry_parse_error": parse_error,
                    "source_geometry_json": (
                        geometry_json if parse_status != "parsed" else None
                    ),
                    "geometry": parsed_geometry,
                }
            )

    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _required_string(value: object, field: str) -> str:
    if pd.isna(value):
        raise ValueError(f"{field} must be non-missing")
    if not isinstance(value, str):
        raise TypeError(f"{field} must remain a source string; observed {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    return text


def _optional_department(value: object) -> str | None:
    if pd.isna(value):
        return None
    if not isinstance(value, str):
        raise TypeError(
            "coddepto must remain a three-digit source string or null; "
            f"observed {type(value).__name__}"
        )
    text = value.strip()
    if not text.isascii() or not text.isdigit() or len(text) != 3:
        raise ValueError(f"coddepto must be exactly three ASCII digits or null: {value!r}")
    return text


def _source_status(circuito: str, config: dict) -> str:
    lowered = circuito.casefold()
    documented = config["nonstandard_status_map"].get(lowered)
    if documented is not None:
        return documented
    if circuito[0].isdigit():
        return ASSIGNED_STATUS
    return "other_nonstandard"


def _native_id(codprov: str, coddepto: str | None, circuito: str) -> str:
    department = coddepto if coddepto is not None else "<missing>"
    return f"{codprov}|{department}|{circuito}"



def _feature_uid(
    vintage: str,
    source_path: str,
    codprov: str,
    coddepto: str | None,
    circuito: str,
    source_geometry_sha256: str,
) -> str:
    payload = {
        "vintage": vintage,
        "source_path": source_path,
        "codprov": codprov,
        "coddepto": coddepto,
        "circuito": circuito,
        "source_geometry_sha256": source_geometry_sha256,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return f"tartagalensis:{vintage}:feature:{digest[:24]}"


def _warning(code: str, message: str, **metrics: object) -> dict:
    item = {"code": code, "stage_decision": "PASS_WITH_WARNINGS", "message": message}
    if metrics:
        item["metrics"] = metrics
    return item


def normalize_source(
    frame: gpd.GeoDataFrame,
    vintage: str,
    config: dict,
) -> tuple[gpd.GeoDataFrame, dict]:
    if vintage not in VALID_VINTAGES:
        raise ValueError(f"unsupported Tartagalensis vintage: {vintage}")
    expected_columns = {
        "circuito",
        "codprov",
        "coddepto",
        "source_path",
        "source_feature_index",
        "source_geometry_type",
        "source_geometry_sha256",
        "source_geometry_parse_status",
        "source_geometry_parse_error",
        "source_geometry_json",
        "geometry",
    }
    missing_columns = sorted(expected_columns - set(frame.columns))
    if missing_columns:
        raise ValueError(f"Tartagalensis normalized input is missing columns: {missing_columns}")
    expected_epsg = int(config["expected_crs_epsg"])
    if frame.crs is None or frame.crs.to_epsg() != expected_epsg:
        raise ValueError(f"Tartagalensis {vintage} normalized source must use EPSG:{expected_epsg}")

    result = frame.copy()
    result["codprov"] = result["codprov"].map(lambda value: _required_string(value, "codprov"))
    invalid_province = ~result["codprov"].str.fullmatch(r"\d{2}", na=False)
    if invalid_province.any():
        values = sorted(result.loc[invalid_province, "codprov"].unique().tolist())
        raise ValueError(f"codprov must be exactly two ASCII digits: {values[:10]}")

    result["circuito"] = result["circuito"].map(
        lambda value: _required_string(value, "circuito")
    )
    result["coddepto"] = result["coddepto"].map(_optional_department)

    expected_districts = set(_district_map(config))
    observed_districts = set(result["codprov"].unique().tolist())
    if observed_districts != expected_districts:
        raise ValueError(
            f"Tartagalensis {vintage} must cover all 24 districts; "
            f"missing={sorted(expected_districts - observed_districts)}, "
            f"unexpected={sorted(observed_districts - expected_districts)}"
        )

    parsed_geometry = result["source_geometry_parse_status"].eq("parsed")
    unexpected_null = parsed_geometry & result.geometry.isna()
    if unexpected_null.any():
        raise ValueError(
            "Tartagalensis parsed source geometry unexpectedly became null: "
            f"affected_rows={int(unexpected_null.sum())}"
        )
    result["source_status"] = result["circuito"].map(
        lambda value: _source_status(value, config)
    )
    result["identity_status"] = "nonstandard_source_feature"
    assigned = result["source_status"].eq(ASSIGNED_STATUS)
    result.loc[assigned & result["coddepto"].notna(), "identity_status"] = "complete_composite"
    result.loc[assigned & result["coddepto"].isna(), "identity_status"] = "missing_coddepto"

    result["native_id"] = [
        _native_id(codprov, coddepto, circuito)
        for codprov, coddepto, circuito in zip(
            result["codprov"], result["coddepto"], result["circuito"], strict=True
        )
    ]
    result["circuit_uid"] = pd.Series(pd.NA, index=result.index, dtype="string")
    complete_identity = result["identity_status"].eq("complete_composite")
    result.loc[complete_identity, "circuit_uid"] = [
        f"tartagalensis:{vintage}:circuit:{codprov}:{coddepto}:{circuito}"
        for codprov, coddepto, circuito in zip(
            result.loc[complete_identity, "codprov"],
            result.loc[complete_identity, "coddepto"],
            result.loc[complete_identity, "circuito"],
            strict=True,
        )
    ]

    result["geo_uid"] = [
        _feature_uid(
            vintage,
            source_path,
            codprov,
            coddepto,
            circuito,
            source_geometry_sha256,
        )
        for source_path, codprov, coddepto, circuito, source_geometry_sha256 in zip(
            result["source_path"],
            result["codprov"],
            result["coddepto"],
            result["circuito"],
            result["source_geometry_sha256"],
            strict=True,
        )
    ]
    if result["geo_uid"].duplicated().any():
        duplicates = sorted(result.loc[result["geo_uid"].duplicated(False), "geo_uid"].unique())
        raise ValueError(
            "Tartagalensis source contains feature-identical duplicate rows that cannot be "
            f"given row-order-independent geo_uid values: {duplicates[:10]}"
        )

    readable = result["source_geometry_parse_status"].eq("parsed")
    valid_mask = pd.Series(False, index=result.index)
    valid_mask.loc[readable] = result.loc[readable].geometry.is_valid
    invalid_mask = readable & (~valid_mask)
    positive_area = pd.Series(False, index=result.index)
    positive_area.loc[readable] = result.loc[readable].geometry.map(
        lambda geometry: bool(geometry.area > 0)
    )
    result["geometry_valid"] = pd.Series(pd.NA, index=result.index, dtype="boolean")
    result.loc[readable, "geometry_valid"] = valid_mask.loc[readable].astype(bool)
    result["geometry_role"] = "source_unreadable_geometry"
    result.loc[readable & valid_mask & positive_area, "geometry_role"] = "analytical"
    result.loc[invalid_mask, "geometry_role"] = "source_invalid"
    result.loc[
        readable & valid_mask & (~positive_area), "geometry_role"
    ] = "source_non_areal_or_zero_area"

    result["reconstruction_status"] = config["reconstruction_status"]
    result["authority_status"] = config["authority_status"]

    standard = result["source_status"].eq(ASSIGNED_STATUS)
    expected_counts = config["vintages"][vintage]["expected_unique_standard_circuits"]
    observed_counts = (
        result.loc[standard].groupby("codprov")["circuito"].nunique().astype(int).to_dict()
    )
    count_mismatches = {
        codprov: {
            "expected": int(expected_counts[codprov]),
            "observed": observed_counts.get(codprov, 0),
        }
        for codprov in sorted(expected_counts)
        if observed_counts.get(codprov, 0) != int(expected_counts[codprov])
    }
    if count_mismatches:
        raise ValueError(
            f"Tartagalensis {vintage} unique standard circuit counts drifted: "
            f"{count_mismatches}"
        )

    code_province_counts = (
        result.loc[standard].groupby("circuito")["codprov"].nunique().sort_index()
    )
    collision_codes = code_province_counts[code_province_counts > 1]
    if collision_codes.empty:
        raise ValueError(
            "Tartagalensis source no longer proves that circuito alone repeats across districts; "
            "composite identity assumptions require re-review"
        )

    status_counts = Counter(result["source_status"].tolist())
    identity_counts = Counter(result["identity_status"].tolist())
    geometry_role_counts = Counter(result["geometry_role"].tolist())
    geometry_types = sorted(
        {value for value in result.loc[readable].geom_type.tolist() if value is not None}
    )
    source_geometry_types = sorted(
        {
            str(value)
            for value in result["source_geometry_type"].dropna().unique().tolist()
        }
    )
    null_coddepto = int(result["coddepto"].isna().sum())

    expected_documented_nulls = config["vintages"][vintage].get(
        "documented_null_coddepto_features"
    )
    if expected_documented_nulls is not None and null_coddepto != int(expected_documented_nulls):
        raise ValueError(
            f"Tartagalensis {vintage} coddepto-null count drifted: "
            f"expected={expected_documented_nulls}, observed={null_coddepto}"
        )

    qa_warnings: list[dict] = []
    nonstandard_count = int((~standard).sum())
    if nonstandard_count:
        qa_warnings.append(
            _warning(
                "documented_nonstandard_source_features",
                "No-data, grey-zone or other nonstandard source polygons are retained with "
                "explicit source_status rather than filtered.",
                affected_rows=nonstandard_count,
                source_status_counts=dict(sorted(status_counts.items())),
            )
        )
    if null_coddepto:
        qa_warnings.append(
            _warning(
                "source_missing_coddepto",
                "Source rows with missing coddepto are retained with incomplete composite "
                "identity rather than imputed.",
                affected_rows=null_coddepto,
            )
        )
    unreadable_count = int((~readable).sum())
    if unreadable_count:
        unreadable_sample = (
            result.loc[
                ~readable,
                [
                    "source_path",
                    "source_feature_index",
                    "source_geometry_type",
                    "source_geometry_parse_error",
                ],
            ]
            .head(20)
            .to_dict(orient="records")
        )
        qa_warnings.append(
            _warning(
                "source_unreadable_geometry",
                "Source geometry that GEOS cannot construct is retained as a source feature "
                "with exact canonical geometry JSON/hash and null analytical geometry.",
                affected_rows=unreadable_count,
                sample=unreadable_sample,
            )
        )
    invalid_count = int(invalid_mask.sum())
    if invalid_count:
        qa_warnings.append(
            _warning(
                "source_invalid_geometry",
                "Source-invalid geometries are retained without repair and excluded from the "
                "analytical geometry role.",
                affected_rows=invalid_count,
            )
        )
    zero_area_count = int((readable & valid_mask & (~positive_area)).sum())
    if zero_area_count:
        qa_warnings.append(
            _warning(
                "source_non_areal_or_zero_area_geometry",
                "Valid source geometries with no areal component are retained and marked "
                "non-analytical.",
                affected_rows=zero_area_count,
            )
        )

    per_district: dict[str, dict] = {}
    for codprov in sorted(expected_districts):
        subset = result[result["codprov"].eq(codprov)]
        standard_subset = subset[subset["source_status"].eq(ASSIGNED_STATUS)]
        per_district[codprov] = {
            "feature_count": len(subset),
            "unique_standard_circuit_count": int(standard_subset["circuito"].nunique()),
            "nonstandard_feature_count": int(
                (~subset["source_status"].eq(ASSIGNED_STATUS)).sum()
            ),
            "null_coddepto_feature_count": int(subset["coddepto"].isna().sum()),
            "geometry_types": sorted(
                {
                    value
                    for value in subset.loc[
                        subset["source_geometry_parse_status"].eq("parsed")
                    ].geom_type.tolist()
                    if value is not None
                }
            ),
            "unreadable_geometry_count": int(
                (~subset["source_geometry_parse_status"].eq("parsed")).sum()
            ),
        }

    audit = {
        "stage_decision": "PASS_WITH_WARNINGS" if qa_warnings else "PASS",
        "accepted_warning_count": len(qa_warnings),
        "accepted_warnings": qa_warnings,
        "vintage": vintage,
        "feature_count": len(result),
        "district_count": int(result["codprov"].nunique()),
        "district_codes": sorted(result["codprov"].unique().tolist()),
        "unique_standard_circuit_count": int(sum(observed_counts.values())),
        "complete_composite_circuit_count": int(
            result.loc[complete_identity, "circuit_uid"].nunique()
        ),
        "multipart_complete_circuit_count": int(
            result.loc[complete_identity, "circuit_uid"].value_counts().gt(1).sum()
        ),
        "circuit_code_cross_district_collision_count": len(collision_codes),
        "circuit_code_cross_district_collision_sample": collision_codes.head(20)
        .astype(int)
        .to_dict(),
        "source_status_counts": dict(sorted(status_counts.items())),
        "identity_status_counts": dict(sorted(identity_counts.items())),
        "null_coddepto_feature_count": null_coddepto,
        "geometry_types": geometry_types,
        "source_geometry_types": source_geometry_types,
        "geometry_role_counts": dict(sorted(geometry_role_counts.items())),
        "unreadable_geometry_count": unreadable_count,
        "invalid_geometry_count": invalid_count,
        "non_areal_or_zero_area_geometry_count": zero_area_count,
        "crs": result.crs.to_string(),
        "bbox": [float(value) for value in result.total_bounds.tolist()],
        "per_district": per_district,
        "geometry_repair_applied": False,
        "reconstruction_status": config["reconstruction_status"],
    }

    columns = [
        "geo_uid",
        "native_id",
        "circuit_uid",
        "codprov",
        "coddepto",
        "circuito",
        "source_status",
        "identity_status",
        "reconstruction_status",
        "authority_status",
        "source_path",
        "source_feature_index",
        "source_geometry_type",
        "source_geometry_sha256",
        "source_geometry_parse_status",
        "source_geometry_parse_error",
        "source_geometry_json",
        "geometry_valid",
        "geometry_role",
        result.geometry.name,
    ]
    result = result[columns].sort_values(
        ["codprov", "circuito", "coddepto", "geo_uid"],
        na_position="last",
        ignore_index=True,
    )
    return result, audit


def _release_version(config: dict, vintage: str, snapshot_sha256: str) -> str:
    return f"{vintage}-{config['commit_sha'][:12]}-{snapshot_sha256[:12]}"


def _geography_id(config: dict, vintage: str) -> str:
    return (
        f"tartagalensis:electoral:{config['commit_sha']}:{vintage}:circuit"
    )


def _dataset_id(vintage: str) -> str:
    return f"arggeo.tartagalensis.electoral.{vintage}.circuit"


def materialize_from_source_dir(
    source_dir: Path,
    output: Path,
    vintage: str,
    config_path: Path = DEFAULT_CONFIG,
) -> dict:
    config = load_config(config_path)
    if vintage not in config["vintages"]:
        raise ValueError(f"vintage is not configured: {vintage}")

    file_records, source_snapshot_sha256 = _source_file_records(source_dir, vintage, config)
    frame = _read_vintage_source(source_dir, vintage, config)
    normalized, audit = normalize_source(frame, vintage, config)

    output.mkdir(parents=True, exist_ok=True)
    geography_path = output / "geography.parquet"
    normalized.to_parquet(geography_path, index=False)
    content_sha256 = sha256_file(geography_path)
    release_version = _release_version(config, vintage, source_snapshot_sha256)
    geography_id = _geography_id(config, vintage)

    geography = GeographySpec(
        provider="tartagalensis",
        version=f"{vintage}-{config['commit_sha'][:12]}",
        scheme="electoral",
        level="circuit",
    )
    dataset = DatasetRef(
        dataset_id=_dataset_id(vintage),
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
        release=f"{config['dataset_version']}@{config['commit_sha']}:{vintage}",
        snapshot_id=f"sha256:{source_snapshot_sha256}",
        origin=f"{config['repository_url']}/tree/{config['commit_sha']}/{vintage}",
        storage_mode="external_immutable",
        files=tuple(
            SourceFileRef(
                path=item["path"],
                sha256=item["sha256"],
                size_bytes=item["size_bytes"],
            )
            for item in file_records
        ),
    )

    qa_state = "YELLOW" if audit["stage_decision"] == "PASS_WITH_WARNINGS" else "GREEN"
    qa_result = QAResult(
        check_id=f"tartagalensis_{vintage}_circuit_source_contract",
        state=qa_state,
        message=(
            f"Tartagalensis {vintage} circuit geography is stageable with documented "
            "source limitations."
            if qa_state == "YELLOW"
            else f"Tartagalensis {vintage} circuit geography satisfies the normalized boundary."
        ),
        metrics={
            "feature_count": audit["feature_count"],
            "district_count": audit["district_count"],
            "unique_standard_circuit_count": audit["unique_standard_circuit_count"],
            "circuit_code_cross_district_collision_count": audit[
                "circuit_code_cross_district_collision_count"
            ],
            "unreadable_geometry_count": audit["unreadable_geometry_count"],
            "invalid_geometry_count": audit["invalid_geometry_count"],
            "null_coddepto_feature_count": audit["null_coddepto_feature_count"],
            "accepted_warning_count": audit["accepted_warning_count"],
            "crs": audit["crs"],
        },
    )
    now = datetime.now(UTC)
    run = RunManifest(
        run_id=f"tartagalensis-circuits-{vintage}:{source_snapshot_sha256[:16]}",
        package="argentina-geography",
        package_version=package_version(),
        started_at=now,
        finished_at=now,
        inputs=(source_snapshot,),
        parameters={
            "source_repository": config["repository"],
            "source_commit_sha": config["commit_sha"],
            "source_tree_sha": config["vintages"][vintage]["tree_sha"],
            "source_paths": [item["path"] for item in file_records],
            "distribution_mode": config["distribution_mode"],
            "native_identity_fields": config["native_id_fields"],
            "row_grain": "source_feature",
            "logical_circuit_identity": "codprov+coddepto+circuito when complete and assigned",
            "circuito_global_uniqueness_assumed": False,
            "geometry_repair_applied": False,
            "reconstruction_status": config["reconstruction_status"],
            "stage_decision": audit["stage_decision"],
            "license_name": config["license_name"],
            "license_url": config["license_url"],
            "citation": config["citation"],
        },
        outputs=(dataset,),
        qa=(qa_result,),
    )

    source_metadata = {
        "source_id": config["source_id"],
        "resource_title": config["resource_title"],
        "repository": config["repository"],
        "repository_url": config["repository_url"],
        "commit_sha": config["commit_sha"],
        "tree_sha": config["vintages"][vintage]["tree_sha"],
        "vintage": vintage,
        "source_paths": [item["path"] for item in file_records],
        "source_files": file_records,
        "source_snapshot_sha256": source_snapshot_sha256,
        "received_crs": audit["crs"],
        "native_identity_fields": config["native_id_fields"],
        "source_schema": config["source_schema"],
        "citation_cff_path": config["citation_cff_path"],
        "citation_cff_blob_sha": config["citation_cff_blob_sha"],
        "license_path": config["license_path"],
        "license_blob_sha": config["license_blob_sha"],
        "readme_blob_sha": config["readme_blob_sha"],
        "license_name": config["license_name"],
        "license_url": config["license_url"],
        "attribution": config["attribution"],
        "citation": config["citation"],
    }
    limitations = {
        "geography_id": geography_id,
        "dataset_id": dataset.dataset_id,
        "release_version": release_version,
        "items": config["known_limitations"],
        "accepted_qa_warnings": audit["accepted_warnings"],
        "source_status_vocabulary": {
            ASSIGNED_STATUS: "Source row carries a circuit code beginning with a digit.",
            "no_data": "Source marker explicitly indicates no circuit data/assignment.",
            "grey_zone": "Source marker explicitly identifies a grey-zone polygon.",
            "unassigned_unknown": (
                "Source marker indicates territory with unknown/unassigned circuit."
            ),
            "other_nonstandard": "Non-digit source marker not in the documented marker vocabulary.",
        },
        "reconstruction_status": config["reconstruction_status"],
        "reconstruction_evidence": config["reconstruction_evidence"],
        "unreadable_geometry_policy": (
            "Rows whose source geometry cannot be constructed by GEOS are retained with "
            "source_geometry_json/source_geometry_sha256, null canonical geometry, and "
            "geometry_role=source_unreadable_geometry. No repair is applied."
        ),
        "cross_vintage_equivalence_published": False,
        "attribution": config["attribution"],
        "citation": config["citation"],
        "license_name": config["license_name"],
        "license_url": config["license_url"],
    }

    catalog = pd.DataFrame(
        [
            {
                "geography_id": geography_id,
                "dataset_id": dataset.dataset_id,
                "release_version": dataset.version,
                "schema_version": dataset.schema_version,
                "provider": "tartagalensis",
                "scheme": "electoral",
                "vintage": vintage,
                "level": "circuit",
                "source_release": f"{config['dataset_version']}@{config['commit_sha']}",
                "authority_status": config["authority_status"],
                "feature_count": audit["feature_count"],
                "logical_circuit_count": audit["complete_composite_circuit_count"],
                "native_id_fields": ",".join(config["native_id_fields"]),
                "row_grain": "source_feature",
                "geometry_types": ",".join(audit["geometry_types"]),
                "source_geometry_types": ",".join(audit["source_geometry_types"]),
                "unreadable_geometry_count": audit["unreadable_geometry_count"],
                "storage_crs": audit["crs"],
                "coverage_status": "24_districts_source_as_pinned",
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
        "geography_id": geography_id,
        "authority_status": config["authority_status"],
        "distribution_mode": config["distribution_mode"],
        "stage_decision": audit["stage_decision"],
        "vintage": vintage,
        "source_commit_sha": config["commit_sha"],
        "source_tree_sha": config["vintages"][vintage]["tree_sha"],
        "source_snapshot_sha256": source_snapshot_sha256,
        "dataset": dataset.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "row_count": len(normalized),
        "logical_circuit_count": audit["complete_composite_circuit_count"],
        "source_snapshot": source_snapshot.model_dump(mode="json"),
        "license": {
            "name": config["license_name"],
            "url": config["license_url"],
            "attribution": config["attribution"],
        },
        "citation": config["citation"],
        "cross_vintage_equivalence_published": False,
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
    vintage: str,
    *,
    source_dir: Path | None = None,
    config_path: Path = DEFAULT_CONFIG,
) -> dict:
    config = load_config(config_path)
    if source_dir is not None:
        return materialize_from_source_dir(source_dir, output, vintage, config_path)
    with tempfile.TemporaryDirectory(prefix=f"arggeo-tartagalensis-{vintage}-") as temporary:
        downloaded = Path(temporary) / vintage
        download_vintage(downloaded, vintage, config)
        return materialize_from_source_dir(downloaded, output, vintage, config_path)


def _expected_feature_uid(row: pd.Series, vintage: str) -> str:
    coddepto = None if pd.isna(row["coddepto"]) else str(row["coddepto"])
    return _feature_uid(
        vintage,
        str(row["source_path"]),
        str(row["codprov"]),
        coddepto,
        str(row["circuito"]),
        str(row["source_geometry_sha256"]),
    )


def verify_release(output: Path, config_path: Path = DEFAULT_CONFIG) -> None:
    config = load_config(config_path)
    verify_checksums(output)
    manifest = validate_manifest(output / "manifest.json")
    vintage = manifest.get("vintage")
    if vintage not in config["vintages"]:
        raise ValueError(f"Tartagalensis manifest has unsupported vintage: {vintage}")

    dataset = manifest["dataset"]
    geography_path = output / manifest["artifacts"]["geography"]
    frame = gpd.read_parquet(geography_path)
    if len(frame) != manifest["row_count"]:
        raise ValueError("Tartagalensis release row count does not match manifest")
    if sha256_file(geography_path) != dataset["content_sha256"]:
        raise ValueError("Tartagalensis geography content hash mismatch")
    if dataset["dataset_id"] != _dataset_id(vintage):
        raise ValueError("Tartagalensis dataset_id changed unexpectedly")
    if manifest.get("geography_id") != _geography_id(config, vintage):
        raise ValueError("Tartagalensis geography_id changed unexpectedly")
    if manifest.get("source_commit_sha") != config["commit_sha"]:
        raise ValueError("Tartagalensis source commit is not the pinned commit")
    if manifest.get("source_tree_sha") != config["vintages"][vintage]["tree_sha"]:
        raise ValueError("Tartagalensis source tree identity changed unexpectedly")
    if manifest.get("cross_vintage_equivalence_published") is not False:
        raise ValueError("A8 must not publish cross-vintage circuit equivalence")

    required = {
        "geo_uid",
        "native_id",
        "circuit_uid",
        "codprov",
        "coddepto",
        "circuito",
        "source_status",
        "identity_status",
        "reconstruction_status",
        "authority_status",
        "source_path",
        "source_feature_index",
        "source_geometry_type",
        "source_geometry_sha256",
        "source_geometry_parse_status",
        "source_geometry_parse_error",
        "source_geometry_json",
        "geometry_valid",
        "geometry_role",
        "geometry",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Tartagalensis release is missing required columns: {missing}")
    if frame["geo_uid"].isna().any() or frame["geo_uid"].duplicated().any():
        raise ValueError("Tartagalensis geo_uid must be non-missing and unique")
    if not set(frame["source_status"]).issubset(VALID_SOURCE_STATUSES):
        raise ValueError("Tartagalensis release has unsupported source_status")
    if not set(frame["identity_status"]).issubset(VALID_IDENTITY_STATUSES):
        raise ValueError("Tartagalensis release has unsupported identity_status")
    if not set(frame["geometry_role"]).issubset(VALID_GEOMETRY_ROLES):
        raise ValueError("Tartagalensis release has unsupported geometry_role")
    if not set(frame["source_geometry_parse_status"]).issubset(VALID_GEOMETRY_PARSE_STATUSES):
        raise ValueError("Tartagalensis release has unsupported geometry parse status")
    if not frame["reconstruction_status"].eq(config["reconstruction_status"]).all():
        raise ValueError(
            "Tartagalensis feature-level reconstruction status was invented or changed"
        )
    if not frame["authority_status"].eq(config["authority_status"]).all():
        raise ValueError("Tartagalensis authority status changed unexpectedly")

    expected_districts = set(_district_map(config))
    if set(frame["codprov"].unique()) != expected_districts:
        raise ValueError("Tartagalensis detached release no longer covers all 24 districts")
    expected_path_prefix = f"{vintage}/"
    if not frame["source_path"].astype(str).str.startswith(expected_path_prefix).all():
        raise ValueError("Tartagalensis source paths no longer identify the release vintage")

    expected_native = [
        _native_id(
            str(row.codprov),
            None if pd.isna(row.coddepto) else str(row.coddepto),
            str(row.circuito),
        )
        for row in frame.itertuples()
    ]
    if frame["native_id"].tolist() != expected_native:
        raise ValueError("Tartagalensis native_id no longer preserves codprov/coddepto/circuito")

    assigned = frame["source_status"].eq(ASSIGNED_STATUS)
    complete = assigned & frame["coddepto"].notna()
    incomplete = assigned & frame["coddepto"].isna()
    nonstandard = ~assigned
    if not frame.loc[complete, "identity_status"].eq("complete_composite").all():
        raise ValueError("complete Tartagalensis composite identities have wrong status")
    if not frame.loc[incomplete, "identity_status"].eq("missing_coddepto").all():
        raise ValueError("Tartagalensis missing coddepto rows have wrong identity status")
    if not frame.loc[nonstandard, "identity_status"].eq("nonstandard_source_feature").all():
        raise ValueError("Tartagalensis nonstandard rows have wrong identity status")
    expected_circuit_uids = (
        "tartagalensis:"
        + vintage
        + ":circuit:"
        + frame.loc[complete, "codprov"].astype(str)
        + ":"
        + frame.loc[complete, "coddepto"].astype(str)
        + ":"
        + frame.loc[complete, "circuito"].astype(str)
    )
    if frame.loc[complete, "circuit_uid"].astype(str).tolist() != expected_circuit_uids.tolist():
        raise ValueError("Tartagalensis circuit_uid no longer preserves the complete composite key")
    if frame.loc[~complete, "circuit_uid"].notna().any():
        raise ValueError("incomplete/nonstandard Tartagalensis rows must not invent circuit_uid")

    expected_geo_uids = frame.apply(
        lambda row: _expected_feature_uid(row, vintage), axis=1
    )
    if frame["geo_uid"].tolist() != expected_geo_uids.tolist():
        raise ValueError(
            "Tartagalensis geo_uid is no longer deterministic from source feature content"
        )

    readable = frame["source_geometry_parse_status"].eq("parsed")
    unreadable = ~readable
    if frame.loc[readable].geometry.isna().any():
        raise ValueError("readable Tartagalensis source geometry became missing")
    if frame.loc[unreadable].geometry.notna().any():
        raise ValueError("unreadable Tartagalensis source geometry must remain null analytically")
    if frame.loc[unreadable, "source_geometry_json"].isna().any():
        raise ValueError("unreadable Tartagalensis geometry must preserve canonical source JSON")
    for row in frame.loc[unreadable].itertuples():
        geometry_hash = hashlib.sha256(str(row.source_geometry_json).encode("utf-8")).hexdigest()
        if geometry_hash != row.source_geometry_sha256:
            raise ValueError("unreadable Tartagalensis source geometry hash does not match payload")
    valid = pd.Series(False, index=frame.index)
    valid.loc[readable] = frame.loc[readable].geometry.is_valid
    positive_area = pd.Series(False, index=frame.index)
    positive_area.loc[readable] = frame.loc[readable].geometry.map(
        lambda geometry: bool(geometry.area > 0)
    )
    if not frame.loc[readable & valid & positive_area, "geometry_role"].eq("analytical").all():
        raise ValueError("valid areal Tartagalensis source features must be analytical")
    if not frame.loc[readable & (~valid), "geometry_role"].eq("source_invalid").all():
        raise ValueError("invalid Tartagalensis source features must remain source_invalid")
    if not frame.loc[
        readable & valid & (~positive_area), "geometry_role"
    ].eq("source_non_areal_or_zero_area").all():
        raise ValueError("zero-area Tartagalensis source features have wrong geometry role")
    if not frame.loc[unreadable, "geometry_role"].eq("source_unreadable_geometry").all():
        raise ValueError("unreadable Tartagalensis source geometry has wrong geometry role")
    if frame.loc[unreadable, "geometry_valid"].notna().any():
        raise ValueError("unreadable Tartagalensis source geometry validity must remain unknown")
    if (
        frame.loc[readable, "geometry_valid"].astype(bool).ne(valid.loc[readable]).any()
    ):
        raise ValueError("Tartagalensis geometry_valid disagrees with readable source geometry")

    standard = frame["source_status"].eq(ASSIGNED_STATUS)
    observed_counts = (
        frame.loc[standard].groupby("codprov")["circuito"].nunique().astype(int).to_dict()
    )
    expected_counts = config["vintages"][vintage]["expected_unique_standard_circuits"]
    if observed_counts != {key: int(value) for key, value in expected_counts.items()}:
        raise ValueError("Tartagalensis detached release standard circuit counts changed")

    collision_counts = frame.loc[standard].groupby("circuito")["codprov"].nunique()
    if not (collision_counts > 1).any():
        raise ValueError("Tartagalensis release no longer proves circuit-code non-uniqueness")

    source_metadata = read_json(output / manifest["artifacts"]["source_metadata"])
    if source_metadata["commit_sha"] != config["commit_sha"]:
        raise ValueError("Tartagalensis source metadata is not pinned to the adopted commit")
    if len(source_metadata["source_files"]) != 24:
        raise ValueError("Tartagalensis source metadata must identify 24 source files")
    if source_metadata["source_snapshot_sha256"] != manifest["source_snapshot_sha256"]:
        raise ValueError("Tartagalensis source snapshot identity disagrees across artifacts")

    catalog = pd.read_parquet(output / manifest["artifacts"]["catalog"])
    if len(catalog) != 1:
        raise ValueError("Tartagalensis release catalog must contain exactly one entry")
    row = catalog.iloc[0]
    if row["geography_id"] != manifest["geography_id"]:
        raise ValueError("Tartagalensis catalog geography_id does not identify the release")
    if row["dataset_id"] != dataset["dataset_id"] or row["release_version"] != dataset["version"]:
        raise ValueError("Tartagalensis catalog release identity does not match manifest")
    if row["authority_status"] != "curated_operational":
        raise ValueError("Tartagalensis release must remain curated_operational")
    if row["coverage_status"] != "24_districts_source_as_pinned":
        raise ValueError("Tartagalensis catalog must preserve the 24-district coverage claim")
    if manifest.get("distribution_mode") != "redistributed_snapshot":
        raise ValueError("Tartagalensis distribution boundary changed unexpectedly")


def compatibility_evidence(
    release_2021: Path,
    release_2025: Path,
    output: Path,
    config_path: Path = DEFAULT_CONFIG,
) -> dict:
    config = load_config(config_path)
    verify_release(release_2021, config_path)
    verify_release(release_2025, config_path)
    manifest_2021 = read_json(release_2021 / "manifest.json")
    manifest_2025 = read_json(release_2025 / "manifest.json")
    if manifest_2021["vintage"] != "2021" or manifest_2025["vintage"] != "2025":
        raise ValueError(
            "compatibility evidence requires exact 2021 and 2025 Tartagalensis releases"
        )

    frame_2021 = gpd.read_parquet(release_2021 / "geography.parquet")
    frame_2025 = gpd.read_parquet(release_2025 / "geography.parquet")
    expected_common = config["cross_vintage_code_compatibility_evidence"][
        "expected_common_standard_codes"
    ]
    rows = {}
    for codprov in sorted(_district_map(config)):
        codes_2021 = set(
            frame_2021.loc[
                frame_2021["codprov"].eq(codprov)
                & frame_2021["source_status"].eq(ASSIGNED_STATUS),
                "circuito",
            ]
        )
        codes_2025 = set(
            frame_2025.loc[
                frame_2025["codprov"].eq(codprov)
                & frame_2025["source_status"].eq(ASSIGNED_STATUS),
                "circuito",
            ]
        )
        common_count = len(codes_2021 & codes_2025)
        expected = int(expected_common[codprov])
        if common_count != expected:
            raise ValueError(
                f"Tartagalensis cross-vintage direct-code compatibility drift for {codprov}: "
                f"expected common count={expected}, observed={common_count}"
            )
        rows[codprov] = {
            "codes_2021": len(codes_2021),
            "codes_2025": len(codes_2025),
            "directly_common_codes": common_count,
        }

    evidence = {
        "evidence_type": "aggregate_code_set_compatibility",
        "source_commit_sha": config["commit_sha"],
        "release_2021": {
            "geography_id": manifest_2021["geography_id"],
            "dataset_id": manifest_2021["dataset"]["dataset_id"],
            "release_version": manifest_2021["dataset"]["version"],
            "content_sha256": manifest_2021["dataset"]["content_sha256"],
        },
        "release_2025": {
            "geography_id": manifest_2025["geography_id"],
            "dataset_id": manifest_2025["dataset"]["dataset_id"],
            "release_version": manifest_2025["dataset"]["version"],
            "content_sha256": manifest_2025["dataset"]["content_sha256"],
        },
        "districts": rows,
        "documented_rename_warning_districts": config[
            "cross_vintage_code_compatibility_evidence"
        ]["documented_rename_warning_districts"],
        "equivalence_rows_published": False,
        "interpretation": (
            "Counts report only literal circuit-code set intersection within each district. "
            "They are evidence about direct code compatibility, not a circuit equivalence, "
            "crosswalk or relation."
        ),
    }
    write_json(output, evidence)
    return evidence


def _identity_record(release: Path) -> dict:
    manifest = read_json(release / "manifest.json")
    return {
        "geography_id": manifest["geography_id"],
        "dataset_id": manifest["dataset"]["dataset_id"],
        "release_version": manifest["dataset"]["version"],
        "source_commit_sha": manifest["source_commit_sha"],
        "source_tree_sha": manifest["source_tree_sha"],
        "source_snapshot_sha256": manifest["source_snapshot_sha256"],
        "content_sha256": manifest["dataset"]["content_sha256"],
    }


def write_release_identities(release_2021: Path, release_2025: Path, output: Path) -> dict:
    identities = {
        "a8_release_identities": {
            "2021": _identity_record(release_2021),
            "2025": _identity_record(release_2025),
        }
    }
    write_json(output, identities)
    return identities


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize pinned Tartagalensis 2021/2025 circuit geographies."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--vintage", choices=VALID_VINTAGES, required=True)
    materialize.add_argument("--output", type=Path, required=True)
    materialize.add_argument("--source-dir", type=Path)
    materialize.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--release", type=Path, required=True)
    verify.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    compatibility = subparsers.add_parser("compatibility-evidence")
    compatibility.add_argument("--release-2021", type=Path, required=True)
    compatibility.add_argument("--release-2025", type=Path, required=True)
    compatibility.add_argument("--output", type=Path, required=True)
    compatibility.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    identities = subparsers.add_parser("release-identities")
    identities.add_argument("--release-2021", type=Path, required=True)
    identities.add_argument("--release-2025", type=Path, required=True)
    identities.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "materialize":
        acquire_and_materialize(
            args.output,
            args.vintage,
            source_dir=args.source_dir,
            config_path=args.config,
        )
        verify_release(args.output, args.config)
    elif args.command == "verify":
        verify_release(args.release, args.config)
    elif args.command == "compatibility-evidence":
        compatibility_evidence(
            args.release_2021,
            args.release_2025,
            args.output,
            args.config,
        )
    else:
        write_release_identities(args.release_2021, args.release_2025, args.output)


if __name__ == "__main__":
    main()
