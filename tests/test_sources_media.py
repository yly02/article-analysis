#!/usr/bin/env python3
"""来源角色、官方附件发现和原网页媒体的行为回归测试。"""

import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace


SKILL_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
sys.path.insert(0, SKILL_SCRIPTS)

import distill as cli  # noqa: E402
import fetcher  # noqa: E402
from editorial_quality import audit_distilled  # noqa: E402
from evidence import normalize_distilled  # noqa: E402
from fetcher import Article  # noqa: E402
from media_audit import audit_rendered_media  # noqa: E402
from renderer import render_html  # noqa: E402


def test_fetcher_extracts_links_and_content_media():
    page_url = "https://vendor.example/blog/launch"
    raw_html = """
    <html><body>
      <a href="/model/card">Model card</a>
      <img src="/assets/logo.svg" alt="Brand">
      <img src="https://cdn-avatars.example.com/user.png" alt="Avatar">
      <img data-src="/media/hero.webp" alt="Product interface">
      <img src="/media/chart.svg" alt="Vector chart">
      <video src="https://cdn.example/private.mp4?X-Amz-Signature=expired"></video>
      <video poster="/media/demo-poster.jpg" title="Workflow demo">
        <source src="/media/demo.mp4" type="video/mp4">
      </video>
      <uni-media
        or-mp4-video-url="https://storage.example.com/original_videos/custom-demo.mp4"
        alt-text="A product capability demo"
        video-title="Custom demo"
        section-header="Product demos">
      </uni-media>
    </body></html>
    """
    original_fetch = fetcher.trafilatura.fetch_url
    original_extract = fetcher.trafilatura.extract
    fetcher.trafilatura.fetch_url = lambda _url: raw_html

    def fake_extract(_html, **kwargs):
        if kwargs.get("output_format") == "json":
            return json.dumps({"title": "Launch", "author": "Vendor", "date": "2026-08-20"})
        return "正文内容"

    fetcher.trafilatura.extract = fake_extract
    try:
        article = fetcher.fetch_article(page_url)
    finally:
        fetcher.trafilatura.fetch_url = original_fetch
        fetcher.trafilatura.extract = original_extract

    assert article.source_links[0]["url"] == "https://vendor.example/model/card"
    assert article.source_links[0]["title"] == "Model card"
    assert [item["type"] for item in article.media_assets] == ["image", "video", "video"]
    assert article.media_assets[0]["url"] == "https://vendor.example/media/hero.webp"
    assert article.media_assets[1]["url"] == "https://vendor.example/media/demo.mp4"
    assert article.media_assets[1]["poster_url"] == "https://vendor.example/media/demo-poster.jpg"
    assert article.media_assets[2]["url"] == "https://storage.example.com/original_videos/custom-demo.mp4"
    assert article.media_assets[2]["alt"] == "A product capability demo"
    assert article.media_assets[2]["caption"] == "A product capability demo"
    assert article.media_assets[2]["section_title"] == "Product demos"
    assert article.media_assets[2]["asset_role"] == "demo"
    assert all(item["source_type"] == "original_media" for item in article.media_assets)


def test_remote_pdf_uses_pdf_text_extraction():
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b"fake-pdf"

    class FakePage:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    class FakeReader:
        def __init__(self, _stream):
            self.pages = [FakePage("研究摘要"), FakePage("实验结果")]
            self.metadata = {"/Title": "Remote Study", "/Author": "Researcher"}

    original_urlopen = fetcher.urlopen
    original_reader = fetcher.PdfReader
    fetcher.urlopen = lambda *_args, **_kwargs: FakeResponse()
    fetcher.PdfReader = FakeReader
    try:
        article = fetcher.fetch_article("https://lab.example/study.pdf", source_type="supplemental")
    finally:
        fetcher.urlopen = original_urlopen
        fetcher.PdfReader = original_reader

    assert article.error is None
    assert article.title == "Remote Study"
    assert article.author == "Researcher"
    assert article.text == "研究摘要\n\n实验结果"
    assert article.source_type == "supplemental"


