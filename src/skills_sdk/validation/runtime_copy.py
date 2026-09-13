"""Read-only comparison of a validated source package and a runtime copy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from skills_sdk.models.validation import SkillPackageValidation
from skills_sdk.validation.skill_package import validate_skill_package


@dataclass(frozen=True, slots=True)
class RuntimeCopyComparison:
    """Local comparison, not installation, activation, or admission evidence."""

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
        return RuntimeCopyComparison("blocked", source, runtime, ())
    expected = {item.path: (item.sha256, item.size_bytes) for item in source.files}
    observed = {item.path: (item.sha256, item.size_bytes) for item in runtime.files}
    differences = tuple(
        sorted(path for path in expected.keys() | observed.keys() if expected.get(path) != observed.get(path))
    )
    return RuntimeCopyComparison("drift" if differences else "pass", source, runtime, differences)
