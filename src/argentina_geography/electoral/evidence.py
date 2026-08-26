from __future__ import annotations

from pathlib import Path

import pandas as pd


def _comparison_component(value: object, *, numeric_padding: int | None = None) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        number = str(int(text))
        return number.zfill(numeric_padding) if numeric_padding else number
    return text.upper()

def _comparison_key(codprov: object, coddepto: object, circuito: object) -> str | None:
    district = _comparison_component(codprov)
    section = _comparison_component(coddepto)
    circuit = _comparison_component(circuito)
    if district is None or section is None or circuit is None:
        return None
    return f"{district}|{section}|{circuit}"

def compare_historical_radio_crosswalk(
    relation: pd.DataFrame,
    path: Path,
) -> tuple[pd.DataFrame, dict]:
    historical = pd.read_csv(path, dtype="string")
    historical = historical.loc[
        :, [column for column in historical.columns if not str(column).startswith("Unnamed:")]
    ]
    required = {"COD_2010", "codprov", "coddepto", "circuito"}
    if not required.issubset(historical.columns):
        raise ValueError(
            f"historical radio crosswalk missing columns {sorted(required - set(historical.columns))}"
        )

    current = relation.loc[relation["target_electoral_uid"].notna()].copy()
    current["comparison_key"] = [
        _comparison_key(a, b, c)
        for a, b, c in zip(
            current["target_electoral_district_code"],
            current["target_electoral_section_code"],
            current["target_electoral_circuit_code"],
            strict=True,
        )
    ]
    current["radio_2010_id"] = current["radio_2010_id"].astype(str)
    grouped = {
        radio_id: group
        for radio_id, group in current.groupby("radio_2010_id", sort=False)
    }

    rows: list[dict] = []
    for item in historical.itertuples(index=False):
        raw = item._asdict()
        radio = _comparison_component(raw["COD_2010"], numeric_padding=9)
        key = _comparison_key(raw["codprov"], raw["coddepto"], raw["circuito"])
        group = grouped.get(radio)
        candidate_keys: set[str] = set()
        max_keys: set[str] = set()
        if group is not None and not group.empty:
            candidate_keys = set(group["comparison_key"].dropna().astype(str))
            max_area = float(group["overlap_area_m2"].astype(float).max())
            max_keys = set(
                group.loc[
                    group["overlap_area_m2"].astype(float).eq(max_area),
                    "comparison_key",
                ].dropna().astype(str)
            )
        rows.append(
            {
                "radio_2010_id": radio,
                "historical_codprov": raw["codprov"],
                "historical_coddepto": raw["coddepto"],
                "historical_circuito": raw["circuito"],
                "historical_assignment_comparison_key": key,
                "current_radio_has_positive_candidates": bool(candidate_keys),
                "current_candidate_count": len(candidate_keys),
                "historical_assignment_is_current_candidate": key in candidate_keys,
                "historical_assignment_is_max_metric_overlap": key in max_keys,
            }
        )
    result = pd.DataFrame(rows)
    summary = {
        "evidence_type": "historical_assignment_regression",
        "row_count": len(result),
        "radios_with_current_positive_candidates": int(
            result["current_radio_has_positive_candidates"].sum()
        ),
        "historical_assignment_is_current_candidate": int(
            result["historical_assignment_is_current_candidate"].sum()
        ),
        "historical_assignment_is_max_metric_overlap": int(
            result["historical_assignment_is_max_metric_overlap"].sum()
        ),
        "interpretation": (
            "Diagnostic comparison only. Historical one-target assignments are not "
            "current relation truth or a published crosswalk."
        ),
    }
    return result, summary