def test_fetcher_discovers_lazy_background_and_embedded_media():
    page_url = "https://vendor.example/blog/dynamic"
    raw_html = """
    <html><body>
      <section style="background-image:url('/media/diagram.webp')">
        <img data-lazy-src="/media/lazy.png" alt="Lazy chart">
        <img data-srcset="/media/small.jpg 480w, /media/large.jpg 1200w" alt="Responsive result">
        <iframe src="https://www.youtube.com/embed/official-demo" title="Official demo"></iframe>
        <iframe src="https://customer-example.cloudflarestream.com/demo-id/iframe" title="Cloudflare Stream demo"></iframe>
      </section>
    </body></html>
    """
    original_fetch = fetcher.trafilatura.fetch_url
    original_extract = fetcher.trafilatura.extract
    fetcher.trafilatura.fetch_url = lambda _url: raw_html
    fetcher.trafilatura.extract = lambda _html, **kwargs: (
        json.dumps({"title": "Dynamic"}) if kwargs.get("output_format") == "json" else "动态正文"
    )
    try:
        article = fetcher.fetch_article(page_url)
    finally:
        fetcher.trafilatura.fetch_url = original_fetch
        fetcher.trafilatura.extract = original_extract

    urls = {item["url"] for item in article.media_assets}
    assert "https://vendor.example/media/diagram.webp" in urls
    assert "https://vendor.example/media/lazy.png" in urls
    assert "https://vendor.example/media/large.jpg" in urls
    embed = next(item for item in article.media_assets if "youtube.com/embed" in item["url"])
    assert embed["type"] == "video"
    assert embed["embed"] is True
    assert embed["asset_role"] == "demo"
    stream_embed = next(item for item in article.media_assets if "cloudflarestream.com" in item["url"])
    assert stream_embed["type"] == "video"
    assert stream_embed["embed"] is True
    assert stream_embed["asset_role"] == "demo"


def _fake_article(url, source_type):
    return Article(
        url=url,
        title=url,
        text="补充正文",
        text_chars=4,
        retrieved_at="2026-08-20T00:00:00+00:00",
        content_hash="hash-" + source_type,
        source_links=[],
        source_type=source_type,
        media_assets=[],
    )


def test_explicit_source_roles_are_not_conflated():
    article = Article(
        url="https://vendor.example/blog/launch",
        text="原文",
        source_links=[],
        media_assets=[],
    )
    args = SimpleNamespace(
        evidence_url=["https://vendor.example/docs", "https://news.example/story"],
        official_url=["https://github.com/vendor/model"],
        independent_url=["https://lab.example/retest"],
        no_discover_official=True,
        official_source_limit=3,
    )
    calls = []
    original_fetch = cli.fetch_article

    def fake_fetch(url, source_type="original"):
        calls.append((url, source_type))
        return _fake_article(url, source_type)

    cli.fetch_article = fake_fetch
    try:
        result = cli._get_evidence_articles(args, article)
    finally:
        cli.fetch_article = original_fetch

    assert {(item.url, item.source_type) for item in result} == {
        ("https://vendor.example/docs", "official"),
        ("https://news.example/story", "supplemental"),
        ("https://github.com/vendor/model", "official"),
        ("https://lab.example/retest", "independent"),
    }
    assert {role for _, role in calls} == {"official", "supplemental", "independent"}


