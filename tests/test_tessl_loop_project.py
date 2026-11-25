"""Regression coverage for SDK issue intake routed to the wrong Tessl project."""

import json

import pytest

from scripts import check_tessl_loop_project as preflight


@pytest.mark.parametrize(
    ("workspace_id", "project_id", "exit_code"),
    [
        ("lab-workspace", "lab-project", 0),
        ("personal-workspace", "personal-project", 1),
        ("lab-workspace", "unrelated-project", 1),
        ("", "", 1),
    ],
)
def test_tessl_loop_checks_committed_project_identity(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    workspace_id: str,
    project_id: str,
    exit_code: int,
) -> None:
    responses = {
        ("git", "rev-parse", "--verify", "--end-of-options", "origin/main^{commit}"): "0" * 40,
        ("git", "show", f"{'0' * 40}:tessl.json"): json.dumps({"name": "skills-sdk-lab/skills-sdk"}),
        ("tessl", "project", "list", "--workspace", "skills-sdk-lab", "--json"): json.dumps(
            {"projects": [{"name": "skills-sdk", "workspaceId": "lab-workspace", "id": "lab-project"}]}
        ),
        ("tessl", "loop", "view", "intake", "--json"): json.dumps(
            {"data": {"attributes": {"workspaceId": workspace_id, "projectId": project_id}}}
        ),
    }

    def read_command(command: tuple[str, ...] | list[str], *, text: bool) -> str:
        assert text
        return responses[tuple(command)]

    monkeypatch.setattr(preflight.subprocess, "check_output", read_command)
    monkeypatch.setattr(preflight.sys, "argv", ["check-tessl-loop", "--revision", "origin/main", "--loop", "intake"])

    assert preflight.main() == exit_code
    captured = capsys.readouterr()
    if exit_code:
        assert "expected ('lab-workspace', 'lab-project') for skills-sdk-lab/skills-sdk" in captured.err
    else:
        assert "matches skills-sdk-lab/skills-sdk" in captured.out
