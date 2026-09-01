"""文章完整性与连贯性质量门禁。

LLM 负责语义审校，本模块负责可重复验证的结构不变量：空内容、重复段落、
输出模式缺失，以及研究账本中高优先级主张是否被覆盖或明确舍弃。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Iterable

from language_quality import analyze_reader_voice, find_language_issues


OUTPUT_MODES = {"full", "onepager", "cards"}
PLACEHOLDER_VALUES = {"内容", "正文", "待补充", "暂无", "省略", "todo", "tbd", "...", "…"}
UNKNOWN_NUMBER_VALUES = {"未知", "不详", "未提供", "材料未提供", "无明确对照", "unknown", "n/a", "na"}
META_NARRATION_RE = re.compile(
    r"(?:本文|原文|原博客|这篇文章|当前材料|本次材料|发布稿)(?:真正|反复|重点|还|又|只|足以|没有|未|把|要|将|的主线|说|称|提到|指出|显示|补充|提供|陈述|说明)?",
    flags=re.UNICODE,
)

SEMANTIC_ALIAS_PATTERNS = (
    (re.compile(r"(?:不会|不再|无需|不需要|没有)(?:额外)?(?:消耗|新增|增加|使用)"), "不增加"),
    (re.compile(r"(?:不会|不再|没有)(?:记录|包含|携带|保存)"), "不编码"),
    (re.compile(r"(?:个人|使用者|账户|账号|身份识别)信息"), "用户身份"),
    (re.compile(r"(?:几乎|基本)(?:没有|无)(?:明显)?影响|影响(?:很小|极小|不明显)"), "影响可忽略"),
    (re.compile(r"(?:没有|未)(?:观察到|发现)(?:统计)?显著(?:的)?(?:质量)?(?:下降|差异)"), "没有显著差异"),
    (re.compile(r"(?:不能|无法)(?:据此)?(?:证明|确认|判定)"), "不能确定"),
    (re.compile(r"(?:会|可以|能够)?(?:携带|形成|产生|留下)(?:新)?水印"), "会留下水印"),
    (re.compile(r"原文(?:称|表示|将|认为|提到|指出|说明)"), ""),
    (re.compile(r"发布方(?:称|表示|认为|提到|指出|说明)"), ""),
    (re.compile(r"solve\s*rate", flags=re.IGNORECASE), "成功率"),
    (re.compile(r"达到峰值"), "峰值"),
    (re.compile(r"用户(?:智能体|\s*agent\b)", flags=re.IGNORECASE), "useragent"),
    (re.compile(r"助手(?:智能体|\s*agent\b)", flags=re.IGNORECASE), "assistantagent"),
    (re.compile(r"(?:表示为|成为)"), "成为"),
    (re.compile(r"描述为"), ""),
    (re.compile(r"逐轮(?:进行|推进)"), "逐轮"),
)
SEMANTIC_GENERIC_NGRAMS = {
    "这个", "一种", "已经", "可以", "可能", "进行", "通过", "结果", "系统",
    "模型", "方法", "内容", "相关", "表示", "说明", "声称", "影响", "使用",
    "当前", "其中", "以及", "同时", "公开", "内部", "实际", "不同", "文本",
}
SEMANTIC_COMMON_LATIN = {
    "and", "are", "for", "from", "has", "have", "into", "not", "that", "the",
    "this", "through", "to", "with", "without",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _normalized_text(value: Any) -> str:
    text = _text(value).lower()
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def _char_count(*values: Any) -> int:
    return len(re.sub(r"\s+", "", "".join(_text(value) for value in values)))


def _is_placeholder(value: Any) -> bool:
    text = _text(value).lower()
    return text in PLACEHOLDER_VALUES or any(token in text for token in ("待补充", "稍后补充", "内容省略"))


def _duplicate_pairs(items: list[dict], title_key: str, body_key: str) -> list[dict]:
    duplicates = []
    for left in range(len(items)):
        for right in range(left + 1, len(items)):
            a = _normalized_text(items[left].get(title_key)) + _normalized_text(items[left].get(body_key))
            b = _normalized_text(items[right].get(title_key)) + _normalized_text(items[right].get(body_key))
            if not a or not b:
                continue
            ratio = SequenceMatcher(None, a, b).ratio()
            if ratio >= 0.88:
                duplicates.append({"first": left + 1, "second": right + 1, "similarity": round(ratio, 3)})
    return duplicates


def _claim_ids(items: Iterable[Any]) -> set[str]:
    result = set()
    for item in items:
        if isinstance(item, dict):
            claim_id = _text(item.get("id") or item.get("claim_id"))
        else:
            claim_id = _text(item)
        if claim_id:
            result.add(claim_id)
    return result


def _has_content(value: Any) -> bool:
    if isinstance(value, list):
        return any(_text(item) for item in value)
    return bool(_text(value))


def _known_number_context(value: Any) -> bool:
    text = _text(value)
    return bool(text) and text.casefold() not in UNKNOWN_NUMBER_VALUES


def _valid_experiment(item: dict) -> bool:
    required = ("id", "after_section_id", "question", "setup", "metric", "result", "limitations")
    return all(_has_content(item.get(key)) for key in required) and bool(_claim_ids(_list(item.get("claim_ids"))))


def _valid_case_story(item: dict) -> bool:
    beats = [
        beat for beat in _list(item.get("beats"))
        if isinstance(beat, dict) and _text(beat.get("label")) and _text(beat.get("text"))
    ]
    source_mode = _text(item.get("source_mode")).lower()
    return (
        all(_has_content(item.get(key)) for key in ("id", "after_section_id", "title", "setup", "outcome", "boundary"))
        and source_mode in {"reconstruction", "quoted"}
        and len(beats) >= 3
        and bool(_claim_ids(_list(item.get("claim_ids"))))
    )


def _valid_interactive_compare(item: dict) -> bool:
    if _text(item.get("type")).lower() != "interactive_compare":
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    options = [x for x in _list(data.get("options")) if isinstance(x, dict) and _text(x.get("label"))]
    modes = [x for x in _list(data.get("modes")) if isinstance(x, dict) and _text(x.get("label"))]
    if len(options) < 2 or len(modes) < 2 or not _text(data.get("caption")):
        return False
    for mode in modes:
        selected_index = mode.get("selected_index")
        if (
            not isinstance(selected_index, int)
            or isinstance(selected_index, bool)
            or not 0 <= selected_index < len(options)
        ):
            return False
    return True


def _valid_strategy_tabs(item: dict) -> bool:
    if _text(item.get("type")).lower() != "strategy_tabs":
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    strategies = [x for x in _list(data.get("strategies")) if isinstance(x, dict)]
    if not 2 <= len(strategies) <= 6 or not _text(data.get("boundary") or data.get("caption")):
        return False
    for strategy in strategies:
        if not all(_text(strategy.get(key)) for key in (
            "label", "target", "mechanism", "expected_effect", "open_questions"
        )):
            return False
        if _text(strategy.get("tone")).lower() not in {
            "primary", "baseline", "warning", "danger", "neutral"
        }:
            return False
    return True


def _valid_scenario_calculator(item: dict) -> bool:
    if _text(item.get("type")).lower() != "scenario_calculator":
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    tabs = [x for x in _list(data.get("tabs")) if isinstance(x, dict) and _text(x.get("label"))]
    slider = data.get("slider") if isinstance(data.get("slider"), dict) else {}
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    source_asset_ids = _claim_ids(_list(data.get("source_asset_ids")))
    if len(tabs) < 2 or not source_asset_ids or not _text(data.get("caption")):
        return False
    if any(not [m for m in _list(tab.get("metrics")) if isinstance(m, dict) and _text(m.get("label")) and _has_content(m.get("value"))] for tab in tabs):
        return False
    try:
        minimum = float(slider.get("min"))
        maximum = float(slider.get("max"))
        step = float(slider.get("step"))
        value = float(slider.get("value"))
        float(result.get("base"))
    except (TypeError, ValueError):
        return False
    return maximum > minimum and step > 0 and minimum <= value <= maximum and bool(_text(result.get("label")))


def _valid_capacity_curve(item: dict) -> bool:
    if _text(item.get("type")).lower() != "capacity_curve":
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    states = [x for x in _list(data.get("states")) if isinstance(x, dict)]
    caption = _text(data.get("caption"))
    if (
        not 3 <= len(states) <= 5
        or not _text(data.get("axis_label"))
        or not _text(data.get("result_label"))
        or "定性" not in caption
        or not any(word in caption for word in ("不是", "不代表", "随"))
    ):
        return False
    positions = []
    for state in states:
        if not all(_text(state.get(key)) for key in ("label", "result")):
            return False
        if _text(state.get("tone")).lower() not in {"primary", "baseline", "warning", "danger", "neutral"}:
            return False
        try:
            position = float(state.get("position"))
        except (TypeError, ValueError):
            return False
        if not 0 <= position <= 100:
            return False
        positions.append(position)
    return positions == sorted(positions) and len(set(positions)) == len(positions)


def _valid_cost_ledger(item: dict) -> bool:
    if _text(item.get("type")).lower() != "cost_ledger":
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    cost_labels = [_text(x) for x in _list(data.get("cost_labels")) if _text(x)]
    scenarios = [x for x in _list(data.get("scenarios")) if isinstance(x, dict)]
    if not 1 <= len(cost_labels) <= 4 or len(set(cost_labels)) != len(cost_labels):
        return False
    if not 2 <= len(scenarios) <= 6 or not _text(data.get("boundary")):
        return False
    scenario_ids = []
    allowed_costs = set(cost_labels)
    for scenario in scenarios:
        scenario_id = _text(scenario.get("id"))
        if not scenario_id or not all(_text(scenario.get(key)) for key in ("label", "verdict", "explanation")):
            return False
        scenario_ids.append(scenario_id)
        included = {_text(x) for x in _list(scenario.get("included")) if _text(x)}
        if not included.issubset(allowed_costs):
            return False
    return len(set(scenario_ids)) == len(scenario_ids)


def _valid_metric_bars(item: dict) -> bool:
    if _text(item.get("type")).lower() != "metric_bars":
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    groups = [x for x in _list(data.get("groups")) if isinstance(x, dict)]
    if (
        len(groups) < 2
        or not _text(data.get("primary_label"))
        or not _text(data.get("baseline_label"))
        or not _text(data.get("boundary"))
    ):
        return False
    for group in groups:
        if not all(_text(group.get(key)) for key in ("id", "label", "question", "metric")):
            return False
        if _text(group.get("better")).lower() not in {"higher", "lower"}:
            return False
        rows = [x for x in _list(group.get("rows")) if isinstance(x, dict)]
        if len(rows) < 2:
            return False
        for row in rows:
            if not all(_text(row.get(key)) for key in ("label", "primary_display", "baseline_display", "ratio")):
                return False
            try:
                primary_value = float(row.get("primary_value"))
                baseline_value = float(row.get("baseline_value"))
            except (TypeError, ValueError):
                return False
            if primary_value <= 0 or baseline_value <= 0:
                return False
    return True


def _valid_rank_bars(item: dict) -> bool:
    if _text(item.get("type")).lower() != "rank_bars":
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    groups = [x for x in _list(data.get("groups")) if isinstance(x, dict)]
    if not 1 <= len(groups) <= 4 or not _text(data.get("boundary")):
        return False
    for group in groups:
        if not all(_text(group.get(key)) for key in ("id", "label", "question", "unit")):
            return False
        direction = _text(group.get("direction")).lower()
        if direction not in {"positive", "negative"}:
            return False
        if _text(group.get("tone")).lower() not in {"primary", "baseline", "warning", "danger"}:
            return False
        rows = [x for x in _list(group.get("rows")) if isinstance(x, dict)]
        if not 2 <= len(rows) <= 18:
            return False
        magnitudes = []
        for row in rows:
            if not all(_text(row.get(key)) for key in ("label", "display")):
                return False
            try:
                value = float(row.get("value"))
            except (TypeError, ValueError):
                return False
            if (direction == "positive" and value < 0) or (direction == "negative" and value > 0):
                return False
            magnitudes.append(abs(value))
        if not any(value > 0 for value in magnitudes):
            return False
        if any(left < right for left, right in zip(magnitudes, magnitudes[1:])):
            return False
    return True


def _valid_funnel_flow(item: dict) -> bool:
    if _text(item.get("type")).lower() != "funnel_flow":
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    steps = [x for x in _list(data.get("steps")) if isinstance(x, dict)]
    if not 2 <= len(steps) <= 5 or not _text(data.get("entry_label")) or not _text(data.get("caption")):
        return False
    widths = []
    for step in steps:
        if not _text(step.get("label") or step.get("title")) or not _text(step.get("description") or step.get("text")):
            return False
        if step.get("width") not in (None, ""):
            try:
                width = float(step.get("width"))
            except (TypeError, ValueError):
                return False
            if not 48 <= width <= 100:
                return False
            widths.append(width)
    if widths and (len(widths) != len(steps) or any(left <= right for left, right in zip(widths, widths[1:]))):
        return False
    return True


def _valid_delta_table(item: dict) -> bool:
    if _text(item.get("type")).lower() != "delta_table":
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    rows = [x for x in _list(data.get("rows")) if isinstance(x, dict)]
    if (
        not 2 <= len(rows) <= 8
        or not _text(data.get("baseline_label"))
        or not _text(data.get("current_label"))
        or not _text(data.get("boundary"))
    ):
        return False
    allowed_tones = {"primary", "baseline", "warning", "danger", "neutral"}
    for row in rows:
        if not all(_text(row.get(key)) for key in ("label", "baseline", "current", "change", "direction", "tone")):
            return False
        if _text(row.get("direction")).lower() not in {"up", "down", "flat"}:
            return False
        if _text(row.get("tone")).lower() not in allowed_tones:
            return False
    return True


def _valid_status_matrix(item: dict) -> bool:
    if _text(item.get("type")).lower() != "status_matrix":
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    columns = [_text(x) for x in _list(data.get("columns")) if _text(x)]
    rows = [x for x in _list(data.get("rows")) if isinstance(x, dict)]
    if (
        not 2 <= len(columns) <= 6
        or not 2 <= len(rows) <= 8
        or not _text(data.get("caption"))
        or not _text(data.get("boundary"))
    ):
        return False
    allowed_tones = {"primary", "baseline", "warning", "danger", "neutral"}
    for row in rows:
        cells = [x for x in _list(row.get("cells")) if isinstance(x, dict)]
        if not _text(row.get("label")) or len(cells) != len(columns):
            return False
        if any(
            not _text(cell.get("value"))
            or _text(cell.get("tone")).lower() not in allowed_tones
            for cell in cells
        ):
            return False
    return True


def _valid_decision_table(item: dict) -> bool:
    if _text(item.get("type")).lower() != "decision_table":
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    rows = [x for x in _list(data.get("rows")) if isinstance(x, dict)]
    if not 2 <= len(rows) <= 8 or not _text(data.get("boundary")):
        return False
    allowed_tones = {"primary", "baseline", "warning", "danger", "neutral"}
    return all(
        all(_text(row.get(key)) for key in ("condition", "result", "action", "tone"))
        and _text(row.get("tone")).lower() in allowed_tones
        for row in rows
    )


def _valid_flow_visual(item: dict) -> bool:
    if _text(item.get("type")).lower() != "flow":
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    steps = _list(data.get("steps"))
    if len(steps) < 2:
        return False
    presentation = _text(data.get("presentation")).lower()
    if presentation == "stepper":
        if not 3 <= len(steps) <= 7 or not _text(data.get("caption")):
            return False
        return all(
            isinstance(step, dict)
            and _text(step.get("label"))
            and _text(step.get("title"))
            and _text(step.get("description"))
            for step in steps
        )
    if presentation not in {"", "static"}:
        return False
    for step in steps:
        if isinstance(step, dict):
            if not (_has_content(step.get("title") or step.get("label")) or _has_content(step.get("description") or step.get("text"))):
                return False
        elif not _has_content(step):
            return False
    return True


def _valid_timeline_visual(item: dict) -> bool:
    if _text(item.get("type")).lower() != "timeline":
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    presentation = _text(data.get("presentation")).lower()
    events = [x for x in _list(data.get("events")) if isinstance(x, dict)]
    if presentation in {"", "static"}:
        return len(events) >= 2 and all(
            _text(event.get("time")) and _text(event.get("title") or event.get("event"))
            for event in events
        )
    if presentation != "scrubber" or not 3 <= len(events) <= 8 or not _text(data.get("caption")):
        return False
    return all(
        _text(event.get("time"))
        and _text(event.get("title") or event.get("event"))
        and _text(event.get("description"))
        for event in events
    )


def _valid_layer_stack(item: dict) -> bool:
    if _text(item.get("type")).lower() != "layer_stack":
        return True
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    layers = [x for x in _list(data.get("layers")) if isinstance(x, dict)]
    if not 2 <= len(layers) <= 7 or not _text(data.get("caption")):
        return False
    return all(
        _text(layer.get("label"))
        and _text(layer.get("title"))
        and _text(layer.get("description"))
        for layer in layers
    )


def _flatten_visible_text(value: Any) -> list[str]:
    """Flatten text from a known public component after its container is selected."""
    if isinstance(value, dict):
        return [text for item in value.values() for text in _flatten_visible_text(item)]
    if isinstance(value, list):
        return [text for item in value for text in _flatten_visible_text(item)]
    text = _text(value)
    return [text] if text else []


def _walk_public_text(
    value: Any,
    path: tuple[str | int, ...] = (),
) -> Iterable[tuple[tuple[str | int, ...], str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_public_text(child, (*path, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_public_text(child, (*path, index))
    elif isinstance(value, str) and value.strip():
        yield path, value


def _public_path(path: tuple[str | int, ...]) -> str:
    result = "$"
    for item in path:
        result += f"[{item}]" if isinstance(item, int) else f".{item}"
    return result


def _semantic_corpus(distilled: dict, mode: str) -> str:
    """Return publish-facing copy only; audit notes and research ledgers are excluded."""
    selected: list[Any] = [distilled.get("distilled_title")]
    if mode == "full":
        selected.extend((
            distilled.get("quick_scan"),
            distilled.get("sections"),
            distilled.get("experiment_ledger"),
            distilled.get("case_stories"),
            distilled.get("number_stories"),
            distilled.get("listening_cards"),
            distilled.get("visuals"),
            distilled.get("action_card"),
            distilled.get("takeaway_list"),
        ))
    elif mode == "onepager":
        selected.append(distilled.get("one_pager"))
    elif mode == "cards":
        selected.append(distilled.get("card_deck"))
    return "\n".join(text for item in selected for text in _flatten_visible_text(item))


def _semantic_normalize(value: Any) -> str:
    text = _normalize_chinese_percentages(_text(value).lower())
    for pattern, replacement in SEMANTIC_ALIAS_PATTERNS:
        text = pattern.sub(replacement, text)
    return re.sub(r"[^0-9a-z%\u4e00-\u9fff.+-]+", "", text)


_CHINESE_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def _chinese_integer(value: str) -> int | None:
    """Parse the small integers normally used in percentage claims."""
    if not value:
        return None
    if all(char in _CHINESE_DIGITS for char in value):
        return int("".join(str(_CHINESE_DIGITS[char]) for char in value))
    total = 0
    current = 0
    for char in value:
        if char in _CHINESE_DIGITS:
            current = _CHINESE_DIGITS[char]
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char == "百":
            total += (current or 1) * 100
            current = 0
        else:
            return None
    return total + current


def _normalize_chinese_percentages(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        integer = _chinese_integer(match.group(1))
        fraction = match.group(2)
        if integer is None:
            return match.group(0)
        if fraction:
            digits = "".join(str(_CHINESE_DIGITS[char]) for char in fraction)
            return f"{integer}.{digits}%"
        return f"{integer}%"

    return re.sub(
        r"百分之([零〇一二两三四五六七八九十百]+)(?:点([零〇一二三四五六七八九]+))?",
        replace,
        value,
    )


def _function_signatures(value: Any) -> set[str]:
    """Extract complete code-like interfaces so prose around them may be paraphrased."""
    signatures = set()
    for match in re.findall(
        r"[A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*\s*\([^)]*\)\s*[-=]>\s*[A-Za-z][A-Za-z0-9_]*",
        _text(value),
    ):
        signatures.add(re.sub(r"\s+", "", match).lower())
    return signatures


def _version_release_signatures(value: Any) -> set[str]:
    """Pair product identifiers with nearby semantic-version release numbers."""
    signatures = set()
    text = _text(value).lower()
    ignored = SEMANTIC_COMMON_LATIN | {"version", "release", "releases", "today"}
    for match in re.finditer(r"\b\d+\.\d+\.\d+\b", text):
        prefix = text[max(0, match.start() - 96):match.start()]
        identifiers = [
            token
            for token in re.findall(r"[a-z][a-z0-9_.+-]*", prefix)
            if token not in ignored and not token.replace(".", "").isdigit()
        ]
        if identifiers:
            signatures.add(f"{identifiers[-1]}@{match.group(0)}")
    return signatures


def _claim_clauses(value: Any) -> list[str]:
    clauses = [
        _text(item)
        for item in re.split(r"[，；。！？;!?]+", _text(value))
        if len(_semantic_normalize(item)) >= 3
    ]
    return clauses or ([_text(value)] if _text(value) else [])


def _exact_claim_terms(clause: str) -> list[str]:
    normalized_clause = _normalize_chinese_percentages(clause)
    numbers = re.findall(r"\d+(?:[.,]\d+)*(?:%|万|亿|[a-zA-Z]{1,5})?", normalized_clause)
    identifiers = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_.+-]*", clause):
        lowered = token.lower()
        if lowered in SEMANTIC_COMMON_LATIN:
            continue
        if len(token) >= 2 and (token != lowered or any(char.isdigit() for char in token) or lowered in {"ai", "api", "token"}):
            identifiers.append(lowered)
    return list(dict.fromkeys(numbers + identifiers))


def _semantic_ngrams(value: Any) -> list[str]:
    normalized = _semantic_normalize(value)
    grams: list[str] = []
    for run in re.findall(r"[\u4e00-\u9fff]+", normalized):
        width = 3 if len(run) >= 3 else 2
        for index in range(max(0, len(run) - width + 1)):
            gram = run[index:index + width]
            if gram not in SEMANTIC_GENERIC_NGRAMS:
                grams.append(gram)
    return list(dict.fromkeys(grams))


def _audit_claim_against_corpus(claim_id: str, claim_text: str, corpus: str) -> dict:
    normalized_corpus = _semantic_normalize(corpus)
    corpus_signatures = _function_signatures(corpus)
    corpus_version_signatures = _version_release_signatures(corpus)
    clause_reports = []
    all_matched: list[str] = []
    all_missing: list[str] = []
    ratios: list[float] = []

    for clause in _claim_clauses(claim_text):
        exact_terms = _exact_claim_terms(clause)
        missing_exact = [term for term in exact_terms if _semantic_normalize(term) not in normalized_corpus]
        claim_signatures = _function_signatures(clause)
        claim_version_signatures = _version_release_signatures(clause)
        signatures_matched = (
            (bool(claim_signatures) and claim_signatures <= corpus_signatures)
            or (
                bool(claim_version_signatures)
                and claim_version_signatures <= corpus_version_signatures
            )
        )
        grams = _semantic_ngrams(clause)
        matched_grams = [term for term in grams if term in normalized_corpus]
        ratio = len(matched_grams) / len(grams) if grams else (1.0 if exact_terms else 0.0)
        # Short paraphrases may retain only one canonical three-character phrase.
        threshold = 0.33 if len(grams) >= 3 else 0.5
        matched = not missing_exact and (
            signatures_matched
            or ratio >= threshold
            or (not grams and bool(exact_terms))
        )
        matched_terms = exact_terms + matched_grams
        missing_terms = missing_exact + ([term for term in grams if term not in normalized_corpus] if not matched else [])
        clause_reports.append({
            "text": clause,
            "matched": matched,
            "match_ratio": round(ratio, 3),
            "required_exact_terms": exact_terms,
            "matched_signatures": sorted(
                (claim_signatures & corpus_signatures)
                | (claim_version_signatures & corpus_version_signatures)
            ),
            "matched_terms": list(dict.fromkeys(matched_terms))[:12],
            "missing_terms": list(dict.fromkeys(missing_terms))[:12],
        })
        ratios.append(ratio)
        all_matched.extend(matched_terms)
        all_missing.extend(missing_terms)

    matched = bool(clause_reports) and all(item["matched"] for item in clause_reports)
    return {
        "claim_id": claim_id,
        "claim": claim_text,
        "matched": matched,
        "match_ratio": round(sum(ratios) / len(ratios), 3) if ratios else 0.0,
        "matched_terms": list(dict.fromkeys(all_matched))[:20],
        "missing_terms": list(dict.fromkeys(all_missing))[:20],
        "clauses": clause_reports,
    }


def semantic_claim_coverage(
    distilled: dict,
    research: dict,
    required_modes: Iterable[str] = ("full", "onepager", "cards"),
) -> dict:
    """Deterministic lexical-semantic coverage check for high-priority claims.

    This catches material omissions and missing numeric/model anchors. It is not a
    substitute for the LLM editorial review and deliberately avoids audit-only text.
    """
    modes = [mode for mode in required_modes if mode in OUTPUT_MODES]
    claims = [item for item in _list(research.get("claims")) if isinstance(item, dict)]
    omissions = distilled.get("editorial_coverage") if isinstance(distilled.get("editorial_coverage"), dict) else {}
    omitted_ids = _claim_ids([
        item for item in _list(omissions.get("omitted_claims"))
        if isinstance(item, dict) and _text(item.get("reason"))
    ])
    high_claims_all = [
        item for item in claims
        if _text(item.get("id"))
        and _text(item.get("importance")).lower() == "high"
        and _text(item.get("id")) not in omitted_ids
    ]
    uncheckable_ids = [
        _text(item.get("id")) for item in high_claims_all
        if len(_semantic_normalize(item.get("claim") or item.get("text") or item.get("statement"))) < 6
    ]
    high_claims = [item for item in high_claims_all if _text(item.get("id")) not in uncheckable_ids]

    by_mode: dict[str, list[dict]] = {}
    missing_by_mode: dict[str, list[str]] = {}
    for mode in modes:
        corpus = _semantic_corpus(distilled, mode)
        reports = []
        for item in high_claims:
            claim_id = _text(item.get("id"))
            claim_text = _text(item.get("claim") or item.get("text") or item.get("statement"))
            report = _audit_claim_against_corpus(claim_id, claim_text, corpus)
            reports.append(report)
        by_mode[mode] = reports
        missing_by_mode[mode] = [item["claim_id"] for item in reports if not item["matched"]]

    missing_ids = sorted({claim_id for ids in missing_by_mode.values() for claim_id in ids})
    return {
        "checked_high_claim_count": len(high_claims),
        "uncheckable_high_claim_ids": uncheckable_ids,
        "modes": by_mode,
        "missing_by_mode": missing_by_mode,
        "semantically_missing_high_claim_ids": missing_ids,
    }


def audit_distilled(
    distilled: dict,
    research: dict | None = None,
    required_modes: Iterable[str] = ("full", "onepager", "cards"),
    strict_editorial: bool = False,
    semantic_coverage_strict: bool | None = None,
) -> dict:
    """返回确定性质量报告，不修改输入。"""
    modes = {x for x in required_modes if x in OUTPUT_MODES}
    blockers: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}

    if not isinstance(distilled, dict):
        return {
            "publishable": False,
            "score": 0,
            "blockers": ["解读结果顶层不是 JSON 对象"],
            "warnings": [],
            "metrics": {},
        }

    quality_meta = (
        distilled.get("editorial_quality")
        if isinstance(distilled.get("editorial_quality"), dict)
        else {}
    )
    semantic_review_status = _text(quality_meta.get("status")) or "missing"
    semantic_review_completed = semantic_review_status == "completed"
    metrics["semantic_review_status"] = semantic_review_status
    metrics["semantic_review_completed"] = semantic_review_completed
    if not semantic_review_completed:
        warnings.append(
            "未记录已完成的语义级编辑审校；确定性语言规则只能排查高置信问题，不能据此宣称语病检查完整通过"
        )

    research = research if isinstance(research, dict) else {}
    claims = [x for x in _list(research.get("claims")) if isinstance(x, dict)]
    research_claim_ids = {
        _text(x.get("id")) for x in claims if _text(x.get("id"))
    }

    if not _text(distilled.get("distilled_title")):
        blockers.append("缺少 distilled_title")

    base_quick_scan = [_text(x) for x in _list(distilled.get("quick_scan")) if _text(x)]
    base_sections = [x for x in _list(distilled.get("sections")) if isinstance(x, dict)]
    base_usable_sections = [
        x for x in base_sections if _text(x.get("title")) and _text(x.get("content"))
    ]
    narrative = distilled.get("narrative_plan")
    narrative_complete = (
        isinstance(narrative, dict)
        and _text(narrative.get("central_question"))
        and _text(narrative.get("closing_answer"))
    )
    human_narrative_complete = (
        isinstance(narrative, dict)
        and _text(narrative.get("reader_tension"))
        and _text(narrative.get("core_mechanism"))
    )
    human_strategy_fields = (
        "opening_anchor",
        "reader_stake",
        "resonance_basis",
        "stance",
    )
    missing_human_strategy_fields = [
        field for field in human_strategy_fields
        if not isinstance(narrative, dict) or not _text(narrative.get(field))
    ]
    title_contract = narrative.get("title_contract") if isinstance(narrative, dict) else {}
    title_contract = title_contract if isinstance(title_contract, dict) else {}
    title_text_normalized = _normalized_text(distilled.get("distilled_title")).casefold()
    recognition_anchor_normalized = _normalized_text(
        title_contract.get("recognition_anchor")
    ).casefold()
    title_anchor_index = (
        title_text_normalized.find(recognition_anchor_normalized)
        if recognition_anchor_normalized else -1
    )
    title_anchor_in_front_half = bool(
        recognition_anchor_normalized
        and title_anchor_index >= 0
        and title_anchor_index <= max(0, len(title_text_normalized) // 2)
    )
    title_contract_fields = (
        "recognition_anchor",
        "click_reason",
        "reader_promise",
        "evidence_guardrail",
    )
    missing_title_contract_fields = [
        field for field in title_contract_fields if not _text(title_contract.get(field))
    ]
    opening_sequence = narrative.get("opening_sequence") if isinstance(narrative, dict) else {}
    opening_sequence = opening_sequence if isinstance(opening_sequence, dict) else {}
    missing_opening_sequence_fields = [
        field for field in ("scene", "turn", "reveal")
        if not _text(opening_sequence.get(field))
    ]
    chapter_system = narrative.get("chapter_system") if isinstance(narrative, dict) else {}
    chapter_system = chapter_system if isinstance(chapter_system, dict) else {}
    chapter_entries = [
        item for item in _list(chapter_system.get("chapters")) if isinstance(item, dict)
    ]
    section_ids = {_text(item.get("id")) for item in base_usable_sections if _text(item.get("id"))}
    chapter_section_ids = {
        _text(item.get("section_id")) for item in chapter_entries if _text(item.get("section_id"))
    }
    missing_chapter_section_ids = sorted(section_ids - chapter_section_ids)
    unknown_chapter_section_ids = sorted(chapter_section_ids - section_ids)
    incomplete_chapter_indexes = [
        index + 1
        for index, item in enumerate(chapter_entries)
        if not all(_text(item.get(field)) for field in ("section_id", "role", "reader_need", "advance", "evidence"))
    ]
    chapter_system_complete = bool(
        _text(chapter_system.get("archetype"))
        and _text(chapter_system.get("throughline"))
        and chapter_entries
        and not missing_chapter_section_ids
        and not unknown_chapter_section_ids
        and not incomplete_chapter_indexes
    )
    if "full" in modes and not narrative_complete:
        message = "缺少完整 narrative_plan，无法审计开头问题是否在结尾得到回答"
        (blockers if strict_editorial else warnings).append(message)
    if "full" in modes and narrative_complete and not human_narrative_complete:
        message = "narrative_plan 缺少 reader_tension 或 core_mechanism，无法完整审计读者张力与单一主线"
        (blockers if strict_editorial else warnings).append(message)
    if "full" in modes and narrative_complete and missing_human_strategy_fields:
        warnings.append(
            "narrative_plan 缺少人味策划字段，仅能按旧稿兼容："
            + ", ".join(missing_human_strategy_fields)
        )
    if "full" in modes and narrative_complete and missing_title_contract_fields:
        warnings.append(
            "narrative_plan.title_contract 不完整，仅能按旧稿兼容："
            + ", ".join(missing_title_contract_fields)
        )
    if "full" in modes and narrative_complete and missing_opening_sequence_fields:
        warnings.append(
            "narrative_plan.opening_sequence 不完整，仅能按旧稿兼容："
            + ", ".join(missing_opening_sequence_fields)
        )
    if "full" in modes and narrative_complete and not chapter_system_complete:
        details = []
        if not _text(chapter_system.get("archetype")):
            details.append("缺 archetype")
        if not _text(chapter_system.get("throughline")):
            details.append("缺 throughline")
        if missing_chapter_section_ids:
            details.append(f"漏章节 {missing_chapter_section_ids}")
        if unknown_chapter_section_ids:
            details.append(f"未知章节 {unknown_chapter_section_ids}")
        if incomplete_chapter_indexes:
            details.append(f"不完整计划 {incomplete_chapter_indexes}")
        if not chapter_entries:
            details.append("缺 chapters")
        warnings.append("narrative_plan.chapter_system 不完整，仅能按旧稿兼容：" + "；".join(details))

    if "full" in modes:
        quick_scan = base_quick_scan
        category_tags = [
            _text(item) for item in _list(distilled.get("category_tags")) if _text(item)
        ]
        duplicate_category_tags = sorted({
            tag for tag in category_tags if category_tags.count(tag) > 1
        })
        long_category_tag_indexes = [
            index + 1
            for index, tag in enumerate(category_tags)
            if len(tag) > (12 if all(ord(char) < 128 for char in tag) else 8)
        ]
        sections = base_sections
        usable_sections = base_usable_sections
        empty_sections = [i + 1 for i, x in enumerate(sections) if not _text(x.get("title")) or not _text(x.get("content"))]
        duplicates = _duplicate_pairs(usable_sections, "title", "content")
        placeholder_sections = [
            i + 1 for i, x in enumerate(sections)
            if _is_placeholder(x.get("title")) or _is_placeholder(x.get("content"))
        ]
        thin_sections = [
            i + 1 for i, x in enumerate(usable_sections)
            if len(_normalized_text(x.get("content"))) < 30
        ]
        meta_narration_sections = [
            i + 1 for i, x in enumerate(usable_sections)
            if META_NARRATION_RE.search(_text(x.get("content")))
        ]
        meta_narration_public_paths = []
        for field in (
            "quick_scan", "one_liner", "recommendation_reason", "experiment_ledger",
            "case_stories", "number_stories", "visuals", "action_card", "takeaway_list",
        ):
            for path, value in _walk_public_text(distilled.get(field), (field,)):
                if META_NARRATION_RE.search(value):
                    meta_narration_public_paths.append(_public_path(path))
        original_quote_count = sum(
            1
            for section in sections
            for quote in _list(section.get("archive_original"))
            if isinstance(quote, dict)
            and (_text(quote.get("original")) or _text(quote.get("translation")))
        )
        metrics.update({
            "quick_scan_count": len(quick_scan),
            "quick_scan_char_count": _char_count(*quick_scan),
            "quick_scan_item_char_counts": [_char_count(item) for item in quick_scan],
            "category_tag_count": len(category_tags),
            "duplicate_category_tags": duplicate_category_tags,
            "long_category_tag_indexes": long_category_tag_indexes,
            "section_count": len(usable_sections),
            "empty_section_indexes": empty_sections,
            "duplicate_sections": duplicates,
            "placeholder_section_indexes": placeholder_sections,
            "thin_section_indexes": thin_sections,
            "meta_narration_section_indexes": meta_narration_sections,
            "meta_narration_public_paths": meta_narration_public_paths,
            "original_quote_count": original_quote_count,
            "human_narrative_complete": human_narrative_complete,
            "missing_human_strategy_fields": missing_human_strategy_fields,
            "missing_title_contract_fields": missing_title_contract_fields,
            "title_recognition_anchor": _text(title_contract.get("recognition_anchor")),
            "title_anchor_in_front_half": title_anchor_in_front_half,
            "missing_opening_sequence_fields": missing_opening_sequence_fields,
            "chapter_system_complete": chapter_system_complete,
            "missing_chapter_section_ids": missing_chapter_section_ids,
            "unknown_chapter_section_ids": unknown_chapter_section_ids,
            "incomplete_chapter_indexes": incomplete_chapter_indexes,
        })
        if len(quick_scan) != 3:
            (blockers if strict_editorial else warnings).append(
                f"一分钟导览有 {len(quick_scan)} 条，必须精简为 3 条"
            )
        quick_scan_chars = _char_count(*quick_scan)
        if quick_scan_chars > 180:
            (blockers if strict_editorial else warnings).append(
                f"一分钟导览共 {quick_scan_chars} 字，必须压缩到 180 字以内"
            )
        long_quick_scan = [
            i + 1 for i, item in enumerate(quick_scan) if _char_count(item) > 70
        ]
        if long_quick_scan:
            warnings.append(f"一分钟导览单条超过 70 字：{long_quick_scan}")
        if category_tags and not 3 <= len(category_tags) <= 5:
            (blockers if strict_editorial else warnings).append(
                f"归档标签有 {len(category_tags)} 个，必须保留 3-5 个稳定大类"
            )
        if duplicate_category_tags:
            (blockers if strict_editorial else warnings).append(
                f"归档标签存在重复项：{duplicate_category_tags}"
            )
        if long_category_tag_indexes:
            (blockers if strict_editorial else warnings).append(
                "归档标签必须短平快，中文不超过 8 字、纯英文不超过 12 字符："
                f"{long_category_tag_indexes}"
            )
        if recognition_anchor_normalized and not title_anchor_in_front_half:
            (blockers if strict_editorial else warnings).append(
                "标题未在前半句兑现 title_contract.recognition_anchor："
                f"{_text(title_contract.get('recognition_anchor'))}"
            )
        if len(usable_sections) < 3:
            blockers.append(f"完整正文只有 {len(usable_sections)} 个有效段落，至少需要 3 个")
        if empty_sections:
            blockers.append(f"正文存在标题或内容为空的段落：{empty_sections}")
        if duplicates:
            blockers.append(f"正文存在高度重复段落：{duplicates}")
        if placeholder_sections:
            blockers.append(f"正文存在占位内容：{placeholder_sections}")
        if thin_sections:
            warnings.append(f"正文段落信息量偏低：{thin_sections}")
        if meta_narration_sections:
            (blockers if strict_editorial else warnings).append(
                f"正文存在割裂的研究过程话术，请改为独立文章语气：{meta_narration_sections}"
            )
        if meta_narration_public_paths:
            (blockers if strict_editorial else warnings).append(
                "发布内容存在写作过程自述，请改为直接面向读者的自然表达："
                f"{meta_narration_public_paths}"
            )
        if original_quote_count > 2:
            (blockers if strict_editorial else warnings).append(
                f"原文引文有 {original_quote_count} 条，最多保留 2 条措辞不可替代的引文"
            )
        if narrative_complete:
            section_logic = [_text(x) for x in _list(narrative.get("section_logic")) if _text(x)]
            if len(section_logic) < len(usable_sections):
                warnings.append(
                    f"narrative_plan 只解释了 {len(section_logic)} 段关系，正文有 {len(usable_sections)} 段"
                )

        reader_voice = analyze_reader_voice(distilled)
        metrics["reader_voice"] = reader_voice
        dense_sections = reader_voice["dense_section_indexes"]
        long_sentences = reader_voice["long_sentences"]
        stiff_hits = reader_voice["stiff_phrase_hits"]
        antithesis_count = reader_voice["antithesis_count"]
        proxy_reader_hits = reader_voice["proxy_reader_hits"]
        performative_depth_hits = reader_voice["performative_depth_hits"]
        abstract_action_hits = reader_voice["abstract_action_hits"]
        uniform_rhythm_sections = reader_voice["uniform_rhythm_section_indexes"]
        question_dense_sections = reader_voice["question_dense_section_indexes"]
        if len(dense_sections) >= 2:
            warnings.append(
                f"正文存在连续文字墙，建议按判断、事实、解释或边界自然分段：{dense_sections}"
            )
        if len(long_sentences) >= 3:
            warnings.append(
                f"正文有 {len(long_sentences)} 个超过 72 个汉字的长句，建议在不丢条件的前提下调整节奏"
            )
        if sum(item["count"] for item in stiff_hits) >= 2:
            phrases = list(dict.fromkeys(item["phrase"] for item in stiff_hits))
            warnings.append(f"正文报告套话重复出现，建议改成具体判断：{phrases}")
        if antithesis_count >= 4:
            warnings.append(
                f"全文使用 {antithesis_count} 次转折对举句式，建议改变起句和论证节奏"
            )
        if len(proxy_reader_hits) >= 3:
            warnings.append(
                f"正文有 {len(proxy_reader_hits)} 处替读者预设想法，建议只保留真实异议并先准确复述其合理版本"
            )
        if len(performative_depth_hits) >= 3:
            warnings.append(
                f"正文有 {len(performative_depth_hits)} 处仪式化深刻表达，建议保留核心判断并删除无必要升华"
            )
        if abstract_action_hits:
            warnings.append(
                f"公开标题或卡片有 {len(abstract_action_hits)} 处抽象动作，建议写清谁完成了调查、处理或验证："
                f"{[item['text'] for item in abstract_action_hits]}"
            )
        if len(uniform_rhythm_sections) >= 2:
            warnings.append(
                f"正文多个章节句长过于均匀，建议用自然长短句调整阅读呼吸：{uniform_rhythm_sections}"
            )
        if question_dense_sections:
            warnings.append(
                f"正文部分章节连续抛出三个以上问题，建议先回答再推进：{question_dense_sections}"
            )

    if "onepager" in modes:
        onepager_present = isinstance(distilled.get("one_pager"), dict) and bool(distilled.get("one_pager"))
        onepager = distilled.get("one_pager") if onepager_present else {}
        op_sections = [x for x in _list(onepager.get("key_sections")) if isinstance(x, dict)]
        usable_op = [x for x in op_sections if _text(x.get("subtitle")) and _text(x.get("content"))]
        op_duplicates = _duplicate_pairs(usable_op, "subtitle", "content")
        placeholder_op = [
            i + 1 for i, x in enumerate(op_sections)
            if _is_placeholder(x.get("subtitle")) or _is_placeholder(x.get("content"))
        ]
        onepager_chars = _char_count(
            onepager.get("lead"),
            *[x.get("subtitle") for x in usable_op],
            *[x.get("content") for x in usable_op],
        )
        metrics.update({
            "onepager_section_count": len(usable_op),
            "onepager_char_count": onepager_chars,
            "duplicate_onepager_sections": op_duplicates,
            "placeholder_onepager_sections": placeholder_op,
        })
        legacy_fallback = not strict_editorial and not onepager_present and len(base_usable_sections) >= 3
        if legacy_fallback:
            warnings.append("旧 JSON 缺少 one_pager，将从完整正文兼容合成")
        else:
            if not _text(onepager.get("lead")):
                blockers.append("一页纸缺少 lead")
            if len(usable_op) < 3:
                blockers.append(f"一页纸只有 {len(usable_op)} 个有效小节，至少需要 3 个")
        if len(usable_op) > 5:
            warnings.append(f"一页纸有 {len(usable_op)} 个小节，建议压缩到 3–5 个")
        if onepager_present and onepager_chars < 450:
            (blockers if strict_editorial else warnings).append(
                f"一页纸只有 {onepager_chars} 字，低于有效短稿下限 450 字"
            )
        elif onepager_chars < 500:
            warnings.append(f"一页纸只有 {onepager_chars} 字，建议达到 500–800 字")
        if onepager_chars > 900:
            (blockers if strict_editorial else warnings).append(
                f"一页纸有 {onepager_chars} 字，超过一页纸上限 900 字"
            )
        elif onepager_chars > 800:
            warnings.append(f"一页纸有 {onepager_chars} 字，建议压缩到 500–800 字")
        if op_duplicates:
            blockers.append(f"一页纸存在高度重复小节：{op_duplicates}")
        if placeholder_op:
            blockers.append(f"一页纸存在占位内容：{placeholder_op}")

    if "cards" in modes:
        deck_present = isinstance(distilled.get("card_deck"), dict) and bool(distilled.get("card_deck"))
        deck = distilled.get("card_deck") if deck_present else {}
        cards = [x for x in _list(deck.get("cards")) if isinstance(x, dict)]
        usable_cards = [x for x in cards if _text(x.get("title")) and (_text(x.get("body")) or _list(x.get("nodes")) or _list(x.get("steps")))]
        card_duplicates = _duplicate_pairs(usable_cards, "title", "body")
        placeholder_cards = [
            i + 1 for i, x in enumerate(cards)
            if _is_placeholder(x.get("title")) or _is_placeholder(x.get("body"))
        ]
        allowed_source_statuses = {"source_only", "cross_checked", "disputed", "unknown"}
        missing_card_claims = [
            i + 1 for i, x in enumerate(cards)
            if not _claim_ids(_list(x.get("claim_ids")))
        ]
        invalid_card_statuses = [
            i + 1 for i, x in enumerate(cards)
            if _text(x.get("source_status")).lower() not in allowed_source_statuses
        ]
        unknown_card_claim_ids = sorted({
            claim_id
            for card in cards
            for claim_id in _claim_ids(_list(card.get("claim_ids")))
            if research_claim_ids and claim_id not in research_claim_ids
        })
        metrics.update({
            "card_count": len(usable_cards),
            "duplicate_cards": card_duplicates,
            "placeholder_cards": placeholder_cards,
            "cards_missing_claim_ids": missing_card_claims,
            "cards_invalid_source_status": invalid_card_statuses,
            "unknown_card_claim_ids": unknown_card_claim_ids,
        })
        legacy_fallback = (
            not strict_editorial
            and not deck_present
            and len(base_usable_sections) + len(base_quick_scan) >= 4
        )
        if legacy_fallback:
            warnings.append("旧 JSON 缺少 card_deck，将从正文与速览兼容合成")
        else:
            if not _text(deck.get("cover_hook")):
                blockers.append("卡片版缺少 cover_hook")
            if len(usable_cards) < 4:
                blockers.append(f"卡片版只有 {len(usable_cards)} 张有效内容卡，至少需要 4 张")
            elif len(usable_cards) < 6:
                (blockers if strict_editorial else warnings).append(
                    f"卡片版只有 {len(usable_cards)} 张内容卡，需要 6–9 张"
                )
            if len(usable_cards) > 9:
                (blockers if strict_editorial else warnings).append(
                    f"卡片版有 {len(usable_cards)} 张内容卡，需要压缩到 6–9 张"
                )
        if card_duplicates:
            blockers.append(f"卡片版存在高度重复内容卡：{card_duplicates}")
        if placeholder_cards:
            blockers.append(f"卡片版存在占位内容：{placeholder_cards}")
        if missing_card_claims:
            target = blockers if strict_editorial and research_claim_ids else warnings
            target.append(f"内容卡缺少 claim_ids：{missing_card_claims}")
        if invalid_card_statuses:
            (blockers if strict_editorial else warnings).append(
                f"内容卡缺少合法 source_status：{invalid_card_statuses}"
            )
        if unknown_card_claim_ids:
            (blockers if strict_editorial else warnings).append(
                f"内容卡引用了不存在的研究 claim id：{unknown_card_claim_ids}"
            )

    high_ids = {
        _text(x.get("id"))
        for x in claims
        if _text(x.get("id")) and _text(x.get("importance")).lower() == "high"
    }
    coverage = distilled.get("editorial_coverage") if isinstance(distilled.get("editorial_coverage"), dict) else {}
    covered_ids = _claim_ids(_list(coverage.get("covered_claim_ids")))
    omissions = _list(coverage.get("omitted_claims"))
    valid_omissions = [
        x for x in omissions
        if isinstance(x, dict) and _text(x.get("id") or x.get("claim_id")) and _text(x.get("reason"))
    ]
    invalid_omissions = [
        x for x in omissions
        if not isinstance(x, dict) or not _text(x.get("id") or x.get("claim_id")) or not _text(x.get("reason"))
    ]
    omitted_ids = _claim_ids(valid_omissions)
    missing_ids = sorted(high_ids - covered_ids - omitted_ids)
    metrics.update({
        "high_priority_claims": len(high_ids),
        "covered_high_priority_claims": len(high_ids & covered_ids),
        "omitted_high_priority_claims": len(high_ids & omitted_ids),
        "missing_high_priority_claim_ids": missing_ids,
    })
    if high_ids and missing_ids:
        blockers.append(f"高优先级主张未覆盖且未说明舍弃原因：{missing_ids}")
    if high_ids and not coverage:
        blockers.append("有高优先级研究主张，但缺少 editorial_coverage")
    if invalid_omissions:
        blockers.append("omitted_claims 中存在缺少 claim id 或具体 reason 的条目")

    semantic_audit = semantic_claim_coverage(distilled, research, modes)
    semantic_missing = semantic_audit["semantically_missing_high_claim_ids"]
    metrics["semantic_claim_coverage"] = semantic_audit
    metrics["semantically_missing_high_claim_ids"] = semantic_missing
    if semantic_audit["uncheckable_high_claim_ids"]:
        warnings.append(
            "高优先级主张缺少可检查的 claim 文本："
            f"{semantic_audit['uncheckable_high_claim_ids']}"
        )
    if semantic_missing:
        details = [
            f"{mode}={claim_ids}"
            for mode, claim_ids in semantic_audit["missing_by_mode"].items()
            if claim_ids
        ]
        message = "高优先级主张未在发布内容中得到语义覆盖：" + "，".join(details)
        enforce_semantic = strict_editorial if semantic_coverage_strict is None else semantic_coverage_strict
        (blockers if enforce_semantic else warnings).append(message)

    if "full" in modes:
        research_experiments = [
            x for x in _list(research.get("experiments")) if isinstance(x, dict)
        ]
        research_cases = [x for x in _list(research.get("cases")) if isinstance(x, dict)]
        experiments = [
            x for x in _list(distilled.get("experiment_ledger")) if isinstance(x, dict)
        ]
        case_stories = [
            x for x in _list(distilled.get("case_stories")) if isinstance(x, dict)
        ]
        visuals = [x for x in _list(distilled.get("visuals")) if isinstance(x, dict)]
        valid_experiments = [x for x in experiments if _valid_experiment(x)]
        valid_cases = [x for x in case_stories if _valid_case_story(x)]
        section_ids = {_text(x.get("id")) for x in base_sections if _text(x.get("id"))}
        high_experiment_ids = {
            _text(x.get("id")) for x in research_experiments
            if _text(x.get("id")) and _text(x.get("importance")).lower() == "high"
        }
        high_case_ids = {
            _text(x.get("id")) for x in research_cases
            if _text(x.get("id")) and _text(x.get("importance")).lower() == "high"
        }
        output_experiment_ids = {_text(x.get("id")) for x in valid_experiments}
        output_case_ids = {_text(x.get("id")) for x in valid_cases}
        missing_experiments = sorted(high_experiment_ids - output_experiment_ids)
        missing_cases = sorted(high_case_ids - output_case_ids)
        invalid_experiment_indexes = [
            i + 1 for i, item in enumerate(experiments) if not _valid_experiment(item)
        ]
        invalid_case_indexes = [
            i + 1 for i, item in enumerate(case_stories) if not _valid_case_story(item)
        ]
        invalid_interactive_indexes = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "interactive_compare"
            and not _valid_interactive_compare(item)
        ]
        invalid_interactive_anchors = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "interactive_compare"
            and _text(item.get("after_section_id")) not in section_ids
        ]
        invalid_strategy_tab_indexes = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "strategy_tabs"
            and not _valid_strategy_tabs(item)
        ]
        invalid_strategy_tab_anchors = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "strategy_tabs"
            and _text(item.get("after_section_id")) not in section_ids
        ]
        invalid_scenario_indexes = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "scenario_calculator"
            and not _valid_scenario_calculator(item)
        ]
        invalid_scenario_anchors = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "scenario_calculator"
            and _text(item.get("after_section_id")) not in section_ids
        ]
        invalid_capacity_curve_indexes = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "capacity_curve"
            and not _valid_capacity_curve(item)
        ]
        invalid_capacity_curve_anchors = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "capacity_curve"
            and _text(item.get("after_section_id")) not in section_ids
        ]
        invalid_cost_ledger_indexes = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "cost_ledger"
            and not _valid_cost_ledger(item)
        ]
        invalid_cost_ledger_anchors = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "cost_ledger"
            and _text(item.get("after_section_id")) not in section_ids
        ]
        invalid_metric_bar_indexes = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "metric_bars"
            and not _valid_metric_bars(item)
        ]
        invalid_metric_bar_anchors = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "metric_bars"
            and _text(item.get("after_section_id")) not in section_ids
        ]
        invalid_rank_bar_indexes = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "rank_bars"
            and not _valid_rank_bars(item)
        ]
        invalid_rank_bar_anchors = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "rank_bars"
            and _text(item.get("after_section_id")) not in section_ids
        ]
        invalid_funnel_flow_indexes = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "funnel_flow"
            and not _valid_funnel_flow(item)
        ]
        invalid_funnel_flow_anchors = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "funnel_flow"
            and _text(item.get("after_section_id")) not in section_ids
        ]
        invalid_delta_table_indexes = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "delta_table"
            and not _valid_delta_table(item)
        ]
        invalid_delta_table_anchors = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "delta_table"
            and _text(item.get("after_section_id")) not in section_ids
        ]
        invalid_status_matrix_indexes = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "status_matrix"
            and not _valid_status_matrix(item)
        ]
        invalid_status_matrix_anchors = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "status_matrix"
            and _text(item.get("after_section_id")) not in section_ids
        ]
        invalid_decision_table_indexes = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "decision_table"
            and not _valid_decision_table(item)
        ]
        invalid_decision_table_anchors = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "decision_table"
            and _text(item.get("after_section_id")) not in section_ids
        ]
        invalid_flow_indexes = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "flow"
            and not _valid_flow_visual(item)
        ]
        invalid_flow_stepper_anchors = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "flow"
            and isinstance(item.get("data"), dict)
            and _text(item["data"].get("presentation")).lower() == "stepper"
            and _text(item.get("after_section_id")) not in section_ids
        ]
        invalid_timeline_indexes = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "timeline"
            and not _valid_timeline_visual(item)
        ]
        invalid_timeline_scrubber_anchors = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "timeline"
            and isinstance(item.get("data"), dict)
            and _text(item["data"].get("presentation")).lower() == "scrubber"
            and _text(item.get("after_section_id")) not in section_ids
        ]
        invalid_layer_stack_indexes = [
            i + 1 for i, item in enumerate(visuals)
            if _text(item.get("type")).lower() == "layer_stack"
            and not _valid_layer_stack(item)
        ]
        oversized_matrix_indexes = []
        for i, item in enumerate(visuals):
            if _text(item.get("type")).lower() != "compare_table":
                continue
            data = item.get("data") if isinstance(item.get("data"), dict) else {}
            if _text(data.get("layout")).lower() != "matrix":
                continue
            headers = _list(data.get("headers"))
            rows = _list(data.get("rows"))
            if len(rows) > 6 or len(headers) > 4 or len(rows) * len(headers) > 24:
                oversized_matrix_indexes.append(i + 1)
        bad_anchors = [
            f"experiment:{_text(item.get('id')) or i + 1}"
            for i, item in enumerate(valid_experiments)
            if _text(item.get("after_section_id")) not in section_ids
        ] + [
            f"case:{_text(item.get('id')) or i + 1}"
            for i, item in enumerate(valid_cases)
            if _text(item.get("after_section_id")) not in section_ids
        ]
        unknown_claim_refs = sorted({
            ref
            for item in valid_experiments + valid_cases
            for ref in _claim_ids(_list(item.get("claim_ids")))
            if ref not in research_claim_ids
        })
        source_media = [
            item for item in _list(distilled.get("source_media")) if isinstance(item, dict)
        ]
        invalid_media_indexes = [
            i + 1 for i, item in enumerate(source_media)
            if not all(_has_content(item.get(key)) for key in ("media_id", "type", "url", "after_section_id"))
            or _text(item.get("type")).lower() not in {"image", "video"}
        ]
        invalid_media_anchors = [
            _text(item.get("media_id")) or str(i + 1)
            for i, item in enumerate(source_media)
            if _text(item.get("after_section_id")) not in section_ids
        ]
        unregistered_media = [
            _text(item.get("media_id")) or str(i + 1)
            for i, item in enumerate(source_media)
            if item.get("registered") is False
        ]
        media_urls = [_text(item.get("url")) for item in source_media if _text(item.get("url"))]
        duplicate_media_urls = sorted({url for url in media_urls if media_urls.count(url) > 1})
        foreign_media_without_guidance = [
            _text(item.get("media_id")) or str(i + 1)
            for i, item in enumerate(source_media)
            if _text(item.get("language")).lower() not in {"", "zh", "zh-cn", "zh-hans", "chinese"}
            and (
                not re.search(r"[\u3400-\u9fff]", _text(item.get("caption")))
                or not re.search(r"[\u3400-\u9fff]", _text(item.get("reader_note")))
            )
        ]
        media_policy = distilled.get("media_policy") if isinstance(distilled.get("media_policy"), dict) else {}
        media_discovery = media_policy.get("discovery") if isinstance(media_policy.get("discovery"), dict) else {}
        media_discovery_status = _text(media_discovery.get("status")).lower()
        available_assets = [
            item for item in _list(media_policy.get("available_assets")) if isinstance(item, dict)
        ]
        available_demo_video_ids = [
            _text(item.get("id")) or _text(item.get("url"))
            for item in available_assets
            if _text(item.get("type")).lower() == "video"
            and _text(item.get("asset_role")).lower() in {"demo", "hero"}
        ]
        used_video_ids = {
            _text(item.get("media_id"))
            for item in source_media
            if _text(item.get("type")).lower() == "video" and item.get("registered") is True
        }
        media_omissions = [
            item for item in _list(distilled.get("media_omissions")) if isinstance(item, dict)
        ]
        invalid_media_omission_indexes = [
            i + 1 for i, item in enumerate(media_omissions)
            if not _text(item.get("media_id"))
            or len(_text(item.get("reason"))) < 4
            or _is_placeholder(item.get("reason"))
        ]
        unregistered_media_omissions = [
            _text(item.get("media_id")) or str(i + 1)
            for i, item in enumerate(media_omissions)
            if item.get("registered") is not True
        ]
        omitted_video_ids = {
            _text(item.get("media_id"))
            for item in media_omissions
            if item.get("registered") is True
            and _text(item.get("type")).lower() == "video"
            and len(_text(item.get("reason"))) >= 4
            and not _is_placeholder(item.get("reason"))
        }
        conflicting_media_decisions = sorted(used_video_ids & omitted_video_ids)
        duplicate_media_omission_ids = sorted({
            media_id
            for media_id in [_text(item.get("media_id")) for item in media_omissions]
            if media_id and sum(
                1 for item in media_omissions if _text(item.get("media_id")) == media_id
            ) > 1
        })
        unexplained_demo_video_ids = [
            media_id for media_id in available_demo_video_ids
            if media_id not in used_video_ids and media_id not in omitted_video_ids
        ]
        number_stories = [
            item for item in _list(distilled.get("number_stories")) if isinstance(item, dict)
        ]
        visible_number_stories = [
            item for item in number_stories
            if item.get("suppress_visual") is not True
            and _text(item.get("display_mode")).lower() != "audit_only"
        ]
        visible_number_story_count_by_section = {}
        for item in visible_number_stories:
            section_id = _text(item.get("after_section_id"))
            visible_number_story_count_by_section[section_id] = (
                visible_number_story_count_by_section.get(section_id, 0) + 1
            )
        dense_number_story_sections = sorted(
            section_id
            for section_id, count in visible_number_story_count_by_section.items()
            if count > 1
        )
        visual_count_by_section = {}
        for item in visuals:
            section_id = _text(item.get("after_section_id"))
            if section_id:
                visual_count_by_section[section_id] = visual_count_by_section.get(section_id, 0) + 1
        mixed_main_visual_sections = sorted(
            section_id
            for section_id in visible_number_story_count_by_section
            if visual_count_by_section.get(section_id, 0) > 0
        )
        high_metric_ids = {
            _text(item.get("id"))
            for item in claims
            if _text(item.get("id"))
            and _text(item.get("importance")).lower() == "high"
            and _text(item.get("claim_kind")).lower() == "metric"
        }
        story_claim_ids = {
            claim_id
            for item in number_stories
            for claim_id in _claim_ids(_list(item.get("claim_ids")))
        }
        missing_metric_story_ids = sorted(high_metric_ids - story_claim_ids)
        incomplete_number_story_ids = []
        invalid_number_story_anchors = []
        unknown_number_story_claim_ids = set()
        unregistered_number_story_assets = set()
        unregistered_number_story_sources = []
        incomplete_high_metric_ids = set()
        for index, item in enumerate(number_stories):
            story_id = _text(item.get("id")) or str(index + 1)
            labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
            has_context = lambda key: (  # noqa: E731
                _known_number_context(item.get(key))
                or _known_number_context(labels.get(key))
            )
            has_change = _known_number_context(item.get("baseline")) or _known_number_context(item.get("change"))
            has_source = _has_content(item.get("source_url")) or bool(_list(item.get("source_asset_ids")))
            structurally_complete = (
                all(has_context(key) for key in ("value", "unit", "denominator", "scope", "period", "boundary"))
                and has_change
                and has_source
            )
            complete = item.get("complete") is True if "complete" in item else structurally_complete
            if not complete:
                incomplete_number_story_ids.append(story_id)
                incomplete_high_metric_ids.update(
                    claim_id
                    for claim_id in _claim_ids(_list(item.get("claim_ids")))
                    if claim_id in high_metric_ids
                )
            if _text(item.get("after_section_id")) not in section_ids:
                invalid_number_story_anchors.append(story_id)
            unknown_number_story_claim_ids.update(
                claim_id
                for claim_id in _claim_ids(_list(item.get("claim_ids")))
                if research_claim_ids and claim_id not in research_claim_ids
            )
            unregistered_number_story_assets.update(_list(item.get("unregistered_source_asset_ids")))
            if item.get("source_url") and item.get("source_registered") is False:
                unregistered_number_story_sources.append(story_id)
        incomplete_high_metric_ids = sorted(incomplete_high_metric_ids)
        evidence_gallery = [
            item for item in _list(distilled.get("evidence_gallery")) if isinstance(item, dict)
        ]
        invalid_gallery_items = [
            i + 1 for i, item in enumerate(evidence_gallery)
            if item.get("registered") is False
            or not _has_content(item.get("media_id"))
            or (_has_content(item.get("type")) and _text(item.get("type")).lower() not in {"image", "video"})
        ]
        gallery_urls = [_text(item.get("url")) for item in evidence_gallery if _text(item.get("url"))]
        duplicate_gallery_urls = sorted({url for url in gallery_urls if gallery_urls.count(url) > 1})
        gallery_media_ids = {
            _text(item.get("media_id")) for item in evidence_gallery if _text(item.get("media_id"))
        }
        scenario_source_asset_ids = {
            media_id
            for item in visuals
            if _text(item.get("type")).lower() == "scenario_calculator"
            for media_id in _claim_ids(_list(
                item.get("data", {}).get("source_asset_ids")
                if isinstance(item.get("data"), dict) else []
            ))
        }
        unregistered_scenario_assets = sorted(scenario_source_asset_ids - gallery_media_ids)
        listening_cards = [
            item for item in _list(distilled.get("listening_cards")) if isinstance(item, dict)
        ]
        invalid_listening_cards = []
        invalid_listening_anchors = []
        unregistered_listening_tracks = []
        for card_index, card in enumerate(listening_cards):
            card_id = _text(card.get("id")) or str(card_index + 1)
            tracks = [track for track in _list(card.get("tracks")) if isinstance(track, dict)]
            valid_tracks = [
                track for track in tracks
                if all(_has_content(track.get(key)) for key in ("media_id", "url", "label", "prompt"))
                and bool(_list(track.get("listening_points")))
            ]
            if (
                not all(_has_content(card.get(key)) for key in ("id", "title", "after_section_id", "boundary"))
                or not tracks
                or len(valid_tracks) != len(tracks)
            ):
                invalid_listening_cards.append(card_id)
            if _text(card.get("after_section_id")) not in section_ids:
                invalid_listening_anchors.append(card_id)
            unregistered_listening_tracks.extend(
                f"{card_id}:{_text(track.get('media_id')) or index + 1}"
                for index, track in enumerate(tracks)
                if track.get("registered") is not True or _text(track.get("type")).lower() != "audio"
            )
        metrics.update({
            "research_experiment_count": len(research_experiments),
            "article_experiment_count": len(valid_experiments),
            "missing_high_experiment_ids": missing_experiments,
            "research_case_count": len(research_cases),
            "article_case_count": len(valid_cases),
            "missing_high_case_ids": missing_cases,
            "invalid_experiment_indexes": invalid_experiment_indexes,
            "invalid_case_indexes": invalid_case_indexes,
            "invalid_interactive_visual_indexes": invalid_interactive_indexes,
            "invalid_interactive_visual_anchors": invalid_interactive_anchors,
            "invalid_strategy_tab_indexes": invalid_strategy_tab_indexes,
            "invalid_strategy_tab_anchors": invalid_strategy_tab_anchors,
            "invalid_scenario_visual_indexes": invalid_scenario_indexes,
            "invalid_scenario_visual_anchors": invalid_scenario_anchors,
            "invalid_capacity_curve_indexes": invalid_capacity_curve_indexes,
            "invalid_capacity_curve_anchors": invalid_capacity_curve_anchors,
            "invalid_cost_ledger_indexes": invalid_cost_ledger_indexes,
            "invalid_cost_ledger_anchors": invalid_cost_ledger_anchors,
            "invalid_metric_bar_indexes": invalid_metric_bar_indexes,
            "invalid_metric_bar_anchors": invalid_metric_bar_anchors,
            "invalid_rank_bar_indexes": invalid_rank_bar_indexes,
            "invalid_rank_bar_anchors": invalid_rank_bar_anchors,
            "invalid_funnel_flow_indexes": invalid_funnel_flow_indexes,
            "invalid_funnel_flow_anchors": invalid_funnel_flow_anchors,
            "invalid_delta_table_indexes": invalid_delta_table_indexes,
            "invalid_delta_table_anchors": invalid_delta_table_anchors,
            "invalid_status_matrix_indexes": invalid_status_matrix_indexes,
            "invalid_status_matrix_anchors": invalid_status_matrix_anchors,
            "invalid_decision_table_indexes": invalid_decision_table_indexes,
            "invalid_decision_table_anchors": invalid_decision_table_anchors,
            "invalid_flow_visual_indexes": invalid_flow_indexes,
            "invalid_flow_stepper_anchors": invalid_flow_stepper_anchors,
            "invalid_timeline_visual_indexes": invalid_timeline_indexes,
            "invalid_timeline_scrubber_anchors": invalid_timeline_scrubber_anchors,
            "invalid_layer_stack_indexes": invalid_layer_stack_indexes,
            "oversized_matrix_visual_indexes": oversized_matrix_indexes,
            "unregistered_scenario_source_assets": unregistered_scenario_assets,
            "invalid_content_anchors": bad_anchors,
            "unknown_component_claim_ids": unknown_claim_refs,
            "source_media_count": len(source_media),
            "invalid_source_media_indexes": invalid_media_indexes,
            "invalid_source_media_anchors": invalid_media_anchors,
            "unregistered_source_media": unregistered_media,
            "duplicate_source_media_urls": duplicate_media_urls,
            "foreign_media_without_chinese_guidance": foreign_media_without_guidance,
            "available_demo_video_count": len(available_demo_video_ids),
            "used_source_video_count": len(used_video_ids),
            "media_omission_count": len(media_omissions),
            "invalid_media_omission_indexes": invalid_media_omission_indexes,
            "unregistered_media_omissions": unregistered_media_omissions,
            "duplicate_media_omission_ids": duplicate_media_omission_ids,
            "conflicting_media_decisions": conflicting_media_decisions,
            "unused_demo_video_ids": unexplained_demo_video_ids,
            "media_discovery_status": media_discovery_status,
            "number_story_count": len(number_stories),
            "visible_number_story_count": len(visible_number_stories),
            "visible_number_story_count_by_section": visible_number_story_count_by_section,
            "dense_number_story_sections": dense_number_story_sections,
            "mixed_main_visual_sections": mixed_main_visual_sections,
            "missing_high_metric_story_ids": missing_metric_story_ids,
            "incomplete_number_story_ids": incomplete_number_story_ids,
            "incomplete_high_metric_story_claim_ids": incomplete_high_metric_ids,
            "invalid_number_story_anchors": invalid_number_story_anchors,
            "unknown_number_story_claim_ids": sorted(unknown_number_story_claim_ids),
            "unregistered_number_story_assets": sorted(unregistered_number_story_assets),
            "unregistered_number_story_sources": unregistered_number_story_sources,
            "evidence_gallery_count": len(evidence_gallery),
            "invalid_evidence_gallery_items": invalid_gallery_items,
            "duplicate_evidence_gallery_urls": duplicate_gallery_urls,
            "listening_card_count": len(listening_cards),
            "invalid_listening_cards": invalid_listening_cards,
            "invalid_listening_card_anchors": invalid_listening_anchors,
            "unregistered_listening_tracks": unregistered_listening_tracks,
        })
        depth_issues = []
        if missing_experiments:
            depth_issues.append(f"高优先级实验未进入文章：{missing_experiments}")
        if missing_cases:
            depth_issues.append(f"高优先级案例未进入文章：{missing_cases}")
        if invalid_experiment_indexes:
            depth_issues.append(f"实验账本缺少问题、条件、指标、结果、限制或 claim_ids：{invalid_experiment_indexes}")
        if invalid_case_indexes:
            depth_issues.append(f"案例叙事缺少三步事件链、来源模式、结果、边界或 claim_ids：{invalid_case_indexes}")
        if invalid_interactive_indexes:
            depth_issues.append(
                f"机制互动缺少至少两个候选、两个模式、合法 selected_index 或边界说明：{invalid_interactive_indexes}"
            )
        if invalid_interactive_anchors:
            depth_issues.append(f"机制互动指向不存在的 section id：{invalid_interactive_anchors}")
        if invalid_strategy_tab_indexes:
            depth_issues.append(
                "策略切换器需要2至6个完整方案，每项包含作用对象、机制、预期效果、"
                f"待补条件和语义色，并提供阅读边界：{invalid_strategy_tab_indexes}"
            )
        if invalid_strategy_tab_anchors:
            depth_issues.append(f"策略切换器指向不存在的 section id：{invalid_strategy_tab_anchors}")
        if invalid_scenario_indexes:
            depth_issues.append(f"证据情景卡缺少双对象指标、合法滑块、计算基数、来源媒体或边界说明：{invalid_scenario_indexes}")
        if invalid_scenario_anchors:
            depth_issues.append(f"证据情景卡指向不存在的 section id：{invalid_scenario_anchors}")
        if invalid_capacity_curve_indexes:
            depth_issues.append(
                "定性曲线需要3至5个位置递增的状态、合法语义色、坐标含义，"
                f"并明确说明不是通用预测器：{invalid_capacity_curve_indexes}"
            )
        if invalid_capacity_curve_anchors:
            depth_issues.append(f"定性曲线指向不存在的 section id：{invalid_capacity_curve_anchors}")
        if invalid_cost_ledger_indexes:
            depth_issues.append(
                "成本账本需要1至4个成本项、2至6个完整且唯一的情景，"
                f"included 只能引用已登记成本，并提供口径边界：{invalid_cost_ledger_indexes}"
            )
        if invalid_cost_ledger_anchors:
            depth_issues.append(f"成本账本指向不存在的 section id：{invalid_cost_ledger_anchors}")
        if invalid_metric_bar_indexes:
            depth_issues.append(
                f"指标切换卡缺少双方案、至少两组指标、每组两行有效数值、比较方向或阅读边界：{invalid_metric_bar_indexes}"
            )
        if invalid_metric_bar_anchors:
            depth_issues.append(f"指标切换卡指向不存在的 section id：{invalid_metric_bar_anchors}")
        if invalid_rank_bar_indexes:
            depth_issues.append(
                "单口径排名条需要1至4个合法分组、每组2至18项同单位且按绝对值降序的数值，"
                f"并提供方向、语义色和阅读边界：{invalid_rank_bar_indexes}"
            )
        if invalid_rank_bar_anchors:
            depth_issues.append(f"单口径排名条指向不存在的 section id：{invalid_rank_bar_anchors}")
        if invalid_funnel_flow_indexes:
            depth_issues.append(
                "资格漏斗需要2至5道真实收窄关口、入口、每关说明和阅读边界；"
                f"显式宽度必须逐级递减：{invalid_funnel_flow_indexes}"
            )
        if invalid_funnel_flow_anchors:
            depth_issues.append(f"资格漏斗指向不存在的 section id：{invalid_funnel_flow_anchors}")
        if invalid_delta_table_indexes:
            depth_issues.append(
                "前后变化表需要2至8行完整的旧值、新值、变化、方向和语义色，并提供统一阅读边界："
                f"{invalid_delta_table_indexes}"
            )
        if invalid_delta_table_anchors:
            depth_issues.append(f"前后变化表指向不存在的 section id：{invalid_delta_table_anchors}")
        if invalid_status_matrix_indexes:
            depth_issues.append(
                "状态矩阵需要2至6个维度、2至8个对象、完整且等长的状态单元格、状态说明和阅读边界："
                f"{invalid_status_matrix_indexes}"
            )
        if invalid_status_matrix_anchors:
            depth_issues.append(f"状态矩阵指向不存在的 section id：{invalid_status_matrix_anchors}")
        if invalid_decision_table_indexes:
            depth_issues.append(
                "条件决策表需要2至8条完整的条件、结果、行动和语义色，并提供适用范围："
                f"{invalid_decision_table_indexes}"
            )
        if invalid_decision_table_anchors:
            depth_issues.append(f"条件决策表指向不存在的 section id：{invalid_decision_table_anchors}")
        if invalid_flow_indexes:
            depth_issues.append(
                "流程图至少需要两个有效步骤；步骤探索器需要3至7个含阶段名、标题和说明的步骤，"
                f"并提供阅读边界：{invalid_flow_indexes}"
            )
        if invalid_flow_stepper_anchors:
            depth_issues.append(f"步骤探索器指向不存在的 section id：{invalid_flow_stepper_anchors}")
        if invalid_timeline_indexes:
            depth_issues.append(
                "时间线至少需要两个完整节点；时间拖动器需要3至8个含时间、标题和说明的节点，"
                f"并提供阅读边界：{invalid_timeline_indexes}"
            )
        if invalid_timeline_scrubber_anchors:
            depth_issues.append(f"时间拖动器指向不存在的 section id：{invalid_timeline_scrubber_anchors}")
        if invalid_layer_stack_indexes:
            depth_issues.append(f"多层结构需要2至7层，每层含层级名、标题和说明，并提供阅读边界：{invalid_layer_stack_indexes}")
        if oversized_matrix_indexes:
            warnings.append(
                "矩阵表格过长，除非读者确实需要逐格查数，否则应改用分层、切换或拆分展示："
                f"{oversized_matrix_indexes}"
            )
        if unregistered_scenario_assets:
            depth_issues.append(f"证据情景卡引用了未进入证据图库的媒体：{unregistered_scenario_assets}")
        if bad_anchors:
            depth_issues.append(f"实验或案例指向不存在的 section id：{bad_anchors}")
        if unknown_claim_refs:
            depth_issues.append(f"实验或案例引用了不存在的研究 claim id：{unknown_claim_refs}")
        if invalid_media_indexes:
            depth_issues.append(f"原始媒体缺少 media_id、类型、URL 或段落锚点：{invalid_media_indexes}")
        if invalid_media_anchors:
            depth_issues.append(f"原始媒体指向不存在的 section id：{invalid_media_anchors}")
        if unregistered_media:
            blockers.append(f"原始媒体没有出现在抓取登记中：{unregistered_media}")
        if media_discovery_status == "failed":
            blockers.append(
                "动态网页媒体发现未完成："
                + (_text(media_discovery.get("reason")) or "未提供失败原因")
            )
        if duplicate_media_urls:
            depth_issues.append(f"原始媒体被重复使用：{duplicate_media_urls}")
        if foreign_media_without_guidance:
            blockers.append(
                "外语媒体必须提供自然中文图注和观看重点/读图提示："
                f"{foreign_media_without_guidance}"
            )
        if invalid_media_omission_indexes:
            blockers.append(
                "媒体省略记录必须包含已登记 media_id 和具体理由："
                f"{invalid_media_omission_indexes}"
            )
        if unregistered_media_omissions:
            blockers.append(f"媒体省略记录引用了未登记素材：{unregistered_media_omissions}")
        if duplicate_media_omission_ids:
            depth_issues.append(f"同一媒体被重复记录为省略：{duplicate_media_omission_ids}")
        if conflicting_media_decisions:
            blockers.append(f"同一视频不能同时采用和省略：{conflicting_media_decisions}")
        if unexplained_demo_video_ids:
            blockers.append(
                "原页的重要演示或首屏视频既未采用，也没有具体省略理由："
                f"{unexplained_demo_video_ids}"
            )
        if missing_metric_story_ids:
            depth_issues.append(f"高优先级指标主张缺少完整数字叙事：{missing_metric_story_ids}")
        if dense_number_story_sections:
            blockers.append(
                "同一章节不得连续展示多张数字大卡；请保留一张承担论证任务的卡，"
                f"其余设置 suppress_visual=true：{dense_number_story_sections}"
            )
        if mixed_main_visual_sections:
            blockers.append(
                "同一章节已有图表或关系组件时，不得再公开展示大数字卡；请把数字并入唯一主视觉，"
                f"并将对应 number_story 设置 suppress_visual=true：{mixed_main_visual_sections}"
            )
        if incomplete_high_metric_ids:
            depth_issues.append(f"高优先级数字叙事缺少单位、分母、范围、时间、对照或变化、边界或登记来源：{incomplete_high_metric_ids}")
        if invalid_number_story_anchors:
            depth_issues.append(f"数字叙事指向不存在的 section id：{invalid_number_story_anchors}")
        if unknown_number_story_claim_ids:
            depth_issues.append(f"数字叙事引用了不存在的研究 claim id：{sorted(unknown_number_story_claim_ids)}")
        if unregistered_number_story_assets:
            blockers.append(f"数字叙事引用了未登记媒体：{sorted(unregistered_number_story_assets)}")
        if unregistered_number_story_sources:
            blockers.append(f"数字叙事引用了未登记来源 URL：{unregistered_number_story_sources}")
        if invalid_gallery_items:
            depth_issues.append(f"证据图库包含未登记或结构无效的媒体：{invalid_gallery_items}")
        if duplicate_gallery_urls:
            depth_issues.append(f"证据图库存在重复 URL：{duplicate_gallery_urls}")
        if invalid_listening_cards:
            depth_issues.append(
                f"试听卡缺少标题、章节锚点、证据边界，或曲目缺少提示词与听感重点：{invalid_listening_cards}"
            )
        if invalid_listening_anchors:
            depth_issues.append(f"试听卡指向不存在的 section id：{invalid_listening_anchors}")
        if unregistered_listening_tracks:
            blockers.append(f"试听卡引用了未登记的音频：{unregistered_listening_tracks}")
        incomplete_noncritical = [
            story_id for story_id in incomplete_number_story_ids
            if story_id not in {
                _text(item.get("id"))
                for item in number_stories
                if _claim_ids(_list(item.get("claim_ids"))) & high_metric_ids
            }
        ]
        if incomplete_noncritical:
            warnings.append(f"不完整数字叙事已降级为普通正文：{incomplete_noncritical}")
        target = blockers if strict_editorial else warnings
        target.extend(depth_issues)

    language_issues = find_language_issues(distilled)
    metrics["language_issue_count"] = len(language_issues)
    metrics["language_issues"] = language_issues
    if language_issues:
        details = [
            f"{item['path']}：{item['message']}（{item['text']}）"
            for item in language_issues[:6]
        ]
        (blockers if strict_editorial else warnings).append(
            "成文语言检查发现高置信语病：" + "；".join(details)
        )

    score = max(0, 100 - len(blockers) * 20 - len(warnings) * 5)
    return {
        "publishable": not blockers,
        "score": score,
        "blockers": blockers,
        "warnings": warnings,
        "metrics": metrics,
    }


def choose_preferred(
    draft: dict,
    revised: dict,
    research: dict | None = None,
    required_modes: Iterable[str] = ("full", "onepager", "cards"),
    strict_editorial: bool = True,
) -> tuple[dict, str, dict, dict]:
    """选择确定性质量更好的版本；分数相同时优先审校后的版本。"""
    draft_audit = audit_distilled(draft, research, required_modes, strict_editorial)
    revised_audit = audit_distilled(revised, research, required_modes, strict_editorial)
    draft_rank = (len(draft_audit["blockers"]), len(draft_audit["warnings"]), -draft_audit["score"])
    revised_rank = (len(revised_audit["blockers"]), len(revised_audit["warnings"]), -revised_audit["score"])
    if revised_rank <= draft_rank:
        return revised, "revised", draft_audit, revised_audit
    return draft, "draft", draft_audit, revised_audit


def assert_publishable(audit: dict, stage: str = "写作结果") -> None:
    blockers = list(audit.get("blockers") or [])
    if blockers:
        raise ValueError(f"{stage}未通过质量门禁：" + "；".join(blockers[:6]))
