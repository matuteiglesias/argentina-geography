from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile

import geopandas as gpd

from argentina_geography.products import read_json, sha256_file, write_json

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = ROOT / "config/sources/indec_census_2010_radio.json"


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    return read_json(path)


def download_file(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "argentina-geography/0.1 research-data-client"})
    with urlopen(request, timeout=300) as response, destination.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    if destination.stat().st_size == 0:
        raise ValueError(f"INDEC 2010 download returned an empty file: {url}")
    if destination.read_bytes()[:2] != b"PK":
        raise ValueError(f"INDEC 2010 response is not a ZIP archive: {url}")
    return destination


def _zip_members(source_path: Path) -> list[str]:
    with ZipFile(source_path) as archive:
        return sorted(name for name in archive.namelist() if not name.endswith("/"))


def _profile_field(frame: gpd.GeoDataFrame, field: str) -> dict:
    series = frame[field]
    values = series.dropna().map(lambda value: str(value).strip())
    lengths = values.map(len).value_counts().sort_index()
    return {
        "dtype": str(series.dtype),
        "null_count": int(series.isna().sum()),
        "unique_count": int(series.nunique(dropna=True)),
        "length_counts": {str(int(length)): int(count) for length, count in lengths.items()},
        "sample_values": values.drop_duplicates().head(12).tolist(),
    }


def _profile_one(source_path: Path, source_spec: dict) -> dict:
    source = f"zip://{source_path.resolve()}"
    layers = gpd.list_layers(source)
    layer_records = layers.astype(object).where(layers.notna(), None).to_dict(orient="records")
    if len(layers) != 1:
        raise ValueError(
            f"{source_spec['file_name']} expected exactly one vector layer; "
            f"observed {len(layers)}: {layer_records}"
        )
    layer_name = str(layers.iloc[0]["name"])
    frame = gpd.read_file(source, layer=layer_name, engine="pyogrio", use_arrow=True)
    geometry_name = frame.geometry.name
    fields = [column for column in frame.columns if column != geometry_name]
    profiles = {field: _profile_field(frame, field) for field in fields}
    potential_identity_fields = [
        field
        for field, profile in profiles.items()
        if profile["null_count"] == 0 and profile["unique_count"] == len(frame)
    ]
    geometry = frame.geometry
    preview = frame[fields].head(5).copy()
    preview = preview.astype(object).where(preview.notna(), "<NA>")
    return {
        **source_spec,
        "source_sha256": sha256_file(source_path),
        "source_size_bytes": source_path.stat().st_size,
        "zip_members": _zip_members(source_path),
        "layers": layer_records,
        "layer_name": layer_name,
        "feature_count": len(frame),
        "columns": frame.columns.tolist(),
        "field_profiles": profiles,
        "potential_identity_fields": potential_identity_fields,
        "first_records": preview.map(str).to_dict(orient="records"),
        "crs": None if frame.crs is None else frame.crs.to_string(),
        "geometry_types": sorted(geometry.geom_type.dropna().unique().tolist()),
        "missing_geometry_count": int(geometry.isna().sum()),
        "empty_geometry_count": int(geometry.is_empty.sum()),
        "invalid_geometry_count_after_driver_read": int(
            (geometry.notna() & ~geometry.is_valid).sum()
        ),
        "bbox": [float(value) for value in frame.total_bounds.tolist()],
    }


def _snapshot_sha(files: list[dict]) -> str:
    payload = "\n".join(
        f"{item['province_code']}\t{item['file_name']}\t{item['layer_name']}\t"
        f"{item['source_sha256']}\t{item['source_size_bytes']}"
        for item in sorted(files, key=lambda item: item["province_code"])
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def profile_sources(
    source_dir: Path, output: Path, summary_output: Path, config_path: Path = DEFAULT_CONFIG
) -> dict:
    config = load_config(config_path)
    evidence_files = []
    for source_spec in config["source_files"]:
        path = source_dir / source_spec["file_name"]
        download_file(source_spec["download_url"], path)
        evidence_files.append(_profile_one(path, source_spec))

    evidence = {
        "source_id": config["source_id"],
        "provider": config["provider"],
        "release": config["release"],
        "catalog_url": config["catalog_url"],
        "reference_url": config["reference_url"],
        "license_name": config["license_name"],
        "distribution_mode": config["distribution_mode"],
        "file_count": len(evidence_files),
        "feature_count": sum(item["feature_count"] for item in evidence_files),
        "snapshot_sha256": _snapshot_sha(evidence_files),
        "files": evidence_files,
    }
    write_json(output, evidence)

    schemas = {}
    for item in evidence_files:
        key = json.dumps(
            {
                "columns": item["columns"],
                "crs": item["crs"],
                "geometry_types": item["geometry_types"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        schemas.setdefault(key, []).append(item["province_code"])
    summary = {
        "source_id": evidence["source_id"],
        "release": evidence["release"],
        "file_count": evidence["file_count"],
        "feature_count": evidence["feature_count"],
        "snapshot_sha256": evidence["snapshot_sha256"],
        "schema_variant_count": len(schemas),
        "schema_variants": [
            {"province_codes": province_codes, **json.loads(key)}
            for key, province_codes in schemas.items()
        ],
        "files": [
            {
                "province_code": item["province_code"],
                "province_name": item["province_name"],
                "file_name": item["file_name"],
                "source_sha256": item["source_sha256"],
                "source_size_bytes": item["source_size_bytes"],
                "layer_name": item["layer_name"],
                "feature_count": item["feature_count"],
                "columns": item["columns"],
                "potential_identity_fields": item["potential_identity_fields"],
                "crs": item["crs"],
                "geometry_types": item["geometry_types"],
                "missing_geometry_count": item["missing_geometry_count"],
                "empty_geometry_count": item["empty_geometry_count"],
                "invalid_geometry_count_after_driver_read": item[
                    "invalid_geometry_count_after_driver_read"
                ],
                "field_profiles": item["field_profiles"],
            }
            for item in evidence_files
        ],
    }
    write_json(summary_output, summary)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Characterize the official INDEC Census 2010 province-by-radio files."
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    profile_sources(args.source_dir, args.output, args.summary_output, args.config)


if __name__ == "__main__":
    main()
