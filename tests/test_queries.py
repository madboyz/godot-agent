import pytest
from conftest import NODE_XML


def test_inheritance_overloads_defaults_signals_enums_and_flags(make_snapshot):
    kb = make_snapshot()
    result = kb.get_api("Node", snapshot="a")
    assert [c["owner"] for c in result["lineage"]] == ["Node", "Object"]
    inherited = kb.get_api("Node", "call_deferred", snapshot="a")
    assert inherited["results"][0]["owner"] == "Object"
    assert inherited["results"][0]["signature"].endswith("[vararg]")
    methods = kb.get_api("Node", "work", snapshot="a")["results"]
    assert len(methods) == 2
    assert methods[0]["details"]["parameters"][0]["default"] == "1"
    assert methods[0]["deprecated"] == "Use run instead."
    assert methods[1]["experimental"] == "May change."
    assert any(r["kind"] == "signal" for r in result["results"])
    assert (
        next(r for r in result["results"] if r["kind"] == "constant")["details"]["enum"]
        == "ProcessMode"
    )
    assert kb.get_api("Missing", snapshot="a")["confirmation"] == "unconfirmed"
    assert kb.get_api("Node", "missing", snapshot="a")["confirmation"] == "unconfirmed"


def test_chinese_english_and_topic_filters(make_snapshot):
    kb = make_snapshot()
    assert kb.search("Node", snapshot="a")["results"][0]["title"] == "Node"
    for query in ["生命周期顺序", "线程安全", "渲染器条件", "_ready"]:
        assert kb.search(query, snapshot="a")["results"]
    assert kb.search("线程", snapshot="a", topic="threads", kind="manual")["results"]
    for topic in ["线程", "生命周期", "渲染"]:
        result = kb.get_topic(topic, snapshot="a")
        assert result["related_apis"] or result["manual_evidence"]
    assert kb.get_topic("threads", snapshot="a")["manual_evidence"]
    with pytest.raises(ValueError):
        kb.search("Node", snapshot="a", topic="unknown")
    with pytest.raises(ValueError):
        kb.search("", snapshot="a")
    kb.search('Node " OR * --', snapshot="a")


def test_source_round_trip_and_bounds(make_snapshot):
    kb = make_snapshot()
    row = kb.get_api("Node", "_ready", snapshot="a")["results"][0]
    original = kb.read_source(row["source_id"], snapshot="a", max_lines=4)
    assert '<method name="_ready"' in original["content"]
    assert original["end_line"] - original["start_line"] == 3
    assert original["truncated"]
    builtin = kb.get_api("Vector2", snapshot="a")["lineage"][0]
    assert kb.read_source(builtin["source_id"], snapshot="a")["json_class"] == "Vector2"
    with pytest.raises(ValueError):
        kb.read_source(snapshot="a", path="../../../secrets.txt")
    with pytest.raises(ValueError):
        kb.read_source(snapshot="a", path="docs/.git/config")
    with pytest.raises(ValueError):
        kb.get_api("Node", snapshot="../a")


def test_snapshots_do_not_mix_and_diff_semantics(make_snapshot):
    kb = make_snapshot()
    make_snapshot(
        "b",
        version="4.8.0.stable.official.deadbeef",
        manual=False,
        node=NODE_XML.replace('default="1"', 'default="2"'),
    )
    kb.select_snapshot("a")
    assert kb.get_api("Node", "work")["results"][0]["details"]["parameters"][0]["default"] == "1"
    assert (
        kb.get_api("Node", "work", snapshot="b")["results"][0]["details"]["parameters"][0][
            "default"
        ]
        == "2"
    )
    assert kb.get_topic("threads", snapshot="b")["limitations_confirmation"] == "unconfirmed"
    comparison = kb.compare_snapshots("a", "b")
    assert "Node:method:work" in [r["symbol"] for r in comparison["api_changed"]]
    assert comparison["counts"]["docs_changed"] == 1
    kb.select_snapshot("b")
    assert kb.get_api("Node")["snapshot"] == "b"
    with pytest.raises(ValueError):
        kb.select_snapshot("missing")
    assert kb.status()["default_snapshot"] == "b"


def test_pagination_and_override(make_snapshot):
    child = NODE_XML.replace(
        "<methods>",
        """<methods>
<method name="call_deferred"><return type="int" /><description>Override.</description></method>""",
    )
    kb = make_snapshot(node=child)
    result = kb.get_api("Node", "call_deferred", snapshot="a")
    assert len(result["results"]) == 1
    assert result["results"][0]["owner"] == "Node"
    first = kb.get_api("Node", snapshot="a", limit=2)
    second = kb.get_api("Node", snapshot="a", limit=2, offset=first["next_offset"])
    assert len(first["results"]) == 2
    assert {r["source_id"] for r in first["results"]}.isdisjoint(
        r["source_id"] for r in second["results"]
    )


def test_response_keeps_snapshot_if_default_switches_mid_query(make_snapshot, monkeypatch):
    kb = make_snapshot()
    make_snapshot("b")
    kb.select_snapshot("a")
    original = kb.connection

    # Switch by writing the pointer; avoid recursing through select_snapshot.
    from godot_knowledge.store import dump_json

    def switch(snapshot=None):
        db = original(snapshot)
        dump_json(kb.root / "active.json", {"snapshot": "b"})
        return db

    monkeypatch.setattr(kb, "connection", switch)
    assert kb.get_api("Node")["snapshot"] == "a"
