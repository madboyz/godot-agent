"""Verify the wheel from an isolated environment outside the source checkout."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path


def command(arguments, cwd):
    result = subprocess.run(
        arguments,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if result.returncode:
        raise RuntimeError(f"Package verification failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


def verify(wheel: Path, store: Path | None = None) -> None:
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("Package verification requires uv")
    with tempfile.TemporaryDirectory(prefix="godot-knowledge-package-") as temporary:
        directory = Path(temporary).resolve()
        environment = directory / "isolated environment"
        command([uv, "venv", "--python", sys.executable, str(environment)], directory)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        command([uv, "pip", "install", "--python", str(python), str(wheel)], directory)
        launcher = [str(python), "-I", "-m", "godot_knowledge.cli"]
        data = directory / "knowledge store"
        status = json.loads(command([*launcher, "--data", str(data), "status"], directory))
        assert Path(status["data_root"]) == data
        assert status["default_snapshot"] is None
        codex_home = directory / "codex user"
        command(
            [*launcher, "--data", str(data), "install", "--codex-home", str(codex_home)], directory
        )
        skill = codex_home / "skills" / "godot-knowledge" / "SKILL.md"
        assert skill.is_file()
        settings = tomllib.loads((codex_home / "config.toml").read_text(encoding="utf-8"))
        registered = settings["mcp_servers"]["godot-knowledge"]
        assert Path(registered["command"]) == python
        assert Path(registered["args"][3]) == data
        assert "godot-knowledge status" in skill.read_text(encoding="utf-8")
        if store:
            result = json.loads(
                command(
                    [
                        *launcher,
                        "--data",
                        str(store),
                        "query",
                        "get_api",
                        "--json",
                        '{"class_name":"Node","member":"_ready"}',
                    ],
                    directory,
                )
            )
            assert result["confirmation"] == "source_found"
            assert result["results"][0]["description"]
        print(
            "Wheel verification passed: isolated install, external working directory, bundled Skill."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--store", type=Path)
    args = parser.parse_args()
    wheel = args.wheel or next(Path("dist").glob("*.whl"))
    verify(wheel.resolve(), args.store.resolve() if args.store else None)
