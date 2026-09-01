#!/usr/bin/env python3
"""关系驱动视觉选择与多层结构的回归测试。"""

import sys
from pathlib import Path


SKILL_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
sys.path.insert(0, SKILL_SCRIPTS)

from editorial_quality import audit_distilled  # noqa: E402
from fetcher import Article  # noqa: E402
from renderer import render_html  # noqa: E402
from test_article_depth import RESEARCH, base_payload  # noqa: E402


ARTICLE = Article(url="https://example.com/stack", title="System stack", text="正文")


def layer_visual():
    return {
        "type": "layer_stack",
        "title": "一套AI系统怎样分层协作",
        "after_section_id": "measurement",
        "reader_question": "上层能力建立在哪些下层能力之上",
        "data": {
            "layers": [
                {
                    "label": "应用层",
                    "title": "用户看到的能力",
                    "description": "把模型能力组织成具体工作流。",
                    "items": ["产品交互", "任务编排"],
                },
                {
                    "label": "模型层",
                    "title": "理解与生成",
                    "description": "根据输入完成推理并生成结果。",
                    "items": ["语言模型"],
                },
                {
                    "label": "基础设施层",
                    "title": "计算、内存与网络",
                    "description": "为模型运行提供底层资源。",
                    "items": ["加速器", "内存", "互联"],
                },
            ],
            "caption": "这是材料支持的职责分层，不代表所有AI系统都采用相同架构。",
        },
    }


def test_layer_stack_renders_as_expandable_html():
    payload = base_payload()
    payload["visuals"] = [layer_visual()]
    audit = audit_distilled(payload, RESEARCH, ("full",), strict_editorial=True)
    assert audit["publishable"], audit
    assert audit["metrics"]["invalid_layer_stack_indexes"] == []
    html = render_html(ARTICLE, payload)
    assert 'class="layer-stack"' in html
    assert html.count('class="layer-item"') == 3
    assert '<details class="layer-item" open>' in html
    assert "应用层" in html and "用户看到的能力" in html
    assert "这是材料支持的职责分层" in html


def test_invalid_layer_stack_is_blocked_in_strict_mode():
    payload = base_payload()
    visual = layer_visual()
    visual["data"]["layers"] = visual["data"]["layers"][:1]
    payload["visuals"] = [visual]
    audit = audit_distilled(payload, RESEARCH, ("full",), strict_editorial=True)
    assert not audit["publishable"]
    assert audit["metrics"]["invalid_layer_stack_indexes"] == [1]


def test_oversized_matrix_gets_restructure_warning():
    payload = base_payload()
    payload["visuals"] = [{
        "type": "compare_table",
        "title": "过长矩阵",
        "after_section_id": "measurement",
        "data": {
            "layout": "matrix",
            "headers": ["对象", "能力", "成本", "边界", "备注"],
            "rows": [[f"对象{i}", "说明", "说明", "说明", "说明"] for i in range(7)],
        },
    }]
    audit = audit_distilled(payload, RESEARCH, ("full",), strict_editorial=True)
    assert audit["metrics"]["oversized_matrix_visual_indexes"] == [1]
    assert any("矩阵表格过长" in item for item in audit["warnings"])


def test_semantic_tones_render_for_tables_and_stats():
    payload = base_payload()
    payload["visuals"] = [
        {
            "type": "compare_table",
            "title": "方案比较",
            "after_section_id": "measurement",
            "data": {
                "layout": "matrix",
                "headers": ["项目", "旧方案", "新方案", "限制"],
                "column_roles": ["neutral", "baseline", "primary", "warning"],
                "rows": [["速度", "慢", "快", "仅限测试集"]],
            },
        },
        {
            "type": "compare_table",
            "title": "逐项比较",
            "after_section_id": "measurement",
            "data": {
                "layout": "paired",
                "headers": ["项目", "旧方案", "新方案", "风险"],
                "column_roles": ["neutral", "baseline", "primary", "danger"],
                "rows": [["结果", "基线", "提升", "可能失败"]],
            },
        },
        {
            "type": "stat",
            "title": "关键数字",
            "after_section_id": "measurement",
            "data": {
                "items": [
                    {"label": "结果", "value": "90%", "tone": "primary"},
                    {"label": "无效角色", "value": "10%", "tone": "rainbow"},
                ]
            },
        },
    ]
    html = render_html(ARTICLE, payload)
    assert 'class="cmp-tone-baseline"' in html
    assert 'class="cmp-tone-primary"' in html
    assert 'class="cmp-tone-warning"' in html
    assert 'class="comparison-pair cmp-tone-danger"' in html
    assert 'class="stat-card tone-primary"' in html
    assert "tone-rainbow" not in html


if __name__ == "__main__":
    test_layer_stack_renders_as_expandable_html()
    test_invalid_layer_stack_is_blocked_in_strict_mode()
    test_oversized_matrix_gets_restructure_warning()
    test_semantic_tones_render_for_tables_and_stats()
    print("visual selection tests passed")
