#!/usr/bin/env python3
"""v9 行为级测试：证据边界、URL 去重、编辑审校与发布门禁。"""

import json
import os
import sqlite3
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace


PROJECT = str(Path(__file__).resolve().parent.parent)
SKILL_SCRIPTS = str(Path(PROJECT) / "scripts")
sys.path.insert(0, SKILL_SCRIPTS)

import distill as cli  # noqa: E402
import distiller as llm  # noqa: E402
from editorial_quality import audit_distilled, choose_preferred  # noqa: E402
from evidence import TRUST_WARNING, normalize_distilled, url_key  # noqa: E402
from fetcher import Article, article_from_text  # noqa: E402
from renderer import render_html  # noqa: E402


def response(payload):
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def test_ccswitch_text_config_discovery():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "cc-switch.db")
        connection = sqlite3.connect(db_path)
        connection.execute(
            "create table providers (id text, name text, app_type text, is_current integer, settings_config text)"
        )
        connection.execute(
            "create table provider_endpoints (id integer, app_type text, provider_id text, url text)"
        )
        connection.execute(
            "insert into providers values (?, ?, ?, ?, ?)",
            (
                "p1",
                "test",
                "codex",
                1,
                json.dumps({"auth": {"api_key": "secret"}, "config": 'model = "gpt-test"'}),
            ),
        )
        connection.execute(
            "insert into provider_endpoints values (?, ?, ?, ?)",
            (1, "codex", "p1", "https://relay.example"),
        )
        connection.commit()
        connection.close()

        config = llm._load_ccswitch_config(db_path)
        assert config == {
            "api_key": "secret",
            "base_url": "https://relay.example/v1",
            "model": "gpt-test",
        }


def test_url_and_evidence_invariants():
    original = "https://Vendor.Example:443/launch/"
    article = article_from_text("厂商称性能提升。", url=original, title="公告")
    article.source_links = [
        {
            "url": "https://lab.example/report",
            "source_type": "discovered",
            "fetched": False,
        }
    ]
    raw = {
        "source_notes": "保留这句。",
        "fact_check": [
            {
                "claim": "厂商称性能提升",
                "verdict": "确认",
                "evidence": [
                    {"url": "https://vendor.example/launch#top", "source_type": "independent"}
                ],
            },
            {
                "claim": "实验室完成复测",
                "verdict": "交叉验证",
                "evidence": [
                    {"url": "https://lab.example/report", "source_type": "independent"}
                ],
            },
        ],
    }

    first = normalize_distilled(raw, article)
    second = normalize_distilled(first, article)
    assert url_key(original) == url_key("https://vendor.example/launch#top")
    assert first["fact_check"][0]["evidence"][0]["source_type"] == "original"
    assert first["fact_check"][1]["evidence"][0]["source_type"] == "unverified_link"
    assert all(x["verdict"] == "原文声称" for x in first["fact_check"])
    assert first["evidence_summary"]["claims_with_independent_source"] == 0
    assert second["source_notes"].count(TRUST_WARNING) == 1

    article.source_links.append(
        {
            "url": "https://lab.example/report/",
            "source_type": "independent",
            "fetched": True,
            "retrieved_at": "2026-08-19T00:00:00+00:00",
            "content_hash": "abc123",
        }
    )
    upgraded = normalize_distilled(second, article)
    evidence = upgraded["fact_check"][1]["evidence"][0]
    assert evidence["source_type"] == "independent"
    assert evidence["retrieved_at"] == "2026-08-19T00:00:00+00:00"
    assert evidence["content_hash"] == "abc123"
    assert upgraded["fact_check"][1]["evidence_status"] == "cross_checked"
    assert TRUST_WARNING not in upgraded["source_notes"]
    assert "保留这句。" in upgraded["source_notes"]

    malformed = normalize_distilled(
        {"fact_check": ["没有对象结构", {"claim": "坏 evidence", "evidence": "not-a-list"}]},
        article,
    )
    assert malformed["fact_check"][0]["verdict"] == "无法核实"
    assert malformed["fact_check"][1]["evidence_status"] == "source_only"
    try:
        normalize_distilled([], article)
        raise AssertionError("顶层数组不应被静默接受")
    except ValueError as exc:
        assert "顶层必须是对象" in str(exc)


