"""Deterministic in-memory ZIP emission for a locally hardened whole plugin."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path, PurePosixPath
from unicodedata import normalize
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from skills_sdk.core.errors import ContractError
from skills_sdk.models.plugin import PluginCapturedFile
from skills_sdk.models.plugin_build import PluginHardeningReceipt
from skills_sdk.validation.plugin_capture import capture_plugin_source


def _capture(root: Path) -> tuple[tuple[PluginCapturedFile, ...], dict[str, bytes], tuple[str, ...]]:
    try:
        return capture_plugin_source(root)
    except (OSError, ValueError) as exc:
        raise ContractError("plugin_archive_source_invalid", "Plugin source could not be captured safely") from exc


def _zip(files: tuple[PluginCapturedFile, ...], payloads: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED, allowZip64=False) as archive:
        for member in files:
            info = ZipInfo(member.path)
            info.create_system = 3
            info.external_attr = (0o100000 | member.permission_mode) << 16
            archive.writestr(info, payloads[member.path])
    return buffer.getvalue()


def _require_distinct_paths(paths: tuple[str, ...]) -> None:
    seen: set[str] = set()
    for path in paths:
        for component in PurePosixPath(path).parts:
            if component.endswith((".", " ")) or any(char in '<>:"\\|?*' or ord(char) < 32 for char in component):
                raise ContractError("plugin_archive_path_unsupported", "Archive path is not portable on restore")
            stem = component.split(".", 1)[0].rstrip(" ").upper()
            if stem in {"CON", "PRN", "AUX", "NUL"} or (
                stem[:3] in {"COM", "LPT"} and len(stem) == 4 and stem[3] in "123456789¹²³"
            ):
                raise ContractError("plugin_archive_path_unsupported", "Archive path names a reserved device")
        key = normalize("NFC", normalize("NFC", path).casefold())
        if key in seen:
            raise ContractError("plugin_archive_path_collision", "Archive paths collide on portable restore")
        seen.add(key)


def emit_plugin_archive(plugin_root: Path, hardening_receipt: PluginHardeningReceipt) -> bytes:
    """Return portable ZIP bytes bound to a passing receipt's captured files and modes."""
    if not isinstance(plugin_root, Path) or ".." in plugin_root.parts:
        raise ContractError("plugin_archive_source_invalid", "Plugin root requires a safe path")
    try:
        hardening = PluginHardeningReceipt.model_validate(hardening_receipt)
    except ValueError as exc:
        raise ContractError("plugin_archive_hardening_invalid", "Plugin hardening receipt is invalid") from exc
    if hardening.status != "pass":
        raise ContractError("plugin_archive_hardening_required", "A passing plugin hardening receipt is required")

    files, payloads, directories = _capture(plugin_root)
    if files != hardening.fresh_validation.files:
        raise ContractError("plugin_archive_source_changed", "Files or modes differ from the hardened capture")
    implied = {parent.as_posix() for member in files for parent in PurePosixPath(member.path).parents if parent.parts}
    if set(directories) != implied:
        raise ContractError("plugin_archive_directory_unsupported", "Empty directories are outside the file ledger")

    _require_distinct_paths((*directories, *(member.path for member in files)))
    result = _zip(files, payloads)
    after, _, after_directories = _capture(plugin_root)
    if after != files or after_directories != directories:
        raise ContractError("plugin_archive_source_changed", "Plugin source changed during archive emission")
    return result
