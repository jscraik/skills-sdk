"""Read-only PR-sweep validation results, independent of a Git host."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from skills_sdk.core.errors import ContractError
from skills_sdk.core.paths import require_portable_relative_path
from skills_sdk.models.inventory import NonEmptyText


class PrSweepFinding(BaseModel):
    """One actionable validation failure."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    code: NonEmptyText
    message: NonEmptyText


class PrSweepDirtyState(BaseModel):
    """Repository-relative paths reported by Git."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    staged_paths: tuple[str, ...] = ()
    unstaged_paths: tuple[str, ...] = ()
    untracked_paths: tuple[str, ...] = ()
    dirty_paths: tuple[str, ...] = ()

    @model_validator(mode="after")
    def paths_match_categories(self) -> Self:
        for path in (*self.staged_paths, *self.unstaged_paths, *self.untracked_paths, *self.dirty_paths):
            try:
                require_portable_relative_path(path)
            except ContractError as error:
                raise ValueError("dirty state contains a non-portable path") from error
        categorized = set(self.staged_paths) | set(self.unstaged_paths) | set(self.untracked_paths)
        if set(self.dirty_paths) != categorized:
            raise ValueError("dirty paths must equal the union of staged, unstaged, and untracked paths")
        return self


class PrSweepValidationResult(BaseModel):
    """Versioned result for one non-mutating PR-sweep guardrail."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal["pr-sweep-validation/v1"] = "pr-sweep-validation/v1"
    kind: Literal["recurring_findings", "dirty_closeout"]
    status: Literal["pass", "fail", "blocked"]
    findings: tuple[PrSweepFinding, ...] = ()
    dirty_state: PrSweepDirtyState | None = None
    ledgered_paths: tuple[str, ...] = ()
    unledgered_paths: tuple[str, ...] = ()

    @model_validator(mode="after")
    def findings_match_status(self) -> Self:
        if (self.status == "pass") == bool(self.findings):
            raise ValueError("passing validation requires no findings; failure requires findings")
        if self.kind == "recurring_findings" and self.dirty_state is not None:
            raise ValueError("recurring-findings validation cannot report Git dirty state")
        if self.kind == "recurring_findings" and (self.ledgered_paths or self.unledgered_paths):
            raise ValueError("recurring-findings validation cannot report dirty-worktree paths")
        for path in (*self.ledgered_paths, *self.unledgered_paths):
            try:
                require_portable_relative_path(path)
            except ContractError as error:
                raise ValueError("validation result contains a non-portable path") from error
        if self.kind == "dirty_closeout" and self.status != "blocked" and self.dirty_state is None:
            raise ValueError("non-blocked dirty closeout requires inspected Git dirty state")
        if self.kind == "dirty_closeout" and self.dirty_state is not None:
            unledgered = set(self.dirty_state.dirty_paths) - set(self.ledgered_paths)
            if set(self.unledgered_paths) != unledgered:
                raise ValueError("unledgered paths must equal dirty paths minus ledgered paths")
            if self.status == "pass" and unledgered:
                raise ValueError("passing dirty closeout requires all dirty paths to be ledgered")
        return self


__all__ = ["PrSweepDirtyState", "PrSweepFinding", "PrSweepValidationResult"]
