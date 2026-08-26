from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
from empirical_contracts import (
    AuthorityLevel,
    DataLayer,
    DatasetRef,
    GrainSpec,
    QAResult,
    RunManifest,
)
from spatial_foundation.geography import relate_areal_objects

from argentina_geography.product_writer import package_version
from argentina_geography.products import (
    read_json,
    sha256_file,
    validate_manifest,
    verify_checksums,
    write_checksums,
    write_json,
)
from argentina_geography.sources.ceur_2022_v2025_1 import (
    verify_release as verify_ceur_release,
)
from argentina_geography.sources.indec_2022_radio import (
    verify_release as verify_indec_release,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config/relations/indec_ceur_census_2022_radio.json"
REQUIRED_OUTPUT_FILES = [
    "relations.parquet",
    "relation_catalog.parquet",
    "qa.json",
    "comparison_summary.json",
    "comparison_summary.md",
    "manifest.json",
]


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    return read_json(path)


def _parent_snapshot_sha(manifest: dict) -> str:
    snapshot_id = manifest["source_snapshot"]["snapshot_id"]
    prefix = "sha256:"
    if not snapshot_id.startswith(prefix):
        raise ValueError(f"parent source snapshot is not SHA-256 addressed: {snapshot_id}")
    return snapshot_id[len(prefix) :]


def _load_parent(
    release: Path,
    expected: dict,
    *,
    verify,
    label: str,
) -> tuple[gpd.GeoDataFrame, dict, DatasetRef]:
    verify(release)
    manifest = validate_manifest(release / "manifest.json")
    dataset = DatasetRef.model_validate(manifest["dataset"])
    if dataset.dataset_id != expected["dataset_id"]:
        raise ValueError(
            f"{label} dataset_id mismatch: expected {expected['dataset_id']}, "
            f"found {dataset.dataset_id}"
        )
    if dataset.version != expected["release_version"]:
        raise ValueError(
            f"{label} release version mismatch: expected {expected['release_version']}, "
            f"found {dataset.version}"
        )
    source_sha = _parent_snapshot_sha(manifest)
    if source_sha != expected["source_snapshot_sha256"]:
        raise ValueError(
            f"{label} source snapshot mismatch: expected "
            f"{expected['source_snapshot_sha256']}, found {source_sha}"
        )
    frame = gpd.read_parquet(release / manifest["artifacts"]["geography"])
    return frame, manifest, dataset


def _quantiles(values: pd.Series) -> dict:
    if values.empty:
        return {}
    numeric = values.astype(float)
    return {
        "min": float(numeric.min()),
        "p01": float(numeric.quantile(0.01)),
        "p05": float(numeric.quantile(0.05)),
        "p50": float(numeric.quantile(0.50)),
        "p95": float(numeric.quantile(0.95)),
        "p99": float(numeric.quantile(0.99)),
        "max": float(numeric.max()),
    }


def build_relation(
    indec: gpd.GeoDataFrame,
    ceur: gpd.GeoDataFrame,
    config: dict,
) -> tuple[pd.DataFrame, dict]:
    source = indec.rename(columns={"geo_uid": "source_geo_uid"}).copy()
    target = ceur.rename(columns={"geo_uid": "target_geo_uid"}).copy()

    target_analytical = target.loc[target["geometry_role"].eq("analytical")].copy()
    source_objects = source[["source_geo_uid", "geometry"]].copy()
    target_polygons = target_analytical[
        ["target_geo_uid", "geometry_role", "geometry"]
    ].copy()

    relation, foundation_audit = relate_areal_objects(
        source_objects,
        target_polygons,
        object_id_col="source_geo_uid",
        polygon_id_col="target_geo_uid",
        area_crs=config["analysis_crs"],
        min_overlap_area_m2=float(config["minimum_overlap_area_m2"]),
    )
    relation = relation.rename(
        columns={
            "overlap_share_of_object": "overlap_share_of_source",
            "overlap_count": "source_candidate_count",
        }
    )

    source_native = source.set_index("source_geo_uid")["native_id"]
    target_native = target_analytical.set_index("target_geo_uid")["native_id"]
    relation["source_native_id"] = relation["source_geo_uid"].map(source_native)
    relation["target_native_id"] = relation["target_geo_uid"].map(target_native)

    positive = relation["target_geo_uid"].notna()
    relation["same_native_id"] = pd.Series(pd.NA, index=relation.index, dtype="boolean")
    relation.loc[positive, "same_native_id"] = (
        relation.loc[positive, "source_native_id"].astype(str).to_numpy()
        == relation.loc[positive, "target_native_id"].astype(str).to_numpy()
    )

    target_metric = target_analytical[
        ["target_geo_uid", target_analytical.geometry.name]
    ].to_crs(config["analysis_crs"])
    target_area = target_metric.set_index("target_geo_uid").geometry.area
    relation["overlap_share_of_target"] = pd.Series(
        pd.NA, index=relation.index, dtype="Float64"
    )
    if positive.any():
        positive_target_area = relation.loc[positive, "target_geo_uid"].map(target_area)
        relation.loc[positive, "overlap_share_of_target"] = (
            relation.loc[positive, "overlap_area_m2"].astype(float).to_numpy()
            / positive_target_area.astype(float).to_numpy()
        )

    positive_relation = relation.loc[positive]
    target_counts = positive_relation.groupby("target_geo_uid").size()
    relation["target_candidate_count"] = pd.Series(
        pd.NA, index=relation.index, dtype="Int64"
    )
    relation.loc[positive, "target_candidate_count"] = (
        relation.loc[positive, "target_geo_uid"].map(target_counts).astype("Int64")
    )

    relation = relation[
        [
            "source_geo_uid",
            "source_native_id",
            "target_geo_uid",
            "target_native_id",
            "same_native_id",
            "overlap_area_m2",
            "overlap_share_of_source",
            "overlap_share_of_target",
            "source_candidate_count",
            "target_candidate_count",
            "relation_status",
        ]
    ].sort_values(
        ["source_geo_uid", "target_geo_uid"],
        na_position="last",
        ignore_index=True,
    )

    positive = relation["target_geo_uid"].notna()
    positive_relation = relation.loc[positive]
    source_analytical = source["geometry_role"].eq("analytical")
    source_invalid = source["geometry_role"].eq("source_invalid")
    target_invalid = target["geometry_role"].eq("source_invalid")

    source_coverage = (
        positive_relation.groupby("source_geo_uid")["overlap_share_of_source"]
        .sum()
        .reindex(source.loc[source_analytical, "source_geo_uid"], fill_value=0.0)
    )
    target_coverage = (
        positive_relation.groupby("target_geo_uid")["overlap_share_of_target"]
        .sum()
        .reindex(target_analytical["target_geo_uid"], fill_value=0.0)
    )
    referenced_targets = int(positive_relation["target_geo_uid"].nunique())

    audit = {
        "stage_decision": (
            "PASS_WITH_WARNINGS"
            if int(source_invalid.sum()) or int(target_invalid.sum())
            else "PASS"
        ),
        "source_parent_rows": len(source),
        "source_analytical_rows": int(source_analytical.sum()),
        "source_invalid_geometry_rows": int(source_invalid.sum()),
        "target_parent_rows": len(target),
        "target_analytical_rows": len(target_analytical),
        "target_invalid_geometry_rows": int(target_invalid.sum()),
        "foundation_input_sources": foundation_audit.input_objects,
        "matched_single": foundation_audit.matched_single,
        "matched_multiple": foundation_audit.matched_multiple,
        "unmatched_outside": foundation_audit.unmatched_outside,
        "invalid_source_geometry": foundation_audit.invalid_geometry,
        "positive_relation_rows": foundation_audit.relation_rows,
        "relation_rows_total": len(relation),
        "sources_with_positive_overlap": int(
            positive_relation["source_geo_uid"].nunique()
        ),
        "referenced_analytical_targets": referenced_targets,
        "unreferenced_analytical_targets": len(target_analytical) - referenced_targets,
        "positive_same_native_id_rows": int(
            positive_relation["same_native_id"].fillna(False).sum()
        ),
        "positive_different_native_id_rows": int(
            (~positive_relation["same_native_id"].fillna(False)).sum()
        ),
        "source_total_overlap_share_quantiles": _quantiles(source_coverage),
        "target_total_overlap_share_quantiles": _quantiles(target_coverage),
        "total_positive_overlap_area_m2": float(
            positive_relation["overlap_area_m2"].astype(float).sum()
        ),
        "analysis_crs": config["analysis_crs"],
        "minimum_overlap_area_m2": float(config["minimum_overlap_area_m2"]),
    }
    return relation, audit


def _relation_version(
    config: dict,
    source_dataset: DatasetRef,
    target_dataset: DatasetRef,
) -> str:
    payload = {
        "relation_id": config["relation_id"],
        "source_dataset": source_dataset.model_dump(mode="json"),
        "target_dataset": target_dataset.model_dump(mode="json"),
        "analysis_crs": config["analysis_crs"],
        "minimum_overlap_area_m2": config["minimum_overlap_area_m2"],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"2022-indec-ceur-{digest[:12]}"


def _summary_markdown(
    audit: dict, source_dataset: DatasetRef, target_dataset: DatasetRef
) -> str:
    return f"""# INDEC ↔ CEUR Census 2022 relation summary

This release contains **geometric relation facts**, not a provider preference or one-to-one crosswalk.

## Exact parents

- Source: `{source_dataset.dataset_id}` `{source_dataset.version}`
- Target: `{target_dataset.dataset_id}` `{target_dataset.version}`

## Relation counts

- INDEC parent rows: **{audit['source_parent_rows']:,}**
- INDEC analytical rows: **{audit['source_analytical_rows']:,}**
- INDEC source-invalid rows: **{audit['source_invalid_geometry_rows']:,}**
- CEUR parent rows: **{audit['target_parent_rows']:,}**
- CEUR analytical rows: **{audit['target_analytical_rows']:,}**
- CEUR source-invalid rows excluded as targets: **{audit['target_invalid_geometry_rows']:,}**
- Positive relation rows: **{audit['positive_relation_rows']:,}**
- INDEC matched to one CEUR target: **{audit['matched_single']:,}**
- INDEC matched to multiple CEUR targets: **{audit['matched_multiple']:,}**
- INDEC unmatched outside analytical CEUR targets: **{audit['unmatched_outside']:,}**
- INDEC invalid source geometry: **{audit['invalid_source_geometry']:,}**
- CEUR analytical targets referenced: **{audit['referenced_analytical_targets']:,}**
- CEUR analytical targets unreferenced: **{audit['unreferenced_analytical_targets']:,}**

## Native-code agreement on positive overlaps

- Same nine-digit native ID: **{audit['positive_same_native_id_rows']:,}**
- Different native IDs: **{audit['positive_different_native_id_rows']:,}**

## Interpretation boundary

Areas and overlap shares are measured in `{audit['analysis_crs']}`. `overlap_share_of_source`
and `overlap_share_of_target` are two-sided geometric facts. Multiple matches, unmatched units,
invalid source geometry and unreferenced targets remain visible. No winner, nearest feature,
canonical provider, population allocation or geometry repair is applied.
"""


def materialize_relation(
    indec_release: Path,
    ceur_release: Path,
    output: Path,
    config_path: Path = DEFAULT_CONFIG,
) -> dict:
    config = load_config(config_path)
    indec, indec_manifest, source_dataset = _load_parent(
        indec_release,
        config["source_parent"],
        verify=verify_indec_release,
        label="INDEC source parent",
    )
    ceur, ceur_manifest, target_dataset = _load_parent(
        ceur_release,
        config["target_parent"],
        verify=verify_ceur_release,
        label="CEUR target parent",
    )

    relation, audit = build_relation(indec, ceur, config)
    output.mkdir(parents=True, exist_ok=True)
    relation_path = output / "relations.parquet"
    relation.to_parquet(relation_path, index=False)
    relation_content_sha = sha256_file(relation_path)

    version = _relation_version(config, source_dataset, target_dataset)
    dataset = DatasetRef(
        dataset_id=config["relation_id"],
        version=version,
        schema_version="arggeo.relation/v1",
        layer=DataLayer.GOLD,
        authority=AuthorityLevel.L2_DERIVED,
        grain=GrainSpec(keys=("source_geo_uid", "target_geo_uid")),
        content_sha256=relation_content_sha,
    )

    warnings_list = []
    if audit["source_invalid_geometry_rows"]:
        warnings_list.append(
            {
                "code": "source_parent_invalid_geometry",
                "affected_rows": audit["source_invalid_geometry_rows"],
                "message": "INDEC source-invalid polygons remain visible as invalid source relation rows.",
            }
        )
    if audit["target_invalid_geometry_rows"]:
        warnings_list.append(
            {
                "code": "target_parent_invalid_geometry_excluded",
                "affected_rows": audit["target_invalid_geometry_rows"],
                "message": "CEUR source-invalid polygons are excluded from the analytical target set.",
            }
        )

    qa_state = "YELLOW" if warnings_list else "GREEN"
    qa_result = QAResult(
        check_id="indec_ceur_2022_radio_relation_contract",
        state=qa_state,
        message=(
            "INDEC↔CEUR 2022 geometric relation is publishable with explicit parent-geometry warnings."
            if qa_state == "YELLOW"
            else "INDEC↔CEUR 2022 geometric relation satisfies the relation boundary."
        ),
        metrics={
            "source_parent_rows": audit["source_parent_rows"],
            "target_parent_rows": audit["target_parent_rows"],
            "positive_relation_rows": audit["positive_relation_rows"],
            "matched_single": audit["matched_single"],
            "matched_multiple": audit["matched_multiple"],
            "unmatched_outside": audit["unmatched_outside"],
            "invalid_source_geometry": audit["invalid_source_geometry"],
            "target_invalid_geometry_rows": audit["target_invalid_geometry_rows"],
        },
    )
    now = datetime.now(UTC)
    run = RunManifest(
        run_id=f"indec-ceur-2022-relation:{version}",
        package="argentina-geography",
        package_version=package_version(),
        started_at=now,
        finished_at=now,
        inputs=(source_dataset, target_dataset),
        parameters={
            "relation_method": "spatial_foundation.geography.relate_areal_objects",
            "analysis_crs": config["analysis_crs"],
            "minimum_overlap_area_m2": config["minimum_overlap_area_m2"],
            "adjudication_applied": False,
            "geometry_repair_applied": False,
            "stage_decision": audit["stage_decision"],
            "accepted_qa_warnings": warnings_list,
        },
        outputs=(dataset,),
        qa=(qa_result,),
    )

    catalog = pd.DataFrame(
        [
            {
                "relation_id": config["relation_id"],
                "dataset_id": dataset.dataset_id,
                "release_version": dataset.version,
                "schema_version": dataset.schema_version,
                "source_dataset_id": source_dataset.dataset_id,
                "source_release_version": source_dataset.version,
                "target_dataset_id": target_dataset.dataset_id,
                "target_release_version": target_dataset.version,
                "authority_status": "derived_geometric_fact",
                "relation_method": "areal_positive_overlap",
                "analysis_crs": config["analysis_crs"],
                "row_count": len(relation),
                "positive_relation_rows": audit["positive_relation_rows"],
                "qa_state": qa_state,
                "stage_decision": audit["stage_decision"],
                "artifact_ref": "relations.parquet",
                "manifest_ref": "manifest.json",
            }
        ]
    )
    catalog.to_parquet(output / "relation_catalog.parquet", index=False)
    write_json(output / "qa.json", {**audit, "accepted_warnings": warnings_list})
    write_json(
        output / "comparison_summary.json",
        {
            "relation_id": config["relation_id"],
            "source_parent": {
                "dataset": source_dataset.model_dump(mode="json"),
                "source_snapshot": indec_manifest["source_snapshot"],
            },
            "target_parent": {
                "dataset": target_dataset.model_dump(mode="json"),
                "source_snapshot": ceur_manifest["source_snapshot"],
            },
            "audit": audit,
            "interpretation": config["interpretation"],
            "known_limitations": config["known_limitations"],
        },
    )
    (output / "comparison_summary.md").write_text(
        _summary_markdown(audit, source_dataset, target_dataset),
        encoding="utf-8",
    )
    manifest = {
        "product_type": "relation",
        "authority_status": "derived_geometric_fact",
        "stage_decision": audit["stage_decision"],
        "dataset": dataset.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "parents": {
            "source_dataset": source_dataset.model_dump(mode="json"),
            "source_snapshot": indec_manifest["source_snapshot"],
            "target_dataset": target_dataset.model_dump(mode="json"),
            "target_snapshot": ceur_manifest["source_snapshot"],
        },
        "relation_method": "spatial_foundation.geography.relate_areal_objects",
        "adjudication_applied": False,
        "row_count": len(relation),
        "positive_relation_rows": audit["positive_relation_rows"],
        "artifacts": {
            "relations": "relations.parquet",
            "catalog": "relation_catalog.parquet",
            "qa": "qa.json",
            "comparison_summary_json": "comparison_summary.json",
            "comparison_summary_md": "comparison_summary.md",
        },
    }
    write_json(output / "manifest.json", manifest)
    write_checksums(output, REQUIRED_OUTPUT_FILES)
    return manifest


def verify_relation(
    output: Path,
    config_path: Path = DEFAULT_CONFIG,
) -> None:
    config = load_config(config_path)
    verify_checksums(output)
    manifest = validate_manifest(output / "manifest.json")
    dataset = manifest["dataset"]
    relation = pd.read_parquet(output / manifest["artifacts"]["relations"])

    if dataset["dataset_id"] != config["relation_id"]:
        raise ValueError("relation dataset_id does not match configured relation")
    if sha256_file(output / manifest["artifacts"]["relations"]) != dataset["content_sha256"]:
        raise ValueError("relation content hash mismatch")
    if len(relation) != manifest["row_count"]:
        raise ValueError("relation row count does not match manifest")

    required = {
        "source_geo_uid",
        "source_native_id",
        "target_geo_uid",
        "target_native_id",
        "same_native_id",
        "overlap_area_m2",
        "overlap_share_of_source",
        "overlap_share_of_target",
        "source_candidate_count",
        "target_candidate_count",
        "relation_status",
    }
    missing = sorted(required - set(relation.columns))
    if missing:
        raise ValueError(f"relation is missing required columns: {missing}")
    if relation["source_geo_uid"].isna().any():
        raise ValueError("relation source_geo_uid must be non-missing")

    positive = relation["target_geo_uid"].notna()
    if relation.loc[positive, "overlap_area_m2"].astype(float).le(0).any():
        raise ValueError("positive relation rows must have positive overlap area")
    for field in ("overlap_share_of_source", "overlap_share_of_target"):
        values = relation.loc[positive, field].astype(float)
        if values.le(0).any() or values.gt(1.0 + 1e-9).any():
            raise ValueError(f"{field} must be within (0, 1] on positive rows")
    if relation.loc[positive, "target_native_id"].isna().any():
        raise ValueError("positive relation rows require target_native_id")

    expected_same = (
        relation.loc[positive, "source_native_id"].astype(str).to_numpy()
        == relation.loc[positive, "target_native_id"].astype(str).to_numpy()
    )
    if not (
        relation.loc[positive, "same_native_id"].astype(bool).to_numpy()
        == expected_same
    ).all():
        raise ValueError("same_native_id is inconsistent with native IDs")

    nonpositive = ~positive
    if relation.loc[nonpositive, "overlap_area_m2"].notna().any():
        raise ValueError("non-positive relation rows must not contain overlap area")
    if relation.loc[nonpositive, "overlap_share_of_source"].notna().any():
        raise ValueError("non-positive relation rows must not contain source overlap share")
    allowed_status = {
        "matched_single",
        "matched_multiple",
        "unmatched_outside",
        "invalid_geometry",
    }
    if not set(relation["relation_status"]).issubset(allowed_status):
        raise ValueError("relation contains unsupported relation_status")

    source_parent = manifest["parents"]["source_dataset"]
    target_parent = manifest["parents"]["target_dataset"]
    if source_parent["version"] != config["source_parent"]["release_version"]:
        raise ValueError("relation source parent release changed")
    if target_parent["version"] != config["target_parent"]["release_version"]:
        raise ValueError("relation target parent release changed")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build or verify the exact INDEC↔CEUR Census 2022 radio relation."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--indec-release", type=Path, required=True)
    materialize.add_argument("--ceur-release", type=Path, required=True)
    materialize.add_argument("--output", type=Path, required=True)
    materialize.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--release", type=Path, required=True)
    verify.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    if args.command == "materialize":
        materialize_relation(
            args.indec_release,
            args.ceur_release,
            args.output,
            args.config,
        )
        verify_relation(args.output, args.config)
    else:
        verify_relation(args.release, args.config)


if __name__ == "__main__":
    main()
