"""Build candidates without mutating any published snapshot or default pointer."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tarfile
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .ingest import filesystem_path
from .paths import engine_executable as resolve_engine
from .store import KnowledgeBase, build_index, dump_json, snapshot_id

UPSTREAMS = {
    "engine": "https://github.com/godotengine/godot.git",
    "docs": "https://github.com/godotengine/godot-docs.git",
}


def run(args: list[str], cwd: Path | None = None, timeout: int = 120) -> str:
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    with subprocess.Popen(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        start_new_session=os.name != "nt",
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.kill()
            process.communicate(timeout=10)
            raise RuntimeError(f"Command timed out after {timeout}s: {args[0]}") from error
    if process.returncode:
        raise RuntimeError(
            f"Command failed ({process.returncode}): {args[0]}\n{(stderr or stdout)[-2000:]}"
        )
    return stdout.strip()


@contextmanager
def sync_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "sync.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as error:
        raise ValueError(
            "Another sync is running, or an interrupted process left data/sync.lock. "
            "Check that no sync process is running before removing the stale lock."
        ) from error
    try:
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def archive_filter(member: tarfile.TarInfo, destination: str) -> tarfile.TarInfo:
    filtered = tarfile.data_filter(member, destination)
    # tarfile normalizes file paths, but its deferred directory metadata pass does not.
    if os.name == "nt" and filtered.isdir():
        filtered = filtered.replace(name=str(Path(filtered.name)))
    return filtered


def archive_checkout(kind: str, ref: str, destination: Path) -> str:
    repository = "godot" if kind == "engine" else "godot-docs"
    headers = {"User-Agent": "godot-knowledge/0.1"}
    download_root = destination.parent.parent / "downloads" / kind
    download_root.mkdir(parents=True)
    archive_path = download_root / "source.tar.gz"
    archive_url = (
        f"https://codeload.github.com/godotengine/{repository}/tar.gz/{quote(ref, safe='')}"
    )
    deadline = time.monotonic() + 180
    with (
        urlopen(Request(archive_url, headers=headers), timeout=30) as response,
        archive_path.open("wb") as output,
    ):
        size = 0
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > 512 * 1024 * 1024 or time.monotonic() > deadline:
                raise RuntimeError("Official archive exceeded download size/time limit")
            output.write(chunk)
    with tarfile.open(archive_path) as archive:
        # Git archive stores the resolved commit in the global PAX header.
        commit = archive.pax_headers.get("comment", "").strip()
        if not re.fullmatch(r"[a-f0-9]{40}", commit):
            raise ValueError("Official archive has no verifiable commit metadata")
        members = archive.getmembers()
        roots = {member.name.split("/")[0] for member in members}
        if len(roots) != 1:
            raise ValueError("Archive must contain one repository root")
        expected_root = roots.pop()
        if not expected_root.startswith(f"{repository}-"):
            raise ValueError("Unexpected archive repository root")
        if sum(member.size for member in members) > 2 * 1024**3:
            raise ValueError("Archive expanded size exceeds limit")
        if any(
            ".." in Path(member.name).parts
            or (not member.name.startswith(expected_root + "/") and member.name != expected_root)
            for member in members
        ):
            raise ValueError("Archive contains unexpected root paths")
        archive.extractall(filesystem_path(download_root), filter=archive_filter)
    extracted = (download_root / expected_root).resolve()
    if not extracted.is_relative_to(download_root.resolve()) or not extracted.is_dir():
        raise ValueError("Invalid archive source directory")
    os.replace(extracted, destination)
    archive_path.unlink()
    return commit


def git_checkout(kind: str, ref: str, destination: Path) -> str:
    destination.mkdir(parents=True)
    run(["git", "init", "--quiet", str(destination)])
    run(["git", "-C", str(destination), "remote", "add", "origin", UPSTREAMS[kind]])
    run(
        [
            "git",
            "-c",
            "http.connectTimeout=15",
            "-c",
            "http.lowSpeedLimit=1000",
            "-c",
            "http.lowSpeedTime=20",
            "-C",
            str(destination),
            "fetch",
            "--depth=1",
            "origin",
            ref,
        ],
        timeout=180,
    )
    commit = run(["git", "-C", str(destination), "rev-parse", "FETCH_HEAD"])
    run(["git", "-C", str(destination), "checkout", "--quiet", "--detach", commit])
    return commit


def checkout(kind: str, ref: str, destination: Path) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", ref) or ".." in ref:
        raise ValueError("Invalid Git ref")
    try:
        return archive_checkout(kind, ref, destination)
    except (OSError, URLError, ValueError, KeyError, tarfile.TarError, RuntimeError) as error:
        archive_error = str(error)
        logging.getLogger(__name__).warning(
            "Official archive acquisition failed for %s: %s; trying Git", kind, archive_error
        )
    try:
        return git_checkout(kind, ref, destination)
    except (OSError, RuntimeError) as error:
        raise RuntimeError(f"Archive: {archive_error}; Git: {error}") from error


def publish(root: Path, candidate: Path, manifest: dict) -> dict:
    identifier = snapshot_id(manifest["id"])
    if not candidate.resolve().is_relative_to((root / "staging").resolve()):
        raise ValueError("Candidate directory is outside the staging area")
    destination = root / "snapshots" / identifier
    if not destination.resolve().is_relative_to((root / "snapshots").resolve()):
        raise ValueError("Snapshot destination is outside the snapshot area")
    manifest["index"] = build_index(candidate)
    manifest["indexed_at"] = datetime.now(UTC).isoformat()
    dump_json(candidate / "manifest.json", manifest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(candidate, destination)
    return {key: value for key, value in manifest.items() if key != "index"} | {
        "index": {key: value for key, value in manifest["index"].items() if key != "files"}
    }


def reindex_snapshot(kb: KnowledgeBase, snapshot: str) -> dict:
    manifest = kb.manifest(snapshot)
    source = kb.directory(snapshot) / "sources"
    with sync_lock(kb.root):
        identifier = f"reindex-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
        candidate = kb.root / "staging" / identifier
        candidate.mkdir(parents=True)
        manifest = {**manifest, "id": identifier, "reindexed_from": snapshot}
        try:
            shutil.copytree(
                filesystem_path(source),
                filesystem_path(candidate / "sources"),
                ignore=shutil.ignore_patterns(".git"),
            )
            return publish(kb.root, candidate, manifest)
        except Exception as error:
            dump_json(candidate / "failure.json", {"error": str(error), "manifest": manifest})
            raise


def sync_sources(
    kb: KnowledgeBase,
    engine_executable: str | None = None,
    source_ref: str | None = None,
    docs_ref: str | None = None,
    offline: bool = False,
    allow_partial: bool = False,
) -> dict:
    engine = resolve_engine(engine_executable)
    version_output = run([str(engine), "--headless", "--version"], timeout=30)
    version = version_output.splitlines()[-1]
    match = re.fullmatch(
        r"(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?"
        r"\.(?P<channel>[A-Za-z0-9]+)\.(?P<build>[A-Za-z0-9]+)\.(?P<hash>[a-f0-9]+)",
        version,
    )
    if not match:
        raise ValueError(f"Unrecognized Godot version: {version!r}")
    numbers = ".".join(
        part for part in [match["major"], match["minor"], match["patch"]] if part is not None
    )
    expected_ref = f"{numbers}-{match['channel']}"
    source_ref = source_ref or expected_ref
    docs_ref = docs_ref or f"{match['major']}.{match['minor']}"
    if docs_ref != f"{match['major']}.{match['minor']}":
        raise ValueError(
            "Docs ref must match the engine major.minor branch; master is not a baseline"
        )
    if source_ref != expected_ref and not re.fullmatch(r"[a-f0-9]{7,40}", source_ref):
        raise ValueError(f"Source ref must be {expected_ref!r} or an exact matching commit")
    with sync_lock(kb.root):
        now = datetime.now(UTC)
        identifier = f"{numbers}-{match['channel']}-{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
        candidate = kb.root / "staging" / identifier
        local = candidate / "sources" / "local"
        local.mkdir(parents=True)
        manifest = {
            "id": identifier,
            "schema_version": 1,
            "engine_version": version,
            "engine_executable": str(engine),
            "engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
            "collected_at": now.isoformat(),
            "sources": {},
            "coverage": {
                "local_api": False,
                "engine_source": False,
                "manuals": False,
                "gaps": [],
            },
        }
        try:
            run(
                [
                    str(engine),
                    "--headless",
                    "--path",
                    str(local),
                    "--dump-extension-api-with-docs",
                    "--quit",
                ],
                cwd=local,
            )
            run(
                [
                    str(engine),
                    "--headless",
                    "--path",
                    str(local),
                    "--doctool",
                    str(local),
                    "--quit",
                ],
                cwd=local,
            )
            api = json.loads((local / "extension_api.json").read_text(encoding="utf-8"))
            header = api["header"]
            if (
                header["version_major"] != int(match["major"])
                or header["version_minor"] != int(match["minor"])
                or header["version_patch"] != int(match["patch"] or 0)
                or header.get("version_status") != match["channel"]
            ):
                raise ValueError("Exported API version does not match executable version")
            if not list(local.rglob("*.xml")):
                raise ValueError("Godot exported no XML class references")
            manifest["coverage"]["local_api"] = True
            manifest["sources"]["local"] = {"version": version, "kind": "engine_export"}
            for kind, ref in [("engine", source_ref), ("docs", docs_ref)]:
                if offline:
                    manifest["coverage"]["gaps"].append(f"{kind}: skipped in offline mode")
                    continue
                destination = candidate / "sources" / kind
                try:
                    commit = checkout(kind, ref, destination)
                    if kind == "engine" and not commit.startswith(match["hash"]):
                        raise ValueError(
                            f"Source commit {commit} does not match executable hash {match['hash']}"
                        )
                    manifest["sources"][kind] = {
                        "repository": UPSTREAMS[kind],
                        "ref": ref,
                        "commit": commit,
                        "version_scope": "exact_engine_commit"
                        if kind == "engine"
                        else "minor_branch",
                    }
                    manifest["coverage"]["engine_source" if kind == "engine" else "manuals"] = True
                except (RuntimeError, ValueError) as error:
                    # Failed checkouts must never be ingested as trusted evidence.
                    if destination.exists():
                        os.replace(destination, candidate / f"rejected-{kind}")
                    if not allow_partial:
                        raise
                    manifest["coverage"]["gaps"].append(f"{kind}: {error}")
            return publish(kb.root, candidate, manifest)
        except Exception as error:
            dump_json(candidate / "failure.json", {"error": str(error), "manifest": manifest})
            raise
