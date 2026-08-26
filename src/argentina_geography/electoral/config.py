from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from empirical_contracts import DatasetRef

from argentina_geography.products import read_json, validate_manifest
from argentina_geography.sources.indec_2010_radio import (
    verify_release as verify_census_release,
)
from argentina_geography.sources.tartagalensis_circuits import (
    verify_release as verify_circuit_release,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config/electoral/electoral_vertical.json"

def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    return read_json(path)

def _snapshot_sha(manifest: dict) -> str:
    direct = manifest.get("source_snapshot_sha256")
    if direct:
        return str(direct)
    snapshot = manifest.get("source_snapshot", {})
    snapshot_id = str(snapshot.get("snapshot_id", ""))
    if snapshot_id.startswith("sha256:"):
        return snapshot_id.removeprefix("sha256:")
    raise ValueError("parent release is not SHA-256 snapshot addressed")

def _verify_parent_binding(manifest: dict, expected: dict, *, label: str) -> DatasetRef:
    dataset = DatasetRef.model_validate(manifest["dataset"])
    checks = {
        "dataset_id": dataset.dataset_id,
        "release_version": dataset.version,
        "content_sha256": dataset.content_sha256,
        "source_snapshot_sha256": _snapshot_sha(manifest),
    }
    for field, observed in checks.items():
        wanted = expected[field]
        if observed != wanted:
            raise ValueError(
                f"{label} {field} mismatch: expected {wanted}, observed {observed}"
            )
    for field in ("source_commit_sha", "source_tree_sha"):
        if field in expected and manifest.get(field) != expected[field]:
            raise ValueError(
                f"{label} {field} mismatch: expected {expected[field]}, "
                f"observed {manifest.get(field)}"
            )
    return dataset

def _load_parents(
    census_release: Path,
    circuit_release: Path,
    vintage: str,
    config: dict,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, DatasetRef, DatasetRef, dict, dict]:
    if vintage not in config["circuit_parents"]:
        raise ValueError(f"unsupported electoral vintage: {vintage}")
    verify_census_release(census_release)
    verify_circuit_release(circuit_release)

    census_manifest = validate_manifest(census_release / "manifest.json")
    circuit_manifest = validate_manifest(circuit_release / "manifest.json")
    census_dataset = _verify_parent_binding(
        census_manifest, config["census_parent"], label="Census 2010 parent"
    )
    circuit_dataset = _verify_parent_binding(
        circuit_manifest,
        config["circuit_parents"][vintage],
        label=f"Tartagalensis {vintage} parent",
    )
    if circuit_manifest.get("vintage") != vintage:
        raise ValueError(
            f"Tartagalensis parent vintage mismatch: expected {vintage}, "
            f"observed {circuit_manifest.get('vintage')}"
        )

    census = gpd.read_parquet(
        census_release / census_manifest["artifacts"]["geography"]
    )
    circuits = gpd.read_parquet(
        circuit_release / circuit_manifest["artifacts"]["geography"]
    )
    return (
        census,
        circuits,
        census_dataset,
        circuit_dataset,
        census_manifest,
        circuit_manifest,
    )

def _district_bridge(config: dict, vintage: str) -> pd.DataFrame:
    rows = []
    for item in config["district_province_bridge"]:
        code = item["electoral_district_code"]
        rows.append(
            {
                "relation_id": config["relation_ids"]["district_province"].format(
                    vintage=vintage
                ),
                "vintage": vintage,
                "electoral_district_uid": f"electoral:{vintage}:district:{code}",
                "electoral_district_code": code,
                "electoral_district_name": item["electoral_district_name"],
                "province_2010_id": item["province_2010_id"],
                "relation_status": "declared_cross_authority_correspondence",
                "mapping_basis": (
                    "explicit electoral-district/province namespace bridge; "
                    "historical and consumer evidence, never numeric-code equality"
                ),
            }
        )
    frame = pd.DataFrame(rows).sort_values("electoral_district_code", ignore_index=True)
    if len(frame) != 24:
        raise ValueError("electoral district/province bridge must contain exactly 24 rows")
    if frame["electoral_district_code"].duplicated().any():
        raise ValueError("electoral district code is duplicated in bridge")
    if frame["province_2010_id"].duplicated().any():
        raise ValueError("Census province code is duplicated in bridge")
    return frame
