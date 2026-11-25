"""Check that a live Tessl loop and a committed manifest select the same project."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


def _read_json(*command: str) -> Any:
    return json.loads(subprocess.check_output(command, text=True))


def check_loop_project(revision: str, loop_id: str) -> str:
    """Return the matched project locator, or raise if it cannot be verified."""
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"], text=True
    ).strip()
    manifest = _read_json("git", "show", f"{commit}:tessl.json")
    locator = manifest["name"]
    if not isinstance(locator, str):
        raise ValueError("expected a workspace/project name in tessl.json")
    workspace, separator, name = locator.partition("/")
    if not separator or not workspace or not name or "/" in name:
        raise ValueError("expected a workspace/project name in tessl.json")

    listing = _read_json("tessl", "project", "list", "--workspace", workspace, "--json")
    matches = [project for project in listing["projects"] if project["name"] == name]
    if len(matches) != 1:
        raise ValueError(f"cannot resolve an unambiguous Tessl project for {locator}")
    project = matches[0]
    expected = (project["workspaceId"], project["id"])
    if not all(isinstance(identifier, str) and identifier for identifier in expected):
        raise ValueError(f"Tessl project identifiers are missing for {locator}")

    loop = _read_json("tessl", "loop", "view", loop_id, "--json")["data"]["attributes"]
    actual = (loop["workspaceId"], loop["projectId"])
    if actual != expected:
        raise ValueError(f"loop {loop_id} belongs to workspace/project IDs {actual}, expected {expected} for {locator}")
    return locator


def main() -> int:
    """Read project identity without starting a Tessl run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="Git revision the loop will check out")
    parser.add_argument("--loop", required=True, help="Live Tessl loop ID")
    options = parser.parse_args()
    try:
        locator = check_loop_project(options.revision, options.loop)
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError) as error:
        print(f"Tessl loop preflight failed: {error}", file=sys.stderr)
        return 1
    print(f"Tessl loop {options.loop} matches {locator}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
