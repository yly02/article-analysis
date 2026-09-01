"""面向成文内容的确定性语言检查与保守自动修复。

语义级审校仍由 LLM 主编完成。本模块只处理高置信、低风险的问题，并跳过
研究账本、逐字引文、代码、URL 与生成元数据，避免为了润色改变证据。
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True)
class LanguageRule:
    code: str
    pattern: re.Pattern[str]
    message: str
    replacement: str | None = None
    category: str = "搭配或结构问题"


RULES = (
    LanguageRule(
        "awkward_problem_explains_system",
        re.compile(r"三个(?:很)?具体的问题最能说明这套制度"),
        "“问题说明制度”主谓搭配生硬，应改为制度解决了哪些问题或用案例说明制度",
        "要理解这套制度具体在解决什么，看三个例子就够了",
    ),
    LanguageRule(
        "awkward_team_responsibility",
        re.compile(r"问题可能不归某一个团队完整负责"),
        "“问题不归团队完整负责”搭配不自然，应明确责任主体",
        "没有哪个团队对这些问题负完整责任",
    ),
    LanguageRule(
        "awkward_duration_object",
        re.compile(r"没有给出三件事从提出到解决用了多久"),
        "“给出三件事用了多久”动宾关系不清",
        "没有说明这三件事从提出到解决各自用了多长时间",
    ),
    LanguageRule(
        "parallel_question_production_break",
        re.compile(r"各自在减少哪一(?:种|类)制作断点"),
        "“各自”“哪一种”和“减少制作断点”搭配杂糅",
        "分别解决哪类制作问题",
    ),
    LanguageRule(
        "parallel_eliminate_production_break",
        re.compile(r"分别在消灭([一二三四五六七八九十两\d]+)(?:种|类)制作断点"),
        "“分别在消灭……制作断点”搭配生硬",
        r"分别解决\1类制作问题",
    ),
    LanguageRule(
        "missing_loss_complement",
        re.compile(r"进入专业后期时丢动态范围"),
        "“丢动态范围”缺少结果补语",
        "进入专业后期时丢失动态范围",
    ),
    LanguageRule(
        "missing_generation_frame",
        re.compile(r"复杂多主体指令首次生成偏离"),
        "时间状语与谓语衔接生硬",
        "复杂多主体指令在首次生成时偏离",
    ),
    LanguageRule(
        "repeated_chinese_punctuation",
        re.compile(r"([，。！？；：])\1+"),
        "存在连续重复的中文标点",
        r"\1",
    ),
    LanguageRule(
        "ambiguous_parallel_question",
        re.compile(r"各自在(?:减少|消灭|解决|降低|增加|提升)哪一(?:种|类)"),
        "“各自”和“哪一种/哪一类”关系不清，请明确为“分别……”或改写问句",
    ),
    LanguageRule(
        "duplicated_de",
        re.compile(r"(?<!的)的的(?!确)"),
        "疑似重复虚词“的的”",
    ),
    LanguageRule(
        "redundant_reason_because",
        re.compile(r"原因是因为"),
        "“原因是因为”句式杂糅，应保留“原因是”或“是因为”中的一种",
        "原因是",
        "结构混乱/句式杂糅",
    ),
    LanguageRule(
        "redundant_mainly_based_on",
        re.compile(r"主要以([^，。！？；\n]{1,36})为主"),
        "“主要以……为主”成分赘余",
        r"以\1为主",
        "成分赘余",
    ),
    LanguageRule(
        "redundant_purpose_aims",
        re.compile(r"目的旨在"),
        "“目的旨在”成分赘余",
        "旨在",
        "成分赘余",
    ),
    LanguageRule(
        "redundant_current_priority",
        re.compile(r"目前的当务之急"),
        "“目前的当务之急”语义重复",
        "当务之急",
        "成分赘余",
    ),
    LanguageRule(
        "redundant_can_be_called",
        re.compile(r"可以堪称"),
        "“可以堪称”成分赘余",
        "堪称",
        "成分赘余",
    ),
    LanguageRule(
        "mixed_around_center",
        re.compile(r"围绕([^，。！？；\n]{1,36})为中心"),
        "“围绕……为中心”混用了两种句式",
        r"以\1为中心",
        "结构混乱/句式杂糅",
    ),
    LanguageRule(
        "mixed_based_on_principle",
        re.compile(r"本着([^，。！？；\n]{1,28})为原则"),
        "“本着……为原则”句式杂糅",
        r"本着\1的原则",
        "结构混乱/句式杂糅",
    ),
    LanguageRule(
        "mixed_due_to_result",
        re.compile(r"是由于([^，。！？；\n]{1,48})造成的结果"),
        "“是由于……造成的结果”句式杂糅",
        r"是由于\1造成的",
        "结构混乱/句式杂糅",
    ),
    LanguageRule(
        "negative_prevention",
        re.compile(r"((?:防止|避免|杜绝)[^，。！？；\n]{0,28}?)不再(发生|出现|复发)"),
        "防止类动词与“不再”叠加后使肯否关系相反",
        r"\1再次\2",
        "否定失当",
    ),
    LanguageRule(
        "redundant_approximate_range",
        re.compile(
            r"((?:大约|约|近)(?:有)?\s*[0-9一二三四五六七八九十百千万亿点.,]+\s*"
            r"(?:%|％|个|名|人|项|次|年|月|天|小时|分钟|秒|条|份|台|GB|MB|TB)?)\s*左右"
        ),
        "“约/近……左右”范围表达重复",
        r"\1",
        "数量/范围表达",
    ),
    LanguageRule(
        "redundant_exceed_above",
        re.compile(
            r"(超过\s*[0-9一二三四五六七八九十百千万亿点.,]+\s*"
            r"(?:%|％|个|名|人|项|次|年|月|天|小时|分钟|秒|条|份|台|GB|MB|TB)?)\s*以上"
        ),
        "“超过……以上”范围表达重复",
        r"\1",
        "数量/范围表达",
    ),
    LanguageRule(
        "indirect_question_mark",
        re.compile(
            r"((?:请|需要|应当|务必)?(?:说明|确认|检查|核实|判断)"
            r"[^：。！？!?\n]{0,72}(?:是否|能否|有没有)[^。！？!?\n]{0,72})[？?]"
        ),
        "要求说明或确认的间接疑问句末不应使用问号",
        r"\1。",
        "标点问题",
    ),
    LanguageRule(
        "mixed_not_only_but_instead",
        re.compile(r"不仅[^，。！？；\n]{1,64}(?:，|,)?\s*而是"),
        "“不仅……而是……”混用了递进和取舍关系，应根据原意选择“不仅……而且”或“不是……而是”",
        None,
        "关联词错误",
    ),
    LanguageRule(
        "mixed_if_only_then",
        re.compile(r"只要[^，。！？；\n]{1,64}(?:，|,)?\s*才"),
        "“只要……才……”混淆充分条件与必要条件，应根据原意选择“只要……就”或“只有……才”",
        None,
        "关联词错误",
    ),
    LanguageRule(
        "invalid_decrease_multiple",
        re.compile(r"(?:降低|减少|下降)了?\s*[0-9一二三四五六七八九十百千万亿点.]+\s*倍"),
        "降低幅度通常不能直接用倍数表达，应依据真实数据改成百分比或“降至原来的……”",
        None,
        "数量/范围表达",
    ),
    LanguageRule(
        "ambiguous_percent_change",
        re.compile(r"从\s*\d+(?:\.\d+)?\s*[%％]\s*(?:提高|增加|上升)了\s*\d+(?:\.\d+)?\s*[%％]"),
        "“从 A% 提高了 B%”无法区分提高到 B% 还是相对提高 B%，必须按真实口径明确",
        None,
        "数量/范围表达",
    ),
    LanguageRule(
        "percentage_point_wording",
        re.compile(r"(?:提高|增加|上升|降低|减少|下降)了?\s*\d+(?:\.\d+)?\s*个百分比"),
        "百分率之差通常使用“百分点”；若表达相对变化，应改用百分比并保留真实口径",
        None,
        "数量/范围表达",
    ),
)

ABSTRACT_ACTION_RE = re.compile(
    r"(?:如何|怎么)被(?:接住|托住|兜住)|(?:事情|问题)(?:如何|怎么|怎样)收住|"
    r"(?:跑通|打通)(?:了)?(?:整个)?闭环|(?:各自)?守住哪一段"
)

SKIP_CONTAINERS = {
    "research_ledger",
    "evidence_policy",
    "media_policy",
    "editorial_quality",
    "source_media",
    "media_omissions",
    "sources",
    "source_links",
    "evidence",
}

SKIP_LEAVES = {
    "id",
    "claim_id",
    "claim_ids",
    "url",
    "source_url",
    "poster_url",
    "original",
    "quote",
    "source_quote",
    "code",
    "code_block",
    "prompt",
    "image_data_uri",
    "image_path",
    "content_hash",
    "retrieved_at",
}

PROTECTED_RE = re.compile(r"```.*?```|`[^`\n]+`|https?://[^\s<>\"']+", re.DOTALL)
CJK_RE = re.compile(r"[\u3400-\u9fff]")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?])")
ANTITHESIS_RE = re.compile(r"不是.{0,42}?而是|并非.{0,42}?而是|不在于.{0,42}?而在于")
PROXY_READER_RE = re.compile(
    r"(?:你|读者)(?:可能|也许|一定|肯定|大概|多半)会(?:觉得|想|问|说|担心)|"
    r"有人(?:可能|也许)会(?:觉得|想|问|说)|"
    r"(?:你|读者)是不是(?:觉得|以为|担心)"
)
PERFORMATIVE_DEPTH_RE = re.compile(
    r"本质上|归根结底|真正的(?:问题|答案|关键|真相)是|这才是(?:真正的)?(?:问题|答案|关键|真相)"
)
STIFF_PHRASES = (
    "值得注意的是",
    "综上所述",
    "总体来看",
    "从某种意义上",
    "不难发现",
    "毋庸置疑",
    "在当今时代",
    "随着人工智能的快速发展",
)

REDUNDANT_DATE_PAREN_RE = re.compile(
    r"(?P<iso>(?P<iso_year>\d{4})-(?P<iso_month>\d{2})-(?P<iso_day>\d{2}))"
    r"\s*[（(]\s*(?P<cn_year>\d{4})\s*年\s*(?P<cn_month>\d{1,2})\s*月\s*"
    r"(?P<cn_day>\d{1,2})\s*日\s*[）)]"
)


def _same_date_formats(match: re.Match[str]) -> bool:
    return (
        match.group("iso_year") == match.group("cn_year")
        and int(match.group("iso_month")) == int(match.group("cn_month"))
        and int(match.group("iso_day")) == int(match.group("cn_day"))
    )


def _path_text(path: tuple[str | int, ...]) -> str:
    result = "$"
    for part in path:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def _walk_text(
    value: Any,
    path: tuple[str | int, ...] = (),
) -> Iterator[tuple[tuple[str | int, ...], str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if key_text in SKIP_CONTAINERS or key_text in SKIP_LEAVES:
                continue
            yield from _walk_text(child, (*path, key_text))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_text(child, (*path, index))
    elif isinstance(value, str) and CJK_RE.search(value):
        yield path, value


def _unprotected_fragments(text: str) -> Iterator[str]:
    cursor = 0
    for match in PROTECTED_RE.finditer(text):
        if match.start() > cursor:
            yield text[cursor:match.start()]
        cursor = match.end()
    if cursor < len(text):
        yield text[cursor:]


def find_language_issues(distilled: dict) -> list[dict]:
    """扫描成文内容并返回带字段路径的高置信语言问题。"""
    if not isinstance(distilled, dict):
        return []
    issues: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for path, value in _walk_text(distilled):
        path_text = _path_text(path)
        for fragment in _unprotected_fragments(value):
            for match in REDUNDANT_DATE_PAREN_RE.finditer(fragment):
                if not _same_date_formats(match):
                    continue
                key = (path_text, "redundant_date_parenthesis", match.group(0))
                if key not in seen:
                    seen.add(key)
                    issues.append({
                        "path": path_text,
                        "rule": "redundant_date_parenthesis",
                        "judgment": "明确病句",
                        "category": "成分赘余",
                        "message": "同一日期使用两种等价格式重复括注，只保留一种即可",
                        "text": match.group(0),
                        "auto_fixable": True,
                    })
            for rule in RULES:
                for match in rule.pattern.finditer(fragment):
                    key = (path_text, rule.code, match.group(0))
                    if key in seen:
                        continue
                    seen.add(key)
                    issues.append({
                        "path": path_text,
                        "rule": rule.code,
                        "judgment": "明确病句",
                        "category": rule.category,
                        "message": rule.message,
                        "text": match.group(0),
                        "auto_fixable": rule.replacement is not None,
                    })
    return issues


def analyze_reader_voice(distilled: dict) -> dict:
    """Return conservative readability signals for full-article prose.

    These are editorial hints, not grammar errors. They deliberately avoid
    rewriting content because paragraph rhythm and tone require semantic judgment.
    """
    if not isinstance(distilled, dict):
        return {
            "dense_section_indexes": [],
            "long_sentences": [],
            "stiff_phrase_hits": [],
            "antithesis_count": 0,
            "proxy_reader_hits": [],
            "performative_depth_hits": [],
            "abstract_action_hits": [],
            "uniform_rhythm_section_indexes": [],
            "question_dense_section_indexes": [],
        }

    sections = [item for item in distilled.get("sections") or [] if isinstance(item, dict)]
    dense_sections: list[int] = []
    long_sentences: list[dict] = []
    stiff_hits: list[dict] = []
    antithesis_count = 0
    proxy_reader_hits: list[dict] = []
    performative_depth_hits: list[dict] = []
    abstract_action_hits: list[dict] = []
    uniform_rhythm_sections: list[int] = []
    question_dense_sections: list[int] = []

    for index, section in enumerate(sections, start=1):
        title = str(section.get("title") or "").strip()
        content = str(section.get("content") or "").strip()
        path = f"$.sections[{index - 1}].content"
        cjk_count = len(CJK_RE.findall(content))
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
        if cjk_count >= 140 and len(paragraphs) < 2:
            dense_sections.append(index)

        sentence_lengths: list[int] = []
        for sentence in SENTENCE_SPLIT_RE.split(content):
            sentence = sentence.strip()
            sentence_cjk = len(CJK_RE.findall(sentence))
            if sentence_cjk >= 4:
                sentence_lengths.append(sentence_cjk)
            if sentence_cjk > 72:
                long_sentences.append({
                    "path": path,
                    "char_count": sentence_cjk,
                    "text": sentence[:96],
                })

        searchable = f"{title}\n{content}"
        antithesis_count += len(ANTITHESIS_RE.findall(searchable))
        for match in PROXY_READER_RE.finditer(searchable):
            proxy_reader_hits.append({"path": path, "text": match.group(0)})
        for match in PERFORMATIVE_DEPTH_RE.finditer(searchable):
            performative_depth_hits.append({"path": path, "text": match.group(0)})
        if searchable.count("？") + searchable.count("?") >= 3:
            question_dense_sections.append(index)
        if len(sentence_lengths) >= 5:
            mean = sum(sentence_lengths) / len(sentence_lengths)
            variance = sum((length - mean) ** 2 for length in sentence_lengths) / len(sentence_lengths)
            coefficient = variance ** 0.5 / mean if mean else 0.0
            if coefficient < 0.18:
                uniform_rhythm_sections.append(index)
        for phrase in STIFF_PHRASES:
            count = searchable.count(phrase)
            if count:
                stiff_hits.append({"path": path, "phrase": phrase, "count": count})

    public_copy = {
        "distilled_title": distilled.get("distilled_title"),
        "sections": distilled.get("sections"),
        "case_stories": distilled.get("case_stories"),
        "visuals": distilled.get("visuals"),
        "number_stories": distilled.get("number_stories"),
        "action_card": distilled.get("action_card"),
        "takeaway_list": distilled.get("takeaway_list"),
    }
    for path, value in _walk_text(public_copy):
        for match in ABSTRACT_ACTION_RE.finditer(value):
            abstract_action_hits.append({
                "path": _path_text(path),
                "text": match.group(0),
            })

    return {
        "dense_section_indexes": dense_sections,
        "long_sentences": long_sentences,
        "stiff_phrase_hits": stiff_hits,
        "antithesis_count": antithesis_count,
        "proxy_reader_hits": proxy_reader_hits,
        "performative_depth_hits": performative_depth_hits,
        "abstract_action_hits": abstract_action_hits,
        "uniform_rhythm_section_indexes": uniform_rhythm_sections,
        "question_dense_section_indexes": question_dense_sections,
    }


def _fix_unprotected(text: str, path: str, fixes: list[dict]) -> str:
    parts: list[str] = []
    cursor = 0
    for protected in PROTECTED_RE.finditer(text):
        parts.append(_fix_fragment(text[cursor:protected.start()], path, fixes))
        parts.append(protected.group(0))
        cursor = protected.end()
    parts.append(_fix_fragment(text[cursor:], path, fixes))
    return "".join(parts)


def _fix_fragment(fragment: str, path: str, fixes: list[dict]) -> str:
    def collapse_date(match: re.Match[str]) -> str:
        if not _same_date_formats(match):
            return match.group(0)
        replacement = match.group("iso")
        fixes.append({
            "path": path,
            "rule": "redundant_date_parenthesis",
            "before": match.group(0),
            "after": replacement,
        })
        return replacement

    result = REDUNDANT_DATE_PAREN_RE.sub(collapse_date, fragment)
    for rule in RULES:
        if rule.replacement is None:
            continue

        def replace(match: re.Match[str]) -> str:
            replacement = match.expand(rule.replacement or "")
            fixes.append({
                "path": path,
                "rule": rule.code,
                "before": match.group(0),
                "after": replacement,
            })
            return replacement

        result = rule.pattern.sub(replace, result)
    return result


def _fix_value(value: Any, path: tuple[str | int, ...], fixes: list[dict]) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            key_text = str(key)
            if key_text in SKIP_CONTAINERS or key_text in SKIP_LEAVES:
                result[key] = child
            else:
                result[key] = _fix_value(child, (*path, key_text), fixes)
        return result
    if isinstance(value, list):
        return [_fix_value(child, (*path, index), fixes) for index, child in enumerate(value)]
    if isinstance(value, str) and CJK_RE.search(value):
        return _fix_unprotected(value, _path_text(path), fixes)
    return value


def apply_safe_language_fixes(distilled: dict) -> tuple[dict, list[dict]]:
    """返回保守修复后的深拷贝和修复记录，不修改输入对象。"""
    if not isinstance(distilled, dict):
        return distilled, []
    fixes: list[dict] = []
    fixed = _fix_value(copy.deepcopy(distilled), (), fixes)
    return fixed, fixes
