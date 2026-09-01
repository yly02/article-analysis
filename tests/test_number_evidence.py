#!/usr/bin/env python3
"""数字叙事、证据图库与图表 OCR 的行为回归测试。"""

import json
import sys
from pathlib import Path


SKILL_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
sys.path.insert(0, SKILL_SCRIPTS)

import fetcher  # noqa: E402
from chart_ocr import enrich_chart_assets  # noqa: E402
from editorial_quality import audit_distilled  # noqa: E402
from evidence import normalize_distilled  # noqa: E402
from fetcher import Article  # noqa: E402
from renderer import render_html  # noqa: E402
from test_article_depth import base_payload  # noqa: E402


ARTICLE = Article(
    url="https://vendor.example/report",
    title="Benchmark report",
    text="报告正文",
    media_assets=[{
        "id": "media-1",
        "type": "image",
        "url": "https://cdn.example/chart.png",
        "source_url": "https://vendor.example/report",
        "source_type": "original_media",
        "asset_role": "chart",
        "caption": "Benchmark results. Source: Vendor evaluation",
    }],
    source_links=[],
)

RESEARCH = {
    "claims": [{
        "id": "c1",
        "claim": "100 次测试中成功 68 次，比基线高 18 个百分点。",
        "importance": "high",
        "claim_kind": "metric",
    }],
    "experiments": [],
    "cases": [],
}


def payload_with_number():
    payload = base_payload()
    payload["experiment_ledger"] = []
    payload["case_stories"] = []
    payload["editorial_coverage"] = {"covered_claim_ids": ["c1"], "omitted_claims": []}
    payload["sections"][1]["content"] = "100 次测试中成功 68 次，比基线高 18 个百分点。"
    payload["number_stories"] = [{
        "id": "success-rate",
        "title": "成功率提升了多少",
        "value": "68",
        "unit": "%",
        "denominator": "100 次测试",
        "scope": "厂商给定测试集",
        "period": "2026 年 8 月发布时",
        "baseline": "基线为 50%",
        "change": "+18 个百分点",
        "boundary": "不能外推为所有真实任务的成功率",
        "source_url": "https://vendor.example/report",
        "source_asset_ids": ["media-1"],
        "claim_ids": ["c1"],
        "after_section_id": "measurement",
        "importance": "high",
    }]
    payload["source_media"] = []
    payload["evidence_gallery"] = [{"media_id": "media-1", "caption": "官方基准图", "claim_ids": ["c1"]}]
    return payload


def test_complete_number_story_passes_and_renders():
    normalized = normalize_distilled(payload_with_number(), ARTICLE)
    story = normalized["number_stories"][0]
    assert story["complete"] is True
    assert story["display_mode"] == "stat"
    assert story["registered_source_asset_ids"] == ["media-1"]
    assert len(normalized["evidence_gallery"]) == 1
    audit = audit_distilled(normalized, RESEARCH, ("full",), strict_editorial=True)
    assert audit["publishable"], audit
    html = render_html(ARTICLE, normalized)
    assert 'class="number-story stat"' in html
    assert html.count('class="number-meta-item"') == 3
    assert '<dt>统计对象</dt><dd>100 次测试</dd>' in html
    assert '<dt>适用场景</dt><dd>厂商给定测试集</dd>' in html
    assert '<dt>统计时间</dt><dd>2026 年 8 月发布时</dd>' in html
    assert 'class="number-compare"' in html
    assert '<div class="number-compare-label">对照情况</div>' in html
    assert '<div class="number-compare-label">结果变化</div>' in html
    assert '<div class="number-compare-arrow" aria-hidden="true">↓</div>' in html
    assert ".number-story.stat { display:block; }" in html
    assert ".number-meta { display:block;" in html
    assert ".number-compare { display:block;" in html
    assert "这个数字不能说明什么：不能外推为所有真实任务的成功率" in html
    assert "分母：100 次测试 · 范围：" not in html
    assert html.index('id="measurement"') < html.index('data-number-story-id="success-rate"') < html.index('id="mechanism"')
    assert "原始证据图库 (1)" in html


