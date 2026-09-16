"""Read-only comparison of a validated source package and a runtime copy."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from skills_sdk.models.validation import SkillPackageValidation
from skills_sdk.validation.skill_package import validate_skill_package


class RuntimeCopyComparison(BaseModel):
    """Local comparison, not installation, activation, or admission evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["runtime-copy-comparison/v1"] = "runtime-copy-comparison/v1"
    status: Literal["pass", "drift", "blocked"]
    source: SkillPackageValidation
    runtime: SkillPackageValidation
    different_paths: tuple[str, ...]


def compare_runtime_copy(source_root: Path, runtime_root: Path, source_revision: str) -> RuntimeCopyComparison:
    """Compare captured file bytes without executing source or changing either tree.

    Existing validation remains mandatory for both trees. This is a bounded
    filesystem observation, not proof of stable synchronization or activation.
    """
    source = validate_skill_package(source_root, source_revision=source_revision)
    runtime = validate_skill_package(runtime_root, source_revision=source_revision)
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
