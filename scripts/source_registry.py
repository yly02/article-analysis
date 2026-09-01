#!/usr/bin/env python3
"""Safely append a reviewed A/B source to the desktop Markdown registry."""

from __future__ import annotations

import argparse
import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from runtime_paths import user_data_file


DEFAULT_REGISTRY = Path(
    os.environ.get("ARTICLE_DISTILLER_SOURCE_REGISTRY")
    or user_data_file("source-registry.md")
)
CATEGORIES = {"模型", "产品", "行业", "工具", "行业动态"}
TRACKING_PARAMS = {
    "fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref", "source",
}


def initialize_registry(registry: Path) -> None:
    if registry.exists():
        return
    registry.parent.mkdir(parents=True, exist_ok=True)
    sections = []
    for category in sorted(CATEGORIES):
        sections.extend([
            f"## {category}",
            "",
            "| 等级 | 标题 | 发布者 | 链接 |",
            "| --- | --- | --- | --- |",
            "",
        ])
    registry.write_text(
        "# AI 一手信息源\n\n> 核对日期：1970-01-01  \n\n" + "\n".join(sections),
        encoding="utf-8",
    )


def normalize_url(value: str) -> str:
    raw = str(value or "").strip().rstrip(".,;:)]}>")
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("url must be an absolute http(s) URL")
    scheme = parts.scheme.lower()
    host = parts.hostname.lower()
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("url contains an invalid port") from exc
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if not port or default_port else f"{host}:{port}"
    path = parts.path.rstrip("/") or "/"
    query = urlencode([
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
    ])
    return urlunsplit((scheme, netloc, path, query, ""))


def urls_in_markdown(text: str) -> set[str]:
    urls = set()
    for raw in re.findall(r"https?://[^\s<>)|]+", text or ""):
        try:
            urls.add(normalize_url(raw))
        except ValueError:
            continue
    return urls


def _table_cell(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).replace("|", "\\|")


def add_source(
    registry: Path,
    level: str,
    category: str,
    title: str,
    publisher: str,
    url: str,
    label: str,
    checked_on: str | None = None,
) -> dict:
    if level not in {"A", "B"}:
        raise ValueError("level must be A or B")
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of: {', '.join(sorted(CATEGORIES))}")
    initialize_registry(registry)
    for field_name, value in (("title", title), ("publisher", publisher), ("label", label)):
        if not str(value or "").strip():
            raise ValueError(f"{field_name} must not be empty")

    normalized = normalize_url(url)
    content = registry.read_text(encoding="utf-8")
    if normalized in urls_in_markdown(content):
        return {"status": "skipped", "reason": "duplicate_url", "url": normalized}

    lines = content.splitlines()
    section_marker = f"## {category}"
    try:
        section_index = lines.index(section_marker)
    except ValueError as exc:
        raise ValueError(f"category section not found: {section_marker}") from exc

    header_index = next(
        (index for index in range(section_index + 1, len(lines)) if lines[index].startswith("| 等级 |")),
        None,
    )
    if header_index is None:
        raise ValueError(f"source table not found under: {section_marker}")
    insert_index = header_index + 2
    while insert_index < len(lines) and lines[insert_index].startswith("|"):
        insert_index += 1

    row = (
        f"| {level} | {_table_cell(title)} | {_table_cell(publisher)} | "
        f"[{_table_cell(label)}]({normalized}) |"
    )
    lines.insert(insert_index, row)
    checked = checked_on or date.today().isoformat()
    updated = "\n".join(lines) + ("\n" if content.endswith("\n") else "")
    updated, count = re.subn(
        r"(?m)^> 核对日期：\d{4}-\d{2}-\d{2}(?:  )?$",
        f"> 核对日期：{checked}  ",
        updated,
        count=1,
    )
    if count != 1:
        raise ValueError("registry is missing the expected checked-date line")
    registry.write_text(updated, encoding="utf-8")
    return {"status": "added", "category": category, "level": level, "url": normalized}


def main() -> None:
    parser = argparse.ArgumentParser(description="Add one reviewed source to AI一手信息源.md")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--level", choices=["A", "B"], required=True)
    parser.add_argument("--category", choices=sorted(CATEGORIES), required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    result = add_source(
        args.registry, args.level, args.category, args.title,
        args.publisher, args.url, args.label,
    )
    print(result)


if __name__ == "__main__":
    main()
