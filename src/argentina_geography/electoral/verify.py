from __future__ import annotations

from pathlib import Path

import pandas as pd

from argentina_geography.electoral.config import DEFAULT_CONFIG, load_config
from argentina_geography.products import (
    read_json,
    validate_manifest,
    verify_checksums,
    write_json,
)

FORBIDDEN_RELATION_COLUMN_TOKENS = (
    "winner",
    "selected",
    "canonical",
    "corrected",
    "nearest",
)

def verify_vertical(output: Path, config_path: Path = DEFAULT_CONFIG) -> None:
    config = load_config(config_path)
    verify_checksums(output)
    manifest = validate_manifest(output / "manifest.json")
    vintage = manifest.get("vintage")
    if vintage not in config["circuit_parents"]:
        raise ValueError(f"invalid electoral vertical vintage: {vintage}")
    if manifest.get("product_type") != "electoral_vertical":
        raise ValueError("electoral vertical product_type changed unexpectedly")
    if manifest.get("policy_boundary", {}).get("publish_crosswalk") is not False:
        raise ValueError("electoral vertical must not publish an implicit crosswalk")

    relations = pd.read_parquet(output / manifest["artifacts"]["relations"])
    forbidden = [
        column
        for column in relations.columns
        if any(token in column.casefold() for token in FORBIDDEN_RELATION_COLUMN_TOKENS)
    ]
    if forbidden:
        raise ValueError(f"primary relation contains adjudication-like columns: {forbidden}")

    bridge = pd.read_parquet(output / manifest["artifacts"]["district_province_bridge"])
    if len(bridge) != 24:
        raise ValueError("district/province bridge must contain 24 rows")
    expected = {
        item["electoral_district_code"]: item["province_2010_id"]
        for item in config["district_province_bridge"]
    }
    observed = bridge.set_index("electoral_district_code")["province_2010_id"].to_dict()
    if observed != expected:
        raise ValueError("district/province bridge drifted from explicit namespace mapping")

    sections = pd.read_parquet(output / manifest["artifacts"]["electoral_sections"])
    circuits = pd.read_parquet(output / manifest["artifacts"]["electoral_circuits"])
    if circuits.empty or sections.empty:
        raise ValueError("electoral hierarchy artifacts must not be empty")
    if circuits["relation_target_uid"].duplicated().any():
        raise ValueError("derived electoral relation target IDs must be unique")
    repeated_code = circuits.groupby("electoral_circuit_code")[
        "electoral_district_code"
    ].nunique()
    if not (repeated_code > 1).any():
        raise ValueError("electoral circuit code alone is incorrectly behaving as globally unique")

    status = pd.read_parquet(output / manifest["artifacts"]["input_status"])
    source_rows = status.loc[status["input_side"].eq("census_radio")]
    relation_sources = set(relations["source_geo_uid"].astype(str))
    if set(source_rows["input_uid"].astype(str)) != relation_sources:
        raise ValueError("primary relation does not keep every Census radio observable")

    province_qa = pd.read_parquet(output / manifest["artifacts"]["province_qa"])
    if len(province_qa) != 24:
        raise ValueError("province QA must contain exactly 24 electoral district/province rows")

    policies = read_json(output / manifest["artifacts"]["historical_policy_registry"])
    if any(item["status"] != "regression_only" for item in policies["policies"]):
        raise ValueError("historical policies escaped the regression-only boundary")

    catalog = pd.read_parquet(output / manifest["artifacts"]["catalog"])
    expected_relation_ids = {
        value.format(vintage=vintage) for value in config["relation_ids"].values()
    }
    if set(catalog["relation_id"]) != expected_relation_ids:
        raise ValueError("relation catalog does not expose the complete electoral vertical")

    if "historical_radio_comparison" in manifest["artifacts"]:
        comparison = pd.read_parquet(
            output / manifest["artifacts"]["historical_radio_comparison"]
        )
        if "historical_assignment_is_current_candidate" not in comparison:
            raise ValueError("historical radio regression evidence is incomplete")
    if "historical_section_comparison" in manifest["artifacts"]:
        comparison = pd.read_parquet(
            output / manifest["artifacts"]["historical_section_comparison"]
        )
        if "historical_department_is_current_candidate" not in comparison:
            raise ValueError("historical section regression evidence is incomplete")
    if "elecciones_compatibility" in manifest["artifacts"]:
        compatibility = pd.read_parquet(
            output / manifest["artifacts"]["elecciones_compatibility"]
        )
        if "compatible_any" not in compatibility:
            raise ValueError("elecciones-ARG compatibility proof is incomplete")

def write_release_identity(release: Path, output: Path) -> dict:
    manifest = read_json(release / "manifest.json")
    record = {
        "vintage": manifest["vintage"],
        "datasets": manifest["datasets"],
        "parents": manifest["parents"],
        "qa": read_json(release / manifest["artifacts"]["qa"]),
    }
    write_json(output, record)
    return record
