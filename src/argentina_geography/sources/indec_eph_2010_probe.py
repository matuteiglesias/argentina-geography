from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile

import geopandas as gpd
import pandas as pd

from argentina_geography.products import read_json, sha256_file, write_json

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config/sources/indec_eph_census2010_radio.json"


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    return read_json(path)


def download_file(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "argentina-geography/0.1 research-data-client"})
    with urlopen(request, timeout=300) as response, destination.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    if destination.stat().st_size == 0:
        raise ValueError(f"INDEC EPH download returned an empty file: {url}")
    return destination


def _zip_members(path: Path) -> list[str]:
    with ZipFile(path) as archive:
        return sorted(name for name in archive.namelist() if not name.endswith("/"))


def _field_profile(frame: gpd.GeoDataFrame, field: str) -> dict:
    series = frame[field]
    values = series.dropna().map(lambda value: str(value).strip())
    lengths = values.map(len).value_counts().sort_index()
    return {
        "dtype": str(series.dtype),
        "null_count": int(series.isna().sum()),
        "unique_count": int(series.nunique(dropna=True)),
        "length_counts": {str(int(length)): int(count) for length, count in lengths.items()},
        "sample_values": values.drop_duplicates().head(15).tolist(),
    }


def _direct_identity_profile(frame: gpd.GeoDataFrame) -> dict:
    required = {"codprov", "coddepto", "frac2010", "radio2010", "eph_codagl", "eph_aglome"}
    missing = sorted(required - set(frame.columns))
    if missing:
        return {"available": False, "missing_fields": missing}

    radio_id = (
        frame["codprov"].astype(str).str.strip()
        + frame["coddepto"].astype(str).str.strip()
        + frame["frac2010"].astype(str).str.strip()
        + frame["radio2010"].astype(str).str.strip()
    )
    relation = pd.DataFrame(
        {
            "radio_2010_id": radio_id,
            "eph_agglomerate_id": frame["eph_codagl"].astype(str).str.strip(),
            "eph_agglomerate_name": frame["eph_aglome"].astype(str).str.strip(),
            "geometry_present": frame.geometry.notna(),
        }
    )
    duplicate_mask = radio_id.duplicated(False)
    grouped = relation.groupby("radio_2010_id", sort=True)
    group_summary = grouped.agg(
        source_row_count=("radio_2010_id", "size"),
        agglomerate_code_count=("eph_agglomerate_id", "nunique"),
        agglomerate_name_count=("eph_agglomerate_name", "nunique"),
        geometry_present_count=("geometry_present", "sum"),
    )
    duplicate_groups = group_summary.loc[group_summary["source_row_count"] > 1]
    conflicts = group_summary.loc[group_summary["agglomerate_code_count"] > 1]
    name_conflicts = group_summary.loc[group_summary["agglomerate_name_count"] > 1]
    all_geometry_missing = group_summary.loc[group_summary["geometry_present_count"] == 0]
    partial_geometry_missing = group_summary.loc[
        (group_summary["geometry_present_count"] > 0)
        & (group_summary["geometry_present_count"] < group_summary["source_row_count"])
    ]

    conflict_records = []
    for radio in conflicts.index.tolist():
        rows = relation.loc[relation["radio_2010_id"] == radio]
        conflict_records.append(
            {
                "radio_2010_id": radio,
                "eph_agglomerate_ids": sorted(rows["eph_agglomerate_id"].unique().tolist()),
                "eph_agglomerate_names": sorted(rows["eph_agglomerate_name"].unique().tolist()),
            }
        )

    agglomerate_names = (
        relation[["eph_agglomerate_id", "eph_agglomerate_name"]]
        .drop_duplicates()
        .sort_values(["eph_agglomerate_id", "eph_agglomerate_name"])
        .groupby("eph_agglomerate_id", dropna=False)["eph_agglomerate_name"]
        .agg(list)
    )
    row_counts = relation["eph_agglomerate_id"].value_counts().sort_index()
    relation_pairs = relation[["radio_2010_id", "eph_agglomerate_id"]].drop_duplicates()
    relation_payload = "\n".join(
        f"{row.radio_2010_id}\t{row.eph_agglomerate_id}"
        for row in relation_pairs.sort_values(["radio_2010_id", "eph_agglomerate_id"]).itertuples()
    )
    relation_sha256 = hashlib.sha256(relation_payload.encode("utf-8")).hexdigest()

    return {
        "available": True,
        "candidate_composition": "codprov+coddepto+frac2010+radio2010",
        "candidate_radio_2010_id_count": int(radio_id.nunique()),
        "candidate_width_counts": {
            str(int(width)): int(count) for width, count in radio_id.str.len().value_counts().sort_index().items()
        },
        "duplicate_candidate_radio_2010_id_row_count": int(duplicate_mask.sum()),
        "duplicate_radio_group_count": int(len(duplicate_groups)),
        "extra_source_rows_beyond_unique_radio_grain": int(len(frame) - radio_id.nunique()),
        "max_source_rows_per_radio": int(group_summary["source_row_count"].max()),
        "radio_to_agglomerate_relation_pair_count": int(len(relation_pairs)),
        "radio_to_agglomerate_relation_sha256": relation_sha256,
        "radio_with_multiple_agglomerate_code_count": int(len(conflicts)),
        "radio_with_multiple_agglomerate_codes": conflict_records,
        "radio_with_multiple_agglomerate_name_count": int(len(name_conflicts)),
        "all_geometry_missing_radio_count": int(len(all_geometry_missing)),
        "all_geometry_missing_radio_2010_ids": sorted(all_geometry_missing.index.tolist()),
        "partial_geometry_missing_radio_count": int(len(partial_geometry_missing)),
        "partial_geometry_missing_radio_2010_ids": sorted(partial_geometry_missing.index.tolist()),
        "duplicate_radio_sample": [
            {
                "radio_2010_id": str(index),
                "source_row_count": int(row.source_row_count),
                "agglomerate_code_count": int(row.agglomerate_code_count),
                "geometry_present_count": int(row.geometry_present_count),
            }
            for index, row in duplicate_groups.head(25).iterrows()
        ],
        "agglomerate_code_count": int(relation["eph_agglomerate_id"].nunique()),
        "agglomerate_codes": sorted(relation["eph_agglomerate_id"].unique().tolist()),
        "agglomerate_code_to_names": {
            str(code): [str(name) for name in names] for code, names in agglomerate_names.items()
        },
        "agglomerate_codes_with_multiple_names": {
            str(code): [str(name) for name in names]
            for code, names in agglomerate_names.items()
            if len(names) > 1
        },
        "rows_by_agglomerate_code": {
            str(code): int(count) for code, count in row_counts.items()
        },
    }


