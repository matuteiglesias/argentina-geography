from __future__ import annotations

import argparse
import hashlib
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
from shapely import union_all

from argentina_geography.product_writer import package_version
from argentina_geography.products import (
    read_json,
    sha256_file,
    validate_manifest,
    verify_checksums,
    write_checksums,
    write_json,
)
from argentina_geography.sources.indec_2010_radio_probe import download_file

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config/sources/indec_census_2010_radio.json"
REQUIRED_OUTPUT_FILES = [
    "geography.parquet",
    "source_components.parquet",
    "geography_catalog.parquet",
    "identity_contract.json",
    "qa.json",
    "source_metadata.json",
    "limitations.json",
    "manifest.json",
]


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    return read_json(path)


def _digit_text(value: object, *, width: int, field: str) -> str:
    if pd.isna(value):
        raise ValueError(f"{field} must be non-missing")
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text.isascii() or not text.isdigit() or len(text) > width:
        raise ValueError(f"{field} must contain at most {width} ASCII digits: {value!r}")
    return text.zfill(width)


def _read_one(path: Path) -> tuple[gpd.GeoDataFrame, str]:
    source = f"zip://{path.resolve()}"
    layers = gpd.list_layers(source)
    if len(layers) != 1:
        records = layers.astype(object).where(layers.notna(), None).to_dict(orient="records")
        raise ValueError(f"INDEC 2010 file must contain one vector layer: {path.name}: {records}")
    layer = str(layers.iloc[0]["name"])
    frame = gpd.read_file(source, layer=layer, engine="pyogrio", use_arrow=True)
    return frame, layer


def _normalize_components(
    frame: gpd.GeoDataFrame, source_spec: dict, layer_name: str
) -> gpd.GeoDataFrame:
    if frame.crs is None:
        raise ValueError(f"INDEC 2010 source requires an explicit CRS: {source_spec['file_name']}")
    if frame.crs.to_string() != "EPSG:22183":
        raise ValueError(
            f"INDEC 2010 source CRS drift for {source_spec['file_name']}: {frame.crs}"
        )

    caba = source_spec["province_code"] == "02"
    required = {"LINK", "PAIS0210_I", "PROV", "DEPTO", "FRAC", "RADIO"} if caba else {"link", "toponimo_i"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"INDEC 2010 source schema drift in {source_spec['file_name']}: {missing}")

    result = frame.copy()
    link_field = "LINK" if caba else "link"
    row_id_field = "PAIS0210_I" if caba else "toponimo_i"
    result["radio_2010_id"] = result[link_field].map(
        lambda value: _digit_text(value, width=9, field=link_field)
    )
    result["department_2010_id"] = result["radio_2010_id"].str[:5]
    result["province_2010_id"] = result["radio_2010_id"].str[:2]
    result["provider_native_row_id"] = result[row_id_field].map(str)
    result["source_component_id"] = (
        source_spec["province_code"] + ":" + result["provider_native_row_id"]
    )
    result["source_file"] = source_spec["file_name"]
    result["source_layer"] = layer_name
    result["native_link"] = result[link_field].map(str)
    result["native_toponimo_i"] = result["toponimo_i"].map(str) if "toponimo_i" in result else None
    result["native_PAIS0210_I"] = result["PAIS0210_I"].map(str) if "PAIS0210_I" in result else None
    result["native_PROV"] = result["PROV"].map(str) if "PROV" in result else None
    result["native_DEPTO"] = result["DEPTO"].map(str) if "DEPTO" in result else None
    result["native_FRAC"] = result["FRAC"].map(str) if "FRAC" in result else None
    result["native_RADIO"] = result["RADIO"].map(str) if "RADIO" in result else None

    if not result["province_2010_id"].eq(source_spec["province_code"]).all():
        bad = result.loc[
            ~result["province_2010_id"].eq(source_spec["province_code"]),
            ["radio_2010_id", "province_2010_id"],
        ].head(10)
        raise ValueError(
            f"INDEC 2010 province/file identity mismatch in {source_spec['file_name']}: "
            f"{bad.to_dict(orient='records')}"
        )

    if caba:
        prov = result["PROV"].map(lambda value: _digit_text(value, width=2, field="PROV"))
        depto = result["DEPTO"].map(lambda value: _digit_text(value, width=3, field="DEPTO"))
        frac = result["FRAC"].map(lambda value: _digit_text(value, width=2, field="FRAC"))
        radio = result["RADIO"].map(lambda value: _digit_text(value, width=2, field="RADIO"))
        reconstructed = prov + depto + frac + radio
        if not reconstructed.eq(result["radio_2010_id"]).all():
            raise ValueError("CABA LINK disagrees with PROV+DEPTO+FRAC+RADIO")

    geometry = result.geometry
    missing_geometry = int(geometry.isna().sum())
    empty_geometry = int(geometry.is_empty.sum())
    areal = geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    non_areal = int((geometry.notna() & ~geometry.is_empty & ~areal).sum())
    invalid = int((geometry.notna() & ~geometry.is_valid).sum())
    if missing_geometry or empty_geometry or non_areal or invalid:
        raise ValueError(
            "INDEC 2010 source geometry is not safely aggregable without repair: "
            f"file={source_spec['file_name']} missing={missing_geometry} empty={empty_geometry} "
            f"non_areal={non_areal} invalid={invalid}"
        )

    columns = [
        "source_component_id",
        "provider_native_row_id",
        "radio_2010_id",
        "department_2010_id",
        "province_2010_id",
        "source_file",
        "source_layer",
        "native_link",
        "native_toponimo_i",
        "native_PAIS0210_I",
        "native_PROV",
        "native_DEPTO",
        "native_FRAC",
        "native_RADIO",
        result.geometry.name,
    ]
    return result[columns].sort_values("source_component_id", ignore_index=True)


