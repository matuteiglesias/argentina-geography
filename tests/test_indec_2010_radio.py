from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from argentina_geography.sources.indec_2010_radio import (
    _aggregate_radios,
    _normalize_components,
)
from argentina_geography.sources.indec_2010_radio_probe import load_config


def test_indec_2010_source_registry_has_complete_province_set() -> None:
    config = load_config()
    rows = config["source_files"]
    assert len(rows) == 24
    assert len({row["province_code"] for row in rows}) == 24
    assert {row["province_code"] for row in rows} == {
        "02", "06", "10", "14", "18", "22", "26", "30", "34", "38", "42", "46",
        "50", "54", "58", "62", "66", "70", "74", "78", "82", "86", "90", "94",
    }
    assert all(row["download_url"].startswith("https://www.indec.gob.ar/") for row in rows)


def _poly(x: float) -> Polygon:
    return Polygon([(x, 0), (x + 0.4, 0), (x + 0.4, 0.4), (x, 0.4)])


def test_indec_2010_non_caba_link_maps_to_zero_preserving_stable_ids() -> None:
    frame = gpd.GeoDataFrame(
        [{"toponimo_i": 123456, "link": "060010104", "geometry": _poly(0)}],
        geometry="geometry",
        crs="EPSG:22183",
    )
    spec = {"province_code": "06", "file_name": "fixture.zip"}
    components = _normalize_components(frame, spec, "fixture")
    row = components.iloc[0]
    assert row["radio_2010_id"] == "060010104"
    assert row["department_2010_id"] == "06001"
    assert row["province_2010_id"] == "06"
    assert row["native_link"] == "060010104"
    assert row["native_toponimo_i"] == "123456"


def test_indec_2010_caba_multicomponent_radio_is_aggregated_without_dropping_source_rows() -> None:
    frame = gpd.GeoDataFrame(
        [
            {
                "PAIS0210_I": 3,
                "PROV": "02",
                "DEPTO": "013",
                "FRAC": "01",
                "RADIO": "04",
                "LINK": "020130104",
                "geometry": _poly(0),
            },
            {
                "PAIS0210_I": 8,
                "PROV": "02",
                "DEPTO": "013",
                "FRAC": "01",
                "RADIO": "04",
                "LINK": "020130104",
                "geometry": _poly(1),
            },
        ],
        geometry="geometry",
        crs="EPSG:22183",
    )
    spec = {"province_code": "02", "file_name": "caba.zip"}
    components = _normalize_components(frame, spec, "cabaxrdatos")
    radios = _aggregate_radios(components)
    assert len(components) == 2
    assert len(radios) == 1
    assert radios.iloc[0]["radio_2010_id"] == "020130104"
    assert radios.iloc[0]["source_component_count"] == 2
    assert radios.iloc[0]["provider_native_row_ids"] == "3|8"
    assert radios.iloc[0].geometry.is_valid


def test_indec_2010_caba_link_must_match_native_components() -> None:
    frame = gpd.GeoDataFrame(
        [
            {
                "PAIS0210_I": 1,
                "PROV": "02",
                "DEPTO": "013",
                "FRAC": "01",
                "RADIO": "04",
                "LINK": "020130105",
                "geometry": _poly(0),
            }
        ],
        geometry="geometry",
        crs="EPSG:22183",
    )
    spec = {"province_code": "02", "file_name": "caba.zip"}
    with pytest.raises(ValueError, match="LINK disagrees"):
        _normalize_components(frame, spec, "cabaxrdatos")
