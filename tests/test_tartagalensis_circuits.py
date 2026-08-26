from __future__ import annotations

import json
import shutil
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Polygon, mapping

from argentina_geography.products import read_json
from argentina_geography.sources.tartagalensis_circuits import (
    DEFAULT_CONFIG,
    compatibility_evidence,
    load_config,
    materialize_from_source_dir,
    verify_release,
)


def _synthetic_config(tmp_path: Path) -> Path:
    config = load_config(DEFAULT_CONFIG)
    config["commit_sha"] = "a" * 40
    config["dataset_version"] = "synthetic"
    for vintage in ("2021", "2025"):
        config["vintages"][vintage]["tree_sha"] = vintage[0] * 40
        config["vintages"][vintage]["expected_unique_standard_circuits"] = {
            item["codprov"]: 1 for item in config["districts"]
        }
        config["vintages"][vintage].pop("documented_null_coddepto_features", None)
    config["cross_vintage_code_compatibility_evidence"][
        "expected_common_standard_codes"
    ] = {item["codprov"]: 1 for item in config["districts"]}
    path = tmp_path / "tartagalensis-synthetic.json"
    path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _square(x: float, y: float) -> dict:
    return mapping(
        Polygon(
            [
                (x, y),
                (x + 0.2, y),
                (x + 0.2, y + 0.2),
                (x, y + 0.2),
                (x, y),
            ]
        )
    )


def _write_source_vintage(root: Path, vintage: str, config: dict) -> Path:
    source_dir = root / vintage
    source_dir.mkdir(parents=True)
    for index, item in enumerate(config["districts"], start=1):
        codprov = item["codprov"]
        features = [
            {
                "type": "Feature",
                "properties": {
                    "circuito": "00001",
                    "codprov": codprov,
                    "coddepto": (
                        None
                        if (vintage == "2021" and codprov == "15")
                        else ("01" if codprov == "24" else "001")
                    ),
                },
                "geometry": _square(-70 + index, -40 + index / 10),
            }
        ]
        if codprov == "01":
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "circuito": "00001",
                        "codprov": codprov,
                        "coddepto": "001",
                    },
                    "geometry": _square(-70 + index + 0.3, -40 + index / 10),
                }
            )
        if codprov == "04":
            features.extend(
                [
                    {
                        "type": "Feature",
                        "properties": {
                            "circuito": "sindatos",
                            "codprov": codprov,
                            "coddepto": "002",
                        },
                        "geometry": _square(-70 + index + 0.6, -40 + index / 10),
                    },
                    {
                        "type": "Feature",
                        "properties": {
                            "circuito": "zonagris",
                            "codprov": codprov,
                            "coddepto": "002",
                        },
                        "geometry": _square(-70 + index + 0.9, -40 + index / 10),
                    },
                    {
                        "type": "Feature",
                        "properties": {
                            "circuito": "zonaincon",
                            "codprov": codprov,
                            "coddepto": "002",
                        },
                        "geometry": _square(-70 + index + 1.2, -40 + index / 10),
                    },
                ]
            )

        if codprov == "18":
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "circuito": "zonagris",
                        "codprov": codprov,
                        "coddepto": "002",
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-49.0, -31.0]],
                    },
                }
            )
        geojson = {"type": "FeatureCollection", "features": features}
        (source_dir / item["filename"]).write_text(
            json.dumps(geojson, ensure_ascii=False),
            encoding="utf-8",
        )
    return source_dir


def test_production_config_pins_exact_commit_and_paths() -> None:
    config = load_config()
    assert config["commit_sha"] == "50692fd821f825566b0589da2cc1fefdef5fa02f"
    assert config["vintages"]["2021"]["tree_sha"] == "5e0fdbf4c010b4ce25bd6ebe0b74938797638daa"
    assert config["vintages"]["2025"]["tree_sha"] == "44cb1588f49c6c51345dbce11b8fb1177eac5c99"
    assert len(config["districts"]) == 24
    assert {item["codprov"] for item in config["districts"]} == {
        f"{value:02d}" for value in range(1, 25)
    }
    source_paths = {
        config["source_path_template"].format(vintage=vintage, filename=item["filename"])
        for vintage in ("2021", "2025")
        for item in config["districts"]
    }
    assert len(source_paths) == 48
    assert all("/" in path and "main" not in path for path in source_paths)
    assert config["native_id_fields"] == ["codprov", "coddepto", "circuito"]