def test_official_discovery_and_cross_check_boundary():
    article = Article(
        url="https://vendor.example/blog/launch",
        text="原文",
        source_links=[
            {"url": "https://huggingface.co/vendor/model", "title": "Hugging Face model card", "source_type": "discovered", "fetched": False},
            {"url": "https://github.com/vendor/model", "title": "GitHub repository", "source_type": "discovered", "fetched": False},
            {"url": "https://vendor.example/pricing", "title": "Pricing", "source_type": "discovered", "fetched": False},
        ],
        media_assets=[],
    )
    args = SimpleNamespace(
        evidence_url=[],
        official_url=[],
        independent_url=[],
        no_discover_official=False,
        official_source_limit=2,
    )
    original_fetch = cli.fetch_article
    cli.fetch_article = lambda url, source_type="original": _fake_article(url, source_type)
    try:
        discovered = cli._get_evidence_articles(args, article)
    finally:
        cli.fetch_article = original_fetch

    assert [item.url for item in discovered] == [
        "https://huggingface.co/vendor/model",
        "https://github.com/vendor/model",
    ]
    assert all(item.source_type == "official" for item in discovered)

    raw = {
        "fact_check": [{
            "claim": "模型已发布",
            "verdict": "交叉验证",
            "evidence": [{"url": "https://huggingface.co/vendor/model"}],
        }]
    }
    official_only = normalize_distilled(raw, article)
    assert official_only["fact_check"][0]["evidence_status"] == "source_only"
    assert official_only["fact_check"][0]["verdict"] == "原文声称"

    article.source_links.append({
        "url": "https://lab.example/retest",
        "source_type": "independent",
        "fetched": True,
        "retrieved_at": "2026-08-20T00:00:00+00:00",
        "content_hash": "independent-hash",
    })
    cross_checked = normalize_distilled({
        "fact_check": [{
            "claim": "独立复测已完成",
            "verdict": "交叉验证",
            "evidence": [{"url": "https://lab.example/retest"}],
        }]
    }, article)
    assert cross_checked["fact_check"][0]["evidence_status"] == "cross_checked"
    assert cross_checked["fact_check"][0]["verdict"] == "交叉验证"


def test_version_specific_sources_outrank_adjacent_releases():
    article = Article(
        url="https://vendor.example/blog/foundation",
        title="Introducing Model 2.5",
        text="原文",
        source_links=[
            {"url": "https://vendor.example/model/model-2-3", "title": "Model 2.3", "fetched": False},
            {"url": "https://vendor.example/model/model-2-5", "title": "Model 2.5", "fetched": False},
            {"url": "https://vendor.example/docs/overview", "title": "Documentation", "fetched": False},
        ],
        media_assets=[],
    )
    ranked = cli._discovered_official_targets(article, 3)
    assert ranked[0]["url"] == "https://vendor.example/model/model-2-5"
    assert all(item["url"] != "https://vendor.example/model/model-2-3" for item in ranked)


def test_discovered_sources_are_globally_ranked_before_limit():
    article = Article(
        url="https://vendor.example/post",
        title="主题",
        text="正文",
        text_chars=2,
        source_links=[],
        media_assets=[],
    )
    args = SimpleNamespace(
        independent_url=[], official_url=[], evidence_url=[],
        no_discover_official=False, official_source_limit=5,
        no_repo_deep_read=True, chart_ocr=False,
    )
    research = [
        {"url": f"https://research.example/{index}", "source_type": "supplemental", "origin": "research", "priority": 104}
        for index in range(5)
    ]
    official = [{
        "url": "https://vendor.example/high-value-case-study",
        "source_type": "official",
        "origin": "discovered",
        "priority": 140,
    }]
    originals = (
        cli._discovered_research_targets,
        cli._discovered_official_targets,
        cli.fetch_article,
    )
    cli._discovered_research_targets = lambda *_args, **_kwargs: research
    cli._discovered_official_targets = lambda *_args, **_kwargs: official
    cli.fetch_article = lambda url, source_type="original", **_kwargs: Article(
        url=url, title=url.rsplit("/", 1)[-1], text="补充正文", text_chars=4,
        source_type=source_type, source_links=[], media_assets=[],
    )
    try:
        result = cli._get_evidence_articles(args, article)
    finally:
        cli._discovered_research_targets, cli._discovered_official_targets, cli.fetch_article = originals

    assert len(result) == 5
    assert result[0].url == "https://vendor.example/high-value-case-study"
    assert all(item.url != "https://research.example/4" for item in result)


