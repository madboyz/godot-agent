"""Exercise an installed store through a real MCP stdio client."""

import argparse
import asyncio
import sys
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from godot_knowledge.store import dump_json


async def verify(data: Path, output: Path) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "godot_knowledge.cli", "--data", str(data), "serve"],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as client:
            await client.initialize()

            async def call(name, arguments=None):
                response = await client.call_tool(name, arguments or {})
                if response.isError:
                    raise AssertionError(response.content)
                assert response.structuredContent is not None
                return response.structuredContent

            status = await call("status")
            snapshot = status["default_snapshot"]
            assert snapshot
            ready = await call(
                "get_api",
                {
                    "class_name": "Node",
                    "member": "_ready",
                    "snapshot": snapshot,
                },
            )
            assert ready["results"][0]["owner"] == "Node"
            inherited = await call(
                "get_api",
                {
                    "class_name": "Node",
                    "member": "call_deferred",
                    "snapshot": snapshot,
                },
            )
            assert inherited["results"][0]["owner"] == "Object"
            source = await call(
                "read_source",
                {
                    "source_id": ready["results"][0]["source_id"],
                    "snapshot": snapshot,
                    "max_lines": 15,
                },
            )
            assert "_ready" in source["content"]
            topics = {}
            for topic in ["lifecycle", "threads", "rendering"]:
                result = await call("get_topic", {"topic": topic, "snapshot": snapshot})
                assert result["related_apis"] or result["manual_evidence"]
                assert result["snapshot"] == snapshot
                topics[topic] = {
                    "confirmation": result["limitations_confirmation"],
                    "manual_sources": [entry["source"] for entry in result["manual_evidence"]],
                    "related_apis": [entry["title"] for entry in result["related_apis"]],
                }
            chinese = await call("search", {"query": "线程安全", "snapshot": snapshot, "limit": 3})
            assert chinese["results"]
            tools = await client.list_tools()
            report = {
                "snapshot": snapshot,
                "engine_version": ready["engine_version"],
                "coverage": ready["coverage"],
                "tool_count": len(tools.tools),
                "ready": ready["results"][0],
                "inherited_member": inherited["results"][0],
                "source_round_trip": source,
                "topics": topics,
                "chinese_search_titles": [entry["title"] for entry in chinese["results"]],
            }
            dump_json(output, report)
            print(f"Live MCP verification passed: {snapshot}; {len(tools.tools)} tools")
            print(f"Report: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(verify(args.data.resolve(), args.output.resolve()))
