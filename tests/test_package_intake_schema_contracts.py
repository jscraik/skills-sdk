"""Direct schema consumers reject expressible intake contradictions."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from skills_sdk.core.schema_registry import SchemaRegistry
from skills_sdk.intake import intake_skill_package
from tests.test_package_intake import FIXTURE_ROOT, _context


@pytest.mark.parametrize("contradiction", ["admit_check", "admit_blocker", "block_empty", "package_type"])
def test_direct_intake_schema_rejects_contradictions(contradiction: str) -> None:
    payload = intake_skill_package(FIXTURE_ROOT, _context()).model_dump(mode="json")
    validator = Draft202012Validator(SchemaRegistry().load("skill-package-intake.v1"))
    validator.validate(payload)
    invalid = deepcopy(payload)
    if contradiction == "admit_check":
        invalid["decision"]["checks"]["rights"] = False
    elif contradiction == "admit_blocker":
        invalid["decision"]["blocker_codes"] = ["rights_unconfirmed"]
    elif contradiction == "block_empty":
        invalid["decision"]["decision"] = "block"
    else:
        invalid["normalized_package"]["package_type"] = "plugin"
    assert not validator.is_valid(invalid)