def test_evidence_url_filtering():
    article = article_from_text("正文", url="https://origin.example/a", title="原文")
    calls = []
    original_fetch = cli.fetch_article

    def fake_fetch(url, source_type="original"):
        calls.append(url)
        if "redirect" in url:
            return Article(url="https://origin.example/a/", text="原文", text_chars=2)
        if "broken" in url:
            return Article(url=url, error="boom")
        return Article(
            url=url,
            title=url.rsplit("/", 1)[-1],
            text="独立正文",
            text_chars=4,
            retrieved_at="2026-08-19T00:00:00+00:00",
            content_hash="hash-" + url.rsplit("/", 1)[-1],
            source_type=source_type,
        )

    cli.fetch_article = fake_fetch
    try:
        args = SimpleNamespace(
            independent_url=[],
            official_url=[],
            no_discover_official=True,
            official_source_limit=3,
            evidence_url=[
                "https://origin.example/a#self",
                "https://lab.example/one",
                "https://lab.example/one#duplicate",
                "https://lab.example/redirect",
                "https://lab.example/broken",
                "https://lab.example/two",
                "https://lab.example/three",
                "https://lab.example/four",
            ]
        )
        result = cli._get_evidence_articles(args, article)
    finally:
        cli.fetch_article = original_fetch

    assert calls == [
        "https://lab.example/one",
        "https://lab.example/redirect",
        "https://lab.example/broken",
        "https://lab.example/two",
        "https://lab.example/three",
    ]
    assert [x.url for x in result] == [
        "https://lab.example/one",
        "https://lab.example/two",
        "https://lab.example/three",
    ]
    assert len(article.source_links) == 3
    assert all(x["source_type"] == "supplemental" and x["fetched"] for x in article.source_links)


def test_public_render_hides_audit_ids_and_respects_visual_anchor():
    article = article_from_text("正文", url="https://example.com/a", title="来源")
    distilled = {
        "distilled_title": "测试文章",
        "quick_scan": ["第一条速览用于说明核心变化和读者需要知道的主要结论。", "第二条速览用于说明变化带来的实际影响和使用价值。", "第三条速览用于说明证据边界和目前仍然未知的信息。"],
        "sections": [
            {
                "id": "s1",
                "title": "先解释机制",
                "content": "第一段。\n\n第二个自然段。",
                "concept_explainers": [
                    {"term": "术语", "definition": "定义。", "analogy": "类比。"}
                ],
                "analogies": [
                    {"concept": "工作方式", "analogy": "像一条便于理解的路线。"}
                ],
                "archive_original": [
                    {"original": "Source wording.", "translation": "中文释义。"}
                ],
            },
            {"id": "s2", "title": "再说明边界", "content": "第二段。"},
            {"id": "s3", "title": "最后给出结论", "content": "第三段。"},
        ],
        "experiment_ledger": [
            {
                "id": "exp-quality",
                "title": "实验支持这个结论",
                "after_section_id": "s1",
                "question": "问题",
                "result": "结果",
                "claim_ids": ["c5", "c6"],
            }
        ],
        "evidence_gallery": [
            {"media_id": "media-chart", "type": "image", "url": "https://example.com/chart.png", "registered": True}
        ],
        "visuals": [
            {
                "type": "interactive_compare",
                "title": "机制切换",
                "after_section_id": "s1",
                "data": {
                    "instruction": "切换模式观察结果。",
                    "prompt": "输入 <script>bad()</script>",
                    "options": [{"label": "候选 A"}, {"label": "候选 B"}],
                    "modes": [
                        {"label": "模式一", "selected_index": 0, "note": "选择第一个。"},
                        {"label": "模式二", "selected_index": 1, "note": "选择第二个。"},
                    ],
                    "takeaway": "候选不变，模式改变结果。",
                },
            },
            {
                "type": "scenario_calculator",
                "title": "证据情景卡",
                "after_section_id": "s1",
                "data": {
                    "instruction": "切换平台并调整成本。",
                    "tabs": [
                        {"label": "平台 A", "metrics": [{"label": "平均支付", "value": "$20"}]},
                        {"label": "平台 B", "metrics": [{"label": "平均支付", "value": "$16"}]},
                    ],
                    "slider": {"label": "假设成本", "min": 0, "max": 10, "step": 0.5, "value": 4, "prefix": "$"},
                    "result": {"label": "情景净额", "base": 15.78, "prefix": "$", "decimals": 2},
                    "source_asset_ids": ["media-chart"],
                    "formula_note": "来源基数减去读者假设。",
                    "caption": "来源数据与读者假设分开。",
                },
            }
        ],
    }

    html = render_html(article, distilled)
    assert '<details class="experiment-block"' in html
    assert "证据锚点" not in html
    assert ">exp-quality<" not in html
    assert html.count('class="art-annotation-label"') >= 3
    assert "名词解释" in html and "通俗理解" in html
    assert "原文引文" in html and "英文原句" in html and "中文释义" in html
    assert "<p>第一段。</p><p>第二个自然段。</p>" in html
    assert 'data-interactive-compare' in html
    assert html.count('data-interactive-mode=') == 2
    assert 'aria-pressed="true"' in html and 'aria-pressed="false"' in html
    assert "&lt;script&gt;bad()&lt;/script&gt;" in html
    assert "<script>bad()</script>" not in html
    assert 'data-scenario-calculator' in html
    assert html.count('data-scenario-tab=') == 2
    assert 'type="range"' in html and 'data-scenario-result' in html

    invalid = json.loads(json.dumps(distilled, ensure_ascii=False))
    invalid["visuals"][0]["data"]["modes"][1]["selected_index"] = 4
    audit = audit_distilled(invalid, {}, required_modes=("full",), strict_editorial=True)
    assert any("机制互动缺少" in item for item in audit["blockers"])

    invalid_scenario = json.loads(json.dumps(distilled, ensure_ascii=False))
    invalid_scenario["visuals"][1]["data"]["slider"]["max"] = 0
    audit = audit_distilled(invalid_scenario, {}, required_modes=("full",), strict_editorial=True)
    assert any("证据情景卡缺少" in item for item in audit["blockers"])

    missing_scenario_source = json.loads(json.dumps(distilled, ensure_ascii=False))
    missing_scenario_source["visuals"][1]["data"]["source_asset_ids"] = ["missing-chart"]
    audit = audit_distilled(missing_scenario_source, {}, required_modes=("full",), strict_editorial=True)
    assert any("未进入证据图库" in item for item in audit["blockers"])

    too_many_quotes = json.loads(json.dumps(distilled, ensure_ascii=False))
    too_many_quotes["sections"][0]["archive_original"] *= 3
    quote_audit = audit_distilled(
        too_many_quotes, {}, required_modes=("full",), strict_editorial=True
    )
    assert any("原文引文有 3 条" in item for item in quote_audit["blockers"])


