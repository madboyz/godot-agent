"""Install the packaged Skill and configure the local Codex MCP integration."""

from __future__ import annotations

import os
import sys
import uuid
from importlib.resources import files
from pathlib import Path

import tomlkit

from .paths import codex_directory, data_directory


def configure(config_path: Path, data_root: Path, python_executable: str | None = None) -> None:
    document = (
        tomlkit.parse(config_path.read_text(encoding="utf-8"))
        if config_path.exists()
        else tomlkit.document()
    )
    if "mcp_servers" not in document:
        document["mcp_servers"] = tomlkit.table()
    servers = document["mcp_servers"]
    if "godot-knowledge" not in servers:
        servers["godot-knowledge"] = tomlkit.table()
    server = servers["godot-knowledge"]
    for key in ["cwd", "url", "bearer_token_env_var", "http_headers", "env_http_headers"]:
        server.pop(key, None)
    server["command"] = python_executable or sys.executable
    server["args"] = ["-m", "godot_knowledge.cli", "--data", str(data_root), "serve"]
    server["startup_timeout_sec"] = 30
    server["tool_timeout_sec"] = 900
    config_path.parent.mkdir(parents=True, exist_ok=True)
    backup = config_path.with_suffix(".toml.before-godot-knowledge")
    if config_path.exists() and not backup.exists():
        backup.write_bytes(config_path.read_bytes())
    temporary = config_path.with_name(f".{config_path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(tomlkit.dumps(document), encoding="utf-8", newline="")
    os.replace(temporary, config_path)


def skill_source():
    packaged = files("godot_knowledge").joinpath("bundled_skills", "godot-knowledge")
    if packaged.joinpath("SKILL.md").is_file():
        return packaged
    # Editable installs use the maintained source; wheels carry their own copy.
    checkout = Path(__file__).resolve().parents[2] / "skills" / "godot-knowledge"
    if checkout.joinpath("SKILL.md").is_file():
        return checkout
    raise ValueError("Packaged godot-knowledge Skill is missing; reinstall the Python package")


def copy_skill(source, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            copy_skill(item, target)
        elif item.is_file():
            target.write_bytes(item.read_bytes())


def install(codex_home: str | Path | None = None, data_root: str | Path | None = None) -> dict:
    home = codex_directory(codex_home)
    data = data_directory(data_root)
    skill = home / "skills" / "godot-knowledge"
    copy_skill(skill_source(), skill)
    configure(home / "config.toml", data)
    return {
        "skill_directory": str(skill),
        "config_file": str(home / "config.toml"),
        "data_root": str(data),
        "python_executable": sys.executable,
        "note": "New Codex chats can discover the installed Skill and MCP server.",
    }
