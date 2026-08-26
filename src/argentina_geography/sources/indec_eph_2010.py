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
from argentina_geography.sources.indec_eph_2010_probe import download_file

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config/sources/indec_eph_census2010_radio.json"
REQUIRED_NATIVE_FIELDS = (
    "id",
    "eph_codagl",
    "eph_aglome",
    "codprov",
    "coddepto",
    "frac2010",
    "radio2010",
)
REQUIRED_OUTPUT_FILES = [
    "frame.parquet",
    "geography.parquet",
    "source_components.parquet",
    "frame_catalog.parquet",
    "identity_contract.json",
    "parent_compatibility.json",
    "consumer_compatibility.json",
    "qa.json",
    "source_metadata.json",
    "limitations.json",
    "manifest.json",
]


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    return read_json(path)


def _digits(value: object, width: int, field: str) -> str:
    if pd.isna(value):
        raise ValueError(f"{field} must be non-missing")
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text.isascii() or not text.isdigit() or len(text) > width:
        raise ValueError(f"{field} must contain at most {width} ASCII digits: {value!r}")
    return text.zfill(width)


def _read_vector(path: Path, label: str) -> tuple[gpd.GeoDataFrame, str]:
    source = f"zip://{path.resolve()}"
    layers = gpd.list_layers(source)
    if len(layers) != 1:
        records = layers.astype(object).where(layers.notna(), None).to_dict(orient="records")
        raise ValueError(f"INDEC EPH {label} must contain one vector layer: {records}")
    layer = str(layers.iloc[0]["name"])
    kwargs: dict[str, object] = {"engine": "pyogrio", "use_arrow": False}
    if label == "shapefile":
        kwargs["encoding"] = "CP1252"
    return gpd.read_file(source, layer=layer, **kwargs), layer


def _source_specs(config: dict) -> list[tuple[str, dict]]:
    return [
        ("radio_shapefile", config["radio_sources"]["shapefile"]),
        ("radio_geojson", config["radio_sources"]["geojson"]),
        ("structure", config["documentation_sources"]["structure"]),
        ("agglomerate_localities", config["documentation_sources"]["agglomerate_localities"]),
    ]


def _acquire_exact_sources(source_dir: Path, config: dict) -> tuple[list[dict], str]:
    source_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    for label, spec in _source_specs(config):
        path = source_dir / spec["file_name"]
        if not path.exists():
            download_file(spec["download_url"], path)
        digest = sha256_file(path)
        size = path.stat().st_size
        if digest != spec["expected_sha256"] or size != spec["expected_size_bytes"]:
            raise ValueError(
                f"INDEC EPH source drift for {label}: sha256={digest} size={size}"
            )
        records.append(
            {
                "label": label,
                "file_name": spec["file_name"],
                "download_url": spec["download_url"],
                "sha256": digest,
                "size_bytes": size,
            }
        )
    payload = "\n".join(
        f"{item['label']}\t{item['file_name']}\t{item['sha256']}\t{item['size_bytes']}"
        for item in sorted(records, key=lambda item: item["label"])
    )
    snapshot_sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if snapshot_sha != config["expected_snapshot_sha256"]:
        raise ValueError(
            f"INDEC EPH composite snapshot drift: {snapshot_sha} != "
            f"{config['expected_snapshot_sha256']}"
        )
    return records, snapshot_sha


