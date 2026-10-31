"""Search vocabulary; aliases are navigation aids, never evidence."""

TOPICS = {
    "lifecycle": {
        "aliases": ["生命周期", "节点", "场景", "scene", "node"],
        "terms": ["Node", "_ready", "_enter_tree", "_exit_tree", "SceneTree"],
    },
    "resources": {
        "aliases": ["资源", "加载", "resource", "loading"],
        "terms": ["Resource", "ResourceLoader", "load", "preload"],
    },
    "gdscript": {
        "aliases": ["脚本", "类型", "GDScript"],
        "terms": ["GDScript", "typed", "static typing", "script"],
    },
    "input": {
        "aliases": ["输入", "键盘", "鼠标", "手柄"],
        "terms": ["Input", "InputEvent", "InputMap"],
    },
    "ui": {
        "aliases": ["界面", "控件", "布局", "UI", "GUI"],
        "terms": ["Control", "Container", "Theme"],
    },
    "2d": {
        "aliases": ["二维", "2D"],
        "terms": ["Node2D", "CanvasItem", "Sprite2D"],
    },
    "3d": {
        "aliases": ["三维", "3D"],
        "terms": ["Node3D", "Camera3D", "MeshInstance3D"],
    },
    "physics": {
        "aliases": ["物理", "碰撞", "刚体"],
        "terms": ["PhysicsServer2D", "PhysicsServer3D", "RigidBody", "collision"],
    },
    "animation": {
        "aliases": ["动画", "骨骼", "补间"],
        "terms": ["AnimationPlayer", "AnimationTree", "Tween"],
    },
    "rendering": {
        "aliases": ["渲染", "渲染器", "着色器", "兼容", "renderer", "shader"],
        "terms": ["RenderingServer", "rendering", "Forward+", "Compatibility", "Mobile"],
    },
    "threads": {
        "aliases": ["线程", "线程安全", "多线程", "并发", "thread", "threading"],
        "terms": ["Thread", "WorkerThreadPool", "thread safe", "thread-safe", "call_deferred"],
    },
    "export": {
        "aliases": ["导出", "平台", "打包", "发布"],
        "terms": ["EditorExportPlugin", "export", "platform"],
    },
    "extension": {
        "aliases": ["扩展", "插件", "定制", "模块", "GDExtension"],
        "terms": ["GDExtension", "EditorPlugin", "C++ modules", "custom modules"],
    },
}


def topic_names(text: str) -> list[str]:
    import re

    folded = text.casefold()
    return [
        name
        for name, spec in TOPICS.items()
        if name == folded
        or any(
            (
                alias.casefold() in folded
                if re.search(r"[\u3400-\u9fff]", alias)
                else re.search(r"(?<!\w)" + re.escape(alias.casefold()) + r"(?!\w)", folded)
            )
            for alias in spec["aliases"]
        )
    ]


def expand_query(text: str) -> list[str]:
    import re

    terms = re.findall(r"[A-Za-z_][A-Za-z_0-9+]*", text)
    for name in topic_names(text):
        terms.extend(TOPICS[name]["terms"])
    # Chinese text not present in the alias map may still occur in imported documents.
    terms.extend(re.findall(r"[\u3400-\u9fff]+", text))
    return list(dict.fromkeys(terms))[:30]


def classify(text: str) -> list[str]:
    folded = text.casefold()
    return [
        name
        for name, spec in TOPICS.items()
        if any(term.casefold() in folded for term in spec["terms"])
    ]
