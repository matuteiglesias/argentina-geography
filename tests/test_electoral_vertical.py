from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from argentina_geography.electoral.vertical import (
    DEFAULT_CONFIG,
    build_products,
    compare_historical_radio_crosswalk,
    compare_historical_section_crosswalk,
    elecciones_compatibility,
    load_config,
)


def _census() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "geo_uid": "census:r1",
                "radio_2010_id": "020010101",
                "department_2010_id": "02001",
                "province_2010_id": "02",
                "geometry_role": "analytical",
                "geometry": box(0.0, 0.0, 1.0, 1.0),
            },
            {
                "geo_uid": "census:r2",
                "radio_2010_id": "020020101",
                "department_2010_id": "02002",
                "province_2010_id": "02",
                "geometry_role": "analytical",
                "geometry": box(1.0, 0.0, 2.0, 1.0),
            },
            {
                "geo_uid": "census:r3",
                "radio_2010_id": "060010101",
                "department_2010_id": "06001",
                "province_2010_id": "06",
                "geometry_role": "analytical",
                "geometry": box(2.0, 0.0, 3.0, 1.0),
            },
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )


def _circuit_row(
    uid: str,
    circuit_uid: str | None,
    codprov: str,
    coddepto: str | None,
    circuito: str,
    geometry,
    *,
    source_status: str = "assigned_circuit",
    identity_status: str = "complete_composite",
    geometry_role: str = "analytical",
) -> dict:
    native_department = "<missing>" if coddepto is None else coddepto
    return {
        "geo_uid": uid,
        "circuit_uid": circuit_uid,
        "codprov": codprov,
        "coddepto": coddepto,
        "circuito": circuito,
        "native_id": f"{codprov}|{native_department}|{circuito}",
        "source_status": source_status,
        "identity_status": identity_status,
        "geometry_role": geometry_role,
        "geometry": geometry,
    }


def _circuits() -> gpd.GeoDataFrame:
    rows = [
        _circuit_row(
            "feature:a1",
            "tartagalensis:2021:circuit:01:001:00001",
            "01",
            "001",
            "00001",
            box(0.0, 0.0, 0.5, 1.0),
        ),
        # Feature-identical duplicate: logical footprint must not double-count its area.
        _circuit_row(
            "feature:a1-duplicate",
            "tartagalensis:2021:circuit:01:001:00001",
            "01",
            "001",
            "00001",
            box(0.0, 0.0, 0.5, 1.0),
        ),
        _circuit_row(
            "feature:a2",
            "tartagalensis:2021:circuit:01:001:00002",
            "01",
            "001",
            "00002",
            box(0.5, 0.0, 1.0, 1.0),
        ),
        # Same electoral section extends into another Census department.
        _circuit_row(
            "feature:a3",
            "tartagalensis:2021:circuit:01:001:00003",
            "01",
            "001",
            "00003",
            box(1.0, 0.0, 2.0, 1.0),
        ),
        # Circuit code 00001 repeats in another electoral district.
        _circuit_row(
            "feature:b1",
            "tartagalensis:2021:circuit:02:001:00001",
            "02",
            "001",
            "00001",
            box(2.0, 0.0, 3.0, 1.0),
        ),
        # Assigned source feature with incomplete section identity stays usable only
        # at source-feature relation grain.
        _circuit_row(
            "feature:b-incomplete",
            None,
            "02",
            None,
            "00099",
            box(2.8, 0.0, 3.0, 1.0),
            identity_status="missing_coddepto",
        ),
        # Real territory without an assigned circuit stays outside the primary relation
        # and is measured separately as nonstandard coverage.
        _circuit_row(
            "feature:b-grey",
            None,
            "02",
            "001",
            "zonagris",
            box(2.0, 0.0, 2.2, 1.0),
            source_status="grey_zone",
            identity_status="nonstandard_source_feature",
        ),
    ]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def test_production_config_pins_parallel_namespaces_and_exact_evidence() -> None:
    config = load_config(DEFAULT_CONFIG)
    bridge = config["district_province_bridge"]
    assert len(bridge) == 24
    assert bridge[0]["electoral_district_code"] == "01"
    assert bridge[0]["province_2010_id"] == "02"
    assert bridge[1]["electoral_district_code"] == "02"
    assert bridge[1]["province_2010_id"] == "06"
    assert config["policy_boundary"]["publish_crosswalk"] is False
    assert all(
        item["status"] == "regression_only"
        for item in config["historical_evidence"]["policies"]
    )
    assert (
        config["historical_evidence"]["commit_sha"]
        == "49d563434471a7a5416f7aa92890e0c70c849a3e"
    )
    assert (
        config["circuit_parents"]["2021"]["content_sha256"]
        == "265b559ae30323e91b67684edee8c41418197f2aa9dfc9df11f63f61b5fdb45b"
    )


