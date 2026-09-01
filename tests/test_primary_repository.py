#!/usr/bin/env python3
"""主链接 GitHub 仓库深读的聚焦回归测试。"""

import sys
from pathlib import Path


SKILL_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
sys.path.insert(0, SKILL_SCRIPTS)

import repository_reader  # noqa: E402


def test_repository_selection_reads_core_rust_and_ignores_meta_noise():
    paths = [
        "README.md",
        "LICENSE",
        "CODE_OF_CONDUCT.md",
        "home-mixer/scorers/ranking_scorer.rs",
        "home-mixer/params/param.rs",
        "visibility-filtering/rules/registry.rs",
        "phoenix/QUICKSTART.md",
        "adult-content/config.py",
    ]
    tree = [
        {"type": "blob", "path": path, "size": 1_000, "download_url": f"https://raw.example/{path}"}
        for path in paths
    ]
    selected = repository_reader.select_repository_paths(tree, max_files=7)

    assert "home-mixer/scorers/ranking_scorer.rs" in selected
    assert "visibility-filtering/rules/registry.rs" in selected
    assert "phoenix/QUICKSTART.md" in selected
    assert "CODE_OF_CONDUCT.md" not in selected


def test_repository_enrichment_skips_duplicate_readme_and_caps_each_file():
    class Article:
        url = "https://github.com/example/repo"
        text = "主页面已经包含完整 README。" * 500
        repository_files = []
        source_links = []

    tree = [
        {"type": "blob", "path": "README.md", "size": 9_000, "download_url": "raw-readme"},
        {"type": "blob", "path": "LICENSE", "size": 9_000, "download_url": "raw-license"},
        {"type": "blob", "path": "src/ranking_scorer.rs", "size": 9_000, "download_url": "raw-ranker"},
        {"type": "blob", "path": "src/filter.rs", "size": 9_000, "download_url": "raw-filter"},
    ]
    original_json = repository_reader._fetch_json
    original_tree = repository_reader.collect_repository_tree
    original_text = repository_reader._fetch_text
    repository_reader._fetch_json = lambda _url: {"default_branch": "main"}
    repository_reader.collect_repository_tree = lambda _url, **_kwargs: tree
    repository_reader._fetch_text = lambda _url: "x" * 9_000
    try:
        files = repository_reader.enrich_github_article(Article(), max_files=3, max_total_chars=9_000)
    finally:
        repository_reader._fetch_json = original_json
        repository_reader.collect_repository_tree = original_tree
        repository_reader._fetch_text = original_text

    assert len(files) == 3
    assert all(item["path"] != "README.md" for item in files)
    assert all(item["text_chars"] <= 3_000 for item in files)
    assert sum(item["text_chars"] for item in files) <= 9_000


def test_repository_failure_is_explicit():
    class Article:
        url = "https://github.com/example/missing"
        title = "Missing"
        text = ""
        repository_files = []
        source_links = []

    original_json = repository_reader._fetch_json
    original_tree = repository_reader.collect_repository_tree
    original_raw = repository_reader.discover_raw_repository_tree
    repository_reader._fetch_json = lambda _url: (_ for _ in ()).throw(OSError("offline"))
    repository_reader.collect_repository_tree = lambda _url, **_kwargs: []
    repository_reader.discover_raw_repository_tree = lambda *_args, **_kwargs: ("main", [])
    article = Article()
    try:
        files = repository_reader.enrich_github_article(article)
    finally:
        repository_reader._fetch_json = original_json
        repository_reader.collect_repository_tree = original_tree
        repository_reader.discover_raw_repository_tree = original_raw

    assert files == []
    assert article.repository_read["status"] == "failed"
    assert "未能读取任何关键文件" in article.repository_read["reason"]


if __name__ == "__main__":
    test_repository_selection_reads_core_rust_and_ignores_meta_noise()
    test_repository_enrichment_skips_duplicate_readme_and_caps_each_file()
    test_repository_failure_is_explicit()
    print("primary repository tests passed")
