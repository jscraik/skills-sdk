"""Read-only PR-sweep validation results, independent of a Git host."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

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
        return self


__all__ = ["PrSweepDirtyState", "PrSweepFinding", "PrSweepValidationResult"]
