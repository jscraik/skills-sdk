from __future__ import annotations

import subprocess
import sys


def test_validation_public_import_does_not_depend_on_packaging_import_order() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "from skills_sdk.validation import validate_skill_package"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_packaging_public_import_does_not_depend_on_validation_import_order() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "from skills_sdk.packaging import build_skill_package"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
