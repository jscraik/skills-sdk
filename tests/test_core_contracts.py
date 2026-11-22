from __future__ import annotations

import copy
import json
from collections import UserList
from collections.abc import MutableMapping
from importlib.resources import files
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

from skills_sdk.core.errors import ContractError
from skills_sdk.core.paths import (
    PORTABLE_PATH_CONTROL_PATTERN,
    require_distinct_portable_restore_paths,
    require_portable_relative_path,
    require_portable_restore_path,
)
from skills_sdk.core.receipts import CandidateIdentity, parse_receipt
from skills_sdk.core.schema_registry import SCHEMA_NAMES, SchemaRegistry, _packaged_validation_resources

EXPECTED_PORTABLE_PATH_PATTERN = (
    rf"^(?=.*\S)(?![\s\S]*(?:{PORTABLE_PATH_CONTROL_PATTERN}))(?!/)(?!.*\\)(?!.*(?:^|/)\.\.?(?:/|$))(?![^/]*:)(?!.*//)"
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
        cast(MutableMapping[str, Any], receipt.payload)["status"] = "fail"


def test_receipt_owns_user_sequence_evidence() -> None:
    payload = _receipt()
    evidence = UserList(["tests/fixtures/synthetic-skill/SKILL.md"])
    payload["evidence"] = evidence
    receipt = parse_receipt(payload)
    evidence.append("tests/fixtures/later.md")
    assert receipt.payload["evidence"] == receipt.evidence == ("tests/fixtures/synthetic-skill/SKILL.md",)
    assert receipt.payload["status"] == "pass"
    assert receipt.receipt_id == "synthetic-validation-1"


def test_candidate_mismatch_is_typed() -> None:
    receipt = parse_receipt(_receipt())
    other = CandidateIdentity("synthetic-skill", "2" * 40, "a" * 64)
    with pytest.raises(ContractError, match="candidate_mismatch"):
        receipt.require_candidate(other)


def test_schema_validation_reuses_packaged_resources_across_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    load = SchemaRegistry.load
    names: list[str] = []

    def counted_load(registry: SchemaRegistry, name: str) -> dict[str, Any]:
        names.append(name)
        return load(registry, name)

    _packaged_validation_resources.cache_clear()
    monkeypatch.setattr(SchemaRegistry, "load", counted_load)
    try:
        SchemaRegistry().validate("receipt-base.v1", _receipt())
        invalid = {**_receipt(), "candidate": {"package_id": "incomplete"}}
        with pytest.raises(ContractError, match="contract_validation_failed"):
            SchemaRegistry().validate("receipt-base.v1", invalid)
        SchemaRegistry().validate("receipt-base.v1", _receipt())
        assert sorted(names) == sorted(SCHEMA_NAMES)
    finally:
        _packaged_validation_resources.cache_clear()


def test_public_schema_mutation_cannot_change_cached_validation() -> None:
    name = "receipt-base.v1"
    registry = SchemaRegistry()
    registry.validate(name, _receipt())
    public_schema = registry.load(name)
    public_schema["properties"]["receipt_id"]["minLength"] = 10_000

    assert registry.load(name) != public_schema
    registry.validate(name, _receipt())


def test_schema_registry_subclass_keeps_its_own_loader() -> None:
    class StrictRegistry(SchemaRegistry):
        def load(self, name: str) -> dict[str, Any]:
            schema = super().load(name)
            if name == "receipt-base.v1":
                schema["properties"]["receipt_id"]["minLength"] = 10_000
            return schema

    name = "receipt-base.v1"
    SchemaRegistry().validate(name, _receipt())
    with pytest.raises(ContractError, match="contract_validation_failed"):
        StrictRegistry().validate(name, _receipt())
    SchemaRegistry().validate(name, _receipt())


def test_unknown_schema_validation_is_typed() -> None:
    with pytest.raises(ContractError, match="unknown_schema"):
        SchemaRegistry().validate("unknown.v1", {})


def test_structurally_compatible_unknown_receipt_family_fails_closed() -> None:
    payload = _receipt()
    payload["schema_version"] = "future-receipt/v99"

    with pytest.raises(ContractError) as error:
        parse_receipt(payload)

    assert error.value.code == "unsupported_receipt_family"


@pytest.mark.parametrize(
    "schema_version",
    ["receipt-base/v01", "receipt-base/v2", " receipt-base/v1", "receipt-base/v1 "],
)
def test_unregistered_receipt_version_strings_fail_closed(schema_version: str) -> None:
    payload = _receipt()
    payload["schema_version"] = schema_version

    with pytest.raises(ContractError) as error:
        parse_receipt(payload)

    assert error.value.code == "unsupported_receipt_family"


@pytest.mark.parametrize("schema_version", [None, [], 1])
def test_malformed_receipt_versions_are_typed(schema_version: object) -> None:
    payload = _receipt()
    payload["schema_version"] = schema_version

    with pytest.raises(ContractError) as error:
        parse_receipt(payload)

    assert error.value.code == "invalid_receipt_schema_version"


def test_missing_receipt_version_is_typed() -> None:
    payload = _receipt()
    payload.pop("schema_version")

    with pytest.raises(ContractError) as error:
        parse_receipt(payload)

    assert error.value.code == "invalid_receipt_schema_version"


def test_schema_registry_does_not_adapt_unknown_receipt_family() -> None:
    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("future-receipt.v99", _receipt())

    assert error.value.code == "unknown_schema"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_schema_registry_rejects_non_finite_numbers(value: float) -> None:
    payload = _receipt()
    payload["lane"] = value

    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("receipt-base.v1", payload)

    assert error.value.code == "invalid_json_value"


def test_schema_registry_rejects_memoryview_binary_input() -> None:
    payload = _receipt()
    payload["lane"] = memoryview(b"validation")

    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("receipt-base.v1", payload)

    assert error.value.code == "invalid_json_value"


def test_schema_registry_rejects_cyclic_mapping() -> None:
    payload = _receipt()
    payload["cycle"] = payload

    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("receipt-base.v1", payload)

    assert error.value.code == "invalid_json_value"


def test_schema_registry_rejects_cyclic_sequence() -> None:
    cycle: list[object] = []
    cycle.append(cycle)
    payload = _receipt()
    payload["evidence"] = cycle

    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("receipt-base.v1", payload)

    assert error.value.code == "invalid_json_value"


def test_schema_registry_rejects_excessive_json_nesting() -> None:
    nested: object = "evidence.json"
    for _ in range(102):
        nested = [nested]
    payload = _receipt()
    payload["evidence"] = nested

    with pytest.raises(ContractError) as error:
        SchemaRegistry().validate("receipt-base.v1", payload)

    assert error.value.code == "invalid_json_value"


def test_public_core_parser_keeps_explicit_receipt_base_support() -> None:
    from skills_sdk.core import parse_receipt as public_parse_receipt

    receipt = public_parse_receipt(_receipt())

    assert receipt.status == "pass"
    assert receipt.artifact_status is None


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
        "/" + "tmp/receipt.json",
        "../receipt.json",
        "C:/receipt.json",
        "a\\b.json",
        "receipt.json\n",
        "receipt.json\r",
        "receipt\tname.json",
        "receipt\x07name.json",
        "receipt\x1b[31mname.json",
        "receipt\x9b31mname.json",
        "receipt\u202ename.json",
        "receipt\u2066name.json",
        "   ",
    ],
)
def test_non_portable_paths_are_rejected(value: str) -> None:
    with pytest.raises(ContractError, match="invalid_portable_path"):
        require_portable_relative_path(value)


