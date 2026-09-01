#!/usr/bin/env python3
"""语言自查、自纠与发布门禁行为测试。"""

from __future__ import annotations

import sys
from pathlib import Path


TEST_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(TEST_ROOT))

from editorial_quality import audit_distilled  # noqa: E402
from language_quality import (  # noqa: E402
    analyze_reader_voice,
    apply_safe_language_fixes,
    find_language_issues,
)
from test_hardening import complete_draft, run_distill_with_fake  # noqa: E402


def publishable_article() -> dict:
    return {
        "distilled_title": "能力如何改善制作流程",
        "quick_scan": ["要点一", "要点二", "要点三"],
        "narrative_plan": {
            "reader_tension": "读者难以判断这些能力分别解决什么问题。",
            "core_mechanism": "能力针对不同制作环节，所以需要按问题选择。",
            "central_question": "这些能力解决什么问题？",
            "closing_answer": "它们改善了制作流程。",
            "section_logic": ["提出问题", "解释机制", "说明边界"],
        },
        "sections": [
            {"id": "s1", "title": "问题", "content": "第一段说明制作环节中真实存在的问题和约束条件。"},
            {"id": "s2", "title": "机制", "content": "第二段解释不同能力如何作用于这些具体环节。"},
            {"id": "s3", "title": "边界", "content": "第三段说明现有证据不足以支持哪些更强的结论。"},
        ],
        "experiment_ledger": [],
        "case_stories": [],
        "fact_check": [],
        "editorial_coverage": {"covered_claim_ids": [], "omitted_claims": []},
    }


def test_safe_fixes() -> None:
    article = publishable_article()
    article["distilled_title"] = "三项能力各自在减少哪一种制作断点"
    article["sections"][0]["content"] = "多镜头、提示词和 ACES，分别在消灭三种制作断点。"
    article["sections"][1]["content"] = "复杂多主体指令首次生成偏离，素材进入专业后期时丢动态范围。。"

    issues = find_language_issues(article)
    assert any(item["path"] == "$.distilled_title" for item in issues)
    assert any(item["rule"] == "missing_loss_complement" for item in issues)

    fixed, fixes = apply_safe_language_fixes(article)
    assert fixed["distilled_title"] == "三项能力分别解决哪类制作问题"
    assert "分别解决三类制作问题" in fixed["sections"][0]["content"]
    assert "在首次生成时偏离" in fixed["sections"][1]["content"]
    assert "丢失动态范围。" in fixed["sections"][1]["content"]
    assert len(fixes) == 5
    assert find_language_issues(fixed) == []
    assert article["distilled_title"] == "三项能力各自在减少哪一种制作断点"


def test_protected_evidence_and_code() -> None:
    article = publishable_article()
    article["sections"][0]["content"] = "正文。。代码 `示例。。`，链接 https://example.com/a。。"
    article["sections"][0]["quote"] = "逐字引文。。"
    article["research_ledger"] = {
        "claims": [{"id": "c1", "claim": "三项能力各自在减少哪一种制作断点。。"}]
    }

    fixed, fixes = apply_safe_language_fixes(article)
    content = fixed["sections"][0]["content"]
    assert "正文。" in content
    assert "`示例。。`" in content
    assert "https://example.com/a。。" in content
    assert fixed["sections"][0]["quote"] == "逐字引文。。"
    assert fixed["research_ledger"] == article["research_ledger"]
    assert len(fixes) == 1


def test_strict_gate_blocks_unresolved_grammar() -> None:
    article = publishable_article()
    article["sections"][1]["title"] = "三项能力各自在提升哪一类指标"
    audit = audit_distilled(article, required_modes=("full",), strict_editorial=True)
    assert audit["publishable"] is False
    assert audit["metrics"]["language_issue_count"] == 1
    assert audit["metrics"]["language_issues"][0]["path"] == "$.sections[1].title"
    assert any("成文语言检查" in item for item in audit["blockers"])

    loose = audit_distilled(article, required_modes=("full",), strict_editorial=False)
    assert loose["publishable"] is True
    assert any("成文语言检查" in item for item in loose["warnings"])