def test_term_marker_follows_inline_translation():
    article = article_from_text("正文", url="https://example.com/a", title="来源")
    distilled = {
        "distilled_title": "术语括注测试",
        "sections": [
            {
                "id": "s1",
                "title": "解释机制",
                "content": "首次出现 feature flag（功能开关），后文继续使用 feature flag。",
                "concept_explainers": [
                    {
                        "term": "feature flag",
                        "definition": "控制功能是否启用的配置开关。",
                        "analogy": "像一只分路开关。",
                    }
                ],
            }
        ],
    }
    rendered = render_html(article, distilled)
    assert 'feature flag（功能开关）<sup class="term-marker-wrap"' in rendered
    assert 'feature flag<sup class="term-marker-wrap"' not in rendered


class FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return response(outcome)


class FakeClient:
    def __init__(self, outcomes):
        self.chat = SimpleNamespace(completions=FakeCompletions(outcomes))


def complete_draft(title="草稿", covered_ids=None):
    return {
        "distilled_title": title,
        "quick_scan": ["要点一", "要点二", "要点三"],
        "narrative_plan": {
            "reader_tension": "读者难以判断这次变化对自己有什么实际影响。",
            "core_mechanism": "执行方式改变了，所以价值与边界需要放在一起判断。",
            "central_question": "这件事意味着什么？",
            "short_answer": "它改变了执行方式。",
            "section_logic": ["先讲变化", "再讲机制", "最后讲边界"],
            "closing_answer": "价值成立，但需要注意边界。",
        },
        "sections": [
            {"title": "变化已经发生", "content": "第一段解释现象和关键结论。"},
            {"title": "机制决定效果", "content": "第二段承接前文，解释为什么会出现这个结果。"},
            {"title": "边界决定选择", "content": "第三段说明限制，并回答开头问题。"},
        ],
        "fact_check": [],
        "takeaway_list": ["先核对来源", "再决定是否采用"],
        "editorial_coverage": {
            "covered_claim_ids": covered_ids or [],
            "omitted_claims": [],
        },
    }