def test_same_site_topic_article_outranks_home_and_tag_pages():
    article = Article(
        url="https://blog.cloudflare.com/cloudflare-os/",
        title="Cloudflare OS: an open platform for agents, apps, and work",
        text="原文",
        source_links=[
            {"url": "https://github.com/cloudflare", "title": "Cloudflare", "fetched": False},
            {"url": "https://blog.cloudflare.com/tag/managed-components/", "title": "Managed Components", "fetched": False},
            {"url": "https://blog.cloudflare.com/how-we-use-ai-with-cloudflare-os", "title": "How we use AI with Cloudflare OS", "fetched": False},
            {"url": "https://github.com/cloudflare/cloudflare-os", "title": "Cloudflare OS repository", "fetched": False},
        ],
        media_assets=[],
    )
    ranked = cli._discovered_official_targets(article, 3)
    urls = [item["url"] for item in ranked]
    assert urls[0] == "https://blog.cloudflare.com/how-we-use-ai-with-cloudflare-os"
    assert "https://blog.cloudflare.com/tag/managed-components/" not in urls
    assert "https://github.com/cloudflare" not in urls


def test_discovered_github_repository_enters_bounded_deep_read():
    article = Article(
        url="https://vendor.example/blog/launch",
        title="Launch",
        text="原文",
        source_links=[
            {"url": "https://github.com/vendor/product", "title": "Product repository", "fetched": False},
        ],
        media_assets=[],
    )
    args = SimpleNamespace(
        evidence_url=[],
        official_url=[],
        independent_url=[],
        no_discover_official=False,
        official_source_limit=3,
        no_repo_deep_read=False,
        repo_file_limit=4,
        chart_ocr=False,
    )
    deep_reads = []
    original_fetch = cli.fetch_article
    original_enrich = cli.enrich_github_article
    cli.fetch_article = lambda url, source_type="original", **_kwargs: _fake_article(url, source_type)

    def fake_enrich(item, max_files=6):
        deep_reads.append((item.url, max_files))
        item.repository_files = [{"path": "src/policy.ts", "content": "policy"}]
        return item.repository_files

    cli.enrich_github_article = fake_enrich
    try:
        result = cli._get_evidence_articles(args, article)
    finally:
        cli.fetch_article = original_fetch
        cli.enrich_github_article = original_enrich

    assert result[0].url == "https://github.com/vendor/product"
    assert deep_reads == [("https://github.com/vendor/product", 4)]
    assert result[0].repository_files[0]["path"] == "src/policy.ts"


def test_discovered_research_links_include_papers_and_public_reports():
    article = Article(
        url="https://author.example/essay",
        title="AI essay",
        text="原文",
        source_links=[
            {"url": "https://arxiv.org/abs/2506.12605", "title": "study", "fetched": False},
            {"url": "https://labor.gov/reports/history.pdf", "title": "historical report", "fetched": False},
            {"url": "https://social.example/share", "title": "Share", "fetched": False},
        ],
        media_assets=[],
    )
    targets = cli._discovered_research_targets(article, 5)
    assert {item["url"] for item in targets} == {
        "https://arxiv.org/abs/2506.12605",
        "https://labor.gov/reports/history.pdf",
    }
    assert all(item["source_type"] == "supplemental" for item in targets)


