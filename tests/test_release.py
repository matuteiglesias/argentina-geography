import json
from pathlib import Path

import pytest

from censo_geo.release import build, semantic_hash, sha256, verify


def load(path):
    return json.loads(Path(path).read_text())


def test_fixture_cases_and_coverage(tmp_path):
    out = tmp_path / "fixture-v1"
    build(out)
    verify(out)
    coverage = load(out / "coverage.json")
    assert coverage["counts"] == {
        "ambiguous": 0, "dropped": 2, "input": 6, "manually_overridden": 0,
        "matched": 3, "multiply_matched": 1, "output": 4, "repaired": 1, "unmatched": 1,
    }
    assert coverage["terminal_dispositions"] == {
        "ambiguous_excluded": 0, "duplicate_conflict_excluded": 2,
        "matched_retained": 3, "unmatched_retained": 1,
    }
    assert coverage["orthogonal_flags"] == {
        "geometry_repaired": 1, "manually_overridden": 0, "multiply_matched": 1,
    }
    assert coverage["partition_check"] == {"input_count": 6, "reconciles": True, "terminal_sum": 6}
    exceptions = load(out / "exceptions.json")
    assert exceptions["unmatched_ids"] == ["00003"]
    assert exceptions["duplicate_ids"] == ["00005"]
    repair = exceptions["repairs"][0]
    assert repair["unit_id"] == "00004"
    assert repair["method"] == "make_valid"
    assert repair["repair_reason"].startswith("Self-intersection")
    assert repair["original_geometry_type"] == "Polygon"
    assert repair["resulting_geometry_type"] == "MultiPolygon"
    assert repair["original_part_count"] == 1
    assert repair["resulting_part_count"] == 2
    assert repair["area_before_m2"] == pytest.approx(0, abs=1e-6)
    assert repair["area_after_m2"] > 0
    assert repair["absolute_area_change_m2"] == repair["area_after_m2"]
    assert repair["relative_area_change"] is None
    assert repair["empty_result"] is False
    assert repair["tolerance_exceeded"] is False
    features = load(out / "geography.geojson")["features"]
    assert [f["properties"]["unit_id"] for f in features] == ["00001", "00002", "00003", "00004"]
    assert next(f for f in features if f["properties"]["unit_id"] == "00002")["properties"]["admin_id"] == "10102"


def test_manifest_byte_and_semantic_hashes(tmp_path):
    out = tmp_path / "fixture-v1"
    manifest = build(out)
    features = load(out / "geography.geojson")["features"]
    assert manifest["output"]["byte_sha256"] == sha256(out / "geography.geojson")
    assert manifest["output"]["semantic_geometry_sha256"] == semantic_hash(features, geometry_only=True)
    assert manifest["output"]["semantic_content_sha256"] == semantic_hash(features)
    assert manifest["reports"]["coverage"]["sha256"] == sha256(out / "coverage.json")
    assert manifest["reports"]["exceptions"]["sha256"] == sha256(out / "exceptions.json")


def test_semantic_hash_ignores_serialization_and_ring_start(tmp_path):
    out = tmp_path / "fixture-v1"
    build(out)
    features = load(out / "geography.geojson")["features"]
    changed = json.loads(json.dumps(features))
    ring = changed[0]["geometry"]["coordinates"][0]
    changed[0]["geometry"]["coordinates"][0] = ring[2:-1] + ring[:2] + [ring[2]]
    changed.reverse()
    assert semantic_hash(changed) == semantic_hash(features)
