import sys
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_real_stdio_client(make_snapshot):
    kb = make_snapshot()
    kb.select_snapshot("a")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "godot_knowledge.cli", "--data", str(kb.root), "serve"],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as client:
            await client.initialize()
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "status",
                "search",
                "get_api",
                "get_topic",
                "read_source",
                "sync_sources",
                "compare_snapshots",
                "select_snapshot",
            }
            for name, args in [
                ("status", {}),
                ("search", {"query": "线程安全"}),
                ("get_api", {"class_name": "Node", "member": "_ready"}),
                ("get_topic", {"topic": "threads"}),
                ("read_source", {"path": "docs/threads.rst"}),
                ("compare_snapshots", {"before": "a", "after": "a"}),
                ("select_snapshot", {"snapshot": "a"}),
            ]:
                result = await client.call_tool(name, args)
                assert not result.isError, result.content
                assert result.structuredContent is not None
            missing = await client.call_tool(
                "get_api", {"class_name": "Node", "snapshot": "missing"}
            )
            assert missing.isError
            failed_sync = await client.call_tool(
                "sync_sources", {"engine_executable": str(kb.root / "missing.exe"), "offline": True}
            )
            assert failed_sync.isError
            state = await client.call_tool("status")
            assert state.structuredContent["default_snapshot"] == "a"
