from __future__ import annotations

import pytest
from pydantic import ValidationError

from skills_sdk.models.lifecycle import RuntimeTarget
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.runtime_evidence import InstallationResult
from tests.test_runtime_execution_evidence import _installation, _plan


@pytest.mark.parametrize(
    ("field", "forged"),
    (
        (
            "candidate",
            PackageCandidateIdentity.model_construct(
                schema_version="package-candidate/v1",
                package_id="synthetic-skill",
                source_revision="invalid-revision",
                content_sha256="a" * 64,
            ),
        ),
        ("target", RuntimeTarget.model_construct(scope="project", target_id="invalid target")),
    ),
)
def test_runtime_evidence_revalidates_external_nested_models(field: str, forged: object) -> None:
    payload = _installation(_plan()).model_dump(mode="python")
    payload[field] = forged

    with pytest.raises(ValidationError):
        InstallationResult.model_validate(payload)
