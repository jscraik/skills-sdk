"""Portable immutable package construction."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from skills_sdk.models.packaging import PackageReceipt

if TYPE_CHECKING:
    from skills_sdk.validation import SkillValidationPolicy


def build_skill_package(
    package_root: Path,
    *,
    source_revision: str,
    policy: SkillValidationPolicy | None = None,
    clock: Callable[[], datetime] | None = None,
) -> PackageReceipt:
    """Load the manifest builder lazily to keep validation imports acyclic."""

    from skills_sdk.packaging.manifest import build_skill_package as _build_skill_package

    return _build_skill_package(
        package_root,
        source_revision=source_revision,
        policy=policy,
        clock=clock,
    )


__all__ = ["build_skill_package"]
