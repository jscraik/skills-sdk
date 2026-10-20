"""Native Codex controls, without fabricated sampling or backend attestation."""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator

from skills_sdk.core.digests import canonical_json_sha256
from skills_sdk.models.inventory import NonEmptyText, _ContractModel
from skills_sdk.models.provider import ProviderIdentityV2
from skills_sdk.models.provider_execution import _identity_is_public

_MCP_NAME_LIMIT = 64
_MCP_SERVER_LIMIT = 64


class CodexNativeJudgeParameters(_ContractModel):
    """Frozen requested CLI controls; temperature is explicitly unavailable."""

    model_config = ConfigDict(revalidate_instances="always")
    schema_version: Literal["codex-native-judge-parameters/v1"] = "codex-native-judge-parameters/v1"
    model: NonEmptyText
    cli_version: NonEmptyText
    reasoning_effort: Literal["low", "medium", "high"]
    temperature: None = None
    temperature_control: Literal["not_exposed_by_codex_cli"] = "not_exposed_by_codex_cli"
    trial_count: Literal[1] = 1
    timeout_seconds: int = Field(ge=1, le=300, strict=True)
    sandbox: Literal["read-only"] = "read-only"
    web_search: Literal["disabled"] = "disabled"
    shell_tool: Literal[False] = False
    apps: Literal[False] = False
    plugins: Literal[False] = False
    ephemeral: Literal[True] = True
    disabled_mcp_servers: tuple[Annotated[str, Field(min_length=1, max_length=_MCP_NAME_LIMIT)], ...] = Field(
        max_length=_MCP_SERVER_LIMIT
    )

    @field_validator("trial_count", "shell_tool", "apps", "plugins", "ephemeral", mode="before")
    @classmethod
    def exact_controls(cls, value: object, info: object) -> object:
        """Do not coerce boolean trials or numeric capability flags."""
        if type(value) not in (bool, int):
            raise ValueError("native controls require exact scalar types")
        if info.field_name == "trial_count":
            if type(value) is not int or value != 1:
                raise ValueError("native calibration requires one trial per fresh capability")
        elif type(value) is not bool:
            raise ValueError("capability controls require booleans")
        return value

    @field_validator("model", "cli_version", mode="before")
    @classmethod
    def public_identity(cls, value: object, info: object) -> str:
        """Require the same canonical public identities as the executable adapter."""
        if type(value) is not str:
            raise ValueError("native identities must be strings")
        ProviderIdentityV2(
            provider_id="codex",
            provider_kind="agent",
            model_id=value if info.field_name == "model" else "model",
            version_or_digest=value if info.field_name == "cli_version" else "v1",
            adapter_id="codex-cli-judge",
            adapter_version_or_digest="v1",
        )
        if (
            not _identity_is_public(value)
            or PurePosixPath(value).is_absolute()
            or PureWindowsPath(value).drive
            or value.startswith(("~", "\\"))
        ):
            raise ValueError("native identities must be public and portable")
        return value

    @field_validator("disabled_mcp_servers", mode="before")
    @classmethod
    def simple_unique_names(cls, value: object) -> object:
        """Bind an explicit, unique list of configuration keys."""
        if (
            not isinstance(value, (list, tuple))
            or len(value) > _MCP_SERVER_LIMIT
            or any(
                type(name) is not str
                or not name
                or len(name) > _MCP_NAME_LIMIT
                or not all(char.isascii() and (char.isalnum() or char in "_-") for char in name)
                for name in value
            )
            or len(set(value)) != len(value)
        ):
            raise ValueError("MCP names must be unique simple keys")
        return value

    def settings_sha256(self) -> str:
        """Bind only the settings actually compiled into invocation arguments."""
        return canonical_json_sha256(self.model_dump(mode="json", exclude={"schema_version"}))