def run_distill_with_fake(
    outcomes,
    two_stage=True,
    editorial_review=True,
    required_modes=("full",),
    checkpoint_dir=None,
    review_output_mode=None,
):
    client = FakeClient(outcomes)
    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = lambda **_kwargs: client
    old_module = sys.modules.get("openai")
    old_key = os.environ.get("DISTILL_LLM_KEY")
    old_review_output_mode = os.environ.get("DISTILL_REVIEW_OUTPUT_MODE")
    sys.modules["openai"] = fake_openai
    os.environ["DISTILL_LLM_KEY"] = "test-key"
    if review_output_mode is None:
        os.environ.pop("DISTILL_REVIEW_OUTPUT_MODE", None)
    else:
        os.environ["DISTILL_REVIEW_OUTPUT_MODE"] = review_output_mode
    try:
        result = llm.distill(
            article_from_text("原文", url="https://example.com/article", title="测试"),
            two_stage=two_stage,
            editorial_review=editorial_review,
            required_modes=required_modes,
            checkpoint_dir=checkpoint_dir,
        )
    finally:
        if old_module is None:
            sys.modules.pop("openai", None)
        else:
            sys.modules["openai"] = old_module
        if old_key is None:
            os.environ.pop("DISTILL_LLM_KEY", None)
        else:
            os.environ["DISTILL_LLM_KEY"] = old_key
        if old_review_output_mode is None:
            os.environ.pop("DISTILL_REVIEW_OUTPUT_MODE", None)
        else:
            os.environ["DISTILL_REVIEW_OUTPUT_MODE"] = old_review_output_mode
    return result, client.chat.completions.calls


def test_article_patch_validation_and_merge():
    draft = complete_draft("草稿")
    for index, section in enumerate(draft["sections"], 1):
        section["id"] = f"s{index}"
    original = json.loads(json.dumps(draft, ensure_ascii=False))

    merged = llm._apply_article_patch(
        draft,
        {
            "set_fields": {"distilled_title": "修订标题", "quick_scan": ["一", "二", "三"]},
            "section_updates": [
                {"id": "s2", "set": {"title": "新机制标题", "content": "新的完整章节正文。"}}
            ],
        },
    )
    assert merged["distilled_title"] == "修订标题"
    assert merged["quick_scan"] == ["一", "二", "三"]
    assert merged["sections"][1]["title"] == "新机制标题"
    assert merged["sections"][1]["content"] == "新的完整章节正文。"
    assert merged["sections"][0] == original["sections"][0]
    assert merged["fact_check"] == original["fact_check"]
    assert draft == original

    invalid_patches = [
        {"set_fields": {"invented_field": "x"}},
        {"section_updates": [{"id": "missing", "set": {"title": "x"}}]},
        {
            "set_fields": {"sections": original["sections"]},
            "section_updates": [{"id": "s1", "set": {"title": "x"}}],
        },
    ]
    for patch in invalid_patches:
        try:
            llm._apply_article_patch(draft, patch)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid patch was accepted: {patch}")


def test_patch_review_and_full_fallback_modes():
    research = {"claims": [], "unknowns": []}
    draft = complete_draft("草稿")
    for index, section in enumerate(draft["sections"], 1):
        section["id"] = f"s{index}"
    patch_review = {
        "quality_report": {"coherence_score": 96, "coverage_score": 100},
        "article_patch": {
            "set_fields": {"distilled_title": "补丁修订稿"},
            "section_updates": [
                {"id": "s2", "set": {"content": "第二段承接前文，并用因果关系解释具体机制。"}}
            ],
        },
    }
    result, calls = run_distill_with_fake([research, draft, patch_review])
    assert len(calls) == 3
    assert result["distilled_title"] == "补丁修订稿"
    assert result["sections"][0] == draft["sections"][0]
    assert result["editorial_quality"]["output_mode"] == "patch"
    assert "article_patch" in calls[2]["messages"][0]["content"]
    assert "只回传实际修改字段" in calls[2]["messages"][1]["content"]

    invalid_patch_review = {
        "quality_report": {},
        "article_patch": {"set_fields": {"invented_field": "x"}},
    }
    fallback = complete_draft("完整回退稿")
    fallback_review = {"quality_report": {"coherence_score": 94}, "revised_article": fallback}
    result, calls = run_distill_with_fake(
        [research, draft, invalid_patch_review, fallback_review]
    )
    assert len(calls) == 4
    assert result["distilled_title"] == "完整回退稿"
    assert result["editorial_quality"]["output_mode"] == "full_fallback"
    assert "返回完整 revised_article" in calls[3]["messages"][1]["content"]
    assert "article_patch" not in calls[3]["messages"][0]["content"]

    full = complete_draft("显式完整稿")
    result, calls = run_distill_with_fake(
        [research, draft, {"quality_report": {}, "revised_article": full}],
        review_output_mode="full",
    )
    assert len(calls) == 3
    assert result["distilled_title"] == "显式完整稿"
    assert result["editorial_quality"]["output_mode"] == "full"
    assert "revised_article" in calls[2]["messages"][0]["content"]
    assert "article_patch" not in calls[2]["messages"][0]["content"]