def test_fetched_attachment_media_joins_the_registry():
    article = Article(
        url="https://vendor.example/blog/launch",
        text="原文",
        source_links=[],
        media_assets=[{
            "id": "media-1",
            "type": "image",
            "url": "https://vendor.example/original.jpg",
            "source_url": "https://vendor.example/blog/launch",
            "source_type": "original_media",
        }],
    )
    args = SimpleNamespace(
        evidence_url=[],
        official_url=["https://vendor.example/newsroom/release"],
        independent_url=[],
        no_discover_official=True,
        official_source_limit=5,
    )
    original_fetch = cli.fetch_article

    def fake_fetch(url, source_type="original"):
        fetched = _fake_article(url, source_type)
        fetched.media_assets = [{
            "id": "media-1",
            "type": "image",
            "url": "https://cdn.example/benchmark.png",
            "poster_url": "",
            "alt": "Official benchmark",
            "source_url": url,
            "source_type": "original_media",
            "extracted": True,
        }]
        return fetched

    cli.fetch_article = fake_fetch
    try:
        cli._get_evidence_articles(args, article)
    finally:
        cli.fetch_article = original_fetch

    assert len(article.media_assets) == 2
    merged = article.media_assets[1]
    assert merged["id"] == "media-2"
    assert merged["source_url"] == "https://vendor.example/newsroom/release"
    assert merged["source_type"] == "official_media"


def test_browser_page_assets_feed_sources_and_media_registry():
    article = Article(
        url="https://vendor.example/blog/launch",
        text="原文",
        source_links=[],
        media_assets=[],
    )
    result = fetcher.merge_page_assets(article, {
        "links": [
            {"href": "https://arxiv.org/abs/2506.12605", "text": "Related paper"},
            {"href": "https://twitter.com/intent/tweet?text=share", "text": "Share"},
        ],
        "images": [
            {"src": "https://vendor.example/icon_share.svg", "alt": "icon"},
            {
                "id": "media-chart",
                "src": "https://cdn.example/results.png",
                "alt": "English results chart",
                "role": "chart",
                "language": "en",
                "caption": "实验结果对比图",
                "reader_note": "重点看两组柱状结果的相对变化，不要跨指标比较高度。",
            },
        ],
        "videos": [{
            "id": "media-demo",
            "src": "https://cdn.example/demo.mp4",
            "poster": "https://cdn.example/poster.jpg",
            "source_page": "https://vendor.example/demos/launch",
            "role": "demo",
            "language": "en",
            "caption": "产品操作演示",
            "reader_note": "留意操作步骤和失败后的恢复过程。",
        }],
    })

    assert result == {"links": 1, "media": 2}
    assert article.source_links[0]["url"] == "https://arxiv.org/abs/2506.12605"
    assert article.source_links[0]["origin"] == "page_assets"
    assert [item["id"] for item in article.media_assets] == ["media-chart", "media-demo"]
    assert article.media_assets[0]["asset_role"] == "chart"
    assert article.media_assets[0]["language"] == "en"
    assert article.media_assets[1]["source_type"] == "supplemental_media"


def test_dynamic_media_discovery_is_automatic_and_failure_is_explicit():
    article = Article(
        url="https://vendor.example/blog/launch",
        text="原文",
        source_links=[],
        media_assets=[],
    )
    args = SimpleNamespace(no_dynamic_media=False, dynamic_media_timeout=5000)
    original_discover = cli.discover_dynamic_page_assets
    original_ensure = cli.ensure_python_dependencies
    cli.ensure_python_dependencies = lambda _modules: None
    cli.discover_dynamic_page_assets = lambda *_args, **_kwargs: {
        "status": "completed",
        "media": [{
            "type": "video",
            "url": "https://player.example/embed/demo",
            "embed": True,
            "asset_role": "demo",
            "origin": "dynamic_browser",
        }],
    }
    try:
        cli._enrich_dynamic_media(args, article)
        assert article.media_discovery["status"] == "completed"
        assert article.media_assets[0]["origin"] == "dynamic_browser"
        assert article.media_assets[0]["embed"] is True

        failed = Article(url=article.url, text="原文", source_links=[], media_assets=[])
        cli.discover_dynamic_page_assets = lambda *_args, **_kwargs: {
            "status": "failed", "reason": "browser blocked", "media": []
        }
        try:
            cli._enrich_dynamic_media(args, failed)
        except SystemExit as exc:
            assert "browser blocked" in str(exc)
        else:
            raise AssertionError("动态媒体发现失败时必须明确中止")
    finally:
        cli.discover_dynamic_page_assets = original_discover
        cli.ensure_python_dependencies = original_ensure


