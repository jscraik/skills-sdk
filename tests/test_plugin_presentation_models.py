"""Hardened presentation model binding and forged-input regressions."""

from __future__ import annotations

import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.plugin_presentation import (
    PluginImageApproval,
    PluginPresentationCheck,
    PluginPresentationCopyApproval,
    PluginPresentationImage,
    PluginPresentationRequest,
)
from skills_sdk.models.validation import SkillPackageFinding, ValidationSeverity

SHA = "1" * 64
OTHER_SHA = "2" * 64
MODE_SHA = "3" * 64
REVISION = "a" * 40


def _candidate(package_id: str = "plugin-example") -> PackageCandidateIdentity:
    return PackageCandidateIdentity(package_id=package_id, source_revision=REVISION, content_sha256=SHA)


def _approval(path: str = "assets/icon.png", *, kind: str = "icon") -> PluginImageApproval:
    values: dict[str, Any] = {
        "candidate": _candidate(),
        "image_path": path,
        "image_sha256": OTHER_SHA,
        "kind": kind,
        "professional": True,
        "rights_confirmed": True,
        "evidence_ref": "review:icon-1",
        "evidence_sha256": SHA,
    }
    if kind == "icon":
        values.update(recognisable=True, small_size=True, light_dark=True, distinctive=True)
    return PluginImageApproval.model_validate(values)


def _copy() -> PluginPresentationCopyApproval:
    return PluginPresentationCopyApproval(
        candidate=_candidate(),
        openai_settings_sha256=SHA,
        accurate=True,
        evidence_ref="review:copy-1",
        evidence_sha256=OTHER_SHA,
    )


def _image(
    path: str = "assets/icon.png",
    roles: tuple[str, ...] = ("composerIcon", "logo"),
    *,
    kind: str = "icon",
) -> PluginPresentationImage:
    return PluginPresentationImage.model_validate(
        {
            "path": path,
            "sha256": OTHER_SHA,
            "size_bytes": 128,
            "format": "png",
            "width": 48.0,
            "height": 48.0,
            "roles": roles,
            "approval": _approval(path, kind=kind),
        }
    )


def _passing() -> PluginPresentationCheck:
    return PluginPresentationCheck(
        status="pass",
        candidate=_candidate(),
        mode_manifest_sha256=MODE_SHA,
        openai_settings_source="inline",
        openai_settings_sha256=SHA,
        images=(_image(),),
        copy_approval=_copy(),
    )


def _blocker() -> SkillPackageFinding:
    return SkillPackageFinding(
        code="presentation_invalid",
        severity=ValidationSeverity.BLOCKER,
        message="presentation input is invalid",
    )


def test_image_approval_kind_controls_review_criteria() -> None:
    assert _approval().kind == "icon"
    assert _approval("assets/screenshot.png", kind="screenshot").recognisable is None
    raw = _approval().model_dump(mode="json")
    for field in ("recognisable", "small_size", "light_dark", "distinctive"):
        missing = {**raw, field: None}
        with pytest.raises(ValidationError):
            PluginImageApproval.model_validate(missing)
    screenshot = _approval("assets/screenshot.png", kind="screenshot").model_dump(mode="json")
    screenshot["recognisable"] = True
    with pytest.raises(ValidationError):
        PluginImageApproval.model_validate(screenshot)


@pytest.mark.parametrize(
    "model,field",
    [
        (_approval(), "professional"),
        (_approval(), "rights_confirmed"),
        (_approval(), "recognisable"),
        (_copy(), "accurate"),
        (_passing(), "mutation_performed"),
        (_passing(), "execution_authorized"),
        (_passing(), "release_ready"),
        (_passing(), "archive_verified"),
        (_passing(), "host_display_observed"),
        (_passing(), "publication_verified"),
    ],
)
def test_boolean_literals_reject_integer_coercion(model: Any, field: str) -> None:
    raw = model.model_dump(mode="json")
    raw[field] = 1 if raw[field] is True else 0
    with pytest.raises(ValidationError):
        type(model).model_validate(raw)