def test_normal_sentence_has_no_false_positive() -> None:
    article = publishable_article()
    article["sections"][1]["title"] = "三项能力分别解决哪些制作问题"
    assert find_language_issues(article) == []


def test_safe_fixes_for_responsibility_examples() -> None:
    article = publishable_article()
    article["sections"][0]["content"] = "三个很具体的问题最能说明这套制度。"
    article["sections"][1]["content"] = "问题可能不归某一个团队完整负责。"
    article["sections"][2]["content"] = "公开报道没有给出三件事从提出到解决用了多久。"

    issues = find_language_issues(article)
    assert {item["rule"] for item in issues} == {
        "awkward_problem_explains_system",
        "awkward_team_responsibility",
        "awkward_duration_object",
    }

    fixed, fixes = apply_safe_language_fixes(article)
    assert fixed["sections"][0]["content"] == "要理解这套制度具体在解决什么，看三个例子就够了。"
    assert fixed["sections"][1]["content"] == "没有哪个团队对这些问题负完整责任。"
    assert fixed["sections"][2]["content"] == "公开报道没有说明这三件事从提出到解决各自用了多长时间。"
    assert len(fixes) == 3
    assert find_language_issues(fixed) == []


def test_extended_chinese_grammar_safe_fixes() -> None:
    article = publishable_article()
    article["sections"][0]["content"] = (
        "失败的原因是因为准备不足。本系统主要以自动控制为主。"
        "本次讨论围绕数据可靠性为中心展开。"
    )
    article["sections"][1]["content"] = (
        "为了防止故障不再出现，我们增加了检查。"
        "参会人数大约有八十人左右，处理量超过五百项以上。"
    )
    article["sections"][2]["content"] = "请确认设备是否已经关机？目前的当务之急是复检。"

    issues = find_language_issues(article)
    assert {item["rule"] for item in issues} == {
        "redundant_reason_because",
        "redundant_mainly_based_on",
        "mixed_around_center",
        "negative_prevention",
        "redundant_approximate_range",
        "redundant_exceed_above",
        "indirect_question_mark",
        "redundant_current_priority",
    }
    assert all(item["judgment"] == "明确病句" for item in issues)
    assert all(item["category"] for item in issues)

    fixed, fixes = apply_safe_language_fixes(article)
    assert fixed["sections"][0]["content"] == (
        "失败的原因是准备不足。本系统以自动控制为主。"
        "本次讨论以数据可靠性为中心展开。"
    )
    assert fixed["sections"][1]["content"] == (
        "为了防止故障再次出现，我们增加了检查。"
        "参会人数大约有八十人，处理量超过五百项。"
    )
    assert fixed["sections"][2]["content"] == "请确认设备是否已经关机。当务之急是复检。"
    assert len(fixes) == 8
    assert find_language_issues(fixed) == []


def test_context_dependent_grammar_is_not_mechanically_rejected() -> None:
    article = publishable_article()
    article["sections"][0]["content"] = "学校通过调整预约制度，使高峰时段的排队时间明显缩短。"
    article["sections"][1]["content"] = "参数是否稳定会影响实验结果。"
    article["sections"][2]["content"] = "由于连续降雨，因此比赛临时延期。"
    assert find_language_issues(article) == []


def test_redundant_equivalent_date_format_is_removed() -> None:
    article = publishable_article()
    article["sections"][0]["content"] = (
        "官方页面将发布日期标为 2026-07-31（2026 年 7 月 31 日）。"
    )
    issues = find_language_issues(article)
    assert [item["rule"] for item in issues] == ["redundant_date_parenthesis"]

    fixed, fixes = apply_safe_language_fixes(article)
    assert fixed["sections"][0]["content"] == "官方页面将发布日期标为 2026-07-31。"
    assert fixes[0]["rule"] == "redundant_date_parenthesis"
    assert find_language_issues(fixed) == []

    article["sections"][0]["content"] = "页面同时出现 2026-07-31（2026 年 8 月 1 日）。"
    assert find_language_issues(article) == []
    unchanged, fixes = apply_safe_language_fixes(article)
    assert unchanged == article
    assert fixes == []


