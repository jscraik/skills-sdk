"""Argument registration for existing source and scenario quality commands."""

from __future__ import annotations

import argparse
from pathlib import Path


def _add_coverage_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    coverage = commands.add_parser("scenario-coverage", help="audit declared claims against active cases and gaps")
    coverage.add_argument("package_root", type=Path)
    coverage.add_argument("--source-revision", required=True)
    coverage.add_argument("--scenario-set", required=True)
    coverage.add_argument("--coverage-plan", type=Path, required=True)
    coverage.add_argument("--json", action="store_true", dest="json_output")
    coverage.add_argument("--robot", action="store_true")


def _add_content_review_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    review = commands.add_parser("review-content", help="bind supplied content review to the current package")
    review.add_argument("package_root", type=Path)
    review.add_argument("--source-revision", required=True)
    review.add_argument("--assessment", type=Path, required=True)
    review.add_argument("--json", action="store_true", dest="json_output")
    review.add_argument("--robot", action="store_true")


def _add_quality_parser(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the v2 quality command and its request, baseline, and assessment inputs."""
    quality = commands.add_parser("check-quality", help="run explicit v2 intent, policy and content quality checks")
    quality.add_argument("package_root", type=Path)
    quality.add_argument("--request", type=Path, required=True)
    quality.add_argument("--baseline-root", type=Path)
    quality.add_argument("--assessment", type=Path)
    quality.add_argument("--json", action="store_true", dest="json_output")
    quality.add_argument("--robot", action="store_true")
