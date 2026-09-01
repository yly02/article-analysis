"""Markdown 渲染模块：把解读 JSON 渲染成带 YAML frontmatter 的 .md 文件。

v6 升级（融文风格 + 目录导航）：
- v5 基础上去掉所有组件标签，比方/概念/原文融进正文流
- 新增目录导航（TOC）：可点击跳转的编号列表
- 新增推荐理由行
- 事实核查降为页脚脚注
- 保留 YAML frontmatter 供下载二次阅读
"""

from __future__ import annotations

import re
from typing import Any

from fetcher import Article


def _slugify(title: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff\s-]", "", title)[:30].strip()
    s = re.sub(r"[\s_]+", "-", s)
    return s.lower().strip("-") or "article"


def _md(s: Any) -> str:
    return str(s) if s is not None else ""


def _section_display_title(section: dict) -> str:
    """Return the reader-facing title without an internal category label."""
    title = str(section.get("title") or "").strip()
    tag = str(section.get("tag") or "").strip()
    if not title or not tag:
        return title
    for prefix in (f"[{tag}]", f"【{tag}】"):
        if title.startswith(prefix):
            return title[len(prefix):].lstrip()
    return title


def _assign_by_section_id(sections: list, items: list) -> tuple[dict[int, list], list]:
    assigned = {i: [] for i in range(len(sections))}
    by_id = {
        str(section.get("id") or "").strip(): i
        for i, section in enumerate(sections)
        if str(section.get("id") or "").strip()
    }
    leftovers = []
    for item in items:
        anchor = str(item.get("after_section_id") or "").strip()
        if anchor in by_id:
            assigned[by_id[anchor]].append(item)
        else:
            leftovers.append(item)
    return assigned, leftovers


def _value_text(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(item) for item in value if str(item).strip())
    return str(value or "").strip()


def _append_experiment_md(parts: list[str], experiment: dict) -> None:
    title = experiment.get("title") or experiment.get("question") or "实验拆解"
    parts.extend([f"### 实验拆解｜{title}", ""])
    fields = [
        ("研究问题", experiment.get("question")),
        ("实验设置", experiment.get("setup")),
        ("样本与轮次", experiment.get("sample")),
        ("模型", experiment.get("models")),
        ("判定指标", experiment.get("metric")),
        ("对照或基线", experiment.get("control")),
        ("结果", experiment.get("result")),
        ("边界", experiment.get("limitations")),
    ]
    for label, value in fields:
        display = _value_text(value)
        if display:
            parts.append(f"- **{label}**：{display}")
    parts.append("")


def _append_case_story_md(parts: list[str], story: dict) -> None:
    title = story.get("title") or "案例复盘"
    parts.extend([f"### 案例复盘｜{title}", ""])
    if story.get("setup"):
        parts.extend([str(story.get("setup")), ""])
    for i, beat in enumerate(story.get("beats") or [], 1):
        if not isinstance(beat, dict) or not beat.get("text"):
            continue
        parts.append(f"{i}. **{beat.get('label') or '阶段'}**：{beat.get('text')}")
        if beat.get("source_quote"):
            parts.append(f"   > {beat.get('source_quote')}")
    if story.get("outcome"):
        parts.append(f"- **结果**：{story.get('outcome')}")
    if story.get("boundary"):
        parts.append(f"- **不能据此证明**：{story.get('boundary')}")
    mode = str(story.get("source_mode") or "reconstruction").lower()
    provenance = "含原文逐字引文" if mode == "quoted" else "基于证据重建事件顺序，非逐字对话"
    parts.extend([f"> {provenance}", ""])


