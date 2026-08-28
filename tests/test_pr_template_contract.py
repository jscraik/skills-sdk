from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _load_validator() -> ModuleType:
    path = REPOSITORY_ROOT / ".github" / "scripts" / "validate_pr_template_body.py"
    spec = importlib.util.spec_from_file_location("validate_pr_template_body", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _template() -> str:
    return (REPOSITORY_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")


def _filled_body() -> str:
    validator = _load_validator()
    body = _template().replace("- [ ]", "- [x]")
    body = validator.FIELD_LINE_RE.sub(
        lambda match: (
            match.group(0)
            if match.group("label") == "Command" or match.group("value").strip()
            else f"- {match.group('label')}: repo-relative evidence"
        ),
        body,
    )
    return body.replace(
        "- Regression coverage: repo-relative evidence",
        "- Regression coverage: focused contract proof\n"
        "- Command: `mise exec -- uv run --frozen pytest tests/test_pr_template_contract.py -q` -> pass\n"
        "- Command: `bash scripts/validate-repository.sh` -> pass",
        1,
    )


def test_accepts_filled_sdk_template() -> None:
    validator = _load_validator()

    assert validator.validate_pr_body(_template(), _filled_body()) == []


def test_rejects_stale_body_missing_current_section() -> None:
    validator = _load_validator()
    body = _filled_body().replace("## Review and readiness", "## Review", 1)

    errors = validator.validate_pr_body(_template(), body)

    assert any("sections must match" in error for error in errors)


def test_rejects_missing_required_field() -> None:
    validator = _load_validator()
    body = _filled_body().replace("- Update readiness: repo-relative evidence\n", "", 1)

    errors = validator.validate_pr_body(_template(), body)

    assert "Missing required field in ## Review and readiness: Update readiness:" in errors


def test_rejects_empty_required_field() -> None:
    validator = _load_validator()
    body = _filled_body().replace("- Problem: repo-relative evidence", "- Problem:", 1)

    errors = validator.validate_pr_body(_template(), body)

    assert "Required field in ## Summary is empty: Problem:" in errors


def test_rejects_duplicate_required_field() -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "- Problem: repo-relative evidence",
        "- Problem: repo-relative evidence\n- Problem: duplicate",
        1,
    )

    errors = validator.validate_pr_body(_template(), body)

    assert "Duplicate field in ## Summary: Problem:" in errors


def test_rejects_changed_checklist_text() -> None:
    validator = _load_validator()
    body = _filled_body().replace("The branch is dedicated", "This branch is dedicated", 1)

    errors = validator.validate_pr_body(_template(), body)

    assert "Checklist item text and order must match the template exactly." in errors


def test_allows_explicit_pending_checklist_state() -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "- [x] The branch will be removed after merge.",
        "- [ ] **(Pending)** The branch will be removed after merge.",
        1,
    )

    assert validator.validate_pr_body(_template(), body) == []


def test_allows_indented_pending_checklist_state() -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "- [x] The branch will be removed after merge.",
        "- [ ]   **(Pending)** The branch will be removed after merge.",
        1,
    )

    assert validator.validate_pr_body(_template(), body) == []


def test_allows_documented_dotted_not_applicable_checklist_state() -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "- [x] The branch will be removed after merge.",
        "- [ ] **(n.a.)** The branch will be removed after merge.",
        1,
    )

    assert validator.validate_pr_body(_template(), body) == []


def test_rejects_unclassified_unchecked_checklist_item() -> None:
    validator = _load_validator()
    body = _filled_body().replace("- [x] The branch will", "- [ ] The branch will", 1)

    errors = validator.validate_pr_body(_template(), body)

    assert any("requires an explicit Pending or N/A marker" in error for error in errors)


@pytest.mark.parametrize("status", ["Pending", "n.a.", "N/A", "not applicable"])
def test_rejects_status_marker_on_checked_checklist_item(status: str) -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "- [x] The branch will be removed after merge.",
        f"- [x] **({status})** The branch will be removed after merge.",
        1,
    )

    errors = validator.validate_pr_body(_template(), body)

    assert any("Checked checklist item cannot use" in error for error in errors)


def test_rejects_missing_or_malformed_command_evidence() -> None:
    validator = _load_validator()
    body = re.sub(r"^- Command:.*$", "- Command: pytest -> maybe", _filled_body(), flags=re.MULTILINE)

    errors = validator.validate_pr_body(_template(), body)

    assert any("Invalid Command evidence" in error for error in errors)


def test_rejects_validation_without_aggregate_repository_evidence() -> None:
    validator = _load_validator()
    body = _filled_body().replace("- Command: `bash scripts/validate-repository.sh` -> pass\n", "", 1)

    errors = validator.validate_pr_body(_template(), body)

    assert "Validation must include Command evidence for bash scripts/validate-repository.sh." in errors


def test_rejects_not_applicable_command_outcome() -> None:
    validator = _load_validator()
    body = re.sub(r"^- Command:.*$", "- Command: pytest -> n.a. (not run)", _filled_body(), flags=re.MULTILINE)

    errors = validator.validate_pr_body(_template(), body)

    assert any("Invalid Command evidence" in error for error in errors)


