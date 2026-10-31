"""Immutable snapshot indexes and bounded, source-backed queries."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

from .ingest import collect, filesystem_path
from .topics import TOPICS, expand_query, topic_names


def dump_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def snapshot_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", value):
        raise ValueError("Invalid snapshot identifier")
    return value


def build_index(directory: Path) -> dict:
    records = collect(directory / "sources")
    if not any(record["kind"] == "class" for record in records):
        raise ValueError("Snapshot has no API classes; publication refused")
    with closing(sqlite3.connect(directory / "index.sqlite")) as db, db:
        db.executescript("""
            CREATE TABLE records (
                id TEXT PRIMARY KEY, kind TEXT, owner TEXT, name TEXT,
                title TEXT, signature TEXT, description TEXT, path TEXT,
                line_start INTEGER, line_end INTEGER, payload TEXT
            );
            CREATE INDEX by_api ON records(owner, name, kind);
            CREATE VIRTUAL TABLE fulltext USING fts5(title, signature, description, topics);
        """)
        counts: dict[str, int] = {}
        for index, record in enumerate(records):
            record["id"] = hashlib.sha256(
                f"{record['path']}:{record['line_start']}:{index}".encode()
            ).hexdigest()[:20]
            db.execute(
                "INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record["id"],
                    record["kind"],
                    record["owner"],
                    record["name"],
                    record["title"],
                    record["signature"],
                    record["description"],
                    record["path"],
                    record["line_start"],
                    record["line_end"],
                    json.dumps(record, ensure_ascii=False),
                ),
            )
            rowid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute(
                "INSERT INTO fulltext(rowid,title,signature,description,topics) VALUES (?,?,?,?,?)",
                (
                    rowid,
                    record["title"],
                    record["signature"],
                    record["description"],
                    " ".join(record["topics"]),
                ),
            )
            counts[record["kind"]] = counts.get(record["kind"], 0) + 1
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("SQLite validation failed")
        db.execute("INSERT INTO fulltext(fulltext) VALUES ('integrity-check')")
    files = {}
    source_root = filesystem_path(directory / "sources")
    for path in source_root.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            files[path.relative_to(source_root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return {"counts": counts, "files": files, "total_records": len(records)}


class KnowledgeBase:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def directory(self, snapshot: str | None = None) -> Path:
        if snapshot is None:
            pointer = self.root / "active.json"
            if not pointer.exists():
                raise ValueError("No default snapshot. Run sync, then select_snapshot.")
            snapshot = json.loads(pointer.read_text(encoding="utf-8"))["snapshot"]
        directory = self.root / "snapshots" / snapshot_id(snapshot)
        if not (directory / "manifest.json").is_file():
            raise ValueError(f"Unknown or incomplete snapshot: {snapshot}")
        return directory

    def manifest(self, snapshot: str | None = None) -> dict:
        return json.loads((self.directory(snapshot) / "manifest.json").read_text(encoding="utf-8"))

    @contextmanager
    def connection(self, snapshot: str | None = None):
        db = sqlite3.connect(
            (self.directory(snapshot) / "index.sqlite").as_uri() + "?mode=ro", uri=True
        )
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    def envelope(self, snapshot: str | None, **data) -> dict:
        manifest = self.manifest(snapshot)
        return {
            "snapshot": manifest["id"],
            "engine_version": manifest["engine_version"],
            "coverage": manifest["coverage"],
            **data,
        }

    def status(self) -> dict:
        snapshots = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((self.root / "snapshots").glob("*/manifest.json"))
        ]
        active = self.root / "active.json"
        return {
            "data_root": str(self.root),
            "default_snapshot": json.loads(active.read_text(encoding="utf-8"))["snapshot"]
            if active.exists()
            else None,
            "snapshots": [
                {
                    **manifest,
                    "index": {
                        key: value for key, value in manifest["index"].items() if key != "files"
                    },
                }
                for manifest in snapshots[-50:]
            ],
            "incomplete_candidates": len(list((self.root / "staging").glob("*"))),
            "sync_in_progress": (self.root / "sync.lock").exists(),
        }

    def select_snapshot(self, snapshot: str) -> dict:
        manifest = self.manifest(snapshot)
        with self.connection(snapshot) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Snapshot integrity check failed")
        dump_json(self.root / "active.json", {"snapshot": manifest["id"]})
        return {"default_snapshot": manifest["id"], "engine_version": manifest["engine_version"]}

    @staticmethod
    def present(row: sqlite3.Row, description_limit: int = 1600) -> dict:
        record = json.loads(row["payload"])
        description = record["description"]
        return {
            "source_id": record["id"],
            "kind": record["kind"],
            "title": record["title"],
            "owner": record["owner"],
            "name": record["name"],
            "inherits": record["inherits"],
            "signature": record["signature"],
            "description": description[:description_limit],
            "description_truncated": len(description) > description_limit,
            "availability": record.get("availability"),
            "description_source": record.get("documentation_source"),
            "deprecated": record["deprecated"],
            "experimental": record["experimental"],
            "details": {
                key: value for key, value in record["details"].items() if key != "binding_metadata"
            },
            "topics": record["topics"],
            "source": {
                "path": record["path"],
                "line_start": record["line_start"],
                "line_end": record["line_end"],
                "evidence": record["evidence"],
                "json_class": record["owner"] if "binding_metadata" in record["details"] else None,
            },
        }

    def search(
        self,
        query: str,
        snapshot: str | None = None,
        topic: str | None = None,
        kind: str | None = None,
        limit: int = 10,
    ) -> dict:
        snapshot = self.directory(snapshot).name
        if not query.strip():
            raise ValueError("Query cannot be empty")
        if len(query) > 1000:
            raise ValueError("Query exceeds 1000 characters")
        limit = max(1, min(limit, 30))
        terms = expand_query(query)
        if not terms:
            return self.envelope(snapshot, results=[], confirmation="unconfirmed")
        match = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
        filters = []
        params: list = [match]
        if kind:
            filters.append("r.kind = ?")
            params.append(kind)
        if topic:
            if topic not in TOPICS:
                raise ValueError(f"Unknown topic; choose from {list(TOPICS)}")
            filters.append("f.topics MATCH ?")
            params.append(f'"{topic}"')
        where = " AND " + " AND ".join(filters) if filters else ""
        params.extend([query, limit])
        with self.connection(snapshot) as db:
            rows = db.execute(
                "SELECT r.* FROM fulltext f JOIN records r ON r.rowid=f.rowid "
                f"WHERE fulltext MATCH ? {where} "
                "ORDER BY CASE WHEN r.title = ? COLLATE NOCASE THEN 0 ELSE 1 END,"
                "bm25(fulltext, 8, 4, 1, 1) LIMIT ?",
                params,
            ).fetchall()
        return self.envelope(
            snapshot,
            query=query,
            expanded_terms=terms,
            results=[self.present(row) for row in rows],
            confirmation="source_found" if rows else "unconfirmed",
        )

    def get_api(
        self,
        class_name: str,
        member: str | None = None,
        snapshot: str | None = None,
        include_inherited: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        snapshot = self.directory(snapshot).name
        limit, offset = max(1, min(limit, 100)), max(0, offset)
        if not class_name or len(class_name) > 200:
            raise ValueError("Supply an exact API class name")
        lineage, rows, seen = [], [], set()
        with self.connection(snapshot) as db:
            owner = class_name
            while owner and owner not in seen:
                seen.add(owner)
                cls = db.execute(
                    "SELECT * FROM records WHERE owner=? AND kind='class'", (owner,)
                ).fetchone()
                if cls is None:
                    break
                lineage.append(self.present(cls, 2500))
                if member is None:
                    rows.extend(
                        db.execute(
                            "SELECT * FROM records WHERE owner=? AND kind!='class' ORDER BY rowid",
                            (owner,),
                        ).fetchall()
                    )
                else:
                    rows.extend(
                        db.execute(
                            "SELECT * FROM records WHERE owner=? AND name=? AND kind!='class' ORDER BY rowid",
                            (owner, member),
                        ).fetchall()
                    )
                if not include_inherited:
                    break
                owner = json.loads(cls["payload"])["inherits"]
        # Child declarations override base declarations; overloads within one owner stay intact.
        selected, declarations = [], {}
        for row in rows:
            key = (row["kind"], row["name"])
            if key not in declarations:
                declarations[key] = row["owner"]
            if declarations[key] == row["owner"]:
                selected.append(row)
        return self.envelope(
            snapshot,
            class_name=class_name,
            member=member,
            lineage=lineage,
            results=[self.present(row) for row in selected[offset : offset + limit]],
            total=len(selected),
            next_offset=offset + limit if offset + limit < len(selected) else None,
            confirmation="source_found"
            if lineage and (member is None or selected)
            else "unconfirmed",
        )

    def get_topic(self, topic: str, snapshot: str | None = None, limit: int = 10) -> dict:
        snapshot = self.directory(snapshot).name
        names = [topic] if topic in TOPICS else topic_names(topic)
        if not names:
            raise ValueError(f"Unknown topic; choose from {list(TOPICS)}")
        name = names[0]
        manuals = self.search(
            " ".join(TOPICS[name]["terms"]),
            snapshot,
            topic=name,
            kind="manual",
            limit=30,
        )
        apis = self.search(" ".join(TOPICS[name]["terms"]), snapshot, kind="class", limit=5)
        terms = TOPICS[name]["terms"]
        with self.connection(snapshot) as db:
            rows = db.execute(
                "SELECT * FROM records WHERE kind='class' AND name IN ("
                + ",".join("?" for _ in terms)
                + ")",
                terms,
            ).fetchall()
        exact = {row["name"]: self.present(row) for row in rows}
        related = [exact[term] for term in terms if term in exact]
        related.extend(entry for entry in apis["results"] if entry["name"] not in exact)
        evidence = [
            entry for entry in manuals["results"] if len(entry["description"].strip()) >= 80
        ][: max(1, min(limit, 20))]
        return self.envelope(
            snapshot,
            topic=name,
            manual_evidence=evidence,
            related_apis=related[:5],
            limitations_confirmation="requires_source_review" if evidence else "unconfirmed",
            note="Excerpts are evidence, not verified conclusions. Missing evidence means unconfirmed.",
        )

    def read_source(
        self,
        source_id: str | None = None,
        snapshot: str | None = None,
        path: str | None = None,
        start_line: int | None = None,
        max_lines: int = 80,
    ) -> dict:
        directory = self.directory(snapshot)
        snapshot = directory.name
        record = None
        if source_id:
            with self.connection(snapshot) as db:
                row = db.execute("SELECT * FROM records WHERE id=?", (source_id,)).fetchone()
            if row is None:
                raise ValueError("Unknown source_id in this snapshot")
            record = json.loads(row["payload"])
            documentation = record.get("documentation_source", {})
            path = documentation.get("path", record["path"])
            start_line = start_line or documentation.get("line_start", record["line_start"])
        if not path:
            raise ValueError("Supply source_id or a snapshot-relative source path")
        source_root = (directory / "sources").resolve()
        target = (source_root / path).resolve()
        if not target.is_relative_to(source_root) or ".git" in target.parts:
            raise ValueError("Source path is outside the snapshot")
        target = filesystem_path(target)
        if target.suffix.lower() not in {
            ".xml",
            ".rst",
            ".json",
            ".cpp",
            ".h",
            ".hpp",
            ".c",
            ".gd",
            ".py",
            ".txt",
            ".md",
        }:
            raise ValueError("Unsupported source file type")
        if not target.is_file():
            raise ValueError("Source file not found")
        if record and "documentation_excerpt" in record:
            raw = json.dumps(record["documentation_excerpt"], ensure_ascii=False, indent=2)
            return self.envelope(
                snapshot,
                **record["documentation_source"],
                content=raw[:16000],
                truncated=len(raw) > 16000,
            )
        if record and "binding_metadata" in record["details"]:
            raw = json.dumps(record["details"]["binding_metadata"], ensure_ascii=False, indent=2)
            return self.envelope(
                snapshot,
                path=path,
                json_class=record["owner"],
                content=raw[:16000],
                truncated=len(raw) > 16000,
            )
        start_line = max(1, start_line or 1)
        max_lines = max(1, min(max_lines, 200))
        content = []
        used = 0
        has_more = False
        with target.open(encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                if number < start_line:
                    continue
                if len(content) >= max_lines or used + len(line) > 16000:
                    has_more = True
                    if not content:
                        content.append(line[:16000].rstrip("\n"))
                    break
                content.append(line.rstrip("\n"))
                used += len(line)
        return self.envelope(
            snapshot,
            path=path,
            start_line=start_line,
            end_line=start_line + len(content) - 1,
            content="\n".join(content),
            truncated=has_more,
        )

    def compare_snapshots(self, before: str, after: str, limit: int = 30) -> dict:
        limit = max(1, min(limit, 100))

        def api_map(snapshot):
            result = {}
            with self.connection(snapshot) as db:
                for row in db.execute("SELECT * FROM records WHERE kind!='manual' ORDER BY rowid"):
                    record = json.loads(row["payload"])
                    key = f"{record['owner']}:{record['kind']}:{record['name']}"
                    semantic = {
                        field: record[field]
                        for field in [
                            "signature",
                            "description",
                            "inherits",
                            "deprecated",
                            "experimental",
                            "details",
                        ]
                    }
                    result.setdefault(key, []).append(semantic)
            return result

        left, right = api_map(before), api_map(after)
        added = sorted(right.keys() - left.keys())
        removed = sorted(left.keys() - right.keys())
        changed = sorted(k for k in left.keys() & right.keys() if left[k] != right[k])
        a, b = self.manifest(before)["index"]["files"], self.manifest(after)["index"]["files"]
        docs_changed = sorted(
            key
            for key in a.keys() | b.keys()
            if key.startswith("docs/") and a.get(key) != b.get(key)
        )
        return {
            "before": before,
            "after": after,
            "counts": {
                "api_added": len(added),
                "api_removed": len(removed),
                "api_changed": len(changed),
                "docs_changed": len(docs_changed),
            },
            "api_added": added[:limit],
            "api_removed": removed[:limit],
            "api_changed": [
                {
                    "symbol": key,
                    "before_signatures": [r["signature"] for r in left[key]][:20],
                    "after_signatures": [r["signature"] for r in right[key]][:20],
                }
                for key in changed[:limit]
            ],
            "docs_changed": docs_changed[:limit],
            "truncated": any(
                len(items) > limit for items in [added, removed, changed, docs_changed]
            ),
        }
