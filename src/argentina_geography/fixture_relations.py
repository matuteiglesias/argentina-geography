from __future__ import annotations

from collections import Counter

import geopandas as gpd
import pandas as pd
from spatial_foundation.geography import relate_areal_objects


def build_relation(
    census: gpd.GeoDataFrame,
    admins: gpd.GeoDataFrame,
    policy: dict,
) -> tuple[pd.DataFrame, dict]:
    objects = census.rename(columns={"geo_uid": "source_geo_uid"})[
        ["source_geo_uid", "geometry_repaired", "geometry"]
    ]
    targets = admins.rename(columns={"geo_uid": "target_geo_uid"})[
        ["target_geo_uid", "geometry_role", "geometry"]
    ]
    relation, foundation_audit = relate_areal_objects(
        objects,
        targets,
        object_id_col="source_geo_uid",
        polygon_id_col="target_geo_uid",
        area_crs=policy["analysis_crs"],
        min_overlap_area_m2=policy["intersection"]["minimum_area_m2"],
    )
    relation = relation.rename(
        columns={
            "overlap_share_of_object": "overlap_share_of_source",
            "overlap_count": "source_candidate_count",
        }
    )
    positive = relation[relation["target_geo_uid"].notna()].copy()
    target_counts = positive.groupby("target_geo_uid").size().to_dict()
    relation["target_candidate_count"] = (
        relation["target_geo_uid"].map(target_counts).astype("Int64")
    )
    relation = relation[
        [
            "source_geo_uid",
            "target_geo_uid",
            "overlap_area_m2",
            "overlap_share_of_source",
            "source_candidate_count",
            "target_candidate_count",
            "relation_status",
        ]
    ].sort_values(
        ["source_geo_uid", "target_geo_uid"],
        na_position="last",
        ignore_index=True,
    )
    audit = {
        "input_sources": foundation_audit.input_objects,
        "matched_single": foundation_audit.matched_single,
        "matched_multiple": foundation_audit.matched_multiple,
        "unmatched_outside": foundation_audit.unmatched_outside,
        "invalid_geometry": foundation_audit.invalid_geometry,
        "positive_relation_rows": foundation_audit.relation_rows,
    }
    return relation, audit


def build_crosswalk(
    census: gpd.GeoDataFrame,
    relation: pd.DataFrame,
    policy: dict,
) -> tuple[pd.DataFrame, dict]:
    rows = []
    intersection = policy["intersection"]
    for source_geo_uid in census["geo_uid"]:
        candidates = relation[
            (relation["source_geo_uid"] == source_geo_uid)
            & relation["target_geo_uid"].notna()
        ].copy()
        candidates = candidates.sort_values(
            ["overlap_area_m2", "target_geo_uid"], ascending=[False, True]
        )
        selected = pd.NA
        winner_share = pd.NA
        status = "unmatched"
        if not candidates.empty:
            first = candidates.iloc[0]
            winner_share = float(first["overlap_share_of_source"])
            tied = len(candidates) > 1 and abs(
                float(first["overlap_area_m2"])
                - float(candidates.iloc[1]["overlap_area_m2"])
            ) <= intersection["tie_tolerance_m2"]
            if tied or winner_share < intersection["minimum_winner_share"]:
                status = "ambiguous"
            else:
                selected = first["target_geo_uid"]
                status = "matched"
        rows.append(
            {
                "source_geo_uid": source_geo_uid,
                "selected_target_geo_uid": selected,
                "policy_id": policy["policy_id"],
                "policy_version": policy["methodology_version"],
                "candidate_count": len(candidates),
                "winner_share": winner_share,
                "assignment_status": status,
                "manual_override_id_or_null": pd.NA,
            }
        )
    crosswalk = pd.DataFrame(rows).sort_values("source_geo_uid", ignore_index=True)
    counts = Counter(crosswalk["assignment_status"])
    audit = {
        "input_sources": len(crosswalk),
        "matched": counts["matched"],
        "unmatched": counts["unmatched"],
        "ambiguous": counts["ambiguous"],
        "excluded": counts["excluded"],
    }
    return crosswalk, audit