def test_completed_page_assets_skip_sessionless_browser_discovery():
    article = Article(
        url="https://vendor.example/blog/launch",
        text="原文",
        source_links=[],
        media_assets=[],
        media_discovery={"status": "completed", "method": "codex_browser"},
    )
    args = SimpleNamespace(no_dynamic_media=False, dynamic_media_timeout=5000)
    original_discover = cli.discover_dynamic_page_assets
    original_ensure = cli.ensure_python_dependencies
    cli.ensure_python_dependencies = lambda _modules: (_ for _ in ()).throw(
        AssertionError("完成浏览器回灌后不应重复检查 Playwright")
    )
    cli.discover_dynamic_page_assets = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("完成浏览器回灌后不应启动无会话浏览器")
    )
    try:
        cli._enrich_dynamic_media(args, article)
    finally:
        cli.discover_dynamic_page_assets = original_discover
        cli.ensure_python_dependencies = original_ensure

    assert article.media_discovery == {
        "status": "completed",
        "method": "codex_browser",
    }


def _full_payload():
    return {
        "distilled_title": "媒体锚点测试",
        "quick_scan": ["要点一", "要点二", "要点三"],
        "narrative_plan": {
            "reader_tension": "读者容易把厂商媒体素材误当成独立证据。",
            "core_mechanism": "媒体素材只负责展示，因此不能提高主张的证据等级。",
            "central_question": "媒体如何支持论证？",
            "short_answer": "只展示已登记且相关的原始素材。",
            "section_logic": ["先定义", "再展示", "最后说明边界"],
            "closing_answer": "媒体辅助理解，但不提高证据等级。",
        },
        "sections": [
            {"id": "framing", "title": "先界定素材角色", "content": "第一段说明原始素材与独立证据并不是同一个概念。"},
            {"id": "demo", "title": "再看原始演示", "content": "第二段通过原网页图片和视频还原产品展示内容。"},
            {"id": "boundary", "title": "最后保留证据边界", "content": "第三段解释为什么厂商演示不能代替独立复测。"},
        ],
        "experiment_ledger": [],
        "case_stories": [],
        "fact_check": [],
        "editorial_coverage": {"covered_claim_ids": [], "omitted_claims": []},
    }