def _normalized_components(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    missing = sorted(set(REQUIRED_NATIVE_FIELDS) - set(frame.columns))
    if missing:
        raise ValueError(f"INDEC EPH source schema drift: missing {missing}")
    if frame.crs is None or frame.crs.to_string() != "EPSG:22183":
        raise ValueError(f"INDEC EPH source CRS drift: {frame.crs}")

    result = frame.copy()
    result["province_2010_id"] = result["codprov"].map(
        lambda value: _digits(value, 2, "codprov")
    )
    native_depto = result["coddepto"].map(lambda value: _digits(value, 3, "coddepto"))
    native_frac = result["frac2010"].map(lambda value: _digits(value, 2, "frac2010"))
    native_radio = result["radio2010"].map(lambda value: _digits(value, 2, "radio2010"))
    result["department_2010_id"] = result["province_2010_id"] + native_depto
    result["radio_2010_id"] = result["department_2010_id"] + native_frac + native_radio
    result["eph_agglomerate_id"] = result["eph_codagl"].map(
        lambda value: _digits(value, 2, "eph_codagl")
    )
    result["provider_native_row_id"] = result["id"].map(lambda value: str(value).strip())
    if result["provider_native_row_id"].duplicated().any():
        raise ValueError("INDEC EPH provider-native row id is not unique")

    geometry = result.geometry
    if int(geometry.is_empty.sum()):
        raise ValueError("INDEC EPH source contains empty geometry")
    non_areal = geometry.notna() & ~geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if non_areal.any():
        raise ValueError("INDEC EPH source contains non-areal non-missing geometry")
    if (geometry.notna() & ~geometry.is_valid).any():
        raise ValueError("INDEC EPH source contains invalid geometry")

    result["source_component_id"] = "indec-eph:" + result["provider_native_row_id"]
    native_columns = [column for column in frame.columns if column != frame.geometry.name]
    columns = [
        "source_component_id",
        "provider_native_row_id",
        "radio_2010_id",
        "department_2010_id",
        "province_2010_id",
        "eph_agglomerate_id",
        *native_columns,
        result.geometry.name,
    ]
    return result[columns].sort_values("source_component_id", ignore_index=True)


def _relation_sha(frame: gpd.GeoDataFrame) -> tuple[str, pd.DataFrame]:
    pairs = (
        frame[["radio_2010_id", "eph_agglomerate_id"]]
        .drop_duplicates()
        .sort_values(["radio_2010_id", "eph_agglomerate_id"], ignore_index=True)
    )
    payload = "\n".join(
        f"{row.radio_2010_id}\t{row.eph_agglomerate_id}" for row in pairs.itertuples()
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), pairs


def _build_frame_and_geography(
    components: gpd.GeoDataFrame,
) -> tuple[pd.DataFrame, gpd.GeoDataFrame, dict]:
    code_counts = components.groupby("radio_2010_id")["eph_agglomerate_id"].nunique()
    conflicts = code_counts.loc[code_counts > 1]
    if not conflicts.empty:
        raise ValueError(
            "Official INDEC EPH source maps a radio to multiple agglomerate codes: "
            f"{conflicts.index[:10].tolist()}"
        )

    frame_rows: list[dict] = []
    geo_rows: list[dict] = []
    for radio_id, group in components.groupby("radio_2010_id", sort=True):
        departments = group["department_2010_id"].unique().tolist()
        provinces = group["province_2010_id"].unique().tolist()
        agglomerates = group["eph_agglomerate_id"].unique().tolist()
        if len(departments) != 1 or len(provinces) != 1 or len(agglomerates) != 1:
            raise ValueError(f"INDEC EPH identity disagreement for radio {radio_id}")
        names = sorted(
            {
                str(value).strip()
                for value in group["eph_aglome"].dropna().tolist()
                if str(value).strip()
            }
        )
        component_ids = sorted(group["source_component_id"].astype(str).tolist())
        base = {
            "radio_2010_id": radio_id,
            "department_2010_id": departments[0],
            "province_2010_id": provinces[0],
            "eph_agglomerate_id": agglomerates[0],
            "native_eph_aglome_values": "|".join(names),
            "source_component_count": len(group),
            "source_component_ids": "|".join(component_ids),
        }
        frame_rows.append(base)

        geometries = [geometry for geometry in group.geometry.tolist() if geometry is not None]
        if geometries:
            geometry = union_all(geometries)
            if geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
                raise ValueError(f"EPH radio aggregation produced unusable geometry: {radio_id}")
            if not geometry.is_valid:
                raise ValueError(
                    f"EPH radio aggregation would require substantive geometry repair: {radio_id}"
                )
            geometry_role = "analytical"
            geometry_valid: bool | None = True
        else:
            geometry = None
            geometry_role = "source_missing"
            geometry_valid = None
        geo_rows.append(
            {
                "geo_uid": f"indec:eph:census2010:radio:{radio_id}",
                "native_id": radio_id,
                **base,
                "geometry_valid": geometry_valid,
                "geometry_role": geometry_role,
                "geometry": geometry,
            }
        )

    frame = pd.DataFrame(frame_rows).sort_values("radio_2010_id", ignore_index=True)
    geography = gpd.GeoDataFrame(geo_rows, geometry="geometry", crs=components.crs)
    missing_ids = geography.loc[geography.geometry.isna(), "radio_2010_id"].sort_values().tolist()
    audit = {
        "source_component_count": len(components),
        "radio_count": len(frame),
        "extra_source_rows_beyond_radio_grain": len(components) - len(frame),
        "multi_component_radio_count": int((frame["source_component_count"] > 1).sum()),
        "max_source_components_per_radio": int(frame["source_component_count"].max()),
        "agglomerate_code_count": int(frame["eph_agglomerate_id"].nunique()),
        "missing_geometry_count": len(missing_ids),
        "missing_geometry_radio_2010_ids": missing_ids,
        "invalid_geometry_count": int(
            (geography.geometry.notna() & ~geography.geometry.is_valid).sum()
        ),
        "geometry_types": sorted(geography.geometry.dropna().geom_type.unique().tolist()),
        "crs": geography.crs.to_string(),
        "province_count": int(frame["province_2010_id"].nunique()),
        "department_count": int(frame["department_2010_id"].nunique()),
    }
    return frame, geography, audit


def _verify_parent_subset(parent_release: Path, config: dict, frame: pd.DataFrame) -> dict:
    parent = validate_manifest(parent_release / "manifest.json")
    expected = config["parent_census_2010"]
    dataset = parent["dataset"]
    if (
        dataset["dataset_id"] != expected["dataset_id"]
        or dataset["version"] != expected["release_version"]
        or dataset["content_sha256"] != expected["normalized_geography_sha256"]
    ):
        raise ValueError("A7 parent is not the exact merged A6 INDEC Census 2010 release")
    parent_frame = pd.read_parquet(
        parent_release / parent["artifacts"]["geography"], columns=["radio_2010_id"]
    )
    parent_ids = set(parent_frame["radio_2010_id"].astype(str))
    eph_ids = set(frame["radio_2010_id"].astype(str))
    missing = sorted(eph_ids - parent_ids)
    if missing:
        raise ValueError(
            f"Official EPH radio IDs are not a subset of exact A6 parent: {missing[:20]}"
        )
    return {
        "status": "PASS",
        "parent_dataset_id": dataset["dataset_id"],
        "parent_release_version": dataset["version"],
        "parent_content_sha256": dataset["content_sha256"],
        "parent_radio_count": len(parent_ids),
        "eph_radio_count": len(eph_ids),
        "missing_from_parent_count": 0,
        "stable_identity": ["radio_2010_id", "department_2010_id", "province_2010_id"],
    }


def materialize(
    source_dir: Path,
    parent_release: Path,
    output: Path,
    config_path: Path = DEFAULT_CONFIG,
) -> dict:
    config = load_config(config_path)
    source_records, snapshot_sha = _acquire_exact_sources(source_dir, config)

    shapefile_path = source_dir / config["radio_sources"]["shapefile"]["file_name"]
    geojson_path = source_dir / config["radio_sources"]["geojson"]["file_name"]
    shapefile, shapefile_layer = _read_vector(shapefile_path, "shapefile")
    geojson, geojson_layer = _read_vector(geojson_path, "geojson")
    components = _normalized_components(shapefile)
    geojson_components = _normalized_components(geojson)

    relation_sha, relation_pairs = _relation_sha(components)
    geojson_relation_sha, _ = _relation_sha(geojson_components)
    expected_relation_sha = config["expected_radio_to_agglomerate_relation_sha256"]
    if relation_sha != expected_relation_sha or geojson_relation_sha != expected_relation_sha:
        raise ValueError("INDEC EPH vector variants disagree with pinned direct radio mapping")

    frame, geography, audit = _build_frame_and_geography(components)
    if len(frame) != 26417 or len(components) != 26815:
        raise ValueError(
            f"INDEC EPH exact snapshot count drift: components={len(components)} radios={len(frame)}"
        )
    if audit["missing_geometry_radio_2010_ids"] != [
        "020011704",
        "020011706",
        "500281605",
    ]:
        raise ValueError("INDEC EPH missing-geometry radio set drift")

    parent_compatibility = _verify_parent_subset(parent_release, config, frame)
    consumer = config["consumer_evidence"]
    consumer_compatibility = {
        "status": "PASS",
        "mode": "read_only_tabular_reference",
        "consumer_repository": consumer["repository"],
        "consumer_commit": consumer["repository_commit"],
        "consumer_column": consumer["consumer_column"],
        "release_field": "eph_agglomerate_id",
        "projection": "AGLOMERADO = int(eph_agglomerate_id)",
        "gis_logic_required": False,
        "roundtrip_code_check": bool(
            frame["eph_agglomerate_id"]
            .astype(int)
            .map(lambda value: f"{value:02d}")
            .eq(frame["eph_agglomerate_id"])
            .all()
        ),
        "scientific_changes_required": False,
    }
    if not consumer_compatibility["roundtrip_code_check"]:
        raise ValueError("EPH agglomerate IDs cannot round-trip to income-modeling-eph AGLOMERADO")

    output.mkdir(parents=True, exist_ok=True)
    frame_path = output / "frame.parquet"
    geography_path = output / "geography.parquet"
    components_path = output / "source_components.parquet"
    frame.to_parquet(frame_path, index=False)
    geography.to_parquet(geography_path, index=False)
    components.to_parquet(components_path, index=False)
    frame_sha = sha256_file(frame_path)
    geography_sha = sha256_file(geography_path)
    components_sha = sha256_file(components_path)
    release_version = f"census2010-frame-{snapshot_sha[:12]}"

    geography_spec = GeographySpec(
        provider="indec",
        version="eph-census2010-frame",
        scheme="eph",
        level="radio",
    )
    dataset = DatasetRef(
        dataset_id="arggeo.indec.eph.census2010.radio_frame",
        version=release_version,
        schema_version="arggeo.eph-frame/v1",
        layer=DataLayer.SILVER,
        authority=AuthorityLevel.L1_NORMALIZED,
        grain=GrainSpec(keys=("radio_2010_id",)),
        geography=geography_spec,
        content_sha256=frame_sha,
    )
    source_refs = tuple(
        SourceFileRef(
            path=item["file_name"], sha256=item["sha256"], size_bytes=item["size_bytes"]
        )
        for item in source_records
    )
    source_snapshot = SourceSnapshotRef(
        source=config["source_id"],
        release=config["release"],
        snapshot_id=f"sha256:{snapshot_sha}",
        origin=config["source_page"],
        storage_mode="external_immutable",
        files=source_refs,
    )
    qa_result = QAResult(
        check_id="indec_eph_census2010_direct_frame_contract",
        state="YELLOW" if audit["missing_geometry_count"] else "GREEN",
        message=(
            "Official INDEC EPH direct radio-to-agglomerate frame is preserved; "
            "three source radios lack geometry but remain valid tabular frame rows."
        ),
        metrics={
            "source_component_count": audit["source_component_count"],
            "radio_count": audit["radio_count"],
            "agglomerate_code_count": audit["agglomerate_code_count"],
            "missing_geometry_count": audit["missing_geometry_count"],
            "parent_missing_count": parent_compatibility["missing_from_parent_count"],
        },
    )
    now = datetime.now(UTC)
    run = RunManifest(
        run_id=f"indec-eph-census2010:{snapshot_sha[:16]}",
        package="argentina-geography",
        package_version=package_version(),
        started_at=now,
        finished_at=now,
        inputs=(source_snapshot,),
        parameters={
            "distribution_mode": config["distribution_mode"],
            "mapping_method": "direct official source fields; no spatial reconstruction",
            "native_radio_identity": "codprov+coddepto+frac2010+radio2010",
            "native_agglomerate_identity": "eph_codagl",
            "radio_to_agglomerate_relation_sha256": relation_sha,
            "source_geometry_variant": "radios_eph.zip shapefile",
            "cross_variant_mapping_check": "PASS",
            "geometry_repair_applied": False,
            "parent_dataset_id": parent_compatibility["parent_dataset_id"],
            "parent_release_version": parent_compatibility["parent_release_version"],
        },
        outputs=(dataset,),
        qa=(qa_result,),
    )

    audit.update(
        {
            "stage_decision": "PASS_WITH_WARNINGS" if audit["missing_geometry_count"] else "PASS",
            "radio_to_agglomerate_relation_pair_count": len(relation_pairs),
            "radio_to_agglomerate_relation_sha256": relation_sha,
            "cross_variant_relation_sha256": geojson_relation_sha,
            "parent_subset_check": parent_compatibility,
            "geometry_repair_applied": False,
        }
    )
    identity_contract = {
        "dataset_id": dataset.dataset_id,
        "release_version": release_version,
        "stable_2010_ids": {
            "radio_2010_id": "codprov+coddepto+frac2010+radio2010 (2+3+2+2 digits)",
            "department_2010_id": "codprov+coddepto = radio_2010_id[0:5]",
            "province_2010_id": "codprov = radio_2010_id[0:2]",
        },
        "official_eph_identity": {
            "eph_agglomerate_id": "eph_codagl, zero-preserving 2-digit source code",
            "native_name_field": "eph_aglome",
            "mapping": "directly declared per source row; no overlay, centroid, nearest-neighbour or winner policy",
        },
        "source_row_grain": "26,815 provider rows retained in source_components.parquet",
        "consumer_radio_grain": "26,417 unique radio_2010_id rows in frame.parquet/geography.parquet",
    }
    source_metadata = {
        **config,
        "snapshot_sha256": snapshot_sha,
        "source_files": source_records,
        "shapefile_layer": shapefile_layer,
        "geojson_layer": geojson_layer,
        "shapefile_columns": shapefile.columns.tolist(),
        "geojson_columns": geojson.columns.tolist(),
        "received_crs": geography.crs.to_string(),
        "adopted_geometry_source": config["radio_sources"]["shapefile"]["file_name"],
        "direct_mapping_relation_sha256": relation_sha,
    }
    limitations = {
        "dataset_id": dataset.dataset_id,
        "release_version": release_version,
        "items": config["known_limitations"],
        "geometry_note": (
            "No missing EPH geometry is filled from the Census parent. "
            "Source-missing geometry remains source_missing."
        ),
        "agglomerate_name_note": (
            "Native names are preserved at radio grain; code 38 has two source spelling variants "
            "across the published layer."
        ),
    }
    catalog = pd.DataFrame(
        [
            {
                "dataset_id": dataset.dataset_id,
                "geography_id": geography_spec.id,
                "release_version": release_version,
                "schema_version": dataset.schema_version,
                "provider": "indec",
                "scheme": "eph",
                "vintage": "census2010-based-frame",
                "level": "radio",
                "source_release": config["release"],
                "authority_status": "official",
                "radio_count": len(frame),
                "source_component_count": len(components),
                "agglomerate_code_count": audit["agglomerate_code_count"],
                "native_id_fields": "codprov,coddepto,frac2010,radio2010,eph_codagl",
                "stable_id_fields": "radio_2010_id,department_2010_id,province_2010_id,eph_agglomerate_id",
                "geometry_types": ",".join(audit["geometry_types"]),
                "storage_crs": audit["crs"],
                "missing_geometry_count": audit["missing_geometry_count"],
                "artifact_ref": "frame.parquet",
                "geography_ref": "geography.parquet",
                "manifest_ref": "manifest.json",
                "parent_dataset_id": parent_compatibility["parent_dataset_id"],
                "parent_release_version": parent_compatibility["parent_release_version"],
                "distribution_mode": config["distribution_mode"],
            }
        ]
    )
    catalog.to_parquet(output / "frame_catalog.parquet", index=False)
    write_json(output / "identity_contract.json", identity_contract)
    write_json(output / "parent_compatibility.json", parent_compatibility)
    write_json(output / "consumer_compatibility.json", consumer_compatibility)
    write_json(output / "qa.json", audit)
    write_json(output / "source_metadata.json", source_metadata)
    write_json(output / "limitations.json", limitations)

    manifest = {
        "product_type": "survey_frame_geography",
        "authority_status": "official",
        "stage_decision": audit["stage_decision"],
        "dataset": dataset.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "row_count": len(frame),
        "source_component_count": len(components),
        "source_snapshot": source_snapshot.model_dump(mode="json"),
        "parent_census_2010": parent_compatibility,
        "content_sha256": {
            "frame": frame_sha,
            "geography": geography_sha,
            "source_components": components_sha,
        },
        "artifacts": {
            "frame": "frame.parquet",
            "geography": "geography.parquet",
            "source_components": "source_components.parquet",
            "catalog": "frame_catalog.parquet",
            "identity_contract": "identity_contract.json",
            "parent_compatibility": "parent_compatibility.json",
            "consumer_compatibility": "consumer_compatibility.json",
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
    frame = pd.read_parquet(output / manifest["artifacts"]["frame"])
    geography = gpd.read_parquet(output / manifest["artifacts"]["geography"])
    components = gpd.read_parquet(output / manifest["artifacts"]["source_components"])

    if len(frame) != manifest["row_count"] or len(geography) != manifest["row_count"]:
        raise ValueError("INDEC EPH detached row count mismatch")
    if len(components) != manifest["source_component_count"]:
        raise ValueError("INDEC EPH detached source-component count mismatch")
    required = {
        "radio_2010_id",
        "department_2010_id",
        "province_2010_id",
        "eph_agglomerate_id",
    }
    if not required.issubset(frame.columns) or not required.issubset(geography.columns):
        raise ValueError("INDEC EPH detached stable identity fields are missing")
    if frame["radio_2010_id"].duplicated().any():
        raise ValueError("INDEC EPH frame has duplicate radio_2010_id")
    if not frame["radio_2010_id"].str.match(r"^[0-9]{9}$").all():
        raise ValueError("INDEC EPH radio IDs are not zero-preserving 9-digit strings")
    if not frame["department_2010_id"].eq(frame["radio_2010_id"].str[:5]).all():
        raise ValueError("INDEC EPH department IDs disagree with radio IDs")
    if not frame["province_2010_id"].eq(frame["radio_2010_id"].str[:2]).all():
        raise ValueError("INDEC EPH province IDs disagree with radio IDs")
    if not frame["eph_agglomerate_id"].str.match(r"^[0-9]{2}$").all():
        raise ValueError("INDEC EPH agglomerate IDs are not zero-preserving 2-digit strings")
    frame_pairs = frame[["radio_2010_id", "eph_agglomerate_id"]].sort_values(
        ["radio_2010_id", "eph_agglomerate_id"], ignore_index=True
    )
    payload = "\n".join(
        f"{row.radio_2010_id}\t{row.eph_agglomerate_id}" for row in frame_pairs.itertuples()
    )
    relation_sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    source_metadata = read_json(output / manifest["artifacts"]["source_metadata"])
    if relation_sha != source_metadata["expected_radio_to_agglomerate_relation_sha256"]:
        raise ValueError("INDEC EPH detached direct mapping hash mismatch")
    missing = geography.geometry.isna()
    if not geography.loc[missing, "geometry_role"].eq("source_missing").all():
        raise ValueError("INDEC EPH missing geometries are not explicitly source_missing")
    if not geography.loc[~missing, "geometry_role"].eq("analytical").all():
        raise ValueError("INDEC EPH present geometries are not explicitly analytical")
    if (geography.loc[~missing].geometry.is_valid == False).any():
        raise ValueError("INDEC EPH detached analytical geometry is invalid")
    parent = read_json(output / manifest["artifacts"]["parent_compatibility"])
    consumer = read_json(output / manifest["artifacts"]["consumer_compatibility"])
    if parent["status"] != "PASS" or parent["missing_from_parent_count"] != 0:
        raise ValueError("INDEC EPH detached parent compatibility proof failed")
    if (
        consumer["status"] != "PASS"
        or consumer["gis_logic_required"]
        or not consumer["roundtrip_code_check"]
    ):
        raise ValueError("INDEC EPH detached income-modeling-eph compatibility proof failed")
    catalog = pd.read_parquet(output / manifest["artifacts"]["catalog"])
    if len(catalog) != 1 or catalog.iloc[0]["dataset_id"] != manifest["dataset"]["dataset_id"]:
        raise ValueError("INDEC EPH frame catalog does not identify detached release")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize official INDEC EPH Census-2010-based radio frame."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("materialize")
    build.add_argument("--source-dir", type=Path, required=True)
    build.add_argument("--parent-release", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    verify = sub.add_parser("verify")
    verify.add_argument("--release", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "materialize":
        materialize(args.source_dir, args.parent_release, args.output, args.config)
    else:
        verify_release(args.release)


if __name__ == "__main__":
    main()
