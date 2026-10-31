import json

from conftest import NODE_XML

from godot_knowledge.sync import reindex_snapshot


def test_cached_reindex_merges_official_docs_and_preserves_signatures(make_snapshot):
    kb = make_snapshot(
        node=NODE_XML.replace(
            "<description>Called when node enters the scene tree.</description>", "<description />"
        )
    )
    kb.select_snapshot("a")
    engine = kb.directory("a") / "sources" / "engine" / "doc" / "classes"
    engine.mkdir(parents=True)
    (engine / "Node.xml").write_text(NODE_XML, encoding="utf-8")
    result = reindex_snapshot(kb, "a")
    row = kb.get_api("Node", "_ready", snapshot=result["id"])["results"][0]
    assert row["description"] == "Called when node enters the scene tree."
    assert row["availability"] == "exported"
    assert row["source"]["path"] == "local/Node.xml"
    assert row["description_source"]["path"] == "engine/doc/classes/Node.xml"
    assert row["signature"] == "_ready() -> void [virtual]"
    assert "Called when" in kb.read_source(row["source_id"], snapshot=result["id"])["content"]
    assert kb.status()["default_snapshot"] == "a"


def test_local_json_documentation_is_available_offline(make_snapshot):
    empty_xml = NODE_XML.replace(
        "<description>Called when node enters the scene tree.</description>", "<description />"
    )
    kb = make_snapshot(node=empty_xml)
    api = kb.directory("a") / "sources" / "local" / "extension_api.json"
    api.write_text(
        json.dumps(
            {
                "classes": [
                    {
                        "name": "Node",
                        "description": "Node documentation.",
                        "methods": [{"name": "_ready", "description": "Called when ready."}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = reindex_snapshot(kb, "a")
    row = kb.get_api("Node", "_ready", snapshot=result["id"])["results"][0]
    assert row["description"] == "Called when ready."
    assert row["description_source"]["json_key"] == "classes[name=Node].methods[name=_ready]"
    source = kb.read_source(row["source_id"], snapshot=result["id"])
    assert json.loads(source["content"])["description"] == "Called when ready."
    assert kb.get_api("Node", "_ready", snapshot="a")["results"][0]["description"] == ""
