#!/usr/bin/env python3
"""Deep-article experiment and case rendering/quality regression tests."""

import os
import sys
from pathlib import Path


SKILL_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
sys.path.insert(0, SKILL_SCRIPTS)

from editorial_quality import audit_distilled  # noqa: E402
from fetcher import Article  # noqa: E402
from renderer import render_html  # noqa: E402


ARTICLE = Article(
    url="https://example.com/paper",
    title="深度组件测试",
    author="研究者",
    text="正文",
    text_chars=2,
)


def base_payload():
    return {
        "distilled_title": "信任边界决定传播风险",
        "quick_scan": ["要点一", "要点二", "要点三"],
        "narrative_plan": {
            "reader_tension": "读者容易把持续传播误解为模型权重被永久改变。",
            "core_mechanism": "低信任消息进入持久配置后，会在下一轮被升级为高优先级上下文。",
            "central_question": "风险来自哪里？",
            "short_answer": "来自低信任输入升级为高优先级指令。",
            "section_logic": ["先定性", "再测量", "最后解释机制"],
            "closing_answer": "风险取决于升级路径，而不是文件名。",
        },
        "sections": [
            {"id": "framing", "title": "先重新定义问题", "content": "第一段建立信任边界判断，并说明风险对象。", "transition_hook": "这种风险会在什么条件下真正发生？"},
            {"id": "measurement", "title": "实验测的是传播条件", "content": "第二段说明样本、指标、对照和结果口径。", "transition_hook": "位置为什么会改变传播结果？"},
            {"id": "mechanism", "title": "自动回灌放大风险", "content": "第三段解释消息如何跨上下文进入高优先级提示。"},
        ],
        "experiment_ledger": [
            {
                "id": "e1",
                "title": "两种持久位置产生不同结果",
                "after_section_id": "measurement",
                "question": "写入位置是否改变传播？",
                "setup": "上下文清空、磁盘保留，比较核心配置与普通文件。",
                "sample": "论文报告的受控试验",
                "models": ["测试模型"],
                "metric": "尝试传播率与感染成功率",
                "result": "核心配置组高于普通文件组。",
                "control": "普通文件组",
                "limitations": "不能外推为现实网络发生率。",
                "claim_ids": ["c1"],
            }
        ],
        "case_stories": [
            {
                "id": "case1",
                "title": "消息跨轮变成控制指令",
                "after_section_id": "mechanism",
                "source_mode": "reconstruction",
                "setup": "宿主最初只收到一条外部消息。",
                "beats": [
                    {"label": "接收", "text": "宿主接收外部目标。"},
                    {"label": "写入", "text": "目标被写入持久配置。"},
                    {"label": "回灌", "text": "下一轮把配置注入系统提示。"},
                ],
                "outcome": "宿主继续执行并转发该目标。",
                "boundary": "不能证明模型权重被永久改变。",
                "claim_ids": ["c2"],
            }
        ],
        "fact_check": [],
        "editorial_coverage": {"covered_claim_ids": ["c1", "c2"], "omitted_claims": []},
    }


RESEARCH = {
    "claims": [
        {"id": "c1", "importance": "high"},
        {"id": "c2", "importance": "high"},
    ],
    "experiments": [{"id": "e1", "importance": "high"}],
    "cases": [{"id": "case1", "importance": "high"}],
}


def test_components_render_after_their_sections_once():
    payload = base_payload()
    html = render_html(ARTICLE, payload)
    assert html.count("两种持久位置产生不同结果") == 1
    assert html.count("消息跨轮变成控制指令") == 1
    assert html.count('class="case-beat-text"') == 3
    assert html.index('id="measurement"') < html.index("两种持久位置产生不同结果") < html.index('id="mechanism"')
    assert html.index('id="mechanism"') < html.index("消息跨轮变成控制指令")
    assert "基于证据重建事件顺序，非逐字对话" in html
    assert html.count('class="transition-hook"') == 2
    assert ".article-body h2 { font-size:19px; font-weight:700;" in html
    assert "color:var(--sub); font-size:14px; font-weight:600;" in html
    assert html.index("两种持久位置产生不同结果") < html.index("位置为什么会改变传播结果？") < html.index('id="mechanism"')

