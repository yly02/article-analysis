"""Bounded deep reading for official GitHub repositories."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, deque
from typing import Any
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


ALLOWED_SUFFIXES = (
    ".md", ".txt", ".json", ".yaml", ".yml",
    ".py", ".rs", ".go", ".java", ".kt", ".scala", ".swift",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".js", ".jsx", ".ts", ".tsx",
)
MAX_FILE_BYTES = 100_000


def _github_repo_parts(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    if (parsed.hostname or "").lower() != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        return None
    owner, repo = parts
    return owner, repo.removesuffix(".git")


def _fetch_json(url: str) -> Any:
    request = Request(url, headers={"User-Agent": "article-distiller", "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=12) as response:  # noqa: S310 - fixed GitHub API host
        return json.loads(response.read().decode("utf-8"))


def _fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "article-distiller"})
    with urlopen(request, timeout=12) as response:  # noqa: S310 - fixed raw.githubusercontent host
        raw = response.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        return ""
    return raw.decode("utf-8", errors="replace")


def _path_score(path: str, crowded_dirs: Counter) -> int | None:
    lowered = path.casefold()
    basename = path.rsplit("/", 1)[-1]
    base_lower = basename.casefold()
    if not lowered.endswith(ALLOWED_SUFFIXES) and base_lower not in {"license", "license.txt"}:
        return None
    if any(token in lowered for token in ("node_modules/", "vendor/", "dist/", "build/", "package-lock", "yarn.lock")):
        return None
    parent = path.rsplit("/", 1)[0] if "/" in path else ""
    index_like = any(token in base_lower for token in ("readme", "index", "router", "catalog", "manifest"))
    skill_file = base_lower == "skill.md"
    license_file = base_lower in {"license", "license.md", "license.txt"}
    score = 0
    if skill_file:
        score += 100
    if license_file:
        score += 85
    if index_like:
        score += 58
    if any(token in base_lower for token in ("config", "example", "cookbook", "usage")):
        score += 35
    if "/skills/" in f"/{lowered}" or lowered.startswith("skills/"):
        score += 24
    if any(token in lowered for token in ("templates/", "examples/", "scripts/", "config/")):
        score += 12
    if any(token in lowered for token in (
        "rank", "scor", "recommend", "retriev", "pipeline", "filter",
        "model", "train", "inference", "serve", "main", "architecture",
        "gatekeeper", "permission", "approval", "policy", "auth", "limit", "quota",
    )):
        score += 32
    if any(token in base_lower for token in (
        "main", "server", "pipeline", "ranker", "scorer", "model",
        "gatekeeper", "permission", "approval", "policy", "limit",
    )):
        score += 18
    if any(token in lowered for token in ("code_of_conduct", "contributing", "changelog", "third_party")):
        score -= 70
    if crowded_dirs[parent] > 20 and not (index_like or skill_file or license_file):
        score -= 8
    score -= min(path.count("/"), 6) * 2
    if lowered.endswith(".py"):
        score -= 5
    return score


def _directory_score(path: str) -> tuple[int, str]:
    """Rank directories before bounded traversal; higher-value product docs go first."""
    lowered = path.casefold().strip("/")
    basename = lowered.rsplit("/", 1)[-1]
    score = 0
    if lowered == "skills":
        score += 100
    if any(token in basename for token in ("music", "audio", "minimax")):
        score += 70
    if any(token in basename for token in (
        "src", "core", "model", "train", "rank", "scor", "recommend",
        "retriev", "pipeline", "filter", "mixer", "server", "visibility",
        "gatekeeper", "permission", "approval", "policy", "auth", "limit", "quota",
    )):
        score += 60
    if basename in {"packages", "services", "modules"}:
        score += 55
    if any(token in basename for token in ("docs", "examples", "cookbook", "config", "scripts")):
        score += 30
    if any(token in lowered for token in ("node_modules", "vendor", "dist", "build", "assets", "figures")):
        score -= 100
    score -= min(path.count("/"), 6) * 3
    return score, lowered


def collect_repository_tree(
    repo_api: str,
    max_directories: int = 12,
    diagnostics: list[str] | None = None,
) -> list[dict]:
    """Collect a small pseudo-tree with the GitHub Contents API.

    Large template repositories routinely time out on the recursive tree endpoint. This
    traversal deliberately reads only a handful of promising directories and returns the
    same blob-like shape consumed by ``select_repository_paths``.
    """
    tree: list[dict] = []
    pending: deque[str] = deque([""])
    visited: set[str] = set()
    while pending and len(visited) < max_directories:
        path = pending.popleft()
        if path in visited:
            continue
        visited.add(path)
        endpoint = f"{repo_api}/contents"
        if path:
            endpoint += f"/{quote(path, safe='/')}"
        try:
            listing = _fetch_json(endpoint)
        except Exception as exc:
            if diagnostics is not None:
                diagnostics.append(f"目录 {path or '/'}：{exc}")
            continue
        if not isinstance(listing, list):
            continue

        directories = []
        for item in listing:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            item_path = str(item["path"])
            item_type = str(item.get("type") or "")
            if item_type == "file":
                tree.append({
                    "type": "blob",
                    "path": item_path,
                    "size": int(item.get("size") or 0),
                    "download_url": str(item.get("download_url") or ""),
                })
            elif item_type == "dir" and _directory_score(item_path)[0] > -50:
                directories.append(item_path)
        directories.sort(key=lambda candidate: (-_directory_score(candidate)[0], _directory_score(candidate)[1]))
        for directory in directories[:10]:
            if directory not in visited and directory not in pending:
                pending.append(directory)
    return tree


def discover_raw_repository_tree(
    owner: str,
    repo: str,
    preferred_branch: str = "main",
    diagnostics: list[str] | None = None,
) -> tuple[str, list[dict]]:
    """Fallback when the unauthenticated GitHub API is rate-limited.

    Read a root README from raw.githubusercontent.com and follow only explicit textual
    links to decision-relevant files. This remains bounded and never clones the repo.
    """
    branches = list(dict.fromkeys([preferred_branch, "main", "master"]))
    for branch in branches:
        for readme_name in ("README.md", "readme.md"):
            readme_url = (
                f"https://raw.githubusercontent.com/{quote(owner)}/{quote(repo)}/"
                f"{quote(branch, safe='')}/{readme_name}"
            )
            try:
                readme = _fetch_text(readme_url).strip()
            except Exception as exc:
                if diagnostics is not None:
                    diagnostics.append(f"{branch}/{readme_name}：{exc}")
                continue
            if not readme:
                continue
            candidates = [readme_name]
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", readme):
                clean = target.strip().split("#", 1)[0].split("?", 1)[0]
                prefix = f"https://github.com/{owner}/{repo}/blob/{branch}/"
                if clean.startswith(prefix):
                    clean = clean[len(prefix):]
                if clean.startswith(("http://", "https://", "/", "#")):
                    continue
                if _path_score(clean, Counter()) is not None:
                    candidates.append(clean)
            candidates.extend(
                re.findall(
                    r"(?<![\w/])((?:skills|docs|examples|config|scripts)/[^\s`'\"()]+\.(?:md|txt|json|ya?ml|py))",
                    readme,
                    flags=re.IGNORECASE,
                )
            )
            tree = []
            for path in list(dict.fromkeys(candidates))[:40]:
                tree.append({
                    "type": "blob",
                    "path": path,
                    "size": 0,
                    "download_url": (
                        f"https://raw.githubusercontent.com/{quote(owner)}/{quote(repo)}/"
                        f"{quote(branch, safe='')}/{quote(path, safe='/')}"
                    ),
                })
            return branch, tree
    return preferred_branch, []


def _topic_terms(value: str) -> set[str]:
    stop = {
        "about", "after", "article", "before", "could", "from", "github", "into",
        "model", "project", "readme", "should", "their", "there", "these", "this",
        "using", "with", "代码", "功能", "项目", "系统", "模型", "文章",
    }
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}|[\u4e00-\u9fff]{2,8}", value or "")
        if token.casefold() not in stop
    }


def select_repository_paths(tree: list[dict], max_files: int = 6, topic_text: str = "") -> list[str]:
    """Select a small, diverse set of decision-relevant repository files."""
    blobs = [
        item for item in tree
        if isinstance(item, dict)
        and item.get("type") == "blob"
        and item.get("path")
        and int(item.get("size") or 0) <= MAX_FILE_BYTES
    ]
    crowded_dirs = Counter(
        str(item["path"]).rsplit("/", 1)[0] if "/" in str(item["path"]) else ""
        for item in blobs
    )
    topic_terms = _topic_terms(topic_text)
    ranked = []
    for item in blobs:
        path = str(item["path"])
        score = _path_score(path, crowded_dirs)
        if score is not None:
            lowered = path.casefold()
            score += min(36, sum(12 for term in topic_terms if term in lowered))
            ranked.append((score, path))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].casefold()))

    selected = []
    top_dir_counts: Counter = Counter()
    for _score, path in ranked:
        top_dir = path.split("/", 1)[0] if "/" in path else "__root__"
        if top_dir_counts[top_dir] >= 3:
            continue
        selected.append(path)
        top_dir_counts[top_dir] += 1
        if len(selected) >= max_files:
            break
    return selected


def enrich_github_article(article: Any, max_files: int = 6, max_total_chars: int = 24_000) -> list[dict]:
    """Read selected files from an official GitHub repository without broad crawling."""
    parts = _github_repo_parts(str(getattr(article, "url", "") or ""))
    if not parts:
        article.repository_read = {"status": "not_applicable", "reason": "不是 GitHub 仓库主页"}
        return []
    if max_files <= 0:
        article.repository_read = {"status": "skipped", "reason": "仓库文件上限为 0"}
        return []
    owner, repo = parts
    repo_api = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}"
    branch = "main"
    diagnostics: list[str] = []
    try:
        metadata = _fetch_json(repo_api)
        if isinstance(metadata, dict):
            branch = str(metadata.get("default_branch") or "main")
    except Exception as exc:
        diagnostics.append(f"仓库元数据：{exc}")
    tree = collect_repository_tree(repo_api, diagnostics=diagnostics)
    if not tree:
        branch, tree = discover_raw_repository_tree(owner, repo, branch, diagnostics=diagnostics)

    topic_text = " ".join([
        str(getattr(article, "title", "") or ""),
        str(getattr(article, "text", "") or "")[:8_000],
        owner,
        repo,
    ])
    selected_paths = select_repository_paths(tree, max_files=max_files + 2, topic_text=topic_text)
    downloads = {str(item.get("path")): str(item.get("download_url") or "") for item in tree}
    result = []
    total_chars = 0
    per_file_limit = max(2_000, min(6_000, max_total_chars // max(max_files, 1)))
    article_text = str(getattr(article, "text", "") or "")
    for path in selected_paths:
        if total_chars >= max_total_chars or len(result) >= max_files:
            break
        raw_url = downloads.get(path) or (
            f"https://raw.githubusercontent.com/{quote(owner)}/{quote(repo)}/"
            f"{quote(branch, safe='')}/{quote(path, safe='/')}"
        )
        try:
            content = _fetch_text(raw_url).strip()
        except Exception as exc:
            diagnostics.append(f"文件 {path}：{exc}")
            continue
        if not content:
            continue
        if path.rsplit("/", 1)[-1].casefold().startswith("readme"):
            if len(article_text) >= 2_000:
                continue
            sample = re.sub(r"\s+", " ", content[:500]).strip()
            normalized_article = re.sub(r"\s+", " ", article_text[:8_000])
            if sample and sample[:240] in normalized_article:
                continue
        remaining = max_total_chars - total_chars
        content = content[:min(per_file_limit, remaining)]
        total_chars += len(content)
        result.append({
            "path": path,
            "url": raw_url,
            "content": content,
            "text_chars": len(content),
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        })

    article.repository_files = result
    article.repository_read = {
        "status": "completed" if result else "failed",
        "reason": "" if result else "未能读取任何关键文件" + (f"；最近错误：{diagnostics[-1]}" if diagnostics else ""),
        "selected_count": len(selected_paths),
        "read_count": len(result),
        "errors": diagnostics[-5:],
    }
    article.source_links = list(getattr(article, "source_links", []) or [])
    for item in result:
        article.source_links.append({
            "url": item["url"],
            "title": item["path"],
            "source_type": "official",
            "fetched": True,
            "content_hash": item["content_hash"],
            "origin": "repository_deep_read",
        })
    return result
