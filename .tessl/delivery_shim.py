"""Public bounded delivery primitive. No private values are logged or exported."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath
from types import ModuleType

CHUNK = 16_384
MAX_CHUNKS = 128
MAX_RAW = 1_500_000


class MaterialisationError(ValueError):
    def __init__(self, root: Path) -> None:
        super().__init__("partial owned delivery preserved")
        self.root = root


def object_json(data: bytes) -> dict:
    def pairs(items: list) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON member")
            result[key] = value
        return result

    value = json.loads(data, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def relative(name: str) -> str:
    if (
        not isinstance(name, str)
        or not name
        or "\\" in name
        or any(ord(char) < 32 for char in name)
        or PurePosixPath(name).is_absolute()
        or any(part in ("", ".", "..", ".git") for part in name.split("/"))
    ):
        raise ValueError("unsafe delivery path")
    return name


def decode(environment: dict, policy: dict) -> dict[str, bytes]:
    """Verify approved outer digest and all member bytes before materialisation."""
    count = policy["chunk_count"]
    records = policy["files"]
    if type(count) is not int or not 1 <= count <= MAX_CHUNKS or not isinstance(records, dict) or not records:
        raise ValueError("delivery shape")
    keys = {f"SDK_CANARY_CHUNK_{index:03d}" for index in range(count)}
    if {key for key in environment if key.startswith("SDK_CANARY_CHUNK_")} != keys:
        raise ValueError("missing or extra delivery chunk")
    chunks = [environment[f"SDK_CANARY_CHUNK_{index:03d}"] for index in range(count)]
    if any(not isinstance(value, str) or not 0 < len(value) <= CHUNK for value in chunks):
        raise ValueError("delivery chunk budget")
    joined = "".join(chunks).encode("ascii")
    if hashlib.sha256(joined).hexdigest() != policy["delivery_sha256"]:
        raise ValueError("delivery digest mismatch")
    raw = base64.b64decode(joined, validate=True)
    if len(raw) > MAX_RAW:
        raise ValueError("delivery aggregate budget")
    encoded = object_json(raw)
    if set(encoded) != set(records):
        raise ValueError("delivery membership mismatch")
    files = {}
    total = 0
    for name, record in records.items():
        relative(name)
        if not isinstance(record, dict) or set(record) != {"sha256", "size"}:
            raise ValueError("member record shape")
        if type(record["size"]) is not int or not 0 <= record["size"] <= MAX_RAW:
            raise ValueError("member budget")
        total += record["size"]
        if total > MAX_RAW or not isinstance(encoded[name], str) or len(encoded[name]) > 2 * MAX_RAW:
            raise ValueError("member aggregate budget")
        value = base64.b64decode(encoded[name], validate=True)
        if len(value) != record["size"] or hashlib.sha256(value).hexdigest() != record["sha256"]:
            raise ValueError("delivery member mismatch")
        files[name] = value
    return files


def materialise(parent: Path, files: dict[str, bytes]) -> Path:
    """Create one fresh owned root; never overwrite or remove caller files."""
    if not parent.is_absolute() or parent != parent.resolve():
        raise ValueError("unlinked delivery parent required")
    info = parent.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise ValueError("owner-controlled delivery parent required")
    for name in files:
        relative(name)
    root = Path(tempfile.mkdtemp(prefix="sdk-canary-delivery-", dir=parent))
    try:
        for name, data in files.items():
            path = root / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
    except (OSError, ValueError) as error:
        raise MaterialisationError(root) from error
    return root


def approved_policy(data: bytes, digest: str) -> dict:
    if len(data) > 200_000 or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("policy budget or digest shape")
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("policy digest mismatch")
    value = object_json(data)
    if value.get("schema_version") != 1 or value.get("export_authorised") is not True:
        raise ValueError("delivery not admitted")
    return value


def load_verified(files: dict[str, bytes]) -> dict[str, ModuleType]:
    """Load only exact delivery-verified bytes, never reopen executable paths."""
    result = {}
    sys.modules["delivery_shim"] = sys.modules[__name__]
    for name in ("hosted_bootstrap", "admission_adapter", "native_controls", "canary_executor"):
        module = ModuleType(name)
        module.__file__ = name + ".py"
        sys.modules[name] = module
        exec(compile(files[name + ".py"], name + ".py", "exec"), module.__dict__)
        result[name] = module
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--policy-sha256", required=True)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--materialise", action="store_true")
    parser.add_argument("--install-controls", action="store_true")
    parser.add_argument("--execute-canary", action="store_true")
    args = parser.parse_args()
    root = None
    try:
        with args.policy.open("rb") as stream:
            policy_data = stream.read(200_001)
            policy = approved_policy(policy_data, args.policy_sha256)
        files = decode(dict(os.environ), policy)
        result = {"status": "delivery_verified", "members": len(files), "written": False}
        if args.install_controls or args.execute_canary:
            if policy.get("installation_authorised") is not True or policy.get("exclusive_config_custody") is not True:
                raise ValueError("installation not admitted")
            loaded = load_verified(files)
            adapter = loaded["admission_adapter"]
            facts = adapter.observe(Path(policy["checkout"]))
            admission = adapter.bind(policy_data, args.policy_sha256, facts)
        if args.materialise or args.install_controls or args.execute_canary:
            if args.parent is None:
                raise ValueError("explicit delivery parent required")
            root = materialise(args.parent, files)
            result.update(root=str(root), written=True)
            if args.install_controls or args.execute_canary:
                encoded = json.dumps(admission, sort_keys=True).encode()
                result["worker_receipt"] = adapter.receipt(policy_data, facts, admission)
                if args.install_controls:
                    result["installation"] = loaded["hosted_bootstrap"].run(
                        root, encoded, hashlib.sha256(encoded).hexdigest(), True
                    )
                if args.execute_canary:
                    result["canary"] = loaded["canary_executor"].execute(root, policy_data, args.policy_sha256, True)
                    if result["canary"]["status"] != "pass":
                        print(json.dumps(result))
                        raise SystemExit(1)
        print(json.dumps(result))
    except (ValueError, OSError, KeyError, TypeError) as error:
        owned = getattr(error, "root", root)
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "diagnostic": "delivery policy, input or destination rejected",
                    "owned_root": str(owned) if owned else None,
                    "partial_materialisation": owned is not None,
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