def test_offline_releases_preserve_identity_status_and_no_equivalence(tmp_path: Path) -> None:
    config_path = _synthetic_config(tmp_path)
    config = load_config(config_path)
    source_2021 = _write_source_vintage(tmp_path / "source", "2021", config)
    source_2025 = _write_source_vintage(tmp_path / "source", "2025", config)
    release_2021 = tmp_path / "release-2021"
    release_2025 = tmp_path / "release-2025"

    manifest_2021 = materialize_from_source_dir(
        source_2021, release_2021, "2021", config_path
    )
    manifest_2025 = materialize_from_source_dir(
        source_2025, release_2025, "2025", config_path
    )
    verify_release(release_2021, config_path)
    verify_release(release_2025, config_path)

    assert manifest_2021["dataset"]["dataset_id"] == "arggeo.tartagalensis.electoral.2021.circuit"
    assert manifest_2025["dataset"]["dataset_id"] == "arggeo.tartagalensis.electoral.2025.circuit"
    assert manifest_2021["geography_id"] != manifest_2025["geography_id"]
    assert manifest_2021["cross_vintage_equivalence_published"] is False
    assert manifest_2025["cross_vintage_equivalence_published"] is False

    frame = gpd.read_parquet(release_2021 / "geography.parquet")
    assert frame["codprov"].nunique() == 24
    repeated = frame[
        frame["source_status"].eq("assigned_circuit") & frame["circuito"].eq("00001")
    ]
    assert repeated["codprov"].nunique() == 24
    assert repeated["circuit_uid"].dropna().nunique() >= 23
    caba_parts = repeated[
        repeated["codprov"].eq("01") & repeated["coddepto"].eq("001")
    ]
    assert len(caba_parts) == 2
    assert caba_parts["circuit_uid"].nunique() == 1
    assert caba_parts["geo_uid"].nunique() == 2

    statuses = set(frame["source_status"])
    assert {"assigned_circuit", "no_data", "grey_zone", "unassigned_unknown"} <= statuses
    neuquen_missing = frame[
        frame["codprov"].eq("15")
        & frame["circuito"].eq("00001")
        & frame["coddepto"].isna()
    ]
    assert len(neuquen_missing) == 1
    assert neuquen_missing.iloc[0]["identity_status"] == "missing_coddepto"
    assert neuquen_missing.iloc[0]["circuit_uid"] is None or (
        neuquen_missing.iloc[0]["circuit_uid"] is not None
        and str(neuquen_missing.iloc[0]["circuit_uid"]) == "<NA>"
    )
    missing_department = frame[
        frame["codprov"].eq("15") & frame["circuito"].eq("00001")
    ].iloc[0]
    assert missing_department["native_id"] == "15|<missing>|00001"

    source_native_width = frame[
        frame["codprov"].eq("24") & frame["circuito"].eq("00001")
    ].iloc[0]
    assert source_native_width["coddepto"] == "01"
    assert str(source_native_width["circuit_uid"]).endswith(":24:01:00001")
    assert frame["reconstruction_status"].eq("unknown_feature_level").all()

    unreadable = frame[frame["source_geometry_parse_status"].eq("unreadable")]
    assert len(unreadable) == 1
    unreadable_row = unreadable.iloc[0]
    assert unreadable_row["codprov"] == "18"
    assert unreadable_row["geometry_role"] == "source_unreadable_geometry"
    assert unreadable_row["geometry"] is None
    assert unreadable_row["source_geometry_json"] is not None
    assert unreadable_row["source_geometry_sha256"]
    assert "point array" in unreadable_row["source_geometry_parse_error"]

    evidence_path = tmp_path / "compatibility.json"
    evidence = compatibility_evidence(
        release_2021, release_2025, evidence_path, config_path
    )
    assert evidence["equivalence_rows_published"] is False
    assert set(evidence["districts"]) == {f"{value:02d}" for value in range(1, 25)}
    assert all(
        row["directly_common_codes"] == 1 for row in evidence["districts"].values()
    )
    assert "equivalence" not in evidence or evidence.get("equivalence") is None


def test_detached_verification_detects_tamper(tmp_path: Path) -> None:
    config_path = _synthetic_config(tmp_path)
    config = load_config(config_path)
    source_2021 = _write_source_vintage(tmp_path / "source", "2021", config)
    release = tmp_path / "release"
    materialize_from_source_dir(source_2021, release, "2021", config_path)

    detached = tmp_path / "detached"
    shutil.copytree(release, detached)
    verify_release(detached, config_path)

    qa = read_json(detached / "qa.json")
    qa["feature_count"] += 1
    (detached / "qa.json").write_text(
        json.dumps(qa, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_release(detached, config_path)
