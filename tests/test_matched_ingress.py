"""Reject caller-controlled coercion before matched assessment or execution."""

from __future__ import annotations

import json
from collections import UserList

import pytest
from pydantic import ValidationError, model_serializer
from test_matched_comparison import _judgment, _plan

from skills_sdk.core.errors import ContractError
from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.evaluation.matched_comparison import assess_matched_pair
from skills_sdk.models.matched_comparison import (
    MatchedComparisonPlan,
    MatchedDimensionJudgment,
    MatchedLaneSpec,
    MatchedPairAssessment,
    MatchedVariantJudgment,
)
from skills_sdk.models.provider import ProviderIdentityV2


@pytest.mark.parametrize("container", ["list", "set", "user_list", "iterator"])
def test_evidence_bytes_are_rejected_before_container_coercion(container: str) -> None:
    plan = _plan()
    judgment = _judgment(plan, "candidate", 3.0)
    dimension = judgment.dimensions[0]
    values = {
        "list": [b"evidence/judgment.json"],
        "set": {b"evidence/judgment.json"},
        "user_list": UserList([b"evidence/judgment.json"]),
        "iterator": iter([b"evidence/judgment.json"]),
    }
    raw = dimension.model_dump(mode="python")
    raw["evidence_refs"] = values[container]
    with pytest.raises(ValidationError):
        MatchedDimensionJudgment.model_validate(raw)
    assert MatchedDimensionJudgment.model_validate(dimension) == dimension
    assert MatchedDimensionJudgment.model_validate_json(dimension.model_dump_json()) == dimension


@pytest.mark.parametrize("mixed_mapping", [False, True])
def test_nested_provider_serializer_is_never_called(mixed_mapping: bool) -> None:
    lane = _plan().lanes[0]
    calls: list[str] = []

    class HiddenProvider(ProviderIdentityV2):
        @model_serializer(mode="plain")
        def disguise(self) -> dict[str, object]:
            calls.append("serializer")
            return lane.judge.model_dump(mode="python")

    hidden = HiddenProvider.model_construct(**dict(lane.judge.__dict__, provider_kind="bogus"))
    incoming = dict(lane.__dict__, judge=hidden) if mixed_mapping else lane.model_copy(update={"judge": hidden})
    with pytest.raises(ValidationError):
        MatchedLaneSpec.model_validate(incoming)
    assert not calls
    assert MatchedLaneSpec.model_validate(lane) == lane


@pytest.mark.parametrize("mutation", ["none", "unknown", "nested_bytes"])
def test_direct_judgment_subclass_is_rejected_and_assessment_recovers(mutation: str) -> None:
    plan = _plan()
    left, right = _judgment(plan, "baseline", 2.5), _judgment(plan, "candidate", 3.0)

    class OtherJudgment(MatchedVariantJudgment):
        pass

    hidden = OtherJudgment.model_construct(**right.__dict__)
    if mutation == "unknown":
        hidden = hidden.model_copy(update={"unexpected": "hidden"})
    if mutation == "nested_bytes":
        provider = right.evidence.provider.model_copy(update={"model_id": b"local-fixture"})
        hidden = hidden.model_copy(update={"evidence": right.evidence.model_copy(update={"provider": provider})})
    with pytest.raises(ValidationError):
        MatchedVariantJudgment.model_validate(hidden)
    assert assess_matched_pair(plan, "local", left, hidden).status == "blocked"
    assert assess_matched_pair(plan, "local", left, right).decision == "candidate"


def test_dictionary_subclass_cannot_hide_invalid_members() -> None:
    right = _judgment(_plan(), "candidate", 3.0)

    class HiddenMembers(dict[str, object]):
        def values(self) -> tuple[object, ...]:
            return ()

    hidden = HiddenMembers(right.evidence.__dict__)
    hidden["provider"] = right.evidence.provider.model_copy(update={"model_id": b"local-fixture"})
    with pytest.raises(ValidationError):
        MatchedVariantJudgment.model_validate(dict(right.__dict__, evidence=hidden))
    assert MatchedVariantJudgment.model_validate(right) == right


