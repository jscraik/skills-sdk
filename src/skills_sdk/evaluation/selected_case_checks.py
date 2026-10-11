"""Pure digest binding for complete selected-case test controls."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.core.errors import ContractError

if TYPE_CHECKING:
    from skills_sdk.evaluation.selected_case import SelectedCaseDefinition


def _category(value: object) -> Literal["happy", "pressure", "boundary", "regression"]:
    """Map supported package categories onto the evaluation-v2 contract."""
    if not isinstance(value, str):
        raise ContractError(code="invalid_selected_case", message="selected case category must be text")
    if value in {"happy", "pressure", "regression"}:
        return cast(Literal["happy", "pressure", "regression"], value)
    if value in {"boundary", "edge", "negative"}:
        return "boundary"
    raise ContractError(code="invalid_selected_case", message="selected case category is unsupported")


def _check_contract_digest(definition: SelectedCaseDefinition) -> str:
    return canonical_json_sha256(
        {
            "semantic": definition.semantic_assertions,
            "deterministic": definition.deterministic_assertions,
            "forbidden_commands": definition.scenario_set.cases[0].forbidden_commands,
        }
    )
