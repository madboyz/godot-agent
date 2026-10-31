import sys

import tomlkit

from godot_knowledge.install import configure, install


def test_configure_preserves_unrelated_settings_and_backup(tmp_path):
    config = tmp_path / "config.toml"
    initial = (
        '# Keep this comment\nmodel = "existing-model"\n[mcp_servers.other]\ncommand = "other"\n'
        '[mcp_servers.godot-knowledge]\ncwd = "old-working-directory"\n'
        'url = "https://example.invalid"\nenabled = false\n'
    )
    config.write_text(initial, encoding="utf-8")
    data = tmp_path / "portable store"
    configure(config, data)
    configure(config, data)
    result = tomlkit.parse(config.read_text(encoding="utf-8"))
    assert result["model"] == "existing-model"
    assert result["mcp_servers"]["other"]["command"] == "other"
    assert result["mcp_servers"]["godot-knowledge"]["tool_timeout_sec"] == 900
    assert result["mcp_servers"]["godot-knowledge"]["args"][-1] == "serve"
    assert result["mcp_servers"]["godot-knowledge"]["command"] == sys.executable
    assert result["mcp_servers"]["godot-knowledge"]["args"][3] == str(data)
    assert "cwd" not in result["mcp_servers"]["godot-knowledge"]
    assert "url" not in result["mcp_servers"]["godot-knowledge"]
    assert result["mcp_servers"]["godot-knowledge"]["enabled"] is False
    assert "# Keep this comment" in config.read_text(encoding="utf-8")
    assert config.with_suffix(".toml.before-godot-knowledge").read_text(encoding="utf-8") == initial


def test_install_uses_configured_locations_and_current_interpreter(tmp_path, monkeypatch):
    home = tmp_path / "other user" / "codex"
    data = tmp_path / "knowledge store"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("GODOT_KNOWLEDGE_DATA", str(data))
    result = install()
    assert result["skill_directory"] == str(home / "skills" / "godot-knowledge")
    skill = home / "skills" / "godot-knowledge" / "SKILL.md"
    assert skill.is_file()
    assert "godot-knowledge status" in skill.read_text(encoding="utf-8")
    config = tomlkit.parse((home / "config.toml").read_text(encoding="utf-8"))
    assert config["mcp_servers"]["godot-knowledge"]["command"] == sys.executable
    assert config["mcp_servers"]["godot-knowledge"]["args"][3] == str(data)


def test_installer_does_not_assume_a_virtualenv_layout(tmp_path):
    for executable in ["custom-python", "/opt/python/bin/python3", "python.exe"]:
        config = tmp_path / executable.replace("/", "_") / "config.toml"
        configure(config, tmp_path / "data", python_executable=executable)
        result = tomlkit.parse(config.read_text(encoding="utf-8"))
        assert result["mcp_servers"]["godot-knowledge"]["command"] == executable
