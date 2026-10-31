"""Resolve machine-local settings without depending on the source checkout."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from platformdirs import user_data_path


def data_directory(explicit: str | Path | None = None) -> Path:
    configured = explicit if explicit is not None else os.environ.get("GODOT_KNOWLEDGE_DATA")
    if configured is not None:
        if not str(configured).strip():
            raise ValueError("The data directory cannot be empty")
        return Path(configured).expanduser().resolve()
    return user_data_path("godot-knowledge", appauthor=False).resolve()


def codex_directory(explicit: str | Path | None = None) -> Path:
    configured = explicit if explicit is not None else os.environ.get("CODEX_HOME")
    return (Path(configured).expanduser() if configured else Path.home() / ".codex").resolve()


def engine_executable(explicit: str | Path | None = None) -> Path:
    configured = explicit if explicit is not None else os.environ.get("GODOT_EXECUTABLE")
    if configured:
        value = str(Path(configured).expanduser())
        located = shutil.which(value)
        path = Path(located or value).resolve()
        if path.is_dir() and path.suffix.casefold() == ".app":
            path = path / "Contents" / "MacOS" / "Godot"
        if path.is_file():
            return path
        raise ValueError("Godot executable not found; check --engine or GODOT_EXECUTABLE")
    for name in ["godot", "godot4"]:
        if located := shutil.which(name):
            return Path(located).resolve()
    raise ValueError("Godot not found; supply --engine, set GODOT_EXECUTABLE, or add Godot to PATH")