def test_three_stage_and_cost_modes():
    research = {
        "claims": [{"id": "c1", "claim": "原文存在", "importance": "high"}],
        "unknowns": [],
    }
    draft = complete_draft("草稿", ["c1"])
    revised = complete_draft("修订稿", ["c1"])
    revised["sections"][1]["content"] = "第二段明确承接第一段，并补回机制解释。"
    review = {
        "quality_report": {"coherence_score": 95, "coverage_score": 100},
        "revised_article": revised,
    }
    result, calls = run_distill_with_fake([research, draft, review])
    assert len(calls) == 3
    assert result["research_ledger"] == research
    assert "研究员生成的证据账本" in calls[1]["messages"][1]["content"]
    assert "原文存在" in calls[1]["messages"][1]["content"]
    assert "待审校完整草稿" in calls[2]["messages"][1]["content"]
    assert "--- 原文标题 ---\n测试" in calls[2]["messages"][1]["content"]
    assert result["distilled_title"] == "修订稿"
    assert result["editorial_quality"]["status"] == "completed"
    assert result["editorial_quality"]["selected_version"] == "revised"

    single = complete_draft("单轮")
    result, calls = run_distill_with_fake(
        [single], two_stage=False, editorial_review=False
    )
    assert len(calls) == 1
    assert result["distilled_title"] == "单轮"
    assert "research_ledger" not in result
    assert result["editorial_quality"]["status"] == "skipped"

    two_call = complete_draft("两阶段", ["c1"])
    result, calls = run_distill_with_fake(
        [research, two_call], editorial_review=False
    )
    assert len(calls) == 2
    assert result["distilled_title"] == "两阶段"
    assert result["research_ledger"] == research


def test_review_failure_and_final_candidate_repair():
    research = {
        "claims": [{"id": "c1", "claim": "关键事实", "importance": "high"}],
        "unknowns": [],
    }
    draft = complete_draft("可发布草稿", ["c1"])
    result, calls = run_distill_with_fake([research, draft, "not json"])
    assert len(calls) == 3
    assert result["distilled_title"] == "可发布草稿"
    assert result["editorial_quality"]["status"] == "review_failed"

    incomplete = {"distilled_title": "残缺修订稿", "sections": []}
    review = {"quality_report": {"coherence_score": 20}, "revised_article": incomplete}
    repaired = complete_draft("定向修复后的成稿", ["c1"])
    repair = {"quality_report": {"coverage_score": 100}, "revised_article": repaired}
    result, calls = run_distill_with_fake([research, draft, review, repair])
    assert len(calls) == 4
    assert result["distilled_title"] == "定向修复后的成稿"
    assert result["editorial_quality"]["selected_version"] == "revised"
    assert result["editorial_quality"]["repair_status"] == "completed"


def test_research_json_fallback_still_reviews():
    draft = complete_draft("研究失败后的草稿")
    revised = complete_draft("研究失败后的修订稿")
    review = {"quality_report": {}, "revised_article": revised}
    result, calls = run_distill_with_fake(["not json", draft, review])
    assert len(calls) == 3
    assert result["distilled_title"] == "研究失败后的修订稿"
    assert "research_ledger" not in result


def test_editorial_quality_gate():
    research = {
        "claims": [
            {"id": "c1", "claim": "关键一", "importance": "high"},
            {"id": "c2", "claim": "关键二", "importance": "high"},
        ]
    }
    broken = complete_draft("问题稿", ["c1"])
    broken["sections"][1] = dict(broken["sections"][0])
    audit = audit_distilled(broken, research, ("full",))
    assert audit["publishable"] is False
    assert any("重复段落" in x for x in audit["blockers"])
    assert any("c2" in x for x in audit["blockers"])

    fixed = complete_draft("修复稿", ["c1"])
    fixed["editorial_coverage"]["omitted_claims"] = [
        {"id": "c2", "reason": "证据不足，仅保留为未知项"}
    ]
    audit = audit_distilled(fixed, research, ("full",))
    assert audit["publishable"] is True

    selected, name, draft_audit, revised_audit = choose_preferred(
        broken, fixed, research, ("full",)
    )
    assert name == "revised" and selected["distilled_title"] == "修复稿"
    assert draft_audit["publishable"] is False
    assert revised_audit["publishable"] is True