def test_clear_but_context_sensitive_fixes_block_auto_publish() -> None:
    article = publishable_article()
    article["sections"][0]["content"] = "这个变化不仅影响速度，而是影响整个系统的稳定性。"
    article["sections"][1]["content"] = "只要认真检查，才可能发现这个问题。"
    article["sections"][2]["content"] = (
        "故障率降低了三倍，通过率从 40% 提高了 60%，合格率提高了 5 个百分比。"
    )
    issues = find_language_issues(article)
    assert {item["rule"] for item in issues} == {
        "mixed_not_only_but_instead",
        "mixed_if_only_then",
        "invalid_decrease_multiple",
        "ambiguous_percent_change",
        "percentage_point_wording",
    }
    assert all(item["auto_fixable"] is False for item in issues)

    audit = audit_distilled(article, required_modes=("full",), strict_editorial=True)
    assert audit["publishable"] is False
    assert audit["metrics"]["language_issue_count"] == 5


def test_semantic_review_status_is_explicit() -> None:
    unchecked = publishable_article()
    unchecked_audit = audit_distilled(unchecked, required_modes=("full",), strict_editorial=True)
    assert unchecked_audit["metrics"]["semantic_review_status"] == "missing"
    assert unchecked_audit["metrics"]["semantic_review_completed"] is False
    assert any("语义级编辑审校" in item for item in unchecked_audit["warnings"])

    checked = publishable_article()
    checked["editorial_quality"] = {"status": "completed", "selected_version": "manual_revision"}
    checked_audit = audit_distilled(checked, required_modes=("full",), strict_editorial=True)
    assert checked_audit["metrics"]["semantic_review_status"] == "completed"
    assert checked_audit["metrics"]["semantic_review_completed"] is True
    assert not any("语义级编辑审校" in item for item in checked_audit["warnings"])


def test_version_selection_runs_after_safe_fixes() -> None:
    draft = complete_draft("三项能力各自在减少哪一种制作断点")
    revised = complete_draft("修订稿")
    revised["sections"][1]["title"] = "三项能力各自在提升哪一类指标"
    review = {"quality_report": {}, "revised_article": revised}

    result, _ = run_distill_with_fake(
        [draft, review],
        two_stage=False,
        editorial_review=True,
        required_modes=("full",),
    )
    assert result["distilled_title"] == "三项能力分别解决哪类制作问题"
    assert result["editorial_quality"]["selected_version"] == "draft"
    assert result["editorial_quality"]["language_fix_count"] == 1


def test_reader_voice_audit_is_advisory() -> None:
    article = publishable_article()
    walls = [
        "值得注意的是，水印不是给文字贴标签，而是让候选词选择形成统计偏向；读者还得同时记住密钥、随机源、文本长度和任务类型，才能理解检测结果究竟说明了什么以及它不能推出什么。",
        "值得注意的是，实验不是只看一个漂亮数字，而是要同时理解样本、指标、对照、人工条件和置信区间；这些前提全部挤在一句话里时，结论即使准确也会变得难以阅读，还会遮住最重要的比较关系。",
        "值得注意的是，治理不是检测后直接处罚，而是把模型信号、版本记录、任务规则、人工贡献和申诉机制放进同一流程；任何一个环节缺席，都可能让概率证据承担它无法承担的责任。",
    ]
    for section, wall in zip(article["sections"], walls):
        section["content"] = wall + wall

    voice = analyze_reader_voice(article)
    assert voice["dense_section_indexes"] == [1, 2, 3]
    assert len(voice["long_sentences"]) >= 3
    assert sum(item["count"] for item in voice["stiff_phrase_hits"]) >= 3
    assert voice["antithesis_count"] >= 3

    audit = audit_distilled(article, required_modes=("full",), strict_editorial=True)
    assert audit["publishable"] is True
    assert audit["metrics"]["reader_voice"] == voice
    assert any("文字墙" in item for item in audit["warnings"])
    assert any("报告套话" in item for item in audit["warnings"])


