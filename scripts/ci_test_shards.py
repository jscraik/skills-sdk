"""Partition the full pytest collection and verify every native CI shard."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from _pytest.junitxml import bin_xml_escape, mangle_test_address


class Collection:
    """Capture the actual pinned pytest collection without running tests."""

    def __init__(self) -> None:
        self.identities: list[str] = []

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        """Retain exact parameterized node IDs from pytest."""
        self.identities = [item.nodeid for item in session.items]


def select(identities: list[str], index: int, total: int) -> list[str]:
    """Reject invalid partitions and preserve each collected test exactly once."""
    if total != 2 or index not in range(total):
        raise ValueError("SDK full CI requires two test shards, indexed 0 and 1")
    if len(identities) < total or len(set(identities)) != len(identities):
        raise ValueError("full collection is empty, too small or duplicated")
    if any(not identity or "\n" in identity or "\r" in identity for identity in identities):
        raise ValueError("test identity cannot be represented in a pytest argument file")
    return sorted(identities)[index::total]


def check_results(path: Path, expected: list[str]) -> None:
    """Reject missing, failed or incomplete JUnit evidence."""
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    identities = [mangle_test_address(identity) for identity in expected]
    wanted = Counter((".".join(names[:-1]), bin_xml_escape(names[-1])) for names in identities)
    actual = Counter((case.get("classname"), case.get("name")) for case in cases)
    if actual != wanted or root.findall(".//failure") or root.findall(".//error"):
        raise ValueError("shard JUnit does not prove the complete successful selection")


def revision() -> str:
    """Read the prepared checkout identity shared by every job."""
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def collect() -> list[str]:
    """Collect the complete pinned suite, failing on collection errors."""
    collection = Collection()
    captured = io.StringIO()
    with redirect_stdout(captured):
        status = pytest.main(["--collect-only", "-q"], plugins=[collection])
    if status != 0:
        print(captured.getvalue(), file=sys.stderr)
        raise ValueError("full pytest collection failed")
    select(collection.identities, 0, 2)
    return sorted(collection.identities)


def read_catalog(path: Path, expected_revision: str) -> list[str]:
    """Require the authoritative collection from the preparation job."""
    catalog = json.loads(path.read_text())
    if catalog["schema_version"] != 1 or catalog["revision"] != expected_revision:
        raise ValueError("stale authoritative collection")
    select(catalog["collection"], 0, 2)
    return catalog["collection"]


def run_shard(index: int, total: int, output: Path, catalog: Path) -> int:
    """Run a verified complete collection's slice with four isolated workers."""
    identities = collect()
    if identities != read_catalog(catalog, revision()):
        raise ValueError("local collection differs from prepared collection")
    selected = select(identities, index, total)
    output.mkdir(parents=True, exist_ok=True)
    receipt = output / f"shard-{index}.json"
    receipt.unlink(missing_ok=True)
    arguments = output / f"shard-{index}.txt"
    arguments.write_text("\n".join(selected) + "\n")
    junit = output / f"shard-{index}.xml"
    junit.unlink(missing_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            f"@{arguments}",
            "-n",
            "4",
            "--dist",
            "load",
            "--durations=25",
            "--durations-min=0.1",
            f"--junitxml={junit}",
            "-o",
            "junit_family=xunit1",
        ],
        check=False,
    )
    if result.returncode:
        return result.returncode
    check_results(junit, selected)
    receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "revision": revision(),
                "index": index,
                "total": total,
                "collection": identities,
                "selected": selected,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0


def verify(output: Path, expected_revision: str) -> None:
    """Require both current-source shards and the exact complete collection."""
    receipts = [json.loads((output / f"shard-{index}.json").read_text()) for index in range(2)]
    catalog = read_catalog(output / "collection.json", expected_revision)
    for index, receipt in enumerate(receipts):
        if (receipt["schema_version"], receipt["revision"], receipt["index"], receipt["total"]) != (
            1,
            expected_revision,
            index,
            2,
        ):
            raise ValueError("stale or invalid shard identity")
        if receipt["collection"] != catalog:
            raise ValueError("shards collected different test suites")
        expected = select(receipt["collection"], index, 2)
        if receipt["selected"] != expected:
            raise ValueError("missing, duplicated or foreign test selection")
        check_results(output / f"shard-{index}.xml", expected)


def main() -> int:
    """Expose bounded native-shard execution and the required success join."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["collect", "run", "verify"])
    parser.add_argument("--catalog", type=Path, default=Path("test-results/collection.json"))
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--total", type=int, default=2)
    parser.add_argument("--output", type=Path, default=Path("test-results"))
    args = parser.parse_args()
    if args.mode == "collect":
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "collection.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "revision": revision(),
                    "collection": collect(),
                }
            )
            + "\n"
        )
        return 0
    if args.mode == "run":
        return run_shard(args.index, args.total, args.output, args.catalog)
    verify(args.output, revision())
    print("Both test shards cover the complete prepared revision.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
