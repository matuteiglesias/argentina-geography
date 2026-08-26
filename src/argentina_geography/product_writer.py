from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
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

from .products import sha256_file, write_checksums, write_json

FIXTURE_TIME = datetime(2026, 8, 4, 0, 0, tzinfo=timezone.utc)


def package_version() -> str:
    try:
        return version("argentina-geography")
    except PackageNotFoundError:
        return "0.1.0"


def source_snapshot(path: Path, *, source: str) -> SourceSnapshotRef:
    digest = sha256_file(path)
    return SourceSnapshotRef(
        source=source,
        release="fixture-v1",
        snapshot_id=f"sha256:{digest}",
        origin="repository synthetic fixture",
        storage_mode="managed",
        files=(
            SourceFileRef(path=path.name, sha256=digest, size_bytes=path.stat().st_size),
        ),
    )


def write_geography_bundle(
    directory: Path,
    frame: gpd.GeoDataFrame,
    *,
    dataset_id: str,
    geography: GeographySpec,
    snapshot: SourceSnapshotRef,
    qa_metrics: dict,
) -> DatasetRef:
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / "geography.parquet"
    frame.to_parquet(artifact, index=False)
    dataset = DatasetRef(
        dataset_id=dataset_id,
        version="fixture-v1",
        schema_version="arggeo.geography/v1",
        layer=DataLayer.SILVER,
        authority=AuthorityLevel.L1_NORMALIZED,
        grain=GrainSpec(keys=("geo_uid",)),
        geography=geography,
        content_sha256=sha256_file(artifact),
    )
    qa = QAResult(
        check_id="fixture_geography_contract",
        state="GREEN",
        message="Synthetic geography release satisfies the A1 product boundary.",
        metrics=qa_metrics,
    )
    run = RunManifest(
        run_id=f"fixture:{dataset_id}:v1",
        package="argentina-geography",
        package_version=package_version(),
        started_at=FIXTURE_TIME,
        finished_at=FIXTURE_TIME,
        inputs=(snapshot,),
        parameters={"fixture_only": True},
        outputs=(dataset,),
        qa=(qa,),
    )
    manifest = {
        "product_type": "geography",
        "authority_status": "synthetic_fixture",
        "distribution_mode": "redistributed_snapshot",
        "dataset": dataset.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "row_count": len(frame),
        "artifacts": {"geography": "geography.parquet", "qa": "qa.json"},
        "limitations": ["Synthetic fixture only; no substantive Argentina geography claim."],
    }
    write_json(directory / "qa.json", qa_metrics)
    write_json(directory / "manifest.json", manifest)
    write_checksums(directory, ["geography.parquet", "manifest.json", "qa.json"])
    return dataset


def write_relation_bundle(
    directory: Path,
    relation: pd.DataFrame,
    *,
    source_dataset: DatasetRef,
    target_dataset: DatasetRef,
    qa_metrics: dict,
    policy: dict,
) -> DatasetRef:
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / "relations.parquet"
    relation.to_parquet(artifact, index=False)
    dataset = DatasetRef(
        dataset_id="arggeo.fixture.census-admin-relation",
        version="fixture-v1",
        schema_version="arggeo.relation/v1",
        layer=DataLayer.GOLD,
        authority=AuthorityLevel.L2_DERIVED,
        grain=GrainSpec(keys=("source_geo_uid", "target_geo_uid")),
        content_sha256=sha256_file(artifact),
    )
    qa = QAResult(
        check_id="fixture_relation_contract",
        state="GREEN",
        message="Foundation relation facts are persisted before adjudication.",
        metrics=qa_metrics,
    )
    run = RunManifest(
        run_id="fixture:arggeo.fixture.census-admin-relation:v1",
        package="argentina-geography",
        package_version=package_version(),
        started_at=FIXTURE_TIME,
        finished_at=FIXTURE_TIME,
        inputs=(source_dataset, target_dataset),
        parameters={
            "area_crs": policy["analysis_crs"],
            "minimum_area_m2": policy["intersection"]["minimum_area_m2"],
            "adjudication_applied": False,
        },
        outputs=(dataset,),
        qa=(qa,),
    )
    manifest = {
        "product_type": "relation",
        "authority_status": "derived_geometric_fact",
        "dataset": dataset.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "parents": {
            "source_dataset_id": source_dataset.dataset_id,
            "source_version": source_dataset.version,
            "target_dataset_id": target_dataset.dataset_id,
            "target_version": target_dataset.version,
        },
        "relation_method": "spatial_foundation.geography.relate_areal_objects",
        "row_count": len(relation),
        "artifacts": {"relations": "relations.parquet", "qa": "qa.json"},
    }
    write_json(directory / "qa.json", qa_metrics)
    write_json(directory / "manifest.json", manifest)
    write_checksums(directory, ["relations.parquet", "manifest.json", "qa.json"])
    return dataset


def write_crosswalk_bundle(
    directory: Path,
    crosswalk: pd.DataFrame,
    *,
    relation_dataset: DatasetRef,
    qa_metrics: dict,
    policy: dict,
) -> DatasetRef:
    directory.mkdir(parents=True, exist_ok=True)
    artifact = directory / "crosswalk.parquet"
    crosswalk.to_parquet(artifact, index=False)
    dataset = DatasetRef(
        dataset_id="arggeo.fixture.census-admin-crosswalk",
        version="fixture-v1",
        schema_version="arggeo.crosswalk/v1",
        layer=DataLayer.GOLD,
        authority=AuthorityLevel.L2_DERIVED,
        grain=GrainSpec(keys=("source_geo_uid",)),
        content_sha256=sha256_file(artifact),
    )
    qa = QAResult(
        check_id="fixture_crosswalk_contract",
        state="GREEN",
        message="Fixture adjudication is a separate policy-bound product.",
        metrics=qa_metrics,
    )
    run = RunManifest(
        run_id="fixture:arggeo.fixture.census-admin-crosswalk:v1",
        package="argentina-geography",
        package_version=package_version(),
        started_at=FIXTURE_TIME,
        finished_at=FIXTURE_TIME,
        inputs=(relation_dataset,),
        parameters={
            "policy_id": policy["policy_id"],
            "policy_version": policy["methodology_version"],
            "minimum_winner_share": policy["intersection"]["minimum_winner_share"],
            "tie_tolerance_m2": policy["intersection"]["tie_tolerance_m2"],
        },
        outputs=(dataset,),
        qa=(qa,),
    )
    manifest = {
        "product_type": "crosswalk",
        "authority_status": "research_interpretation",
        "dataset": dataset.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "parent_relation": relation_dataset.model_dump(mode="json"),
        "policy": {
            "policy_id": policy["policy_id"],
            "policy_version": policy["methodology_version"],
        },
        "row_count": len(crosswalk),
        "artifacts": {"crosswalk": "crosswalk.parquet", "qa": "qa.json"},
    }
    write_json(directory / "qa.json", qa_metrics)
    write_json(directory / "manifest.json", manifest)
    write_checksums(directory, ["crosswalk.parquet", "manifest.json", "qa.json"])
    return dataset