def test_vertical_keeps_n_to_m_relations_and_source_edge_cases() -> None:
    config = load_config(DEFAULT_CONFIG)
    products = build_products(_census(), _circuits(), "2021", config)

    circuits_dim = products["circuits_dim"]
    # Duplicate physical rows for circuit 00001 collapse only in the derived logical
    # footprint, while the source-feature evidence remains in input_status.
    logical = circuits_dim.loc[
        circuits_dim["relation_target_uid"].eq(
            "tartagalensis:2021:circuit:01:001:00001"
        )
    ]
    assert len(logical) == 1
    assert logical.iloc[0]["source_feature_count"] == 2

    relation = products["radio_relation"]
    r1 = relation.loc[
        relation["radio_2010_id"].eq("020010101")
        & relation["target_electoral_uid"].notna()
    ]
    assert len(r1) == 2
    assert set(r1["target_electoral_circuit_code"]) == {"00001", "00002"}
    assert r1["relation_status"].eq("matched_multiple").all()
    # The identical duplicate source feature does not inflate logical-circuit coverage.
    assert abs(float(r1["overlap_share_of_source"].sum()) - 1.0) < 1e-9

    section_relation = products["section_relation"]
    section = section_relation.loc[
        section_relation["source_electoral_section_uid"].eq(
            "electoral:2021:section:01:001"
        )
        & section_relation["target_department_footprint_uid"].notna()
    ]
    assert set(section["target_department_2010_id"]) == {"02001", "02002"}
    assert section["relation_status"].eq("matched_multiple").all()

    # District 01 is an electoral namespace value and explicitly maps to Census
    # province 02; no code equality is assumed.
    bridge = products["bridge"]
    caba = bridge.loc[bridge["electoral_district_code"].eq("01")].iloc[0]
    assert caba["province_2010_id"] == "02"

    status = products["input_status"]
    incomplete = status.loc[status["input_uid"].eq("feature:b-incomplete")].iloc[0]
    assert bool(incomplete["eligible_for_primary_relation"])
    assert str(incomplete["relation_target_uid"]).startswith("source-feature:")

    nonstandard = products["nonstandard_relation"]
    grey = nonstandard.loc[
        nonstandard["radio_2010_id"].eq("060010101")
        & nonstandard["target_source_feature_uid"].notna()
    ]
    assert "grey_zone" in set(grey["target_source_status"])

    repeated = circuits_dim.groupby("electoral_circuit_code")[
        "electoral_district_code"
    ].nunique()
    assert repeated.loc["00001"] == 2


def test_historical_crosswalks_are_diagnostics_not_current_crosswalks(
    tmp_path: Path,
) -> None:
    config = load_config(DEFAULT_CONFIG)
    products = build_products(_census(), _circuits(), "2021", config)

    historical_radio = tmp_path / "radio.csv"
    pd.DataFrame(
        [
            {
                "COD_2010": "020010101",
                "codprov": "1",
                "coddepto": "1",
                "circuito": "1",
            },
            {
                "COD_2010": "060010101",
                "codprov": "2",
                "coddepto": "1",
                "circuito": "1",
            },
        ]
    ).to_csv(historical_radio, index=False)
    comparison, summary = compare_historical_radio_crosswalk(
        products["radio_relation"], historical_radio
    )
    assert comparison["historical_assignment_is_current_candidate"].all()
    assert summary["historical_assignment_is_current_candidate"] == 2
    assert "current relation truth" in summary["interpretation"]

    historical_section = tmp_path / "section.csv"
    pd.DataFrame(
        [
            {"codprov": "1", "coddepto": "1", "IN1": "02001"},
            {"codprov": "2", "coddepto": "1", "IN1": "06001"},
        ]
    ).to_csv(historical_section, index=False)
    section_comparison, section_summary = compare_historical_section_crosswalk(
        products["section_relation"], historical_section
    )
    assert section_comparison["historical_department_is_current_candidate"].all()
    assert section_summary["historical_department_is_current_candidate"] == 2


def test_elecciones_arg_is_a_read_only_compatibility_projection(tmp_path: Path) -> None:
    config = load_config(DEFAULT_CONFIG)
    products = build_products(_census(), _circuits(), "2021", config)

    table = tmp_path / "circuito_table.csv"
    pd.DataFrame(
        [
            {
                "eleccion_id": "0",
                "distrito_id": "1",
                "seccion_id": "1",
                "seccionprovincial_id": "0",
                "circuito_id": "000001",
                "circuito_nombre": "",
            },
            {
                "eleccion_id": "0",
                "distrito_id": "1",
                "seccion_id": "1",
                "seccionprovincial_id": "0",
                "circuito_id": "000002",
                "circuito_nombre": "",
            },
            {
                "eleccion_id": "0",
                "distrito_id": "2",
                "seccion_id": "1",
                "seccionprovincial_id": "0",
                "circuito_id": "000001",
                "circuito_nombre": "",
            },
        ]
    ).to_csv(table, index=False)

    proof, summary = elecciones_compatibility(products["circuits_dim"], table)
    complete = proof.loc[proof["identity_status"].eq("complete_composite")]
    assert complete["compatible_any"].any()
    assert summary["evidence_type"] == "elecciones_ARG_read_only_key_compatibility"
    assert "not electoral geography authority" in summary["interpretation"]
