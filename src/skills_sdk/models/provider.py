"""Portable identity for external providers and their adapters."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import StringConstraints, field_validator

from skills_sdk.models.inventory import _ContractModel

ProviderSlug = Annotated[str, StringConstraints(max_length=64, pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")]
IdentityText = Annotated[str, StringConstraints(max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:+-]*$")]

_CREDENTIAL_PREFIXES = ("akia", "bearer", "ghp_", "github_pat_", "sk-", "xoxb-", "xoxp-")
_CREDENTIAL_COMPONENT_PATTERN = re.compile(
    rf"(?:^|[._:+-])(?:{'|'.join(re.escape(prefix) for prefix in _CREDENTIAL_PREFIXES)})",
    re.IGNORECASE,
)


class ProviderIdentity(_ContractModel):
    """Secret-free identity for the external producer of an observation."""

    schema_version: Literal["provider-identity/v1"] = "provider-identity/v1"
    provider_id: ProviderSlug
    provider_kind: Literal["llm", "agent", "external"]
    model_id: IdentityText
    version_or_digest: IdentityText
    adapter_id: ProviderSlug
    adapter_version_or_digest: IdentityText

    @field_validator(
        "provider_id", "model_id", "version_or_digest", "adapter_id", "adapter_version_or_digest", mode="before"
    )
    @classmethod
    def identity_text_is_redaction_safe(cls, value: object) -> object:
        if isinstance(value, str):
            if value != value.strip():
                raise ValueError("provider identity text must not contain surrounding whitespace")
            if _CREDENTIAL_COMPONENT_PATTERN.search(value):
                raise ValueError("provider identity text must not contain credential-shaped values")
        return value


ModelIdentityText = Annotated[
    str,
    StringConstraints(
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:+-]*(?:/[A-Za-z0-9][A-Za-z0-9._:+-]*)*$",
    ),
]

_V2_CREDENTIAL_PREFIXES = ("aiza", "akia", "bearer", "ghp_", "github_pat_", "hf_", "sk-", "xoxb-", "xoxp-")
_V2_CREDENTIAL_COMPONENT_PATTERN = re.compile(
    rf"(?:^|[._:+/-])(?:{'|'.join(re.escape(prefix) for prefix in _V2_CREDENTIAL_PREFIXES)})",
    re.IGNORECASE,
)
_URI_SCHEME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


class ProviderIdentityV2(_ContractModel):
    """Hardened provider identity for provider-bearing v2 contracts."""

    schema_version: Literal["provider-identity/v2"] = "provider-identity/v2"
    provider_id: ProviderSlug
    provider_kind: Literal["llm", "agent", "external"]
    model_id: ModelIdentityText
    version_or_digest: IdentityText
    adapter_id: ProviderSlug
    adapter_version_or_digest: IdentityText

    @field_validator("model_id", mode="before")
    @classmethod
    def model_id_is_not_a_uri(cls, value: object) -> object:
        if isinstance(value, str) and _URI_SCHEME_PATTERN.match(value):
            raise ValueError("provider model_id must not be a URI")
        return value

    @field_validator(
        "provider_id", "model_id", "version_or_digest", "adapter_id", "adapter_version_or_digest", mode="before"
    )
    @classmethod
    def identity_text_is_redaction_safe(cls, value: object) -> object:
        if isinstance(value, str):
            if value != value.strip():
                raise ValueError("provider identity text must not contain surrounding whitespace")
            if _V2_CREDENTIAL_COMPONENT_PATTERN.search(value):
                raise ValueError("provider identity text must not contain credential-shaped values")
        return value


__all__ = ["ProviderIdentity", "ProviderIdentityV2"]
