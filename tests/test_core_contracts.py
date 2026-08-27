from __future__ import annotations

import copy
import json
from importlib.resources import files

import pytest
from jsonschema import Draft202012Validator

from skills_sdk.core.errors import ContractError
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.core.receipts import CandidateIdentity, parse_receipt
from skills_sdk.core.schema_registry import SCHEMA_NAMES, SchemaRegistry

EXPECTED_PORTABLE_PATH_PATTERN = (
    r"^(?=.*\S)(?!.*[\r\n])(?!/)(?!.*\\)(?!.*(?:^|/)\.\.?(?:/|$))(?![^/]*:)(?!.*//)"
    r"(?!.*(?:^|/)\./)(?!.*\/$)[\s\S]+$"
)

PORTABLE_PATH_SCHEMA_NAMES = (
    "blocker.v1",
    "normalized-package.v1",
    "package-inventory-set.v1",
    "package-inventory.v1",
    "package-manifest.v1",
    "package-owner.v1",
    "package-receipt.v1",
    "package-receipt.v2",
    "package-source.v1",
    "receipt-base.v1",
    "security-screening.v1",
)


def _receipt() -> dict[str, object]:
    return {
        "schema_version": "receipt-base/v1",
        "receipt_id": "synthetic-validation-1",
        "candidate": {
            "package_id": "synthetic-skill",
            "source_revision": "1" * 40,
            "content_sha256": "a" * 64,
        },
        "lane": "validation",
        "status": "pass",
        "started_at": "2026-08-25T10:00:00Z",
        "finished_at": "2026-08-25T10:00:01Z",
        "evidence": ["tests/fixtures/synthetic-skill/SKILL.md"],
    }


@pytest.mark.parametrize("name", sorted(SCHEMA_NAMES))
def test_packaged_schemas_are_valid(name: str) -> None:
    assert SchemaRegistry().load(name)["$schema"].endswith("2020-12/schema")
    assert files("skills_sdk.schemas").joinpath(f"{name}.schema.json").is_file()


def test_valid_receipt_is_immutable_and_candidate_bound() -> None:
    receipt = parse_receipt(_receipt())
    expected = CandidateIdentity("synthetic-skill", "1" * 40, "a" * 64)
    receipt.require_candidate(expected)
    with pytest.raises(TypeError):
        receipt.payload["status"] = "fail"


def test_candidate_mismatch_is_typed() -> None:
    receipt = parse_receipt(_receipt())
    other = CandidateIdentity("synthetic-skill", "2" * 40, "a" * 64)
    with pytest.raises(ContractError, match="candidate_mismatch"):
        receipt.require_candidate(other)


def test_unknown_schema_validation_is_typed() -> None:
    with pytest.raises(ContractError, match="unknown_schema"):
        SchemaRegistry().validate("unknown.v1", {})


def test_blocked_receipt_requires_typed_blocker() -> None:
    payload = _receipt()
    payload["status"] = "blocked"
    with pytest.raises(ContractError, match="contract_validation_failed"):
        parse_receipt(payload)


def test_non_blocked_receipt_rejects_blocker() -> None:
    payload = _receipt()
    payload["blocker"] = {"code": "unexpected", "message": "not blocked", "evidence_refs": []}
    with pytest.raises(ContractError, match="contract_validation_failed"):
        parse_receipt(payload)


@pytest.mark.parametrize(
    "value",
    [
        "/tmp/receipt.json",
        "../receipt.json",
        "C:/receipt.json",
        "a\\b.json",
        "receipt.json\n",
        "receipt.json\r",
        "   ",
    ],
)
def test_non_portable_paths_are_rejected(value: str) -> None:
    with pytest.raises(ContractError, match="invalid_portable_path"):
        require_portable_relative_path(value)


def test_receipt_schema_rejects_candidate_shape_drift() -> None:
    payload = copy.deepcopy(_receipt())
    payload["candidate"]["runtime_path"] = "/tmp/synthetic"
    with pytest.raises(ContractError, match="contract_validation_failed"):
        parse_receipt(payload)


def _contains_pattern(node: object, pattern: str) -> bool:
    if isinstance(node, dict):
        return node.get("pattern") == pattern or any(_contains_pattern(value, pattern) for value in node.values())
    if isinstance(node, list):
        return any(_contains_pattern(value, pattern) for value in node)
    return False


@pytest.mark.parametrize("name", PORTABLE_PATH_SCHEMA_NAMES)
def test_packaged_schemas_project_portable_path_constraints(name: str) -> None:
    schema = json.loads(files("skills_sdk.schemas").joinpath(f"{name}.schema.json").read_text(encoding="utf-8"))
    assert _contains_pattern(schema, EXPECTED_PORTABLE_PATH_PATTERN)


@pytest.mark.parametrize(
    "schema_name, path",
    [("receipt-base.v1", ("evidence",)), ("blocker.v1", ("evidence_refs",))],
)
@pytest.mark.parametrize("value", ["   ", "path/\n", "../outside", "path/"])
def test_generic_receipt_schemas_reject_non_portable_paths(
    schema_name: str, path: tuple[str, ...], value: str
) -> None:
    schema = SchemaRegistry().load(schema_name)
    if schema_name == "receipt-base.v1":
        payload = _receipt()
    else:
        payload = {"code": "unsafe_path", "message": "blocked", "evidence_refs": ["valid/path"]}
    target: object = payload
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = [value]  # type: ignore[index]
    if schema_name == "receipt-base.v1":
        with pytest.raises(ContractError, match="contract_validation_failed"):
            SchemaRegistry().validate(schema_name, payload)
    else:
        assert list(Draft202012Validator(schema).iter_errors(payload))
