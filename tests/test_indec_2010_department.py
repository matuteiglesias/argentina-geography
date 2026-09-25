from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from argentina_geography.derived.indec_2010_department import (
    derive_department_footprints,
)


def _poly(x: float) -> Polygon:
    return Polygon([(x, 0), (x + 0.4, 0), (x + 0.4, 0.4), (x, 0.4)])


def test_department_footprints_preserve_exact_zero_padded_identity():
    radios = gpd.GeoDataFrame(
        [
            {
                "radio_2010_id": "020010101",
                "department_2010_id": "02001",
                "province_2010_id": "02",
                "geometry": _poly(0),
            },
            {
                "radio_2010_id": "020010102",
                "department_2010_id": "02001",
                "province_2010_id": "02",
                "geometry": _poly(1),
            },
            {
                "radio_2010_id": "060280101",
                "department_2010_id": "06028",
                "province_2010_id": "06",
                "geometry": _poly(3),
            },
        ],
        geometry="geometry",
        crs="EPSG:22183",
    )
    departments = derive_department_footprints(radios)
    assert departments["geography_id"].tolist() == ["02001", "06028"]
    assert departments["native_id"].tolist() == ["02001", "06028"]
    assert departments["source_radio_count"].tolist() == [2, 1]
    assert departments["province_2010_id"].tolist() == ["02", "06"]
    assert departments["department_name"].tolist() == ["Comuna 01", "Almirante Brown"]
    assert departments["province_name"].tolist() == ["Ciudad Autónoma de Buenos Aires", "Buenos Aires"]
    assert departments["geometry_valid"].all()


def test_department_footprint_fails_when_department_crosses_provinces():
    radios = gpd.GeoDataFrame(
        [
            {
                "radio_2010_id": "020010101",
                "department_2010_id": "02001",
                "province_2010_id": "02",
                "geometry": _poly(0),
            },
            {
                "radio_2010_id": "020010102",
                "department_2010_id": "02001",
                "province_2010_id": "06",
                "geometry": _poly(1),
            },
        ],
        geometry="geometry",
        crs="EPSG:22183",
    )
    with pytest.raises(ValueError, match="province identity disagrees"):
        derive_department_footprints(radios)


def test_department_footprint_rejects_numeric_or_short_identity():
    radios = gpd.GeoDataFrame(
        [
            {
                "radio_2010_id": "020010101",
                "department_2010_id": "2001",
                "province_2010_id": "02",
                "geometry": _poly(0),
            }
        ],
        geometry="geometry",
        crs="EPSG:22183",
    )
    with pytest.raises(ValueError, match="5-digit"):
        derive_department_footprints(radios)