def test_audit_only_number_story_is_not_rendered_but_still_covers_claim():
    payload = payload_with_number()
    payload["number_stories"][0]["suppress_visual"] = True
    normalized = normalize_distilled(payload, ARTICLE)
    story = normalized["number_stories"][0]
    assert story["complete"] is True
    assert story["display_mode"] == "audit_only"
    audit = audit_distilled(normalized, RESEARCH, ("full",), strict_editorial=True)
    assert audit["publishable"], audit
    assert audit["metrics"]["missing_high_metric_story_ids"] == []
    assert audit["metrics"]["visible_number_story_count"] == 0
    html = render_html(ARTICLE, normalized)
    assert 'data-number-story-id="success-rate"' not in html


def test_multiple_visible_number_stories_in_one_section_are_blocked():
    payload = payload_with_number()
    second = dict(payload["number_stories"][0])
    second["id"] = "success-rate-detail"
    second["title"] = "另一张重复数字卡"
    payload["number_stories"].append(second)
    normalized = normalize_distilled(payload, ARTICLE)
    audit = audit_distilled(normalized, RESEARCH, ("full",), strict_editorial=True)
    assert not audit["publishable"]
    assert audit["metrics"]["dense_number_story_sections"] == ["measurement"]
    assert any("同一章节不得连续展示多张数字大卡" in item for item in audit["blockers"])


def test_one_visible_and_multiple_audit_only_stories_are_allowed():
    payload = payload_with_number()
    for index in range(2):
        hidden = dict(payload["number_stories"][0])
        hidden["id"] = f"hidden-{index + 1}"
        hidden["suppress_visual"] = True
        payload["number_stories"].append(hidden)
    normalized = normalize_distilled(payload, ARTICLE)
    audit = audit_distilled(normalized, RESEARCH, ("full",), strict_editorial=True)
    assert audit["publishable"], audit
    assert audit["metrics"]["visible_number_story_count_by_section"] == {"measurement": 1}


def test_visual_and_number_story_in_same_section_are_blocked():
    payload = payload_with_number()
    payload["visuals"] = [{
        "type": "compare_table",
        "title": "结果对比",
        "after_section_id": "measurement",
        "data": {
            "layout": "matrix",
            "headers": ["比较项", "结果"],
            "rows": [["成功率", "68%"]],
        },
    }]
    normalized = normalize_distilled(payload, ARTICLE)
    audit = audit_distilled(normalized, RESEARCH, ("full",), strict_editorial=True)
    assert not audit["publishable"]
    assert audit["metrics"]["mixed_main_visual_sections"] == ["measurement"]
    assert any("不得再公开展示大数字卡" in item for item in audit["blockers"])

    payload["number_stories"][0]["suppress_visual"] = True
    normalized = normalize_distilled(payload, ARTICLE)
    audit = audit_distilled(normalized, RESEARCH, ("full",), strict_editorial=True)
    assert audit["publishable"], audit


def test_number_story_accepts_reader_facing_labels():
    payload = payload_with_number()
    payload["number_stories"][0]["labels"] = {
        "denominator": "计时口径",
        "scope": "对应事件",
        "period": "事件时间",
        "baseline": "过去的处理方式",
        "change": "这次的处理方式",
        "boundary": "这 3 分钟不能说明什么",
    }
    normalized = normalize_distilled(payload, ARTICLE)
    html = render_html(ARTICLE, normalized)
    assert '<dt>计时口径</dt><dd>100 次测试</dd>' in html
    assert '<div class="number-compare-label">过去的处理方式</div>' in html
    assert "这 3 分钟不能说明什么：不能外推为所有真实任务的成功率" in html


def test_number_story_without_real_comparison_uses_compact_layout():
    payload = payload_with_number()
    story = payload["number_stories"][0]
    story["baseline"] = "无明确对照"
    story["change"] = "无可计算变化"
    story["labels"] = {
        "denominator": "统计对象",
        "period": "口径时间",
        "boundary": "尚未公布",
    }
    story["display_note"] = "厂商发布口径 · 2026 年 8 月"
    normalized = normalize_distilled(payload, ARTICLE)
    html = render_html(ARTICLE, normalized)
    assert 'class="number-story stat compact"' in html
    assert 'class="number-compact-head"' in html
    assert 'class="number-compare"' not in html
    assert "适用场景" not in html
    assert "无明确对照" not in html
    assert "无可计算变化" not in html
    assert "<strong>尚未公布：</strong>" in html
    assert "厂商发布口径 · 2026 年 8 月" in html
    assert "统计对象：100 次测试" not in html


