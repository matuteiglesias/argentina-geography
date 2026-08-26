from __future__ import annotations

import argparse
import warnings
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile

import geopandas as gpd

from argentina_geography.products import read_json, sha256_file, write_json

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config/sources/ceur_census_2022_radio_v2025_1.json"


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    return read_json(path)


def download_source(destination: Path, config: dict) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(
        config["download_url"],
        headers={"User-Agent": "argentina-geography/0.1 research-data-client"},
    )
    with urlopen(request, timeout=300) as response, destination.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    if destination.stat().st_size == 0:
        raise ValueError("CEUR V2025-1 download returned an empty source file")
    if destination.read_bytes()[:2] != b"PK":
        raise ValueError("CEUR V2025-1 response is not a ZIP archive; source endpoint may have changed")
    return destination


def _zip_members(source_path: Path) -> list[str]:
    with ZipFile(source_path) as archive:
        return sorted(name for name in archive.namelist() if not name.endswith("/"))


def _read_single_layer(source_path: Path) -> tuple[gpd.GeoDataFrame, list[dict]]:
    source = f"zip://{source_path.resolve()}"
    layers = gpd.list_layers(source)
    layer_records = layers.astype(object).where(layers.notna(), None).to_dict(orient="records")
    if len(layers) != 1:
        raise ValueError(
            "CEUR V2025-1 probe expected one vector layer in the source ZIP; "
            f"observed {len(layers)}: {layer_records}"
        )
    frame = gpd.read_file(source, layer=layers.iloc[0]["name"], engine="pyogrio", use_arrow=True)
    return frame, layer_records


def _profile_field(frame: gpd.GeoDataFrame, field: str) -> dict:
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


def profile_source(source_path: Path, output: Path, config_path: Path = DEFAULT_CONFIG) -> dict:
    config = load_config(config_path)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        frame, layers = _read_single_layer(source_path)

    geometry_name = frame.geometry.name
    fields = [column for column in frame.columns if column != geometry_name]
    field_profiles = {field: _profile_field(frame, field) for field in fields}
    potential_identity_fields = [
        field
        for field, profile in field_profiles.items()
        if profile["null_count"] == 0 and profile["unique_count"] == len(frame)
    ]
    geometry = frame.geometry
    preview = frame[fields].head(12).copy()
    preview = preview.astype(object).where(preview.notna(), "<NA>")
    evidence = {
        "source_id": config["source_id"],
        "record_uri": config["record_uri"],
        "release": config["release"],
        "file_name": config["file_name"],
        "download_url": config["download_url"],
        "license_name": config["license_name"],
        "distribution_mode": config["distribution_mode"],
        "source_sha256": sha256_file(source_path),
        "source_size_bytes": source_path.stat().st_size,
        "zip_members": _zip_members(source_path),
        "layers": layers,
        "feature_count": len(frame),
        "columns": frame.columns.tolist(),
        "field_profiles": field_profiles,
        "potential_identity_fields": potential_identity_fields,
        "first_records": preview.map(str).to_dict(orient="records"),
        "crs": None if frame.crs is None else frame.crs.to_string(),
        "geometry_types": sorted(geometry.geom_type.dropna().unique().tolist()),
        "missing_geometry_count": int(geometry.isna().sum()),
        "empty_geometry_count": int(geometry.is_empty.sum()),
        "invalid_geometry_count_after_driver_read": int((geometry.notna() & ~geometry.is_valid).sum()),
        "driver_runtime_warnings": sorted(
            {str(item.message) for item in caught if issubclass(item.category, RuntimeWarning)}
        ),
        "bbox": [float(value) for value in frame.total_bounds.tolist()],
    }
    write_json(output, evidence)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Characterize CEUR Census 2022 radio V2025-1 before normalization."
    )
    parser.add_argument("--source-out", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    config = load_config(args.config)
    download_source(args.source_out, config)
    profile_source(args.source_out, args.output, args.config)


if __name__ == "__main__":
    main()
