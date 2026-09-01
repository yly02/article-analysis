#!/usr/bin/env python3
"""多指标切换卡的渲染与发布门禁回归测试。"""

import sys
from pathlib import Path


SKILL_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
sys.path.insert(0, SKILL_SCRIPTS)

from editorial_quality import audit_distilled  # noqa: E402
from fetcher import Article  # noqa: E402
from renderer import render_html  # noqa: E402


ARTICLE = Article(
    url="https://example.com/benchmark",
    title="多指标测试",
    author="测试",
    text="正文",
    text_chars=2,
)


def payload():
    row_a = {
        "label": "模型 A",
        "primary_value": 100,
        "baseline_value": 50,
        "primary_display": "100 tok/s",
        "baseline_display": "50 tok/s",
        "ratio": "2.0×",
    }
    row_b = {
        "label": "模型 B",
        "primary_value": 80,
        "baseline_value": 40,
        "primary_display": "80 tok/s",
        "baseline_display": "40 tok/s",
        "ratio": "2.0×",
    }
    return {
        "distilled_title": "多指标切换卡测试",
        "narrative_plan": {"core_mechanism": "不同指标回答不同问题。"},
        "sections": [
            {"id": "s1", "title": "第一节", "content": "正文内容。"},
            {"id": "s2", "title": "第二节", "content": "继续说明。"},
            {"id": "s3", "title": "第三节", "content": "给出结论。"},
        ],
        "visuals": [{
            "type": "metric_bars",
            "title": "两个问题不能混用",
            "after_section_id": "s1",
            "data": {
                "primary_label": "主方案",
                "baseline_label": "对照系统",
                "normalization_note": "条长只在同一行内归一化。",
                "groups": [
                    {
                        "id": "throughput",
                        "label": "吞吐",
                        "question": "单位时间能处理多少工作？",
                        "metric": "tokens/s，越高越好",
                        "better": "higher",
                        "rows": [row_a, row_b],
                    },
                    {
                        "id": "latency",
                        "label": "延迟",
                        "question": "完成请求需要多久？",
                        "metric": "秒，越低越好",
                        "better": "lower",
                        "rows": [
                            {**row_a, "primary_value": 1, "baseline_value": 2, "primary_display": "1 秒", "baseline_display": "2 秒"},
                            {**row_b, "primary_value": 2, "baseline_value": 4, "primary_display": "2 秒", "baseline_display": "4 秒"},
                        ],
                    },
                ],
                "boundary": "吞吐和延迟不能合成一个总倍数。",
            },
        }],
    }


def test_metric_bars_render_interactive_html_with_static_fallback():
    distilled = payload()
    html = render_html(ARTICLE, distilled)

    assert 'data-metric-bars' in html
    assert html.count('data-metric-tab=') == 2
    assert html.count('data-metric-panel=') == 2
    assert '--bar-width:50.00%' in html
    assert "metric-bars-ready" in html
    assert "--metric-primary: #1f9d68" in html
    assert "--metric-baseline: #4f7fd8" in html
    assert ".mb-line.primary .mb-series::before" in html
    assert ".mb-line.baseline .mb-fill { background:var(--metric-baseline); }" in html
    assert ".mb-ratio { min-width:58px; padding:3px 7px;" in html
    assert "不同指标不能混用" not in html
    assert "吞吐和延迟不能合成一个总倍数" in html

def test_metric_bars_gate_rejects_bad_data_and_anchor():
    valid = audit_distilled(payload(), {}, required_modes=("full",), strict_editorial=True)
    assert valid["metrics"]["invalid_metric_bar_indexes"] == []
    assert valid["metrics"]["invalid_metric_bar_anchors"] == []

    invalid = payload()
    invalid["visuals"][0]["after_section_id"] = "missing"
    invalid["visuals"][0]["data"]["groups"][0]["rows"] = []
    audit = audit_distilled(invalid, {}, required_modes=("full",), strict_editorial=True)

    assert not audit["publishable"]
    assert audit["metrics"]["invalid_metric_bar_indexes"] == [1]
    assert audit["metrics"]["invalid_metric_bar_anchors"] == [1]
    assert any("指标切换卡缺少" in item for item in audit["blockers"])
    assert any("指标切换卡指向不存在" in item for item in audit["blockers"])


if __name__ == "__main__":
    test_metric_bars_render_interactive_html_with_static_fallback()
    test_metric_bars_gate_rejects_bad_data_and_anchor()
    print("metric bars tests passed")
