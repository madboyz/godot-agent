import io
import tarfile
from pathlib import PurePosixPath
from unittest.mock import patch

import pytest

from godot_knowledge.ingest import filesystem_path
from godot_knowledge.sync import archive_checkout, checkout


def archive_bytes(name, content=b"example", commit="a" * 40):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", pax_headers={"comment": commit}) as archive:
        for parent in reversed(PurePosixPath(name).parents):
            if str(parent) == ".":
                continue
            directory = tarfile.TarInfo(str(parent) + "/")
            directory.type = tarfile.DIRTYPE
            archive.addfile(directory)
        member = tarfile.TarInfo(name)
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
    return buffer.getvalue()


def test_official_archive_commit_and_windows_long_paths(tmp_path):
    name = "godot-4.7.1-stable/" + "/".join(["long-directory"] * 16) + "/example.cpp"
    destination = tmp_path / "candidate" / "sources" / "engine"
    destination.parent.mkdir(parents=True)
    with patch("godot_knowledge.sync.urlopen", return_value=io.BytesIO(archive_bytes(name))):
        commit = archive_checkout("engine", "4.7.1-stable", destination)
    assert commit == "a" * 40
    relative = name.split("/", 1)[1]
    assert filesystem_path(destination / relative).read_bytes() == b"example"
    assert not list((tmp_path / "candidate" / "downloads").rglob("*.tar.gz"))


@pytest.mark.parametrize("name", ["godot-ref/../../escape.cpp", "unexpected-root/file.cpp"])
def test_archive_rejects_paths(tmp_path, name):
    destination = tmp_path / "candidate" / "sources" / "engine"
    destination.parent.mkdir(parents=True)
    with patch("godot_knowledge.sync.urlopen", return_value=io.BytesIO(archive_bytes(name))):
        with pytest.raises(ValueError):
            archive_checkout("engine", "4.7.1-stable", destination)
    assert not destination.exists()


def test_archive_requires_commit_and_git_fallback_is_bounded(tmp_path):
    destination = tmp_path / "candidate" / "sources" / "engine"
    destination.parent.mkdir(parents=True)
    with patch(
        "godot_knowledge.sync.urlopen",
        return_value=io.BytesIO(archive_bytes("godot-ref/file.cpp", commit="")),
    ):
        with pytest.raises(ValueError, match="commit metadata"):
            archive_checkout("engine", "4.7.1-stable", destination)
    with (
        patch("godot_knowledge.sync.archive_checkout", side_effect=OSError("unavailable")),
        patch("godot_knowledge.sync.git_checkout", return_value="b" * 40) as fallback,
    ):
        assert checkout("engine", "4.7.1-stable", destination) == "b" * 40
        fallback.assert_called_once()