def test_media_registration_gate_and_rendering():
    article = Article(
        url="https://vendor.example/blog/launch",
        title="Launch",
        text="原文",
        source_links=[],
        media_assets=[
            {"id": "media-1", "type": "image", "url": "https://cdn.example/hero.jpg", "poster_url": "", "alt": "Hero", "source_url": "https://vendor.example/blog/launch", "source_type": "original_media", "extracted": True},
            {"id": "media-2", "type": "video", "url": "https://cdn.example/demo.mp4", "poster_url": "https://cdn.example/poster.jpg", "alt": "Demo", "asset_role": "demo", "source_url": "https://vendor.example/blog/launch", "source_type": "original_media", "extracted": True},
        ],
    )
    payload = _full_payload()
    payload["source_media"] = [
        {"media_id": "media-1", "caption": "产品界面原图", "after_section_id": "demo"},
        {"media_id": "media-2", "caption": "原始工作流演示", "after_section_id": "demo"},
    ]
    normalized = normalize_distilled(payload, article)
    audit = audit_distilled(normalized, {}, ("full",), strict_editorial=True)
    assert audit["publishable"], audit

    html = render_html(article, normalized)
    assert html.count('class="source-media" data-media-id="media-1"') == 1
    assert html.count('class="source-media" data-media-id="media-2"') == 1
    assert html.count('<details class="evidence-gallery">') == 1
    assert len(normalized["evidence_gallery"]) == 2
    assert "查看视频" in html
    assert "素材来源" not in html
    assert ".source-media img { display:block; width:auto; max-width:100%; height:auto; margin:0 auto;" in html
    assert ".source-media img,.source-media video" not in html
    assert ".source-media video { display:block; width:100%;" in html
    assert ".source-media video { max-height:420px;" in html
    assert "产品界面原图</figcaption>" in html
    assert html.index('id="demo"') < html.index('data-media-id="media-1"') < html.index('id="boundary"')
    assert "<video controls preload=\"metadata\" poster=\"https://cdn.example/poster.jpg\">" in html
    rendered_audit = audit_rendered_media(article, normalized, html)
    assert rendered_audit["ok"], rendered_audit
    assert rendered_audit["inventory_count"] == 2
    assert rendered_audit["used_count"] == 2
    assert rendered_audit["unaccounted_count"] == 0
    assert rendered_audit["rendered_source_media_count"] == 2

    broken_html = html.replace('data-media-id="media-2"', 'data-media-id="missing-media"', 1)
    broken_audit = audit_rendered_media(article, normalized, broken_html)
    assert not broken_audit["ok"]
    assert "media-2" in str(broken_audit["errors"])

    unaccounted_payload = _full_payload()
    unaccounted = normalize_distilled(unaccounted_payload, article)
    unaccounted_audit = audit_rendered_media(article, unaccounted, render_html(article, unaccounted))
    assert not unaccounted_audit["ok"]
    assert unaccounted_audit["unaccounted_important_media_ids"] == ["media-2"]

    invalid = _full_payload()
    invalid["source_media"] = [{
        "media_id": "media-404",
        "type": "image",
        "url": "https://attacker.example/fake.jpg",
        "caption": "未登记素材",
        "after_section_id": "missing",
    }]
    normalized_invalid = normalize_distilled(invalid, article)
    invalid_audit = audit_distilled(normalized_invalid, {}, ("full",), strict_editorial=True)
    assert not invalid_audit["publishable"]
    assert "没有出现在抓取登记" in str(invalid_audit["blockers"])
    assert "不存在的 section id" in str(invalid_audit["blockers"])
    assert "https://attacker.example/fake.jpg" not in render_html(article, normalized_invalid)


def test_media_explanation_contract_is_audited_without_breaking_legacy_payloads():
    article = Article(
        url="https://vendor.example/blog/launch",
        title="Launch",
        text="原文",
        source_links=[],
        media_assets=[{
            "id": "media-1",
            "type": "image",
            "url": "https://cdn.example/diagram.png",
            "poster_url": "",
            "alt": "Workflow diagram",
            "source_url": "https://vendor.example/blog/launch",
            "source_type": "original_media",
            "extracted": True,
        }],
    )
    payload = _full_payload()
    payload["source_media"] = [{
        "media_id": "media-1",
        "type": "image",
        "url": "https://cdn.example/diagram.png",
        "caption": "工作流示意图",
        "after_section_id": "demo",
    }]
    normalized = normalize_distilled(payload, article)
    audit = audit_distilled(normalized, {}, ("full",), strict_editorial=True)

    # 老稿可以继续发布，但审校结果必须明确指出媒体没有解释任务/观看重点。
    assert audit["publishable"], audit
    assert audit["metrics"]["media_explanation_gaps"] == ["media-1"]
    assert "解释任务或具体观看重点" in str(audit["warnings"])

    complete = _full_payload()
    complete["source_media"] = [{
        "media_id": "media-1",
        "type": "image",
        "url": "https://cdn.example/diagram.png",
        "caption": "工作流示意图",
        "purpose": "解释请求如何经过排队、执行和回传三个阶段",
        "reader_note": "重点看三段箭头的先后关系，这能帮助理解任务为什么会在执行前排队。",
        "after_section_id": "demo",
    }]
    complete_normalized = normalize_distilled(complete, article)
    complete_audit = audit_distilled(complete_normalized, {}, ("full",), strict_editorial=True)
    assert complete_audit["metrics"]["media_explanation_gaps"] == []