@pytest.mark.parametrize(
    "detail",
    ["not run", "not-run", "not executed", "not-executed", "unexecuted", "blocked by missing tool"],
)
def test_rejects_passing_command_with_nonexecution_detail(detail: str) -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "`bash scripts/validate-repository.sh` -> pass",
        f"`bash scripts/validate-repository.sh` -> pass ({detail})",
        1,
    )

    errors = validator.validate_pr_body(_template(), body)

    assert any("cannot contradict the execution result" in error for error in errors)


@pytest.mark.parametrize("detail", ["not blocked; executed", "not   blocked; executed", "not-unexecuted"])
def test_allows_passing_command_with_negated_blocker_detail(detail: str) -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "`bash scripts/validate-repository.sh` -> pass",
        f"`bash scripts/validate-repository.sh` -> pass ({detail})",
        1,
    )

    assert validator.validate_pr_body(_template(), body) == []


@pytest.mark.parametrize("detail", ["tests failed", "failure", "error", "three errors"])
def test_rejects_passing_command_with_failure_detail(detail: str) -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "`bash scripts/validate-repository.sh` -> pass",
        f"`bash scripts/validate-repository.sh` -> pass ({detail})",
        1,
    )

    errors = validator.validate_pr_body(_template(), body)

    assert any("cannot contradict the execution result" in error for error in errors)


def test_allows_passing_command_with_negated_error_detail() -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "`bash scripts/validate-repository.sh` -> pass",
        "`bash scripts/validate-repository.sh` -> pass (no errors; tests passed)",
        1,
    )

    assert validator.validate_pr_body(_template(), body) == []


def test_command_line_does_not_fill_empty_required_field() -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "- Regression coverage: focused contract proof\n",
        "- Regression coverage:\n",
        1,
    )

    errors = validator.validate_pr_body(_template(), body)

    assert "Required field in ## Validation is empty: Regression coverage:" in errors


def test_indented_code_does_not_satisfy_command_evidence() -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "- Command: `bash scripts/validate-repository.sh` -> pass",
        "    - Command: `bash scripts/validate-repository.sh` -> pass",
        1,
    )

    errors = validator.validate_pr_body(_template(), body)

    assert "Validation must include Command evidence for bash scripts/validate-repository.sh." in errors


@pytest.mark.parametrize("marker", ["n.a.", "N/A", "not applicable"])
def test_rejects_bare_not_applicable_field(marker: str) -> None:
    validator = _load_validator()
    body = _filled_body().replace("- Public API impact: repo-relative evidence", f"- Public API impact: {marker}", 1)

    errors = validator.validate_pr_body(_template(), body)

    assert (
        "Not-applicable field in ## Contract and evidence boundaries requires a concrete reason: Public API impact:"
        in errors
    )


def test_allows_not_applicable_field_with_reason() -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "- Public API impact: repo-relative evidence",
        "- Public API impact: n.a. because no public model changes.",
        1,
    )

    assert validator.validate_pr_body(_template(), body) == []


def test_rejects_local_absolute_path() -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "- Problem: repo-relative evidence", "- Problem: observed at /" + "private/tmp/sdk-fixture"
    )

    errors = validator.validate_pr_body(_template(), body)

    assert "PR body must not contain local absolute paths." in errors


def test_allows_web_urls_and_repository_relative_paths() -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "- Problem: repo-relative evidence",
        "- Problem: see https://example.test/evidence and docs/standards.md",
    )

    assert validator.validate_pr_body(_template(), body) == []


def test_allows_html_details_and_markdown_autolinks() -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "- Problem: repo-relative evidence",
        "- Problem: <details><summary>Evidence</summary><https://example.test/evidence></details>",
    )

    assert validator.validate_pr_body(_template(), body) == []


def test_rejects_genuine_placeholder_tokens() -> None:
    validator = _load_validator()
    body = _filled_body().replace("- Problem: repo-relative evidence", "- Problem: <describe the problem>")

    errors = validator.validate_pr_body(_template(), body)

    assert "Replace unresolved placeholder token: <describe the problem>" in errors


def test_rejects_template_contract_rendered_only_inside_fenced_code() -> None:
    validator = _load_validator()
    body = f"```markdown\n{_filled_body()}\n```\n"

    errors = validator.validate_pr_body(_template(), body)

    assert any("sections must match" in error for error in errors)
    assert "Validation must include at least one Command evidence line." in errors


def test_rejects_fenced_template_with_longer_valid_closing_fence() -> None:
    validator = _load_validator()
    body = f"```markdown\n{_filled_body()}\n````\n"

    errors = validator.validate_pr_body(_template(), body)

    assert any("sections must match" in error for error in errors)
    assert "Validation must include at least one Command evidence line." in errors


def test_html_comment_inside_fence_does_not_hide_following_contract() -> None:
    validator = _load_validator()
    body = _filled_body().replace(
        "## Summary",
        "```markdown\n<!-- literal comment opener\n```\n-->\n## Summary",
        1,
    )

    assert validator.validate_pr_body(_template(), body) == []
