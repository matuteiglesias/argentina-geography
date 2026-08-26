from __future__ import annotations

import argparse
from pathlib import Path

from argentina_geography.electoral.config import DEFAULT_CONFIG, load_config
from argentina_geography.electoral.core import build_products
from argentina_geography.electoral.evidence import (
    compare_historical_radio_crosswalk,
    compare_historical_section_crosswalk,
    elecciones_compatibility,
)
from argentina_geography.electoral.materialize import materialize_vertical
from argentina_geography.electoral.verify import verify_vertical, write_release_identity

__all__ = [
    "DEFAULT_CONFIG",
    "build_products",
    "compare_historical_radio_crosswalk",
    "compare_historical_section_crosswalk",
    "elecciones_compatibility",
    "load_config",
    "materialize_vertical",
    "verify_vertical",
    "write_release_identity",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build the Argentina Geography electoral vertical from exact Census 2010 "
            "and Tartagalensis circuit releases."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    materialize = sub.add_parser("materialize")
    materialize.add_argument("--census-release", type=Path, required=True)
    materialize.add_argument("--circuit-release", type=Path, required=True)
    materialize.add_argument("--vintage", choices=("2021", "2025"), required=True)
    materialize.add_argument("--output", type=Path, required=True)
    materialize.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    materialize.add_argument("--historical-radio-crosswalk", type=Path)
    materialize.add_argument("--historical-section-crosswalk", type=Path)
    materialize.add_argument("--elecciones-circuit-table", type=Path)

    verify = sub.add_parser("verify")
    verify.add_argument("--release", type=Path, required=True)
    verify.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    identity = sub.add_parser("release-identity")
    identity.add_argument("--release", type=Path, required=True)
    identity.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "materialize":
        materialize_vertical(
            args.census_release,
            args.circuit_release,
            args.output,
            args.vintage,
            config_path=args.config,
            historical_radio_crosswalk=args.historical_radio_crosswalk,
            historical_section_crosswalk=args.historical_section_crosswalk,
            elecciones_circuit_table=args.elecciones_circuit_table,
        )
        verify_vertical(args.output, args.config)
    elif args.command == "verify":
        verify_vertical(args.release, args.config)
    else:
        write_release_identity(args.release, args.output)


if __name__ == "__main__":
    main()
