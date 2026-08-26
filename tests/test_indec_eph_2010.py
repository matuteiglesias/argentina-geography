from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import box

from argentina_geography.sources.indec_eph_2010 import (
    _build_frame_and_geography,
    _normalized_components,
)


def _fixture() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "id": [1, 2, 3],
            "eph_codagl": ["32", "32", "33"],
            "eph_aglome": ["CABA", "CABA", "Partidos del GBA"],
            "codprov": ["02", "02", "06"],
            "coddepto": ["001", "001", "001"],
            "frac2010": ["01", "01", "02"],
            "radio2010": ["01", "01", "03"],
            "tiporad": ["U", "U", "U"],
        },
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), None],
        crs="EPSG:22183",
    )


def test_direct_radio_mapping_collapses_source_components_without_gis_assignment() -> None:
    components = _normalized_components(_fixture())
    frame, geography, audit = _build_frame_and_geography(components)

    assert frame["radio_2010_id"].tolist() == ["020010101", "060010203"]
    assert frame["eph_agglomerate_id"].tolist() == ["32", "33"]
    assert frame.loc[0, "source_component_count"] == 2
    assert geography.loc[0, "geometry_role"] == "analytical"
    assert geography.loc[1, "geometry_role"] == "source_missing"
    assert audit["missing_geometry_radio_2010_ids"] == ["060010203"]


def test_conflicting_official_agglomerate_codes_fail_closed() -> None:
    source = _fixture()
    source.loc[1, "eph_codagl"] = "33"
    components = _normalized_components(source)

    with pytest.raises(ValueError, match="multiple agglomerate codes"):
        _build_frame_and_geography(components)