@pytest.mark.parametrize("storage", ["members", "extras"])
def test_forged_model_storage_is_rejected_without_invoking_caller(storage: str) -> None:
    lane = _plan().lanes[0]
    hidden = lane.judge.model_copy()
    calls: list[str] = []

    class HiddenMembers(dict[str, object]):
        def __iter__(self) -> object:
            calls.append("iteration")
            return iter(())

    class HiddenExtras:
        def __bool__(self) -> bool:
            calls.append("truthiness")
            return False

    if storage == "members":
        object.__setattr__(hidden, "__dict__", HiddenMembers(hidden.__dict__))
    else:
        object.__setattr__(hidden, "__pydantic_extra__", HiddenExtras())
    with pytest.raises(ValidationError):
        MatchedLaneSpec.model_validate(dict(lane.__dict__, judge=hidden))
    assert not calls
    assert MatchedLaneSpec.model_validate(lane) == lane


@pytest.mark.parametrize("attack", ["class_property", "metaclass_equality"])
def test_unsupported_objects_are_rejected_without_type_hooks(attack: str) -> None:
    lane = _plan().lanes[0]
    calls: list[str] = []

    class HiddenClass:
        @property
        def __class__(self) -> type:
            calls.append("class property")
            return dict

    class HiddenMeta(type):
        def __eq__(cls, other: object) -> bool:
            calls.append("metaclass equality")
            return False

    class HiddenEquality(metaclass=HiddenMeta):
        pass

    hidden = HiddenClass() if attack == "class_property" else HiddenEquality()
    with pytest.raises(ValidationError):
        MatchedLaneSpec.model_validate(dict(lane.__dict__, judge=hidden))
    assert not calls
    assert MatchedLaneSpec.model_validate(lane) == lane


@pytest.mark.parametrize("field", ["package_id", "source_revision", "content_sha256"])
@pytest.mark.parametrize("boundary", ["raw", "json", "copied", "constructed"])
def test_padded_nested_identity_is_rejected_and_canonical_input_recovers(field: str, boundary: str) -> None:
    plan = _plan()
    padded = " " + getattr(plan.baseline, field) + " "
    raw = plan.model_dump(mode="json")
    raw["plugin_scope"]["baseline"]["candidate"][field] = padded
    if boundary in ("raw", "json"):
        incoming = raw
    else:
        identity = plan.baseline.model_copy(update={field: padded})
        capture = plan.plugin_scope.baseline.model_copy(update={"candidate": identity})
        scope = plan.plugin_scope.model_copy(update={"baseline": capture})
        if boundary == "copied":
            incoming = plan.model_copy(update={"plugin_scope": scope})
        else:
            incoming = MatchedComparisonPlan.model_construct(**dict(plan.__dict__, plugin_scope=scope))
    with pytest.raises(ValidationError):
        if boundary == "json":
            MatchedComparisonPlan.model_validate_json(json.dumps(raw))
        else:
            MatchedComparisonPlan.model_validate(incoming)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("matched-comparison-plan.v1", raw)
    left, right = _judgment(plan, "baseline", 2.5), _judgment(plan, "candidate", 3.0)
    rejected = assess_matched_pair(incoming, "local", left, right)
    assert rejected.status == "blocked" and rejected.plan is None
    assert assess_matched_pair(plan, "local", left, right).decision == "candidate"
    assert MatchedComparisonPlan.model_validate(plan) == plan
    assert MatchedComparisonPlan.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.parametrize("boundary", ["raw", "json", "copied", "constructed"])
def test_padded_inherited_blocker_code_cannot_be_laundered(boundary: str) -> None:
    blocked = assess_matched_pair(None, "local", None, None)
    raw = blocked.model_dump(mode="json")
    raw["blocker"]["code"] = " " + blocked.blocker.code + " "
    incoming = raw
    if boundary in ("copied", "constructed"):
        blocker = blocked.blocker.model_copy(update={"code": raw["blocker"]["code"]})
        incoming = blocked.model_copy(update={"blocker": blocker})
        if boundary == "constructed":
            incoming = MatchedPairAssessment.model_construct(**dict(blocked.__dict__, blocker=blocker))
    with pytest.raises(ValidationError):
        if boundary == "json":
            MatchedPairAssessment.model_validate_json(json.dumps(raw))
        else:
            MatchedPairAssessment.model_validate(incoming)
    with pytest.raises(ContractError):
        SchemaRegistry().validate("matched-pair-assessment.v1", raw)
    assert MatchedPairAssessment.model_validate(blocked) == blocked
