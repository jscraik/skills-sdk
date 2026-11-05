"""Public manual canary bridge. Default mode inspects only; no cloud API calls."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

NAMESPACE_INIT = """set -e
if [ "$(/usr/bin/readlink /proc/self/ns/net)" = "$7" ]; then exit 1; fi
/usr/sbin/ip link set lo up
exec /usr/bin/setpriv --reuid "$1" --regid "$2" --clear-groups \\
  --inh-caps=-all --ambient-caps=-all --bounding-set=-all --no-new-privs -- \\
  /usr/bin/env -i HOME="$3" PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 \\
  AGENT=claude-code CLAUDE_CONFIG_DIR="$3/.claude" \\
  /usr/bin/python3 -I -B "$4" --phase child --policy "$5" --policy-sha256 "$6"
"""


def shim_module():
    path = Path(__file__).with_name("delivery_shim.py")
    spec = importlib.util.spec_from_file_location("delivery_shim", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["delivery_shim"] = module
    spec.loader.exec_module(module)
    return module


def native_claude() -> tuple[str, str]:
    candidate = shutil.which("claude")
    if not candidate:
        raise ValueError("platform Claude unavailable")
    path = Path(candidate).resolve()
    for member in (path, *path.parents):
        info = member.stat()
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
            raise ValueError("Claude is not platform-owned immutable input")
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("native Claude executable required")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65_536), b""):
            digest.update(block)
    return str(path), digest.hexdigest()


def effective_policy(original: bytes, expected: str, shim) -> tuple[bytes, str]:
    policy = shim.approved_policy(original, expected)
    if policy.get("bind_runtime_paths") is not True or policy.get("capture_platform_claude") is not True:
        raise ValueError("runtime binding not admitted")
    if platform.system() != "Linux" or os.getuid() == 0:
        raise ValueError("non-root Linux worker required")
    # Only measured path/tool fields change. Scope, authority and expected HEAD remain owner supplied.
    policy["checkout"] = str(Path.cwd().resolve())
    if policy.get("bind_checkout_head_from_controller") is True:
        head = os.environ.get("SDK_CANARY_EXPECTED_HEAD", "")
        if not re.fullmatch(r"[0-9a-f]{40}", head):
            raise ValueError("controller branch HEAD binding required")
        policy["checkout_head"] = head
    policy["claude_path"], policy["claude_sha256"] = native_claude()
    data = json.dumps(policy, sort_keys=True).encode()
    return data, hashlib.sha256(data).hexdigest()


def namespace_command(delivery: Path, policy: Path, digest: str) -> list[str]:
    if platform.system() != "Linux" or os.getuid() <= 0:
        raise ValueError("native namespace launch requires non-root Linux")
    for path in (
        "/usr/bin/sudo",
        "/usr/bin/unshare",
        "/usr/bin/python3",
        "/usr/bin/bash",
        "/usr/sbin/ip",
        "/usr/bin/setpriv",
        "/usr/bin/env",
        "/usr/bin/readlink",
    ):
        if not Path(path).is_file() or not os.access(path, os.X_OK):
            raise ValueError("namespace prerequisite absent: " + path)
    return [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/unshare",
        "--net",
        "--fork",
        "--kill-child=KILL",
        "--",
        "/usr/bin/bash",
        "--noprofile",
        "--norc",
        "-c",
        NAMESPACE_INIT,
        "canary-namespace",
        str(os.getuid()),
        str(os.getgid()),
        str(Path.home()),
        str(Path(__file__).resolve()),
        str(policy),
        digest,
        os.readlink("/proc/self/ns/net"),
    ]


def setup(policy_path: Path, expected: str, parent: Path) -> dict:
    shim = shim_module()
    with policy_path.open("rb") as stream:
        original = stream.read(200_001)
    data, digest = effective_policy(original, expected, shim)
    policy = shim.approved_policy(data, digest)
    files = shim.decode(dict(os.environ), policy)
    loaded = shim.load_verified(files)
    adapter = loaded["admission_adapter"]
    facts = adapter.observe(Path(policy["checkout"]))
    admission = adapter.bind(data, digest, facts)
    root = shim.materialise(parent, files)
    receipt = {
        "status": "partial",
        "root": str(root),
        "original_policy_sha256": expected,
        "effective_policy_sha256": digest,
    }
    try:
        descriptor = os.open(root / "effective-policy.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        encoded = json.dumps(admission, sort_keys=True).encode()
        receipt["installation"] = loaded["hosted_bootstrap"].run(
            root, encoded, hashlib.sha256(encoded).hexdigest(), True
        )
        receipt["worker"] = facts
        receipt["status"] = "setup_pass"
    except (ValueError, OSError, KeyError, TypeError):
        receipt["status"] = "setup_failed"
    return receipt


def checked_receipt(path: Path, expected: str, effective_expected: str, shim) -> dict:
    if not path.is_absolute() or path != path.resolve():
        raise ValueError("canonical setup receipt required")
    info = path.stat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or info.st_mode & 0o077
        or info.st_size > 32_768
    ):
        raise ValueError("private owned setup receipt required")
    with path.open("rb") as stream:
        receipt = shim.object_json(stream.read(32_769))
    if (
        receipt.get("status") != "setup_pass"
        or receipt.get("original_policy_sha256") != expected
        or receipt.get("effective_policy_sha256") != effective_expected
    ):
        raise ValueError("setup receipt not bound to launch policy")
    root = Path(receipt["root"])
    if (
        not root.is_absolute()
        or root != root.resolve()
        or root.stat().st_uid != os.getuid()
        or not root.is_dir()
        or root.stat().st_mode & 0o022
    ):
        raise ValueError("invalid setup root")
    with (root / "effective-policy.json").open("rb") as stream:
        shim.approved_policy(stream.read(200_001), effective_expected)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("inspect", "setup", "canary", "child"), default="inspect")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--policy-sha256", required=True)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    result = {}
    try:
        shim = shim_module()
        if args.phase == "inspect":
            with args.policy.open("rb") as stream:
                shim.approved_policy(stream.read(200_001), args.policy_sha256)
            result = {"status": "policy_verified", "executed": False}
        elif args.phase == "setup":
            if args.parent is None or args.receipt is None:
                raise ValueError("explicit owned parent and receipt required")
            if args.receipt.exists() or args.receipt.is_symlink():
                raise ValueError("setup receipt already exists; no automatic retry")
            result = setup(args.policy, args.policy_sha256, args.parent)
            descriptor = os.open(args.receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump(result, stream)
        elif args.phase == "canary":
            if args.receipt is None:
                raise ValueError("setup receipt required")
            with args.policy.open("rb") as stream:
                original = stream.read(200_001)
            _derived, effective_digest = effective_policy(original, args.policy_sha256, shim)
            receipt = checked_receipt(args.receipt, args.policy_sha256, effective_digest, shim)
            root = Path(receipt["root"])
            command = namespace_command(root, root / "effective-policy.json", receipt["effective_policy_sha256"])
            env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "LANG": "C.UTF-8"}
            completed = subprocess.run(command, env=env, timeout=180, check=False)
            result = {
                "status": "canary_pass" if completed.returncode == 0 else "canary_failed",
                "child_exit": completed.returncode,
                "root": str(root),
            }
        else:
            with args.policy.open("rb") as stream:
                data = stream.read(200_001)
            policy = shim.approved_policy(data, args.policy_sha256)
            root = args.policy.parent
            files = {}
            for name, record in policy["files"].items():
                shim.relative(name)
                path = root / name
                if path != path.resolve() or path.stat().st_size > shim.MAX_RAW:
                    raise ValueError("materialised member path or budget")
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise ValueError("regular materialised member required")
                    value = stream.read(shim.MAX_RAW + 1)
                if len(value) != record["size"] or hashlib.sha256(value).hexdigest() != record["sha256"]:
                    raise ValueError("materialised executable changed")
                files[name] = value
            loaded = shim.load_verified(files)
            result = loaded["canary_executor"].execute(root, data, args.policy_sha256, True)
        print(json.dumps(result))
        if result["status"] not in {"policy_verified", "setup_pass", "canary_pass", "pass"}:
            raise SystemExit(1)
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        owned = getattr(error, "root", None) or result.get("root")
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "diagnostic": "platform binding or namespace step failed",
                    "owned_root": str(owned) if owned else None,
                    "partial_materialisation": owned is not None,
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