def test_publish_audit_blocks_when_demo_videos_are_ignored():
    article = Article(
        url="https://vendor.example/blog/launch",
        title="Launch",
        text="原文",
        source_links=[],
        media_assets=[{
            "id": "media-1",
            "type": "video",
            "url": "https://cdn.example/demo.mp4",
            "poster_url": "",
            "alt": "Official capability demo",
            "asset_role": "demo",
            "source_url": "https://vendor.example/blog/launch",
            "source_type": "original_media",
            "extracted": True,
        }],
    )
    normalized = normalize_distilled(_full_payload(), article)
    audit = audit_distilled(normalized, {}, ("full",), strict_editorial=True)

    assert not audit["publishable"], audit
    assert audit["metrics"]["available_demo_video_count"] == 1
    assert audit["metrics"]["used_source_video_count"] == 0
    assert audit["metrics"]["unused_demo_video_ids"] == ["media-1"]
    assert "重要演示或首屏视频既未采用" in str(audit["blockers"])


def test_foreign_media_requires_chinese_guidance_without_exposing_internal_notes():
    article = Article(
        url="https://vendor.example/blog/launch",
        title="Launch",
        text="原文",
        source_links=[],
        media_assets=[{
            "id": "media-1",
            "type": "video",
            "url": "https://cdn.example/demo.mp4",
            "poster_url": "",
            "alt": "English demo",
            "asset_role": "demo",
            "language": "en",
            "caption": "英文产品演示",
            "reader_note": "留意第二步如何发现失败并重新执行任务。",
            "translation_note": "根据官方英文标题和画面整理中文导读；视频无中文字幕。",
            "source_url": "https://vendor.example/blog/launch",
            "source_type": "original_media",
            "extracted": True,
        }],
    )
    payload = _full_payload()
    payload["source_media"] = [{"media_id": "media-1", "after_section_id": "demo"}]
    normalized = normalize_distilled(payload, article)
    audit = audit_distilled(normalized, {}, ("full",), strict_editorial=True)
    assert audit["publishable"], audit
    html = render_html(article, normalized)
    assert "观看重点" in html and "重新执行任务" in html
    for internal_text in ("中文化说明", "视频无中文字幕", "media-translation-note"):
        assert internal_text not in html

    article.media_assets[0]["reader_note"] = ""
    missing = normalize_distilled(payload, article)
    missing_audit = audit_distilled(missing, {}, ("full",), strict_editorial=True)
    assert not missing_audit["publishable"]
    assert "外语媒体必须提供自然中文图注" in str(missing_audit["blockers"])


if __name__ == "__main__":
    test_fetcher_extracts_links_and_content_media()
    test_fetcher_discovers_lazy_background_and_embedded_media()
    test_remote_pdf_uses_pdf_text_extraction()
    test_explicit_source_roles_are_not_conflated()
    test_official_discovery_and_cross_check_boundary()
    test_version_specific_sources_outrank_adjacent_releases()
    test_discovered_sources_are_globally_ranked_before_limit()
    test_discovered_research_links_include_papers_and_public_reports()
    test_fetched_attachment_media_joins_the_registry()
    test_browser_page_assets_feed_sources_and_media_registry()
    test_dynamic_media_discovery_is_automatic_and_failure_is_explicit()
    test_completed_page_assets_skip_sessionless_browser_discovery()
    test_media_registration_gate_and_rendering()
    test_media_explanation_contract_is_audited_without_breaking_legacy_payloads()
    test_publish_audit_blocks_when_demo_videos_are_ignored()
    test_foreign_media_requires_chinese_guidance_without_exposing_internal_notes()
    print("source and media tests passed")
