from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from empirical_contracts import DatasetRef, RunManifest

JSON_ARGS = {"ensure_ascii": False, "indent": 2, "sort_keys": True}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, **JSON_ARGS) + "\n", encoding="utf-8", newline="\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_checksums(directory: Path, filenames: list[str]) -> None:
    lines = [f"{sha256_file(directory / name)}  {name}" for name in sorted(filenames)]
    (directory / "checksums.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def verify_checksums(directory: Path) -> None:
    checksum_path = directory / "checksums.txt"
    if not checksum_path.exists():
        raise ValueError(f"missing checksums: {checksum_path}")
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        expected, name = line.split("  ", maxsplit=1)
        actual = sha256_file(directory / name)
        if actual != expected:
            raise ValueError(f"checksum mismatch for {directory / name}")


def validate_manifest(path: Path) -> dict[str, Any]:
    manifest = read_json(path)
    DatasetRef.model_validate(manifest["dataset"])
    RunManifest.model_validate(manifest["run"])
    return manifest
