"""Separate, caller-bound advisory contracts; never acceptance receipts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from skills_sdk.models.inventory import Sha256, _ContractModel
from skills_sdk.models.package import PackageCandidateIdentity
from skills_sdk.models.safety import _public_text_is_redaction_safe

DocumentId = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
SnapshotText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=12000)]
Explanation = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=1200, pattern=r"^[^\x00-\x1f\x7f-\x9f]+$"),
]


class AdvisoryDocument(_ContractModel):
    """Explicit caller-supplied text, not a filesystem path to discover."""

    model_config = ConfigDict(revalidate_instances="always", str_strip_whitespace=False)
    document_id: DocumentId
    role: Literal["specification", "response"]
    text: SnapshotText

    @field_validator("text")
    @classmethod
    def text_has_content(cls, value: str) -> str:
        """Reject an empty context without silently normalizing source bytes."""
        if not value.strip():
            raise ValueError("advisory document must have content")
        return value


class FMAdvisoryRequest(_ContractModel):
    """A caller-bound optional check, not verified source or execution evidence."""

    model_config = ConfigDict(revalidate_instances="always", str_strip_whitespace=False)
    schema_version: Literal["fm-advisory-request/v1"] = "fm-advisory-request/v1"
    candidate: PackageCandidateIdentity
    kind: Literal["contradiction", "semantic"]
    assertion: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2000)]
    required_context: tuple[DocumentId, ...] = Field(min_length=2, max_length=32)
    documents: tuple[AdvisoryDocument, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def request_is_bounded(self) -> FMAdvisoryRequest:
        """Reject duplicate IDs and bound the exact supplied text workload."""
        ids = tuple(document.document_id for document in self.documents)
        if len(set(ids)) != len(ids) or len(set(self.required_context)) != len(self.required_context):
            raise ValueError("advisory context IDs must be unique")
        if not self.assertion.strip():
            raise ValueError("advisory assertion must have content")
        if len(self.model_dump_json().encode("utf-8")) > 16384:
            raise ValueError("advisory request exceeds 16 KiB")
        if sum(len(document.text.encode("utf-8")) for document in self.documents) > 12000:
            raise ValueError("advisory documents exceed the input budget")
        if sum(len(document.text.splitlines()) for document in self.documents) > 128:
            raise ValueError("advisory documents exceed 128 source lines")
        return self


class AdvisoryEvidence(_ContractModel):
    """A reference to supplied bytes, without exporting the raw quotation."""

    document_id: DocumentId
    line: int = Field(ge=1, strict=True)
    line_sha256: Sha256


class FMAdvisoryResult(_ContractModel):
    """Neutral advisory observation, deliberately incompatible with SDK receipts."""

    model_config = ConfigDict(revalidate_instances="always", str_strip_whitespace=False)
    schema_version: Literal["fm-advisory/v1"] = "fm-advisory/v1"
    candidate: PackageCandidateIdentity
    request_sha256: Sha256
    source_binding: Literal["caller_supplied"] = "caller_supplied"
    advisory_only: Literal[True] = True
    acceptance_authorized: Literal[False] = False
    status: Literal["completed", "skipped", "unavailable", "error"]
    generation_attempted: bool = Field(default=False, strict=True)
    reason: (
        Literal[
            "missing_required_context",
            "unsupported_platform",
            "fm_unavailable",
            "custom_provider_configured",
            "execution_timeout",
            "execution_failed",
            "invalid_model_output",
            "input_limit",
        ]
        | None
    ) = None
    missing_context_ids: tuple[DocumentId, ...] = ()
    judgement: Literal["no_finding", "finding", "insufficient_evidence"] | None = None
    explanation: Explanation | None = None
    missing_context_note: Explanation | None = None
    evidence: tuple[AdvisoryEvidence, ...] = Field(default=(), max_length=8)
    model_output_sha256: Sha256 | None = None

    @field_validator("advisory_only", "acceptance_authorized", mode="before")
    @classmethod
    def flags_are_booleans(cls, value: object) -> object:
        """Reject integer aliases for advisory and acceptance flags."""
        if type(value) is not bool:
            raise ValueError("advisory flags require JSON booleans")
        return value

    @field_validator("explanation", "missing_context_note")
    @classmethod
    def public_text_is_safe(cls, value: str | None) -> str | None:
        """Do not return credential-shaped or machine-specific model text."""
        if value is not None and (not value.strip() or not _public_text_is_redaction_safe(value)):
            raise ValueError("advisory explanation is not public-safe")
        return value

    @model_validator(mode="after")
    def outcome_matches_execution(self) -> FMAdvisoryResult:
        """Keep skips/errors free of invented judgements or acceptance evidence."""
        if self.status == "completed":
            if not self.generation_attempted or self.reason is not None or self.judgement is None:
                raise ValueError("completed advisory requires an attempted model judgement")
            if self.explanation is None or self.model_output_sha256 is None or self.missing_context_ids:
                raise ValueError("completed advisory requires bound model output")
            if self.judgement == "insufficient_evidence":
                if self.missing_context_note is None or self.evidence:
                    raise ValueError("abstention needs missing context and no decisive evidence")
            elif self.missing_context_note is not None or len(self.evidence) < 2:
                raise ValueError("decisive advisory requires both source references")
        elif self.judgement is not None or self.explanation is not None or self.evidence:
            raise ValueError("unexecuted or failed advisory cannot contain judgement evidence")
        elif self.model_output_sha256 is not None or self.missing_context_note is not None:
            raise ValueError("unusable output cannot masquerade as a model observation")
        if self.status != "completed" and self.reason is None:
            raise ValueError("noncompleted advisory needs a reason")
        if self.status == "unavailable" and self.reason not in {
            "unsupported_platform",
            "fm_unavailable",
            "custom_provider_configured",
        }:
            raise ValueError("unavailable advisory needs an availability reason")
        if self.status == "error" and self.reason not in {
            "execution_timeout",
            "execution_failed",
            "invalid_model_output",
            "input_limit",
        }:
            raise ValueError("advisory error needs an execution reason")
        if self.status in {"skipped", "unavailable"} and self.generation_attempted:
            raise ValueError("skipped or unavailable advisory cannot claim generation")
        if (self.status == "skipped") != (self.reason == "missing_required_context"):
            raise ValueError("only missing required context is a preflight skip")
        if (self.status == "skipped") != bool(self.missing_context_ids):
            raise ValueError("skip must identify missing context")
        if len(set(self.missing_context_ids)) != len(self.missing_context_ids):
            raise ValueError("missing context IDs must be unique")
        if len({(item.document_id, item.line) for item in self.evidence}) != len(self.evidence):
            raise ValueError("advisory evidence must be unique")
        return self
