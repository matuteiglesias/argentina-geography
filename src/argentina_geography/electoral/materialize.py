from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from empirical_contracts import QAResult, RunManifest

from argentina_geography.electoral.config import (
    DEFAULT_CONFIG,
    _load_parents,
    _snapshot_sha,
    load_config,
)
from argentina_geography.electoral.core import (
    _dataset,
    _relation_catalog,
    _summary_text,
    _version_payload,
    build_products,
)
from argentina_geography.electoral.evidence import (
    compare_historical_radio_crosswalk,
    compare_historical_section_crosswalk,
    elecciones_compatibility,
)
from argentina_geography.product_writer import package_version
from argentina_geography.products import sha256_file, write_checksums, write_json

CORE_OUTPUT_FILES = [
    "relations.parquet",
    "section_department_relations.parquet",
    "district_province_bridge.parquet",
    "nonstandard_coverage_relations.parquet",
    "electoral_districts.parquet",
    "electoral_sections.parquet",
    "electoral_circuits.parquet",
    "input_status.parquet",
    "province_qa.parquet",
    "relation_catalog.parquet",
    "historical_policy_registry.json",
    "qa.json",
    "summary.md",
    "manifest.json",
]

def materialize_vertical(
    census_release: Path,
    circuit_release: Path,
    output: Path,
    vintage: str,
    *,
    config_path: Path = DEFAULT_CONFIG,
    historical_radio_crosswalk: Path | None = None,
    historical_section_crosswalk: Path | None = None,
    elecciones_circuit_table: Path | None = None,
) -> dict:
    config = load_config(config_path)
    (
        census,
        circuits,
        census_dataset,
        circuit_dataset,
        census_manifest,
        circuit_manifest,
    ) = _load_parents(census_release, circuit_release, vintage, config)

    products = build_products(census, circuits, vintage, config)
    output.mkdir(parents=True, exist_ok=True)

    artifact_frames = {
        "relations.parquet": products["radio_relation"],
        "section_department_relations.parquet": products["section_relation"],
        "district_province_bridge.parquet": products["bridge"],
        "nonstandard_coverage_relations.parquet": products["nonstandard_relation"],
        "electoral_districts.parquet": products["districts"],
        "electoral_sections.parquet": products["sections"],
        "electoral_circuits.parquet": products["circuits_dim"],
        "input_status.parquet": products["input_status"],
        "province_qa.parquet": products["province_qa"],
    }
    for name, frame in artifact_frames.items():
        frame.to_parquet(output / name, index=False)

    digest = _version_payload(vintage, census_dataset, circuit_dataset, config)
    version = f"2010-{vintage}-{digest[:12]}"
    relation_ids = {
        key: value.format(vintage=vintage) for key, value in config["relation_ids"].items()
    }
    datasets = {
        "radio_circuit": _dataset(
            relation_ids["radio_circuit"],
            version,
            sha256_file(output / "relations.parquet"),
            ("source_geo_uid", "target_electoral_uid"),
        ),
        "section_department": _dataset(
            relation_ids["section_department"],
            version,
            sha256_file(output / "section_department_relations.parquet"),
            ("source_electoral_section_uid", "target_department_footprint_uid"),
        ),
        "district_province": _dataset(
            relation_ids["district_province"],
            version,
            sha256_file(output / "district_province_bridge.parquet"),
            ("electoral_district_uid", "province_2010_id"),
        ),
    }
    catalog = _relation_catalog(
        config,
        vintage,
        version,
        datasets,
        products["radio_relation"],
        products["section_relation"],
    )
    catalog.to_parquet(output / "relation_catalog.parquet", index=False)

    policy_registry = {
        "evidence_repository": config["historical_evidence"]["repository"],
        "evidence_commit_sha": config["historical_evidence"]["commit_sha"],
        "artifacts": config["historical_evidence"]["artifacts"],
        "policies": config["historical_evidence"]["policies"],
        "current_policy_boundary": config["policy_boundary"],
    }
    write_json(output / "historical_policy_registry.json", policy_registry)

    evidence_summaries: dict[str, object] = {}
    optional_artifacts: dict[str, str] = {}
    if historical_radio_crosswalk is not None:
        comparison, summary = compare_historical_radio_crosswalk(
            products["radio_relation"], historical_radio_crosswalk
        )
        comparison.to_parquet(output / "historical_radio_comparison.parquet", index=False)
        write_json(output / "historical_radio_comparison.json", summary)
        optional_artifacts.update(
            {
                "historical_radio_comparison": "historical_radio_comparison.parquet",
                "historical_radio_comparison_summary": "historical_radio_comparison.json",
            }
        )
        evidence_summaries["historical_radio"] = summary

    if historical_section_crosswalk is not None:
        comparison, summary = compare_historical_section_crosswalk(
            products["section_relation"], historical_section_crosswalk
        )
        comparison.to_parquet(output / "historical_section_comparison.parquet", index=False)
        write_json(output / "historical_section_comparison.json", summary)
        optional_artifacts.update(
            {
                "historical_section_comparison": "historical_section_comparison.parquet",
                "historical_section_comparison_summary": "historical_section_comparison.json",
            }
        )
        evidence_summaries["historical_section"] = summary

    if elecciones_circuit_table is not None:
        proof, summary = elecciones_compatibility(
            products["circuits_dim"], elecciones_circuit_table
        )
        proof.to_parquet(output / "elecciones_compatibility.parquet", index=False)
        write_json(output / "elecciones_compatibility.json", summary)
        optional_artifacts.update(
            {
                "elecciones_compatibility": "elecciones_compatibility.parquet",
                "elecciones_compatibility_summary": "elecciones_compatibility.json",
            }
        )
        evidence_summaries["elecciones_ARG"] = summary

    qa = products["qa"]
    qa["historical_evidence_summaries"] = evidence_summaries
    write_json(output / "qa.json", qa)

    summary = _summary_text(
        vintage,
        qa,
        datasets,
        census_dataset,
        circuit_dataset,
        evidence_summaries,
    )
    (output / "summary.md").write_text(summary, encoding="utf-8")

    qa_result = QAResult(
        check_id=f"argentina_electoral_vertical_{vintage}",
        state="YELLOW",
        message=(
            "Electoral hierarchy and cross-authority relations are publishable with "
            "source limitations and ambiguity retained explicitly."
        ),
        metrics={
            "census_radio_count": qa["census_radio_count"],
            "electoral_district_count": qa["electoral_district_count"],
            "electoral_section_count": qa["electoral_section_count"],
            "derived_circuit_target_count": qa["derived_circuit_target_count"],
            "cross_province_radio_circuit_rows": qa[
                "cross_province_radio_circuit_rows"
            ],
            "cross_province_section_department_rows": qa[
                "cross_province_section_department_rows"
            ],
        },
    )
    now = datetime.now(UTC)
    run = RunManifest(
        run_id=f"argentina-electoral-vertical:{version}",
        package="argentina-geography",
        package_version=package_version(),
        started_at=now,
        finished_at=now,
        inputs=(census_dataset, circuit_dataset),
        parameters={
            "analysis_crs": config["analysis_crs"],
            "minimum_overlap_area_m2": config["minimum_overlap_area_m2"],
            "relation_method": config["foundation_kernel"]["callable"],
            "statistical_and_electoral_namespaces_collapsed": False,
            "adjudication_applied": False,
            "crosswalk_published": False,
            "geometry_repair_applied": False,
            "historical_policies_status": "regression_only",
        },
        outputs=tuple(datasets.values()),
        qa=(qa_result,),
    )
    manifest = {
        "product_type": "electoral_vertical",
        "schema_version": config["schema_version"],
        "vintage": vintage,
        "stage_decision": qa["stage_decision"],
        "dataset": datasets["radio_circuit"].model_dump(mode="json"),
        "datasets": {
            key: dataset.model_dump(mode="json") for key, dataset in datasets.items()
        },
        "run": run.model_dump(mode="json"),
        "parents": {
            "census": {
                "dataset": census_dataset.model_dump(mode="json"),
                "source_snapshot_sha256": _snapshot_sha(census_manifest),
            },
            "circuits": {
                "dataset": circuit_dataset.model_dump(mode="json"),
                "source_snapshot_sha256": _snapshot_sha(circuit_manifest),
                "source_commit_sha": circuit_manifest.get("source_commit_sha"),
                "source_tree_sha": circuit_manifest.get("source_tree_sha"),
            },
        },
        "policy_boundary": config["policy_boundary"],
        "artifacts": {
            "relations": "relations.parquet",
            "section_department_relations": "section_department_relations.parquet",
            "district_province_bridge": "district_province_bridge.parquet",
            "nonstandard_coverage_relations": "nonstandard_coverage_relations.parquet",
            "electoral_districts": "electoral_districts.parquet",
            "electoral_sections": "electoral_sections.parquet",
            "electoral_circuits": "electoral_circuits.parquet",
            "input_status": "input_status.parquet",
            "province_qa": "province_qa.parquet",
            "catalog": "relation_catalog.parquet",
            "historical_policy_registry": "historical_policy_registry.json",
            "qa": "qa.json",
            "summary": "summary.md",
            **optional_artifacts,
        },
    }
    write_json(output / "manifest.json", manifest)

    checksum_files = list(CORE_OUTPUT_FILES)
    checksum_files.extend(optional_artifacts.values())
    checksum_files = sorted(set(checksum_files))
    write_checksums(output, checksum_files)
    return manifest
