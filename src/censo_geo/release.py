"""Build the bounded offline geography release; never downloads live data."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

import pyproj
import shapely
from pyproj import Transformer
from shapely import make_valid, set_precision
from shapely.geometry import mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import transform
from shapely.validation import explain_validity

ROOT = Path(__file__).resolve().parents[2]
UNITS = ROOT / "fixtures/census_units.geojson"
ADMINS = ROOT / "fixtures/admin_candidates.geojson"
REGISTRY = ROOT / "config/source_registry.json"
POLICY = ROOT / "config/reconciliation_policy.json"
OUTPUT = ROOT / "releases/fixture-v1"
JSON_ARGS = {"ensure_ascii": False, "indent": 2, "sort_keys": True}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, **JSON_ARGS) + "\n", encoding="utf-8", newline="\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_id(value, width: int, field: str) -> str:
    text = str(value)
    if not text.isascii() or not text.isdigit() or len(text) > width:
        raise ValueError(f"{field} must be at most {width} ASCII digits: {value!r}")
    return text.zfill(width)


def normalize_geometry(geom):
    """Canonical polygon precision, ring orientation, and coordinate order."""
    geom = set_precision(geom, grid_size=1e-9, mode="valid_output")
    if geom.geom_type == "Polygon":
        return orient(geom, sign=1.0)
    if geom.geom_type == "MultiPolygon":
        parts = sorted((orient(g, sign=1.0) for g in geom.geoms), key=lambda g: g.wkb_hex)
        return shapely.MultiPolygon(parts)
    raise ValueError(f"unsupported output geometry: {geom.geom_type}")


def geometry_part_count(geom) -> int:
    """Count top-level polygon parts consistently for repair auditing."""
    if geom.is_empty:
        return 0
    if geom.geom_type == "MultiPolygon":
        return len(geom.geoms)
    return 1


def _canonical_ring(coords) -> list[list[float]]:
    points = [tuple(round(value, 9) for value in point[:2]) for point in coords[:-1]]
    rotations = [points[index:] + points[:index] for index in range(len(points))]
    selected = min(rotations)
    return [list(point) for point in selected + [selected[0]]]


def canonical_geometry_value(geom) -> dict:
    """Return a driver-independent geometry value for semantic hashing."""
    normalized = normalize_geometry(geom)
    polygons = normalized.geoms if normalized.geom_type == "MultiPolygon" else [normalized]
    values = []
    for polygon in polygons:
        shell = _canonical_ring(polygon.exterior.coords)
        holes = sorted(_canonical_ring(ring.coords) for ring in polygon.interiors)
        values.append([shell, *holes])
    values.sort(key=lambda value: json.dumps(value, separators=(",", ":")))
    if normalized.geom_type == "Polygon":
        return {"type": "Polygon", "coordinates": values[0]}
    return {"type": "MultiPolygon", "coordinates": values}


def semantic_hash(records: list[dict], *, geometry_only: bool = False) -> str:
    """Hash normalized meaning, independent of GeoJSON whitespace and driver metadata."""
    values = []
    for feature in sorted(records, key=lambda item: item["properties"]["unit_id"]):
        geometry = shape(feature["geometry"])
        value = {"unit_id": feature["properties"]["unit_id"], "geometry": canonical_geometry_value(geometry)}
        if not geometry_only:
            value["properties"] = {key: feature["properties"][key] for key in sorted(feature["properties"])}
        values.append(value)
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def build(output: Path) -> dict:
    policy = read_json(POLICY)
    units_doc, admins_doc = read_json(UNITS), read_json(ADMINS)
    to_analysis = Transformer.from_crs("OGC:CRS84", policy["analysis_crs"], always_xy=True)
    to_output = Transformer.from_crs(policy["analysis_crs"], "OGC:CRS84", always_xy=True)

    admins = []
    for feature in admins_doc["features"]:
        props = feature["properties"]
        admins.append({
            "admin_id": normalize_id(props["admin_id"], 5, "admin_id"),
            "province_id": normalize_id(props["province_id"], 2, "province_id"),
            "geometry": shape(feature["geometry"]),
        })
    admins.sort(key=lambda x: x["admin_id"])

    raw_ids = [normalize_id(f["properties"]["unit_id"], 5, "unit_id") for f in units_doc["features"]]
    duplicates = {key for key, count in Counter(raw_ids).items() if count > 1}
    records, exceptions, repairs = [], [], []
    weights = defaultdict(lambda: {"input": 0.0, "matched": 0.0})
    status_counts = Counter()
    multiply_matched = 0

    for sequence, feature in enumerate(units_doc["features"], start=1):
        props = feature["properties"]
        uid = normalize_id(props["unit_id"], 5, "unit_id")
        province = normalize_id(props["province_id"], 2, "province_id")
        weight = float(props["weight"])
        weights[province]["input"] += weight
        geom = transform(to_analysis.transform, shape(feature["geometry"]))
        was_invalid = not geom.is_valid
        if was_invalid:
            original = geom
            original_area = original.area
            repair_reason = explain_validity(original)
            repaired = make_valid(original)
            polygon_parts = [g for g in getattr(repaired, "geoms", [repaired]) if g.geom_type in {"Polygon", "MultiPolygon"}]
            geom = shapely.union_all(polygon_parts)
            resulting_area = geom.area
            absolute_change = abs(resulting_area - original_area)
            effectively_zero_area = original_area <= policy["geometry_repair"]["zero_area_epsilon_m2"]
            relative_change = None if effectively_zero_area else absolute_change / original_area
            empty_result = geom.is_empty
            relative_exceeded = relative_change is not None and relative_change > policy["geometry_repair"]["max_relative_area_change"]
            absolute_exceeded = effectively_zero_area and absolute_change > policy["geometry_repair"]["zero_area_max_absolute_area_change_m2"]
            tolerance_exceeded = relative_exceeded or absolute_exceeded
            repair = {
                "unit_id": uid, "method": "make_valid", "repair_reason": repair_reason,
                "original_geometry_type": original.geom_type, "resulting_geometry_type": geom.geom_type,
                "original_part_count": geometry_part_count(original), "resulting_part_count": geometry_part_count(geom),
                "area_before_m2": round(original_area, 6), "area_after_m2": round(resulting_area, 6),
                "absolute_area_change_m2": round(absolute_change, 6),
                "relative_area_change": None if relative_change is None else round(relative_change, 12),
                "empty_result": empty_result, "tolerance_exceeded": tolerance_exceeded,
            }
            repairs.append(repair)
            if empty_result or not geom.is_valid:
                raise ValueError(f"repair failed for {uid}: empty={empty_result}, valid={geom.is_valid}")
            if tolerance_exceeded:
                raise ValueError(f"repair area tolerance exceeded for {uid}: {repair}")

        overlaps = []
        for admin in admins:
            area = geom.intersection(admin["geometry"]).area
            if area > policy["intersection"]["minimum_area_m2"]:
                overlaps.append((admin["admin_id"], area))
        overlaps.sort(key=lambda item: (-item[1], item[0]))
        candidate_ids = [item[0] for item in overlaps]
        if len(overlaps) > 1:
            multiply_matched += 1

        admin_id, status, reason = None, "unmatched", "no_positive_area_intersection"
        winner_share = 0.0
        if uid in duplicates:
            status, reason = "dropped", "duplicate_identifier"
        elif overlaps:
            winner_share = overlaps[0][1] / geom.area
            tied = len(overlaps) > 1 and abs(overlaps[0][1] - overlaps[1][1]) <= policy["intersection"]["tie_tolerance_m2"]
            if tied:
                status, reason = "ambiguous", "largest_overlap_tie"
            elif winner_share >= policy["intersection"]["minimum_winner_share"]:
                admin_id, status, reason = overlaps[0][0], "matched", "unique_largest_overlap"
                weights[province]["matched"] += weight
            else:
                status, reason = "ambiguous", "winner_below_minimum_share"
        status_counts[status] += 1
        if status != "matched" or len(overlaps) > 1 or was_invalid:
            exceptions.append({
                "unit_id": uid, "occurrence": sequence, "status": status, "reason": reason,
                "candidate_admin_ids": candidate_ids, "geometry_repaired": was_invalid,
            })
        if status not in {"dropped", "ambiguous"}:
            records.append({
                "type": "Feature",
                "properties": {
                    "unit_id": uid, "province_id": province, "admin_id": admin_id,
                    "status": status, "weight": weight, "winner_area_share": round(winner_share, 9),
                    "geometry_repaired": was_invalid,
                },
                "geometry": mapping(normalize_geometry(transform(to_output.transform, geom))),
            })

    records.sort(key=lambda f: f["properties"]["unit_id"])
    exceptions.sort(key=lambda x: (x["unit_id"], x["occurrence"]))
    total = len(units_doc["features"])
    matched = status_counts["matched"]
    coverage_by_province = []
    for province in sorted(weights):
        province_features = [f for f in units_doc["features"] if normalize_id(f["properties"]["province_id"], 2, "province_id") == province]
        province_ids = [normalize_id(f["properties"]["unit_id"], 5, "unit_id") for f in province_features]
        province_matched = sum(1 for r in records if r["properties"]["province_id"] == province and r["properties"]["status"] == "matched")
        inp_weight, match_weight = weights[province]["input"], weights[province]["matched"]
        coverage_by_province.append({
            "province_id": province, "input_count": len(province_ids), "matched_count": province_matched,
            "feature_coverage_share": round(province_matched / len(province_ids), 9),
            "synthetic_weight_input": inp_weight, "synthetic_weight_matched": match_weight,
            "synthetic_weight_coverage_share": round(match_weight / inp_weight, 9),
        })

    terminal_dispositions = {
        "matched_retained": status_counts["matched"],
        "unmatched_retained": status_counts["unmatched"],
        "ambiguous_excluded": status_counts["ambiguous"],
        "duplicate_conflict_excluded": status_counts["dropped"],
    }
    if sum(terminal_dispositions.values()) != total:
        raise AssertionError("terminal dispositions do not partition every input occurrence")
    orthogonal_flags = {
        "multiply_matched": multiply_matched, "geometry_repaired": len(repairs),
        "manually_overridden": 0,
    }
    coverage = {
        "schema_version": "1.1.0", "release_id": "fixture-v1", "geographic_level": "synthetic census unit",
        "terminal_dispositions": terminal_dispositions,
        "orthogonal_flags": orthogonal_flags,
        "partition_check": {"input_count": total, "terminal_sum": sum(terminal_dispositions.values()), "reconciles": True},
        "counts": {"input": total, "output": len(records), "matched": matched,
                   "unmatched": status_counts["unmatched"], "ambiguous": status_counts["ambiguous"],
                   "multiply_matched": multiply_matched, "repaired": len(repairs),
                   "dropped": status_counts["dropped"], "manually_overridden": 0},
        "shares_of_input": {key: round(value / total, 9) for key, value in {
            "matched": matched, "unmatched": status_counts["unmatched"], "ambiguous": status_counts["ambiguous"],
            "multiply_matched": multiply_matched, "repaired": len(repairs), "dropped": status_counts["dropped"],
            "manually_overridden": 0}.items()},
        "invalid_geometry": {"before_repair": len(repairs), "after_repair": 0},
        "area": {"analysis_crs": policy["analysis_crs"], "note": "Intersection areas drive assignment; no national area-coverage claim is made."},
        "coverage_by_province": coverage_by_province,
        "population_coverage": None,
        "synthetic_weight_note": "Weight belongs to this synthetic fixture vintage; it is not population.",
        "historical_snapshot_difference": {"comparable": False, "reason": "Synthetic fixture has no corresponding historical snapshot."},
    }
    exception_report = {
        "schema_version": "1.1.0", "release_id": "fixture-v1", "exceptions": exceptions,
        "repairs": repairs, "manual_overrides": [],
        "unmatched_ids": sorted({e["unit_id"] for e in exceptions if e["status"] == "unmatched"}),
        "ambiguous_ids": sorted({e["unit_id"] for e in exceptions if e["status"] == "ambiguous"}),
        "duplicate_ids": sorted(duplicates),
    }

    output.mkdir(parents=True, exist_ok=True)
    geography_path = output / "geography.geojson"
    coverage_path = output / "coverage.json"
    exceptions_path = output / "exceptions.json"
    manifest_path = output / "manifest.json"
    write_json(geography_path, {"type": "FeatureCollection", "name": "fixture-v1", "features": records})
    write_json(coverage_path, coverage)
    write_json(exceptions_path, exception_report)
    source_hashes = {str(p.relative_to(ROOT)): sha256(p) for p in (REGISTRY, UNITS, ADMINS, POLICY)}
    manifest = {
        "schema_version": "1.1.0", "release_version": "1.1.0", "release_id": "fixture-v1",
        "declared_reference_vintage": "synthetic fixture-v1; no current-boundary meaning",
        "source_registry": {"version": read_json(REGISTRY)["registry_version"], "path": "config/source_registry.json", "sha256": source_hashes["config/source_registry.json"]},
        "input_files": {k: v for k, v in source_hashes.items() if k.startswith("fixtures/")},
        "policy": {"path": "config/reconciliation_policy.json", "sha256": source_hashes["config/reconciliation_policy.json"],
                   "methodology_version": policy["methodology_version"], "approval_scope": policy["approval_scope"]},
        "environment": {"python": platform.python_version(), "shapely": shapely.__version__, "pyproj": pyproj.__version__, "definition": "environment.yml and requirements.lock"},
        "producer": {"git_commit": git_commit(), "command": "make release-fixture"},
        "output": {"crs": "OGC:CRS84", "axis_order": "longitude, latitude", "geometry_type": "Polygon or MultiPolygon", "precision_degrees": 1e-9,
                   "schema": {"unit_id": "string[5]", "province_id": "string[2]", "admin_id": "nullable string[5]", "status": "matched|unmatched", "weight": "number", "winner_area_share": "number", "geometry_repaired": "boolean"},
                   "feature_count": len(records), "path": "geography.geojson", "byte_sha256": sha256(geography_path),
                   "semantic_geometry_sha256": semantic_hash(records, geometry_only=True),
                   "semantic_content_sha256": semantic_hash(records)},
        "reports": {"coverage": {"path": "coverage.json", "sha256": sha256(coverage_path)}, "exceptions": {"path": "exceptions.json", "sha256": sha256(exceptions_path)}},
        "limitations": ["Synthetic bounded fixture only; not an Argentina geography release.", "Not official, not current boundaries, and not suitable for substantive analysis.", "Historical IGN vintage, license, and checksum remain unresolved; no live source was adopted."],
        "current_boundary_disclaimer": "This artifact must not be represented as current official administrative boundaries."
    }
    write_json(manifest_path, manifest)
    return manifest


def verify(output: Path) -> None:
    manifest = read_json(output / "manifest.json")
    for item in [manifest["output"], *manifest["reports"].values()]:
        expected = item.get("byte_sha256", item.get("sha256"))
        if sha256(output / item["path"]) != expected:
            raise ValueError(f"checksum mismatch: {item['path']}")
    records = read_json(output / manifest["output"]["path"])["features"]
    if semantic_hash(records, geometry_only=True) != manifest["output"]["semantic_geometry_sha256"]:
        raise ValueError("semantic geometry checksum mismatch")
    if semantic_hash(records) != manifest["output"]["semantic_content_sha256"]:
        raise ValueError("semantic content checksum mismatch")
    with TemporaryDirectory() as tmp:
        rebuilt = Path(tmp) / "fixture-v1"
        build(rebuilt)
        for name in ("geography.geojson", "coverage.json", "exceptions.json", "manifest.json"):
            if (output / name).read_bytes() != (rebuilt / name).read_bytes():
                raise ValueError(f"non-deterministic artifact: {name}")


def check() -> None:
    policy = read_json(POLICY)
    registry = read_json(REGISTRY)
    assert policy["manual_overrides"] == []
    assert {source["status"] for source in registry["sources"]} <= {"observed", "historical snapshot", "unavailable", "unresolved"}
    with TemporaryDirectory() as tmp:
        out = Path(tmp) / "fixture-v1"
        build(out)
        verify(out)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        check()
    else:
        build(args.output)
        if args.verify:
            verify(args.output)


if __name__ == "__main__":
    main()
