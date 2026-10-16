"""Prove every argparse route is classified and discovery-only routes fail loudly."""

from __future__ import annotations

import argparse

import pytest

from skills_sdk.cli.main import build_parser, main
from skills_sdk.cli.routes import DISCOVERY_ONLY_EXIT, ROUTE_CAPABILITIES, RouteCapability


def _nested_choices(parser: argparse.ArgumentParser, dest: str) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction) and action.dest == dest:
            return dict(action.choices)
    return {}


def _parser_route_keys() -> set[str]:
    parser = build_parser()
    top = _nested_choices(parser, "command")
    keys: set[str] = set()
    for name, subparser in top.items():
        nested = (
            _nested_choices(subparser, "eval_command")
            or _nested_choices(subparser, "verify_command")
            or _nested_choices(subparser, "tessl_command")
        )
        if nested:
            keys.update(f"{name}:{child}" for child in nested)
        else:
            keys.add(name)
    return keys


def test_every_argparse_route_is_classified() -> None:
    """Fail when a new CLI route is added without a capability entry."""
    assert _parser_route_keys() == set(ROUTE_CAPABILITIES)


@pytest.mark.parametrize(
    "arguments",
    [
        ["inventory"],
        ["package"],
        ["project"],
        ["tessl", "prepare"],
        ["tessl", "verify"],
    ],
)
def test_discovery_only_routes_exit_loudly(
    arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Discovery-only routes must not look like successful lifecycle work."""
    assert main(arguments) == DISCOVERY_ONLY_EXIT
    err = capsys.readouterr().err
    assert "discovery-only:" in err
    assert "ROUTE_CAPABILITIES" in err


def test_registry_marks_write_gated_entrypoint() -> None:
    assert ROUTE_CAPABILITIES["maintain-entrypoint"] is RouteCapability.WRITE_GATED
