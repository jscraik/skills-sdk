from __future__ import annotations

import json
import time
import tracemalloc
from itertools import product
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.intake import intake_skill_package
from skills_sdk.models.intake import SkillPackageIntakeContext, SkillPackageIntakeReceipt
from skills_sdk.models.package import IntakeChecks, IntakeDecisionStatus, PackageOwner, PackageSourceKind
from skills_sdk.validation import SkillValidationPolicy

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "synthetic-skill"


def _owner() -> PackageOwner:
    return PackageOwner.model_validate(
        {
            "owner": "sdk-tests",
            "maintainer": "sdk-tests",
            "ownership_state": "canonical",
            "rights": {
                "basis": "authored",
                "license": "Apache-2.0",
                "evidence_ref": "tests/fixtures/synthetic-skill/SKILL.md",
            },
        }
    )


def _context(*, checks: IntakeChecks | None = None) -> SkillPackageIntakeContext:
    return SkillPackageIntakeContext(
        source_repository="jscraik/skills-sdk",
        source_revision="1" * 40,
        source_path="tests/fixtures/synthetic-skill",
        source_kind=PackageSourceKind.GIT,
        owner=_owner(),
        checks=checks or IntakeChecks(identity=True, provenance=True, rights=True, owner_unchanged=True),
    )


def test_intake_normalizes_validated_skill_without_mutation() -> None:
    before = {path.relative_to(FIXTURE_ROOT): path.read_bytes() for path in FIXTURE_ROOT.rglob("*") if path.is_file()}
    receipt = intake_skill_package(FIXTURE_ROOT, _context())
    after = {path.relative_to(FIXTURE_ROOT): path.read_bytes() for path in FIXTURE_ROOT.rglob("*") if path.is_file()}

    assert receipt.status == "normalized"
    assert receipt.decision is not None
    assert receipt.decision.decision is IntakeDecisionStatus.ADMIT
    assert receipt.normalized_package is not None
    assert receipt.candidate is not None
    assert receipt.normalized_package.source.provenance.content_sha256 == receipt.candidate.content_sha256
    assert receipt.mutation_performed is False
    assert receipt.network_used is False
    assert receipt.execution_performed is False
    assert after == before
    SchemaRegistry().validate("skill-package-intake.v1", receipt.model_dump(mode="json"))


def test_normalization_preserves_non_admit_owner_decision() -> None:
    checks = IntakeChecks(identity=True, provenance=True, rights=True, owner_unchanged=False)
    receipt = intake_skill_package(FIXTURE_ROOT, _context(checks=checks))

    assert receipt.status == "normalized"
    assert receipt.decision is not None
    assert receipt.decision.decision is IntakeDecisionStatus.NEEDS_OWNER_DECISION
    assert receipt.decision.blocker_codes == ("owner_decision_required",)
    assert receipt.normalized_package is not None


def test_hard_check_failure_is_not_masked_by_owner_decision() -> None:
    checks = IntakeChecks(identity=True, provenance=False, rights=True, owner_unchanged=False)
    receipt = intake_skill_package(FIXTURE_ROOT, _context(checks=checks))

    assert receipt.decision is not None
    assert receipt.decision.decision is IntakeDecisionStatus.BLOCK
    assert receipt.decision.blocker_codes == ("provenance_unconfirmed", "owner_decision_required")


@pytest.mark.parametrize(
    ("identity", "provenance", "rights", "owner_unchanged"),
    tuple(product((False, True), repeat=4)),
)
def test_intake_decision_truth_table(identity: bool, provenance: bool, rights: bool, owner_unchanged: bool) -> None:
    checks = IntakeChecks(
        identity=identity,
        provenance=provenance,
        rights=rights,
        owner_unchanged=owner_unchanged,
    )
    receipt = intake_skill_package(FIXTURE_ROOT, _context(checks=checks))
    assert receipt.decision is not None
    expected = (
        IntakeDecisionStatus.BLOCK
        if not (identity and provenance and rights)
        else IntakeDecisionStatus.NEEDS_OWNER_DECISION
        if not owner_unchanged
        else IntakeDecisionStatus.ADMIT
    )
    assert receipt.decision.decision is expected


def test_invalid_source_returns_typed_blocker(tmp_path: Path) -> None:
    receipt = intake_skill_package(tmp_path / "missing", _context())

    assert receipt.status == "blocked"
    assert receipt.blocker is not None
    assert receipt.blocker.code == "invalid_package_root"
    assert receipt.normalized_package is None
    SchemaRegistry().validate("skill-package-intake.v1", receipt.model_dump(mode="json"))


def test_context_rejects_archive_until_archive_service_is_composed() -> None:
    SchemaRegistry().validate("skill-package-intake-context.v1", _context().model_dump(mode="json"))
    payload = _context().model_dump(mode="json")
    payload["source_kind"] = "archive"
    with pytest.raises(ValidationError):
        SkillPackageIntakeContext.model_validate(payload)