def compare_historical_section_crosswalk(
    relation: pd.DataFrame,
    path: Path,
) -> tuple[pd.DataFrame, dict]:
    historical = pd.read_csv(path, dtype="string")
    required = {"codprov", "coddepto", "IN1"}
    if not required.issubset(historical.columns):
        raise ValueError(
            f"historical section crosswalk missing columns {sorted(required - set(historical.columns))}"
        )
    positive = relation.loc[relation["target_department_footprint_uid"].notna()].copy()
    positive["section_compare_key"] = [
        f"{_comparison_component(a)}|{_comparison_component(b)}"
        for a, b in zip(
            positive["electoral_district_code"],
            positive["electoral_section_code"],
            strict=True,
        )
    ]
    grouped = {
        key: group for key, group in positive.groupby("section_compare_key", sort=False)
    }

    rows: list[dict] = []
    for item in historical.itertuples(index=False):
        raw = item._asdict()
        section_key = (
            f"{_comparison_component(raw['codprov'])}|"
            f"{_comparison_component(raw['coddepto'])}"
        )
        department = str(raw["IN1"]).strip()
        group = grouped.get(section_key)
        candidates = (
            set(group["target_department_2010_id"].dropna().astype(str))
            if group is not None
            else set()
        )
        rows.append(
            {
                "electoral_section_comparison_key": section_key,
                "historical_department_id": department,
                "current_department_candidate_count": len(candidates),
                "historical_department_is_current_candidate": department in candidates,
            }
        )
    result = pd.DataFrame(rows)
    summary = {
        "evidence_type": "historical_section_department_regression",
        "row_count": len(result),
        "historical_department_is_current_candidate": int(
            result["historical_department_is_current_candidate"].sum()
        ),
        "interpretation": (
            "Historical one-target section→department mappings are regression evidence. "
            "Current section↔department facts remain N:M."
        ),
    }
    return result, summary

def elecciones_compatibility(
    circuits_dim: pd.DataFrame,
    path: Path,
) -> tuple[pd.DataFrame, dict]:
    election = pd.read_csv(path, dtype="string")
    required = {"distrito_id", "seccion_id", "circuito_id"}
    if not required.issubset(election.columns):
        raise ValueError(
            f"elecciones-ARG circuit table missing columns {sorted(required - set(election.columns))}"
        )
    election = election.dropna(subset=["distrito_id", "seccion_id", "circuito_id"]).copy()
    election["compatibility_key"] = [
        f"{_comparison_component(a)}|{_comparison_component(b)}|{str(c).strip()}"
        for a, b, c in zip(
            election["distrito_id"],
            election["seccion_id"],
            election["circuito_id"],
            strict=True,
        )
    ]
    counts = election["compatibility_key"].value_counts()

    rows: list[dict] = []
    for row in circuits_dim.itertuples():
        district = _comparison_component(row.electoral_district_code)
        section = _comparison_component(row.electoral_section_code)
        circuito_raw = str(row.electoral_circuit_code)
        if circuito_raw.isdigit():
            circuito_projected = circuito_raw.zfill(6)
        else:
            circuito_projected = circuito_raw
        key = (
            f"{district}|{section}|{circuito_projected}"
            if district is not None and section is not None
            else None
        )
        match_count = int(counts.get(key, 0)) if key is not None else 0
        rows.append(
            {
                "relation_target_uid": row.relation_target_uid,
                "identity_status": row.identity_status,
                "electoral_district_code": row.electoral_district_code,
                "electoral_section_code": row.electoral_section_code,
                "electoral_circuit_code": row.electoral_circuit_code,
                "projected_elecciones_key": key,
                "matching_elecciones_rows": match_count,
                "compatible_any": match_count > 0,
            }
        )
    result = pd.DataFrame(rows)
    complete = result["identity_status"].eq("complete_composite")
    summary = {
        "evidence_type": "elecciones_ARG_read_only_key_compatibility",
        "row_count": len(result),
        "complete_identity_row_count": int(complete.sum()),
        "complete_identity_compatible_count": int(
            (complete & result["compatible_any"]).sum()
        ),
        "complete_identity_compatibility_share": (
            float((complete & result["compatible_any"]).sum() / complete.sum())
            if complete.any()
            else None
        ),
        "interpretation": (
            "Compatibility is an observed consumer-key projection, not electoral "
            "geography authority and not an identity rewrite."
        ),
    }
    return result, summary
