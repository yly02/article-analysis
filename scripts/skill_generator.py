"""蒸馏产物变 skill 模块：解读完一篇文章后，自动生成一个小型领域 skill。

生成的 skill 是一个 .md 文件，包含：
- 文章的核心方法论和概念定义
- 类比解释（帮助 AI 理解技术概念）
- 行动清单和上手指南

让 AI 能"按这篇文章的知识体系"回答相关问题。

输出位置：~/.article-distiller/skills/<slug>.md，或 ARTICLE_DISTILLER_DATA_DIR 指定目录。
"""

from __future__ import annotations

import os
import re
from typing import Optional

from runtime_paths import user_data_dir

_SKILLS_DIR = str(user_data_dir() / "skills")


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff\s-]", "", text)[:40].strip()
    s = re.sub(r"[\s_]+", "-", s)
    return s.lower().strip("-") or "article"


def generate_skill(article_meta: dict, distilled: dict, output_dir: Optional[str] = None) -> str:
    """从解读 JSON 生成一个领域 skill 文件，返回文件路径。

    article_meta: {"url": ..., "title": ..., "date": ...}
    distilled: 解读 JSON dict
    output_dir: 自定义输出目录，默认用 _SKILLS_DIR
    """
    out_dir = output_dir or _SKILLS_DIR
    os.makedirs(out_dir, exist_ok=True)

    d_title = distilled.get("distilled_title") or article_meta.get("title", "未命名")
    slug = _slugify(d_title)
    category_tags = distilled.get("category_tags") or []
    quick_scan = distilled.get("quick_scan") or []
    sections = distilled.get("sections") or []
    action_card = distilled.get("action_card") or {}
    takeaway_list = distilled.get("takeaway_list") or []
    source_notes = distilled.get("source_notes") or ""

    tags_str = ", ".join(category_tags) if category_tags else "AI"

    parts = []

    # ── Frontmatter ──────────────────────────────
    parts.append("---")
    parts.append(f'title: "关于 {d_title} 的知识包"')
    parts.append(f"slug: \"{slug}\"")
    parts.append(f"date: {article_meta.get('date', '')}")
    parts.append(f"category: [{tags_str}]")
    parts.append(f'source_url: "{article_meta.get("url", "")}"')
    parts.append("agent_created: true")
    parts.append("---")
    parts.append("")

    # ── 描述 ──────────────────────────────────────
    parts.append(f"# {d_title} · 知识包")
    parts.append("")
    parts.append(f"> 本文由 article-distiller 从 [{article_meta.get('title', d_title)}]"
                 f"({article_meta.get('url', '')}) 蒸馏生成。")
    if source_notes:
        parts.append(f"> {source_notes}")
    parts.append("")

    # ── 核心速览 ──────────────────────────────────
    if quick_scan:
        parts.append("## 核心速览")
        parts.append("")
        for item in quick_scan:
            parts.append(f"- {item}")
        parts.append("")

    # ── 概念词典 ──────────────────────────────────
    # 从所有 section 的 concept_explainers 里提取概念定义
    concept_entries = []
    for sec in sections:
        tag = sec.get("tag") or ""
        for expl in sec.get("concept_explainers") or []:
            term = expl.get("term") or ""
            definition = expl.get("definition") or ""
            analogy = expl.get("analogy") or ""
            if term:
                concept_entries.append({
                    "term": term,
                    "definition": definition,
                    "analogy": analogy,
                    "context": tag,
                })

    if concept_entries:
        parts.append("## 概念词典")
        parts.append("")
        for entry in concept_entries:
            term = entry["term"]
            definition = entry["definition"]
            analogy = entry["analogy"]
            parts.append(f"### {term}")
            if entry["context"]:
                parts.append(f"*分类: {entry['context']}*")
            parts.append("")
            if definition:
                parts.append(definition)
                parts.append("")
            if analogy:
                parts.append(f"**类比**: {analogy}")
                parts.append("")

    # ── 核心方法论 ────────────────────────────────
    method_sections = []
    for sec in sections:
        title = sec.get("title") or ""
        content = sec.get("content") or ""
        if title and content:
            method_sections.append({"title": title, "content": content})

    if method_sections:
        parts.append("## 核心方法论")
        parts.append("")
        for sec in method_sections:
            parts.append(f"### {sec['title']}")
            parts.append("")
            parts.append(sec["content"])
            parts.append("")

            # 附带这个 section 的类比
            for analogy in sec.get("analogies") or []:  # type: ignore
                concept = analogy.get("concept") or ""
                analogy_text = analogy.get("analogy") or ""
                if concept and analogy_text:
                    parts.append(f"- **{concept}**: {analogy_text}")
            parts.append("")

    # ── 行动指南 ──────────────────────────────────
    if action_card and (action_card.get("items") or action_card.get("code_block")):
        parts.append("## 行动指南")
        parts.append("")
        for item in action_card.get("items") or []:
            parts.append(f"- {item}")
        parts.append("")

        code_block = action_card.get("code_block") or ""
        if code_block:
            parts.append("```")
            parts.append(code_block)
            parts.append("```")
            parts.append("")

    # ── 带走清单 ──────────────────────────────────
    if takeaway_list:
        parts.append("## 要点清单")
        parts.append("")
        for item in takeaway_list:
            clean = item.replace("\u2705", "").strip()
            parts.append(f"- {clean}")
        parts.append("")

    # ── 使用说明 ──────────────────────────────────
    parts.append("---")
    parts.append("")
    parts.append("*此知识包由 article-distiller 自动生成。加载此 skill 后，AI 可基于本文的方法论和概念定义回答相关问题。*")

    content = "\n".join(parts)
    file_path = os.path.join(out_dir, f"{slug}.md")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    return file_path


def get_skills_dir() -> str:
    """返回 skill 输出目录路径。"""
    return _SKILLS_DIR


def list_generated_skills() -> list:
    """列出已生成的所有领域 skill。"""
    if not os.path.exists(_SKILLS_DIR):
        return []
    return sorted(
        f for f in os.listdir(_SKILLS_DIR) if f.endswith(".md")
    )