def _profile_vector(path: Path, label: str) -> dict:
    if path.read_bytes()[:2] != b"PK":
        raise ValueError(f"{label} is not the expected ZIP archive: {path}")
    source = f"zip://{path.resolve()}"
    layers = gpd.list_layers(source)
    layer_records = layers.astype(object).where(layers.notna(), None).to_dict(orient="records")
    if len(layers) != 1:
        raise ValueError(f"{label} expected one vector layer; observed {layer_records}")
    layer_name = str(layers.iloc[0]["name"])
    read_kwargs: dict[str, object] = {"engine": "pyogrio", "use_arrow": False}
    if label == "shapefile":
        read_kwargs["encoding"] = "CP1252"
    frame = gpd.read_file(source, layer=layer_name, **read_kwargs)
    geometry_name = frame.geometry.name
    fields = [column for column in frame.columns if column != geometry_name]
    geometry = frame.geometry
    preview = frame[fields].head(12).copy()
    preview = preview.astype(object).where(preview.notna(), "<NA>")
    profiles = {field: _field_profile(frame, field) for field in fields}
    return {
        "label": label,
        "file_name": path.name,
        "source_sha256": sha256_file(path),
        "source_size_bytes": path.stat().st_size,
        "source_encoding_override": "CP1252" if label == "shapefile" else None,
        "zip_members": _zip_members(path),
        "layers": layer_records,
        "layer_name": layer_name,
        "feature_count": len(frame),
        "columns": frame.columns.tolist(),
        "field_profiles": profiles,
        "potential_identity_fields": [
            field
            for field, profile in profiles.items()
            if profile["null_count"] == 0 and profile["unique_count"] == len(frame)
        ],
        "direct_identity_profile": _direct_identity_profile(frame),
        "first_records": preview.map(str).to_dict(orient="records"),
        "crs": None if frame.crs is None else frame.crs.to_string(),
        "geometry_types": sorted(geometry.geom_type.dropna().unique().tolist()),
        "missing_geometry_count": int(geometry.isna().sum()),
        "empty_geometry_count": int(geometry.is_empty.sum()),
        "invalid_geometry_count": int((geometry.notna() & ~geometry.is_valid).sum()),
        "bbox": [float(value) for value in frame.total_bounds.tolist()],
    }


