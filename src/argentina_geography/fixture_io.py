from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import shapely
from shapely.geometry import shape
from shapely.validation import explain_validity


def normalize_id(value: object, width: int, field: str) -> str:
    text = str(value)
    if not text.isascii() or not text.isdigit() or len(text) > width:
        raise ValueError(f"{field} must be at most {width} ASCII digits: {value!r}")
    return text.zfill(width)


def load_geojson(path: Path, *, crs: str) -> gpd.GeoDataFrame:
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = [
        {**feature["properties"], "geometry": shape(feature["geometry"])}
        for feature in document["features"]
    ]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)


def _polygonal_part(geometry):
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    parts = [
        part
        for part in getattr(geometry, "geoms", [])
        if part.geom_type in {"Polygon", "MultiPolygon"}
    ]
    if not parts:
        return shapely.GeometryCollection()
    return shapely.union_all(parts)


def repair_census_geography(
    frame: gpd.GeoDataFrame, policy: dict
) -> tuple[gpd.GeoDataFrame, list[dict]]:
    metric = frame.to_crs(policy["analysis_crs"]).copy()
    repairs: list[dict] = []
    repaired_geometries = []
    for row in metric.itertuples():
        geometry = row.geometry
        if geometry.is_valid:
            repaired_geometries.append(geometry)
            continue
        before_area = float(geometry.area)
        reason = explain_validity(geometry)
        candidate = _polygonal_part(shapely.make_valid(geometry))
        after_area = float(candidate.area)
        absolute_change = abs(after_area - before_area)
        effectively_zero = before_area <= policy["geometry_repair"]["zero_area_epsilon_m2"]
        relative_change = None if effectively_zero else absolute_change / before_area
        exceeded = (
            relative_change is not None
            and relative_change > policy["geometry_repair"]["max_relative_area_change"]
        ) or (
            effectively_zero
            and absolute_change
            > policy["geometry_repair"]["zero_area_max_absolute_area_change_m2"]
        )
        if candidate.is_empty or not candidate.is_valid or exceeded:
            raise ValueError(
                f"fixture repair failed for {row.native_id}: empty={candidate.is_empty}, "
                f"valid={candidate.is_valid}, tolerance_exceeded={exceeded}"
            )
        repaired_geometries.append(candidate)
        repairs.append(
            {
                "native_id": row.native_id,
                "method": "shapely.make_valid",
                "reason": reason,
                "area_before_m2": round(before_area, 6),
                "area_after_m2": round(after_area, 6),
                "absolute_area_change_m2": round(absolute_change, 6),
                "relative_area_change": None
                if relative_change is None
                else round(relative_change, 12),
            }
        )
    metric.geometry = repaired_geometries
    repaired_ids = {repair["native_id"] for repair in repairs}
    metric["geometry_repaired"] = metric["native_id"].isin(repaired_ids)
    return metric.to_crs("OGC:CRS84"), repairs


def prepare_geographies(
    units_path: Path,
    admins_path: Path,
    policy: dict,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, dict]:
    unit_width = policy["identifier"]["unit_width"]
    admin_width = policy["identifier"]["admin_width"]
    province_width = policy["identifier"]["province_width"]

    census = load_geojson(units_path, crs="OGC:CRS84")
    input_occurrences = len(census)
    census["native_id"] = census["unit_id"].map(
        lambda value: normalize_id(value, unit_width, "unit_id")
    )
    census["province_id"] = census["province_id"].map(
        lambda value: normalize_id(value, province_width, "province_id")
    )
    duplicate_mask = census["native_id"].duplicated(keep=False)
    duplicate_ids = sorted(census.loc[duplicate_mask, "native_id"].unique().tolist())
    duplicate_occurrences = int(duplicate_mask.sum())
    census = census.loc[~duplicate_mask].copy()
    census, repairs = repair_census_geography(census, policy)
    census["geo_uid"] = "synthetic:fixture-v1:census:unit:" + census["native_id"]
    census["geometry_role"] = "analytical"
    census = census[
        [
            "geo_uid",
            "native_id",
            "province_id",
            "weight",
            "geometry_repaired",
            "geometry_role",
            "geometry",
        ]
    ].sort_values("geo_uid", ignore_index=True)

    admins = load_geojson(admins_path, crs="EPSG:3857")
    admins["native_id"] = admins["admin_id"].map(
        lambda value: normalize_id(value, admin_width, "admin_id")
    )
    admins["province_id"] = admins["province_id"].map(
        lambda value: normalize_id(value, province_width, "province_id")
    )
    if admins["native_id"].duplicated().any():
        raise ValueError("fixture admin IDs must be unique")
    invalid_admin = (
        admins.geometry.isna().any()
        or admins.geometry.is_empty.any()
        or (~admins.geometry.is_valid).any()
    )
    if invalid_admin:
        raise ValueError("fixture analytical admin geography must be valid and non-empty")
    admins["geo_uid"] = "synthetic:fixture-v1:admin:unit:" + admins["native_id"]
    admins["geometry_role"] = "analytical"
    admins = admins[
        ["geo_uid", "native_id", "province_id", "geometry_role", "geometry"]
    ].to_crs("OGC:CRS84").sort_values("geo_uid", ignore_index=True)

    audit = {
        "input_census_occurrences": input_occurrences,
        "released_census_features": len(census),
        "duplicate_occurrences_excluded": duplicate_occurrences,
        "duplicate_ids": duplicate_ids,
        "repaired_features": len(repairs),
        "repairs": repairs,
        "released_admin_features": len(admins),
    }
    return census, admins, audit