def _append_visual_md(parts: list[str], visual: dict) -> None:
    vtype = visual.get("type") or ""
    data = visual.get("data") or {}
    title = visual.get("title") or ""
    if title:
        parts.extend([f"**{title}**", ""])
    if vtype == "compare_table":
        headers = data.get("headers") or []
        rows = data.get("rows") or []
        if headers:
            parts.append("| " + " | ".join(headers) + " |")
            parts.append("|" + "---|" * len(headers))
            for row in rows:
                parts.append("| " + " | ".join(str(cell) for cell in row) + " |")
            parts.append("")
    elif vtype == "delta_table":
        baseline_label = str(data.get("baseline_label") or "调整前").strip()
        current_label = str(data.get("current_label") or "调整后").strip()
        parts.extend([
            f"| 指标 | {baseline_label} | {current_label} | 变化 |",
            "|---|---:|---:|---:|",
        ])
        symbols = {"up": "↑", "down": "↓", "flat": "→"}
        for row in (data.get("rows") or []):
            if not isinstance(row, dict):
                continue
            symbol = symbols.get(str(row.get("direction") or "flat").lower(), "→")
            parts.append(
                f"| {row.get('label') or ''} | {row.get('baseline') or ''} | "
                f"{row.get('current') or ''} | {symbol} {row.get('change') or ''} |"
            )
        parts.append("")
        boundary = str(data.get("boundary") or "").strip()
        if boundary:
            parts.extend([f"> **怎么读：**{boundary}", ""])
    elif vtype == "status_matrix":
        columns = [str(x).strip() for x in (data.get("columns") or []) if str(x).strip()]
        parts.append("| 对象 | " + " | ".join(columns) + " |")
        parts.append("|---|" + "---|" * len(columns))
        for row in (data.get("rows") or []):
            if not isinstance(row, dict):
                continue
            values = [
                str(cell.get("value") or "")
                for cell in (row.get("cells") or [])
                if isinstance(cell, dict)
            ]
            parts.append(f"| {row.get('label') or ''} | " + " | ".join(values) + " |")
        parts.append("")
        caption = str(data.get("caption") or "").strip()
        boundary = str(data.get("boundary") or "").strip()
        if caption:
            parts.extend([f"*{caption}*", ""])
        if boundary:
            parts.extend([f"> **怎么读：**{boundary}", ""])
    elif vtype == "decision_table":
        parts.extend(["| 条件 | 结果 | 可以怎么做 |", "|---|---|---|"])
        for row in (data.get("rows") or []):
            if not isinstance(row, dict):
                continue
            parts.append(
                f"| {row.get('condition') or ''} | {row.get('result') or ''} | {row.get('action') or ''} |"
            )
        parts.append("")
        boundary = str(data.get("boundary") or "").strip()
        if boundary:
            parts.extend([f"> **适用范围：**{boundary}", ""])
    elif vtype == "metric_bars":
        primary_label = str(data.get("primary_label") or "方案 A").strip()
        baseline_label = str(data.get("baseline_label") or "方案 B").strip()
        for group in (data.get("groups") or []):
            if not isinstance(group, dict):
                continue
            label = str(group.get("label") or "比较指标").strip()
            question = str(group.get("question") or "").strip()
            metric = str(group.get("metric") or "").strip()
            parts.extend([f"### {label}", ""])
            if question:
                parts.extend([question, ""])
            if metric:
                parts.extend([f"指标：{metric}", ""])
            parts.append(f"| 模型 | {primary_label} | {baseline_label} | 比较结果 |")
            parts.append("|---|---:|---:|---:|")
            for row in (group.get("rows") or []):
                if not isinstance(row, dict):
                    continue
                parts.append(
                    f"| {row.get('label') or ''} | {row.get('primary_display') or row.get('primary_value') or ''} "
                    f"| {row.get('baseline_display') or row.get('baseline_value') or ''} | {row.get('ratio') or ''} |"
                )
            parts.append("")
        normalization_note = str(data.get("normalization_note") or "").strip()
        boundary = str(data.get("boundary") or "").strip()
        if normalization_note:
            parts.extend([f"*{normalization_note}*", ""])
        if boundary:
            parts.extend([f"> **怎么读：**{boundary}", ""])
    elif vtype == "rank_bars":
        for group in (data.get("groups") or []):
            if not isinstance(group, dict):
                continue
            label = str(group.get("label") or "数值排名").strip()
            question = str(group.get("question") or "").strip()
            parts.extend([f"### {label}", ""])
            if question:
                parts.extend([question, ""])
            parts.extend(["| 对象 | 数值 |", "|---|---:|"])
            for row in (group.get("rows") or []):
                if not isinstance(row, dict):
                    continue
                display = row.get("display")
                if display in (None, ""):
                    display = f"{row.get('value', '')}{group.get('unit') or ''}"
                parts.append(f"| {row.get('label') or ''} | {display} |")
            parts.append("")
        caption = str(data.get("caption") or "").strip()
        boundary = str(data.get("boundary") or "").strip()
        if caption:
            parts.extend([f"*{caption}*", ""])
        if boundary:
            parts.extend([f"> **怎么读：**{boundary}", ""])
    elif vtype == "funnel_flow":
        entry_label = str(data.get("entry_label") or "进入流程的全部对象").strip()
        parts.extend([f"**入口：{entry_label}**", ""])
        for index, step in enumerate(data.get("steps") or [], 1):
            if not isinstance(step, dict):
                continue
            label = str(step.get("label") or step.get("title") or f"第 {index} 关").strip()
            description = str(step.get("description") or step.get("text") or "").strip()
            parts.append(f"{index}. **{label}**" + (f"：{description}" if description else ""))
            exit_label = str(step.get("exit_label") or "").strip()
            if exit_label:
                parts.append(f"   - 这一关会拿掉：{exit_label}")
        parts.append("")
        caption = str(data.get("caption") or "").strip()
        if caption:
            parts.extend([f"> **怎么读：**{caption}", ""])
    elif vtype == "flow":
        for i, step in enumerate(data.get("steps") or [], 1):
            if isinstance(step, dict):
                step_title = str(step.get("title") or step.get("label") or "").strip()
                step_description = str(step.get("description") or step.get("text") or "").strip()
                if step_title and step_description:
                    parts.append(f"{i}. **{step_title}**：{step_description}")
                else:
                    parts.append(f"{i}. {step_title or step_description}")
                if step.get("result"):
                    parts.append(f"   - 结果：{step.get('result')}")
            else:
                parts.append(f"{i}. {step}")
        parts.append("")
        caption = str(data.get("caption") or "").strip()
        if caption:
            parts.extend([f"> **怎么读：**{caption}", ""])
    elif vtype == "strategy_tabs":
        instruction = str(data.get("instruction") or "").strip()
        if instruction:
            parts.extend([instruction, ""])
        for index, strategy in enumerate(data.get("strategies") or [], 1):
            if not isinstance(strategy, dict):
                continue
            parts.extend([f"### {index:02d}｜{strategy.get('label') or f'方案 {index}'}", ""])
            parts.append(f"- **作用对象**：{strategy.get('target') or ''}")
            parts.append(f"- **怎样起作用**：{strategy.get('mechanism') or ''}")
            parts.append(f"- **预期变化**：{strategy.get('expected_effect') or ''}")
            parts.extend([f"- **落地还缺什么**：{strategy.get('open_questions') or ''}", ""])
        boundary = str(data.get("boundary") or data.get("caption") or "").strip()
        if boundary:
            parts.extend([f"> **阅读边界：**{boundary}", ""])
    elif vtype == "layer_stack":
        for index, layer in enumerate(data.get("layers") or [], 1):
            if not isinstance(layer, dict):
                continue
            label = str(layer.get("label") or f"第 {index} 层").strip()
            layer_title = str(layer.get("title") or "").strip()
            description = str(layer.get("description") or "").strip()
            parts.append(f"{index}. **{label}｜{layer_title}**")
            if description:
                parts.append(f"   {description}")
            for item in layer.get("items") or []:
                if str(item).strip():
                    parts.append(f"   - {str(item).strip()}")
        parts.append("")
        caption = str(data.get("caption") or "").strip()
        if caption:
            parts.extend([f"> **怎么读：**{caption}", ""])
    elif vtype == "stat":
        unit = data.get("unit") or ""
        for item in data.get("items") or []:
            parts.append(f"- **{item.get('value', '')}{unit}** — {item.get('label', '')}")
        parts.append("")
    elif vtype == "timeline":
        for event in data.get("events") or []:
            title = event.get("title") or event.get("event") or ""
            description = str(event.get("description") or "").strip()
            parts.append(f"- **{event.get('time', '')}** — {title}")
            if description:
                parts.append(f"  - {description}")
        parts.append("")
        caption = str(data.get("caption") or "").strip()
        if caption:
            parts.extend([f"> **怎么读：**{caption}", ""])
    elif vtype == "interactive_compare":
        instruction = str(data.get("instruction") or "").strip()
        prompt = str(data.get("prompt") or "").strip()
        options = [x for x in (data.get("options") or []) if isinstance(x, dict)]
        modes = [x for x in (data.get("modes") or []) if isinstance(x, dict)]
        if instruction:
            parts.extend([instruction, ""])
        if prompt:
            parts.extend([f"> `{prompt}`", ""])
        option_labels = [str(x.get("label") or "").strip() for x in options]
        for mode in modes:
            label = str(mode.get("label") or "比较模式").strip()
            selected_index = mode.get("selected_index")
            selected = ""
            if isinstance(selected_index, int) and not isinstance(selected_index, bool):
                if 0 <= selected_index < len(option_labels):
                    selected = option_labels[selected_index]
            signal = str(mode.get("signal") or "").strip()
            note = str(mode.get("note") or "").strip()
            result = f"选择 {selected}" if selected else "展示对应结果"
            suffix = "；".join(x for x in (signal, note) if x)
            parts.append(f"- **{label}**：{result}{'；' + suffix if suffix else ''}")
        takeaway = str(data.get("takeaway") or "").strip()
        caption = str(data.get("caption") or "机制示意，不代表真实概率、模型输出或检测结果。").strip()
        if takeaway:
            parts.extend(["", takeaway])
        parts.extend(["", f"*{caption}*", ""])
    elif vtype == "scenario_calculator":
        instruction = str(data.get("instruction") or "").strip()
        tabs = [x for x in (data.get("tabs") or []) if isinstance(x, dict)]
        slider = data.get("slider") if isinstance(data.get("slider"), dict) else {}
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        if instruction:
            parts.extend([instruction, ""])
        for tab in tabs:
            parts.append(f"- **{tab.get('label') or '对象'}**")
            for metric in (tab.get("metrics") or []):
                if isinstance(metric, dict):
                    note = str(metric.get("note") or "").strip()
                    parts.append(
                        f"  - {metric.get('label') or '指标'}：{metric.get('value') or ''}"
                        f"{'（' + note + '）' if note else ''}"
                    )
        slider_label = str(slider.get("label") or "可调假设").strip()
        slider_value = slider.get("value", "")
        prefix = str(slider.get("prefix") or "")
        suffix = str(slider.get("suffix") or "")
        parts.extend(["", f"- **默认{slider_label}**：{prefix}{slider_value}{suffix}"])
        try:
            scenario_result = float(result.get("base")) - float(slider_value)
            decimals = result.get("decimals", 2)
            if not isinstance(decimals, int) or isinstance(decimals, bool):
                decimals = 2
            decimals = min(max(decimals, 0), 4)
            result_text = f"{str(result.get('prefix') or '')}{scenario_result:.{decimals}f}"
        except (TypeError, ValueError):
            result_text = "按公式计算"
        parts.append(f"- **{result.get('label') or '默认情景结果'}**：{result_text}")
        formula_note = str(data.get("formula_note") or "").strip()
        caption = str(data.get("caption") or "交互中的可调数值是情景假设，不是来源数据。").strip()
        if formula_note:
            parts.extend(["", formula_note])
        parts.extend(["", f"*{caption}*", ""])
    elif vtype == "capacity_curve":
        question = str(data.get("question") or data.get("reader_question") or "变量增强时，结果如何变化？").strip()
        states = [x for x in (data.get("states") or []) if isinstance(x, dict)]
        caption = str(data.get("caption") or "定性关系示意；具体转折点会随条件变化，不是通用预测器。").strip()
        if question:
            parts.extend([question, ""])
        for index, state in enumerate(states, 1):
            parts.append(
                f"{index}. **{state.get('label') or '阶段'}**：{state.get('result') or ''}"
            )
        parts.extend(["", f"*{caption}*", ""])
    elif vtype == "cost_ledger":
        question = str(data.get("question") or data.get("reader_question") or "哪些成本被计入时，结论会改变？").strip()
        cost_labels = [str(x).strip() for x in (data.get("cost_labels") or []) if str(x).strip()]
        scenarios = [x for x in (data.get("scenarios") or []) if isinstance(x, dict)]
        boundary = str(data.get("boundary") or "不同成本口径不能直接混为同一个结论。").strip()
        if question:
            parts.extend([question, ""])
        for scenario in scenarios:
            included = {str(x).strip() for x in (scenario.get("included") or [])}
            ledger = "；".join(f"{label}：{'计入' if label in included else '不计入'}" for label in cost_labels)
            parts.append(f"- **{scenario.get('label') or '成本情景'}**：{scenario.get('verdict') or ''}")
            if ledger:
                parts.append(f"  - {ledger}")
            if scenario.get("explanation"):
                parts.append(f"  - {scenario.get('explanation')}")
        parts.extend(["", f"> **口径说明：**{boundary}", ""])