def _profile_workbook(path: Path, label: str) -> dict:
    workbook = pd.ExcelFile(path)
    sheets = []
    for sheet_name in workbook.sheet_names:
        frame = pd.read_excel(path, sheet_name=sheet_name, header=None, dtype=object)
        preview = frame.head(30).astype(object).where(frame.head(30).notna(), "<NA>")
        sheets.append(
            {
                "sheet_name": str(sheet_name),
                "row_count": len(frame),
                "column_count": len(frame.columns),
                "first_rows": preview.map(str).values.tolist(),
            }
        )
    return {
        "label": label,
        "file_name": path.name,
        "source_sha256": sha256_file(path),
        "source_size_bytes": path.stat().st_size,
        "sheet_count": len(sheets),
        "sheets": sheets,
    }


def probe(source_dir: Path, output: Path, config_path: Path = DEFAULT_CONFIG) -> dict:
    config = load_config(config_path)
    source_dir.mkdir(parents=True, exist_ok=True)

    vector_evidence = {}
    for label, spec in config["radio_sources"].items():
        path = source_dir / spec["file_name"]
        download_file(spec["download_url"], path)
        vector_evidence[label] = _profile_vector(path, label)

    document_evidence = {}
    for label, spec in config["documentation_sources"].items():
        path = source_dir / spec["file_name"]
        download_file(spec["download_url"], path)
        document_evidence[label] = _profile_workbook(path, label)

    vector_signatures = {
        label: {
            "feature_count": item["feature_count"],
            "crs": item["crs"],
            "candidate_radio_2010_id_count": item["direct_identity_profile"].get(
                "candidate_radio_2010_id_count"
            ),
            "agglomerate_code_count": item["direct_identity_profile"].get("agglomerate_code_count"),
            "relation_pair_count": item["direct_identity_profile"].get(
                "radio_to_agglomerate_relation_pair_count"
            ),
            "relation_sha256": item["direct_identity_profile"].get(
                "radio_to_agglomerate_relation_sha256"
            ),
            "radio_with_multiple_agglomerate_code_count": item["direct_identity_profile"].get(
                "radio_with_multiple_agglomerate_code_count"
            ),
            "missing_geometry_count": item["missing_geometry_count"],
            "invalid_geometry_count": item["invalid_geometry_count"],
        }
        for label, item in vector_evidence.items()
    }
    evidence = {
        "source_id": config["source_id"],
        "provider": config["provider"],
        "authority_status": config["authority_status"],
        "source_page": config["source_page"],
        "release": config["release"],
        "census_basis": config["census_basis"],
        "parent_census_2010": config["parent_census_2010"],
        "vectors": vector_evidence,
        "documentation": document_evidence,
        "vector_semantic_signatures": vector_signatures,
        "vector_semantic_signature_equivalent": len(
            {json.dumps(value, sort_keys=True, ensure_ascii=False) for value in vector_signatures.values()}
        )
        == 1,
    }
    write_json(output, evidence)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Characterize the official INDEC EPH Census-2010-based radio coverage before normalization."
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    probe(args.source_dir, args.output, args.config)


if __name__ == "__main__":
    main()
