from __future__ import annotations

import argparse
from pathlib import Path

from argentina_geography.products import sha256_file, write_json
from argentina_geography.sources.indec_2022_radio import (
    _read_source,
    build_wfs_url,
    download_source,
    load_config,
)


def profile_source(source_path: Path, output: Path) -> dict:
    config = load_config()
    frame = _read_source(source_path, encoding=config.get("source_encoding"))
    fields = [field for field in config["required_fields"] if field in frame.columns]
    profiles = {}
    for field in fields:
        raw = frame[field].dropna()
        values = raw.map(lambda value: str(value).strip())
        lengths = values.map(len).value_counts().sort_index()
        profiles[field] = {
            "dtype": str(frame[field].dtype),
            "null_count": int(frame[field].isna().sum()),
            "length_counts": {str(int(length)): int(count) for length, count in lengths.items()},
            "sample_values": values.drop_duplicates().head(12).tolist(),
        }
    geometry = frame.geometry
    evidence = {
        "source_id": config["source_id"],
        "resource_uuid": config["resource_uuid"],
        "acquisition_url": build_wfs_url(config),
        "source_sha256": sha256_file(source_path),
        "source_encoding": config.get("source_encoding"),
        "feature_count": len(frame),
        "columns": frame.columns.tolist(),
        "crs": None if frame.crs is None else frame.crs.to_string(),
        "field_profiles": profiles,
        "first_records": frame[fields].head(12).map(lambda value: "<NA>" if value is None else str(value)).to_dict(orient="records"),
        "geometry_types": sorted(geometry.geom_type.dropna().unique().tolist()),
        "missing_geometry_count": int(geometry.isna().sum()),
        "empty_geometry_count": int(geometry.is_empty.sum()),
        "invalid_geometry_count_after_driver_read": int((geometry.notna() & ~geometry.is_valid).sum()),
        "bbox": [float(value) for value in frame.total_bounds.tolist()],
        "accepted_qa_warnings": config.get("accepted_qa_warnings", []),
    }
    write_json(output, evidence)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Characterize the live INDEC 2022 radio source without normalizing it."
    )
    parser.add_argument("--source-out", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = load_config()
    download_source(args.source_out, config)
    profile_source(args.source_out, args.output)


if __name__ == "__main__":
    main()
