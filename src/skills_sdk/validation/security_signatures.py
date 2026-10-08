"""Deterministic source indicators, adapted from pinned Agent-Skills semantics.

Indicators require applicable review; they are not a claim of exploitability.
Raw source and matched credential values never enter public findings.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath

from skills_sdk.models.risk import SecurityFinding

_PATTERNS = (
    (
        r"\b(fetch|download|curl|wget|retrieve)\b[^\n]{0,80}(?:\b(instruction|prompt|rule|skill|agent)\b|https?://[^\s)'\"]+)",
        "runtime_instruction_fetch",
        "external_service",
    ),
    (
        r"\b(api[_-]?(?:key|token)|access[_-]?token|auth[_-]?token|secret|password|credential)\b"
        r"\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{8,}",
        "hardcoded_secret_literal",
        "secret",
    ),
    (
        r"\b(print|echo|log|stdout|stderr|trace)\b[^\n]{0,80}\b(secret|token|password|credential|api key)\b",
        "insecure_credential_output",
        "secret",
    ),
    (
        r"\b(launchctl|systemctl|crontab|sudo)\b|/Library/LaunchAgents|/etc/",
        "system_service_modification",
        "unsafe_path",
    ),
    (
        r"\brm\s+-rf\b|\bdelete all\b|\bdrop table\b|\bwipe\s+(?:the\s+)?(?:repo|disk|database)",
        "destructive_local_capability",
        "unsafe_path",
    ),
    (r"\b(webhook|post to|send to|upload|publish|deploy|push)\b", "external_write_capability", "external_service"),
    (r"\b(mcp|tool[_ -]?call|allowed[_ -]?tools)\b", "tool_access_capability", "mcp_auth"),
    (
        r"(?s)\b(?:fetch|download|retrieve|browse|scrape|crawl|open|load|read|ingest)\b.{0,120}?"
        r"\b(?:untrusted|arbitrary url|third[- ]party|unknown website|social media|forum|reddit|"
        r"browser content|web page)\b",
        "untrusted_external_content_acquisition",
        "external_service",
    ),
)

_PIPE_TOKENS = re.compile(r"\b(?:curl|wget)\b|[|\n]", re.IGNORECASE)
_SHELL_AFTER_PIPE = re.compile(r"\s*(?:sh|bash|zsh|python|node)\b", re.IGNORECASE)
_URL_TOKENS = re.compile(r"https?://[^\s)'\"]*", re.IGNORECASE)
_DOWNLOAD_MARKERS = re.compile(
    r"raw\.githubusercontent\.com|gist\.githubusercontent\.com|bit\.ly|tinyurl\.com|"
    r"\.sh\b|\.py\b|\.js\b|\.zip\b|\.tgz\b|\.tar\.gz\b|\.dmg\b|\.pkg\b|\.exe\b",
    re.IGNORECASE,
)


def _pipe_to_shell(text: str) -> bool:
    """Scan non-overlapping download/pipe segments without repeated tail scans."""
    download = False
    for token in _PIPE_TOKENS.finditer(text):
        if token.group() == "\n":
            download = False
        elif token.group() == "|":
            if download and _SHELL_AFTER_PIPE.match(text, token.end()) is not None:
                return True
            download = False
        else:
            download = True
    return False


def _suspicious_download_url(text: str) -> bool:
    """Inspect each consumed URL once, including nested scheme-shaped text."""
    return any(_DOWNLOAD_MARKERS.search(token.group()) is not None for token in _URL_TOKENS.finditer(text))


def _finding(code: str, category: str, path: str) -> SecurityFinding:
    return SecurityFinding.model_validate(
        {
            "code": code,
            "category": category,
            "severity": "warning",
            "message": "Captured source contains an indicator requiring applicable review.",
            "evidence_refs": [path],
        }
    )


def source_security_indicators(path: str, content: bytes) -> tuple[SecurityFinding, ...]:
    """Inspect captured bytes without following paths, executing source or emitting it."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return (_finding("opaque_binary_content", "dependency", path),)
    if path == "references/evals.yaml":
        text = _eval_security_text(text)
    findings = []
    if _pipe_to_shell(text):
        findings.append(_finding("pipe_to_shell_download", "external_service", path))
    if _suspicious_download_url(text):
        findings.append(_finding("suspicious_download_url", "external_service", path))
    findings.extend(
        _finding(code, category, path)
        for pattern, code, category in _PATTERNS
        if re.search(pattern, text, re.IGNORECASE)
    )
    codes = {finding.code for finding in findings}
    if "untrusted_external_content_acquisition" in codes and codes & {
        "hardcoded_secret_literal",
        "external_write_capability",
    }:
        findings.append(_finding("composed_capability_risk", "external_service", path))
    if any(char not in "\n\r\t" and unicodedata.category(char) in {"Cf", "Cc"} for char in text):
        findings.append(_finding("hidden_unicode_obfuscation", "unsafe_path", path))
    name = PurePosixPath(path)
    if (
        text.startswith("#!")
        or "scripts" in name.parts
        or name.suffix.lower()
        in {
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".sh",
            ".bash",
            ".zsh",
            ".ps1",
        }
    ):
        findings.append(_finding("executable_source_capability", "dependency", path))
    if name.name.lower() in {"requirements.txt", "pyproject.toml", "package.json", "uv.lock", "package-lock.json"}:
        findings.append(_finding("dependency_manifest", "dependency", path))
    return tuple(findings)


def _eval_security_text(text: str) -> str:
    """Exclude only closed, explicit refusal prompts; malformed input scans raw."""
    import yaml

    from skills_sdk.validation.safe_yaml import _ClosedLoader

    try:
        payload = yaml.load(text, Loader=_ClosedLoader)
    except (yaml.YAMLError, ValueError, TypeError, RecursionError):
        return text
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        return text
    return "\n".join(
        [str(key) + "\n" + str(value) for key, value in payload.items() if key != "cases"]
        + [_case_security_text(case) for case in payload["cases"]]
    )


def _case_security_text(case: object) -> str:
    if not isinstance(case, dict):
        return str(case)
    expectation = case.get("should")
    refusal = (
        case.get("category") in {"negative", "pressure"}
        and isinstance(expectation, str)
        and expectation.strip().lower()
        in {"refuse the operation", "reject the operation", "decline the operation", "cannot comply"}
    )
    # Only the adversarial prompt is exempt: task/given and unknown fields retain
    # source risk. Ordinary positive prompts never inherit this exemption.
    return "\n".join(str(key) + "\n" + str(value) for key, value in case.items() if not (key == "prompt" and refusal))