def test_depth_gate_rejects_missing_or_unanchored_components():
    valid = audit_distilled(base_payload(), RESEARCH, ("full",), strict_editorial=True)
    assert valid["publishable"], valid

    missing = base_payload()
    missing["experiment_ledger"] = []
    missing_audit = audit_distilled(missing, RESEARCH, ("full",), strict_editorial=True)
    assert "e1" in str(missing_audit["blockers"])

    broken = base_payload()
    broken["experiment_ledger"][0]["after_section_id"] = "missing"
    broken["case_stories"][0]["claim_ids"] = ["c404"]
    broken_audit = audit_distilled(broken, RESEARCH, ("full",), strict_editorial=True)
    assert "不存在的 section id" in str(broken_audit["blockers"])
    assert "c404" in str(broken_audit["blockers"])


def test_non_research_article_needs_no_synthetic_experiment_or_case():
    payload = base_payload()
    payload["experiment_ledger"] = []
    payload["case_stories"] = []
    research = {"claims": RESEARCH["claims"], "experiments": [], "cases": []}
    audit = audit_distilled(payload, research, ("full",), strict_editorial=True)
    assert audit["publishable"], audit


def test_strict_gate_rejects_meta_narration_in_article_body():
    payload = base_payload()
    payload["sections"][1]["content"] = "原博客重点说明了测试结果，当前材料没有更多信息。"
    audit = audit_distilled(payload, RESEARCH, ("full",), strict_editorial=True)
    assert not audit["publishable"]
    assert audit["metrics"]["meta_narration_section_indexes"] == [2]
    assert "研究过程话术" in str(audit["blockers"])

    payload["sections"][1]["content"] = "厂商尚未公布完整测试集，现有数据不足以支持综合领先。"
    audit = audit_distilled(payload, RESEARCH, ("full",), strict_editorial=True)
    assert audit["publishable"], audit

    payload = base_payload()
    payload["recommendation_reason"] = "读完本文就能理解这次变化。"
    payload["takeaway_list"] = ["当前材料没有证明性能领先。"]
    audit = audit_distilled(payload, RESEARCH, ("full",), strict_editorial=True)
    assert not audit["publishable"]
    assert audit["metrics"]["meta_narration_public_paths"] == [
        "$.recommendation_reason",
        "$.takeaway_list[0]",
    ]


def test_quick_scan_is_a_real_one_minute_guide():
    payload = base_payload()
    payload["quick_scan"].append("多出来的第四条")
    audit = audit_distilled(payload, RESEARCH, ("full",), strict_editorial=True)
    assert not audit["publishable"]
    assert "必须精简为 3 条" in str(audit["blockers"])

    payload = base_payload()
    payload["quick_scan"] = ["很长的导览内容" * 30, "第二条", "第三条"]
    audit = audit_distilled(payload, RESEARCH, ("full",), strict_editorial=True)
    assert not audit["publishable"]
    assert audit["metrics"]["quick_scan_char_count"] > 180
    assert "180 字以内" in str(audit["blockers"])


def test_category_tags_are_short_archival_categories():
    payload = base_payload()
    payload["category_tags"] = ["Google", "Gemini", "语音识别", "语音交互"]
    audit = audit_distilled(payload, RESEARCH, ("full",), strict_editorial=True)
    assert audit["publishable"], audit
    assert audit["metrics"]["category_tag_count"] == 4

    payload["category_tags"] = [
        "转录模型正在转向语音操作入口",
        "实时流式与预录处理分工",
        "公开预览仍待独立复现",
    ]
    audit = audit_distilled(payload, RESEARCH, ("full",), strict_editorial=True)
    assert not audit["publishable"]
    assert audit["metrics"]["long_category_tag_indexes"] == [1, 2, 3]
    assert "归档标签必须短平快" in str(audit["blockers"])


if __name__ == "__main__":
    test_components_render_after_their_sections_once()
    test_depth_gate_rejects_missing_or_unanchored_components()
    test_non_research_article_needs_no_synthetic_experiment_or_case()
    test_strict_gate_rejects_meta_narration_in_article_body()
    test_quick_scan_is_a_real_one_minute_guide()
    test_category_tags_are_short_archival_categories()
    print("article depth tests passed")
