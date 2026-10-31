import json

import pytest

from godot_knowledge.store import KnowledgeBase
from godot_knowledge.sync import publish

BASE_XML = """<?xml version="1.0"?>
<class name="Object" inherits="">
<brief_description>Base object.</brief_description>
<methods>
<method name="call_deferred" qualifiers="vararg">
<return type="Variant" />
<param index="0" name="method" type="StringName" />
<description>Call on the main thread when safe.</description>
</method>
</methods>
<signals><signal name="changed"><description>Changed.</description></signal></signals>
</class>
"""
NODE_XML = """<?xml version="1.0"?>
<class name="Node" inherits="Object">
<brief_description>Scene node lifecycle.</brief_description>
<description>Children receive _ready before their parent.</description>
<methods>
<method name="_ready" qualifiers="virtual">
<return type="void" />
<description>Called when node enters the scene tree.</description>
</method>
<method name="work" deprecated="Use run instead.">
<return type="int" />
<param index="0" name="count" type="int" default="1" />
<description>Work once.</description>
</method>
<method name="work" experimental="May change.">
<return type="String" />
<param index="0" name="label" type="String" default="&quot;&quot;" />
<description>Work with a label.</description>
</method>
</methods>
<members><member name="name" type="StringName" default="&amp;&quot;&quot;">Node name.</member></members>
<constants><constant name="MODE_IDLE" value="0" enum="ProcessMode">Idle.</constant></constants>
</class>
"""
THREADS_RST = """Thread safety
=============

The active scene tree is not thread-safe.
Use call_deferred to schedule node operations on the main thread.

Rendering
---------

Rendering behavior depends on the renderer.
Compatibility, Mobile and Forward+ have different capabilities.
"""


@pytest.fixture
def make_snapshot(tmp_path):
    kb = KnowledgeBase(tmp_path / "data")

    def make(identifier="a", version="4.7.1.stable.official.a13da4feb", manual=True, node=NODE_XML):
        candidate = kb.root / "staging" / identifier
        local = candidate / "sources" / "local"
        local.mkdir(parents=True)
        (local / "Object.xml").write_text(BASE_XML, encoding="utf-8")
        (local / "Node.xml").write_text(node, encoding="utf-8")
        (local / "extension_api.json").write_text(
            json.dumps(
                {
                    "builtin_classes": [{"name": "Vector2", "description": "2D vector."}],
                }
            ),
            encoding="utf-8",
        )
        if manual:
            docs = candidate / "sources" / "docs"
            docs.mkdir()
            (docs / "threads.rst").write_text(THREADS_RST, encoding="utf-8")
        manifest = {
            "id": identifier,
            "engine_version": version,
            "schema_version": 1,
            "sources": {},
            "coverage": {
                "local_api": True,
                "manuals": manual,
                "engine_source": False,
                "gaps": [] if manual else ["manuals missing"],
            },
        }
        publish(kb.root, candidate, manifest)
        return kb

    return make
