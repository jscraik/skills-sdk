from __future__ import annotations

import argparse
from collections.abc import Sequence

from skills_sdk import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the boundary-only command parser."""
    parser = argparse.ArgumentParser(
        prog="skills-sdk",
        description="Portable lifecycle contracts and tooling for Agent Skills packages.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the currently supported boundary-only command surface."""
    build_parser().parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