def _aggregate_radios(components: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    rows: list[dict] = []
    for radio_id, group in components.groupby("radio_2010_id", sort=True):
        departments = group["department_2010_id"].unique().tolist()
        provinces = group["province_2010_id"].unique().tolist()
        if len(departments) != 1 or len(provinces) != 1:
            raise ValueError(f"INDEC 2010 radio component identity disagreement: {radio_id}")
        geometry = union_all(group.geometry.tolist())
        if geometry is None or geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"INDEC 2010 radio aggregation produced unusable geometry: {radio_id}")
        if not geometry.is_valid:
            raise ValueError(
                f"INDEC 2010 component aggregation would require geometry repair: {radio_id}"
            )
        native_rows = sorted(group["provider_native_row_id"].astype(str).tolist())
        rows.append(
            {
                "geo_uid": f"indec:census:2010:radio:{radio_id}",
                "radio_2010_id": radio_id,
                "department_2010_id": departments[0],
                "province_2010_id": provinces[0],
                "source_component_count": len(group),
                "provider_native_row_ids": "|".join(native_rows),
                "geometry_valid": True,
                "geometry_role": "analytical",
                "geometry": geometry,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=components.crs)


def _snapshot_sha(file_records: list[dict]) -> str:
    payload = "\n".join(
        f"{item['province_code']}\t{item['file_name']}\t{item['layer_name']}\t"
        f"{item['sha256']}\t{item['size_bytes']}"
        for item in sorted(file_records, key=lambda item: item["province_code"])
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def materialize_from_sources(
    source_dir: Path, output: Path, config_path: Path = DEFAULT_CONFIG
) -> dict:
    config = load_config(config_path)
    component_frames: list[gpd.GeoDataFrame] = []
    file_records: list[dict] = []
    source_refs: list[SourceFileRef] = []

    for source_spec in config["source_files"]:
        source_path = source_dir / source_spec["file_name"]
        if not source_path.exists():
            download_file(source_spec["download_url"], source_path)
        frame, layer_name = _read_one(source_path)
        normalized = _normalize_components(frame, source_spec, layer_name)
        component_frames.append(normalized)
        digest = sha256_file(source_path)
        size = source_path.stat().st_size
        file_records.append(
            {
                "province_code": source_spec["province_code"],
                "province_name": source_spec["province_name"],
                "file_name": source_spec["file_name"],
                "layer_name": layer_name,
                "download_url": source_spec["download_url"],
                "sha256": digest,
                "size_bytes": size,
                "feature_count": len(frame),
                "columns": frame.columns.tolist(),
                "crs": frame.crs.to_string(),
            }
        )
        source_refs.append(SourceFileRef(path=source_spec["file_name"], sha256=digest, size_bytes=size))

    components = gpd.GeoDataFrame(
        pd.concat(component_frames, ignore_index=True), geometry="geometry", crs=component_frames[0].crs
    )
    if components["source_component_id"].duplicated().any():
        raise ValueError("INDEC 2010 provider-native source component IDs are not unique")
    geography = _aggregate_radios(components)
    if geography["radio_2010_id"].duplicated().any():
        raise ValueError("INDEC 2010 consumer radio IDs are not unique after component aggregation")

    duplicate_components = (
        geography.loc[geography["source_component_count"] > 1, [
            "radio_2010_id", "source_component_count", "provider_native_row_ids"
        ]]
        .sort_values("radio_2010_id")
        .to_dict(orient="records")
    )
    snapshot_sha256 = _snapshot_sha(file_records)
    release_version = f"2010-national-{snapshot_sha256[:12]}"

    output.mkdir(parents=True, exist_ok=True)
    geography_path = output / "geography.parquet"
    component_path = output / "source_components.parquet"
    geography.to_parquet(geography_path, index=False)
    components.to_parquet(component_path, index=False)
    content_sha256 = sha256_file(geography_path)

    geography_spec = GeographySpec(provider="indec", version="2010", scheme="census", level="radio")
    dataset = DatasetRef(
        dataset_id="arggeo.indec.census.2010.radio",
        version=release_version,
        schema_version="arggeo.geography/v1",
        layer=DataLayer.SILVER,
        authority=AuthorityLevel.L1_NORMALIZED,
        grain=GrainSpec(keys=("radio_2010_id",)),
        geography=geography_spec,
        content_sha256=content_sha256,
    )
    source_snapshot = SourceSnapshotRef(
        source=config["source_id"],
        release=config["release"],
        snapshot_id=f"sha256:{snapshot_sha256}",
        origin=config["catalog_url"],
        storage_mode="external_immutable",
        files=tuple(source_refs),
    )
    qa = {
        "stage_decision": "PASS",
        "source_component_count": len(components),
        "consumer_radio_count": len(geography),
        "duplicate_radio_component_rows": int(len(components) - len(geography)),
        "multi_component_radio_count": int((geography["source_component_count"] > 1).sum()),
        "multi_component_radios": duplicate_components,
        "province_count": int(geography["province_2010_id"].nunique()),
        "department_count": int(geography["department_2010_id"].nunique()),
        "crs": geography.crs.to_string(),
        "geometry_types": sorted(geography.geom_type.unique().tolist()),
        "missing_geometry_count": int(geography.geometry.isna().sum()),
        "empty_geometry_count": int(geography.geometry.is_empty.sum()),
        "invalid_geometry_count": int((~geography.geometry.is_valid).sum()),
        "bbox": [float(value) for value in geography.total_bounds.tolist()],
    }
    qa_result = QAResult(
        check_id="indec_2010_radio_source_contract",
        state="GREEN",
        message="Official INDEC Census 2010 radio snapshot satisfies the normalized identity/geography boundary.",
        metrics={
            "source_component_count": qa["source_component_count"],
            "consumer_radio_count": qa["consumer_radio_count"],
            "multi_component_radio_count": qa["multi_component_radio_count"],
            "crs": qa["crs"],
        },
    )
    now = datetime.now(UTC)
    run = RunManifest(
        run_id=f"indec-2010-radio:{snapshot_sha256[:16]}",
        package="argentina-geography",
        package_version=package_version(),
        started_at=now,
        finished_at=now,
        inputs=(source_snapshot,),
        parameters={
            "distribution_mode": config["distribution_mode"],
            "source_crs": qa["crs"],
            "consumer_identity_fields": [
                "radio_2010_id", "department_2010_id", "province_2010_id"
            ],
            "component_aggregation": "union source polygon components sharing the same official LINK; source_components.parquet preserves every source row",
            "geometry_repair_applied": False,
        },
        outputs=(dataset,),
        qa=(qa_result,),
    )
    identity_contract = {
        "dataset_id": dataset.dataset_id,
        "release_version": release_version,
        "consumer_fields": {
            "radio_2010_id": "zero-preserving 9-digit INDEC LINK",
            "department_2010_id": "radio_2010_id[0:5]",
            "province_2010_id": "radio_2010_id[0:2]",
        },
        "provider_native_identity": {
            "non_caba": {
                "radio": "link",
                "source_row": "toponimo_i",
            },
            "caba": {
                "radio": "LINK",
                "source_row": "PAIS0210_I",
                "components": "PROV+DEPTO+FRAC+RADIO must equal LINK",
            },
        },
        "source_component_artifact": "source_components.parquet",
        "component_aggregation": duplicate_components,
    }
    source_metadata = {
        "source_id": config["source_id"],
        "provider": config["provider"],
        "authority_status": config["authority_status"],
        "release": config["release"],
        "catalog_url": config["catalog_url"],
        "reference_url": config["reference_url"],
        "license_name": config["license_name"],
        "license_url": config["license_url"],
        "snapshot_sha256": snapshot_sha256,
        "files": file_records,
    }
    limitations = {
        "dataset_id": dataset.dataset_id,
        "release_version": release_version,
        "items": config["known_limitations"],
        "component_note": "Two CABA LINK values have two source polygon components each. All 52,408 source rows are preserved in source_components.parquet; the consumer geography contains 52,406 unique official radio identities.",
    }
    catalog = pd.DataFrame([
        {
            "geography_id": geography_spec.id,
            "dataset_id": dataset.dataset_id,
            "release_version": dataset.version,
            "schema_version": dataset.schema_version,
            "provider": "indec",
            "scheme": "census",
            "vintage": "2010",
            "level": "radio",
            "source_release": config["release"],
            "authority_status": "official",
            "feature_count": len(geography),
            "source_component_count": len(components),
            "native_id_fields": "link/LINK; toponimo_i/PAIS0210_I",
            "consumer_id_fields": "radio_2010_id,department_2010_id,province_2010_id",
            "storage_crs": qa["crs"],
            "manifest_ref": "manifest.json",
            "distribution_mode": config["distribution_mode"],
        }
    ])
    catalog.to_parquet(output / "geography_catalog.parquet", index=False)
    write_json(output / "qa.json", qa)
    write_json(output / "source_metadata.json", source_metadata)
    write_json(output / "identity_contract.json", identity_contract)
    write_json(output / "limitations.json", limitations)
    manifest = {
        "product_type": "geography",
        "authority_status": "official",
        "stage_decision": "PASS",
        "dataset": dataset.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "row_count": len(geography),
        "source_component_count": len(components),
        "source_snapshot": source_snapshot.model_dump(mode="json"),
        "artifacts": {
            "geography": "geography.parquet",
            "source_components": "source_components.parquet",
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
    dataset = manifest["dataset"]
    frame = gpd.read_parquet(output / manifest["artifacts"]["geography"])
    components = gpd.read_parquet(output / manifest["artifacts"]["source_components"])
    if len(frame) != manifest["row_count"]:
        raise ValueError("INDEC 2010 row count does not match manifest")
    if len(components) != manifest["source_component_count"]:
        raise ValueError("INDEC 2010 source component count does not match manifest")
    required = {"radio_2010_id", "department_2010_id", "province_2010_id"}
    if not required.issubset(frame.columns):
        raise ValueError("INDEC 2010 stable consumer identity fields are missing")
    if frame["radio_2010_id"].duplicated().any():
        raise ValueError("INDEC 2010 detached release has duplicate radio_2010_id")
    if not frame["radio_2010_id"].str.match(r"^[0-9]{9}$").all():
        raise ValueError("INDEC 2010 detached radio IDs are not zero-preserving 9-digit strings")
    if not frame["department_2010_id"].eq(frame["radio_2010_id"].str[:5]).all():
        raise ValueError("INDEC 2010 detached department IDs disagree with radio IDs")
    if not frame["province_2010_id"].eq(frame["radio_2010_id"].str[:2]).all():
        raise ValueError("INDEC 2010 detached province IDs disagree with radio IDs")
    if (~frame.geometry.is_valid).any():
        raise ValueError("INDEC 2010 detached release contains invalid geometry")
    catalog = pd.read_parquet(output / manifest["artifacts"]["catalog"])
    if len(catalog) != 1 or catalog.iloc[0]["dataset_id"] != dataset["dataset_id"]:
        raise ValueError("INDEC 2010 catalog does not identify the detached release")


def materialize(source_dir: Path, output: Path, config_path: Path = DEFAULT_CONFIG) -> dict:
    return materialize_from_sources(source_dir, output, config_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize official INDEC Census 2010 radio geography.")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("materialize")
    build.add_argument("--source-dir", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    verify = sub.add_parser("verify")
    verify.add_argument("--release", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "materialize":
        materialize(args.source_dir, args.output, args.config)
    else:
        verify_release(args.release)


if __name__ == "__main__":
    main()