def _append_source_media_md(parts: list[str], item: dict) -> None:
    """输出已登记的来源媒体，保持与 HTML 相同的发布边界。"""
    if item.get("registered") is not True:
        return
    media_type = str(item.get("type") or "").strip().lower()
    url = str(item.get("url") or "").strip()
    if media_type not in {"image", "video"} or not url:
        return
    caption = str(item.get("caption") or "原始素材").strip()
    reader_note = str(item.get("reader_note") or "").strip()
    if media_type == "image":
        parts.append(f"![{caption}]({url})")
        parts.append(f"*{caption}*")
    else:
        parts.append(f"[观看视频：{caption}]({url})")
    if reader_note:
        label = "观看重点" if media_type == "video" else "读图提示"
        parts.append(f"> **{label}：**{reader_note}")
    parts.append("")


def _append_number_story_md(parts: list[str], item: dict) -> None:
    if item.get("suppress_visual") is True or item.get("display_mode") == "audit_only":
        return
    title = str(item.get("title") or "这个数字意味着什么").strip()
    value = str(item.get("value") or "").strip()
    unit = str(item.get("unit") or "").strip()
    mode = "关键数字" if item.get("display_mode") == "stat" and item.get("complete") is True else "数字说明"
    parts.append(f"> <small>{mode}</small> **{title}**")
    if value:
        parts.append(f"> **{value}{unit}**")
    custom_labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
    baseline = str(item.get("baseline") or "").strip()
    change = str(item.get("change") or "").strip()
    empty_comparison_values = {
        "", "未知", "未提供", "无", "不适用", "无明确对照", "无可计算变化", "无法计算",
    }
    compact = (
        str(item.get("display_variant") or "").strip().lower() == "compact"
        or (baseline in empty_comparison_values and change in empty_comparison_values)
    )
    labels = (
        (custom_labels.get("denominator") or "统计对象", "denominator"),
        (custom_labels.get("scope") or "适用场景", "scope"),
        (custom_labels.get("period") or "统计时间", "period"),
        (custom_labels.get("baseline") or "对照情况", "baseline"),
        (custom_labels.get("change") or "结果变化", "change"),
        (custom_labels.get("boundary") or "这个数字不能说明什么", "boundary"),
    )
    if compact:
        display_note = str(item.get("display_note") or "").strip()
        if display_note:
            parts.append(f"> {display_note}")
            labels = (labels[5],)
        else:
            labels = (labels[0], labels[2], labels[5])
    for label, key in labels:
        if item.get(key):
            parts.append(f"> {label}：{item[key]}")
    if item.get("source_url"):
        parts.append(f"> [数字来源]({item['source_url']})")
    parts.append("")


