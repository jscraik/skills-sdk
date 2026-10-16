"""Machine-readable CLI route capability registry.

Agents previously had to infer implemented vs discovery-only status from
prose in docs/cli.md. Silent exit 0 on inventory/package/project/tessl made
unimplemented routes look successful. This module is the single source of
truth for route capability; tests assert every argparse route is classified.
"""

from __future__ import annotations

import argparse
import sys
from enum import StrEnum
from typing import Final


class RouteCapability(StrEnum):
    """What invoking a parsed route does."""

    IMPLEMENTED = "implemented"
    """Runs a real local service and returns a versioned result."""

    WRITE_GATED = "write_gated"
    """May mutate the host only with an explicit apply flag."""

    DISCOVERY_ONLY = "discovery_only"
    """Parses and exits without performing the named lifecycle work."""


# Keys are "command" or "command:subcommand". Keep this table exhaustive:
# tests/test_cli_route_capabilities.py fails when argparse grows a route
# that is missing here, or when a discovery-only route gains a silent handler.
ROUTE_CAPABILITIES: Final[dict[str, RouteCapability]] = {
    "inventory": RouteCapability.DISCOVERY_ONLY,
    "package": RouteCapability.DISCOVERY_ONLY,
    "project": RouteCapability.DISCOVERY_ONLY,
    "tessl:prepare": RouteCapability.DISCOVERY_ONLY,
    "tessl:verify": RouteCapability.DISCOVERY_ONLY,
    "intake": RouteCapability.IMPLEMENTED,
    "validate": RouteCapability.IMPLEMENTED,
    "build": RouteCapability.IMPLEMENTED,
    "check-local": RouteCapability.IMPLEMENTED,
    "check-quality": RouteCapability.IMPLEMENTED,
    "review-content": RouteCapability.IMPLEMENTED,
    "compare-copy": RouteCapability.IMPLEMENTED,
    "validate-plugin": RouteCapability.IMPLEMENTED,
    "check-plugin-presentation": RouteCapability.IMPLEMENTED,
    "verify:recurring-findings": RouteCapability.IMPLEMENTED,
    "verify:pr-sweep-dirty-closeout": RouteCapability.IMPLEMENTED,
    "eval:scenario-quality": RouteCapability.IMPLEMENTED,
    "eval:scenario-coverage": RouteCapability.IMPLEMENTED,
    "eval:scorer-quality": RouteCapability.IMPLEMENTED,
    "eval:scorer-calibration": RouteCapability.IMPLEMENTED,
    "eval:selected-case": RouteCapability.IMPLEMENTED,
    "eval:observed-calibration": RouteCapability.IMPLEMENTED,
    "eval:matched-assessment": RouteCapability.IMPLEMENTED,
    "eval:matched-calibration": RouteCapability.IMPLEMENTED,
    "eval:matched-cloud": RouteCapability.IMPLEMENTED,
    "eval:matched-cloud-regression": RouteCapability.IMPLEMENTED,
    "eval:matched-handoff": RouteCapability.IMPLEMENTED,
    "eval:matched-local": RouteCapability.IMPLEMENTED,
    "eval:matched-regression": RouteCapability.IMPLEMENTED,
    "maintain-entrypoint": RouteCapability.WRITE_GATED,
}

DISCOVERY_ONLY_EXIT: Final[int] = 3


def route_key(command: str | None, *, subcommand: str | None = None) -> str | None:
    """Return the registry key for a top-level command and optional subcommand."""
    if command is None:
        return None
    if subcommand:
        return f"{command}:{subcommand}"
    return command


def capability_for(command: str | None, *, subcommand: str | None = None) -> RouteCapability | None:
    """Look up capability for a parsed route, preferring the subcommand key."""
    if command is None:
        return None
    if subcommand is not None:
        keyed = ROUTE_CAPABILITIES.get(f"{command}:{subcommand}")
        if keyed is not None:
            return keyed
    return ROUTE_CAPABILITIES.get(command)


def _subcommand_for(arguments: argparse.Namespace) -> str | None:
    """Return the nested route name when a parent command requires one."""
    for attr in ("eval_command", "verify_command", "tessl_command"):
        value = getattr(arguments, attr, None)
        if isinstance(value, str) and value:
            return value
    return None


def reject_discovery_only(arguments: argparse.Namespace) -> int | None:
    """Fail loudly when a discovery-only route is invoked as if it were real work."""
    subcommand = _subcommand_for(arguments)
    capability = capability_for(arguments.command, subcommand=subcommand)
    if capability is not RouteCapability.DISCOVERY_ONLY:
        return None
    route = arguments.command if subcommand is None else f"{arguments.command} {subcommand}"
    print(
        f"discovery-only: `{route}` is a reserved CLI boundary and does not perform "
        "lifecycle work. See docs/cli.md and skills_sdk.cli.routes.ROUTE_CAPABILITIES.",
        file=sys.stderr,
    )
    return DISCOVERY_ONLY_EXIT


__all__ = [
    "DISCOVERY_ONLY_EXIT",
    "ROUTE_CAPABILITIES",
    "RouteCapability",
    "capability_for",
    "reject_discovery_only",
    "route_key",
]