@pytest.mark.parametrize("field", ["candidate", "source", "decision", "normalized_package"])
def test_receipt_and_registry_reject_forged_normalized_binding(field: str) -> None:
    receipt = intake_skill_package(FIXTURE_ROOT, _context())
    payload = receipt.model_dump(mode="json")
    if field == "candidate":
        payload[field]["content_sha256"] = "f" * 64
    elif field == "source":
        payload[field]["provenance"]["content_sha256"] = "f" * 64
    elif field == "decision":
        payload[field]["candidate"]["content_sha256"] = "f" * 64
    else:
        payload[field]["source"]["provenance"]["content_sha256"] = "f" * 64
    with pytest.raises(ValidationError):
        SkillPackageIntakeReceipt.model_validate(payload)
    with pytest.raises(ContractError, match="rejected the payload"):
        SchemaRegistry().validate("skill-package-intake.v1", payload)


def test_receipt_rejects_forged_normalized_identity() -> None:
    receipt = intake_skill_package(FIXTURE_ROOT, _context())
    payload = receipt.model_dump(mode="json")
    payload["normalized_package"]["identity"]["version"] = "forged"
    with pytest.raises(ValidationError, match="identity must match validation"):
        SkillPackageIntakeReceipt.model_validate(payload)
    with pytest.raises(ContractError, match="rejected the payload"):
        SchemaRegistry().validate("skill-package-intake.v1", payload)


def test_blocked_receipt_rejects_forged_decision_candidate(tmp_path: Path) -> None:
    source = tmp_path / "invalid-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("not frontmatter", encoding="utf-8")
    context = _context().model_copy(update={"source_path": "invalid-skill"})
    receipt = intake_skill_package(source, context)
    assert receipt.decision is not None
    payload = receipt.model_dump(mode="json")
    payload["decision"]["candidate"]["content_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="decision must bind"):
        SkillPackageIntakeReceipt.model_validate(payload)
    with pytest.raises(ContractError, match="rejected the payload"):
        SchemaRegistry().validate("skill-package-intake.v1", payload)


@pytest.mark.parametrize(
    ("decision", "blocker_codes"),
    [
        ("needs_owner_decision", ["owner_decision_required"]),
        ("block", ["rights_unconfirmed"]),
    ],
)
def test_receipt_rejects_forged_decision_projection(decision: str, blocker_codes: list[str]) -> None:
    checks = IntakeChecks(identity=True, provenance=False, rights=True, owner_unchanged=True)
    receipt = intake_skill_package(FIXTURE_ROOT, _context(checks=checks))
    payload = receipt.model_dump(mode="json")
    payload["decision"]["decision"] = decision
    payload["decision"]["blocker_codes"] = blocker_codes
    with pytest.raises(ValidationError, match="decision must match"):
        SkillPackageIntakeReceipt.model_validate(payload)
    with pytest.raises(ContractError, match="rejected the payload"):
        SchemaRegistry().validate("skill-package-intake.v1", payload)


@pytest.mark.parametrize("field", ["code", "message", "evidence_refs"])
def test_blocked_receipt_rejects_forged_primary_blocker(tmp_path: Path, field: str) -> None:
    source = tmp_path / "invalid-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("not frontmatter", encoding="utf-8")
    context = _context().model_copy(update={"source_path": "invalid-skill"})
    receipt = intake_skill_package(source, context)
    payload = receipt.model_dump(mode="json")
    payload["blocker"][field] = ["forged"] if field == "evidence_refs" else "forged"
    with pytest.raises(ValidationError, match="blocker must match"):
        SkillPackageIntakeReceipt.model_validate(payload)
    with pytest.raises(ContractError, match="rejected the payload"):
        SchemaRegistry().validate("skill-package-intake.v1", payload)


def test_receipt_schema_is_draft_2020_12() -> None:
    schema = SchemaRegistry().load("skill-package-intake.v1")
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert json.dumps(schema, sort_keys=True)


@pytest.mark.parametrize("kind", ["git", "local", "external"])
def test_allowed_source_kinds_are_metadata_not_transports(kind: str) -> None:
    payload = _context().model_dump(mode="json")
    payload["source_kind"] = kind
    context = SkillPackageIntakeContext.model_validate(payload)
    SchemaRegistry().validate("skill-package-intake-context.v1", payload)
    receipt = intake_skill_package(FIXTURE_ROOT, context)
    assert receipt.status == "normalized"
    assert receipt.source.source_kind.value == kind
    assert receipt.network_used is False
    SchemaRegistry().validate("skill-package-intake.v1", receipt.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_kind", "archive"),
        ("source_revision", "invalid"),
        ("source_path", "../escape"),
        ("source_repository", ""),
        ("owner", {}),
    ],
)
def test_invalid_context_model_and_registry(field: str, value: object) -> None:
    payload = _context().model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        SkillPackageIntakeContext.model_validate(payload)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("skill-package-intake-context.v1", payload)


def test_direct_schema_shape_is_not_candidate_binding_proof() -> None:
    registry = SchemaRegistry()
    validator = Draft202012Validator(registry.load("skill-package-intake.v1"))
    payload = intake_skill_package(FIXTURE_ROOT, _context()).model_dump(mode="json")
    validator.validate(payload)
    payload["candidate"]["content_sha256"] = "f" * 64
    validator.validate(payload)  # Cross-object equality requires the registered model.
    with pytest.raises(ContractError):
        registry.validate("skill-package-intake.v1", payload)
    payload["status"] = "unknown"
    assert not validator.is_valid(payload)