def test_version_release_paraphrase_and_number_labels():
    research = {
        "claims": [
            {
                "id": "c-version",
                "claim": "原文称 verifiers 的多智能体支持发布于版本 0.3.0。",
                "claim_kind": "version",
                "importance": "high",
            },
            {
                "id": "c-metric",
                "claim": "成功率约为百分之五十。",
                "claim_kind": "metric",
                "importance": "high",
            },
        ]
    }
    distilled = complete_draft("版本与数字口径", ["c-version", "c-metric"])
    for index, section in enumerate(distilled["sections"], 1):
        section["id"] = f"s{index}"
    distilled["sections"][0]["content"] = (
        "发布方称多智能体支持随 verifiers 0.3.0 发布，任务成功率约为50%。"
    )
    distilled["number_stories"] = [
        {
            "id": "rate",
            "title": "任务成功率",
            "value": "50%",
            "unit": "成功率",
            "denominator": "同一组任务中的成功任务比例",
            "scope": "本次任务集合",
            "period": "未知",
            "baseline": "低于半数",
            "change": "升至约一半",
            "boundary": "不能代表其他任务",
            "labels": {"period": "统计时间未公布"},
            "source_url": "https://example.com/article",
            "claim_ids": ["c-metric"],
            "after_section_id": "s1",
        }
    ]
    audit = audit_distilled(distilled, research, ("full",), strict_editorial=True)
    assert audit["metrics"]["semantically_missing_high_claim_ids"] == []
    assert audit["metrics"]["incomplete_high_metric_story_claim_ids"] == []

def test_response_format_retry_boundary():
    class ApiError(Exception):
        def __init__(self, message, status_code):
            super().__init__(message)
            self.status_code = status_code

    cfg = {"model": "test"}
    auth_client = FakeClient([ApiError("invalid api key", 401), {"ok": True}])
    try:
        llm._call_json(auth_client, cfg, "system", "user", 0.1)
        raise AssertionError("鉴权错误不应被吞掉")
    except ApiError:
        pass
    assert len(auth_client.chat.completions.calls) == 1

    format_client = FakeClient(
        [ApiError("unsupported response_format json_object", 400), {"ok": True}]
    )
    result = llm._call_json(format_client, cfg, "system", "user", 0.1)
    assert result == {"ok": True}
    assert len(format_client.chat.completions.calls) == 2
    assert "response_format" in format_client.chat.completions.calls[0]
    assert "response_format" not in format_client.chat.completions.calls[1]


def test_streaming_response_is_assembled():
    class Stream:
        def __init__(self):
            self.closed = False

        def __iter__(self):
            for part in ('{"ok":', ' true}'):
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=part))]
                )

        def close(self):
            self.closed = True

    stream = Stream()
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return stream

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result = llm._call_json(
        client,
        {"model": "test", "_stream": True, "_manual_max_retries": 0},
        "system",
        "user",
        0.1,
    )
    assert result == {"ok": True}
    assert calls[0]["stream"] is True
    assert stream.closed is True


def test_full_draft_context_keeps_original_without_repeating_attachments():
    article = article_from_text(
        "这是必须保留的原始文章正文。",
        url="https://example.com/original",
        title="原始文章",
    )
    evidence = article_from_text(
        "这是只应进入研究阶段、不应在写作阶段重复发送的附件全文。",
        url="https://evidence.example/report",
        title="附件",
    )
    evidence.source_type = "official"
    research = {
        "claims": [{"id": "c1", "claim": "附件支持的关键结论", "importance": "high"}],
        "unknowns": ["尚无独立复现"],
    }
    context = llm._build_draft_context(
        article,
        [evidence],
        research,
        "包含全部附件全文的旧上下文",
    )
    assert "这是必须保留的原始文章正文" in context
    assert "附件支持的关键结论" in context
    assert "尚无独立复现" in context
    assert "这是只应进入研究阶段" not in context
    assert "包含全部附件全文的旧上下文" not in context


