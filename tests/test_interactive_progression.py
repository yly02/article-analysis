#!/usr/bin/env python3
"""步骤探索器与时间拖动器的渲染、降级和门禁回归测试。"""

import sys
from pathlib import Path


SKILL_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
sys.path.insert(0, SKILL_SCRIPTS)

from editorial_quality import audit_distilled  # noqa: E402
from fetcher import Article  # noqa: E402
from renderer import render_html  # noqa: E402
from test_article_depth import RESEARCH, base_payload  # noqa: E402


ARTICLE = Article(url="https://example.com/progression", title="互动进程测试", text="正文")


def stepper_visual():
    return {
        "type": "flow",
        "title": "一次请求怎样完成",
        "after_section_id": "method",
        "reader_question": "请求经过哪些阶段",
        "data": {
            "presentation": "stepper",
            "steps": [
                {"label": "接收", "title": "接收输入", "description": "系统先读取用户提交的内容。", "result": "形成待处理请求"},
                {"label": "检查", "title": "检查边界", "description": "验证格式、长度与权限条件。", "result": "不合格输入被拒绝"},
                {"label": "处理", "title": "运行模型", "description": "模型根据有效输入完成计算。", "result": "生成候选结果"},
                {"label": "返回", "title": "返回结果", "description": "系统整理结果并交给用户。", "result": "本次请求结束"},
            ],
            "caption": "阶段顺序来自当前实现，不能据此推断每一步耗时。",
        },
    }


def scrubber_visual():
    return {
        "type": "timeline",
        "title": "能力怎样一步步开放",
        "after_section_id": "measurement",
        "reader_question": "不同时间节点增加了什么",
        "data": {
            "presentation": "scrubber",
            "events": [
                {"time": "2024", "title": "只支持文本", "description": "首个版本处理文字输入。"},
                {"time": "2025 上半年", "title": "加入图片", "description": "模型开始读取静态图像。"},
                {"time": "2025 下半年", "title": "加入音频", "description": "输入范围扩展到声音。"},
                {"time": "2026", "title": "支持视频", "description": "系统能够处理连续画面。"},
            ],
            "caption": "时间节点只表示材料确认的开放顺序，不代表各能力质量相同。",
        },
    }


def test_interactive_progression_renders_and_degrades():
    payload = base_payload()
    payload["visuals"] = [stepper_visual(), scrubber_visual()]
    audit = audit_distilled(payload, RESEARCH, ("full",), strict_editorial=True)
    assert audit["metrics"]["invalid_flow_visual_indexes"] == []
    assert audit["metrics"]["invalid_timeline_visual_indexes"] == []

    html = render_html(ARTICLE, payload)
    assert 'data-flow-stepper' in html
    assert html.count('data-flow-step=') == 4
    assert html.count('data-flow-panel=') == 4
    assert 'data-flow-prev' in html and 'data-flow-next' in html
    assert 'data-timeline-scrubber' in html
    assert html.count('hidden data-timeline-event=') == 4
    assert 'data-timeline-input' in html
    assert 'class="ts-fallback"' in html
    assert "setFlowStep(root" in html
    assert "data-timeline-title" in html
    assert "接收输入" in html and "系统先读取用户提交的内容。" in html
    assert "形成待处理请求" in html
    assert "支持视频" in html and "系统能够处理连续画面。" in html


def test_invalid_interactive_progression_is_blocked():
    payload = base_payload()
    stepper = stepper_visual()
    stepper["data"]["steps"][0]["description"] = ""
    scrubber = scrubber_visual()
    scrubber["data"]["events"] = scrubber["data"]["events"][:2]
    scrubber["after_section_id"] = "missing"
    payload["visuals"] = [stepper, scrubber]

    audit = audit_distilled(payload, RESEARCH, ("full",), strict_editorial=True)
    assert audit["metrics"]["invalid_flow_visual_indexes"] == [1]
    assert audit["metrics"]["invalid_timeline_visual_indexes"] == [2]
    assert audit["metrics"]["invalid_timeline_scrubber_anchors"] == [2]
    assert not audit["publishable"]
    assert any("步骤探索器需要" in item for item in audit["blockers"])
    assert any("时间拖动器需要" in item for item in audit["blockers"])


if __name__ == "__main__":
    test_interactive_progression_renders_and_degrades()
    test_invalid_interactive_progression_is_blocked()
    print("interactive progression tests passed")