def test_incomplete_high_metric_is_downgraded_and_blocked():
    payload = payload_with_number()
    payload["number_stories"][0]["denominator"] = ""
    normalized = normalize_distilled(payload, ARTICLE)
    assert normalized["number_stories"][0]["display_mode"] == "prose"
    audit = audit_distilled(normalized, RESEARCH, ("full",), strict_editorial=True)
    assert not audit["publishable"]
    assert "c1" in str(audit["blockers"])


def test_missing_high_metric_story_is_blocked():
    payload = payload_with_number()
    payload["number_stories"] = []
    normalized = normalize_distilled(payload, ARTICLE)
    audit = audit_distilled(normalized, RESEARCH, ("full",), strict_editorial=True)
    assert not audit["publishable"]
    assert audit["metrics"]["missing_high_metric_story_ids"] == ["c1"]


def test_unknown_context_is_not_treated_as_complete():
    payload = payload_with_number()
    payload["number_stories"][0].pop("id")
    payload["number_stories"][0]["scope"] = "未知"
    normalized = normalize_distilled(payload, ARTICLE)
    assert normalized["number_stories"][0]["display_mode"] == "prose"
    audit = audit_distilled(normalized, RESEARCH, ("full",), strict_editorial=True)
    assert audit["metrics"]["incomplete_high_metric_story_claim_ids"] == ["c1"]


def test_fetcher_tracks_figure_context_and_upstream_source():
    raw_html = """
    <html><body><h2>Evaluation</h2><figure>
      <a href="/methodology"><img src="/chart.png" alt="Benchmark chart"></a>
      <figcaption>Results by model. Source: Internal evaluation set</figcaption>
    </figure></body></html>
    """
    original_fetch = fetcher.trafilatura.fetch_url
    original_extract = fetcher.trafilatura.extract
    fetcher.trafilatura.fetch_url = lambda _url: raw_html
    fetcher.trafilatura.extract = lambda _html, **kwargs: (
        json.dumps({"title": "Report"}) if kwargs.get("output_format") == "json" else "正文"
    )
    try:
        article = fetcher.fetch_article("https://vendor.example/report")
    finally:
        fetcher.trafilatura.fetch_url = original_fetch
        fetcher.trafilatura.extract = original_extract
    asset = article.media_assets[0]
    assert asset["asset_role"] == "chart"
    assert asset["section_title"] == "Evaluation"
    assert asset["source_label"] == "Internal evaluation set"
    assert asset["upstream_source_candidates"] == ["https://vendor.example/methodology"]


def test_ocr_only_runs_for_bounded_chart_set():
    assets = [
        {"id": f"media-{index}", "type": "image", "url": f"https://cdn.example/{index}.png", "asset_role": "chart"}
        for index in range(1, 8)
    ] + [{"id": "photo", "type": "image", "url": "https://cdn.example/photo.png", "asset_role": "photo"}]
    calls = []

    def runner(url):
        calls.append(url)
        return {"status": "success", "text": "Source: Lab", "confidence": 0.9, "source_label": "Lab"}

    enriched = enrich_chart_assets(assets, enabled=True, max_assets=5, runner=runner)
    assert len(calls) == 5
    assert sum(item.get("ocr_status") == "success" for item in enriched) == 5
    assert enriched[-1].get("ocr_status") is None


if __name__ == "__main__":
    test_complete_number_story_passes_and_renders()
    test_audit_only_number_story_is_not_rendered_but_still_covers_claim()
    test_multiple_visible_number_stories_in_one_section_are_blocked()
    test_one_visible_and_multiple_audit_only_stories_are_allowed()
    test_visual_and_number_story_in_same_section_are_blocked()
    test_number_story_accepts_reader_facing_labels()
    test_number_story_without_real_comparison_uses_compact_layout()
    test_incomplete_high_metric_is_downgraded_and_blocked()
    test_missing_high_metric_story_is_blocked()
    test_unknown_context_is_not_treated_as_complete()
    test_fetcher_tracks_figure_context_and_upstream_source()
    test_ocr_only_runs_for_bounded_chart_set()
    print("number evidence tests passed")