def test_request_binds_unique_approvals_and_copy_to_candidate() -> None:
    request = PluginPresentationRequest(
        candidate=_candidate(),
        mode_manifest_sha256=MODE_SHA,
        image_approvals=(_approval(), _approval("assets/shot.png", kind="screenshot")),
        copy_approval=_copy(),
    )
    assert len(request.image_approvals) == 2
    with pytest.raises(ValidationError):
        PluginPresentationRequest.model_validate(
            {**request.model_dump(mode="json"), "image_approvals": [request.image_approvals[0]] * 2}
        )
    wrong = _approval().model_copy(update={"candidate": _candidate("plugin-other")})
    with pytest.raises(ValidationError):
        PluginPresentationRequest.model_validate({**request.model_dump(mode="json"), "image_approvals": [wrong]})
    wrong_copy = _copy().model_copy(update={"candidate": _candidate("plugin-other")})
    with pytest.raises(ValidationError):
        PluginPresentationRequest.model_validate({**request.model_dump(mode="json"), "copy_approval": wrong_copy})


def test_image_binds_approval_roles_and_dimensions() -> None:
    assert _image().width == 48.0
    screenshot = _image("assets/shot.png", ("screenshot",), kind="screenshot")
    assert screenshot.approval.kind == "screenshot"
    raw = _image().model_dump(mode="json")
    rejected = (
        {**raw, "path": "assets/other.png"},
        {**raw, "sha256": SHA},
        {**raw, "roles": ["logo", "composerIcon"]},
        {**raw, "roles": ["logo", "logo"]},
        {**raw, "width": 47.0, "height": 47.0},
        {**raw, "width": 48.0, "height": 49.0},
        {**raw, "width": float("inf")},
        {**raw, "format": "png", "width": 4097.0, "height": 4097.0},
    )
    for value in rejected:
        with pytest.raises(ValidationError):
            PluginPresentationImage.model_validate(value)
    shared = PluginPresentationImage.model_validate({**raw, "roles": ["logo", "screenshot"]})
    assert shared.approval.kind == "icon"


def test_presentation_check_pass_and_blocked_invariants() -> None:
    assert _passing().status == "pass"
    blocked = PluginPresentationCheck(status="blocked", findings=(_blocker(),))
    assert blocked.candidate is None and not blocked.archive_verified
    raw = _passing().model_dump(mode="json")
    rejected = (
        {**raw, "mode_manifest_sha256": None},
        {**raw, "openai_settings_source": "none"},
        {**raw, "openai_settings_sha256": None},
        {**raw, "copy_approval": None},
        {**raw, "images": []},
        {**raw, "images": [{**raw["images"][0], "roles": ["logo"]}]},
        {**raw, "findings": [_blocker().model_dump(mode="json")]},
        {**raw, "copy_approval": {**raw["copy_approval"], "openai_settings_sha256": OTHER_SHA}},
    )
    for value in rejected:
        with pytest.raises(ValidationError):
            PluginPresentationCheck.model_validate(value)
    with pytest.raises(ValidationError):
        PluginPresentationCheck(status="blocked")
    with pytest.raises(ValidationError):
        PluginPresentationCheck(status="pass")


def test_check_rejects_unsorted_duplicate_or_wrong_candidate_images() -> None:
    first = _image("assets/a.png")
    second = _image("assets/b.png")
    raw = _passing().model_dump(mode="json")
    for images in ((second, first), (first, first)):
        with pytest.raises(ValidationError):
            PluginPresentationCheck.model_validate({**raw, "images": images})
    wrong_approval = first.approval.model_copy(update={"candidate": _candidate("plugin-other")})
    wrong = first.model_copy(update={"approval": wrong_approval})
    with pytest.raises(ValidationError):
        PluginPresentationCheck.model_validate({**raw, "images": [wrong]})


@pytest.mark.parametrize("form", ["raw", "copy", "construct"])
def test_unknown_and_forged_inputs_are_revalidated(form: str) -> None:
    good = _passing()
    if form == "raw":
        value: object = {**good.model_dump(mode="json"), "unknown": True}
    elif form == "copy":
        value = good.model_copy(update={"release_ready": True})
    else:
        value = PluginPresentationCheck.model_construct(**{**good.__dict__, "release_ready": True})
    with pytest.raises((ValidationError, ValueError)):
        PluginPresentationCheck.model_validate(value)


def test_subclasses_cycles_and_noncanonical_values_are_rejected() -> None:
    class ApprovalSubclass(PluginImageApproval):
        pass

    raw = _passing().model_dump(mode="json")
    subclass = ApprovalSubclass.model_validate(_approval().model_dump(mode="json"))
    raw["images"][0]["approval"] = subclass
    with pytest.raises(ValidationError):
        PluginPresentationCheck.model_validate(raw)
    cycle: dict[str, object] = {}
    cycle["cycle"] = cycle
    with pytest.raises(ValidationError):
        PluginPresentationCheck.model_validate(cycle)


