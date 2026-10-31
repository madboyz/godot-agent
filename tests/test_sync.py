import json
import sys
import time
from unittest.mock import patch

import pytest
from conftest import NODE_XML

from godot_knowledge.sync import publish, run, sync_lock, sync_sources

VERSION = "4.7.1.stable.official.a13da4feb"


def fake_engine(args, cwd=None, timeout=120):
    if "--version" in args:
        return VERSION
    if "--dump-extension-api-with-docs" in args:
        (cwd / "extension_api.json").write_text(
            json.dumps(
                {
                    "header": {
                        "version_major": 4,
                        "version_minor": 7,
                        "version_patch": 1,
                        "version_status": "stable",
                    },
                }
            ),
            encoding="utf-8",
        )
    if "--doctool" in args:
        (cwd / "Node.xml").write_text(NODE_XML, encoding="utf-8")
    return ""


def test_offline_sync_and_failures_preserve_active(make_snapshot, tmp_path):
    kb = make_snapshot()
    kb.select_snapshot("a")
    executable = tmp_path / "godot.exe"
    executable.touch()
    with patch("godot_knowledge.sync.run", side_effect=fake_engine):
        result = sync_sources(kb, str(executable), offline=True)
    assert result["coverage"]["local_api"]
    assert not result["coverage"]["manuals"]
    assert kb.status()["default_snapshot"] == "a"
    with (
        patch("godot_knowledge.sync.run", side_effect=fake_engine),
        patch("godot_knowledge.sync.checkout", side_effect=RuntimeError("network disconnected")),
    ):
        with pytest.raises(RuntimeError, match="network disconnected"):
            sync_sources(kb, str(executable))
    assert kb.status()["default_snapshot"] == "a"
    assert kb.get_api("Node")["confirmation"] == "source_found"
    assert not (kb.root / "sync.lock").exists()


def test_source_commit_mismatch_excluded(make_snapshot, tmp_path):
    kb = make_snapshot()
    executable = tmp_path / "godot.exe"
    executable.touch()

    def wrong_checkout(kind, ref, destination):
        destination.mkdir()
        if kind == "engine":
            (destination / "Untrusted.xml").write_text(NODE_XML, encoding="utf-8")
        return "badbadbad00000000000000000000000000000000"

    with (
        patch("godot_knowledge.sync.run", side_effect=fake_engine),
        patch("godot_knowledge.sync.checkout", side_effect=wrong_checkout),
    ):
        result = sync_sources(kb, str(executable), allow_partial=True)
    assert not result["coverage"]["engine_source"]
    assert "does not match executable" in result["coverage"]["gaps"][0]
    assert "engine" not in kb.manifest(result["id"])["sources"]
    assert all(
        not path.startswith("engine/") for path in kb.manifest(result["id"])["index"]["files"]
    )


def test_partial_network_failure_and_ref_validation(make_snapshot, tmp_path):
    kb = make_snapshot()
    executable = tmp_path / "godot.exe"
    executable.touch()
    with (
        patch("godot_knowledge.sync.run", side_effect=fake_engine),
        patch("godot_knowledge.sync.checkout", side_effect=RuntimeError("offline")),
    ):
        result = sync_sources(kb, str(executable), allow_partial=True)
        assert len(result["coverage"]["gaps"]) == 2
        with pytest.raises(ValueError, match="Docs ref"):
            sync_sources(kb, str(executable), docs_ref="master")
        with pytest.raises(ValueError, match="Source ref"):
            sync_sources(kb, str(executable), source_ref="4.6-stable")


def test_interrupted_publication_is_not_visible(make_snapshot, monkeypatch):
    kb = make_snapshot()
    kb.select_snapshot("a")
    candidate = kb.root / "staging" / "interrupted"
    candidate.mkdir()
    with patch("godot_knowledge.sync.build_index", side_effect=RuntimeError("interrupted")):
        with pytest.raises(RuntimeError):
            publish(kb.root, candidate, {"id": "interrupted"})
    assert len(kb.status()["snapshots"]) == 1
    assert kb.status()["default_snapshot"] == "a"
    with pytest.raises(ValueError):
        kb.select_snapshot("interrupted")


def test_sync_lock_releases_on_interrupt(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        with sync_lock(tmp_path):
            with pytest.raises(ValueError, match="Another sync"):
                with sync_lock(tmp_path):
                    pass
            raise KeyboardInterrupt()
    assert not (tmp_path / "sync.lock").exists()


def test_subprocess_timeout_stops_its_process(tmp_path):
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="timed out"):
        run([sys.executable, "-c", "import time; time.sleep(60)"], cwd=tmp_path, timeout=1)
    assert time.monotonic() - start < 10
