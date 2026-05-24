from __future__ import annotations

import shutil
import sys
from pathlib import Path


MANAGED_FOLDER_NAME = "myfile"
TRASH_FOLDER_NAME = "trash"

EXTENSION_GROUPS: dict[str, set[str]] = {
    "Documents": {
        ".doc",
        ".docx",
        ".md",
        ".pdf",
        ".ppt",
        ".pptx",
        ".rtf",
        ".txt",
        ".xls",
        ".xlsx",
    },
    "Images": {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"},
    "Videos": {".avi", ".mkv", ".mov", ".mp4", ".wmv"},
    "Audio": {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"},
    "Archives": {".7z", ".gz", ".rar", ".tar", ".zip"},
    "Applications": {".bat", ".cmd", ".exe", ".msi", ".ps1"},
    "Code": {
        ".c",
        ".cpp",
        ".css",
        ".go",
        ".html",
        ".java",
        ".js",
        ".json",
        ".py",
        ".rs",
        ".ts",
        ".xml",
        ".yaml",
        ".yml",
    },
}

INTERNAL_NAMES = {
    ".git",
    ".venv",
    ".folder_organizer_settings.json",
    ".organize_trash",
    TRASH_FOLDER_NAME,
    "__pycache__",
    "build",
    "dist",
    "src",
    "tests",
}


def get_app_base_folder() -> Path:
    """Return the folder that contains the managed myfile directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def get_managed_folder() -> Path:
    """Return the relative data folder managed by the app."""
    managed_folder = get_app_base_folder() / MANAGED_FOLDER_NAME
    managed_folder.mkdir(exist_ok=True)
    return managed_folder.resolve()


def get_trash_folder() -> Path:
    """Return the single shared trash folder under myfile (not the current browse path)."""
    trash_folder = get_managed_folder() / TRASH_FOLDER_NAME
    trash_folder.mkdir(exist_ok=True)
    _migrate_legacy_trash_folders(trash_folder)
    return trash_folder


def _migrate_legacy_trash_folders(target: Path) -> None:
    root = get_managed_folder()
    legacy_roots = [root / ".organize_trash", *root.rglob(".organize_trash")]
    seen: set[Path] = set()
    for legacy in legacy_roots:
        legacy = legacy.resolve()
        if legacy in seen or not legacy.is_dir():
            continue
        if legacy == target.resolve():
            continue
        seen.add(legacy)
        for item in list(legacy.iterdir()):
            destination = unique_destination(target / item.name)
            shutil.move(str(item), str(destination))
        try:
            legacy.rmdir()
        except OSError:
            pass


def categorize_path(path: Path) -> str:
    if path.is_dir():
        return "Folders"

    suffix = path.suffix.lower()
    for group_name, extensions in EXTENSION_GROUPS.items():
        if suffix in extensions:
            return group_name
    return "Other"


def is_internal_path(path: Path, root: Path) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return True

    if not relative.parts:
        return True

    first_part = relative.parts[0]
    return first_part in INTERNAL_NAMES


def is_running_app_path(path: Path) -> bool:
    return getattr(sys, "frozen", False) and path.resolve() == Path(sys.executable).resolve()


def unique_destination(destination: Path) -> Path:
    if not destination.exists():
        return destination

    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent
    counter = 1

    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