def _append_listening_card_md(parts: list[str], card: dict) -> None:
    tracks = [
        track for track in (card.get("tracks") or [])
        if isinstance(track, dict) and track.get("registered") is True and track.get("url")
    ]
    if not tracks:
        return
    parts.extend([f"### 试听｜{card.get('title') or '听一听模型真正做出了什么'}", ""])
    if card.get("intro"):
        parts.extend([str(card.get("intro")), ""])
    for track in tracks:
        label = str(track.get("label") or "官方样曲").strip()
        parts.extend([f"#### {label}", "", f"[播放官方样曲]({track.get('url')})", ""])
        if track.get("prompt"):
            parts.extend([f"> **生成提示词**：{track.get('prompt')}", ""])
        points = [str(point).strip() for point in (track.get("listening_points") or []) if str(point).strip()]
        if points:
            parts.extend(["**重点听什么**", ""])
            parts.extend(f"- {point}" for point in points)
            parts.append("")
        if track.get("lyrics_excerpt"):
            parts.extend(["<details>", "<summary>歌词摘录</summary>", "", str(track.get("lyrics_excerpt")), "", "</details>", ""])
    if card.get("boundary"):
        parts.extend([f"*边界：{card.get('boundary')}*", ""])


def _append_evidence_gallery_md(parts: list[str], items: list[dict]) -> None:
    valid = [item for item in items if isinstance(item, dict) and item.get("registered") is True and item.get("url")]
    if not valid:
        return
    parts.append("<details>")
    parts.append(f"<summary><strong>原始证据图库 ({len(valid)})</strong></summary>")
    parts.append("")
    for item in valid:
        caption = item.get("caption") or item.get("section_title") or "原始证据"
        url = item.get("url") or ""
        if item.get("type") == "image" or item.get("poster_url"):
            preview = item.get("poster_url") or url
            parts.append(f"![{caption}]({preview})")
        parts.append(f"**{caption}** · [查看原始文件]({url})")
        if item.get("source_url"):
            parts.append(f" · [来源页面]({item['source_url']})")
        if item.get("source_label"):
            parts.append(f"  \n图内来源：{item['source_label']}")
        parts.append("")
    parts.append("</details>")
    parts.append("")