def test_stage_checkpoints_resume_without_model_calls():
    research = {
        "claims": [{"id": "c1", "claim": "关键事实", "importance": "high"}],
        "unknowns": [],
    }
    draft = complete_draft("草稿", ["c1"])
    revised = complete_draft("修订稿", ["c1"])
    review = {"quality_report": {}, "revised_article": revised}
    with tempfile.TemporaryDirectory() as temp_dir:
        first, first_calls = run_distill_with_fake(
            [research, draft, review], checkpoint_dir=temp_dir
        )
        second, second_calls = run_distill_with_fake([], checkpoint_dir=temp_dir)
        full_revision = complete_draft("完整协议修订稿", ["c1"])
        third, third_calls = run_distill_with_fake(
            [{"quality_report": {}, "revised_article": full_revision}],
            checkpoint_dir=temp_dir,
            review_output_mode="full",
        )
        assert len(first_calls) == 3
        assert len(second_calls) == 0
        assert len(third_calls) == 1
        assert first["distilled_title"] == second["distilled_title"] == "修订稿"
        assert third["distilled_title"] == "完整协议修订稿"
        assert os.path.exists(os.path.join(temp_dir, "research.json"))
        assert os.path.exists(os.path.join(temp_dir, "writing.json"))
        assert os.path.exists(os.path.join(temp_dir, "review.json"))


def test_source_snapshot_restores_exact_inputs_after_fetch_failure():
    article = article_from_text(
        "稳定保存的原始正文",
        url="https://example.com/article",
        title="原始标题",
    )
    evidence = article_from_text(
        "已经成功抓取的官方附件",
        url="https://docs.example.com/model-card",
        title="模型卡",
    )
    evidence.source_type = "official"
    evidence.repository_files = [
        {"path": "README.md", "url": "https://example.com/README.md", "content": "说明"}
    ]
    with tempfile.TemporaryDirectory() as temp_dir:
        path = cli._save_source_snapshot(temp_dir, article, [evidence])
        restored = cli._load_source_snapshot(temp_dir, "https://example.com/article#top")
        assert path == os.path.join(temp_dir, "source.json")
        assert restored is not None
        restored_article, restored_evidence, restored_path = restored
        assert restored_path == path
        assert restored_article.text == article.text
        assert restored_article.content_hash == article.content_hash
        assert restored_evidence[0].text == evidence.text
        assert restored_evidence[0].repository_files == evidence.repository_files
        assert cli._load_source_snapshot(temp_dir, "https://other.example/article") is None


def test_quality_repair_runs_only_after_strict_gate_failure():
    research = {
        "claims": [
            {"id": "c1", "claim": "关键一", "importance": "high"},
            {"id": "c2", "claim": "关键二", "importance": "high"},
        ],
        "unknowns": [],
    }
    broken = complete_draft("缺口稿", ["c1"])
    for index, section in enumerate(broken["sections"], 1):
        section["id"] = f"s{index}"
    broken["sections"][0]["content"] = "关键一已经确认。"
    broken["sections"][1] = dict(broken["sections"][0])
    reviewed = {"quality_report": {}, "revised_article": broken}

    fixed = complete_draft("修复稿", ["c1", "c2"])
    for index, section in enumerate(fixed["sections"], 1):
        section["id"] = f"s{index}"
    fixed["sections"][0]["content"] = "关键一已经确认，先解释具体变化。"
    fixed["sections"][1]["content"] = "关键二说明机制如何承接这项变化。"
    repair = {
        "quality_report": {"coverage_score": 100},
        "article_patch": {
            "set_fields": {
                "distilled_title": "修复稿",
                "editorial_coverage": fixed["editorial_coverage"],
                "sections": fixed["sections"],
            },
            "section_updates": [],
        },
    }

    result, calls = run_distill_with_fake([research, broken, reviewed, repair])
    assert len(calls) == 4
    assert result["distilled_title"] == "修复稿"
    assert result["editorial_quality"]["repair_status"] == "completed"
    assert result["editorial_quality"]["final_audit"]["publishable"] is True
    repair_prompt = calls[-1]["messages"][-1]["content"]
    assert "meta_narration_section_indexes" in repair_prompt
    assert "article_patch" in repair_prompt


