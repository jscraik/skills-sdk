"""Read-only comparison of a validated source package and a runtime copy."""

from __future__ import annotations

from pathlib import Path

from skills_sdk.models.maintenance import RuntimeCopyComparison
from skills_sdk.models.validation import SkillPackageFinding, SkillPackageValidation, ValidationSeverity
from skills_sdk.validation.skill_package import validate_skill_package


def _validate_copy(root: Path, source_revision: str) -> SkillPackageValidation:
    """Convert recursive metadata failure into the public validation boundary."""
    try:
        return validate_skill_package(root, source_revision=source_revision)
    except RecursionError:
        return SkillPackageValidation(
            status="blocked",
            findings=(
                SkillPackageFinding(
                    code="recursive_metadata",
                    severity=ValidationSeverity.BLOCKER,
                    message="package metadata exceeds the supported nesting depth",
                ),
            ),
        )


def compare_runtime_copy(source_root: Path, runtime_root: Path, source_revision: str) -> RuntimeCopyComparison:
    """Compare captured file bytes without executing source or changing either tree.

    Existing validation remains mandatory for both trees. This is a bounded
    filesystem observation, not proof of stable synchronization or activation.
    """
    source = _validate_copy(source_root, source_revision)
    runtime = _validate_copy(runtime_root, source_revision)
    if source.status != "pass" or runtime.status != "pass":
        return RuntimeCopyComparison(status="blocked", source=source, runtime=runtime, different_paths=())
    expected = {item.path: (item.sha256, item.size_bytes) for item in source.files}
    observed = {item.path: (item.sha256, item.size_bytes) for item in runtime.files}
    differences = tuple(
        sorted(path for path in expected.keys() | observed.keys() if expected.get(path) != observed.get(path))
    )
    return RuntimeCopyComparison(
        status="drift" if differences else "pass",
        source=source,
        runtime=runtime,
        different_paths=differences,
    )