def _append_ai_illustration_md(parts: list[str], item: dict) -> None:
    if item.get("status") != "generated":
        return
    path = str(item.get("image_path") or "").strip()
    if not path:
        return
    title = str(item.get("title") or "AI 概念示意").strip()
    alt = str(item.get("alt") or title).strip()
    caption = str(item.get("caption") or "").strip()
    parts.append(f"![{alt}]({path})")
    parts.append(f"*AI 概念示意 · {caption or title + '；用于辅助理解，不是原始证据。'}*")
    parts.append("")


def render_md(article: Article, distilled: dict, related: list | None = None) -> str:
    d_title = distilled.get("distilled_title") or article.title or "AI 蒸馏解读"
    category_tags = distilled.get("category_tags") or []
    sections = distilled.get("sections") or []
    recommendation_reason = distilled.get("recommendation_reason") or ""
    quick_scan = distilled.get("quick_scan") or []
    key_points = distilled.get("key_points") or []
    fact_check = distilled.get("fact_check") or []
    action_card = distilled.get("action_card") or {}
    takeaway_list = distilled.get("takeaway_list") or []
    visuals = distilled.get("visuals") or []
    experiments = distilled.get("experiment_ledger") or []
    case_stories = distilled.get("case_stories") or []
    source_media = distilled.get("source_media") or []
    number_stories = distilled.get("number_stories") or []
    listening_cards = distilled.get("listening_cards") or []
    evidence_gallery = distilled.get("evidence_gallery") or []
    illustrations = distilled.get("illustration_plan") or []
    further_reading = distilled.get("further_reading") or []
    site_note = distilled.get("site_note") or ""
    one_liner = distilled.get("one_liner") or ""
    background = distilled.get("background") or ""

    # 向后兼容
    if not sections and key_points:
        sections = [
            {"tag": "", "title": p.get("title", ""), "content": p.get("insight", ""),
             "archive_original": [{"original": "", "translation": p.get("evidence", "")}]}
            for p in key_points
        ]
    section_experiments, leftover_experiments = _assign_by_section_id(sections, experiments)
    section_cases, leftover_cases = _assign_by_section_id(sections, case_stories)
    section_visuals, leftover_visuals = _assign_by_section_id(sections, visuals)
    section_media, _leftover_media = _assign_by_section_id(
        sections,
        [item for item in source_media if isinstance(item, dict) and item.get("registered") is True],
    )
    section_illustrations, _leftover_illustrations = _assign_by_section_id(
        sections,
        [item for item in illustrations if isinstance(item, dict) and item.get("status") == "generated"],
    )
    section_numbers, leftover_numbers = _assign_by_section_id(sections, number_stories)
    section_listening, leftover_listening = _assign_by_section_id(
        sections,
        [item for item in listening_cards if isinstance(item, dict) and item.get("registered") is True],
    )

    slug = _slugify(d_title)
    category_str = ", ".join(f'"{t}"' for t in category_tags) if category_tags else '"AI"'
    parts = []

    # ── YAML Frontmatter ──
    parts.append("---")
    parts.append(f'title: "{d_title}"')
    parts.append(f'slug: "{slug}"')
    parts.append(f"date: {article.date or ''}")
    parts.append(f"category: [{category_str}]")
    parts.append(f'source: "{article.title or ""}"')
    parts.append(f'source_url: "{article.url or ""}"')
    parts.append(f'url: "{article.url or ""}"')
    parts.append("lang: zh")
    parts.append("---")
    parts.append("")

    # ── 标题 ──
    parts.append(f"# {d_title}")
    parts.append("")

    if one_liner:
        parts.append(f"> {one_liner}")
        parts.append("")

    # ── 推荐理由 ──
    if recommendation_reason:
        parts.append(f"> **推荐理由**：{recommendation_reason}")
        parts.append("")

    # ── 一分钟速览 ──
    quick_points = [str(item).strip() for item in quick_scan if str(item).strip()][:3]
    if quick_points:
        parts.extend(["## 一分钟速览", ""])
        parts.extend(f"- {item}" for item in quick_points)
        parts.append("")

    # ── 目录 ──
    if sections:
        toc_lines = []
        for i, sec in enumerate(sections):
            heading_text = _section_display_title(sec)
            anchor = _slugify(heading_text)
            toc_lines.append(f"{i+1}. [{heading_text}](#{anchor})")
        if toc_lines:
            parts.append("## 目录")
            parts.append("")
            parts.extend(toc_lines)
            parts.append("")

    # ── 正文（段落直接流，比方/概念/原文融进去）──
    if sections:
        for section_index, sec in enumerate(sections):
            title = _section_display_title(sec)
            content = sec.get("content") or ""

            parts.append(f"## {title}")
            parts.append("")

            if content:
                parts.append(content)
                parts.append("")

            # 比方 → 带用途小标签的引用块
            for analogy in sec.get("analogies") or []:
                concept = analogy.get("concept") or ""
                analogy_text = analogy.get("analogy") or ""
                parts.append(f"> <small>类比</small> **{concept}**")
                parts.append(f"> {analogy_text}")
                parts.append("")

            # 概念解释 → 术语、定义和通俗理解分层
            for expl in sec.get("concept_explainers") or []:
                term = expl.get("term") or ""
                definition = expl.get("definition") or ""
                analogy_text = expl.get("analogy") or ""
                parts.append(f"> <small>名词解释</small> **{term}**")
                parts.append(f"> {definition}")
                if analogy_text:
                    parts.append(f"> <small>通俗理解</small> {analogy_text}")
                parts.append("")

            # 原文引文仅在措辞不可替代时出现，并明确原句与释义。
            for arch in sec.get("archive_original") or []:
                original = arch.get("original") or ""
                translation = arch.get("translation") or ""
                if original or translation:
                    parts.append("> <small>原文引文</small>")
                    if original:
                        parts.append(f"> <small>英文原句</small> {original}")
                    if translation:
                        parts.append(f"> <small>中文释义</small> {translation}")
                    parts.append("")

            for item in section_media[section_index]:
                _append_source_media_md(parts, item)
            for item in section_illustrations[section_index]:
                _append_ai_illustration_md(parts, item)
            for item in section_numbers[section_index]:
                _append_number_story_md(parts, item)
            for card in section_listening[section_index]:
                _append_listening_card_md(parts, card)

            for story in section_cases[section_index]:
                _append_case_story_md(parts, story)
            for experiment in section_experiments[section_index]:
                _append_experiment_md(parts, experiment)
            for visual in section_visuals[section_index]:
                _append_visual_md(parts, visual)

            transition_hook = str(sec.get("transition_hook") or "").strip()
            if transition_hook:
                parts.append(f"**{transition_hook}**")
                parts.append("")

    # 兼容旧数据：未锚定的组件只在文末渲染一次。
    for visual in leftover_visuals:
        _append_visual_md(parts, visual)

    for story in leftover_cases:
        _append_case_story_md(parts, story)
    for experiment in leftover_experiments:
        _append_experiment_md(parts, experiment)
    for story in leftover_numbers:
        _append_number_story_md(parts, story)
    for card in leftover_listening:
        _append_listening_card_md(parts, card)

    # ── 背景补充（向后兼容）──
    if background and not any(s.get("content") == background for s in sections):
        parts.append("## 背景补充")
        parts.append("")
        parts.append(background)
        parts.append("")

    # ── 上手卡 ──
    if action_card and (action_card.get("items") or action_card.get("code_block")):
        items = action_card.get("items") or []
        code_block = action_card.get("code_block") or ""
        parts.append("## 判断清单")
        parts.append("")
        if items:
            for item in items:
                parts.append(f"- {item}")
            parts.append("")
        if code_block:
            parts.append("```")
            parts.append(code_block)
            parts.append("```")
            parts.append("")

    # ── 带走清单 ──
    if takeaway_list:
        parts.append("## 带走清单")
        parts.append("")
        for item in takeaway_list:
            clean = item.replace("✅", "").strip()
            parts.append(f"- [ ] {clean}")
        parts.append("")

    _append_evidence_gallery_md(parts, evidence_gallery)

    # ── 资料与边界：发布页只保留来源、延伸和本站说明 ──
    if article.url or further_reading or site_note:
        parts.append("---")
        parts.append("")
        parts.append("**资料与边界**")
        parts.append("")
        if article.url:
            parts.append("**来源**")
            parts.append("")
            source_title = article.title or article.author or "主材料"
            source_meta = [value for value in (article.author, article.date) if value]
            source_line = f"[{source_title}]({article.url})"
            if source_meta:
                source_line += " · " + " · ".join(source_meta)
            parts.append(source_line)
        valid_further = []
        seen_further_urls = {article.url} if article.url else set()
        for item in further_reading:
            if not isinstance(item, dict) or not item.get("url") or item["url"] in seen_further_urls:
                continue
            seen_further_urls.add(item["url"])
            valid_further.append(item)
        for check in fact_check:
            if not isinstance(check, dict):
                continue
            for evidence in check.get("evidence") or []:
                if not isinstance(evidence, dict):
                    continue
                url = evidence.get("url") or ""
                if (
                    not url
                    or url in seen_further_urls
                    or evidence.get("registered") is not True
                    or evidence.get("fetched") is not True
                    or evidence.get("source_type") == "original"
                ):
                    continue
                seen_further_urls.add(url)
                valid_further.append({
                    "title": evidence.get("publisher") or evidence.get("title") or "延伸材料",
                    "url": url,
                })
        if valid_further:
            parts.append("")
            parts.append("**延伸**")
            parts.append("")
            for item in valid_further[:5]:
                parts.append(f"- [{item.get('title') or '延伸阅读'}]({item['url']})")
        if site_note:
            parts.append("")
            parts.append("**本站说明**")
            parts.append("")
            parts.append(site_note)
        parts.append("")

    return "\n".join(parts)
