from __future__ import annotations

import argparse
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


def _profile_vector(path: Path, label: str) -> dict:
    if path.read_bytes()[:2] != b"PK":
        raise ValueError(f"{label} is not the expected ZIP archive: {path}")
    source = f"zip://{path.resolve()}"
    layers = gpd.list_layers(source)
    layer_records = layers.astype(object).where(layers.notna(), None).to_dict(orient="records")
    if len(layers) != 1:
        raise ValueError(f"{label} expected one vector layer; observed {layer_records}")
    layer_name = str(layers.iloc[0]["name"])
    frame = gpd.read_file(source, layer=layer_name, engine="pyogrio", use_arrow=True)
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
            "columns": item["columns"],
            "crs": item["crs"],
            "geometry_types": item["geometry_types"],
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
        "vector_signatures": vector_signatures,
        "vector_schema_equivalent": len(
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
