from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from skills_sdk.models.package import (
    IntakeChecks,
    IntakeDecision,
    IntakeDecisionStatus,
    NormalizedPackage,
    OwnershipState,
    PackageCandidateIdentity,
    PackageOwner,
    PackageSource,
    PackageSourceKind,
    PluginIdentity,
    SkillIdentity,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "package-lifecycle"


def _candidate() -> PackageCandidateIdentity:
    return PackageCandidateIdentity(
        package_id="synthetic-skill",
        source_revision="1" * 40,
        content_sha256="a" * 64,
    )


def _source() -> PackageSource:
    return PackageSource(
        package_id="synthetic-skill",
        provenance={
            "repository": "jscraik/agent-skills",
            "revision": "1" * 40,
            "path": "tests/fixtures/synthetic-skill/SKILL.md",
            "content_sha256": "a" * 64,
        },
        source_kind=PackageSourceKind.GIT,
    )


def _owner() -> PackageOwner:
    return PackageOwner(
        owner="jscraik",
        maintainer="jscraik",
        ownership_state=OwnershipState.CANONICAL,
        rights={
            "basis": "authored",
            "license": "Apache-2.0",
            "evidence_ref": "tests/fixtures/synthetic-skill/SKILL.md",
        },
    )


def test_accepted_normalized_skill_fixture() -> None:
    payload = json.loads((FIXTURE_ROOT / "accepted.json").read_text(encoding="utf-8"))
    normalized = NormalizedPackage.model_validate(payload)
    assert isinstance(normalized.identity, SkillIdentity)
    assert normalized.source.package_id == normalized.identity.package_id


@pytest.mark.parametrize("filename", ["rejected.json", "boundary.json"])
def test_rejected_and_boundary_fixtures_are_not_admitted(filename: str) -> None:
    payload = json.loads((FIXTURE_ROOT / filename).read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        NormalizedPackage.model_validate(payload)


def test_intake_admission_requires_all_checks_and_no_blockers() -> None:
    decision = IntakeDecision(
        candidate=_candidate(),
        decision=IntakeDecisionStatus.ADMIT,
        checks=IntakeChecks(identity=True, provenance=True, rights=True, owner_unchanged=True),
    )
    assert decision.decision is IntakeDecisionStatus.ADMIT

    with pytest.raises(ValidationError):
        IntakeDecision(
            candidate=_candidate(),
            decision=IntakeDecisionStatus.ADMIT,
            checks=IntakeChecks(identity=True, provenance=False, rights=True, owner_unchanged=True),
        )


def test_blocked_intake_requires_a_blocker_code() -> None:
    blocked = IntakeDecision(
        candidate=_candidate(),
        decision=IntakeDecisionStatus.BLOCK,
        checks=IntakeChecks(identity=True, provenance=False, rights=True, owner_unchanged=True),
        blocker_codes=("provenance_missing",),
    )
    assert blocked.blocker_codes == ("provenance_missing",)

    with pytest.raises(ValidationError):
        IntakeDecision(
            candidate=_candidate(),
            decision=IntakeDecisionStatus.BLOCK,
            checks=IntakeChecks(identity=True, provenance=False, rights=True, owner_unchanged=True),
        )


def test_plugin_identity_is_distinct_from_skill_identity() -> None:
    plugin = PluginIdentity(
        package_id="example.plugin",
        name="example.plugin",
        version="1.0.0",
    )
    assert plugin.package_type == "plugin"
    with pytest.raises(ValidationError):
        SkillIdentity(
            package_id="example.plugin",
            name="example.plugin",
            version="1.0.0",
        )
