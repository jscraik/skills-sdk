"""Bounded validation of untrusted provider metadata before serialization."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import cast

from pydantic_core import PydanticSerializationError

from skills_sdk.core.errors import ContractError
from skills_sdk.models.provider_call import ProviderCostObservation
from skills_sdk.models.provider_execution import ProviderUsageMetadata
from skills_sdk.providers.types import JsonValue

_MAX_PROVIDER_METADATA_BYTES = 65_536
_MAX_PROVIDER_METADATA_ITEMS = 256
_MAX_PROVIDER_METADATA_ITEM_BYTES = 4_096


def _canonical_bytes(value: JsonValue) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _metadata_text(value: object, invalid_code: str) -> str:
    if type(value) is not str:
        raise ContractError(invalid_code, "provider metadata contains an invalid string")
    text = str.__str__(value)
    if len(text) > _MAX_PROVIDER_METADATA_ITEM_BYTES:
        raise ContractError("provider_metadata_too_large", "provider metadata exceeds the byte limit")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        raise ContractError(invalid_code, "provider metadata strings must be valid UTF-8") from None
    if len(encoded) > _MAX_PROVIDER_METADATA_ITEM_BYTES:
        raise ContractError("provider_metadata_too_large", "provider metadata exceeds the byte limit")
    return text


def _validate_evidence_refs(value: object, invalid_code: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise ContractError(invalid_code, "provider evidence refs have an invalid container")
    if len(value) > _MAX_PROVIDER_METADATA_ITEMS:
        raise ContractError("provider_metadata_too_large", "provider metadata exceeds the item limit")
    canonical_size = 2
    for index, item in enumerate(value):
        text = _metadata_text(item, invalid_code)
        canonical_size += len(_canonical_bytes(text)) + (1 if index else 0)
        if canonical_size > _MAX_PROVIDER_METADATA_BYTES:
            raise ContractError("provider_metadata_too_large", "provider metadata exceeds the byte limit")
    return cast(tuple[str, ...], value)


def _require_metadata_budget(value: JsonValue, invalid_code: str) -> None:
    try:
        size = len(_canonical_bytes(value))
    except (TypeError, ValueError):
        raise ContractError(invalid_code, "provider metadata failed serialization") from None
    if size > _MAX_PROVIDER_METADATA_BYTES:
        raise ContractError("provider_metadata_too_large", "provider metadata exceeds the byte limit")


def _validate_usage(value: object) -> ProviderUsageMetadata | None:
    if value is None:
        return None
    if type(value) is not ProviderUsageMetadata:
        raise ContractError("invalid_provider_event", "provider usage evidence failed validation")
    _metadata_text(getattr(value, "unit_kind", None), "invalid_provider_event")
    counts = (
        getattr(value, "input_units", None),
        getattr(value, "output_units", None),
        getattr(value, "total_units", None),
    )
    if any(type(count) is not int for count in counts):
        raise ContractError("invalid_provider_event", "provider usage evidence failed validation")
    if any(int.bit_length(count) > _MAX_PROVIDER_METADATA_BYTES * 4 for count in counts):
        raise ContractError("provider_metadata_too_large", "provider metadata exceeds the byte limit")
    try:
        payload = value.model_dump(mode="json", warnings="none")
        return ProviderUsageMetadata.model_validate(payload)
    except (PydanticSerializationError, TypeError, ValueError):
        raise ContractError("invalid_provider_event", "provider usage evidence failed validation") from None


def _validate_cost(value: object) -> ProviderCostObservation | None:
    if value is None:
        return None
    if type(value) is not ProviderCostObservation:
        raise ContractError("invalid_provider_event", "provider cost evidence failed validation")
    amount = getattr(value, "amount", None)
    if type(amount) is str:
        _metadata_text(amount, "invalid_provider_event")
    elif type(amount) is not Decimal:
        raise ContractError("invalid_provider_event", "provider cost evidence failed validation")
    elif amount.__sizeof__() > _MAX_PROVIDER_METADATA_BYTES:
        raise ContractError("provider_metadata_too_large", "provider metadata exceeds the byte limit")
    else:
        _metadata_text(str(amount), "invalid_provider_event")
    _metadata_text(getattr(value, "currency", None), "invalid_provider_event")
    _metadata_text(getattr(value, "claimed_by", None), "invalid_provider_event")
    if type(getattr(value, "observed_at", None)) not in {datetime, str}:
        raise ContractError("invalid_provider_event", "provider cost evidence failed validation")
    if type(getattr(value, "observed_at", None)) is str:
        _metadata_text(getattr(value, "observed_at", None), "invalid_provider_event")
    try:
        payload = value.model_dump(mode="json", warnings="none")
        return ProviderCostObservation.model_validate(payload)
    except (PydanticSerializationError, TypeError, ValueError):
        raise ContractError("invalid_provider_event", "provider cost evidence failed validation") from None
