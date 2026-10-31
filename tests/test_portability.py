import os
import shutil
import subprocess
import sys
from datetime import timedelta

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from godot_knowledge.paths import codex_directory, data_directory, engine_executable
from godot_knowledge.store import KnowledgeBase


def test_location_precedence_is_independent_of_working_directory(tmp_path, monkeypatch):
    system_data = tmp_path / "OS user data"
    monkeypatch.setattr("godot_knowledge.paths.user_data_path", lambda *a, **k: system_data)
    monkeypatch.delenv("GODOT_KNOWLEDGE_DATA", raising=False)
    monkeypatch.chdir(tmp_path)
    assert data_directory() == system_data.resolve()
    environment_data = tmp_path / "environment data"
    monkeypatch.setenv("GODOT_KNOWLEDGE_DATA", str(environment_data))
    assert data_directory() == environment_data.resolve()
    assert data_directory(tmp_path / "explicit") == (tmp_path / "explicit").resolve()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    assert codex_directory() == (tmp_path / "codex").resolve()
    assert codex_directory(tmp_path / "override") == (tmp_path / "override").resolve()


def test_engine_discovery_supports_path_env_explicit_and_macos_bundle(tmp_path, monkeypatch):
    executable = tmp_path / "Godot"
    executable.touch()
    monkeypatch.delenv("GODOT_EXECUTABLE", raising=False)
    monkeypatch.setattr(
        "godot_knowledge.paths.shutil.which",
        lambda name: str(executable) if name == "godot4" else None,
    )
    assert engine_executable() == executable.resolve()
    monkeypatch.setenv("GODOT_EXECUTABLE", str(executable))
    assert engine_executable() == executable.resolve()
    bundle = tmp_path / "Godot.app"
    binary = bundle / "Contents" / "MacOS" / "Godot"
    binary.parent.mkdir(parents=True)
    binary.touch()
    assert engine_executable(bundle) == binary.resolve()
    with pytest.raises(ValueError, match="not found"):
        engine_executable(tmp_path / "missing")


def test_copied_store_works_without_original_working_directory(
    make_snapshot, tmp_path, monkeypatch
):
    kb = make_snapshot()
    kb.select_snapshot("a")
    destination = tmp_path / "different machine" / "copied store"
    shutil.copytree(kb.root, destination)
    monkeypatch.chdir(tmp_path)
    relocated = KnowledgeBase(destination)
    result = relocated.get_api("Node", "_ready")
    assert result["results"][0]["source"]["path"] == "local/Node.xml"
    source = relocated.read_source(result["results"][0]["source_id"])
    assert "_ready" in source["content"]
    assert relocated.get_topic("线程")["manual_evidence"]


async def test_cli_and_direct_mcp_share_environment_store(make_snapshot, tmp_path):
    kb = make_snapshot()
    kb.select_snapshot("a")
    environment = {**os.environ, "GODOT_KNOWLEDGE_DATA": str(kb.root)}
    command = subprocess.run(
        [sys.executable, "-m", "godot_knowledge.cli", "status"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        check=True,
        encoding="utf-8",
    )
    import json

    assert json.loads(command.stdout)["default_snapshot"] == "a"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from godot_knowledge.server import create_server; create_server().run()"],
        cwd=str(tmp_path),
        env={"GODOT_KNOWLEDGE_DATA": str(kb.root)},
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as client:
            await client.initialize()
            result = await client.call_tool("status")
            assert result.structuredContent["data_root"] == str(kb.root)
            assert result.structuredContent["default_snapshot"] == "a"
