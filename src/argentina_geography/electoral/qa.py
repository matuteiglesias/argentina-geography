from __future__ import annotations

import geopandas as gpd
import pandas as pd


def _coverage_quantiles(values: pd.Series) -> dict[str, float | None]:
    if values.empty:
        return {"min": None, "p50": None, "p95": None, "max": None}
    values = values.astype(float)
    return {
        "min": float(values.min()),
        "p50": float(values.quantile(0.50)),
        "p95": float(values.quantile(0.95)),
        "max": float(values.max()),
    }

def build_province_qa(
    census: gpd.GeoDataFrame,
    circuits: gpd.GeoDataFrame,
    radio_relation: pd.DataFrame,
    section_relation: pd.DataFrame,
    nonstandard_relation: pd.DataFrame,
    sections: pd.DataFrame,
    circuit_footprints: gpd.GeoDataFrame,
    bridge: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict] = []
    for mapping in bridge.itertuples():
        province_id = str(mapping.province_2010_id)
        district_code = str(mapping.electoral_district_code)
        source_ids = set(
            census.loc[
                census["province_2010_id"].astype(str).eq(province_id), "geo_uid"
            ].astype(str)
        )
        rel = radio_relation.loc[
            radio_relation["source_geo_uid"].astype(str).isin(source_ids)
        ]
        by_source = rel.groupby("source_geo_uid", dropna=False).first()
        positive = rel.loc[rel["target_electoral_uid"].notna()]
        coverage = (
            positive.groupby("source_geo_uid")["overlap_share_of_source"]
            .sum()
            .reindex(sorted(source_ids), fill_value=0.0)
        )
        section_ids = set(
            sections.loc[
                sections["electoral_district_code"].astype(str).eq(district_code),
                "electoral_section_uid",
            ].astype(str)
        )
        section_rel = section_relation.loc[
            section_relation["source_electoral_section_uid"].astype(str).isin(section_ids)
        ]
        section_status = section_rel.groupby(
            "source_electoral_section_uid", dropna=False
        ).first()
        nonstandard_positive = nonstandard_relation.loc[
            nonstandard_relation["source_geo_uid"].astype(str).isin(source_ids)
            & nonstandard_relation["target_source_feature_uid"].notna()
        ]
        targets = circuit_footprints.loc[
            circuit_footprints["electoral_district_code"].astype(str).eq(district_code)
        ]
        raw = circuits.loc[circuits["codprov"].astype(str).eq(district_code)]
        q = _coverage_quantiles(coverage)
        rows.append(
            {
                "province_2010_id": province_id,
                "electoral_district_code": district_code,
                "electoral_district_name": mapping.electoral_district_name,
                "census_radio_count": len(source_ids),
                "matched_single_radio_count": int(
                    by_source["relation_status"].eq("matched_single").sum()
                )
                if not by_source.empty
                else 0,
                "matched_multiple_radio_count": int(
                    by_source["relation_status"].eq("matched_multiple").sum()
                )
                if not by_source.empty
                else 0,
                "unmatched_radio_count": int(
                    by_source["relation_status"].eq("unmatched_outside").sum()
                )
                if not by_source.empty
                else 0,
                "invalid_radio_count": int(
                    by_source["relation_status"].eq("invalid_geometry").sum()
                )
                if not by_source.empty
                else 0,
                "positive_radio_circuit_rows": len(positive),
                "cross_province_positive_rows": int(
                    (~positive["province_compatible"].fillna(False)).sum()
                ),
                "radio_coverage_share_min": q["min"],
                "radio_coverage_share_p50": q["p50"],
                "radio_coverage_share_p95": q["p95"],
                "radio_coverage_share_max": q["max"],
                "electoral_section_count": len(section_ids),
                "section_matched_multiple_department_count": int(
                    section_status["relation_status"].eq("matched_multiple").sum()
                )
                if not section_status.empty
                else 0,
                "derived_circuit_target_count": len(targets),
                "raw_circuit_source_feature_count": len(raw),
                "raw_nonstandard_feature_count": int(
                    (~raw["source_status"].eq("assigned_circuit")).sum()
                ),
                "raw_nonanalytical_feature_count": int(
                    (~raw["geometry_role"].eq("analytical")).sum()
                ),
                "assigned_missing_section_feature_count": int(
                    (
                        raw["source_status"].eq("assigned_circuit")
                        & raw["coddepto"].isna()
                    ).sum()
                ),
                "radio_count_overlapping_nonstandard_features": int(
                    nonstandard_positive["source_geo_uid"].nunique()
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("electoral_district_code", ignore_index=True)