def test_portable_paths_and_public_safe_evidence_refs_are_required() -> None:
    raw = _approval().model_dump(mode="json")
    for path in ("../icon.png", "/icon.png", "assets\\icon.png"):
        with pytest.raises(ValidationError):
            PluginImageApproval.model_validate({**raw, "image_path": path})
    for reference in (
        " private",
        "private review",
        "x" * 129,
        "file:///example/private",
        "https://private.invalid/review",
    ):
        with pytest.raises(ValidationError):
            PluginImageApproval.model_validate({**raw, "evidence_ref": reference})


def test_registered_semantics_do_not_claim_source_derivation() -> None:
    registry = SchemaRegistry()
    request = PluginPresentationRequest(
        candidate=_candidate(),
        mode_manifest_sha256=MODE_SHA,
        image_approvals=(_approval(),),
        copy_approval=_copy(),
    )
    for name, model in (
        ("plugin-image-approval.v1", _approval()),
        ("plugin-presentation-copy-approval.v1", _copy()),
        ("plugin-presentation-request.v1", request),
        ("plugin-presentation-check.v1", _passing()),
    ):
        payload = model.model_dump(mode="json")
        Draft202012Validator(registry.load(name)).validate(payload)
        registry.validate(name, payload)
    forged = _passing().model_dump(mode="json")
    forged["images"][0]["approval"]["candidate"]["content_sha256"] = "f" * 64
    Draft202012Validator(registry.load("plugin-presentation-check.v1")).validate(forged)
    with pytest.raises(ContractError):
        registry.validate("plugin-presentation-check.v1", forged)
    forged["images"][0]["approval"]["candidate"]["content_sha256"] = SHA
    registry.validate("plugin-presentation-check.v1", forged)


def test_shared_svg_screenshot_rejects_model_and_registered_evidence() -> None:
    raw = _passing().model_dump(mode="json")
    shared = _image("assets/icon.svg").model_dump(mode="json")
    shared.update(format="svg", roles=["composerIcon", "logo", "screenshot"])
    with pytest.raises(ValidationError):
        PluginPresentationImage.model_validate(shared)
    raw["images"] = [shared]
    registry = SchemaRegistry()
    with pytest.raises(ContractError):
        registry.validate("plugin-presentation-check.v1", raw)
    raw["images"] = [_image(roles=("composerIcon", "logo", "screenshot")).model_dump(mode="json")]
    registry.validate("plugin-presentation-check.v1", raw)


@pytest.mark.parametrize("field", ["package_id", "source_revision", "content_sha256"])
@pytest.mark.parametrize("form", ["raw", "json", "copy", "construct"])
def test_padded_candidate_identifiers_reject_before_normalisation(field: str, form: str) -> None:
    good = _copy()
    raw = good.model_dump(mode="json")
    raw["candidate"][field] = " " + raw["candidate"][field] + " "
    if form == "copy":
        value = good.model_copy(update={"candidate": good.candidate.model_copy(update=raw["candidate"])})
    elif form == "construct":
        value = good.model_copy(update={"candidate": PackageCandidateIdentity.model_construct(**raw["candidate"])})
    else:
        value = raw
    with pytest.raises(ValidationError):
        if form == "json":
            PluginPresentationCopyApproval.model_validate_json(json.dumps(raw))
        else:
            PluginPresentationCopyApproval.model_validate(value)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-presentation-copy-approval.v1", raw)
    assert PluginPresentationCopyApproval.model_validate(good) == good


@pytest.mark.parametrize("form", ["raw", "copy", "construct"])
def test_padded_finding_code_rejects_and_canonical_input_recovers(form: str) -> None:
    good = PluginPresentationCheck(status="blocked", findings=(_blocker(),))
    raw = good.model_dump(mode="json")
    finding = {**raw["findings"][0], "code": " presentation_invalid "}
    if form == "copy":
        entry = good.findings[0].model_copy(update=finding)
    elif form == "construct":
        entry = SkillPackageFinding.model_construct(**finding)
    else:
        entry = finding
    with pytest.raises(ValidationError):
        PluginPresentationCheck.model_validate({**raw, "findings": [entry]})
    with pytest.raises(ContractError):
        SchemaRegistry().validate("plugin-presentation-check.v1", {**raw, "findings": [finding]})
    assert PluginPresentationCheck.model_validate(good) == good