def test_human_voice_fingerprints_are_advisory() -> None:
    article = publishable_article()
    article["sections"][0]["content"] = (
        "你可能会觉得这个功能只是噱头？有人也许会问它是否增加成本？"
        "读者是不是担心流程更复杂？真正的关键是先分清它解决哪个环节。"
    )
    article["sections"][1]["content"] = (
        "你一定会问结果能否复现。本质上，测试只覆盖了当前条件。"
        "真正的答案是保留样本、指标和对照，不能把局部结果写成普遍结论。"
    )
    article["sections"][2]["content"] = (
        "有人可能会说边界不重要。归根结底，边界决定了结果能外推到哪里。"
    )

    voice = analyze_reader_voice(article)
    assert len(voice["proxy_reader_hits"]) >= 5
    assert len(voice["performative_depth_hits"]) >= 3
    assert voice["question_dense_section_indexes"] == [1]

    audit = audit_distilled(article, required_modes=("full",), strict_editorial=True)
    assert audit["publishable"] is True
    assert any("替读者预设想法" in item for item in audit["warnings"])
    assert any("仪式化深刻表达" in item for item in audit["warnings"])
    assert any("连续抛出三个以上问题" in item for item in audit["warnings"])


def test_abstract_action_titles_are_advisory() -> None:
    article = publishable_article()
    article["distilled_title"] = "一次故障如何被接住"
    article["visuals"] = [{"title": "Claude 与人，各自守住哪一段"}]
    voice = analyze_reader_voice(article)
    assert voice["abstract_action_hits"] == [
        {"path": "$.distilled_title", "text": "如何被接住"},
        {"path": "$.visuals[0].title", "text": "各自守住哪一段"},
    ]
    assert find_language_issues(article) == []
    audit = audit_distilled(article, required_modes=("full",), strict_editorial=True)
    assert audit["publishable"] is True
    assert any("抽象动作" in item for item in audit["warnings"])

    article["distilled_title"] = "一次故障，Claude 是怎么处理的"
    article["visuals"][0]["title"] = "Claude 负责什么，人负责什么"
    assert analyze_reader_voice(article)["abstract_action_hits"] == []


def test_uniform_sentence_rhythm_is_advisory() -> None:
    article = publishable_article()
    uniform = (
        "团队确认输入条件。团队确认输出结果。团队确认测试边界。"
        "团队确认失败样本。团队确认适用范围。"
    )
    uniform_other = (
        "模型记录输入条件。模型记录输出结果。模型记录测试边界。"
        "模型记录失败样本。模型记录适用范围。"
    )
    article["sections"][0]["content"] = uniform
    article["sections"][1]["content"] = uniform_other

    voice = analyze_reader_voice(article)
    assert voice["uniform_rhythm_section_indexes"] == [1, 2]
    audit = audit_distilled(article, required_modes=("full",), strict_editorial=True)
    assert audit["publishable"] is True
    assert any("句长过于均匀" in item for item in audit["warnings"])


def test_strict_gate_requires_human_narrative_contract() -> None:
    article = publishable_article()
    del article["narrative_plan"]["core_mechanism"]
    strict = audit_distilled(article, required_modes=("full",), strict_editorial=True)
    assert strict["publishable"] is False
    assert any("core_mechanism" in item for item in strict["blockers"])

    loose = audit_distilled(article, required_modes=("full",), strict_editorial=False)
    assert loose["publishable"] is True
    assert any("core_mechanism" in item for item in loose["warnings"])