def test_printable_unicode_paths_remain_portable() -> None:
    value = "références/指南-🙂.md"

    assert require_portable_relative_path(value).as_posix() == value


@pytest.mark.parametrize(
    "value",
    [
        "NUL",
        "assets/COM1.log",
        "references/guide.md.",
        "references/guide.md ",
        "assets/a?.txt",
        "assets/a:b",
    ],
)
def test_restore_paths_reject_host_rewritten_components(value: str) -> None:
    with pytest.raises(ContractError, match="invalid_portable_restore_path"):
        require_portable_restore_path(value)


@pytest.mark.parametrize(
    "paths",
    [
        ("SKILL.md", "skill.md"),
        ("café.txt", "cafe\u0301.txt"),
        ("Straße", "STRASSE"),
        ("assets/a.txt", "Assets/b.txt"),
        ("assets", "assets/file.txt"),
    ],
)
def test_restore_paths_reject_file_and_parent_aliases(paths: tuple[str, ...]) -> None:
    with pytest.raises(ContractError, match="portable_restore_path_collision"):
        require_distinct_portable_restore_paths(paths, include_parents=True)


def test_restore_paths_preserve_distinct_unicode_and_shared_parents() -> None:
    paths = ("references/résumé.md", "references/指南-🙂.md")

    require_distinct_portable_restore_paths(paths, include_parents=True)
    assert tuple(require_portable_restore_path(value).as_posix() for value in paths) == paths


def test_receipt_schema_rejects_candidate_shape_drift() -> None:
    payload: dict[str, Any] = copy.deepcopy(_receipt())
    payload["candidate"]["runtime_path"] = "/" + "tmp/synthetic"
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
def test_generic_receipt_schemas_reject_non_portable_paths(schema_name: str, path: tuple[str, ...], value: str) -> None:
    schema = SchemaRegistry().load(schema_name)
    if schema_name == "receipt-base.v1":
        payload = _receipt()
    else:
        payload = {"code": "unsafe_path", "message": "blocked", "evidence_refs": ["valid/path"]}
    target: Any = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = [value]
    if schema_name == "receipt-base.v1":
        with pytest.raises(ContractError, match="contract_validation_failed"):
            SchemaRegistry().validate(schema_name, payload)
    else:
        assert list(Draft202012Validator(schema).iter_errors(payload))
