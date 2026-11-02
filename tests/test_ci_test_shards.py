"""Guard native shard completeness, source binding and failure propagation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from scripts.ci_test_shards import check_results, select, verify
from scripts.circleci_standards import command_contract_findings, validation_scheduled

ROOT = Path(__file__).resolve().parents[1]


def test_real_pytest_shards_fail_closed_then_cover_the_full_fixture(tmp_path: Path) -> None:
    """Run the actual adapter, pytest workers, JUnit and success join together."""
    (tmp_path / "test_fixture.py").write_text(
        "import os\nimport pytest\n"
        "@pytest.mark.parametrize('number', range(8))\n"
        "def test_value(number):\n"
        "    assert not (number == 7 and os.environ.get('SDK_SHARD_FAIL') == '1')\n"
    )
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("GIT_") and name not in {"PYTEST_ADDOPTS", "BASH_ENV"}
    }
    for arguments in (
        ["init"],
        ["add", "."],
        [
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "fixture",
        ],
    ):
        subprocess.run(["git", *arguments], cwd=tmp_path, env=environment, capture_output=True, check=True)
    command = [sys.executable, str(ROOT / "scripts/ci_test_shards.py")]
    subprocess.run([*command, "collect"], cwd=tmp_path, env=environment, capture_output=True, check=True)
    failed = subprocess.run(
        [*command, "run", "--index", "1"],
        cwd=tmp_path,
        env={**environment, "SDK_SHARD_FAIL": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode == 1, failed.stdout + failed.stderr
    assert not (tmp_path / "test-results/shard-1.json").exists()
    for index in range(2):
        passed = subprocess.run(
            [*command, "run", "--index", str(index)],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert passed.returncode == 0, passed.stdout + passed.stderr
    joined = subprocess.run(
        [*command, "verify"], cwd=tmp_path, env=environment, capture_output=True, text=True, check=False
    )
    assert joined.returncode == 0, joined.stdout + joined.stderr


def _evidence(root: Path) -> None:
    """Create bounded synthetic successful receipts for verifier negative controls."""
    identities = [f"tests/test_fixture.py::test_case[{index}]" for index in range(7)]
    (root / "collection.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "revision": "candidate",
                "collection": identities,
            }
        )
    )
    for index in range(2):
        selected = select(identities, index, 2)
        (root / f"shard-{index}.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "revision": "candidate",
                    "index": index,
                    "total": 2,
                    "collection": identities,
                    "selected": selected,
                }
            )
        )
        xml = ET.Element("testsuites")
        for identity in selected:
            ET.SubElement(xml, "testcase", classname="tests.test_fixture", name=identity.split("::")[1])
        ET.ElementTree(xml).write(root / f"shard-{index}.xml")


@pytest.mark.parametrize("damage", ["missing", "stale", "duplicate", "foreign", "collection", "failed", "short"])
def test_incomplete_or_failed_shards_cannot_turn_green(tmp_path: Path, damage: str) -> None:
    """Require exact selection, matching source and successful complete results."""
    _evidence(tmp_path)
    verify(tmp_path, "candidate")
    path = tmp_path / "shard-1.json"
    receipt = json.loads(path.read_text())
    if damage == "missing":
        path.unlink()
    elif damage in {"failed", "short"}:
        xml = tmp_path / "shard-1.xml"
        tree = ET.parse(xml)
        case = tree.getroot()[0]
        if damage == "failed":
            ET.SubElement(case, "failure")
        else:
            tree.getroot().remove(case)
        tree.write(xml)
    else:
        if damage == "stale":
            receipt["revision"] = "old"
        elif damage == "duplicate":
            receipt["selected"][1] = receipt["selected"][0]
        elif damage == "foreign":
            receipt["selected"][0] = "tests/test_elsewhere.py::test_wrong"
        else:
            receipt["collection"].append("tests/test_fixture.py::test_new")
        path.write_text(json.dumps(receipt))
    with pytest.raises((ValueError, FileNotFoundError)):
        verify(tmp_path, "candidate")
    _evidence(tmp_path)
    verify(tmp_path, "candidate")


def test_partition_is_complete_balanced_and_rejects_ambiguous_inputs() -> None:
    """Exercise parameter IDs, empty and duplicate collections, and bad topology."""
    identities = [f"tests/test_fixture.py::test_case[{index}::parameter]" for index in range(9)]
    parts = [select(identities, index, 2) for index in range(2)]
    assert sorted(parts[0] + parts[1]) == sorted(identities)
    assert not set(parts[0]) & set(parts[1])
    for values, index, total in [
        ([], 0, 2),
        (identities * 2, 0, 2),
        (identities, 2, 2),
        (identities, 0, 1),
        (["one\ntwo", "three"], 0, 2),
    ]:
        with pytest.raises(ValueError):
            select(values, index, total)


def test_collection_errors_in_junit_are_not_success(tmp_path: Path) -> None:
    """Reject setup or collection errors even with a matching test count."""
    path = tmp_path / "result.xml"
    path.write_text("<testsuites><testsuite><testcase><error/></testcase></testsuite></testsuites>")
    with pytest.raises(ValueError):
        check_results(path, ["test_fixture.py::test_value"])


def test_equal_count_wrong_junit_and_shared_omissions_fail(tmp_path: Path) -> None:
    """Reject the independent review's equal-count substitution and common omission controls."""
    _evidence(tmp_path)
    xml = tmp_path / "shard-1.xml"
    tree = ET.parse(xml)
    tree.getroot()[0].set("name", "foreign_test")
    tree.write(xml)
    with pytest.raises(ValueError):
        verify(tmp_path, "candidate")
    _evidence(tmp_path)
    for index in range(2):
        path = tmp_path / f"shard-{index}.json"
        receipt = json.loads(path.read_text())
        receipt["collection"] = receipt["collection"][:-1]
        receipt["selected"] = select(receipt["collection"], index, 2)
        path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        verify(tmp_path, "candidate")


def test_required_join_cannot_omit_a_shard_or_installed_proof() -> None:
    """Keep the canonical check downstream of every full-validation lane."""
    config = yaml.safe_load((ROOT / ".circleci/config.yml").read_text())
    assert validation_scheduled(config)
    assert not command_contract_findings(config)
    config["workflows"]["validation"]["jobs"][-1]["validate"]["requires"].remove("installed")
    assert not validation_scheduled(config)
    config = yaml.safe_load((ROOT / ".circleci/config.yml").read_text())
    config["jobs"]["tests"]["parallelism"] = 1
    assert command_contract_findings(config)
