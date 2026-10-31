from __future__ import annotations

import argparse
import json
import sys

from .paths import data_directory
from .store import KnowledgeBase
from .sync import reindex_snapshot, sync_sources


def main() -> None:
    for stream in [sys.stdout, sys.stderr]:
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Local Godot knowledge and MCP stdio server")
    parser.add_argument(
        "--data", help="Store directory; defaults to GODOT_KNOWLEDGE_DATA or OS user data"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve")
    commands.add_parser("status")
    install = commands.add_parser(
        "install", help="Install the bundled Skill and configure Codex MCP"
    )
    install.add_argument("--codex-home", help="Codex home; defaults to CODEX_HOME or ~/.codex")
    sync = commands.add_parser("sync")
    sync.add_argument("--engine", help="Godot executable, PATH command, or macOS app bundle")
    sync.add_argument("--source-ref")
    sync.add_argument("--docs-ref")
    sync.add_argument("--offline", action="store_true")
    sync.add_argument("--allow-partial", action="store_true")
    sync.add_argument("--select", action="store_true")
    reindex = commands.add_parser("reindex", help="Rebuild a candidate using cached pinned sources")
    reindex.add_argument("--snapshot", required=True)
    reindex.add_argument("--select", action="store_true")
    query = commands.add_parser("query", help="Invoke any read/select tool using JSON arguments")
    query.add_argument(
        "tool",
        choices=[
            "search",
            "get_api",
            "get_topic",
            "read_source",
            "compare_snapshots",
            "select_snapshot",
        ],
    )
    query.add_argument("--json", default="{}")
    args = parser.parse_args()
    try:
        if args.command == "install":
            from .install import install

            print(json.dumps(install(args.codex_home, args.data), ensure_ascii=False, indent=2))
            return
        kb = KnowledgeBase(data_directory(args.data))
        if args.command == "serve":
            from .server import create_server

            create_server(args.data).run(transport="stdio")
            return
        if args.command == "status":
            result = kb.status()
        elif args.command == "reindex":
            result = reindex_snapshot(kb, args.snapshot)
            if args.select:
                result["selection"] = kb.select_snapshot(result["id"])
        elif args.command == "sync":
            result = sync_sources(
                kb,
                args.engine,
                args.source_ref,
                args.docs_ref,
                args.offline,
                args.allow_partial,
            )
            if args.select:
                result["selection"] = kb.select_snapshot(result["id"])
        else:
            arguments = json.loads(args.json)
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be a JSON object")
            result = getattr(kb, args.tool)(**arguments)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