def test_final_quality_record_persists_audit_and_timings():
    with tempfile.TemporaryDirectory() as temp_dir:
        distilled = {
            "editorial_quality": {
                "status": "completed",
                "selected_version": "revised",
                "stage_timings_seconds": {"研究阶段": 1.2, "写作阶段": 2.3},
            }
        }
        audit = {"publishable": True, "score": 100, "blockers": []}
        rendered = {"ok": True, "inventory_count": 2, "used_count": 2}
        path = cli._save_quality_record(temp_dir, distilled, audit, rendered)
        assert path == os.path.join(temp_dir, "final-quality.json")
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        assert record["final_audit"] == audit
        assert record["rendered_media_audit"] == rendered
        assert record["stage_timings_seconds"]["写作阶段"] == 2.3


def test_media_fingerprint_ignores_signed_and_decorative_assets():
    article = article_from_text("正文", url="https://example.com/a", title="文章")
    article.media_assets = [
        {"id": "hero-1", "type": "video", "url": "https://cdn.example/demo.mp4?sig=one", "asset_role": "demo"},
        {"id": "decor-1", "type": "image", "url": "https://cdn.example/footer.png?v=1", "asset_role": "other"},
    ]
    first = llm._stable_media_fingerprint(article)
    article.media_assets[0]["url"] = "https://cdn.example/demo.mp4?sig=two"
    article.media_assets[1]["url"] = "https://cdn.example/footer.png?v=2"
    second = llm._stable_media_fingerprint(article)
    assert first == second
    article.media_assets[0]["url"] = "https://cdn.example/other-demo.mp4?sig=two"
    assert first != llm._stable_media_fingerprint(article)


def test_checkpoint_fingerprint_ignores_volatile_evidence_body():
    original = article_from_text("稳定原文", url="https://example.com/a", title="文章")
    changed_original = article_from_text("原文已经变化", url="https://example.com/a", title="文章")
    evidence_v1 = article_from_text("动态计数 100", url="https://repo.example/project", title="仓库")
    evidence_v2 = article_from_text("动态计数 101", url="https://repo.example/project", title="仓库")
    cfg = {"model": "test", "base_url": "https://relay.example/v1"}
    common = (cfg, ("full",), "writing", "review", True, True)
    first = llm._pipeline_fingerprint(original, [evidence_v1], *common)
    second = llm._pipeline_fingerprint(original, [evidence_v2], *common)
    changed = llm._pipeline_fingerprint(changed_original, [evidence_v2], *common)
    assert first == second
    assert first != changed


def test_ledger_truncation_keeps_valid_json():
    ledger = {
        "claims": [{"id": str(i), "claim": "x" * 1000} for i in range(100)],
        "background": ["b" * 1000] * 30,
        "unknowns": ["u" * 1000] * 30,
        "source_assessment": "s" * 5000,
    }
    serialized = llm._serialize_research_ledger(ledger, max_chars=5000)
    parsed = json.loads(serialized)
    assert len(serialized) <= 5000
    assert parsed["ledger_truncated"] is True


def test_output_is_always_a_single_html_file():
    article = article_from_text("正文", url="https://example.com/a", title="标题")
    distilled = {
        "distilled_title": "解读",
        "quick_scan": ["要点"],
        "sections": [{"title": "结论", "content": "内容"}],
        "fact_check": [],
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        output = os.path.join(temp_dir, "article.md")
        args = SimpleNamespace(output=output)
        wrote = cli._post_distill(article, distilled, args, "unused")
        html_output = os.path.join(temp_dir, "article.html")
        assert wrote == [html_output]
        assert os.path.exists(html_output)
        assert not os.path.exists(output)


if __name__ == "__main__":
    test_ccswitch_text_config_discovery()
    test_url_and_evidence_invariants()
    test_evidence_url_filtering()
    test_article_patch_validation_and_merge()
    test_patch_review_and_full_fallback_modes()
    test_three_stage_and_cost_modes()
    test_review_failure_and_final_candidate_repair()
    test_research_json_fallback_still_reviews()
    test_editorial_quality_gate()
    test_version_release_paraphrase_and_number_labels()
    test_final_quality_record_persists_audit_and_timings()
    test_term_marker_follows_inline_translation()
    test_response_format_retry_boundary()
    test_streaming_response_is_assembled()
    test_full_draft_context_keeps_original_without_repeating_attachments()
    test_stage_checkpoints_resume_without_model_calls()
    test_source_snapshot_restores_exact_inputs_after_fetch_failure()
    test_quality_repair_runs_only_after_strict_gate_failure()
    test_checkpoint_fingerprint_ignores_volatile_evidence_body()
    test_ledger_truncation_keeps_valid_json()
    test_output_is_always_a_single_html_file()
    print("hardening tests passed")