def test_policy_passthrough_and_read_only_retry() -> None:
    before = {p.relative_to(FIXTURE_ROOT): p.read_bytes() for p in FIXTURE_ROOT.rglob("*") if p.is_file()}
    blocked = intake_skill_package(FIXTURE_ROOT, _context(), policy=SkillValidationPolicy(max_entrypoint_lines=1))
    assert blocked.status == "blocked"
    assert blocked.blocker.code == "entrypoint_line_budget_exceeded"
    assert blocked.normalized_package is None
    success = intake_skill_package(FIXTURE_ROOT, _context())
    repeated = intake_skill_package(FIXTURE_ROOT, _context())
    assert success.status == "normalized"
    assert success == repeated
    after = {p.relative_to(FIXTURE_ROOT): p.read_bytes() for p in FIXTURE_ROOT.rglob("*") if p.is_file()}
    assert before == after


def test_invalid_source_can_be_corrected_and_retried(tmp_path: Path) -> None:
    tmp_path = tmp_path / "recovered"
    tmp_path.mkdir()
    entrypoint = tmp_path / "SKILL.md"
    entrypoint.write_text("invalid frontmatter", encoding="utf-8")
    blocked = intake_skill_package(tmp_path, _context())
    assert blocked.status == "blocked"
    assert entrypoint.read_text() == "invalid frontmatter"
    entrypoint.write_text("---\nname: recovered\ndescription: Recovery fixture.\n---\n", encoding="utf-8")
    before = entrypoint.read_bytes()
    success = intake_skill_package(tmp_path, _context())
    assert success.status == "normalized"
    assert intake_skill_package(tmp_path, _context()) == success
    assert entrypoint.read_bytes() == before


@pytest.mark.parametrize("construction", ["copy", "construct"])
@pytest.mark.parametrize("field", ["source_kind", "source_revision", "source_path"])
def test_forged_context_is_rejected_before_source_inspection(
    monkeypatch: pytest.MonkeyPatch,
    construction: str,
    field: str,
) -> None:
    from skills_sdk.intake import normalization

    value = {"source_kind": "archive", "source_revision": "invalid", "source_path": "../escape"}[field]
    context = _context()
    forged = (
        context.model_copy(update={field: value})
        if construction == "copy"
        else SkillPackageIntakeContext.model_construct(**{**context.__dict__, field: value})
    )

    def unexpected_inspection(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid context reached package inspection")

    monkeypatch.setattr(normalization, "validate_skill_package", unexpected_inspection)
    with pytest.raises(ValidationError):
        intake_skill_package(FIXTURE_ROOT, forged)


@pytest.mark.parametrize("case", ["entries", "single_file", "total_bytes", "entrypoint"])
def test_small_resource_characterization(tmp_path: Path, case: str) -> None:
    """Observe proposed measurement points, without enforcing future limits."""
    root = tmp_path / "synthetic-skill"
    root.mkdir()
    entrypoint = root / "SKILL.md"
    entrypoint.write_bytes((FIXTURE_ROOT / "SKILL.md").read_bytes())
    if case == "entrypoint":
        entrypoint.write_bytes(entrypoint.read_bytes().ljust(256 * 1024 + 1, b" "))
    else:
        count, size = {"entries": (250, 0), "single_file": (1, 1024 * 1024 + 1), "total_bytes": (5, 1024 * 1024)}[case]
        for index in range(count):
            (root / f"asset-{index}.txt").write_bytes(b"x" * size)
    before = {p.name: p.stat().st_size for p in root.iterdir()}
    results = []
    observations = []
    for _ in range(2):
        owns_tracing = not tracemalloc.is_tracing()
        if owns_tracing:
            tracemalloc.start()
        started = time.perf_counter()
        try:
            result = intake_skill_package(root, _context())
            elapsed = time.perf_counter() - started
            peak = tracemalloc.get_traced_memory()[1] if owns_tracing else None
        finally:
            if owns_tracing:
                tracemalloc.stop()
        results.append(result)
        observations.append({"seconds": elapsed, "python_peak_bytes": peak})
    assert results[0] == results[1]
    assert results[0].status == "normalized"
    assert before == {p.name: p.stat().st_size for p in root.iterdir()}
    print(
        json.dumps(
            {"case": case, "entries": len(before), "bytes": sum(before.values()), "observations": observations},
            sort_keys=True,
        )
    )


def test_characterization_preserves_existing_tracing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    owns_tracing = not tracemalloc.is_tracing()
    if owns_tracing:
        tracemalloc.start()
    try:
        retained = bytearray(1024)
        test_small_resource_characterization(tmp_path, "single_file")
        assert tracemalloc.is_tracing()
        assert tracemalloc.get_object_traceback(retained) is not None
        report = json.loads(capsys.readouterr().out)
        assert all(item["python_peak_bytes"] is None for item in report["observations"])
    finally:
        if owns_tracing:
            tracemalloc.stop()