def test_human_strategy_fields_are_compatibility_warnings() -> None:
    article = publishable_article()
    audit = audit_distilled(article, required_modes=("full",), strict_editorial=True)
    assert audit["publishable"] is True
    assert audit["metrics"]["missing_human_strategy_fields"] == [
        "opening_anchor",
        "reader_stake",
        "resonance_basis",
        "stance",
    ]
    assert any("人味策划字段" in item for item in audit["warnings"])

    article["narrative_plan"].update({
        "opening_anchor": "一项真实测试结果直接暴露了差异。",
        "reader_stake": "它会影响读者选择哪一种制作流程。",
        "resonance_basis": "共鸣来自材料中的时间成本和失败结果。",
        "stance": "当前证据支持按任务选择；出现统一基准后再调整判断。",
    })
    complete = audit_distilled(article, required_modes=("full",), strict_editorial=True)
    assert complete["metrics"]["missing_human_strategy_fields"] == []
    assert not any("人味策划字段" in item for item in complete["warnings"])


def test_editorial_pattern_contract_is_a_compatibility_warning() -> None:
    article = publishable_article()
    audit = audit_distilled(article, required_modes=("full",), strict_editorial=True)
    assert audit["publishable"] is True
    assert audit["metrics"]["missing_title_contract_fields"] == [
        "recognition_anchor",
        "click_reason",
        "reader_promise",
        "evidence_guardrail",
    ]
    assert audit["metrics"]["chapter_system_complete"] is False
    assert any("title_contract" in item for item in audit["warnings"])
    assert any("chapter_system" in item for item in audit["warnings"])

    article["narrative_plan"].update({
        "title_contract": {
            "recognition_anchor": "OpenAI",
            "click_reason": "一个真实反常结果",
            "reader_promise": "解释它为什么发生",
            "evidence_guardrail": "不把相关写成因果",
        },
        "opening_sequence": {
            "scene": "一个真实动作",
            "turn": "动作暴露了矛盾",
            "reveal": "主体随后揭示机制",
        },
        "chapter_system": {
            "archetype": "explainer",
            "throughline": "从问题走到机制和边界",
            "chapters": [
                {"section_id": "s1", "role": "进入", "reader_need": "看懂问题", "advance": "建立事实", "evidence": "材料一", "handoff": "继续解释"},
                {"section_id": "s2", "role": "解释", "reader_need": "理解机制", "advance": "补充因果", "evidence": "材料二", "handoff": "进入边界"},
                {"section_id": "s3", "role": "收束", "reader_need": "判断边界", "advance": "给出结论", "evidence": "材料三", "handoff": ""},
            ],
        },
    })
    missing_anchor = audit_distilled(article, required_modes=("full",), strict_editorial=True)
    assert missing_anchor["metrics"]["title_anchor_in_front_half"] is False
    assert any("未在前半句兑现" in item for item in missing_anchor["blockers"])

    article["distilled_title"] = "OpenAI能力如何改善制作流程"
    complete = audit_distilled(article, required_modes=("full",), strict_editorial=True)
    assert complete["metrics"]["missing_title_contract_fields"] == []
    assert complete["metrics"]["missing_opening_sequence_fields"] == []
    assert complete["metrics"]["chapter_system_complete"] is True
    assert complete["metrics"]["missing_chapter_section_ids"] == []
    assert complete["metrics"]["unknown_chapter_section_ids"] == []
    assert complete["metrics"]["title_anchor_in_front_half"] is True


if __name__ == "__main__":
    test_safe_fixes()
    test_protected_evidence_and_code()
    test_strict_gate_blocks_unresolved_grammar()
    test_normal_sentence_has_no_false_positive()
    test_safe_fixes_for_responsibility_examples()
    test_extended_chinese_grammar_safe_fixes()
    test_context_dependent_grammar_is_not_mechanically_rejected()
    test_redundant_equivalent_date_format_is_removed()
    test_clear_but_context_sensitive_fixes_block_auto_publish()
    test_semantic_review_status_is_explicit()
    test_version_selection_runs_after_safe_fixes()
    test_reader_voice_audit_is_advisory()
    test_human_voice_fingerprints_are_advisory()
    test_abstract_action_titles_are_advisory()
    test_uniform_sentence_rhythm_is_advisory()
    test_strict_gate_requires_human_narrative_contract()
    test_human_strategy_fields_are_compatibility_warnings()
    test_editorial_pattern_contract_is_a_compatibility_warning()
    print("language quality tests passed")
