#!/usr/bin/env python3
"""article-distiller 主入口：把任意网页文章二次解读成图文 HTML / Markdown。

v9.17：深度文章独立入口、动态媒体发现与可移植发布门禁。

用法示例：
  # 全自动（需要 LLM key）—— 默认输出正文版 HTML
  python run.py https://example.com/article

  # 正文版同时输出 HTML + Markdown + 生成领域 skill
  python run.py https://example.com/article --both --gen-skill

  # 没 key：先抓取 + 生成 prompt 包
  python run.py https://example.com/article --source-only -o pack.json

  # 抓不到正文时：从纯文本、Markdown、PDF 或 Word 读取
  python run.py --from-text raw.txt --title "标题"
  python run.py article.pdf --both -o out
  python run.py report.docx --both -o out

  # 拿到 prompt 包跑完 LLM 后，回来渲染
  python run.py --render pack.json distilled.json -o out --both

  # 查看概念索引统计
  python distill.py --index-stats
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from urllib.parse import urlsplit

from dependency_bootstrap import ensure_python_dependencies, runtime_python_check

_OPTIONAL_MODE_FILES = ("onepager_renderer.py", "card_renderer.py")
DEEP_ONLY = (
    os.environ.get("ARTICLE_DISTILLER_DEEP_ONLY") == "1"
    or not all(os.path.isfile(os.path.join(os.path.dirname(__file__), name)) for name in _OPTIONAL_MODE_FILES)
)

runtime_python_check()
ensure_python_dependencies(["trafilatura", "lxml_html_clean", "pypdf"])

from fetcher import Article, article_from_text, fetch_article, merge_page_assets, merge_page_assets_file
from dynamic_media import discover_dynamic_page_assets
from file_ingest import article_from_file
from distiller import _editorial_review_prompt_for_modes, build_manual_prompt, distill
from renderer import render_html
from md_renderer import render_md
from article_imagegen import enhance_article_images
from evidence import normalize_distilled, normalize_url, url_key
from editorial_quality import assert_publishable, audit_distilled
from language_quality import apply_safe_language_fixes
from media_audit import assert_rendered_media
from repository_reader import enrich_github_article
import concept_index
import skill_generator

# These imports belong to the separately distributed onepager/cards Skills.
# Keep them optional so the deep-article package can be installed on its own.
try:
    from onepager_renderer import render_onepager_html, render_onepager_md
except ModuleNotFoundError:
    render_onepager_html = render_onepager_md = None
try:
    from card_renderer import render_card_deck_html, resolve_visual_system
except ModuleNotFoundError:
    render_card_deck_html = resolve_visual_system = None
try:
    from xhs_imagegen import enhance_xhs_images
except ModuleNotFoundError:
    enhance_xhs_images = None
try:
    from publish_shell import write_publish_shell
except ModuleNotFoundError:
    write_publish_shell = None


def _load_mode_adapter(path: str | None, output_format: str):
    """Load a single-output implementation supplied by a sibling skill."""
    if not path:
        return None
    if output_format == "all":
        raise ValueError("--mode-adapter 只支持单一输出格式，不能与 --format all 同用")
    adapter_path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(adapter_path):
        raise ValueError(f"输出模式适配器不存在：{adapter_path}")
    spec = importlib.util.spec_from_file_location("article_distiller_mode_adapter", adapter_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"无法加载输出模式适配器：{adapter_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    mode = str(getattr(module, "MODE", "") or "")
    if mode != output_format:
        raise ValueError(
            f"输出模式适配器声明 MODE={mode or '(空)'}，与 --format {output_format} 不一致"
        )
    required = (
        "SYSTEM_PROMPT",
        "EDITORIAL_REVIEW_PROMPT",
        "audit_distilled",
        "choose_preferred",
        "assert_publishable",
        "render_html",
        "render_markdown",
    )
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise ValueError(f"输出模式适配器缺少接口：{', '.join(missing)}")
    return module


def _quality_api(args):
    adapter = getattr(args, "mode_adapter", None)
    return (
        getattr(adapter, "audit_distilled", audit_distilled),
        getattr(adapter, "assert_publishable", assert_publishable),
    )


def _ts() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _stage_checkpoint_dir(args, article: Article) -> str | None:
    if getattr(args, "no_stage_cache", False):
        return None
    explicit = str(getattr(args, "stage_cache_dir", "") or "").strip()
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    if args.output:
        return os.path.abspath(os.path.expanduser(str(args.output))) + ".distill-cache"
    identity = article.url or article.content_hash or article.title or article.text[:200]
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return os.path.abspath(os.path.join(".article-distiller-cache", key))


def _article_from_snapshot(value: dict) -> Article:
    return Article(
        url=str(value.get("url") or ""),
        title=str(value.get("title") or ""),
        author=str(value.get("author") or ""),
        date=str(value.get("date") or ""),
        text=str(value.get("text") or ""),
        text_chars=int(value.get("text_chars") or len(str(value.get("text") or ""))),
        error=None,
        retrieved_at=str(value.get("retrieved_at") or ""),
        content_hash=str(value.get("content_hash") or ""),
        source_links=list(value.get("source_links") or []),
        source_type=str(value.get("source_type") or "original"),
        media_assets=list(value.get("media_assets") or []),
        repository_files=list(value.get("repository_files") or []),
        repository_read=dict(value.get("repository_read") or {}),
        media_discovery=dict(value.get("media_discovery") or {}),
    )


def _save_source_snapshot(
    checkpoint_dir: str | None,
    article: Article,
    evidence_articles: list[Article],
) -> str | None:
    """Persist the exact fetched inputs so anti-bot failures can resume safely."""
    if not checkpoint_dir or not article.text:
        return None
    directory = os.path.abspath(checkpoint_dir)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "source.json")
    temporary = os.path.join(directory, f".source.{os.getpid()}.tmp")
    payload = {
        "version": 1,
        "created_at": time.time(),
        "requested_url": article.url,
        "article": article.to_dict(),
        "evidence_articles": [item.to_dict() for item in evidence_articles],
    }
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)
    return path


def _load_source_snapshot(
    checkpoint_dir: str | None,
    requested_url: str,
) -> tuple[Article, list[Article], str] | None:
    if not checkpoint_dir:
        return None
    path = os.path.join(os.path.abspath(checkpoint_dir), "source.json")
    try:
        with open(path, encoding="utf-8") as handle:
            stored = json.load(handle)
        created_at = float(stored.get("created_at") or os.path.getmtime(path))
        max_age = max(1, int(os.getenv("DISTILL_STAGE_CACHE_MAX_AGE_SECONDS", "86400")))
        article_data = stored.get("article")
        evidence_data = stored.get("evidence_articles") or []
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if time.time() - created_at > max_age:
        return None
    if not isinstance(article_data, dict) or not isinstance(evidence_data, list):
        return None
    snapshot_url = str(stored.get("requested_url") or article_data.get("url") or "")
    if url_key(snapshot_url) != url_key(requested_url):
        return None
    article = _article_from_snapshot(article_data)
    if not article.text:
        return None
    evidence = [
        _article_from_snapshot(item)
        for item in evidence_data
        if isinstance(item, dict) and item.get("text")
    ]
    return article, evidence, path


def _get_article(args) -> Article:
    if args.from_text:
        try:
            return article_from_file(
                args.from_text,
                url=args.url or "",
                title=args.title or "",
                author=args.author or "",
            )
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            sys.exit(f"[错误] {exc}")
    if args.url and os.path.isfile(os.path.expanduser(args.url)):
        try:
            return article_from_file(
                args.url,
                title=args.title or "",
                author=args.author or "",
            )
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            sys.exit(f"[错误] {exc}")
    if getattr(args, "chart_ocr", False):
        return fetch_article(args.url, chart_ocr=True)
    return fetch_article(args.url)


def _merge_page_assets_arg(args, article: Article) -> None:
    path = str(getattr(args, "page_assets", "") or "").strip()
    if not path:
        return
    try:
        added = merge_page_assets_file(article, path)
    except ValueError as exc:
        sys.exit(f"[错误] {exc}")
    print(
        f"[浏览器素材] 已回灌 {added['links']} 条候选来源、{added['media']} 个媒体素材",
        file=sys.stderr,
    )
    discovery = added.get("discovery") if isinstance(added.get("discovery"), dict) else {}
    if discovery.get("status") == "completed":
        article.media_discovery = {
            **discovery,
            "status": "completed",
            "method": str(discovery.get("method") or "page_assets"),
            "added_count": added["media"],
        }


def _enrich_dynamic_media(args, article: Article) -> None:
    """Render the source page and merge media missed by the raw HTML fetcher."""
    if getattr(args, "no_dynamic_media", False):
        article.media_discovery = {"status": "skipped", "reason": "用户显式关闭动态媒体发现"}
        return
    if urlsplit(str(article.url or "")).scheme not in {"http", "https"}:
        article.media_discovery = {"status": "skipped", "reason": "本地文件不需要动态网页媒体发现"}
        return
    prior = article.media_discovery if isinstance(article.media_discovery, dict) else {}
    if prior.get("status") == "completed":
        return
    try:
        ensure_python_dependencies(["playwright"])
    except RuntimeError as exc:
        sys.exit(f"[媒体发现] {exc}\n可显式使用 --no-dynamic-media 跳过，但成品将不具备动态媒体完整性保证。")
    result = discover_dynamic_page_assets(
        article.url,
        timeout_ms=max(5000, int(getattr(args, "dynamic_media_timeout", 25000) or 25000)),
    )
    status = str(result.get("status") or "failed")
    if status != "completed":
        article.media_discovery = {
            "status": status,
            "reason": str(result.get("reason") or "动态媒体发现未完成"),
        }
        sys.exit(
            "[媒体发现] 无法完成动态页面媒体清单："
            + article.media_discovery["reason"]
            + "\n可在浏览器导出 page-assets 后重跑，或显式使用 --no-dynamic-media 跳过。"
        )
    added = merge_page_assets(article, {"media": list(result.get("media") or [])})
    article.media_discovery = {
        "status": "completed",
        "reason": "",
        "discovered_count": len(result.get("media") or []),
        "added_count": added["media"],
    }
    print(
        f"[动态媒体] 浏览器发现 {article.media_discovery['discovered_count']} 项，"
        f"新增登记 {added['media']} 项",
        file=sys.stderr,
    )


def _enrich_primary_repository(args, article: Article) -> None:
    """Deep-read a GitHub repository even when it is the primary input URL."""
    if getattr(args, "no_repo_deep_read", False):
        article.repository_read = {"status": "skipped", "reason": "用户显式关闭仓库深读"}
        return
    if getattr(article, "repository_files", None):
        return
    files = enrich_github_article(
        article,
        max_files=max(0, int(getattr(args, "repo_file_limit", 6) or 0)),
    )
    if files:
        print(f"[仓库深读] 主链接已读取 {len(files)} 个关键文件", file=sys.stderr)
    elif str((article.repository_read or {}).get("status") or "") == "failed":
        sys.exit(f"[仓库深读] {(article.repository_read or {}).get('reason') or '未能读取关键文件'}")


def _site_key(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _version_tokens(value: str) -> set[str]:
    return {
        match.lower().removeprefix("v").replace("_", ".").replace("-", ".")
        for match in re.findall(r"\b(?:v?\d+(?:[._-]\d+)+)\b", value or "", flags=re.IGNORECASE)
    }


def _topic_tokens(value: str) -> set[str]:
    """Return stable topic words for ranking same-site supporting articles."""
    return {
        token
        for token in re.findall(r"[a-z0-9]{2,}", (value or "").casefold())
        if token not in {
            "about", "after", "blog", "cloudflare", "from", "github", "home",
            "https", "into", "news", "post", "posts", "that", "their", "this",
            "using", "with", "www",
        }
    }


def _official_link_score(source: dict, article: Article | str) -> int:
    article_url = article.url if isinstance(article, Article) else str(article or "")
    article_title = article.title if isinstance(article, Article) else ""
    url = normalize_url(str(source.get("url") or ""))
    if not url or source.get("fetched"):
        return -1
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    title = str(source.get("title") or "").lower()
    score = 0
    if _site_key(url) == _site_key(article_url):
        score += 2
        overlap = _topic_tokens(f"{path} {title}") & _topic_tokens(f"{article_url} {article_title}")
        if overlap and not any(token in path for token in ("/tag/", "/category/", "/author/")):
            score += 2
        score += min(len(overlap), 4) * 3
    score += {
        "huggingface.co": 7,
        "github.com": 6,
        "arxiv.org": 6,
    }.get(host, 2 if host.startswith("docs.") else 0)
    for token in ("model", "model-card", "hugging face", "huggingface", "github", "paper", "arxiv", "docs", "documentation", "license", "announcement"):
        if token in path or token in title:
            score += 2
    source_versions = _version_tokens(f"{path} {title}")
    article_versions = _version_tokens(f"{article_url} {article_title}")
    if source_versions:
        score += 3
    if source_versions and article_versions:
        score += 6 if source_versions & article_versions else -20
    if any(token in path or token in title for token in ("announcement", "introducing", "release", "newsroom")):
        score += 4
    for token in ("login", "signup", "pricing", "contact", "about", "careers", "privacy", "terms", "status"):
        if token in path or token in title:
            score -= 4
    if path in {"", "/"} or re.fullmatch(r"/(?:blog/)?(?:tag|category)/[^/]+/?", path):
        score -= 10
    if any(token in path for token in ("/tag/", "/category/", "/author/")):
        score -= 8
    if host == "github.com" and len([part for part in path.split("/") if part]) < 2:
        score -= 10
    return score


def _discovered_official_targets(article: Article, limit: int) -> list[dict]:
    ranked = sorted(
        (
            (_official_link_score(source, article), source)
            for source in (article.source_links or [])
            if isinstance(source, dict)
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    return [
        {
            "url": normalize_url(str(source.get("url") or "")),
            "source_type": "official",
            "origin": "discovered",
            "priority": 100 + score,
        }
        for score, source in ranked
        if score >= 4
    ][:limit]


def _research_link_score(source: dict) -> int:
    """Score source links that are worth reading even when they are not publisher-owned."""
    url = normalize_url(str(source.get("url") or ""))
    if not url or source.get("fetched"):
        return -1
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    title = str(source.get("title") or "").lower()
    score = 0
    if host in {"arxiv.org", "doi.org", "github.com", "huggingface.co"}:
        score += 8
    if host.endswith((".gov", ".edu")):
        score += 5
    if path.endswith(".pdf"):
        score += 5
    if any(token in host for token in ("nature.com", "science.org", "springer.com", "sciencedirect.com", "mdpi.com")):
        score += 4
    if any(token in f"{path} {title}" for token in (
        "paper", "study", "research", "report", "survey", "dataset", "benchmark",
        "artificial intelligence", "ai ", "token",
        "论文", "研究", "报告", "调查", "数据集", "基准", "人工智能",
    )):
        score += 3
    if any(token in f"{host}{path}" for token in (
        "facebook.com/sharer", "twitter.com/intent", "linkedin.com/sharearticle",
        "/login", "/signup", "/privacy", "/terms", "/careers",
    )):
        score -= 12
    return score


def _discovered_research_targets(article: Article, limit: int) -> list[dict]:
    ranked = sorted(
        (
            (_research_link_score(source), source)
            for source in (article.source_links or [])
            if isinstance(source, dict)
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    targets = []
    for score, source in ranked:
        if score < 4 or len(targets) >= limit:
            continue
        url = normalize_url(str(source.get("url") or ""))
        explicit_role = str(source.get("source_type") or "").strip().lower()
        if explicit_role not in {"official", "supplemental", "independent"}:
            host = (urlsplit(url).hostname or "").lower()
            explicit_role = (
                "official"
                if _site_key(url) == _site_key(article.url)
                or host in {"github.com", "huggingface.co"}
                else "supplemental"
            )
        targets.append({
            "url": url,
            "source_type": explicit_role,
            "origin": str(source.get("origin") or "research_discovery"),
            "priority": 100 + score,
        })
    return targets


def _get_evidence_articles(args, article: Article) -> list[Article]:
    """抓取补充材料并登记来源角色；只有 independent 可提升交叉核验。"""
    result = []
    article.source_links = list(article.source_links or [])
    original_key = url_key(article.url)
    targets = []
    for raw_url in getattr(args, "independent_url", None) or []:
        targets.append({"url": raw_url, "source_type": "independent", "origin": "explicit", "priority": 400})
    for raw_url in getattr(args, "official_url", None) or []:
        targets.append({"url": raw_url, "source_type": "official", "origin": "explicit", "priority": 350})
    for raw_url in getattr(args, "evidence_url", None) or []:
        role = "official" if _site_key(raw_url) == _site_key(article.url) else "supplemental"
        targets.append({"url": raw_url, "source_type": role, "origin": "explicit", "priority": 300})
    if not getattr(args, "no_discover_official", False):
        discovery_limit = max(0, int(getattr(args, "official_source_limit", 3) or 0))
        targets.extend(_discovered_research_targets(article, discovery_limit))
        targets.extend(_discovered_official_targets(
            article,
            discovery_limit,
        ))

    unique_by_key = {}
    for sequence, target in enumerate(targets):
        url = normalize_url(str(target.get("url") or ""))
        key = url_key(url)
        if not key:
            continue
        if original_key and key == original_key:
            print(f"[证据提示] 原文 URL 不能作为补充证据，已忽略：{url}", file=sys.stderr)
            continue
        candidate = {**target, "url": url, "_sequence": sequence}
        previous = unique_by_key.get(key)
        if previous is not None:
            print(f"[证据提示] 已合并重复 URL：{url}", file=sys.stderr)
        if previous is None or int(candidate.get("priority") or 0) > int(previous.get("priority") or 0):
            unique_by_key[key] = candidate

    unique_targets = sorted(
        unique_by_key.values(),
        key=lambda item: (
            -int(item.get("priority") or 0),
            int(item.get("_sequence") or 0),
        ),
    )

    if len(unique_targets) > 5:
        print(f"[证据提示] 最多使用 5 个补充来源，已忽略其余 {len(unique_targets) - 5} 个。", file=sys.stderr)

    for target in unique_targets[:5]:
        url = target["url"]
        role = str(target.get("source_type") or "supplemental")
        if getattr(args, "chart_ocr", False):
            ev = fetch_article(url, source_type=role, chart_ocr=True)
        else:
            ev = fetch_article(url, source_type=role)
        if ev.error or not ev.text:
            print(f"[证据警告] 无法抓取 {url}：{ev.error or '正文为空'}", file=sys.stderr)
            continue
        if original_key and url_key(ev.url) == original_key:
            print(f"[证据提示] 该 URL 最终指向原文，已忽略：{url}", file=sys.stderr)
            continue
        if role == "official" and not getattr(args, "no_repo_deep_read", False):
            enrich_github_article(
                ev,
                max_files=max(0, int(getattr(args, "repo_file_limit", 6) or 0)),
            )
            if str((ev.repository_read or {}).get("status") or "") == "failed":
                print(
                    f"[仓库深读警告] {ev.url}：{ev.repository_read.get('reason') or '未能读取关键文件'}",
                    file=sys.stderr,
                )
        result.append(ev)
        article.source_links.append({
            "url": ev.url,
            "title": ev.title,
            "author": ev.author,
            "retrieved_at": ev.retrieved_at,
            "content_hash": ev.content_hash,
            "source_type": role,
            "fetched": True,
            "origin": target.get("origin") or "explicit",
        })
        for repo_source in ev.source_links or []:
            if not isinstance(repo_source, dict) or repo_source.get("origin") != "repository_deep_read":
                continue
            article.source_links.append(dict(repo_source))
        article.media_assets = list(article.media_assets or [])
        seen_media = {
            url_key(str(item.get("url") or ""))
            for item in article.media_assets
            if isinstance(item, dict) and item.get("url")
        }
        for raw_asset in ev.media_assets or []:
            if len(article.media_assets) >= 30:
                break
            if not isinstance(raw_asset, dict) or not raw_asset.get("url"):
                continue
            media_key = url_key(str(raw_asset.get("url") or ""))
            if not media_key or media_key in seen_media:
                continue
            seen_media.add(media_key)
            asset = dict(raw_asset)
            asset["id"] = f"media-{len(article.media_assets) + 1}"
            asset["source_url"] = ev.url
            asset["source_type"] = f"{role}_media"
            article.media_assets.append(asset)
    return result


def _source_counts(items: list[Article]) -> str:
    counts = {"official": 0, "supplemental": 0, "independent": 0}
    for item in items:
        role = str(getattr(item, "source_type", "supplemental") or "supplemental")
        counts[role] = counts.get(role, 0) + 1
    return f"官方附件 {counts.get('official', 0)} · 补充材料 {counts.get('supplemental', 0)} · 独立来源 {counts.get('independent', 0)}"


def _write_output(html_str: str | None, md_str: str | None, output: str | None, ts: str):
    """根据输出内容写文件，自动补后缀。"""
    wrote = []
    base = output or f"distilled-{ts}"

    if html_str:
        html_out = base if base.endswith(".html") else base + ".html"
        with open(html_out, "w", encoding="utf-8") as f:
            f.write(html_str)
        wrote.append(html_out)

    if md_str:
        if base.endswith(".html"):
            md_out = base[:-5] + ".md"
        elif base.endswith(".md"):
            md_out = base
        else:
            md_out = base + ".md"
        with open(md_out, "w", encoding="utf-8") as f:
            f.write(md_str)
        wrote.append(md_out)

    return wrote


def _write_format_output(base: str, suffix: str, html_str: str | None, md_str: str | None) -> list:
    """写指定格式的输出文件，文件名加 _{suffix} 后缀。"""
    wrote = []
    if html_str:
        out = f"{base}_{suffix}.html"
        with open(out, "w", encoding="utf-8") as f:
            f.write(html_str)
        wrote.append(out)
    if md_str:
        out = f"{base}_{suffix}.md"
        with open(out, "w", encoding="utf-8") as f:
            f.write(md_str)
        wrote.append(out)
    return wrote


def _post_distill(article: Article, distilled: dict, args, ts: str) -> list:
    """解读后处理：查互链 → 渲染 → 写文件 → 更新索引 → 生成 skill。

    返回写入的文件路径列表。
    支持 --format 参数：full / onepager / cards / all。
    """
    fmt = getattr(args, "format", "full") or "full"

    # 1. 查概念互链（渲染前查，这样当前文章也能显示已有相关文章）
    related = None
    if not args.no_index:
        related = concept_index.find_related(article.to_dict(), distilled)
        if related:
            print(f"[概念互链] 找到 {len(related)} 篇相关文章")

    # 2. 渲染
    base = args.output or f"distilled-{ts}"
    # 去掉后缀
    if base.endswith(".html"):
        base = base[:-5]
    elif base.endswith(".md"):
        base = base[:-3]

    wrote = []
    image_artifacts = []

    article_image_mode = getattr(args, "article_images", "off") or "off"
    planned_illustrations = [
        item for item in (distilled.get("illustration_plan") or [])
        if isinstance(item, dict) and item.get("scene") and item.get("after_section_id")
    ]
    rendered_illustrations = [
        item for item in planned_illustrations
        if item.get("status") == "generated" and (item.get("image_path") or item.get("image_data_uri"))
    ]
    if article_image_mode == "off" and planned_illustrations and not rendered_illustrations:
        print(
            f"[长文解释配图警告] 已规划 {len(planned_illustrations)} 张解释图，但当前模式为 off，"
            "成品不会显示图片。已获用户生图授权时请使用 --article-images generate。"
        )
    if fmt in ("full", "all") and article_image_mode != "off":
        try:
            image_result = enhance_article_images(
                article,
                distilled,
                base,
                mode=article_image_mode,
                max_images=getattr(args, "article_image_count", 2),
                size=getattr(args, "article_image_size", "1536x864"),
                relay_config=getattr(args, "relay_config", None),
                plan_file=getattr(args, "article_image_plan", None),
                reuse_manifest=getattr(args, "article_image_manifest", None),
            )
        except (OSError, ValueError, RuntimeError) as exc:
            sys.exit(f"[长文解释配图] {exc}")
        image_artifacts.append(image_result["manifest"])
        action = {
            "generate": "图片与提示词",
            "reuse": "复用图片与提示词",
        }.get(article_image_mode, "图片提示词")
        print(f"[长文解释配图] 已准备 {len(image_result['items'])} 组{action}")

    image_mode = getattr(args, "xhs_images", "off") or "off"
    if fmt in ("cards", "all") and image_mode != "off":
        requested_style = getattr(args, "xhs_style", "auto") or "auto"
        visual_system = resolve_visual_system(distilled, requested_style)
        try:
            image_result = enhance_xhs_images(
                article,
                distilled,
                base,
                mode=image_mode,
                visual_system=visual_system,
                max_images=getattr(args, "xhs_image_count", 3),
                size=getattr(args, "xhs_image_size", "1440x1920"),
                relay_config=getattr(args, "relay_config", None),
            )
        except (OSError, ValueError, RuntimeError) as exc:
            sys.exit(f"[小红书配图] {exc}")
        image_artifacts.append(image_result["manifest"])
        action = "图片与提示词" if image_mode == "generate" else "图片提示词"
        print(f"[小红书配图] 已准备 {len(image_result['items'])} 组{action}")

    if fmt in ("full", "all"):
        html_str = None if fmt == "full" and args.md_only else render_html(article, distilled, related=related)
        if html_str:
            try:
                media_render_audit = assert_rendered_media(article, distilled, html_str)
            except ValueError as exc:
                sys.exit(f"[媒体发布门禁] {exc}")
            quality = distilled.get("editorial_quality") if isinstance(distilled.get("editorial_quality"), dict) else {}
            distilled["editorial_quality"] = {**quality, "rendered_media_audit": media_render_audit}
        md_str = None
        if (args.both or fmt == "all") or (fmt == "full" and args.md_only):
            md_str = render_md(article, distilled, related=related)
        if fmt == "full":
            # 单格式：用原来的命名逻辑
            wrote.extend(_write_output(html_str, md_str, args.output, ts))
        else:
            # all 模式：加 _full 后缀
            wrote.extend(_write_format_output(base, "full", html_str, md_str))

    if fmt in ("onepager", "all"):
        adapter = getattr(args, "mode_adapter", None)
        html_renderer = getattr(adapter, "render_html", render_onepager_html)
        markdown_renderer = getattr(adapter, "render_markdown", render_onepager_md)
        op_html = html_renderer(article, distilled)
        op_md = markdown_renderer(article, distilled)
        if fmt == "onepager":
            wrote.extend(_write_output(op_html, op_md, args.output, ts))
        else:
            wrote.extend(_write_format_output(base, "onepager", op_html, op_md))

    if fmt in ("cards", "all"):
        card_html = render_card_deck_html(article, distilled, style_override=getattr(args, "xhs_style", "auto"))
        if fmt == "cards":
            wrote.extend(_write_output(card_html, None, args.output, ts))
        else:
            wrote.extend(_write_format_output(base, "cards", card_html, None))

    # 默认输出（防止 fmt 没匹配到任何分支）
    if not wrote:
        html_str = render_html(article, distilled, related=related)
        wrote.extend(_write_output(html_str, None, args.output, ts))

    if fmt == "all" and getattr(args, "publish_shell", False):
        shell_path = base + ".html"
        shell = write_publish_shell(
            shell_path,
            views={
                "full": f"{base}_full.html",
                "onepager": f"{base}_onepager.html",
                "cards": f"{base}_cards.html",
            },
            markdown_paths={
                "full": f"{base}_full.md",
                "onepager": f"{base}_onepager.md",
            },
            title=str(distilled.get("distilled_title") or article.title or "文章解读"),
            author=str(article.author or ""),
            source_url=str(article.url or ""),
            published_at=str(article.date or ""),
        )
        wrote.insert(0, shell)
        print(f"[统一发布] 已生成多视图入口：{shell}")

    wrote.extend(image_artifacts)

    # 3. 更新概念索引（渲染后更新，避免把自己当成相关文章）
    if not args.no_index:
        output_file = wrote[0] if wrote else ""
        concept_index.update_index(article.to_dict(), distilled, output_file)
        print(f"[概念索引] 已更新：{concept_index.get_index_stats()}")

    # 4. 生成领域 skill
    if args.gen_skill:
        skill_path = skill_generator.generate_skill(article.to_dict(), distilled)
        print(f"[领域 skill] 已生成：{skill_path}")

    return wrote


def cmd_full(args):
    article = _get_article(args)
    ensure_python_dependencies(["openai"])
    checkpoint_dir = _stage_checkpoint_dir(args, article)
    evidence_articles = None
    if article.error and not article.text:
        restored = _load_source_snapshot(checkpoint_dir, args.url or article.url)
        if restored is not None:
            article, evidence_articles, snapshot_path = restored
            print(
                f"[来源缓存] 当前网页抓取失败，复用 24 小时内的真实材料快照：{snapshot_path}",
                file=sys.stderr,
            )
    if article.error:
        print(f"[警告] {article.error}", file=sys.stderr)
        if not article.text:
            sys.exit(1)
    _merge_page_assets_arg(args, article)
    _enrich_dynamic_media(args, article)
    _enrich_primary_repository(args, article)
    if evidence_articles is None:
        evidence_articles = _get_evidence_articles(args, article)
        snapshot_path = _save_source_snapshot(checkpoint_dir, article, evidence_articles)
        if snapshot_path:
            print(f"[来源缓存] 已保存本次真实抓取材料：{snapshot_path}")
    print(
        f"[1/2] 抓取完成：{article.title or '(无标题)'} · {article.text_chars} 字 · {_source_counts(evidence_articles)}",
        flush=True,
    )

    if args.format == "all":
        required_modes = ("full", "onepager", "cards")
    else:
        required_modes = (args.format,)
    distilled = normalize_distilled(
        distill(
            article,
            config_path=args.config,
            evidence_articles=evidence_articles,
            two_stage=not args.single_pass,
            editorial_review=not args.single_pass and not args.skip_editorial_review,
            required_modes=required_modes,
            mode_adapter=getattr(args, "mode_adapter", None),
            checkpoint_dir=checkpoint_dir,
        ),
        article,
    )
    distilled, normalization_fixes = apply_safe_language_fixes(distilled)
    quality = distilled.get("editorial_quality") if isinstance(distilled.get("editorial_quality"), dict) else {}
    prior_fixes = list(quality.get("language_fixes") or [])
    all_fixes = prior_fixes + normalization_fixes
    distilled["editorial_quality"] = {
        **quality,
        "language_fixes": all_fixes,
        "language_fix_count": len(all_fixes),
    }
    research = distilled.get("research_ledger") if isinstance(distilled.get("research_ledger"), dict) else None
    audit, require_publishable = _quality_api(args)
    normalized_audit = audit(distilled, research, required_modes, strict_editorial=True)
    try:
        require_publishable(normalized_audit, "证据规范化后的文章")
    except ValueError as exc:
        sys.exit(f"[质量门禁] {exc}")
    print("[2/3] AI 解读与编辑审校完成")

    ts = _ts()
    wrote = _post_distill(article, distilled, args, ts)
    print(f"已生成：{', '.join(wrote)}")


def cmd_source_only(args):
    article = _get_article(args)
    if article.error:
        print(f"[警告] {article.error}", file=sys.stderr)
        if not article.text:
            sys.exit(1)
    _merge_page_assets_arg(args, article)
    _enrich_dynamic_media(args, article)
    _enrich_primary_repository(args, article)
    evidence_articles = _get_evidence_articles(args, article)
    print(f"[1/2] 抓取完成：{article.title or '(无标题)'} · {article.text_chars} 字 · {_source_counts(evidence_articles)}")

    required_modes = (args.format,) if args.format != "all" else ("full", "onepager", "cards")
    prompt = build_manual_prompt(
        article,
        evidence_articles=evidence_articles,
        required_modes=required_modes,
        mode_adapter=getattr(args, "mode_adapter", None),
    )
    adapter = getattr(args, "mode_adapter", None)
    editorial_prompt = getattr(
        adapter,
        "EDITORIAL_REVIEW_PROMPT",
        _editorial_review_prompt_for_modes(required_modes),
    )
    pack = {
        "article": article.to_dict(),
        "evidence_articles": [x.to_dict() for x in evidence_articles],
        "prompt": prompt,
        "editorial_review_prompt": editorial_prompt,
    }
    out = args.output or f"pack-{_ts()}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False, indent=2)
    print(f"[2/2] 已生成解读 prompt 包：{out}")
    print("下一步：把 pack 里的 prompt 复制到任意 LLM 跑出 JSON，")
    entrypoint = str(getattr(adapter, "ENTRYPOINT", "") or "") if adapter else ""
    if entrypoint:
        print(f"      再用：python {entrypoint} --render {out} distilled.json -o out")
    elif DEEP_ONLY:
        print(f"      再用：python run.py --render {out} distilled.json -o out --both")
    else:
        print(f"      再用：python distill.py --render {out} distilled.json -o out --format all")
        print(f"      或正文版：python distill.py --render {out} distilled.json -o out --format full --both")
        print(f"      或一页纸：python distill.py --render {out} distilled.json -o out --format onepager")
        print(f"      或图文卡片：python distill.py --render {out} distilled.json -o out --format cards")


def cmd_render(args):
    pack_path, dist_path = args.render
    if not os.path.exists(pack_path):
        sys.exit(f"[错误] pack 文件不存在：{pack_path}")
    with open(pack_path, "r", encoding="utf-8") as f:
        pack = json.load(f)
    art_d = pack.get("article", {})
    valid_keys = {
        "url", "title", "author", "date", "text", "text_chars", "error",
        "retrieved_at", "content_hash", "source_links", "source_type", "media_assets", "repository_files",
        "media_discovery", "repository_read",
    }
    art_d = {k: v for k, v in art_d.items() if k in valid_keys}
    article = Article(**art_d)

    if os.path.exists(dist_path):
        with open(dist_path, "r", encoding="utf-8") as f:
            distilled = json.load(f)
    else:
        try:
            distilled = json.loads(dist_path)
        except json.JSONDecodeError:
            sys.exit(f"[错误] distilled 既不是文件也不是合法 JSON：{dist_path}")

    distilled = normalize_distilled(distilled, article)
    distilled, render_fixes = apply_safe_language_fixes(distilled)
    if args.format == "all":
        required_modes = ("full", "onepager", "cards")
    else:
        required_modes = (args.format,)
    research = distilled.get("research_ledger") if isinstance(distilled.get("research_ledger"), dict) else None
    audit, require_publishable = _quality_api(args)
    render_audit = audit(
        distilled,
        research,
        required_modes,
        strict_editorial=True,
        semantic_coverage_strict=False,
    )
    try:
        require_publishable(render_audit, "待渲染文章")
    except ValueError as exc:
        sys.exit(f"[质量门禁] {exc}")
    quality = distilled.get("editorial_quality") if isinstance(distilled.get("editorial_quality"), dict) else {}
    prior_fixes = list(quality.get("language_fixes") or [])
    all_fixes = prior_fixes + render_fixes
    distilled["editorial_quality"] = {
        **quality,
        "language_fixes": all_fixes,
        "language_fix_count": len(all_fixes),
        "render_audit": render_audit,
    }
    ts = _ts()
    wrote = _post_distill(article, distilled, args, ts)
    print(f"已生成：{', '.join(wrote)}")


def cmd_index_stats():
    stats = concept_index.get_index_stats()
    print("=== 概念索引统计 ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    index = concept_index.list_all_concepts()
    articles = index.get("articles", [])
    if articles:
        print(f"\n已索引文章（{len(articles)} 篇）：")
        for a in articles:
            print(f"  - {a.get('title', '?')}")
            print(f"    URL: {a.get('url', '?')}")
            print(f"    概念: {', '.join(a.get('concepts', []))}")


def main():
    p = argparse.ArgumentParser(
        description="把网页文章二次解读成图文 HTML / Markdown（article-distiller v9.16）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("url", nargs="?", help="目标文章 URL，或本地 txt/md/html/pdf/docx/doc 文件路径")
    p.add_argument("--from-text", dest="from_text", help="从本地 txt/md/html/pdf/docx/doc 文件读取正文")
    p.add_argument("--config", help="config.json 路径（含 LLM 配置）")
    p.add_argument("--output", "-o", help="输出文件路径（自动补 .html / .md 后缀）")
    format_choices = ["full"] if DEEP_ONLY else ["full", "onepager", "cards", "all"]
    format_help = "输出格式：full=深度文章（固定）" if DEEP_ONLY else "输出格式：full=正文版(默认) / onepager=一页纸版 / cards=图文卡片 / all=三态全出"
    p.add_argument("--format", choices=format_choices, default="full", help=format_help)
    if not DEEP_ONLY:
        p.add_argument(
            "--mode-adapter",
            help="单一输出 Skill 的实现模块路径；由固定 Skill 入口传入",
        )
        p.add_argument(
            "--publish-shell",
            action="store_true",
            help="为 --format all 生成统一多视图入口（不改写各视图内容）",
        )
        p.add_argument(
            "--xhs-style",
            choices=["auto", "classic", "guizang-editorial", "guizang-kraft", "guizang-swiss"],
            default="auto",
            help="小红书视觉系统（仅 cards/all 模式）",
        )
        p.add_argument(
            "--xhs-images",
            choices=["off", "prompts", "generate"],
            default="off",
            help="小红书配图（仅 cards/all 模式）",
        )
        p.add_argument("--xhs-image-count", type=int, default=3,
                       help="封面加内容配图的总数，1-6（默认 3）")
        p.add_argument("--xhs-image-size", default="1440x1920",
                       help="relay-imagegen 输出尺寸（默认 1440x1920，3:4）")
    p.add_argument(
        "--article-images",
        choices=["off", "prompts", "generate", "reuse"],
        default="off",
        help="长文解释配图：off=关闭 / prompts=只生成提示词 / generate=生图 / reuse=复用已有图片",
    )
    p.add_argument("--article-image-count", type=int, default=2,
                   help="长文解释配图总数，1-3（默认 2）")
    p.add_argument("--article-image-size", default="1536x864",
                   help="长文解释配图尺寸（默认 1536x864，16:9；适合正文窄栏 Retina 显示）")
    p.add_argument("--article-image-plan",
                   help="可选的解释配图计划 JSON；用于精修旧文章而不改写完整 distilled JSON")
    p.add_argument("--article-image-manifest",
                   help="reuse 模式使用的已有配图 manifest；复用审核后的图片，不调用生图接口")
    p.add_argument("--relay-config",
                   help="可选 relay-imagegen 私有配置路径；不传时沿用其自动配置发现")
    p.add_argument("--source-only", action="store_true", help="只抓取 + 生成 prompt 包，不调 LLM")
    p.add_argument("--render", nargs=2, metavar=("PACK", "DISTILLED"),
                   help="渲染模式：传 pack.json 和 distilled.json 两个文件")
    p.add_argument("--title", help="配合 --from-text 手动指定标题")
    p.add_argument("--author", help="配合 --from-text 手动指定作者")
    p.add_argument(
        "--page-assets",
        help="合并浏览器或主题检索导出的 JSON：links/sources、images、videos、audio 会进入来源与媒体注册表",
    )
    p.add_argument(
        "--no-dynamic-media",
        action="store_true",
        help="显式跳过动态网页媒体发现；将失去 JS/iframe/懒加载素材完整性保证",
    )
    p.add_argument(
        "--dynamic-media-timeout",
        type=int,
        default=25000,
        help="动态页面媒体发现超时毫秒数（默认 25000）",
    )
    p.add_argument(
        "--evidence-url",
        action="append",
        default=[],
        help="补充一个待抓取 URL；同站按 official，跨站按 supplemental，不自动计为独立核验",
    )
    p.add_argument(
        "--official-url",
        action="append",
        default=[],
        help="补充一个官方模型卡、文档、仓库或许可证 URL；可重复使用",
    )
    p.add_argument(
        "--independent-url",
        action="append",
        default=[],
        help="补充一个确认独立于原发布方的来源 URL；可重复使用，成功抓取后可计入交叉核验",
    )
    p.add_argument(
        "--no-discover-official",
        action="store_true",
        help="关闭从原文直链自动发现并抓取官方模型卡、文档和仓库",
    )
    p.add_argument(
        "--official-source-limit",
        type=int,
        default=5,
        help="自动抓取官方附件数量，0-5（默认 5）",
    )
    p.add_argument(
        "--no-repo-deep-read",
        action="store_true",
        help="关闭官方 GitHub 仓库的受限关键文件读取",
    )
    p.add_argument(
        "--repo-file-limit",
        type=int,
        default=6,
        help="每个官方 GitHub 仓库最多读取的关键文本文件数，0-8（默认 6）",
    )
    p.add_argument(
        "--chart-ocr",
        action="store_true",
        help="对最多 5 张疑似图表运行本地 OCR，提取图内来源标签（默认关闭）",
    )
    p.add_argument(
        "--stage-cache-dir",
        help="研究、写作和审校阶段的恢复目录；默认使用 <output>.distill-cache",
    )
    p.add_argument(
        "--no-stage-cache",
        action="store_true",
        help="关闭阶段检查点；默认开启，并且只复用来源、模型和提示词指纹完全一致的结果",
    )
    cost_group = p.add_mutually_exclusive_group()
    cost_group.add_argument(
        "--single-pass",
        action="store_true",
        help="只调用一次 LLM（最低成本）；跳过研究账本和编辑审校",
    )
    cost_group.add_argument(
        "--skip-editorial-review",
        action="store_true",
        help="调用研究+写作两阶段，但跳过第三次编辑审校",
    )
    output_group = p.add_mutually_exclusive_group()
    output_group.add_argument("--md", dest="md_only", action="store_true",
                              help="只输出 Markdown（.md 文件），不输出 HTML（仅 full 格式有效）")
    output_group.add_argument("--both", action="store_true",
                              help="同时输出 HTML + Markdown（双文件，仅 full 格式有效）")
    p.add_argument("--no-index", action="store_true",
                   help="跳过概念索引更新和互链查询")
    p.add_argument("--gen-skill", action="store_true",
                   help="解读后自动生成领域 skill（.md 文件），让 AI 能按本文知识体系回答问题")
    p.add_argument("--index-stats", action="store_true",
                   help="查看概念索引统计信息")
    args = p.parse_args()

    if DEEP_ONLY:
        args.mode_adapter = None
        args.publish_shell = False
        args.xhs_images = "off"
        args.xhs_image_count = 3
        args.xhs_image_size = "1440x1920"
    else:
        try:
            args.mode_adapter = _load_mode_adapter(args.mode_adapter, args.format)
        except ValueError as exc:
            p.error(str(exc))

        if args.xhs_images != "off" and args.format not in {"cards", "all"}:
            p.error("--xhs-images 只适用于 --format cards 或 --format all")
        if args.publish_shell and args.format != "all":
            p.error("--publish-shell 需要配合 --format all")
    if args.article_images != "off" and args.format not in {"full", "all"}:
        p.error("--article-images 只适用于 --format full 或 --format all")
    if args.article_images == "reuse" and not args.article_image_manifest:
        p.error("--article-images reuse 需要 --article-image-manifest")
    if not DEEP_ONLY and not 1 <= args.xhs_image_count <= 6:
        p.error("--xhs-image-count 必须在 1 到 6 之间")
    if not 1 <= args.article_image_count <= 3:
        p.error("--article-image-count 必须在 1 到 3 之间")
    if not 0 <= args.official_source_limit <= 5:
        p.error("--official-source-limit 必须在 0 到 5 之间")
    if not 0 <= args.repo_file_limit <= 8:
        p.error("--repo-file-limit 必须在 0 到 8 之间")

    if args.index_stats:
        cmd_index_stats()
        return

    if args.render:
        cmd_render(args)
        return

    if not args.url and not args.from_text:
        p.error("需要提供文章 URL 或本地文件，或用 --from-text / --render / --index-stats")

    if args.source_only:
        cmd_source_only(args)
    else:
        cmd_full(args)


if __name__ == "__main__":
    main()
