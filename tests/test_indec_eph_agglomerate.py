from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from argentina_geography.derived.indec_eph_agglomerate import derive_agglomerates


def _poly(x: float, y: float = 0.0) -> Polygon:
    return Polygon([(x, y), (x + 0.25, y), (x + 0.25, y + 0.25), (x, y + 0.25)])


def _fixture():
    frame_rows = []
    geo_rows = []
    for code in range(1, 33):
        aglo = f"{code:02d}"
        province = "06"
        department = f"06{code:03d}"
        radio = f"{department}0101"
        frame_rows.append(
            {
                "radio_2010_id": radio,
                "department_2010_id": department,
                "province_2010_id": province,
                "eph_agglomerate_id": aglo,
                "native_eph_aglome_values": f"Aglomerado {aglo}",
            }
        )
        geo_rows.append(
            {
                "radio_2010_id": radio,
                "department_2010_id": department,
                "province_2010_id": province,
                "eph_agglomerate_id": aglo,
                "geometry": _poly(float(code)),
            }
        )

    # One EPH agglomerate deliberately crosses a province boundary. The second
    # polygon is far away: membership must still follow the declared A7 code.
    frame_rows.append(
        {
            "radio_2010_id": "820010101",
            "department_2010_id": "82001",
            "province_2010_id": "82",
            "eph_agglomerate_id": "01",
            "native_eph_aglome_values": "Aglomerado 01",
        }
    )
    geo_rows.append(
        {
            "radio_2010_id": "820010101",
            "department_2010_id": "82001",
            "province_2010_id": "82",
            "eph_agglomerate_id": "01",
            "geometry": _poly(100.0),
        }
    )
    return (
        pd.DataFrame(frame_rows),
        gpd.GeoDataFrame(geo_rows, geometry="geometry", crs="EPSG:22183"),
    )


def test_agglomerate_is_parallel_geography_and_can_cross_provinces():
    frame, geography = _fixture()
    agglomerates, relation, audit = derive_agglomerates(frame, geography)

    assert len(agglomerates) == 32
    aglo = agglomerates.set_index("eph_agglomerate_id").loc["01"]
    assert aglo["province_2010_ids"] == "06|82"
    assert bool(aglo["cross_province"]) is True
    assert aglo["source_radio_count"] == 2
    assert set(relation.loc[relation.eph_agglomerate_id == "01", "radio_2010_id"]) == {
        "060010101",
        "820010101",
    }
    assert audit["cross_province_agglomerate_ids"] == ["01"]


def test_membership_comes_from_direct_a7_relation_not_geometry():
    frame, geography = _fixture()
    # Give agglomerates 02 and 03 exactly the same polygon. A geometric
    # reconstruction could not distinguish them, but the direct relation can.
    geography.loc[geography.eph_agglomerate_id == "02", "geometry"] = _poly(200.0)
    geography.loc[geography.eph_agglomerate_id == "03", "geometry"] = _poly(200.0)

    agglomerates, relation, _ = derive_agglomerates(frame, geography)

    assert set(agglomerates.eph_agglomerate_id) == {f"{i:02d}" for i in range(1, 33)}
    assert relation.loc[
        relation.radio_2010_id == "060020101", "eph_agglomerate_id"
    ].item() == "02"
    assert relation.loc[
        relation.radio_2010_id == "060030101", "eph_agglomerate_id"
    ].item() == "03"


def test_source_missing_radio_geometry_is_retained_in_relation_and_audited():
    frame, geography = _fixture()
    geography.loc[geography.radio_2010_id == "820010101", "geometry"] = None

    agglomerates, relation, audit = derive_agglomerates(frame, geography)

    aglo = agglomerates.set_index("eph_agglomerate_id").loc["01"]
    assert aglo["source_radio_count"] == 2
    assert aglo["geometry_radio_count"] == 1
    assert aglo["missing_geometry_radio_count"] == 1
    assert len(relation) == len(frame)
    assert audit["source_missing_geometry_radio_count"] == 1


def test_frame_and_geometry_must_agree_on_direct_membership():
    frame, geography = _fixture()
    geography.loc[geography.radio_2010_id == "060020101", "eph_agglomerate_id"] = "03"

    with pytest.raises(ValueError, match="direct radio-to-agglomerate"):
        derive_agglomerates(frame, geography)
