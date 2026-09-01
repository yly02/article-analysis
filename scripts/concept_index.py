"""跨文章概念索引模块：维护本地概念→文章映射，实现互链网络。

每次解读完一篇文章后：
1. 抽取关键概念（category_tags / concept_explainers / section tags / takeaway keywords）
2. 存入本地索引文件
3. 查询时返回与当前文章概念重合的其他文章

索引文件位置：~/.article-distiller/concept_index.json，或 ARTICLE_DISTILLER_DATA_DIR 指定目录。
结构：
{
  "concepts": {
    "提示词工程": [
      {"title": "...", "url": "...", "file": "...", "date": "...", "slug": "..."}
    ]
  },
  "articles": [
    {"title": "...", "url": "...", "file": "...", "date": "...", "slug": "...", "concepts": [...]}
  ]
}
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from runtime_paths import user_data_file

_INDEX_FILE = str(user_data_file("concept_index.json"))
_INDEX_DIR = os.path.dirname(_INDEX_FILE)

# 这些词用于章节编排或泛化分类，不能证明两篇文章主题相关。
_GENERIC_CONCEPTS = {
    "ai", "事件", "主题", "主线", "入口", "分化", "判断", "变化", "机制",
    "案例", "结论", "定义", "方法", "核心方法", "能力", "实际能力", "定位",
    "训练方法", "评测数据", "数据", "背景", "原因", "结果", "影响", "问题",
    "目的", "边界", "风险", "选择", "控制", "流程", "技术", "产品", "工具",
    "应用", "落地", "追查", "对照", "冲突", "总结", "风向", "怪事",
}


def _is_linkable_concept(value: str) -> bool:
    text = str(value or "").strip()
    return len(text) >= 2 and text.casefold() not in _GENERIC_CONCEPTS


def _add_concept(concepts: set[str], value: str) -> None:
    text = str(value or "").strip()
    if _is_linkable_concept(text):
        concepts.add(text)


def _ensure_index_dir():
    os.makedirs(_INDEX_DIR, exist_ok=True)


def _load_index() -> dict:
    """加载索引文件，不存在则返回空结构。"""
    if not os.path.exists(_INDEX_FILE):
        return {"concepts": {}, "articles": []}
    try:
        with open(_INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"concepts": {}, "articles": []}


def _save_index(index: dict):
    """保存索引文件。"""
    _ensure_index_dir()
    with open(_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff\s-]", "", text)[:40].strip()
    s = re.sub(r"[\s_]+", "-", s)
    return s.lower().strip("-") or "article"


def extract_concepts(distilled: dict) -> list:
    """从解读 JSON 中抽取关键概念列表（去重）。"""
    concepts = set()

    # 1. category_tags
    for tag in distilled.get("category_tags") or []:
        _add_concept(concepts, tag)

    # 2. concept_explainers 里的 term
    for sec in distilled.get("sections") or []:
        for expl in sec.get("concept_explainers") or []:
            term = (expl.get("term") or "").strip()
            _add_concept(concepts, term)

    # 3. section title 里括号中的概念词（如"思维链（CoT）"→"思维链"）
    for sec in distilled.get("sections") or []:
        title = sec.get("title") or ""
        # 匹配"概念名（英文）"模式
        for m in re.finditer(r"([\u4e00-\u9fff]{2,})\uff08", title):
            _add_concept(concepts, m.group(1))

    return sorted(concepts)


def find_related(article_meta: dict, distilled: dict, max_results: int = 5) -> list:
    """查询索引，返回与当前文章概念重合的其他文章列表。

    返回格式：[{"title": "...", "url": "...", "file": "...", "date": "...",
               "shared_concepts": ["概念A", "概念B"], "relevance": 3}]
    """
    concepts = extract_concepts(distilled)
    if not concepts:
        return []

    index = _load_index()
    current_url = article_meta.get("url", "")

    # 统计每篇已索引文章的共享概念数
    related = []
    for existing in index.get("articles", []):
        # 排除当前文章自己（按 URL 或文件名）
        if existing.get("url") == current_url:
            continue

        existing_concepts = {
            concept for concept in existing.get("concepts", [])
            if _is_linkable_concept(concept)
        }
        shared = existing_concepts & set(concepts)
        if not shared:
            continue

        related.append({
            "title": existing.get("title", ""),
            "url": existing.get("url", ""),
            "file": existing.get("file", ""),
            "date": existing.get("date", ""),
            "shared_concepts": sorted(shared),
            "relevance": len(shared),
        })

    # 按重合度降序，取前 N
    related.sort(key=lambda x: x["relevance"], reverse=True)
    return related[:max_results]


def update_index(article_meta: dict, distilled: dict, output_file: str = ""):
    """把当前文章的概念写入索引。article_meta 含 title/url/date。

    output_file: 生成的 HTML/MD 文件路径（用于互链跳转）。
    """
    concepts = extract_concepts(distilled)
    if not concepts:
        return

    index = _load_index()
    url = article_meta.get("url", "")
    title = distilled.get("distilled_title") or article_meta.get("title", "")
    date = article_meta.get("date", "")
    slug = _slugify(title)

    entry = {
        "title": title,
        "url": url,
        "file": output_file,
        "date": date,
        "slug": slug,
        "concepts": concepts,
    }

    # 同一来源或同一成品文件都属于同一篇文章；标题和来源形式变化时保留最新版。
    normalized_output = os.path.realpath(os.path.abspath(output_file)) if output_file else ""
    articles = []
    for article in index.get("articles", []):
        same_url = bool(url and article.get("url") == url)
        existing_file = str(article.get("file") or "").strip()
        same_output = bool(
            normalized_output
            and existing_file
            and os.path.realpath(os.path.abspath(existing_file)) == normalized_output
        )
        if not same_url and not same_output:
            articles.append(article)
    articles.append(entry)
    for article in articles:
        article["concepts"] = sorted({
            concept for concept in article.get("concepts", [])
            if _is_linkable_concept(concept)
        })
    index["articles"] = articles

    # 从文章列表重建映射，同时清掉旧版本留下的通用概念和失效条目。
    concepts_map = {}
    for article in articles:
        for concept in article.get("concepts", []):
            concepts_map.setdefault(concept, []).append({
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "file": article.get("file", ""),
                "date": article.get("date", ""),
                "slug": article.get("slug", ""),
            })
    index["concepts"] = concepts_map

    _save_index(index)


def get_index_path() -> str:
    """返回索引文件路径。"""
    return _INDEX_FILE


def list_all_concepts() -> dict:
    """返回当前索引中所有概念→文章映射（供调试/展示用）。"""
    return _load_index()


def get_index_stats() -> dict:
    """返回索引统计信息。"""
    index = _load_index()
    return {
        "total_concepts": len(index.get("concepts", {})),
        "total_articles": len(index.get("articles", [])),
        "index_file": _INDEX_FILE,
    }
