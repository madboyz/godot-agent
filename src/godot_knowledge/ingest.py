"""Parse official XML/RST and exported binding JSON without executing content."""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.parsers import expat

from .topics import classify


def filesystem_path(path: Path) -> Path:
    """Allow upstream source filenames beyond Windows' legacy MAX_PATH."""
    absolute = str(path.resolve())
    if os.name == "nt" and not absolute.startswith("\\\\?\\"):
        return Path(
            "\\\\?\\UNC\\" + absolute[2:] if absolute.startswith("\\\\") else "\\\\?\\" + absolute
        )
    return Path(absolute)


def text(element: ET.Element | None) -> str:
    return "" if element is None else "".join(element.itertext()).strip()


def xml_records(path: Path, relative: str) -> list[dict]:
    raw = path.read_bytes()
    root = ET.fromstring(raw)
    if root.tag != "class":
        return []
    starts: list[tuple[int, int]] = []
    stack: list[int] = []
    parser = expat.ParserCreate()

    def start(*_):
        stack.append(len(starts))
        starts.append((parser.CurrentLineNumber, parser.CurrentLineNumber))

    def end(*_):
        index = stack.pop()
        starts[index] = (starts[index][0], parser.CurrentLineNumber)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.Parse(raw, True)
    lines = dict(zip(root.iter(), starts, strict=True))
    owner = root.attrib["name"]
    common = {
        "owner": owner,
        "inherits": root.get("inherits", ""),
        "path": relative,
        "evidence": "official",
        "availability": "exported" if relative.startswith("local/") else "source_only",
    }
    records = []

    def add(element, kind, name, signature, description, extra=None):
        records.append(
            {
                **common,
                "kind": kind,
                "name": name,
                "title": owner if kind == "class" else f"{owner}.{name}",
                "signature": signature,
                "description": description,
                "line_start": lines[element][0],
                "line_end": lines[element][1],
                "deprecated": element.get("deprecated"),
                "experimental": element.get("experimental"),
                "details": extra or {},
            }
        )

    add(
        root,
        "class",
        owner,
        f"class {owner}" + (f" extends {root.get('inherits')}" if root.get("inherits") else ""),
        "\n\n".join(
            filter(None, [text(root.find("brief_description")), text(root.find("description"))])
        ),
        {
            "tutorials": [
                {"title": item.get("title", ""), "url": text(item)}
                for item in root.findall("tutorials/link")
            ]
        },
    )
    for group, kind in [
        ("methods", "method"),
        ("constructors", "constructor"),
        ("operators", "operator"),
        ("signals", "signal"),
        ("members", "property"),
        ("constants", "constant"),
        ("annotations", "annotation"),
        ("theme_items", "theme_item"),
    ]:
        for item in root.findall(f"{group}/*"):
            name = item.get("name", "")
            params = [
                dict(param.attrib)
                for param in sorted(item.findall("param"), key=lambda p: int(p.get("index", "0")))
            ]
            returns = item.find("return")
            return_type = returns.get("type", "void") if returns is not None else "void"
            if kind in {"property", "constant", "theme_item"}:
                signature = f"{name}: {item.get('type', '')}"
                if "value" in item.attrib or "default" in item.attrib:
                    signature += f" = {item.get('value', item.get('default', ''))}"
            else:
                args = ", ".join(
                    f"{p.get('name', '')}: {p.get('type', '')}"
                    + (f" = {p['default']}" if "default" in p else "")
                    for p in params
                )
                signature = f"{name}({args}) -> {return_type}"
                if item.get("qualifiers"):
                    signature += f" [{item.get('qualifiers')}]"
            add(
                item,
                kind,
                name,
                signature,
                text(item.find("description")) or text(item),
                {
                    **item.attrib,
                    "parameters": params,
                    "return": dict(returns.attrib) if returns is not None else {},
                },
            )
    return records


def rst_records(path: Path, relative: str) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    headings = []
    for index in range(len(lines) - 1):
        underline = lines[index + 1].strip()
        if (
            lines[index].strip()
            and len(underline) >= 3
            and len(set(underline)) == 1
            and underline[0] in '=-~^"+*#'
        ):
            headings.append((index, lines[index].strip()))
    if not headings or headings[0][0] > 0:
        headings.insert(0, (0, path.stem.replace("_", " ")))
    # Split long sections on line boundaries so read_source always has useful ranges.
    result = []
    for section, (start, title) in enumerate(headings):
        end = headings[section + 1][0] if section + 1 < len(headings) else len(lines)
        cursor = start
        while cursor < end:
            stop = min(cursor + 100, end)
            result.append(
                {
                    "kind": "manual",
                    "owner": "",
                    "inherits": "",
                    "name": title,
                    "title": title,
                    "signature": "",
                    "description": "\n".join(lines[cursor:stop]),
                    "path": relative,
                    "line_start": cursor + 1,
                    "line_end": stop,
                    "deprecated": None,
                    "experimental": None,
                    "details": {},
                    "evidence": "official",
                }
            )
            cursor = stop
    return result


