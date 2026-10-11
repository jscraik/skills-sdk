"""Explicit offline Codex-profile adapters; no home discovery or provider calls.

Construct the profile identity before freezing a matched plan. Its adapter digest
binds profile, dependencies and caller defaults, so changed inputs require a new
plan and downstream calibration. The model revision is caller-supplied evidence,
not a verified external model revision. Drivers remain separately supplied.
"""

from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.providers._codex_profile_adapter import (
    _CodexProfiledCompleteAdapter as CodexProfiledCompleteAdapter,
)
from skills_sdk.providers._codex_profile_adapter import (
    _CodexProfiledJudgeAdapter as CodexProfiledJudgeAdapter,
)
from skills_sdk.providers._codex_profile_adapter import (
    _CodexProfiledStreamingAdapter as CodexProfiledStreamingAdapter,
)
from skills_sdk.providers._codex_profile_binding import (
    _capture_codex_profile,
)
from skills_sdk.providers._codex_profile_binding import (
    _CodexProfileSource as CodexProfileSource,
)
from skills_sdk.providers._codex_profile_invocation import (
    _CodexProfileInvocation as CodexProfileInvocation,
)
from skills_sdk.providers._codex_profile_invocation import (
    _compile_codex_profile as compile_codex_profile,
)


def describe_codex_profile(source: CodexProfileSource, *, model_revision: str) -> ProviderIdentityV2:
    """Return input-bound identity for a frozen lane; this grants no execution authority."""
    selected, digest = _capture_codex_profile(source)
    return ProviderIdentityV2(
        provider_id=selected.provider,
        provider_kind="llm",
        model_id=f"{selected.provider}/{selected.model}",
        version_or_digest=model_revision,
        adapter_id="codex-profile-offline-v1",
        adapter_version_or_digest=digest,
    )


__all__ = [
    "CodexProfileInvocation",
    "CodexProfileSource",
    "CodexProfiledCompleteAdapter",
    "CodexProfiledJudgeAdapter",
    "CodexProfiledStreamingAdapter",
    "compile_codex_profile",
    "describe_codex_profile",
]
