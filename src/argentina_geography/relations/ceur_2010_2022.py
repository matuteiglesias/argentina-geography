from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
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
from argentina_geography.sources.ceur_2010_v2025_1 import (
    verify_release as verify_ceur_2010_release,
)
from argentina_geography.sources.ceur_2022_v2025_1 import (
    verify_release as verify_ceur_2022_release,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config/relations/ceur_census_2010_2022_radio.json"
REQUIRED_OUTPUT_FILES = [
    "relations.parquet",
    "relation_catalog.parquet",
    "qa.json",
    "relation_summary.json",
    "relation_summary.md",
    "pattern_examples.json",
    "pattern_examples.md",
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


def _verify_parent_binding(
    dataset: DatasetRef,
    source_snapshot: dict,
    expected: dict,
    *,
    label: str,
) -> None:
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
    if dataset.content_sha256 != expected["content_sha256"]:
        raise ValueError(
            f"{label} content hash mismatch: expected {expected['content_sha256']}, "
            f"found {dataset.content_sha256}"
        )
    source_sha = _parent_snapshot_sha({"source_snapshot": source_snapshot})
    if source_sha != expected["source_snapshot_sha256"]:
        raise ValueError(
            f"{label} source snapshot mismatch: expected "
            f"{expected['source_snapshot_sha256']}, found {source_sha}"
        )


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
    _verify_parent_binding(
        dataset,
        manifest["source_snapshot"],
        expected,
        label=label,
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


def _multiplicity_distribution(values: pd.Series) -> dict[str, int]:
    counts = values.astype(int).value_counts().sort_index()
    return {str(int(key)): int(value) for key, value in counts.items()}


def _coverage_counts(values: pd.Series, tolerance: float) -> dict[str, int]:
    numeric = values.astype(float)
    return {
        "zero": int(numeric.le(tolerance).sum()),
        "partial": int(((numeric > tolerance) & (numeric < 1.0 - tolerance)).sum()),
        "near_full": int(
            ((numeric >= 1.0 - tolerance) & (numeric <= 1.0 + tolerance)).sum()
        ),
        "over_one": int((numeric > 1.0 + tolerance).sum()),
    }


def _positive_components(relation: pd.DataFrame) -> list[dict]:
    positive = relation.loc[relation["target_geo_uid"].notna()].copy()
    source_to_targets: dict[str, set[str]] = {}
    target_to_sources: dict[str, set[str]] = {}
    for row in positive[["source_geo_uid", "target_geo_uid"]].itertuples(index=False):
        source_id = str(row.source_geo_uid)
        target_id = str(row.target_geo_uid)
        source_to_targets.setdefault(source_id, set()).add(target_id)
        target_to_sources.setdefault(target_id, set()).add(source_id)

    components: list[dict] = []
    seen_sources: set[str] = set()
    seen_targets: set[str] = set()
    for start_source in sorted(source_to_targets):
        if start_source in seen_sources:
            continue
        stack: list[tuple[str, str]] = [("source", start_source)]
        component_sources: set[str] = set()
        component_targets: set[str] = set()
        while stack:
            kind, node = stack.pop()
            if kind == "source":
                if node in seen_sources:
                    continue
                seen_sources.add(node)
                component_sources.add(node)
                for target_id in sorted(source_to_targets.get(node, set())):
                    if target_id not in seen_targets:
                        stack.append(("target", target_id))
            else:
                if node in seen_targets:
                    continue
                seen_targets.add(node)
                component_targets.add(node)
                for source_id in sorted(target_to_sources.get(node, set())):
                    if source_id not in seen_sources:
                        stack.append(("source", source_id))
        edge_count = sum(
            len(source_to_targets[source_id] & component_targets)
            for source_id in component_sources
        )
        components.append(
            {
                "source_geo_uids": sorted(component_sources),
                "target_geo_uids": sorted(component_targets),
                "source_count": len(component_sources),
                "target_count": len(component_targets),
                "edge_count": edge_count,
            }
        )
    return components


def _component_shape(source_count: int, target_count: int) -> str:
    if source_count == 1 and target_count == 1:
        return "1x1"
    if source_count == 1:
        return "1xN"
    if target_count == 1:
        return "Nx1"
    return "NxM"


def _component_shape_distributions(components: list[dict]) -> tuple[dict, dict]:
    broad = Counter()
    exact = Counter()
    for component in components:
        source_count = int(component["source_count"])
        target_count = int(component["target_count"])
        broad[_component_shape(source_count, target_count)] += 1
        exact[f"{source_count}x{target_count}"] += 1
    return (
        {key: int(value) for key, value in sorted(broad.items())},
        {key: int(value) for key, value in sorted(exact.items())},
    )


def _component_record(
    relation: pd.DataFrame,
    component: dict,
    *,
    pattern: str,
    interpretation_basis: str,
) -> dict:
    source_ids = set(component["source_geo_uids"])
    target_ids = set(component["target_geo_uids"])
    rows = relation.loc[
        relation["source_geo_uid"].isin(source_ids)
        & relation["target_geo_uid"].isin(target_ids)
    ].copy()
    rows = rows.sort_values(["source_geo_uid", "target_geo_uid"], ignore_index=True)

    sources = (
        rows[["source_geo_uid", "source_native_id"]]
        .drop_duplicates()
        .sort_values("source_geo_uid")
    )
    targets = (
        rows[["target_geo_uid", "target_native_id"]]
        .drop_duplicates()
        .sort_values("target_geo_uid")
    )
    return {
        "pattern": pattern,
        "interpretation_basis": interpretation_basis,
        "source_count": int(component["source_count"]),
        "target_count": int(component["target_count"]),
        "edge_count": int(component["edge_count"]),
        "sources": [
            {
                "geo_uid": str(row.source_geo_uid),
                "native_id": str(row.source_native_id),
            }
            for row in sources.itertuples(index=False)
        ],
        "targets": [
            {
                "geo_uid": str(row.target_geo_uid),
                "native_id": str(row.target_native_id),
            }
            for row in targets.itertuples(index=False)
        ],
        "edges": [
            {
                "source_geo_uid": str(row.source_geo_uid),
                "source_native_id": str(row.source_native_id),
                "target_geo_uid": str(row.target_geo_uid),
                "target_native_id": str(row.target_native_id),
                "same_native_id": bool(row.same_native_id),
                "overlap_area_m2": float(row.overlap_area_m2),
                "overlap_share_of_source": float(row.overlap_share_of_source),
                "overlap_share_of_target": float(row.overlap_share_of_target),
            }
            for row in rows.itertuples(index=False)
        ],
    }


def build_pattern_examples(relation: pd.DataFrame, config: dict) -> dict:
    positive = relation.loc[relation["target_geo_uid"].notna()].copy()
    components = _positive_components(relation)
    example_config = config["derived_examples"]
    stable_min = float(example_config["stable_mutual_overlap_min"])
    preferred_max_edges = int(example_config["max_example_edges_preferred"])

    candidates: dict[str, list[tuple[tuple, dict, str]]] = {
        "stable": [],
        "split": [],
        "merge": [],
        "complex": [],
    }
    pattern_counts = Counter()
    one_to_one_below_stable = 0

    for component in components:
        source_ids = set(component["source_geo_uids"])
        target_ids = set(component["target_geo_uids"])
        rows = positive.loc[
            positive["source_geo_uid"].isin(source_ids)
            & positive["target_geo_uid"].isin(target_ids)
        ].copy()
        source_count = int(component["source_count"])
        target_count = int(component["target_count"])
        shape = _component_shape(source_count, target_count)

        source_coverage = rows.groupby("source_geo_uid")["overlap_share_of_source"].sum()
        target_coverage = rows.groupby("target_geo_uid")["overlap_share_of_target"].sum()
        min_source_coverage = float(source_coverage.min())
        min_target_coverage = float(target_coverage.min())

        if shape == "1x1":
            row = rows.iloc[0]
            mutual_min = min(
                float(row["overlap_share_of_source"]),
                float(row["overlap_share_of_target"]),
            )
            if mutual_min >= stable_min:
                pattern_counts["stable"] += 1
                rank = (
                    0 if bool(row["same_native_id"]) else 1,
                    -mutual_min,
                    str(row["source_geo_uid"]),
                )
                candidates["stable"].append(
                    (
                        rank,
                        component,
                        (
                            "1x1 connected component with both overlap shares at or above "
                            f"{stable_min}; equal native IDs are not sufficient by themselves."
                        ),
                    )
                )
            else:
                one_to_one_below_stable += 1
        elif shape == "1xN":
            pattern_counts["split"] += 1
            rank = (
                target_count,
                int(component["edge_count"]),
                -min_source_coverage,
                component["source_geo_uids"][0],
            )
            candidates["split"].append(
                (
                    rank,
                    component,
                    (
                        "One 2010 source is connected by positive area to multiple 2022 targets; "
                        "the label is a versioned structural interpretation, not allocation."
                    ),
                )
            )
        elif shape == "Nx1":
            pattern_counts["merge"] += 1
            rank = (
                source_count,
                int(component["edge_count"]),
                -min_target_coverage,
                component["target_geo_uids"][0],
            )
            candidates["merge"].append(
                (
                    rank,
                    component,
                    (
                        "Multiple 2010 sources are connected by positive area to one 2022 target; "
                        "the label is a versioned structural interpretation, not allocation."
                    ),
                )
            )
        else:
            pattern_counts["complex"] += 1
            edge_count = int(component["edge_count"])
            rank = (
                0 if edge_count <= preferred_max_edges else 1,
                edge_count,
                source_count + target_count,
                -min(min_source_coverage, min_target_coverage),
                component["source_geo_uids"][0],
            )
            candidates["complex"].append(
                (
                    rank,
                    component,
                    (
                        "Connected positive-overlap component with multiple sources and multiple "
                        "targets; this is genuinely N:M rather than a one-sided split or merge."
                    ),
                )
            )

    examples = {}
    for pattern in ("stable", "split", "merge", "complex"):
        entries = sorted(candidates[pattern], key=lambda item: item[0])
        if not entries:
            examples[pattern] = None
            continue
        _, component, basis = entries[0]
        examples[pattern] = _component_record(
            relation,
            component,
            pattern=pattern,
            interpretation_basis=basis,
        )

    broad_shapes, exact_shapes = _component_shape_distributions(components)
    return {
        "interpretation_version": example_config["interpretation_version"],
        "stored_on_relation_rows": False,
        "scope": (
            "Versioned derived interpretation of connected positive-overlap components for "
            "human inspection. Relation rows remain unclassified geometric facts."
        ),
        "thresholds": {
            "minimum_overlap_area_m2": float(config["minimum_overlap_area_m2"]),
            "stable_mutual_overlap_min": stable_min,
            "max_example_edges_preferred": preferred_max_edges,
        },
        "component_shape_distribution": broad_shapes,
        "component_exact_size_distribution": exact_shapes,
        "derived_pattern_counts": {
            "stable": int(pattern_counts["stable"]),
            "split": int(pattern_counts["split"]),
            "merge": int(pattern_counts["merge"]),
            "complex": int(pattern_counts["complex"]),
            "one_to_one_below_stable_threshold": int(one_to_one_below_stable),
        },
        "examples": examples,
    }


def build_relation(
    ceur_2010: gpd.GeoDataFrame,
    ceur_2022: gpd.GeoDataFrame,
    config: dict,
) -> tuple[pd.DataFrame, dict]:
    source = ceur_2010.rename(columns={"geo_uid": "source_geo_uid"}).copy()
    target = ceur_2022.rename(columns={"geo_uid": "target_geo_uid"}).copy()

    required_source = {"source_geo_uid", "native_id", "geometry_role", "geometry"}
    required_target = {"target_geo_uid", "native_id", "geometry_role", "geometry"}
    source_missing = sorted(required_source - set(source.columns))
    target_missing = sorted(required_target - set(target.columns))
    if source_missing:
        raise ValueError(f"CEUR 2010 source parent is missing fields: {source_missing}")
    if target_missing:
        raise ValueError(f"CEUR 2022 target parent is missing fields: {target_missing}")

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

    # A5 and A10 already needed this same neutral mechanic. Keep it local in A11 and
    # record the repeated-use promotion case under TOOL_PROMOTION_POLICY.md.
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
    source_candidate_counts = (
        relation.groupby("source_geo_uid")["source_candidate_count"]
        .first()
        .reindex(source.loc[source_analytical, "source_geo_uid"], fill_value=0)
        .fillna(0)
        .astype(int)
    )
    target_candidate_counts = (
        target_counts.reindex(target_analytical["target_geo_uid"], fill_value=0)
        .astype(int)
    )

    coverage_tolerance = float(config["coverage_tolerance"])
    source_coverage_counts = _coverage_counts(source_coverage, coverage_tolerance)
    target_coverage_counts = _coverage_counts(target_coverage, coverage_tolerance)

    same_id_tolerance = float(config["same_id_mutual_full_overlap_tolerance"])
    same_id_mask = positive_relation["same_native_id"].fillna(False)
    same_id_rows = positive_relation.loc[same_id_mask]
    mutual_full = (
        same_id_rows["overlap_share_of_source"].astype(float).ge(1.0 - same_id_tolerance)
        & same_id_rows["overlap_share_of_target"].astype(float).ge(1.0 - same_id_tolerance)
    )

    components = _positive_components(relation)
    broad_shapes, exact_shapes = _component_shape_distributions(components)
    referenced_targets = int(positive_relation["target_geo_uid"].nunique())
    audit = {
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
        "source_multiplicity_distribution": _multiplicity_distribution(
            source_candidate_counts
        ),
        "referenced_analytical_targets": referenced_targets,
        "unreferenced_analytical_targets": len(target_analytical) - referenced_targets,
        "target_matched_single": int((target_candidate_counts == 1).sum()),
        "target_matched_multiple": int((target_candidate_counts > 1).sum()),
        "target_multiplicity_distribution": _multiplicity_distribution(
            target_candidate_counts
        ),
        "source_total_overlap_share_quantiles": _quantiles(source_coverage),
        "target_total_overlap_share_quantiles": _quantiles(target_coverage),
        "source_coverage_counts": source_coverage_counts,
        "target_coverage_counts": target_coverage_counts,
        "coverage_tolerance": coverage_tolerance,
        "positive_same_native_id_rows": int(same_id_mask.sum()),
        "positive_different_native_id_rows": int((~same_id_mask).sum()),
        "same_native_id_mutual_full_overlap_rows": int(mutual_full.sum()),
        "same_native_id_geometry_difference_rows": int((~mutual_full).sum()),
        "same_id_mutual_full_overlap_tolerance": same_id_tolerance,
        "positive_component_count": len(components),
        "component_shape_distribution": broad_shapes,
        "component_exact_size_distribution": exact_shapes,
        "total_positive_overlap_area_m2": float(
            positive_relation["overlap_area_m2"].astype(float).sum()
        ),
        "analysis_crs": config["analysis_crs"],
        "minimum_overlap_area_m2": float(config["minimum_overlap_area_m2"]),
        "target_side_overlap_share_required": True,
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
        "foundation_kernel": config["foundation_kernel"],
        "analysis_crs": config["analysis_crs"],
        "minimum_overlap_area_m2": config["minimum_overlap_area_m2"],
        "coverage_tolerance": config["coverage_tolerance"],
        "same_id_mutual_full_overlap_tolerance": config[
            "same_id_mutual_full_overlap_tolerance"
        ],
        "derived_examples": config["derived_examples"],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"2010-2022-ceur-{digest[:12]}"


def _examples_markdown(examples: dict) -> str:
    lines = [
        "# CEUR 2010 → 2022 illustrative longitudinal patterns",
        "",
        "These labels are a versioned derived interpretation for human inspection only. ",
        "The relation artifact itself contains unclassified N:M geometric facts.",
        "",
        f"Interpretation version: `{examples['interpretation_version']}`",
        "",
        "Thresholds:",
        "",
        f"- minimum positive overlap area: `{examples['thresholds']['minimum_overlap_area_m2']}` m²",
        f"- stable mutual-overlap minimum: `{examples['thresholds']['stable_mutual_overlap_min']}`",
        "",
        "Derived component counts: ",
        f"`{json.dumps(examples['derived_pattern_counts'], sort_keys=True)}`",
        "",
    ]
    for pattern in ("stable", "split", "merge", "complex"):
        example = examples["examples"][pattern]
        lines.extend([f"## {pattern}", ""])
        if example is None:
            lines.extend(["No example found under the versioned selection rule.", ""])
            continue
        lines.extend(
            [
                example["interpretation_basis"],
                "",
                f"- sources: **{example['source_count']}**",
                f"- targets: **{example['target_count']}**",
                f"- positive-overlap edges: **{example['edge_count']}**",
                f"- source native IDs: `{[item['native_id'] for item in example['sources']]}`",
                f"- target native IDs: `{[item['native_id'] for item in example['targets']]}`",
                "",
                "Edges:",
                "",
            ]
        )
        for edge in example["edges"]:
            lines.append(
                "- "
                f"`{edge['source_native_id']}` → `{edge['target_native_id']}`; "
                f"area={edge['overlap_area_m2']:.3f} m²; "
                f"source_share={edge['overlap_share_of_source']:.9f}; "
                f"target_share={edge['overlap_share_of_target']:.9f}; "
                f"same_id={edge['same_native_id']}"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def _summary_markdown(
    audit: dict,
    source_dataset: DatasetRef,
    target_dataset: DatasetRef,
    config: dict,
    examples: dict,
) -> str:
    return f"""# CEUR Census 2010 → 2022 radio relation summary

This release contains **explicit N:M geometric relation facts** between two exact harmonized CEUR releases. It contains no population allocation, transfer weights, preferred geography, or one-to-one crosswalk.

## Exact parents

- Source: `{source_dataset.dataset_id}` `{source_dataset.version}`
  - source snapshot SHA-256: `{config['source_parent']['source_snapshot_sha256']}`
  - normalized geography SHA-256: `{source_dataset.content_sha256}`
- Target: `{target_dataset.dataset_id}` `{target_dataset.version}`
  - source snapshot SHA-256: `{config['target_parent']['source_snapshot_sha256']}`
  - normalized geography SHA-256: `{target_dataset.content_sha256}`

## Relation size and multiplicity

- Source parent rows: **{audit['source_parent_rows']:,}**
- Source analytical rows: **{audit['source_analytical_rows']:,}**
- Source-invalid rows: **{audit['source_invalid_geometry_rows']:,}**
- Target parent rows: **{audit['target_parent_rows']:,}**
- Target analytical rows: **{audit['target_analytical_rows']:,}**
- Target-invalid rows excluded as targets: **{audit['target_invalid_geometry_rows']:,}**
- Positive overlap rows: **{audit['positive_relation_rows']:,}**
- Source multiplicity: `{json.dumps(audit['source_multiplicity_distribution'], sort_keys=True)}`
- Target multiplicity: `{json.dumps(audit['target_multiplicity_distribution'], sort_keys=True)}`
- Connected component shapes: `{json.dumps(audit['component_shape_distribution'], sort_keys=True)}`

## Coverage QA

- Source coverage counts: `{json.dumps(audit['source_coverage_counts'], sort_keys=True)}`
- Target coverage counts: `{json.dumps(audit['target_coverage_counts'], sort_keys=True)}`
- Source total-overlap-share quantiles: `{json.dumps(audit['source_total_overlap_share_quantiles'], sort_keys=True)}`
- Target total-overlap-share quantiles: `{json.dumps(audit['target_total_overlap_share_quantiles'], sort_keys=True)}`
- Total positive overlap area: **{audit['total_positive_overlap_area_m2']:.3f} m²**
- Coverage tolerance: `{audit['coverage_tolerance']}`

## Equal identifiers are not geometry equivalence

Among positive overlaps, **{audit['positive_same_native_id_rows']:,}** rows have equal native nine-digit IDs and **{audit['positive_different_native_id_rows']:,}** do not. Of the equal-ID rows, **{audit['same_native_id_mutual_full_overlap_rows']:,}** mutually cover both polygons within tolerance and **{audit['same_native_id_geometry_difference_rows']:,}** differ geometrically in at least one direction. Equal IDs are therefore never used as a geometry-equivalence shortcut.

## Human-readable patterns

The separate `pattern_examples.*` artifact uses interpretation version `{examples['interpretation_version']}`. It stores no classification on relation rows. Its derived counts are `{json.dumps(examples['derived_pattern_counts'], sort_keys=True)}` and it includes bounded examples of stable, split, merge, and genuinely complex connected components.

## Interpretation boundary

`overlap_area_m2`, `overlap_share_of_source`, and `overlap_share_of_target` are geometric facts measured in `{audit['analysis_crs']}`. Source and target multiplicities remain explicit. No population, household, housing, or other attribute is used to allocate observations between vintages.
"""


def materialize_relation(
    source_release: Path,
    target_release: Path,
    output: Path,
    config_path: Path = DEFAULT_CONFIG,
) -> dict:
    config = load_config(config_path)
    source, source_manifest, source_dataset = _load_parent(
        source_release,
        config["source_parent"],
        verify=verify_ceur_2010_release,
        label="CEUR 2010 source parent",
    )
    target, target_manifest, target_dataset = _load_parent(
        target_release,
        config["target_parent"],
        verify=verify_ceur_2022_release,
        label="CEUR 2022 target parent",
    )

    relation, audit = build_relation(source, target, config)
    examples = build_pattern_examples(relation, config)
    missing_examples = [
        name for name, value in examples["examples"].items() if value is None
    ]
    if missing_examples:
        raise ValueError(
            "A11 requires bounded human-readable examples for all patterns; missing "
            f"{missing_examples}"
        )

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
                "message": "CEUR 2010 source-invalid polygons remain explicit invalid-source rows.",
            }
        )
    if audit["target_invalid_geometry_rows"]:
        warnings_list.append(
            {
                "code": "target_parent_invalid_geometry_excluded",
                "affected_rows": audit["target_invalid_geometry_rows"],
                "message": "CEUR 2022 source-invalid polygons are excluded from analytical targets.",
            }
        )
    for side in ("source", "target"):
        coverage = audit[f"{side}_coverage_counts"]
        if coverage["zero"]:
            warnings_list.append(
                {
                    "code": f"{side}_zero_coverage",
                    "affected_rows": coverage["zero"],
                    "message": f"{side.title()} analytical units with zero retained positive overlap remain explicit.",
                }
            )
        if coverage["over_one"]:
            warnings_list.append(
                {
                    "code": f"{side}_coverage_over_one",
                    "affected_rows": coverage["over_one"],
                    "message": f"{side.title()} total overlap share exceeds one beyond tolerance for some units.",
                }
            )

    audit["stage_decision"] = "PASS_WITH_WARNINGS" if warnings_list else "PASS"
    qa_state = "YELLOW" if warnings_list else "GREEN"
    qa_result = QAResult(
        check_id="ceur_2010_2022_radio_relation_contract",
        state=qa_state,
        message=(
            "CEUR 2010→2022 N:M relation is publishable with explicit coverage/geometry warnings."
            if warnings_list
            else "CEUR 2010→2022 N:M relation satisfies the geometric relation boundary."
        ),
        metrics={
            "source_parent_rows": audit["source_parent_rows"],
            "target_parent_rows": audit["target_parent_rows"],
            "positive_relation_rows": audit["positive_relation_rows"],
            "matched_single": audit["matched_single"],
            "matched_multiple": audit["matched_multiple"],
            "target_matched_single": audit["target_matched_single"],
            "target_matched_multiple": audit["target_matched_multiple"],
            "source_zero_coverage": audit["source_coverage_counts"]["zero"],
            "target_zero_coverage": audit["target_coverage_counts"]["zero"],
            "complex_component_count": examples["derived_pattern_counts"]["complex"],
        },
    )
    now = datetime.now(UTC)
    run = RunManifest(
        run_id=f"ceur-2010-2022-relation:{version}",
        package="argentina-geography",
        package_version=package_version(),
        started_at=now,
        finished_at=now,
        inputs=(source_dataset, target_dataset),
        parameters={
            "relation_method": "spatial_foundation.geography.relate_areal_objects",
            "relation_cardinality": "N:M",
            "analysis_crs": config["analysis_crs"],
            "minimum_overlap_area_m2": config["minimum_overlap_area_m2"],
            "target_side_overlap_share": "local_a11_fact",
            "derived_examples_interpretation_version": examples[
                "interpretation_version"
            ],
            "population_allocation_applied": False,
            "transfer_weights_applied": False,
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
                "source_content_sha256": source_dataset.content_sha256,
                "target_dataset_id": target_dataset.dataset_id,
                "target_release_version": target_dataset.version,
                "target_content_sha256": target_dataset.content_sha256,
                "authority_status": "derived_geometric_fact",
                "relation_method": "areal_positive_overlap",
                "relation_cardinality": "N:M",
                "analysis_crs": config["analysis_crs"],
                "row_count": len(relation),
                "positive_relation_rows": audit["positive_relation_rows"],
                "qa_state": qa_state,
                "stage_decision": audit["stage_decision"],
                "derived_examples_interpretation_version": examples[
                    "interpretation_version"
                ],
                "artifact_ref": "relations.parquet",
                "manifest_ref": "manifest.json",
            }
        ]
    )
    catalog.to_parquet(output / "relation_catalog.parquet", index=False)
    write_json(output / "qa.json", {**audit, "accepted_warnings": warnings_list})
    write_json(output / "pattern_examples.json", examples)
    (output / "pattern_examples.md").write_text(
        _examples_markdown(examples), encoding="utf-8"
    )
    write_json(
        output / "relation_summary.json",
        {
            "relation_id": config["relation_id"],
            "relation_cardinality": "N:M",
            "source_parent": {
                "dataset": source_dataset.model_dump(mode="json"),
                "source_snapshot": source_manifest["source_snapshot"],
            },
            "target_parent": {
                "dataset": target_dataset.model_dump(mode="json"),
                "source_snapshot": target_manifest["source_snapshot"],
            },
            "audit": audit,
            "derived_examples": {
                "interpretation_version": examples["interpretation_version"],
                "derived_pattern_counts": examples["derived_pattern_counts"],
                "thresholds": examples["thresholds"],
            },
            "interpretation": config["interpretation"],
            "known_limitations": config["known_limitations"],
        },
    )
    (output / "relation_summary.md").write_text(
        _summary_markdown(audit, source_dataset, target_dataset, config, examples),
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
            "source_snapshot": source_manifest["source_snapshot"],
            "target_dataset": target_dataset.model_dump(mode="json"),
            "target_snapshot": target_manifest["source_snapshot"],
        },
        "relation_method": "spatial_foundation.geography.relate_areal_objects",
        "relation_cardinality": "N:M",
        "derived_interpretation": {
            "artifact": "pattern_examples.json",
            "version": examples["interpretation_version"],
            "stored_on_relation_rows": False,
        },
        "population_allocation_applied": False,
        "transfer_weights_applied": False,
        "adjudication_applied": False,
        "geometry_repair_applied": False,
        "row_count": len(relation),
        "positive_relation_rows": audit["positive_relation_rows"],
        "artifacts": {
            "relations": "relations.parquet",
            "catalog": "relation_catalog.parquet",
            "qa": "qa.json",
            "summary_json": "relation_summary.json",
            "summary_md": "relation_summary.md",
            "pattern_examples_json": "pattern_examples.json",
            "pattern_examples_md": "pattern_examples.md",
        },
    }
    write_json(output / "manifest.json", manifest)
    write_checksums(output, REQUIRED_OUTPUT_FILES)
    return manifest


def verify_relation(output: Path, config_path: Path = DEFAULT_CONFIG) -> None:
    config = load_config(config_path)
    verify_checksums(output)
    manifest = validate_manifest(output / "manifest.json")
    dataset = DatasetRef.model_validate(manifest["dataset"])
    relation = pd.read_parquet(output / manifest["artifacts"]["relations"])
    examples = read_json(output / manifest["artifacts"]["pattern_examples_json"])

    if dataset.dataset_id != config["relation_id"]:
        raise ValueError("relation dataset_id does not match configured relation")
    if sha256_file(output / manifest["artifacts"]["relations"]) != dataset.content_sha256:
        raise ValueError("relation content hash mismatch")
    if len(relation) != manifest["row_count"]:
        raise ValueError("relation row count does not match manifest")
    if manifest.get("relation_cardinality") != "N:M":
        raise ValueError("A11 relation must explicitly declare N:M cardinality")

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
    positive_relation = relation.loc[positive]
    if positive_relation["overlap_area_m2"].astype(float).le(0).any():
        raise ValueError("positive relation rows must have positive overlap area")
    for field in ("overlap_share_of_source", "overlap_share_of_target"):
        values = positive_relation[field].astype(float)
        if values.le(0).any() or values.gt(1.0 + 1e-9).any():
            raise ValueError(f"{field} must be within (0, 1] on positive rows")
    if positive_relation["target_native_id"].isna().any():
        raise ValueError("positive relation rows require target_native_id")

    source_counts = positive_relation.groupby("source_geo_uid").size()
    observed_source_counts = positive_relation["source_geo_uid"].map(source_counts)
    if not (
        positive_relation["source_candidate_count"].astype(int).to_numpy()
        == observed_source_counts.astype(int).to_numpy()
    ).all():
        raise ValueError("source_candidate_count is inconsistent with positive N:M facts")
    target_counts = positive_relation.groupby("target_geo_uid").size()
    observed_target_counts = positive_relation["target_geo_uid"].map(target_counts)
    if not (
        positive_relation["target_candidate_count"].astype(int).to_numpy()
        == observed_target_counts.astype(int).to_numpy()
    ).all():
        raise ValueError("target_candidate_count is inconsistent with positive N:M facts")

    expected_same = (
        positive_relation["source_native_id"].astype(str).to_numpy()
        == positive_relation["target_native_id"].astype(str).to_numpy()
    )
    if not (
        positive_relation["same_native_id"].astype(bool).to_numpy() == expected_same
    ).all():
        raise ValueError("same_native_id is inconsistent with native IDs")

    nonpositive = ~positive
    for field in (
        "overlap_area_m2",
        "overlap_share_of_source",
        "overlap_share_of_target",
        "target_candidate_count",
    ):
        if relation.loc[nonpositive, field].notna().any():
            raise ValueError(f"non-positive relation rows must not contain {field}")
    allowed_status = {
        "matched_single",
        "matched_multiple",
        "unmatched_outside",
        "invalid_geometry",
    }
    if not set(relation["relation_status"]).issubset(allowed_status):
        raise ValueError("relation contains unsupported relation_status")

    prohibited_tokens = (
        "winner",
        "selected",
        "canonical",
        "corrected",
        "nearest",
        "population",
        "allocation",
        "transfer_weight",
    )
    prohibited = [
        column
        for column in relation.columns
        if any(token in column.lower() for token in prohibited_tokens)
    ]
    if prohibited:
        raise ValueError(f"relation contains prohibited policy/allocation columns: {prohibited}")
    if any("pattern" in column.lower() for column in relation.columns):
        raise ValueError("derived pattern classification must not be stored on relation rows")

    expected_examples_version = config["derived_examples"]["interpretation_version"]
    if examples["interpretation_version"] != expected_examples_version:
        raise ValueError("derived examples interpretation version mismatch")
    if examples.get("stored_on_relation_rows") is not False:
        raise ValueError("derived examples must remain separate from geometric relation facts")
    missing_examples = [
        name for name, value in examples["examples"].items() if value is None
    ]
    if missing_examples:
        raise ValueError(f"detached A11 release is missing required examples: {missing_examples}")

    _verify_parent_binding(
        DatasetRef.model_validate(manifest["parents"]["source_dataset"]),
        manifest["parents"]["source_snapshot"],
        config["source_parent"],
        label="relation source parent",
    )
    _verify_parent_binding(
        DatasetRef.model_validate(manifest["parents"]["target_dataset"]),
        manifest["parents"]["target_snapshot"],
        config["target_parent"],
        label="relation target parent",
    )

    for field in (
        "population_allocation_applied",
        "transfer_weights_applied",
        "adjudication_applied",
        "geometry_repair_applied",
    ):
        if manifest.get(field) is not False:
            raise ValueError(f"relation manifest must declare {field}=false")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build or verify the exact CEUR Census 2010→2022 radio relation."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--source-release", type=Path, required=True)
    materialize.add_argument("--target-release", type=Path, required=True)
    materialize.add_argument("--output", type=Path, required=True)
    materialize.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--release", type=Path, required=True)
    verify.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    if args.command == "materialize":
        materialize_relation(
            args.source_release,
            args.target_release,
            args.output,
            args.config,
        )
        verify_relation(args.output, args.config)
    else:
        verify_relation(args.release, args.config)


if __name__ == "__main__":
    main()