def json_records(path: Path, relative: str, existing_classes: set[str]) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    result = []
    # XML is canonical for class/member docs. JSON supplies binding-only types.
    for cls in data.get("classes", []) + data.get("builtin_classes", []):
        if cls["name"] in existing_classes:
            continue
        result.append(
            {
                "kind": "class",
                "owner": cls["name"],
                "inherits": cls.get("inherits", ""),
                "name": cls["name"],
                "title": cls["name"],
                "signature": f"class {cls['name']}",
                "description": cls.get("description", cls.get("brief_description", "")),
                "path": relative,
                "line_start": 1,
                "line_end": 1,
                "deprecated": cls.get("is_deprecated"),
                "experimental": cls.get("is_experimental"),
                "details": {"binding_metadata": cls, "location": "JSON class name"},
                "evidence": "official",
                "availability": "exported",
            }
        )
    return result


def merge_xml_documentation(local: list[dict], official: list[dict]) -> None:
    for record in local:
        matches = [
            source
            for source in official
            if source["kind"] == record["kind"] and source["name"] == record["name"]
        ]
        exact = [source for source in matches if source["signature"] == record["signature"]]
        candidates = exact or (matches if len(matches) == 1 else [])
        if len(candidates) != 1:
            continue
        source = candidates[0]
        if not record["description"] and source["description"]:
            record["description"] = source["description"]
            record["documentation_source"] = {
                "path": source["path"],
                "line_start": source["line_start"],
                "line_end": source["line_end"],
                "evidence": "official",
            }
        for flag in ["deprecated", "experimental"]:
            if record[flag] is None:
                record[flag] = source[flag]
        if record["kind"] == "class" and not record["details"].get("tutorials"):
            record["details"]["tutorials"] = source["details"].get("tutorials", [])


def enrich_json_documentation(records: list[dict], api: Path) -> None:
    data = json.loads(api.read_text(encoding="utf-8"))
    classes = {
        cls["name"]: (group, cls)
        for group in ["classes", "builtin_classes"]
        for cls in data.get(group, [])
    }
    groups = {
        "method": "methods",
        "constructor": "constructors",
        "operator": "operators",
        "signal": "signals",
        "property": "properties",
        "constant": "constants",
    }
    for record in records:
        if record["owner"] not in classes:
            continue
        record["availability"] = "exported"
        if record["description"]:
            continue
        group, cls = classes[record["owner"]]
        key = f"{group}[name={record['owner']}]"
        if record["kind"] == "class":
            source = cls
        else:
            member_group = groups.get(record["kind"])
            if not member_group:
                continue
            matches = [
                item for item in cls.get(member_group, []) if item.get("name") == record["name"]
            ]
            if len(matches) > 1:
                types = [p.get("type") for p in record["details"].get("parameters", [])]
                matches = [
                    item
                    for item in matches
                    if [p.get("type") for p in item.get("arguments", [])] == types
                ]
            if len(matches) != 1:
                continue
            source = matches[0]
            key += f".{member_group}[name={record['name']}]"
        description = "\n\n".join(
            str(source[field])
            for field in ["brief_description", "description"]
            if source.get(field)
        )
        if description:
            record["description"] = description
            record["documentation_source"] = {
                "path": "local/extension_api.json",
                "json_key": key,
                "evidence": "official",
            }
            record["documentation_excerpt"] = {
                field: source[field]
                for field in [
                    "name",
                    "brief_description",
                    "description",
                    "arguments",
                    "return_type",
                    "index",
                ]
                if field in source
            }


def collect(source_root: Path) -> list[dict]:
    source_root = filesystem_path(source_root)
    records = []
    # Local XML describes the actual executable; don't mix duplicate upstream class versions.
    for base in ["local", "engine"]:
        seen = {r["owner"] for r in records if r["kind"] == "class"}
        for path in sorted((source_root / base).rglob("*.xml")):
            if base == "engine" and not (
                "doc/classes" in path.as_posix() or "doc_classes" in path.parts
            ):
                continue
            parsed = xml_records(path, path.relative_to(source_root).as_posix())
            if parsed and parsed[0]["owner"] not in seen:
                records.extend(parsed)
                seen.add(parsed[0]["owner"])
            elif parsed and base == "engine":
                merge_xml_documentation(
                    [record for record in records if record["owner"] == parsed[0]["owner"]],
                    parsed,
                )
    api = source_root / "local" / "extension_api.json"
    if api.exists():
        enrich_json_documentation(records, api)
        records.extend(
            json_records(
                api,
                api.relative_to(source_root).as_posix(),
                {r["owner"] for r in records if r["kind"] == "class"},
            )
        )
    for path in sorted((source_root / "docs").rglob("*.rst")):
        if (
            ".git" not in path.parts
            and "classes" not in path.relative_to(source_root / "docs").parts
        ):
            records.extend(rst_records(path, path.relative_to(source_root).as_posix()))
    for record in records:
        record["topics"] = classify(f"{record['title']} {record['description']} {record['path']}")
    return records
