"""Deterministic independent trial identities within one frozen experiment."""

from __future__ import annotations

from skills_sdk.core.digests import canonical_json_sha256


def matched_trial_identity(
    plan_sha256: str, lane: str, case_id: str, variant: str, trial_index: int
) -> tuple[str, str]:
    """Namespace request and idempotency identities without changing input bytes."""
    digest = canonical_json_sha256(
        {
            "schema_version": "matched-trial-identity/v1",
            "plan_sha256": plan_sha256,
            "lane": lane,
            "case_id": case_id,
            "variant": variant,
            "trial_index": trial_index,
        }
    )
    return f"matched-trial-{digest}", digest
