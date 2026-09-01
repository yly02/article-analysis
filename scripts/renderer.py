"""HTML 渲染模块：把解读 JSON 渲染成自包含图文 HTML。

v6 升级（融文风格 + 目录导航）：
- v5 基础上去掉所有组件标签，比方/概念/原文融进正文流
- 新增目录导航卡（toc-card）：可点击跳转到各段落，smooth scroll
- 新增推荐理由行（rec-reason）：一句话说明为什么值得读
- 事实核查保留在数据层，页面只显示统一资料区
- 保留主题切换与目录导航
- 向后兼容旧 JSON（one_liner + key_points 自动合成，无 recommendation_reason 不报错）
CSS/JS 全内联，浏览器直开可看，不依赖任何第三方库。
"""

from __future__ import annotations

import html
import re
from typing import Any

from fetcher import Article


def _esc(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")


def _render_text_with_term_markers(
    text: str,
    term_refs: list[dict],
    used_targets: set[str],
) -> str:
    """Escape prose and append markers to non-overlapping first term mentions."""
    matches = []
    for ref in term_refs:
        marker_id = str(ref.get("marker_id") or "")
        term = str(ref.get("term") or "")
        if not marker_id or not term or marker_id in used_targets:
            continue
        position = text.find(term)
        if position >= 0:
            marker_end = position + len(term)
            if marker_end < len(text) and text[marker_end] in "（(":
                closing = "）" if text[marker_end] == "（" else ")"
                close_at = text.find(closing, marker_end + 1)
                if close_at >= 0 and close_at - marker_end <= 40 and "\n" not in text[marker_end:close_at]:
                    marker_end = close_at + 1
            matches.append((position, -len(term), term, marker_end, ref))
    matches.sort()

    accepted = []
    cursor = 0
    for position, _negative_length, term, marker_end, ref in matches:
        if position < cursor:
            continue
        accepted.append((position, term, marker_end, ref))
        cursor = marker_end

    if not accepted:
        return _esc(text)
    parts = []
    cursor = 0
    for position, term, marker_end, ref in accepted:
        marker_id = str(ref["marker_id"])
        popover_id = f"{marker_id}-popover"
        definition = str(ref.get("definition") or "")
        analogy = str(ref.get("analogy") or "")
        plain = (
            '<span class="term-popover-plain">'
            '<span class="term-popover-label">通俗理解</span>'
            f'{_esc(analogy)}</span>'
        ) if analogy else ""
        parts.append(_esc(text[cursor:marker_end]))
        parts.append(
            f'<sup class="term-marker-wrap" id="{_esc(marker_id)}">'
            '<button class="term-marker" type="button" data-term-popover-toggle '
            f'aria-label="查看“{_esc(term)}”的名词解释" '
            f'aria-describedby="{_esc(popover_id)}" aria-expanded="false">i</button>'
            f'<span class="term-popover" id="{_esc(popover_id)}" role="tooltip">'
            f'<strong class="term-popover-term">{_esc(term)}</strong>'
            f'<span class="term-popover-definition">{_esc(definition)}</span>'
            f'{plain}</span></sup>'
        )
        used_targets.add(marker_id)
        cursor = marker_end
    parts.append(_esc(text[cursor:]))
    return "".join(parts)


def _render_prose_paragraphs(value: Any, term_refs: list[dict] | None = None) -> str:
    """Render paragraphs and mark each glossary term at its first body mention."""
    text = str(value or "").strip()
    if not text:
        return ""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    rendered = []
    used_targets: set[str] = set()
    for paragraph in paragraphs:
        normalized = re.sub(r"\s*\n\s*", " ", paragraph)
        prose = _render_text_with_term_markers(normalized, term_refs or [], used_targets)
        rendered.append(f"<p>{prose}</p>")
    return "".join(rendered)


_VERDICT_CLASS = {
    "确认": "v-ok",
    "交叉验证": "v-ok",
    "原文声称": "v-warn",
    "存疑": "v-warn",
    "夸大": "v-bad",
    "无法核实": "v-warn",
}

# ── CSS ──────────────────────────────────────────────────────

_CSS = """
:root {
  --bg: #f7f8fa; --card: #ffffff; --ink: #1a1a1a; --sub: #6b7280;
  --line: #e5e7eb; --accent: #5b9bd5; --accent-soft: #eef7ff;
  --ok: #16a34a; --warn: #d97706; --bad: #dc2626;
  --quote-bg: #f8f9fb; --bias-bg: #fff7ed; --bias-border: #fdba74;
  --analogy-bg: #f7fbff; --term-bg: #f5f7fa; --statement-bg: #eef7ff;
  --term-accent: #526b87; --statement-accent: #1677ff;
  --metric-primary: #1f9d68; --metric-primary-soft: #eaf7f1;
  --metric-baseline: #4f7fd8; --metric-baseline-soft: #eaf1fd;
  --ok-soft: #edf8f2; --warn-soft: #fff7e8; --bad-soft: #fff0f0;
}
[data-theme="dark"] {
  --bg: #0f1115; --card: #1a1d24; --ink: #e5e7eb; --sub: #9ca3af;
  --line: #2d3038; --accent: #8dc1f3; --accent-soft: #182738;
  --ok: #4ade80; --warn: #fbbf24; --bad: #f87171;
  --quote-bg: #161922; --bias-bg: #2a2018; --bias-border: #92400e;
  --analogy-bg: #141e29; --term-bg: #20242d; --statement-bg: #182738;
  --term-accent: #9fb3c8; --statement-accent: #8dc1f3;
  --metric-primary: #52c991; --metric-primary-soft: #17352b;
  --metric-baseline: #82aaf1; --metric-baseline-soft: #1b2b47;
  --ok-soft: #17352b; --warn-soft: #352916; --bad-soft: #3a1d22;
}
[data-theme="sepia"] {
  --bg: #f5f0e1; --card: #fffdf5; --ink: #4a3b2a; --sub: #8b7d6b;
  --line: #ddd0b8; --accent: #8b6914; --accent-soft: #f5edd0;
  --ok: #5d7c1f; --warn: #b8860b; --bad: #c14444;
  --quote-bg: #ede4cc; --bias-bg: #f5edd0; --bias-border: #c4a44a;
  --analogy-bg: #fbf6e8; --term-bg: #f4eddb; --statement-bg: #f5edd0;
  --term-accent: #7c6b52; --statement-accent: #8b6914;
  --metric-primary: #3d8b62; --metric-primary-soft: #e9f1e5;
  --metric-baseline: #587caa; --metric-baseline-soft: #e7edf3;
  --ok-soft: #e9f1e5; --warn-soft: #f8edcf; --bad-soft: #f8e3df;
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.85; -webkit-font-smoothing:antialiased; transition: background .2s; }
.wrap { max-width:780px; margin:0 auto; padding:40px 20px 80px; }

/* 主题切换器 */
.theme-switcher { position:fixed; top:16px; right:16px; display:flex; gap:6px; z-index:100; }
.theme-btn { width:28px; height:28px; border-radius:50%; border:1.5px solid var(--line);
  cursor:pointer; transition:transform .15s; }
.theme-btn:hover { transform:scale(1.1); }
.theme-btn.active { border-color:var(--accent); border-width:2px; }
.theme-light { background:#f7f8fa; } .theme-dark { background:#0f1115; } .theme-sepia { background:#f5f0e1; }

/* 文章头部 */
header { margin-bottom:32px; }
.category-tags { display:flex; flex-wrap:wrap; gap:6px; margin:0 0 10px; }
.category-tag { background:var(--accent-soft); color:var(--accent); font-size:12px;
  padding:2px 10px; border-radius:12px; font-weight:500; }
header h1 { font-size:26px; line-height:1.35; margin:0 0 10px; font-weight:700; }
header .sub-title { color:var(--sub); font-size:14px; }
.source-panel { margin:52px 0 10px; border-top:1px solid var(--line); color:var(--sub); }
.source-row { display:grid; grid-template-columns:132px minmax(0,1fr); gap:34px;
  padding:22px 0; border-bottom:1px solid var(--line); }
.source-label { color:var(--sub); font-size:13px; font-weight:700; letter-spacing:0; }
.source-content { min-width:0; font-size:14px; line-height:1.75; }
.source-title { display:block; color:var(--ink); font-size:15px; font-weight:650;
  line-height:1.55; overflow-wrap:anywhere; }
.source-meta,.source-links { display:flex; flex-wrap:wrap; align-items:baseline; gap:0;
  margin-top:8px; }
.source-meta > * + *::before,.source-links > * + *::before {
  content:"·"; display:inline-block; margin:0 10px; color:var(--sub); }
.source-panel a { color:var(--accent); text-decoration:none; text-underline-offset:3px; }
.source-panel a:hover { text-decoration:underline; }
.source-note { margin:0; }

/* 来源声明 */
.bias-note { background:var(--bias-bg); border-left:3px solid var(--warn);
  border-radius:0 8px 8px 0; padding:12px 18px; margin-bottom:24px;
  font-size:14px; color:var(--ink); line-height:1.7; }

/* 推荐理由 */
.rec-reason { font-size:15px; color:var(--ink); line-height:1.75;
  padding:0 4px 20px; margin:0; border:none; }
.rec-reason strong { color:var(--accent); }

/* 一分钟速览：三条纵向结论，不替代目录，也不压缩正文。 */
.quick-scan { margin:0 0 28px; padding:15px 18px 15px 20px; border:1px solid var(--line);
  border-left:3px solid var(--accent); border-radius:6px; background:var(--card); }
.quick-scan-title { margin:0 0 8px; color:var(--accent); font-size:13px; font-weight:750; }
.quick-scan-list { margin:0; padding-left:20px; }
.quick-scan-list li { padding:4px 0; color:var(--ink); font-size:14.5px; line-height:1.7; }
.quick-scan-list li::marker { color:var(--accent); }
.quick-scan-list li:nth-child(2)::marker { color:var(--ok); }
.quick-scan-list li:nth-child(3)::marker { color:var(--warn); }
.quick-scan-list li:nth-child(2) { border-left:2px solid var(--ok); padding-left:10px; }
.quick-scan-list li:nth-child(3) { border-left:2px solid var(--warn); padding-left:10px; }

/* 目录与按需原文引文栏不占正文流；术语使用正文浮层 */
html { scroll-behavior:smooth; }
.toc-card,.glossary-rail { position:fixed; bottom:16px; z-index:90; background:var(--card);
  border:1px solid var(--line); border-radius:6px; box-shadow:0 8px 24px rgba(0,0,0,.12); }
.toc-card { left:16px; }
.glossary-rail { right:16px; }
.toc-card:not([open]) { width:88px; }
.glossary-rail:not([open]) { width:108px; }
.toc-card[open],.glossary-rail[open] { width:min(360px,calc(100vw - 32px)); max-height:70vh; overflow:auto; }
.toc-heading,.glossary-heading { display:flex; align-items:center; justify-content:space-between; gap:8px;
  min-height:42px; padding:9px 12px; color:var(--ink); font-size:12px; font-weight:700;
  cursor:pointer; list-style:none; letter-spacing:0; }
.toc-heading::-webkit-details-marker,.glossary-heading::-webkit-details-marker { display:none; }
.toc-heading::after,.glossary-heading::after { content:"+"; color:var(--accent); font-size:16px; font-weight:500; }
.toc-card[open] .toc-heading::after,.glossary-rail[open] .glossary-heading::after { content:"−"; }
.toc-list { list-style:none; padding:0; margin:0; }
.toc-item { display:flex; align-items:flex-start; gap:8px; padding:6px 0;
  border-bottom:1px solid var(--line); }
.toc-item:last-child { border-bottom:none; }
.toc-num { color:var(--accent); font-weight:600; font-size:14px;
  flex-shrink:0; min-width:20px; }
.toc-link { color:var(--ink); text-decoration:none; font-size:14.5px;
  line-height:1.5; cursor:pointer; }
.toc-link:hover { color:var(--accent); }
.toc-link.active { color:var(--accent); font-weight:700; }
.toc-card .toc-list { padding:0 12px 12px; }
.glossary-list { padding:0 12px 12px; }
.glossary-count { color:var(--sub); font-size:10px; font-weight:500; }
.glossary-item { padding:10px 0; border-top:1px solid var(--line); overflow-wrap:anywhere; }
.margin-note { scroll-margin:12px; transition:background .2s,border-color .2s,box-shadow .2s; }
.margin-note-kind { display:block; margin-bottom:5px; color:var(--sub); font-size:9.5px;
  font-weight:750; line-height:1.4; }
.term-marker-wrap { position:relative; display:inline-block; margin-left:2px; vertical-align:super; line-height:0; }
.term-marker { display:inline-flex; align-items:center; justify-content:center; width:14px; height:14px;
  border:1px solid var(--accent); border-radius:50%; color:var(--accent); background:var(--card);
  padding:0; font-family:Georgia,serif; font-size:9px; font-weight:700; line-height:1;
  text-decoration:none; cursor:pointer; }
.term-marker:hover,.term-marker:focus-visible { color:#fff; background:var(--accent); outline:none; }
.term-marker-wrap:target .term-marker { box-shadow:0 0 0 3px var(--accent-soft); }
.term-popover { position:absolute; left:var(--term-popover-left,7px); top:var(--term-popover-top,0);
  z-index:130; display:none; width:min(300px,calc(100vw - 24px)); padding:12px 14px;
  border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--ink);
  box-shadow:0 10px 30px rgba(0,0,0,.16); text-align:left; white-space:normal;
  transform:translate(-50%,calc(-100% - 9px)); font-family:inherit; font-style:normal;
  font-weight:400; line-height:1.55; pointer-events:none; }
.term-popover.below { transform:translate(-50%,9px); }
.term-popover-term,.term-popover-definition,.term-popover-plain { display:block; }
.term-popover-term { color:var(--ink); font-size:13px; font-weight:750; }
.term-popover-definition { margin-top:3px; color:var(--sub); font-size:11.5px; }
.term-popover-plain { margin-top:6px; padding-top:6px; border-top:1px solid var(--line);
  color:var(--term-accent); font-size:11px; }
.term-popover-label { margin-right:6px; color:var(--sub); font-size:9.5px; font-weight:700; }
@media (hover:hover) and (pointer:fine) {
  .term-marker-wrap:hover .term-popover,.term-marker-wrap:focus-within .term-popover { display:block; }
}
.term-marker-wrap.is-open .term-popover { display:block; }
.margin-quote-label { margin-top:6px; color:var(--statement-accent); font-size:9.5px; font-weight:700; }
.margin-quote-original { margin-top:2px; color:var(--sub); font-family:"SF Mono",Monaco,Consolas,monospace;
  font-size:10.5px; line-height:1.55; overflow-wrap:anywhere; }
.margin-quote-translation { margin-top:3px; color:var(--ink); font-size:11.5px; line-height:1.6; }
.margin-note:target,.margin-note.is-highlighted { margin-left:-7px; margin-right:-7px; padding-left:7px;
  padding-right:7px; border-color:var(--statement-accent); background:var(--statement-bg);
  box-shadow:inset 3px 0 0 var(--statement-accent); }
.margin-citations { display:flex; align-items:baseline; flex-wrap:wrap; gap:4px; margin:5px 0 15px;
  color:var(--sub); font-size:11.5px; line-height:1.55; }
.margin-citations-label { margin-right:2px; }
.margin-cite { color:var(--statement-accent); font-weight:750; text-decoration:none; padding:0 2px; }
.margin-cite:hover,.margin-cite:focus-visible { text-decoration:underline; outline:none; }
.article-body h2 { scroll-margin-top:20px; }

@media (min-width:1240px) {
  .toc-card,.glossary-rail { top:72px; bottom:auto; width:210px !important; max-height:calc(100vh - 96px);
    overflow:auto; background:transparent; box-shadow:none; border-width:1px 0 0; border-radius:0; }
  .toc-card { left:max(18px,calc(50vw - 625px)); }
  .glossary-rail { right:max(18px,calc(50vw - 625px)); }
  .toc-heading,.glossary-heading { padding:10px 0 8px; cursor:default; border-bottom:1px solid var(--line); }
  .toc-heading::after,.glossary-heading::after { display:none; }
  .toc-card .toc-list,.glossary-list { padding:5px 0 0; }
  .toc-item { gap:5px; padding:7px 0; }
  .toc-num { min-width:18px; font-size:11px; }
  .toc-link { font-size:12px; line-height:1.45; }
}

/* 正文 */
.article-body { margin-bottom:32px; }
.article-body h2 { font-size:19px; font-weight:700; margin:28px 0 10px;
  line-height:1.4; color:var(--ink); }
.article-body h2:first-child { margin-top:0; }
.article-body p { font-size:15.5px; color:var(--ink); line-height:1.85; margin:0 0 14px; }
.article-body p.transition-hook { margin:24px 0 8px; padding:13px 0 1px; border-top:1px dashed var(--line);
  color:var(--sub); font-size:14px; font-weight:600; line-height:1.65; }
.article-body .visual-title { margin:22px 0 10px; color:var(--ink); font-size:18px;
  font-weight:700; line-height:1.5; }

/* 来源媒体：只渲染抓取注册且与段落锚定的图片/视频 */
.source-media { margin:20px 0 24px; }
.source-media img { display:block; width:auto; max-width:100%; height:auto; margin:0 auto;
  background:transparent; border:0; border-radius:0; }
.source-media video { display:block; width:100%; max-width:100%; height:auto;
  max-height:560px; object-fit:contain; background:#000; border:1px solid var(--line); border-radius:6px; }
.source-media-embed { position:relative; width:100%; aspect-ratio:16 / 9; overflow:hidden; background:#000; }
.source-media-embed iframe { display:block; width:100%; height:100%; border:0; }
.source-media figcaption { margin-top:8px; color:var(--sub); font-size:12.5px; line-height:1.6;
  overflow-wrap:anywhere; }
.source-media .media-reader-note { max-width:680px; margin:10px auto 0; padding:10px 12px;
  border-left:3px solid var(--accent); background:var(--soft); color:var(--ink);
  font-size:13px; line-height:1.65; text-align:left; }
.ai-illustration { margin:24px 0 28px; }
.ai-illustration img { display:block; width:100%; height:auto; max-height:560px; object-fit:cover;
  border:1px solid var(--line); border-radius:4px; background:var(--card); }
.ai-illustration figcaption { margin-top:9px; color:var(--sub); font-size:12.5px; line-height:1.65; }
.ai-illustration .ai-label { display:inline-block; margin-right:7px; padding:2px 6px;
  border:1px solid var(--accent); color:var(--accent); font-size:10px; line-height:1.4; }

/* 统一注释系统：结构一致，颜色和层级表达不同用途 */
.art-annotation { margin:16px 0; min-width:0; font-size:14.5px; line-height:1.75; }
.art-annotation-label,.art-mini-label { display:inline-block; color:var(--sub); font-size:10.5px;
  font-weight:700; line-height:1.4; letter-spacing:0; }
.art-annotation-label { margin-bottom:7px; padding:2px 6px; border:1px solid currentColor; border-radius:3px; }
.art-mini-label { margin-right:8px; white-space:nowrap; }

/* 类比：保留引用感，但不再用斜体冒充术语解释 */
.art-quote { border-left:3px solid var(--accent); background:var(--analogy-bg);
  border-radius:0 6px 6px 0; padding:11px 16px 12px; color:var(--ink); }
.art-quote .art-annotation-label { color:var(--accent); }
.art-analogy-copy { display:flex; align-items:baseline; gap:8px; min-width:0; }
.art-analogy-term { flex:0 0 auto; color:var(--sub); font-weight:650; }
.art-analogy-text { min-width:0; }

/* 名词解释：术语、定义、通俗理解形成固定层级 */
.art-note { padding:13px 15px; border:1px solid var(--line); border-radius:6px; background:var(--term-bg); }
.art-note .art-annotation-label { color:var(--term-accent); }
.art-concept-head { display:flex; align-items:center; gap:9px; margin-bottom:5px; }
.art-concept-head .art-annotation-label { margin:0; flex:0 0 auto; }
.art-concept-term { color:var(--ink); font-size:15px; font-weight:750; }
.art-concept-definition { color:var(--ink); }
.art-concept-plain { margin-top:8px; padding-top:7px; border-top:1px solid var(--line); color:var(--sub); font-size:13px; }
.art-concept-plain .art-mini-label { color:var(--term-accent); }

/* 原文引文：英文原句与中文释义属于同一个来源引用组件 */
.art-archive { padding:13px 15px 12px; border-left:3px solid var(--statement-accent);
  border-radius:0 6px 6px 0; background:var(--statement-bg); }
.art-archive .art-annotation-label { color:var(--statement-accent); }
.art-statement-row { display:grid; grid-template-columns:76px minmax(0,1fr); gap:10px;
  padding:4px 0; min-width:0; }
.art-statement-row + .art-statement-row { margin-top:7px; padding-top:9px; border-top:1px solid var(--line); }
.art-statement-row .art-mini-label { color:var(--statement-accent); padding-top:1px; }
.art-orig { color:var(--sub); font-family:"SF Mono",Monaco,Consolas,monospace;
  font-size:12.5px; line-height:1.7; overflow-wrap:anywhere; }
.art-trans { color:var(--ink); font-size:14.5px; }

/* 实验拆解：默认折叠，完整条件仍可随时展开核对 */
.experiment-block { margin:22px 0; padding:0; border-top:2px solid var(--ink); border-bottom:1px solid var(--line); }
.experiment-block summary { display:flex; align-items:center; gap:10px; padding:13px 0; cursor:pointer;
  list-style:none; color:var(--ink); }
.experiment-block summary::-webkit-details-marker { display:none; }
.experiment-block summary::before { content:"实验细节"; color:var(--accent); font-size:11px; font-weight:700;
  padding:2px 7px; border:1px solid var(--accent); border-radius:3px; flex-shrink:0; }
.experiment-block summary::after { content:"+"; margin-left:auto; color:var(--accent); font-size:18px; }
.experiment-block[open] summary::after { content:"−"; }
.experiment-body { padding:0 0 16px; }
.experiment-title { font-size:16px; font-weight:700; line-height:1.45; }
.experiment-question { font-size:14.5px; font-weight:600; margin:0 0 12px; }
.experiment-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); border-top:1px solid var(--line); }
.experiment-field { padding:10px 12px 10px 0; border-bottom:1px solid var(--line); min-width:0; }
.experiment-field:nth-child(even) { padding-left:12px; border-left:1px solid var(--line); }
.experiment-label { color:var(--sub); font-size:11px; margin-bottom:3px; }
.experiment-value { font-size:13.5px; line-height:1.65; overflow-wrap:anywhere; }
.experiment-result { margin:12px 0 0; padding:10px 14px; border-left:3px solid var(--ok); background:var(--ok-soft); font-size:14px; }
.experiment-limit { margin-top:9px; padding:9px 12px; border-left:3px solid var(--warn); background:var(--warn-soft); color:var(--sub); font-size:13px; line-height:1.65; }

/* 案例叙事：只呈现有证据的事件链 */
.case-story { margin:22px 0; padding:16px 0; border-top:2px solid var(--ink); border-bottom:1px solid var(--line); }
.case-title { font-size:16px; font-weight:700; margin-bottom:6px; }
.case-setup { font-size:14px; color:var(--sub); margin-bottom:14px; }
.case-beats { border-left:2px solid var(--line); margin-left:11px; padding-left:20px; }
.case-beat { position:relative; padding:0 0 16px; }
.case-beat:last-child { padding-bottom:4px; }
.case-beat::before { content:""; position:absolute; left:-27px; top:4px; width:12px; height:12px;
  border-radius:50%; background:var(--card); border:2px solid var(--accent); }
.case-beat-label { color:var(--accent); font-size:12px; font-weight:700; margin-bottom:2px; }
.case-beat-text { font-size:14px; line-height:1.7; }
.case-source-quote { margin:6px 0 0; color:var(--sub); font-size:12.5px; font-style:italic; }
.case-outcome { margin-top:12px; padding:9px 12px; border-left:3px solid var(--ok); background:var(--ok-soft); font-size:14px; font-weight:600; }
.case-boundary { margin-top:8px; padding-left:12px; border-left:3px solid var(--warn); color:var(--sub); font-size:13px; line-height:1.65; }
.case-provenance { margin-top:9px; color:var(--sub); font-size:11px; }

/* 对比项：外层主题纵向，明确的平级对象可在组内并排。 */
.comparison-list { margin:14px 0; border-top:1px solid var(--line); }
.comparison-row { padding:14px 0 15px; border-bottom:1px solid var(--line); }
.comparison-topic { margin-bottom:10px; color:var(--ink); font-size:15px; font-weight:750; }
.comparison-pairs { margin:0; }
.comparison-pair + .comparison-pair { margin-top:10px; }
.comparison-pair dt { margin:0 0 3px; color:var(--sub); font-size:11px; font-weight:750; }
.comparison-pair dd { margin:0; color:var(--ink); font-size:14px; line-height:1.65; overflow-wrap:anywhere; }
.comparison-list.paired .comparison-pairs { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
.comparison-list.paired .comparison-pair { min-width:0; padding:11px 12px; border:1px solid var(--line);
  border-radius:4px; background:var(--accent-soft); }
.comparison-list.paired .comparison-pair + .comparison-pair { margin-top:0; }
.comparison-pair.cmp-tone-primary { border-color:var(--metric-primary); background:var(--metric-primary-soft); }
.comparison-pair.cmp-tone-primary dt { color:var(--metric-primary); }
.comparison-pair.cmp-tone-baseline { border-color:var(--metric-baseline); background:var(--metric-baseline-soft); }
.comparison-pair.cmp-tone-baseline dt { color:var(--metric-baseline); }
.comparison-pair.cmp-tone-warning { border-color:var(--warn); background:var(--warn-soft); }
.comparison-pair.cmp-tone-warning dt { color:var(--warn); }
.comparison-pair.cmp-tone-danger { border-color:var(--bad); background:var(--bad-soft); }
.comparison-pair.cmp-tone-danger dt { color:var(--bad); }
.cmp-scroll { width:100%; overflow-x:auto; margin:14px 0; -webkit-overflow-scrolling:touch; }
.cmp-table { width:100%; table-layout:fixed; border-collapse:collapse; font-size:14px; background:var(--card);
  border:1px solid var(--line); border-radius:6px; overflow:hidden; }
.cmp-table th { background:var(--accent-soft); text-align:left; padding:10px 14px;
  color:var(--accent); font-weight:700; border-top:3px solid var(--metric-baseline);
  border-bottom:1px solid var(--line); font-size:13px; }
.cmp-table th:first-child { width:18%; }
.cmp-table td { padding:11px 14px; border-bottom:1px solid var(--line); line-height:1.55; vertical-align:top; overflow-wrap:anywhere; }
.cmp-table tr:last-child td { border-bottom:none; }
.cmp-table tbody tr:nth-child(even) td { background:var(--quote-bg); }
.cmp-table tbody tr:hover td { background:var(--metric-primary-soft); }
.cmp-table th.cmp-tone-primary,.cmp-table td.cmp-tone-primary { background:var(--metric-primary-soft); }
.cmp-table th.cmp-tone-primary { color:var(--metric-primary); border-top-color:var(--metric-primary); }
.cmp-table th.cmp-tone-baseline,.cmp-table td.cmp-tone-baseline { background:var(--metric-baseline-soft); }
.cmp-table th.cmp-tone-baseline { color:var(--metric-baseline); border-top-color:var(--metric-baseline); }
.cmp-table th.cmp-tone-warning,.cmp-table td.cmp-tone-warning { background:var(--warn-soft); }
.cmp-table th.cmp-tone-warning { color:var(--warn); border-top-color:var(--warn); }
.cmp-table th.cmp-tone-danger,.cmp-table td.cmp-tone-danger { background:var(--bad-soft); }
.cmp-table th.cmp-tone-danger { color:var(--bad); border-top-color:var(--bad); }

/* 前后变化：同一指标的旧值、新值与变化方向。 */
.delta-table { margin:18px 0 24px; border-top:1px solid var(--line); }
.delta-head,.delta-row { display:grid; grid-template-columns:minmax(110px,1.1fr) minmax(0,1.9fr) minmax(108px,.8fr);
  gap:12px 18px; align-items:center; }
.delta-head { padding:9px 12px; color:var(--sub); font-size:10.5px; font-weight:750; }
.delta-row { padding:13px 12px; border-bottom:1px solid var(--line); }
.delta-label { color:var(--ink); font-size:13.5px; font-weight:700; line-height:1.45; }
.delta-values { display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); gap:8px; align-items:center; min-width:0; }
.delta-value { min-width:0; padding:8px 10px; border-radius:5px; background:var(--quote-bg); }
.delta-value.current { background:var(--metric-primary-soft); }
.delta-value-label { display:block; color:var(--sub); font-size:9.5px; font-weight:700; }
.delta-value strong { display:block; margin-top:2px; color:var(--ink); font-size:13px; overflow-wrap:anywhere; }
.delta-arrow { color:var(--sub); font-size:16px; }
.delta-change { justify-self:start; padding:5px 8px; border-radius:4px; background:var(--quote-bg);
  color:var(--sub); font-size:12px; font-weight:750; line-height:1.4; }
.delta-change.tone-primary { background:var(--metric-primary-soft); color:var(--metric-primary); }
.delta-change.tone-baseline { background:var(--metric-baseline-soft); color:var(--metric-baseline); }
.delta-change.tone-warning { background:var(--warn-soft); color:var(--warn); }
.delta-change.tone-danger { background:var(--bad-soft); color:var(--bad); }
.delta-change .delta-direction { margin-right:3px; }
.delta-boundary,.status-boundary,.decision-boundary { margin-top:10px; padding:9px 11px; border-left:3px solid var(--warn);
  background:var(--quote-bg); color:var(--sub); font-size:11.5px; line-height:1.6; }

/* 状态矩阵：颜色只表示固定语义状态，横向空间不足时滚动。 */
.status-matrix-scroll { width:100%; overflow-x:auto; margin:18px 0 8px; -webkit-overflow-scrolling:touch; }
.status-matrix { width:100%; min-width:520px; border-collapse:separate; border-spacing:4px; table-layout:fixed; }
.status-matrix th { padding:7px 9px; color:var(--sub); font-size:11px; font-weight:750; text-align:center; }
.status-matrix th:first-child { width:24%; text-align:left; }
.status-matrix td { padding:9px 10px; border:1px solid var(--line); border-radius:5px; background:var(--quote-bg);
  color:var(--ink); font-size:12px; line-height:1.45; text-align:center; overflow-wrap:anywhere; }
.status-matrix td:first-child { background:var(--card); font-weight:700; text-align:left; }
.status-matrix td.tone-primary { border-color:var(--metric-primary); background:var(--metric-primary-soft); color:var(--metric-primary); }
.status-matrix td.tone-baseline { border-color:var(--metric-baseline); background:var(--metric-baseline-soft); color:var(--metric-baseline); }
.status-matrix td.tone-warning { border-color:var(--warn); background:var(--warn-soft); color:var(--warn); }
.status-matrix td.tone-danger { border-color:var(--bad); background:var(--bad-soft); color:var(--bad); }
.status-caption { margin-top:7px; color:var(--sub); font-size:10.5px; line-height:1.55; }

/* 条件决策表：把来源规则与编辑建议分列，避免把建议伪装成事实。 */
.decision-table { margin:18px 0 24px; border-top:1px solid var(--line); }
.decision-head,.decision-row { display:grid; grid-template-columns:minmax(0,1.15fr) minmax(0,1fr) minmax(0,1.25fr); gap:0; }
.decision-head { color:var(--sub); font-size:10.5px; font-weight:750; }
.decision-head span { padding:9px 12px; }
.decision-row { position:relative; border-bottom:1px solid var(--line); }
.decision-cell { min-width:0; padding:13px 12px; color:var(--ink); font-size:12.5px; line-height:1.6; overflow-wrap:anywhere; }
.decision-cell + .decision-cell { border-left:1px solid var(--line); }
.decision-cell.action { background:var(--accent-soft); }
.decision-row.tone-primary { border-left:3px solid var(--metric-primary); }
.decision-row.tone-baseline { border-left:3px solid var(--metric-baseline); }
.decision-row.tone-warning { border-left:3px solid var(--warn); }
.decision-row.tone-danger { border-left:3px solid var(--bad); }

/* 多指标基准：先切换读者问题，再在同一模型内比较两套系统。 */
.metric-bars { margin:18px 0 24px; padding:18px; border:1px solid var(--line);
  border-radius:8px; background:var(--card); }
.mb-tabs { display:grid; grid-template-columns:repeat(auto-fit,minmax(128px,1fr)); gap:4px;
  padding:4px; border:1px solid var(--line); border-radius:6px; background:var(--bg); }
.mb-tab { min-height:38px; padding:7px 10px; border:0; border-radius:4px; background:transparent;
  color:var(--sub); font:inherit; font-size:12.5px; font-weight:650; line-height:1.35; cursor:pointer; }
.mb-tab:hover { color:var(--ink); }
.mb-tab.active { color:#fff; background:var(--accent); }
.metric-bars.metric-bars-ready .mb-panel[hidden] { display:none; }
.mb-panel { padding-top:16px; }
.mb-question { margin:0; color:var(--ink); font-size:16px; font-weight:750; line-height:1.5; }
.mb-metric { margin:4px 0 13px; color:var(--sub); font-size:11.5px; line-height:1.55; }
.mb-model { display:grid; grid-template-columns:minmax(112px,.72fr) minmax(0,2fr) auto;
  gap:10px 16px; align-items:center; padding:13px 0; border-top:1px solid var(--line); }
.mb-model-name { color:var(--ink); font-size:13.5px; font-weight:700; line-height:1.4; }
.mb-pair { display:grid; gap:7px; min-width:0; }
.mb-line { display:grid; grid-template-columns:68px minmax(80px,1fr) minmax(82px,auto);
  gap:8px; align-items:center; min-width:0; }
.mb-series { display:flex; align-items:center; gap:5px; color:var(--sub); font-size:10.5px;
  font-weight:650; overflow-wrap:anywhere; }
.mb-series::before { content:""; width:7px; height:7px; border-radius:2px; flex:0 0 auto; }
.mb-line.primary .mb-series { color:var(--metric-primary); }
.mb-line.primary .mb-series::before { background:var(--metric-primary); }
.mb-line.baseline .mb-series { color:var(--metric-baseline); }
.mb-line.baseline .mb-series::before { background:var(--metric-baseline); }
.mb-track { height:10px; overflow:hidden; border-radius:3px; background:var(--metric-primary-soft); }
.mb-line.baseline .mb-track { background:var(--metric-baseline-soft); }
.mb-fill { display:block; width:var(--bar-width); min-width:3px; height:100%; border-radius:2px;
  background:var(--metric-primary); }
.mb-line.baseline .mb-fill { background:var(--metric-baseline); }
.mb-value { color:var(--ink); font-size:11.5px; font-variant-numeric:tabular-nums; text-align:right;
  white-space:nowrap; }
.mb-ratio { min-width:58px; padding:3px 7px; border:1px solid var(--metric-primary);
  border-radius:4px; background:var(--metric-primary-soft); color:var(--metric-primary);
  font-size:14px; font-weight:800; font-variant-numeric:tabular-nums; text-align:center; }
.mb-note { margin-top:8px; padding-top:11px; border-top:1px solid var(--line); color:var(--sub);
  font-size:11px; line-height:1.6; }
.mb-boundary { margin-top:8px; padding:9px 11px; border-left:3px solid var(--warn);
  background:var(--quote-bg); color:var(--sub); font-size:12px; line-height:1.6; }

/* 单口径排名条：比较一组同单位数值，不伪装成双方案指标。 */
.rank-bars { margin:18px 0 24px; padding:18px; border:1px solid var(--line);
  border-radius:8px; background:var(--card); }
.rb-tabs { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:13px; }
.rb-tab { min-height:34px; padding:6px 12px; border:1px solid var(--line); border-radius:5px;
  background:var(--bg); color:var(--sub); font:inherit; font-size:12.5px; font-weight:650; cursor:pointer; }
.rb-tab.active { border-color:var(--accent); background:var(--accent-soft); color:var(--ink); }
.rank-bars.rank-bars-ready .rb-panel[hidden] { display:none; }
.rb-question { margin:0 0 10px; color:var(--sub); font-size:12.5px; line-height:1.6; }
.rb-row { display:grid; grid-template-columns:minmax(92px,.72fr) minmax(100px,2.4fr) minmax(52px,auto);
  gap:10px 14px; align-items:center; padding:10px 0; border-top:1px solid var(--line); }
.rb-label { color:var(--ink); font-size:13.5px; font-weight:650; line-height:1.4; overflow-wrap:anywhere; }
.rb-track { height:12px; overflow:hidden; border-radius:3px; background:var(--quote-bg); }
.rb-fill { display:block; width:var(--bar-width); min-width:3px; height:100%; border-radius:2px;
  background:var(--metric-primary); }
.rb-panel.tone-baseline .rb-fill { background:var(--metric-baseline); }
.rb-panel.tone-warning .rb-fill { background:var(--warn); }
.rb-panel.tone-danger .rb-fill { background:var(--bad); }
.rb-value { color:var(--ink); font-size:13px; font-weight:750; font-variant-numeric:tabular-nums;
  text-align:right; white-space:nowrap; }
.rb-note { grid-column:2 / -1; margin-top:-6px; color:var(--sub); font-size:10.5px; line-height:1.5; }
.rb-caption { margin-top:11px; padding-top:10px; border-top:1px solid var(--line); color:var(--sub);
  font-size:11px; line-height:1.6; }
.rb-boundary { margin-top:8px; padding:9px 11px; border-left:3px solid var(--warn);
  background:var(--warn-soft); color:var(--sub); font-size:11.5px; line-height:1.6; }

/* 流程图 */
.flow { display:flex; flex-direction:column; align-items:center; margin:14px 0; }
.flow-step { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:12px 18px; width:100%; max-width:460px; display:flex; gap:12px;
  align-items:center; font-size:14px; }
.flow-num { background:var(--accent); color:#fff; width:24px; height:24px; border-radius:50%;
  display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:600; flex-shrink:0; }
.flow-copy { min-width:0; display:flex; flex-direction:column; gap:2px; }
.flow-title { color:var(--ink); font-weight:650; }
.flow-description { color:var(--sub); font-size:13px; line-height:1.55; }
.flow-arrow { color:var(--sub); font-size:18px; padding:4px 0; }

/* 步骤探索器：复杂流程一次聚焦一个阶段，普通短流程仍用上方静态样式。 */
.flow-stepper { margin:18px 0 24px; padding:18px; border:1px solid var(--line); border-radius:8px; background:var(--card); }
.fs-nav { display:grid; grid-template-columns:repeat(auto-fit,minmax(92px,1fr)); gap:6px; margin-bottom:16px; }
.fs-tab { min-height:42px; padding:7px 9px; border:1px solid var(--line); border-radius:5px; background:var(--bg);
  color:var(--sub); font:inherit; font-size:11.5px; font-weight:650; line-height:1.35; cursor:pointer; }
.fs-tab.active { border-color:var(--accent); background:var(--accent-soft); color:var(--accent); }
.flow-stepper.flow-stepper-ready .fs-panel:not(.active) { display:none; }
.fs-panel { min-height:132px; padding:17px 18px; border-left:3px solid var(--accent); background:var(--quote-bg); }
.fs-kicker { color:var(--accent); font-size:10.5px; font-weight:800; }
.fs-title { margin-top:4px; color:var(--ink); font-size:17px; font-weight:780; line-height:1.45; }
.fs-description { margin-top:7px; color:var(--sub); font-size:13.5px; line-height:1.7; }
.fs-result { margin-top:10px; padding-top:9px; border-top:1px solid var(--line); color:var(--ink); font-size:12.5px; line-height:1.6; }
.fs-result strong { color:var(--metric-primary); }
.fs-controls { display:flex; justify-content:space-between; gap:10px; margin-top:12px; }
.fs-control { width:34px; height:34px; border:1px solid var(--line); border-radius:5px; background:var(--card);
  color:var(--accent); font:inherit; font-size:18px; cursor:pointer; }
.fs-control:disabled { opacity:.35; cursor:default; }
.fs-caption { margin-top:10px; color:var(--sub); font-size:10.5px; line-height:1.55; }

/* 策略切换器：平行方案逐项展开，避免把长说明压进宽表格。 */
.strategy-tabs { margin:18px 0 24px; padding:18px; border:1px solid var(--line); border-radius:8px; background:var(--card); }
.st-instruction { margin:0 0 13px; color:var(--sub); font-size:13px; line-height:1.65; }
.st-nav { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:7px; margin-bottom:14px; }
.st-tab { min-height:46px; padding:8px 10px; border:1px solid var(--line); border-radius:6px; background:var(--bg);
  color:var(--sub); font:inherit; font-size:12px; font-weight:700; line-height:1.35; cursor:pointer; text-align:left; }
.st-tab::before { content:attr(data-step); display:block; margin-bottom:2px; color:var(--st-tone,var(--accent));
  font-size:9px; font-weight:850; letter-spacing:0; }
.st-tab:hover { border-color:var(--st-tone,var(--accent)); color:var(--ink); }
.st-tab.active { border-color:var(--st-tone,var(--accent)); background:var(--st-soft,var(--accent-soft)); color:var(--ink);
  box-shadow:inset 0 -3px 0 var(--st-tone,var(--accent)); }
.st-tab.tone-primary,.st-panel.tone-primary { --st-tone:var(--metric-primary); --st-soft:var(--accent-soft); }
.st-tab.tone-baseline,.st-panel.tone-baseline { --st-tone:var(--metric-baseline); --st-soft:var(--metric-baseline-soft); }
.st-tab.tone-warning,.st-panel.tone-warning { --st-tone:var(--warn); --st-soft:var(--warn-soft); }
.st-tab.tone-danger,.st-panel.tone-danger { --st-tone:var(--bad); --st-soft:var(--bad-soft); }
.strategy-tabs.strategy-tabs-ready .st-panel:not(.active) { display:none; }
.st-panel { padding:18px; border-top:3px solid var(--st-tone,var(--accent)); background:var(--st-soft,var(--quote-bg)); }
.st-panel-head { display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin-bottom:13px; }
.st-panel-title { color:var(--ink); font-size:18px; font-weight:800; line-height:1.4; }
.st-panel-target { color:var(--st-tone,var(--accent)); font-size:11.5px; font-weight:750; text-align:right; }
.st-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.st-item { min-width:0; padding:12px 13px; border:1px solid var(--line); border-radius:6px; background:var(--card); }
.st-item.open { grid-column:1 / -1; border-left:3px solid var(--warn); }
.st-label { display:block; margin-bottom:4px; color:var(--sub); font-size:9.5px; font-weight:800; }
.st-value { color:var(--ink); font-size:13px; line-height:1.65; }
.st-boundary { margin-top:12px; padding-top:10px; border-top:1px solid var(--line); color:var(--sub); font-size:11px; line-height:1.6; }

/* 资格漏斗：宽度逐级收窄，强调每关都会淘汰一部分对象。 */
.funnel-flow { margin:18px 0 24px; padding:18px; border:1px solid var(--line);
  border-radius:8px; background:var(--card); }
.ff-entry { width:100%; padding:10px 14px; border-radius:5px; background:var(--quote-bg);
  color:var(--ink); font-size:14px; font-weight:750; text-align:center; }
.ff-arrow { color:var(--sub); font-size:18px; line-height:1; padding:6px 0; text-align:center; }
.ff-stage { position:relative; width:var(--funnel-width); min-width:42%; margin:0 auto;
  padding:11px 14px; border:2px solid var(--accent); border-radius:6px; background:var(--card); text-align:center; }
.ff-stage::before,.ff-stage::after { content:""; position:absolute; top:50%; width:22px;
  border-top:1px solid var(--warn); }
.ff-stage::before { right:100%; }
.ff-stage::after { left:100%; }
.ff-label { display:block; color:var(--accent); font-size:14px; font-weight:780; line-height:1.45; }
.ff-description { display:block; margin-top:3px; color:var(--sub); font-size:11.5px; line-height:1.5; }
.ff-exit { width:min(92%,620px); margin:6px auto 0; color:var(--warn); font-size:10.5px;
  line-height:1.5; text-align:center; }
.ff-caption { margin-top:13px; padding-top:10px; border-top:1px solid var(--line); color:var(--sub);
  font-size:11px; line-height:1.6; }

/* 多层结构：摘要保持可扫读，细节按需展开，不把架构压成大表格。 */
.layer-stack { margin:16px 0 24px; border-top:1px solid var(--line); }
.layer-item { border-bottom:1px solid var(--line); background:var(--card); }
.layer-item summary { list-style:none; display:grid; grid-template-columns:32px minmax(0,1fr) auto;
  gap:10px 12px; align-items:center; padding:13px 4px; cursor:pointer; }
.layer-item summary::-webkit-details-marker { display:none; }
.layer-index { display:flex; align-items:center; justify-content:center; width:26px; height:26px;
  border-radius:4px; background:var(--accent-soft); color:var(--accent); font-size:11px; font-weight:800; }
.layer-item:nth-child(4n+2) .layer-index { background:var(--metric-primary-soft); color:var(--metric-primary); }
.layer-item:nth-child(4n+3) .layer-index { background:var(--bias-bg); color:var(--warn); }
.layer-item:nth-child(4n+4) .layer-index { background:var(--term-bg); color:var(--term-accent); }
.layer-heading { min-width:0; }
.layer-label { display:block; color:var(--sub); font-size:10.5px; font-weight:700; line-height:1.4; }
.layer-title { display:block; color:var(--ink); font-size:14.5px; font-weight:750; line-height:1.45; }
.layer-toggle { color:var(--accent); font-size:17px; line-height:1; }
.layer-toggle::before { content:"+"; }
.layer-item[open] .layer-toggle::before { content:"−"; }
.layer-body { margin:0 4px 0 42px; padding:0 0 14px; color:var(--sub); font-size:13px; line-height:1.65; }
.layer-points { margin:7px 0 0; padding-left:18px; color:var(--ink); }
.layer-points li + li { margin-top:3px; }
.layer-caption { margin-top:10px; padding-left:12px; border-left:3px solid var(--warn);
  color:var(--sub); font-size:11.5px; line-height:1.6; }

/* 统计 */
.stat-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; margin:14px 0; }
.stat-card { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:18px; text-align:center; }
.stat-val { font-size:24px; font-weight:700; color:var(--accent); }
.stat-label { font-size:13px; color:var(--sub); margin-top:4px; }
.stat-card.tone-primary { border-top:3px solid var(--metric-primary); background:var(--metric-primary-soft); }
.stat-card.tone-primary .stat-val { color:var(--metric-primary); }
.stat-card.tone-baseline { border-top:3px solid var(--metric-baseline); background:var(--metric-baseline-soft); }
.stat-card.tone-baseline .stat-val { color:var(--metric-baseline); }
.stat-card.tone-warning { border-top:3px solid var(--warn); background:var(--warn-soft); }
.stat-card.tone-warning .stat-val { color:var(--warn); }
.stat-card.tone-danger { border-top:3px solid var(--bad); background:var(--bad-soft); }
.stat-card.tone-danger .stat-val { color:var(--bad); }

/* 时间线 */
.timeline { border-left:2px solid var(--accent); padding-left:20px; margin:14px 0; }
.tl-event { position:relative; margin-bottom:16px; }
.tl-event::before { content:""; position:absolute; left:-27px; top:5px; width:12px; height:12px;
  background:var(--accent); border-radius:50%; border:2px solid var(--bg); }
.tl-time { font-size:13px; font-weight:600; color:var(--accent); margin-bottom:2px; }
.tl-body { font-size:14px; line-height:1.65; }
.tl-title { display:block; color:var(--ink); font-weight:700; }
.tl-description { display:block; color:var(--sub); margin-top:2px; }

/* 时间拖动器：时间节点较多且每次只需理解一个阶段时使用。 */
.timeline-scrubber { margin:18px 0 24px; padding:18px; border:1px solid var(--line); border-radius:8px; background:var(--card); }
.ts-stage { min-height:142px; padding:16px 18px; border-left:3px solid var(--metric-baseline); background:var(--quote-bg); }
.ts-time { color:var(--metric-baseline); font-size:12px; font-weight:800; }
.ts-title { margin-top:5px; color:var(--ink); font-size:17px; font-weight:780; line-height:1.45; }
.ts-description { margin-top:7px; color:var(--sub); font-size:13.5px; line-height:1.7; }
.ts-range { width:100%; margin:18px 0 5px; accent-color:var(--accent); cursor:pointer; }
.ts-ticks { display:flex; justify-content:space-between; gap:6px; color:var(--sub); font-size:9.5px; line-height:1.35; }
.ts-ticks span { max-width:25%; text-align:center; overflow-wrap:anywhere; }
.ts-fallback { margin:14px 0 0; padding-left:20px; color:var(--sub); font-size:12px; line-height:1.65; }
.timeline-scrubber.timeline-scrubber-ready .ts-fallback { display:none; }
.ts-caption { margin-top:13px; padding-top:10px; border-top:1px solid var(--line); color:var(--sub); font-size:10.5px; line-height:1.55; }

/* 机制互动：固定候选，切换不同选择模式 */
.interactive-compare { margin:18px 0 24px; padding:18px; border:1px solid var(--line);
  border-radius:8px; background:var(--card); }
.ic-instruction { color:var(--sub); font-size:13px; line-height:1.65; margin-bottom:12px; }
.ic-toggle { display:inline-flex; max-width:100%; padding:3px; gap:3px; border:1px solid var(--line);
  border-radius:6px; background:var(--bg); margin-bottom:15px; }
.ic-toggle button { min-height:34px; padding:6px 12px; border:0; border-radius:4px; background:transparent;
  color:var(--sub); font:inherit; font-size:13px; font-weight:600; cursor:pointer; white-space:normal; }
.ic-toggle button:hover { color:var(--ink); }
.ic-toggle button.active { color:#fff; background:var(--accent); }
.ic-prompt { padding:11px 13px; border-left:3px solid var(--accent); background:var(--accent-soft);
  font-family:"SF Mono",Monaco,Consolas,monospace; font-size:13px; line-height:1.6;
  overflow-wrap:anywhere; margin-bottom:12px; }
.ic-state[hidden] { display:none; }
.ic-state-meta { display:flex; flex-wrap:wrap; align-items:baseline; justify-content:space-between;
  gap:6px 12px; margin-bottom:9px; }
.ic-state-label { color:var(--ink); font-size:14px; font-weight:700; }
.ic-state-signal { color:var(--accent); font-size:12px; font-weight:600; }
.ic-options { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:8px; }
.ic-option { min-width:0; padding:10px 12px; border:1px solid var(--line); border-radius:6px;
  background:var(--bg); }
.ic-option.selected { border-color:var(--accent); background:var(--accent-soft);
  box-shadow:inset 0 0 0 1px var(--accent); }
.ic-option-name { font-size:14px; font-weight:650; overflow-wrap:anywhere; }
.ic-option-note { color:var(--sub); font-size:11px; line-height:1.5; margin-top:2px; }
.ic-option.selected .ic-option-name::after { content:"已选择"; display:inline-block; margin-left:7px;
  padding:1px 5px; border-radius:3px; background:var(--accent); color:#fff; font-size:9px;
  font-weight:700; vertical-align:2px; }
.ic-state-note { margin-top:10px; color:var(--sub); font-size:12.5px; line-height:1.65; }
.ic-takeaway { margin-top:13px; padding-top:11px; border-top:1px solid var(--line);
  color:var(--ink); font-size:13px; line-height:1.65; }
.ic-caption { margin-top:8px; color:var(--sub); font-size:11px; line-height:1.55; }

/* 证据情景卡：把来源图表中的关系转成可操作问题 */
.scenario-calculator { margin:18px 0 24px; padding:18px; border:1px solid var(--line);
  border-radius:8px; background:var(--card); }
.sc-instruction { color:var(--sub); font-size:13px; line-height:1.65; margin-bottom:12px; }
.sc-tabs { display:inline-grid; grid-auto-flow:column; grid-auto-columns:minmax(108px,1fr); max-width:100%;
  border-bottom:1px solid var(--line); margin-bottom:14px; }
.sc-tabs button { min-height:42px; padding:8px 18px; border:0; border-bottom:2px solid transparent;
  background:transparent; color:var(--sub); font:inherit; font-size:14px; font-weight:650; cursor:pointer; }
.sc-tabs button:hover { color:var(--ink); }
.sc-tabs button.active { color:var(--ink); border-bottom-color:var(--accent); background:var(--accent-soft); }
.sc-platform[hidden] { display:none; }
.sc-metrics { display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); gap:16px 22px; }
.sc-metric { min-width:0; padding-top:10px; border-top:1px solid var(--line); }
.sc-metric-label { color:var(--sub); font-size:12.5px; line-height:1.45; }
.sc-metric-value { margin-top:4px; color:var(--ink); font-size:25px; font-weight:720; line-height:1.2; }
.sc-metric-note { margin-top:4px; color:var(--sub); font-size:10.5px; line-height:1.5; }
.sc-control { display:grid; grid-template-columns:minmax(150px,.85fr) minmax(220px,1.5fr) auto;
  gap:14px 20px; align-items:center; margin-top:20px; padding:17px 0; border-top:1px solid var(--line);
  border-bottom:1px solid var(--line); }
.sc-control-label { color:var(--ink); font-size:13.5px; font-weight:600; line-height:1.45; }
.sc-control input[type="range"] { width:100%; height:5px; border-radius:999px; border:0;
  appearance:none; -webkit-appearance:none; background:var(--line); cursor:pointer; }
.sc-control input[type="range"]::-webkit-slider-thumb { width:18px; height:18px; border-radius:50%;
  border:0; -webkit-appearance:none; background:var(--accent); box-shadow:0 0 0 3px var(--accent-soft); }
.sc-control input[type="range"]::-moz-range-track { height:5px; border:0; border-radius:999px; background:var(--line); }
.sc-control input[type="range"]::-moz-range-progress { height:5px; border-radius:999px; background:var(--accent); }
.sc-control input[type="range"]::-moz-range-thumb { width:18px; height:18px; border:0; border-radius:50%;
  background:var(--accent); box-shadow:0 0 0 3px var(--accent-soft); }
.sc-input-value { min-width:72px; color:var(--warn); font-size:17px; font-weight:700; text-align:right; }
.sc-result { display:flex; align-items:baseline; justify-content:space-between; gap:16px;
  padding:18px 0 12px; }
.sc-result-label { color:var(--ink); font-size:14px; font-weight:650; }
.sc-result-value { color:var(--accent); font-size:30px; font-weight:760; line-height:1; }
.sc-formula { padding-top:10px; border-top:1px solid var(--line); color:var(--sub);
  font-size:11.5px; line-height:1.6; }
.sc-caption { margin-top:8px; color:var(--sub); font-size:11px; line-height:1.55; }

/* 定性容量曲线：解释连续变量的拐点，不伪造精确实验数值 */
.capacity-curve { margin:18px 0 24px; padding:18px; border:1px solid var(--line);
  border-radius:8px; background:var(--card); }
.cc-question { color:var(--ink); font-size:14px; font-weight:680; line-height:1.55; margin-bottom:16px; }
.cc-stage { position:relative; min-height:150px; margin:0 2px 12px; border-left:1px solid var(--line);
  border-bottom:1px solid var(--line); background:linear-gradient(to top,var(--accent-soft),transparent 58%); }
.cc-stage::before { content:""; position:absolute; inset:22px 7% 20px; border-radius:50% 50% 18% 18%;
  border-bottom:4px solid var(--accent); transform:perspective(220px) rotateX(-18deg); opacity:.85; }
.cc-points { position:absolute; inset:10px 5% 18px; display:flex; justify-content:space-between; align-items:flex-start; }
.cc-point { width:92px; color:var(--sub); font-size:11px; line-height:1.35; text-align:center; }
.cc-point:nth-child(2) { align-self:flex-end; color:var(--metric-primary); }
.cc-point-dot { display:block; width:11px; height:11px; margin:0 auto 5px; border-radius:50%;
  background:currentColor; box-shadow:0 0 0 4px var(--card); }
.cc-axis-y { position:absolute; left:7px; top:8px; color:var(--sub); font-size:10px; writing-mode:vertical-rl; }
.cc-axis-x { position:absolute; right:8px; bottom:3px; color:var(--sub); font-size:10px; }
.cc-control { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px 14px; align-items:center; }
.cc-control input { width:100%; accent-color:var(--accent); }
.cc-current { min-width:86px; color:var(--accent); font-size:13px; font-weight:700; text-align:right; }
.cc-result { margin-top:11px; padding:11px 13px; border-left:3px solid var(--accent); background:var(--accent-soft);
  color:var(--ink); font-size:13px; line-height:1.6; }
.cc-caption { margin-top:8px; color:var(--sub); font-size:11px; line-height:1.55; }

/* 成本账本：切换哪些成本被计入，避免把情景差异铺成大表格 */
.cost-ledger { margin:18px 0 24px; padding:18px; border:1px solid var(--line);
  border-radius:8px; background:var(--card); }
.cl-question { color:var(--sub); font-size:13px; line-height:1.65; margin-bottom:12px; }
.cl-tabs { display:flex; flex-wrap:wrap; gap:7px; margin-bottom:14px; }
.cl-tabs button { min-height:34px; padding:6px 11px; border:1px solid var(--line); border-radius:5px;
  background:var(--bg); color:var(--sub); font:inherit; font-size:12.5px; font-weight:650; cursor:pointer; }
.cl-tabs button.active { border-color:var(--accent); background:var(--accent-soft); color:var(--ink); }
.cl-panel[hidden] { display:none; }
.cl-included { display:flex; flex-wrap:wrap; gap:7px; margin-bottom:12px; }
.cl-cost { padding:4px 8px; border:1px solid var(--line); border-radius:4px; color:var(--sub);
  background:var(--bg); font-size:11.5px; }
.cl-cost.included { border-color:var(--warn); background:var(--warn-soft); color:var(--warn); }
.cl-verdict { color:var(--ink); font-size:17px; font-weight:720; line-height:1.45; }
.cl-explanation { margin-top:7px; color:var(--sub); font-size:13px; line-height:1.65; }
.cl-boundary { margin-top:13px; padding-top:11px; border-top:1px solid var(--line); color:var(--sub);
  font-size:11px; line-height:1.55; }

/* 上手卡 */
.action-card { background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:18px 22px; margin-bottom:20px; }
.action-card .action-items { list-style:none; padding:0; margin:0 0 12px; }
.action-card .action-items li { padding:6px 0; font-size:14px; border-bottom:1px dashed var(--line); }
.action-card .action-items li:last-child { border-bottom:none; }
.action-code { background:var(--bg); border:1px solid var(--line); border-radius:8px;
  padding:12px 16px; font-family:"SF Mono",Monaco,Consolas,monospace; font-size:13px;
  white-space:pre-wrap; overflow-x:auto; margin:0; }

/* 带走清单 */
.takeaway-list { display:flex; flex-direction:column; gap:8px; margin-bottom:20px; }
.takeaway-item { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:12px 18px; font-size:14.5px; display:flex; align-items:flex-start; gap:8px; }
.takeaway-check { color:var(--ok); font-size:16px; flex-shrink:0; margin-top:1px; }

/* 来源说明 */
.source-notes { font-size:13px; color:var(--sub); line-height:1.7; margin-bottom:20px; }
.evidence-links { display:block; margin-top:5px; font-size:12px; }
.evidence-links a { color:var(--accent); text-decoration:none; word-break:break-all; }
.evidence-links a:hover { text-decoration:underline; }
.number-story { margin:22px 0; border:1px solid var(--line); border-radius:6px; background:var(--card); padding:16px 18px; }
.number-story.stat { display:block; }
.number-main { font-size:32px; font-weight:800; color:var(--statement-accent); line-height:1.05; }
.number-main small { font-size:14px; margin-left:4px; color:var(--sub); }
.number-detail { min-width:0; margin-top:9px; }
.number-title { color:var(--ink); font-weight:750; margin-bottom:8px; }
.number-meta { display:block; margin:0; border-top:1px solid var(--line); }
.number-meta-item { min-width:0; padding:9px 0; border-bottom:1px solid var(--line); }
.number-meta dt,.number-compare-label { margin:0 0 3px; color:var(--sub); font-size:10px; font-weight:750; }
.number-meta dd { margin:0; color:var(--ink); font-size:12.5px; line-height:1.5; overflow-wrap:anywhere; }
.number-compare { display:block; margin-top:10px; }
.number-compare-item { min-width:0; padding:9px 10px; border:1px solid var(--line); border-radius:4px; background:var(--card); }
.number-compare-value { color:var(--ink); font-size:12.5px; line-height:1.55; overflow-wrap:anywhere; }
.number-compare-arrow { display:block; height:22px; color:var(--accent); font-size:17px; font-weight:800; line-height:22px; text-align:center; }
.number-boundary { margin-top:10px; padding:8px 10px; border-left:3px solid var(--warn); background:var(--warn-soft); color:var(--sub); font-size:12px; line-height:1.6; }
.number-story.compact { padding:0; overflow:hidden; }
.number-compact-head { display:grid; grid-template-columns:minmax(170px,auto) minmax(0,1fr); gap:0; align-items:stretch; }
.number-story.compact .number-main { display:flex; align-items:center; padding:20px 18px; background:var(--ink); color:var(--card); }
.number-story.compact .number-main small { color:color-mix(in srgb,var(--card) 72%,transparent); }
.number-story.compact .number-detail { margin-top:0; padding:17px 18px; align-self:center; }
.number-story.compact .number-title { margin:0 0 4px; }
.number-compact-meta { color:var(--sub); font-size:11.5px; line-height:1.55; }
.number-story.compact .number-boundary { margin:0; padding:10px 18px 11px; border:0; border-top:1px solid var(--line); background:var(--warn-soft); }
.listening-card { margin:24px 0 28px; border:1px solid var(--line); border-radius:6px; background:var(--card); overflow:hidden; }
.listening-head { padding:16px 18px 12px; border-bottom:1px solid var(--line); }
.listening-title { margin:0; color:var(--ink); font-size:16px; line-height:1.45; }
.listening-intro { margin:5px 0 0 !important; color:var(--sub) !important; font-size:13px !important; line-height:1.65 !important; }
.listening-tabs { display:flex; gap:0; overflow-x:auto; padding:0 12px; border-bottom:1px solid var(--line); scrollbar-width:thin; }
.listening-tab { flex:0 0 auto; min-height:42px; padding:9px 12px; border:0; border-bottom:2px solid transparent;
  background:transparent; color:var(--sub); font:inherit; font-size:12px; font-weight:650; cursor:pointer; }
.listening-tab.active { color:var(--accent); border-bottom-color:var(--accent); }
.listening-tab:focus-visible { outline:2px solid var(--accent); outline-offset:-2px; }
.listening-panel { padding:16px 18px 18px; }
.listening-panel[hidden] { display:none; }
.listening-panel audio { display:block; width:100%; height:40px; margin:0 0 15px; }
.listening-prompt { margin:0 0 14px; padding:10px 12px; border-left:3px solid var(--accent); background:var(--accent-soft);
  color:var(--ink); font-size:12.5px; line-height:1.65; overflow-wrap:anywhere; }
.listening-label { display:block; margin-bottom:3px; color:var(--sub); font-size:10px; font-weight:750; }
.listening-points { margin:0; padding-left:19px; color:var(--ink); font-size:13px; line-height:1.7; }
.listening-points li + li { margin-top:3px; }
.listening-lyrics { margin-top:12px; color:var(--sub); font-size:11.5px; }
.listening-lyrics summary { cursor:pointer; font-weight:650; }
.listening-lyrics p { margin:7px 0 0 !important; color:var(--sub) !important; font-size:11.5px !important;
  line-height:1.65 !important; white-space:pre-line; }
.listening-boundary { margin:0; padding:10px 18px 12px; border-top:1px solid var(--line); color:var(--sub); font-size:11px; line-height:1.6; }
.evidence-gallery { border-top:1px solid var(--line); margin-top:28px; padding-top:14px; }
.evidence-gallery summary { cursor:pointer; font-weight:700; font-size:13px; }
.evidence-gallery-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin-top:14px; }
.evidence-gallery figure { margin:0; border:1px solid var(--line); background:var(--card); overflow:hidden; border-radius:6px; }
.evidence-gallery img { width:100%; aspect-ratio:16/10; object-fit:cover; display:block; background:var(--quote-bg); }
.evidence-gallery figcaption { padding:9px 10px; color:var(--sub); font-size:11px; line-height:1.55; }
.evidence-gallery a { color:var(--accent); text-decoration:none; }
@media (max-width:560px) {
  .number-main { font-size:28px; }
  .number-compact-head { grid-template-columns:1fr; }
  .number-story.compact .number-main { min-height:68px; padding:15px 16px; }
  .number-story.compact .number-detail { padding:14px 16px; }
  .number-story.compact .number-boundary { padding:9px 16px 10px; }
  .comparison-list.paired .comparison-pairs { grid-template-columns:1fr; }
  .comparison-list.paired .comparison-pair + .comparison-pair { margin-top:0; }
  .cmp-table { font-size:12px; }
  .cmp-table th,.cmp-table td { padding:8px 7px; }
  .cmp-table th:first-child { width:20%; }
  .delta-head { display:none; }
  .delta-row { grid-template-columns:1fr; gap:9px; padding:14px 2px; }
  .delta-values { grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); }
  .decision-head { display:none; }
  .decision-row { grid-template-columns:1fr; padding:10px 0; }
  .decision-cell { position:relative; padding:5px 11px 5px 30px; }
  .decision-cell + .decision-cell { border-left:0; }
  .decision-cell::before { position:absolute; left:11px; color:var(--sub); font-size:9.5px; font-weight:750; }
  .decision-cell.condition::before { content:"当"; }
  .decision-cell.result::before { content:"则"; }
  .decision-cell.action::before { content:"做"; }
  .decision-cell.action { margin-top:4px; padding-top:8px; padding-bottom:8px; }
}

/* 回到顶部 */
.scroll-top { position:fixed; bottom:20px; right:20px; width:36px; height:36px;
  background:var(--accent); color:#fff; border-radius:50%; border:none; cursor:pointer;
  display:none; align-items:center; justify-content:center; font-size:18px; z-index:99;
  box-shadow:0 2px 8px rgba(0,0,0,.15); text-decoration:none; line-height:1; }
.scroll-top.show { display:flex; }

@media (max-width:480px) {
  .wrap { padding:68px 16px 48px; }
  .theme-switcher { position:static; justify-content:flex-end; margin:10px 12px 0; }
  header { margin-bottom:24px; }
  header h1 { font-size:23px; padding-right:0; }
  .toc-card,.glossary-rail { bottom:12px; }
  .toc-card { left:12px; }
  .glossary-rail { right:12px; }
  .toc-card[open],.glossary-rail[open] { width:calc(100vw - 24px); }
  .article-body h2 { font-size:18px; }
  .article-body p { font-size:15px; }
  .article-body p.transition-hook { font-size:13.5px; }
  .article-body .visual-title { font-size:17px; margin:20px 0 9px; }
  .quick-scan { margin-bottom:24px; padding:13px 14px 13px 16px; }
  .quick-scan-list { padding-left:18px; }
  .quick-scan-list li { font-size:14px; line-height:1.65; }
  .art-analogy-copy { display:block; }
  .art-analogy-term { display:block; margin-bottom:3px; }
  .art-statement-row { grid-template-columns:1fr; gap:2px; }
  .source-media { margin:16px 0 20px; }
  .source-media video { max-height:420px; border-radius:4px; }
  .listening-head,.listening-panel { padding-left:14px; padding-right:14px; }
  .listening-boundary { padding-left:14px; padding-right:14px; }
  .experiment-block summary { align-items:flex-start; }
  .experiment-grid { grid-template-columns:1fr; }
  .experiment-field:nth-child(even) { padding-left:0; border-left:none; }
  .interactive-compare { padding:15px; }
  .ic-toggle { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); width:100%; }
  .ic-options { grid-template-columns:1fr; }
  .scenario-calculator { padding:15px; }
  .capacity-curve,.cost-ledger { padding:15px; }
  .flow-stepper,.timeline-scrubber { padding:14px; }
  .strategy-tabs { padding:14px; }
  .st-nav { grid-template-columns:1fr; }
  .st-panel { padding:14px; }
  .st-panel-head { display:block; }
  .st-panel-target { margin-top:4px; text-align:left; }
  .st-grid { grid-template-columns:1fr; }
  .st-item.open { grid-column:auto; }
  .fs-nav { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .fs-panel,.ts-stage { min-height:0; padding:14px; }
  .ts-ticks span:nth-child(n+4):not(:last-child) { display:none; }
  .cc-stage { min-height:135px; }
  .cc-point { width:76px; font-size:10px; }
  .cl-tabs { display:grid; grid-template-columns:1fr 1fr; }
  .metric-bars,.rank-bars,.funnel-flow { padding:14px; }
  .layer-item summary { grid-template-columns:30px minmax(0,1fr) auto; gap:8px; }
  .layer-body { margin-left:38px; }
  .mb-tabs { grid-template-columns:1fr; }
  .mb-model { grid-template-columns:1fr auto; gap:8px 10px; }
  .mb-pair { grid-column:1 / -1; grid-row:2; }
  .mb-ratio { grid-column:2; grid-row:1; }
  .mb-line { grid-template-columns:60px minmax(72px,1fr) minmax(76px,auto); gap:6px; }
  .rb-tabs { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); }
  .rb-row { grid-template-columns:minmax(74px,.8fr) minmax(72px,2fr) minmax(46px,auto); gap:8px; }
  .rb-note { grid-column:1 / -1; margin-top:-4px; }
  .ff-stage { min-width:58%; }
  .ff-stage::before,.ff-stage::after { width:10px; }
  .sc-tabs { display:grid; grid-auto-flow:column; grid-auto-columns:1fr; width:100%; }
  .sc-metrics { grid-template-columns:1fr 1fr; gap:12px; }
  .sc-metric:last-child:nth-child(odd) { grid-column:1 / -1; }
  .sc-control { grid-template-columns:1fr auto; gap:10px 14px; }
  .sc-control input[type="range"] { grid-column:1 / -1; grid-row:2; }
  .sc-result-value { font-size:27px; }
  .fn-item { display:block; padding:7px 0; }
  .fn-num { margin-right:5px; }
  .verdict { margin:3px 0 0 4px; }
  .scroll-top { right:14px; bottom:14px; }
  .source-panel { margin-top:40px; }
  .source-row { grid-template-columns:1fr; gap:8px; padding:18px 0; }
  .source-title { font-size:14px; }
}
"""


# ── 组件渲染 ──────────────────────────────────────────────────


def _render_category_tags(tags: list) -> str:
    if not tags:
        return ""
    chips = "".join(f'<span class="category-tag">{_esc(t)}</span>' for t in tags)
    return f'<div class="category-tags">{chips}</div>'


def _render_source_panel(
    article: Article,
    further_reading: list,
    source_note: str,
    fact_check: list,
) -> str:
    """Render reader-facing provenance as a compact editorial footer."""
    primary_title = _esc(article.title or "主材料")
    meta = []
    if article.author:
        meta.append(f'<span>{_esc(article.author)}</span>')
    if article.date:
        meta.append(f'<time>{_esc(article.date)}</time>')
    if article.url:
        meta.append(
            f'<a href="{_esc(article.url)}" target="_blank" rel="noopener">查看主材料</a>'
        )
    source_body = (
        f'<span class="source-title">{primary_title}</span>'
        f'<span class="source-meta">{"".join(meta)}</span>'
    )
    rows = [
        '<div class="source-row"><div class="source-label">来源</div>'
        f'<div class="source-content">{source_body}</div></div>'
    ]

    links = []
    seen_urls = {str(article.url or "").rstrip("/")}
    candidates = list(further_reading or [])
    if not candidates:
        for item in fact_check or []:
            for evidence in item.get("evidence") or []:
                candidates.append({
                    "title": evidence.get("title") or evidence.get("publisher") or "延伸材料",
                    "url": evidence.get("url") or "",
                })
    for item in candidates:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        normalized = url.rstrip("/")
        if not url or not title or normalized in seen_urls:
            continue
        seen_urls.add(normalized)
        links.append(
            f'<a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(title)}</a>'
        )
    if links:
        rows.append(
            '<div class="source-row"><div class="source-label">延伸</div>'
            f'<div class="source-content source-links">{"".join(links[:5])}</div></div>'
        )
    if source_note:
        rows.append(
            '<div class="source-row"><div class="source-label">本站说明</div>'
            f'<div class="source-content"><p class="source-note">{_esc(source_note)}</p></div></div>'
        )
    return f'<footer class="source-panel">{"".join(rows)}</footer>'


def _render_bias_note(bias: str) -> str:
    if not bias:
        return ""
    return f'<div class="bias-note">{_esc(bias)}</div>'


def _render_rec_reason(reason: str) -> str:
    """推荐理由：一句话说明为什么值得读，不加标签，自然段。"""
    if not reason:
        return ""
    return f'<p class="rec-reason">{_esc(reason)}</p>'


def _section_dom_id(section: dict, index: int) -> str:
    """返回稳定且可安全用于 HTML/JS 的 ASCII 段落锚点。"""
    raw_id = str(section.get("id") or "").strip()
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", raw_id).strip("-_")
    if safe_id and re.match(r"^[A-Za-z]", safe_id):
        return safe_id
    return f"sec-{index}"


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


def _render_toc(sections: list) -> str:
    """Render a responsive off-flow table of contents."""
    if not sections:
        return ""
    items = []
    for i, s in enumerate(sections):
        title = _section_display_title(s)
        if not title:
            continue
        target_id = _section_dom_id(s, i)
        items.append(
            f'<li class="toc-item">'
            f'<span class="toc-num">{i+1}</span>'
            f'<a class="toc-link" data-section-target="{target_id}" href="#{target_id}" '
            f'onclick="var e=document.getElementById(\'{target_id}\');'
            f"if(e){{e.scrollIntoView({{behavior:'smooth'}})}}\""
            f'>{_esc(title)}</a></li>'
        )
    if not items:
        return ""
    return (
        '<details class="toc-card" data-reading-rail="toc">'
        '<summary class="toc-heading">\u76EE\u5F55</summary>'
        f'<ul class="toc-list">{"".join(items)}</ul>'
        '</details>'
    )


def _build_margin_rail(
    sections: list,
) -> tuple[str, dict[int, list[dict]], dict[int, list[dict]]]:
    """Build inline term popovers and a rail only for necessary source quotes."""
    items = []
    seen = set()
    term_count = 0
    quote_count = 0
    term_refs: dict[int, list[dict]] = {i: [] for i in range(len(sections))}
    citations: dict[int, list[dict]] = {i: [] for i in range(len(sections))}
    for index, section in enumerate(sections):
        for explainer in section.get("concept_explainers") or []:
            term = str(explainer.get("term") or "").strip()
            definition = str(explainer.get("definition") or "").strip()
            analogy = str(explainer.get("analogy") or "").strip()
            key = term.casefold()
            if not term or not definition or key in seen:
                continue
            seen.add(key)
            term_count += 1
            marker_id = f"term-marker-{term_count}"
            marker_section = next((
                section_index
                for section_index, candidate in enumerate(sections)
                if term in str(candidate.get("content") or "")
            ), None)
            if marker_section is not None:
                term_refs[marker_section].append({
                    "term": term,
                    "definition": definition,
                    "analogy": analogy,
                    "marker_id": marker_id,
                })

        archives = section.get("archive_original") or []
        if isinstance(archives, dict):
            archives = [archives]
        for archive in archives:
            if not isinstance(archive, dict):
                continue
            original = str(archive.get("original") or "").strip()
            translation = str(archive.get("translation") or "").strip()
            if not original and not translation:
                continue
            quote_count += 1
            note_id = f"margin-quote-{quote_count}"
            citations[index].append({"number": quote_count, "target_id": note_id})
            quote_parts = [
                f'<aside class="glossary-item margin-note margin-quote" id="{note_id}" tabindex="-1">',
                f'<span class="margin-note-kind">原文引文 {quote_count}</span>',
            ]
            if original:
                quote_parts.extend([
                    '<div class="margin-quote-label">英文原句</div>',
                    f'<div class="margin-quote-original" lang="en">{_esc(original)}</div>',
                ])
            if translation:
                quote_parts.extend([
                    '<div class="margin-quote-label">中文释义</div>',
                    f'<div class="margin-quote-translation">{_esc(translation)}</div>',
                ])
            quote_parts.append('</aside>')
            items.append("".join(quote_parts))
    if not items:
        return "", term_refs, citations
    rail_html = (
        '<details class="glossary-rail margin-rail" data-reading-rail="margin">'
        '<summary class="glossary-heading"><span>原文引文</span>'
        f'<span class="glossary-count">{quote_count} 条</span></summary>'
        f'<div class="glossary-list">{"".join(items)}</div></details>'
    )
    return rail_html, term_refs, citations


def _render_margin_citations(citations: list[dict]) -> str:
    """Keep a compact, clickable quotation reference in the body."""
    if not citations:
        return ""
    links = "".join(
        f'<a class="margin-cite" href="#{_esc(item["target_id"])}" '
        f'data-margin-note-target="{_esc(item["target_id"])}">[{item["number"]}]</a>'
        for item in citations
    )
    return (
        '<div class="margin-citations">'
        '<span class="margin-citations-label">相关引文</span>'
        f'{links}</div>'
    )


def _render_analogies_inline(analogies: list) -> str:
    """Render analogies as a consistently labelled explanatory annotation."""
    if not analogies:
        return ""
    parts = []
    for a in analogies:
        concept = _esc(a.get("concept") or "")
        analogy = _esc(a.get("analogy") or "")
        concept_html = f'<span class="art-analogy-term">{concept}</span>' if concept else ""
        parts.append(
            '<blockquote class="art-annotation art-quote">'
            '<span class="art-annotation-label">类比</span>'
            f'<div class="art-analogy-copy">{concept_html}'
            f'<span class="art-analogy-text">{analogy}</span></div>'
            '</blockquote>'
        )
    return "".join(parts)


def _render_concepts_inline(explainers: list) -> str:
    """Render term, definition and plain-language explanation as distinct levels."""
    if not explainers:
        return ""
    parts = []
    for e in explainers:
        term = _esc(e.get("term") or "")
        definition = _esc(e.get("definition") or "")
        analogy = _esc(e.get("analogy") or "")
        line = (
            '<aside class="art-annotation art-note">'
            '<div class="art-concept-head">'
            '<span class="art-annotation-label">名词解释</span>'
            f'<span class="art-concept-term">{term}</span></div>'
            f'<div class="art-concept-definition">{definition}</div>'
        )
        if analogy:
            line += (
                '<div class="art-concept-plain">'
                '<span class="art-mini-label">通俗理解</span>'
                f'{analogy}</div>'
            )
        line += '</aside>'
        parts.append(line)
    return "".join(parts)


def _display_value(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(item) for item in value if str(item).strip())
    return str(value or "").strip()


def _visual_tone(value: Any) -> str:
    """Return a whitelisted semantic color role for public visual classes."""
    tone = str(value or "").strip().lower()
    return tone if tone in {"primary", "baseline", "warning", "danger"} else ""


def _render_experiment(experiment: dict) -> str:
    title = experiment.get("title") or experiment.get("question") or ""
    experiment_id = experiment.get("id") or ""
    question = experiment.get("question") or ""
    fields = [
        ("实验设置", experiment.get("setup")),
        ("样本与轮次", experiment.get("sample")),
        ("模型", experiment.get("models")),
        ("判定指标", experiment.get("metric")),
        ("对照或基线", experiment.get("control")),
    ]
    result = experiment.get("result") or ""
    limitations = experiment.get("limitations") or ""
    claim_ids = [str(x) for x in (experiment.get("claim_ids") or []) if str(x).strip()]
    if not any((title, question, result)):
        return ""
    parts = [
        f'<details class="experiment-block" data-experiment-id="{_esc(experiment_id)}" '
        f'data-claim-ids="{_esc(",".join(claim_ids))}">',
        f'<summary><span class="experiment-title">{_esc(title)}</span></summary>',
        '<div class="experiment-body">',
    ]
    if question:
        parts.append(f'<div class="experiment-question">{_esc(question)}</div>')
    field_html = []
    for label, value in fields:
        display = _display_value(value)
        if display:
            field_html.append(
                '<div class="experiment-field">'
                f'<div class="experiment-label">{_esc(label)}</div>'
                f'<div class="experiment-value">{_esc(display)}</div>'
                '</div>'
            )
    if field_html:
        parts.append(f'<div class="experiment-grid">{"".join(field_html)}</div>')
    if result:
        parts.append(f'<div class="experiment-result"><strong>结果：</strong>{_esc(result)}</div>')
    if limitations:
        parts.append(f'<div class="experiment-limit"><strong>边界：</strong>{_esc(limitations)}</div>')
    parts.append('</div></details>')
    return "".join(parts)


def _render_case_story(story: dict) -> str:
    title = story.get("title") or ""
    setup = story.get("setup") or ""
    beats = [beat for beat in (story.get("beats") or []) if isinstance(beat, dict)]
    outcome = story.get("outcome") or ""
    boundary = story.get("boundary") or ""
    source_mode = str(story.get("source_mode") or "reconstruction").lower()
    claim_ids = [str(x) for x in (story.get("claim_ids") or []) if str(x).strip()]
    if not title or not beats:
        return ""
    parts = [
        f'<section class="case-story" data-case-id="{_esc(story.get("id") or "")}" '
        f'data-claim-ids="{_esc(",".join(claim_ids))}">',
        f'<div class="case-title">{_esc(title)}</div>',
    ]
    if setup:
        parts.append(f'<div class="case-setup">{_esc(setup)}</div>')
    parts.append('<div class="case-beats">')
    for beat in beats:
        label = beat.get("label") or "阶段"
        text = beat.get("text") or ""
        if not text:
            continue
        quote = beat.get("source_quote") or ""
        parts.append(
            '<div class="case-beat">'
            f'<div class="case-beat-label">{_esc(label)}</div>'
            f'<div class="case-beat-text">{_esc(text)}</div>'
        )
        if quote:
            parts.append(f'<blockquote class="case-source-quote">{_esc(quote)}</blockquote>')
        parts.append('</div>')
    parts.append('</div>')
    if outcome:
        parts.append(f'<div class="case-outcome">结果：{_esc(outcome)}</div>')
    if boundary:
        parts.append(f'<div class="case-boundary"><strong>不能据此证明：</strong>{_esc(boundary)}</div>')
    provenance = "含原文逐字引文" if source_mode == "quoted" else "基于证据重建事件顺序，非逐字对话"
    parts.append(f'<div class="case-provenance">{_esc(provenance)}')
    parts.append('</div></section>')
    return "".join(parts)


def _render_visual(v: dict) -> str:
    t = v.get("type", "")
    title = _esc(v.get("title") or "")
    data = v.get("data") or {}
    parts = []
    if title:
        parts.append(f'<p class="visual-title">{title}</p>')

    if t == "compare_table":
        headers = data.get("headers", [])
        rows = data.get("rows", [])
        column_roles = data.get("column_roles", [])
        layout = str(data.get("layout") or "stacked").strip().lower()
        if layout == "matrix":
            parts.append('<div class="cmp-scroll"><table class="cmp-table"><thead><tr>')
            for index, header in enumerate(headers):
                tone = _visual_tone(column_roles[index] if index < len(column_roles) else "")
                tone_class = f' class="cmp-tone-{tone}"' if tone else ""
                parts.append(f'<th{tone_class}>{_esc(header)}</th>')
            parts.append('</tr></thead><tbody>')
            for row in rows:
                parts.append('<tr>')
                for index, cell in enumerate(row):
                    tone = _visual_tone(column_roles[index] if index < len(column_roles) else "")
                    tone_class = f' class="cmp-tone-{tone}"' if tone else ""
                    parts.append(f'<td{tone_class}>{_esc(cell)}</td>')
                parts.append('</tr>')
            parts.append('</tbody></table></div>')
        else:
            layout_class = "paired" if layout == "paired" else "stacked"
            parts.append(f'<div class="comparison-list {layout_class}">')
            for row in rows:
                if not row:
                    continue
                topic = row[0]
                parts.append('<section class="comparison-row">')
                parts.append(f'<div class="comparison-topic">{_esc(topic)}</div>')
                parts.append('<dl class="comparison-pairs">')
                for index, cell in enumerate(row[1:], 1):
                    label = headers[index] if index < len(headers) else f"对比项 {index}"
                    tone = _visual_tone(column_roles[index] if index < len(column_roles) else "")
                    tone_class = f" cmp-tone-{tone}" if tone else ""
                    parts.append(
                        f'<div class="comparison-pair{tone_class}">'
                        f'<dt>{_esc(label)}</dt><dd>{_esc(cell)}</dd>'
                        '</div>'
                    )
                parts.append('</dl></section>')
            parts.append("</div>")

    elif t == "delta_table":
        rows = [x for x in (data.get("rows") or []) if isinstance(x, dict)]
        baseline_label = str(data.get("baseline_label") or "调整前").strip()
        current_label = str(data.get("current_label") or "调整后").strip()
        boundary = str(data.get("boundary") or "").strip()
        if rows:
            parts.append('<div class="delta-table">')
            parts.append(
                f'<div class="delta-head"><span>指标</span><span>{_esc(baseline_label)} → {_esc(current_label)}</span><span>变化</span></div>'
            )
            direction_symbols = {"up": "↑", "down": "↓", "flat": "→"}
            for row in rows:
                direction = str(row.get("direction") or "flat").strip().lower()
                tone = _visual_tone(row.get("tone"))
                tone_class = f" tone-{tone}" if tone else ""
                parts.append('<div class="delta-row">')
                parts.append(f'<div class="delta-label">{_esc(row.get("label") or "指标")}</div>')
                parts.append('<div class="delta-values">')
                parts.append(
                    f'<div class="delta-value"><span class="delta-value-label">{_esc(baseline_label)}</span>'
                    f'<strong>{_esc(row.get("baseline") or "")}</strong></div>'
                )
                parts.append('<span class="delta-arrow" aria-hidden="true">→</span>')
                parts.append(
                    f'<div class="delta-value current"><span class="delta-value-label">{_esc(current_label)}</span>'
                    f'<strong>{_esc(row.get("current") or "")}</strong></div></div>'
                )
                parts.append(
                    f'<div class="delta-change{tone_class}"><span class="delta-direction" aria-hidden="true">'
                    f'{direction_symbols.get(direction, "→")}</span>{_esc(row.get("change") or "")}</div></div>'
                )
            if boundary:
                parts.append(f'<div class="delta-boundary"><strong>怎么读：</strong>{_esc(boundary)}</div>')
            parts.append('</div>')

    elif t == "status_matrix":
        columns = [str(x).strip() for x in (data.get("columns") or []) if str(x).strip()]
        rows = [x for x in (data.get("rows") or []) if isinstance(x, dict)]
        caption = str(data.get("caption") or "").strip()
        boundary = str(data.get("boundary") or "").strip()
        if columns and rows:
            parts.append('<div class="status-matrix-scroll"><table class="status-matrix"><thead><tr><th>对象</th>')
            parts.extend(f'<th>{_esc(column)}</th>' for column in columns)
            parts.append('</tr></thead><tbody>')
            for row in rows:
                parts.append(f'<tr><td>{_esc(row.get("label") or "对象")}</td>')
                for cell in (row.get("cells") or []):
                    if not isinstance(cell, dict):
                        continue
                    tone = _visual_tone(cell.get("tone"))
                    tone_class = f' class="tone-{tone}"' if tone else ""
                    parts.append(f'<td{tone_class}>{_esc(cell.get("value") or "")}</td>')
                parts.append('</tr>')
            parts.append('</tbody></table></div>')
            if caption:
                parts.append(f'<div class="status-caption">{_esc(caption)}</div>')
            if boundary:
                parts.append(f'<div class="status-boundary"><strong>怎么读：</strong>{_esc(boundary)}</div>')

    elif t == "decision_table":
        rows = [x for x in (data.get("rows") or []) if isinstance(x, dict)]
        boundary = str(data.get("boundary") or "").strip()
        if rows:
            parts.append('<div class="decision-table">')
            parts.append('<div class="decision-head"><span>条件</span><span>结果</span><span>可以怎么做</span></div>')
            for row in rows:
                tone = _visual_tone(row.get("tone"))
                tone_class = f" tone-{tone}" if tone else ""
                parts.append(f'<div class="decision-row{tone_class}">')
                parts.append(f'<div class="decision-cell condition">{_esc(row.get("condition") or "")}</div>')
                parts.append(f'<div class="decision-cell result">{_esc(row.get("result") or "")}</div>')
                parts.append(f'<div class="decision-cell action">{_esc(row.get("action") or "")}</div></div>')
            if boundary:
                parts.append(f'<div class="decision-boundary"><strong>适用范围：</strong>{_esc(boundary)}</div>')
            parts.append('</div>')

    elif t == "metric_bars":
        groups = [x for x in (data.get("groups") or []) if isinstance(x, dict)]
        primary_label = str(data.get("primary_label") or "方案 A")
        baseline_label = str(data.get("baseline_label") or "方案 B")
        normalization_note = str(
            data.get("normalization_note")
            or "条长只在同一模型、同一指标内归一化；标注数字保留原值。"
        )
        boundary = str(data.get("boundary") or "")
        if groups:
            parts.append('<div class="metric-bars" data-metric-bars>')
            parts.append('<div class="mb-tabs" role="group" aria-label="切换比较指标">')
            for index, group in enumerate(groups):
                active = " active" if index == 0 else ""
                pressed = "true" if index == 0 else "false"
                parts.append(
                    f'<button type="button" class="mb-tab{active}" data-metric-tab="{index}" '
                    f'aria-pressed="{pressed}">{_esc(group.get("label") or f"指标 {index + 1}")}</button>'
                )
            parts.append('</div>')
            for index, group in enumerate(groups):
                parts.append(f'<section class="mb-panel" data-metric-panel="{index}">')
                parts.append(f'<p class="mb-question">{_esc(group.get("question") or "比较结果")}</p>')
                if group.get("metric"):
                    parts.append(f'<div class="mb-metric">指标：{_esc(group.get("metric"))}</div>')
                rows = [x for x in (group.get("rows") or []) if isinstance(x, dict)]
                for row in rows:
                    try:
                        primary_value = float(row.get("primary_value"))
                        baseline_value = float(row.get("baseline_value"))
                    except (TypeError, ValueError):
                        continue
                    maximum = max(primary_value, baseline_value)
                    if maximum <= 0:
                        continue
                    primary_width = max(3.0, primary_value / maximum * 100)
                    baseline_width = max(3.0, baseline_value / maximum * 100)
                    parts.append('<div class="mb-model">')
                    parts.append(f'<div class="mb-model-name">{_esc(row.get("label") or "比较对象")}</div>')
                    parts.append('<div class="mb-pair">')
                    parts.append(
                        '<div class="mb-line primary">'
                        f'<span class="mb-series">{_esc(primary_label)}</span>'
                        f'<span class="mb-track"><span class="mb-fill" style="--bar-width:{primary_width:.2f}%"></span></span>'
                        f'<span class="mb-value">{_esc(row.get("primary_display") or f"{primary_value:g}")}</span>'
                        '</div>'
                    )
                    parts.append(
                        '<div class="mb-line baseline">'
                        f'<span class="mb-series">{_esc(baseline_label)}</span>'
                        f'<span class="mb-track"><span class="mb-fill" style="--bar-width:{baseline_width:.2f}%"></span></span>'
                        f'<span class="mb-value">{_esc(row.get("baseline_display") or f"{baseline_value:g}")}</span>'
                        '</div></div>'
                    )
                    parts.append(f'<div class="mb-ratio">{_esc(row.get("ratio") or "")}</div></div>')
                parts.append('</section>')
            parts.append(f'<div class="mb-note">{_esc(normalization_note)}</div>')
            if boundary:
                parts.append(f'<div class="mb-boundary"><strong>怎么读：</strong>{_esc(boundary)}</div>')
            parts.append('</div>')

    elif t == "rank_bars":
        groups = [x for x in (data.get("groups") or []) if isinstance(x, dict)]
        caption = str(data.get("caption") or "").strip()
        boundary = str(data.get("boundary") or "").strip()
        if groups:
            parts.append('<div class="rank-bars" data-rank-bars>')
            if len(groups) > 1:
                parts.append('<div class="rb-tabs" role="group" aria-label="切换参数组">')
                for index, group in enumerate(groups):
                    active = " active" if index == 0 else ""
                    pressed = "true" if index == 0 else "false"
                    parts.append(
                        f'<button type="button" class="rb-tab{active}" data-rank-tab="{index}" '
                        f'aria-pressed="{pressed}">{_esc(group.get("label") or f"分组 {index + 1}")}</button>'
                    )
                parts.append('</div>')
            for index, group in enumerate(groups):
                tone = _visual_tone(group.get("tone")) or "primary"
                hidden = "" if index == 0 else " hidden"
                rows = [x for x in (group.get("rows") or []) if isinstance(x, dict)]
                numeric_values = []
                for row in rows:
                    try:
                        numeric_values.append(abs(float(row.get("value"))))
                    except (TypeError, ValueError):
                        numeric_values.append(0.0)
                maximum = max(numeric_values, default=0.0)
                parts.append(
                    f'<section class="rb-panel tone-{tone}" data-rank-panel="{index}"{hidden}>'
                )
                question = str(group.get("question") or "").strip()
                if question:
                    parts.append(f'<p class="rb-question">{_esc(question)}</p>')
                for row, numeric_value in zip(rows, numeric_values):
                    width = numeric_value / maximum * 100 if maximum > 0 else 0
                    display = row.get("display")
                    if display in (None, ""):
                        display = f'{row.get("value", "")}{group.get("unit") or ""}'
                    parts.append('<div class="rb-row">')
                    parts.append(f'<div class="rb-label">{_esc(row.get("label") or "比较对象")}</div>')
                    parts.append(
                        '<div class="rb-track" aria-hidden="true">'
                        f'<span class="rb-fill" style="--bar-width:{width:.2f}%"></span></div>'
                    )
                    parts.append(f'<div class="rb-value">{_esc(display)}</div>')
                    note = str(row.get("note") or "").strip()
                    if note:
                        parts.append(f'<div class="rb-note">{_esc(note)}</div>')
                    parts.append('</div>')
                parts.append('</section>')
            if caption:
                parts.append(f'<div class="rb-caption">{_esc(caption)}</div>')
            if boundary:
                parts.append(f'<div class="rb-boundary"><strong>怎么读：</strong>{_esc(boundary)}</div>')
            parts.append('</div>')

    elif t == "funnel_flow":
        steps = [x for x in (data.get("steps") or []) if isinstance(x, dict)]
        entry_label = str(data.get("entry_label") or "进入流程的全部对象").strip()
        caption = str(data.get("caption") or "").strip()
        if steps:
            parts.append('<div class="funnel-flow">')
            parts.append(f'<div class="ff-entry">{_esc(entry_label)}</div>')
            for index, step in enumerate(steps):
                try:
                    requested_width = float(step.get("width"))
                except (TypeError, ValueError):
                    requested_width = 100 - index * 18
                width = max(48.0, min(100.0, requested_width))
                parts.append('<div class="ff-arrow">\u2193</div>')
                parts.append(f'<div class="ff-stage" style="--funnel-width:{width:.1f}%">')
                parts.append(f'<span class="ff-label">{_esc(step.get("label") or step.get("title") or f"第 {index + 1} 关")}</span>')
                description = str(step.get("description") or step.get("text") or "").strip()
                if description:
                    parts.append(f'<span class="ff-description">{_esc(description)}</span>')
                parts.append('</div>')
                exit_label = str(step.get("exit_label") or "").strip()
                if exit_label:
                    parts.append(f'<div class="ff-exit">这一关会拿掉：{_esc(exit_label)}</div>')
            if caption:
                parts.append(f'<div class="ff-caption">{_esc(caption)}</div>')
            parts.append('</div>')

    elif t == "flow":
        steps = data.get("steps", [])
        presentation = str(data.get("presentation") or "static").strip().lower()
        if presentation == "stepper" and all(isinstance(step, dict) for step in steps):
            caption = str(data.get("caption") or "").strip()
            parts.append('<div class="flow-stepper" data-flow-stepper>')
            parts.append('<div class="fs-nav" role="group" aria-label="选择流程阶段">')
            for index, step in enumerate(steps):
                active = " active" if index == 0 else ""
                pressed = "true" if index == 0 else "false"
                label = str(step.get("label") or step.get("title") or f"第 {index + 1} 步").strip()
                parts.append(
                    f'<button type="button" class="fs-tab{active}" data-flow-step="{index}" '
                    f'aria-pressed="{pressed}">{index + 1}. {_esc(label)}</button>'
                )
            parts.append('</div>')
            for index, step in enumerate(steps):
                active = " active" if index == 0 else ""
                label = str(step.get("label") or f"第 {index + 1} 步").strip()
                step_title = str(step.get("title") or label).strip()
                description = str(step.get("description") or step.get("text") or "").strip()
                result = str(step.get("result") or "").strip()
                parts.append(f'<section class="fs-panel{active}" data-flow-panel="{index}">')
                parts.append(f'<div class="fs-kicker">第 {index + 1} / {len(steps)} 步 · {_esc(label)}</div>')
                parts.append(f'<div class="fs-title">{_esc(step_title)}</div>')
                parts.append(f'<div class="fs-description">{_esc(description)}</div>')
                if result:
                    parts.append(f'<div class="fs-result"><strong>结果：</strong>{_esc(result)}</div>')
                parts.append('</section>')
            parts.append('<div class="fs-controls">')
            parts.append('<button type="button" class="fs-control" data-flow-prev aria-label="上一步" title="上一步" disabled>←</button>')
            parts.append('<button type="button" class="fs-control" data-flow-next aria-label="下一步" title="下一步">→</button>')
            parts.append('</div>')
            if caption:
                parts.append(f'<div class="fs-caption">{_esc(caption)}</div>')
            parts.append('</div>')
        else:
            parts.append('<div class="flow">')
            for i, s in enumerate(steps, 1):
                if isinstance(s, dict):
                    step_title = str(s.get("title") or s.get("label") or "").strip()
                    step_description = str(s.get("description") or s.get("text") or "").strip()
                    if step_title and step_description:
                        step_html = (
                            '<span class="flow-copy">'
                            f'<span class="flow-title">{_esc(step_title)}</span>'
                            f'<span class="flow-description">{_esc(step_description)}</span>'
                            '</span>'
                        )
                    else:
                        step_html = f'<span class="flow-copy">{_esc(step_title or step_description)}</span>'
                else:
                    step_html = f'<span class="flow-copy">{_esc(s)}</span>'
                parts.append(
                    f'<div class="flow-step"><span class="flow-num">{i}</span>'
                    f'{step_html}</div>'
                )
                if i < len(steps):
                    parts.append('<div class="flow-arrow">\u2193</div>')
            parts.append("</div>")

    elif t == "strategy_tabs":
        strategies = [x for x in (data.get("strategies") or []) if isinstance(x, dict)]
        instruction = str(data.get("instruction") or "切换方案，查看它分别改变哪一层问题。").strip()
        boundary = str(data.get("boundary") or data.get("caption") or "").strip()
        if strategies:
            parts.append('<div class="strategy-tabs" data-strategy-tabs>')
            if instruction:
                parts.append(f'<div class="st-instruction">{_esc(instruction)}</div>')
            parts.append('<div class="st-nav" role="tablist" aria-label="切换策略方案">')
            for index, strategy in enumerate(strategies):
                tone = _visual_tone(strategy.get("tone")) or "primary"
                active = " active" if index == 0 else ""
                selected = "true" if index == 0 else "false"
                parts.append(
                    f'<button type="button" role="tab" class="st-tab tone-{tone}{active}" '
                    f'data-strategy-tab="{index}" data-step="{index + 1:02d}" '
                    f'aria-selected="{selected}">{_esc(strategy.get("label") or f"方案 {index + 1}")}</button>'
                )
            parts.append('</div>')
            for index, strategy in enumerate(strategies):
                tone = _visual_tone(strategy.get("tone")) or "primary"
                active = " active" if index == 0 else ""
                parts.append(
                    f'<section role="tabpanel" class="st-panel tone-{tone}{active}" data-strategy-panel="{index}">'
                )
                parts.append('<div class="st-panel-head">')
                parts.append(f'<div class="st-panel-title">{_esc(strategy.get("label") or f"方案 {index + 1}")}</div>')
                parts.append(f'<div class="st-panel-target">作用对象 · {_esc(strategy.get("target") or "")}</div></div>')
                parts.append('<div class="st-grid">')
                parts.append('<div class="st-item"><span class="st-label">它怎样起作用</span>')
                parts.append(f'<div class="st-value">{_esc(strategy.get("mechanism") or "")}</div></div>')
                parts.append('<div class="st-item"><span class="st-label">希望带来什么变化</span>')
                parts.append(f'<div class="st-value">{_esc(strategy.get("expected_effect") or "")}</div></div>')
                parts.append('<div class="st-item open"><span class="st-label">真正落地还缺什么</span>')
                parts.append(f'<div class="st-value">{_esc(strategy.get("open_questions") or "")}</div></div>')
                parts.append('</div></section>')
            if boundary:
                parts.append(f'<div class="st-boundary"><strong>阅读边界：</strong>{_esc(boundary)}</div>')
            parts.append('</div>')

    elif t == "layer_stack":
        layers = [x for x in (data.get("layers") or []) if isinstance(x, dict)]
        caption = str(data.get("caption") or "").strip()
        if layers:
            parts.append('<div class="layer-stack">')
            for index, layer in enumerate(layers, 1):
                opened = " open" if index == 1 else ""
                label = str(layer.get("label") or f"第 {index} 层").strip()
                layer_title = str(layer.get("title") or "").strip()
                description = str(layer.get("description") or "").strip()
                points = [str(x).strip() for x in (layer.get("items") or []) if str(x).strip()]
                parts.append(f'<details class="layer-item"{opened}>')
                parts.append(
                    '<summary>'
                    f'<span class="layer-index">{index:02d}</span>'
                    '<span class="layer-heading">'
                    f'<span class="layer-label">{_esc(label)}</span>'
                    f'<span class="layer-title">{_esc(layer_title)}</span>'
                    '</span><span class="layer-toggle" aria-hidden="true"></span>'
                    '</summary>'
                )
                parts.append(f'<div class="layer-body">{_esc(description)}')
                if points:
                    parts.append('<ul class="layer-points">')
                    parts.extend(f'<li>{_esc(point)}</li>' for point in points)
                    parts.append('</ul>')
                parts.append('</div></details>')
            parts.append('</div>')
            if caption:
                parts.append(f'<div class="layer-caption"><strong>怎么读：</strong>{_esc(caption)}</div>')

    elif t == "stat":
        items = data.get("items", [])
        unit = _esc(data.get("unit") or "")
        parts.append('<div class="stat-grid">')
        for it in items:
            tone = _visual_tone(it.get("tone"))
            tone_class = f" tone-{tone}" if tone else ""
            parts.append(
                f'<div class="stat-card{tone_class}"><div class="stat-val">'
                f'{_esc(it.get("value", ""))}{unit}</div>'
                f'<div class="stat-label">{_esc(it.get("label", ""))}</div></div>'
            )
        parts.append("</div>")

    elif t == "timeline":
        events = [event for event in (data.get("events") or []) if isinstance(event, dict)]
        presentation = str(data.get("presentation") or "static").strip().lower()
        if presentation == "scrubber" and events:
            caption = str(data.get("caption") or "").strip()
            first = events[0]
            first_title = str(first.get("title") or first.get("event") or "").strip()
            parts.append('<div class="timeline-scrubber" data-timeline-scrubber>')
            parts.append('<div class="ts-stage" aria-live="polite">')
            parts.append(f'<div class="ts-time" data-timeline-time>{_esc(first.get("time") or "")}</div>')
            parts.append(f'<div class="ts-title" data-timeline-title>{_esc(first_title)}</div>')
            parts.append(f'<div class="ts-description" data-timeline-description>{_esc(first.get("description") or "")}</div></div>')
            parts.append(
                f'<input class="ts-range" type="range" min="0" max="{len(events) - 1}" step="1" value="0" '
                'data-timeline-input aria-label="拖动查看时间节点">'
            )
            parts.append('<div class="ts-ticks" aria-hidden="true">')
            parts.extend(f'<span>{_esc(event.get("time") or "")}</span>' for event in events)
            parts.append('</div><ol class="ts-fallback">')
            for event in events:
                event_title = str(event.get("title") or event.get("event") or "").strip()
                parts.append(f'<li><strong>{_esc(event.get("time") or "")}</strong> · {_esc(event_title)}</li>')
            parts.append('</ol>')
            for index, event in enumerate(events):
                event_title = str(event.get("title") or event.get("event") or "").strip()
                parts.append(
                    f'<span hidden data-timeline-event="{index}" data-time="{_esc(event.get("time") or "")}" '
                    f'data-title="{_esc(event_title)}" data-description="{_esc(event.get("description") or "")}"></span>'
                )
            if caption:
                parts.append(f'<div class="ts-caption">{_esc(caption)}</div>')
            parts.append('</div>')
        else:
            parts.append('<div class="timeline">')
            for e in events:
                event_title = str(e.get("title") or e.get("event") or "").strip()
                description = str(e.get("description") or "").strip()
                body_parts = []
                if event_title:
                    body_parts.append(f'<span class="tl-title">{_esc(event_title)}</span>')
                if description:
                    body_parts.append(f'<span class="tl-description">{_esc(description)}</span>')
                parts.append(
                    f'<div class="tl-event"><div class="tl-time">{_esc(e.get("time", ""))}</div>'
                    f'<div class="tl-body">{"".join(body_parts)}</div></div>'
                )
            parts.append("</div>")

    elif t == "interactive_compare":
        instruction = data.get("instruction") or "切换模式，观察同一组候选怎样得到不同结果。"
        prompt = data.get("prompt") or ""
        options = [x for x in (data.get("options") or []) if isinstance(x, dict)]
        modes = [x for x in (data.get("modes") or []) if isinstance(x, dict)]
        takeaway = data.get("takeaway") or ""
        caption = data.get("caption") or "机制示意，不代表真实概率、模型输出或检测结果。"
        if options and modes:
            parts.append('<div class="interactive-compare" data-interactive-compare>')
            parts.append(f'<div class="ic-instruction">{_esc(instruction)}</div>')
            parts.append('<div class="ic-toggle" role="group" aria-label="切换比较模式">')
            for index, mode in enumerate(modes):
                active = " active" if index == 0 else ""
                pressed = "true" if index == 0 else "false"
                parts.append(
                    f'<button type="button" class="ic-mode{active}" data-interactive-mode="{index}" '
                    f'aria-pressed="{pressed}">{_esc(mode.get("label") or f"模式 {index + 1}")}</button>'
                )
            parts.append('</div>')
            if prompt:
                parts.append(f'<div class="ic-prompt">{_esc(prompt)}</div>')
            for index, mode in enumerate(modes):
                hidden = "" if index == 0 else " hidden"
                selected_index = mode.get("selected_index")
                if not isinstance(selected_index, int) or isinstance(selected_index, bool):
                    selected_index = -1
                parts.append(f'<div class="ic-state" data-interactive-state="{index}"{hidden}>')
                parts.append('<div class="ic-state-meta">')
                parts.append(
                    f'<span class="ic-state-label">{_esc(mode.get("result_label") or "本次选择")}</span>'
                )
                if mode.get("signal"):
                    parts.append(f'<span class="ic-state-signal">{_esc(mode.get("signal"))}</span>')
                parts.append('</div><div class="ic-options">')
                for option_index, option in enumerate(options):
                    selected = " selected" if option_index == selected_index else ""
                    parts.append(f'<div class="ic-option{selected}">')
                    parts.append(f'<div class="ic-option-name">{_esc(option.get("label") or "候选")}</div>')
                    if option.get("note"):
                        parts.append(f'<div class="ic-option-note">{_esc(option.get("note"))}</div>')
                    parts.append('</div>')
                parts.append('</div>')
                if mode.get("note"):
                    parts.append(f'<div class="ic-state-note">{_esc(mode.get("note"))}</div>')
                parts.append('</div>')
            if takeaway:
                parts.append(f'<div class="ic-takeaway">{_esc(takeaway)}</div>')
            parts.append(f'<div class="ic-caption">{_esc(caption)}</div></div>')

    elif t == "scenario_calculator":
        instruction = data.get("instruction") or "切换对象并调整假设，观察结果怎样变化。"
        tabs = [x for x in (data.get("tabs") or []) if isinstance(x, dict)]
        slider = data.get("slider") if isinstance(data.get("slider"), dict) else {}
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        formula_note = data.get("formula_note") or ""
        caption = data.get("caption") or "交互中的可调数值是情景假设，不是来源数据。"
        try:
            slider_min = float(slider.get("min", 0))
            slider_max = float(slider.get("max", 10))
            slider_step = float(slider.get("step", 1))
            slider_value = float(slider.get("value", slider_min))
            result_base = float(result.get("base"))
        except (TypeError, ValueError):
            tabs = []
        else:
            if slider_max <= slider_min or slider_step <= 0:
                tabs = []
            slider_value = min(max(slider_value, slider_min), slider_max)
        if tabs:
            decimals = result.get("decimals", 2)
            if not isinstance(decimals, int) or isinstance(decimals, bool):
                decimals = 2
            decimals = min(max(decimals, 0), 4)
            prefix = str(result.get("prefix") or "")
            initial_result = result_base - slider_value
            slider_prefix = str(slider.get("prefix") or "")
            slider_suffix = str(slider.get("suffix") or "")
            parts.append(
                '<div class="scenario-calculator" data-scenario-calculator '
                f'data-scenario-base="{result_base}" data-scenario-decimals="{decimals}" '
                f'data-scenario-prefix="{_esc(prefix)}" '
                f'data-scenario-input-prefix="{_esc(slider_prefix)}" '
                f'data-scenario-input-suffix="{_esc(slider_suffix)}">'
            )
            parts.append(f'<div class="sc-instruction">{_esc(instruction)}</div>')
            parts.append('<div class="sc-tabs" role="group" aria-label="切换情景对象">')
            for index, tab in enumerate(tabs):
                active = " active" if index == 0 else ""
                pressed = "true" if index == 0 else "false"
                parts.append(
                    f'<button type="button" class="sc-tab{active}" data-scenario-tab="{index}" '
                    f'aria-pressed="{pressed}">{_esc(tab.get("label") or f"对象 {index + 1}")}</button>'
                )
            parts.append('</div>')
            for index, tab in enumerate(tabs):
                hidden = "" if index == 0 else " hidden"
                metrics = [x for x in (tab.get("metrics") or []) if isinstance(x, dict)]
                parts.append(f'<div class="sc-platform" data-scenario-panel="{index}"{hidden}>')
                parts.append('<div class="sc-metrics">')
                for metric in metrics:
                    parts.append('<div class="sc-metric">')
                    parts.append(f'<div class="sc-metric-label">{_esc(metric.get("label") or "指标")}</div>')
                    parts.append(f'<div class="sc-metric-value">{_esc(metric.get("value") or "")}</div>')
                    if metric.get("note"):
                        parts.append(f'<div class="sc-metric-note">{_esc(metric.get("note"))}</div>')
                    parts.append('</div>')
                parts.append('</div></div>')
            parts.append('<div class="sc-control">')
            slider_label = str(slider.get("label") or "调整情景假设")
            parts.append(f'<span class="sc-control-label">{_esc(slider_label)}</span>')
            parts.append(
                f'<input type="range" data-scenario-input aria-label="{_esc(slider_label)}" '
                f'min="{slider_min:g}" max="{slider_max:g}" step="{slider_step:g}" value="{slider_value:g}">'
            )
            parts.append(
                f'<output class="sc-input-value" data-scenario-input-value>'
                f'{_esc(slider_prefix)}{slider_value:.2f}{_esc(slider_suffix)}</output>'
            )
            parts.append('</div><div class="sc-result">')
            parts.append(f'<span class="sc-result-label">{_esc(result.get("label") or "情景结果")}</span>')
            parts.append(f'<output class="sc-result-value" data-scenario-result>{_esc(prefix)}{initial_result:.{decimals}f}</output>')
            parts.append('</div>')
            if formula_note:
                parts.append(f'<div class="sc-formula">{_esc(formula_note)}</div>')
            parts.append(f'<div class="sc-caption">{_esc(caption)}</div></div>')

    elif t == "capacity_curve":
        question = data.get("question") or data.get("reader_question") or "变量继续增强时，结果会怎样变化？"
        axis_label = data.get("axis_label") or "变量强度"
        result_label = data.get("result_label") or "结果表现"
        states = [x for x in (data.get("states") or []) if isinstance(x, dict)]
        caption = data.get("caption") or "定性关系示意；具体转折点会随条件变化，不是通用预测器。"
        if 3 <= len(states) <= 5:
            positions = []
            for index, state in enumerate(states):
                try:
                    position = float(state.get("position"))
                except (TypeError, ValueError):
                    position = index * 100 / max(len(states) - 1, 1)
                positions.append(min(max(position, 0), 100))
            parts.append('<div class="capacity-curve" data-capacity-curve>')
            parts.append(f'<div class="cc-question">{_esc(question)}</div>')
            parts.append('<div class="cc-stage" aria-hidden="true">')
            parts.append(f'<span class="cc-axis-y">{_esc(result_label)}</span><span class="cc-axis-x">{_esc(axis_label)}</span>')
            parts.append('<div class="cc-points">')
            for state in states:
                parts.append(
                    '<span class="cc-point"><span class="cc-point-dot"></span>'
                    f'{_esc(state.get("label") or "阶段")}</span>'
                )
            parts.append('</div></div><div class="cc-control">')
            parts.append(
                '<input type="range" min="0" max="100" step="1" value="50" '
                f'aria-label="{_esc(axis_label)}" data-capacity-input>'
            )
            nearest = min(range(len(states)), key=lambda i: abs(positions[i] - 50))
            parts.append(f'<output class="cc-current" data-capacity-label>{_esc(states[nearest].get("label") or "阶段")}</output>')
            parts.append('</div>')
            parts.append(
                f'<div class="cc-result" data-capacity-result>{_esc(states[nearest].get("result") or "")}</div>'
            )
            for state, position in zip(states, positions):
                parts.append(
                    f'<span hidden data-capacity-state data-position="{position:g}" '
                    f'data-label="{_esc(state.get("label") or "阶段")}" '
                    f'data-result="{_esc(state.get("result") or "")}"></span>'
                )
            parts.append(f'<div class="cc-caption">{_esc(caption)}</div></div>')

    elif t == "cost_ledger":
        question = data.get("question") or data.get("reader_question") or "哪些成本被计入时，结论会改变？"
        cost_labels = [str(x).strip() for x in (data.get("cost_labels") or []) if str(x).strip()]
        scenarios = [x for x in (data.get("scenarios") or []) if isinstance(x, dict)]
        boundary = data.get("boundary") or "不同成本口径不能直接混为同一个结论。"
        if cost_labels and 2 <= len(scenarios) <= 6:
            parts.append('<div class="cost-ledger" data-cost-ledger>')
            parts.append(f'<div class="cl-question">{_esc(question)}</div>')
            parts.append('<div class="cl-tabs" role="group" aria-label="切换成本计算方式">')
            for index, scenario in enumerate(scenarios):
                active = " active" if index == 0 else ""
                pressed = "true" if index == 0 else "false"
                parts.append(
                    f'<button type="button" class="cl-tab{active}" data-cost-tab="{index}" '
                    f'aria-pressed="{pressed}">{_esc(scenario.get("label") or f"情景 {index + 1}")}</button>'
                )
            parts.append('</div>')
            for index, scenario in enumerate(scenarios):
                hidden = "" if index == 0 else " hidden"
                included = {str(x).strip() for x in (scenario.get("included") or [])}
                parts.append(f'<div class="cl-panel" data-cost-panel="{index}"{hidden}>')
                parts.append('<div class="cl-included">')
                for label in cost_labels:
                    state_class = " included" if label in included else ""
                    state_text = "计入" if label in included else "不计入"
                    parts.append(f'<span class="cl-cost{state_class}">{_esc(label)} · {state_text}</span>')
                parts.append('</div>')
                parts.append(f'<div class="cl-verdict">{_esc(scenario.get("verdict") or "")}</div>')
                parts.append(f'<div class="cl-explanation">{_esc(scenario.get("explanation") or "")}</div></div>')
            parts.append(f'<div class="cl-boundary">{_esc(boundary)}</div></div>')

    return "".join(parts)


def _render_source_media(item: dict) -> str:
    """渲染一项已登记的来源媒体；未登记项永不进入发布页。"""
    if item.get("registered") is not True:
        return ""
    media_type = str(item.get("type") or "").strip().lower()
    url = str(item.get("url") or "").strip()
    if media_type not in {"image", "video"} or not url:
        return ""
    caption = str(item.get("caption") or "").strip()
    reader_note = str(item.get("reader_note") or "").strip()
    media_id = str(item.get("media_id") or "").strip()
    if media_type == "video" and item.get("embed") is True:
        media_html = (
            '<div class="source-media-embed">'
            f'<iframe src="{_esc(url)}" title="{_esc(caption or "原文视频")}" '
            'loading="lazy" allow="accelerometer; autoplay; encrypted-media; picture-in-picture" '
            'allowfullscreen></iframe></div>'
        )
    elif media_type == "video":
        poster = str(item.get("poster_url") or "").strip()
        poster_attr = f' poster="{_esc(poster)}"' if poster else ""
        media_html = (
            f'<video controls preload="metadata"{poster_attr}>'
            f'<source src="{_esc(url)}">'
            "当前浏览器无法播放该视频。"
            "</video>"
        )
    else:
        alt = caption or "原文图片"
        media_html = f'<img src="{_esc(url)}" alt="{_esc(alt)}" loading="lazy" decoding="async">'
    figcaption = f'<figcaption>{_esc(caption)}</figcaption>' if caption else ""
    note_label = "观看重点" if media_type == "video" else "读图提示"
    reader_html = (
        f'<div class="media-reader-note"><strong>{note_label}：</strong>'
        f'{_esc(reader_note)}</div>'
        if reader_note else ""
    )
    return (
        f'<figure class="source-media" data-media-id="{_esc(media_id)}">'
        f'{media_html}{figcaption}{reader_html}</figure>'
    )


def _render_ai_illustration(item: dict) -> str:
    """AI 图只承担解释功能，必须显式标注且不能伪装成来源媒体。"""
    if item.get("status") != "generated":
        return ""
    image_uri = str(item.get("image_data_uri") or item.get("image_path") or "").strip()
    if not image_uri:
        return ""
    title = str(item.get("title") or "AI 概念示意").strip()
    alt = str(item.get("alt") or title).strip()
    caption = str(item.get("caption") or "").strip()
    note = caption or f"{title}：根据正文制作的概念示意，用于辅助理解，不是原始证据。"
    return (
        f'<figure class="ai-illustration" data-illustration-id="{_esc(item.get("id") or "")}">'
        f'<img src="{_esc(image_uri)}" alt="{_esc(alt)}" loading="lazy" decoding="async">'
        f'<figcaption><span class="ai-label">AI 概念示意</span>{_esc(note)}</figcaption>'
        '</figure>'
    )


def _render_number_story(item: dict) -> str:
    if item.get("suppress_visual") is True or item.get("display_mode") == "audit_only":
        return ""
    title = str(item.get("title") or "这个数字意味着什么").strip()
    value = str(item.get("value") or "").strip()
    unit = str(item.get("unit") or "").strip()
    labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}

    def reader_label(key: str, fallback: str) -> str:
        return str(labels.get(key) or fallback).strip()

    meta_items = [
        (reader_label("denominator", "统计对象"), item.get("denominator")),
        (reader_label("scope", "适用场景"), item.get("scope")),
        (reader_label("period", "统计时间"), item.get("period")),
    ]
    meta = "".join(
        '<div class="number-meta-item">'
        f'<dt>{_esc(label)}</dt><dd>{_esc(content)}</dd></div>'
        for label, content in meta_items if content
    )
    baseline = str(item.get("baseline") or "").strip()
    change = str(item.get("change") or "").strip()
    empty_comparison_values = {
        "", "未知", "未提供", "无", "不适用", "无明确对照", "无可计算变化", "无法计算",
    }
    compact = (
        str(item.get("display_variant") or "").strip().lower() == "compact"
        or (baseline in empty_comparison_values and change in empty_comparison_values)
    )
    compare = ""
    if baseline or change:
        compare_parts = []
        if baseline:
            compare_parts.append(
                '<div class="number-compare-item"><div class="number-compare-label">'
                f'{_esc(reader_label("baseline", "对照情况"))}</div>'
                f'<div class="number-compare-value">{_esc(baseline)}</div></div>'
            )
        if baseline and change:
            compare_parts.append('<div class="number-compare-arrow" aria-hidden="true">↓</div>')
        if change:
            compare_parts.append(
                '<div class="number-compare-item"><div class="number-compare-label">'
                f'{_esc(reader_label("change", "结果变化"))}</div>'
                f'<div class="number-compare-value">{_esc(change)}</div></div>'
            )
        compare = f'<div class="number-compare">{"".join(compare_parts)}</div>'
    boundary = str(item.get("boundary") or "").strip()
    mode = "stat" if item.get("display_mode") == "stat" and item.get("complete") is True else "prose"
    main = f'<div class="number-main">{_esc(value)}<small>{_esc(unit)}</small></div>' if value else ""
    if compact:
        compact_meta = str(item.get("display_note") or "").strip() or " · ".join(
            f"{label}：{content}"
            for label, content in (
                (reader_label("denominator", "统计对象"), item.get("denominator")),
                (reader_label("period", "统计时间"), item.get("period")),
            )
            if content
        )
        return (
            f'<aside class="number-story {mode} compact" data-number-story-id="{_esc(item.get("id") or "")}">'
            f'<div class="number-compact-head">{main}<div class="number-detail">'
            f'<div class="number-title">{_esc(title)}</div>'
            f'<div class="number-compact-meta">{_esc(compact_meta)}</div></div></div>'
            f'<div class="number-boundary"><strong>{_esc(reader_label("boundary", "需要注意"))}：</strong>'
            f'{_esc(boundary)}</div></aside>'
        )
    return (
        f'<aside class="number-story {mode}" data-number-story-id="{_esc(item.get("id") or "")}">'
        f'{main}<div class="number-detail"><div class="number-title">{_esc(title)}</div>'
        f'<dl class="number-meta">{meta}</dl>{compare}'
        f'<div class="number-boundary">{_esc(reader_label("boundary", "这个数字不能说明什么"))}：'
        f'{_esc(boundary)}</div></div></aside>'
    )


def _render_listening_card(card: dict) -> str:
    """Render registered audio as a prompt-led, evidence-bounded listening experience."""
    tracks = [
        track for track in (card.get("tracks") or [])
        if isinstance(track, dict) and track.get("registered") is True and track.get("url")
    ]
    if not tracks:
        return ""
    card_id = str(card.get("id") or "listening-card").strip()
    parts = [f'<section class="listening-card" data-listening-card data-listening-card-id="{_esc(card_id)}">']
    parts.append('<div class="listening-head">')
    parts.append(f'<h3 class="listening-title">{_esc(card.get("title") or "听一听模型真正做出了什么")}</h3>')
    if card.get("intro"):
        parts.append(f'<p class="listening-intro">{_esc(card.get("intro"))}</p>')
    parts.append('</div><div class="listening-tabs" role="tablist" aria-label="切换试听样曲">')
    for index, track in enumerate(tracks):
        active = " active" if index == 0 else ""
        selected = "true" if index == 0 else "false"
        tabindex = "0" if index == 0 else "-1"
        tab_id = f"{card_id}-tab-{index + 1}"
        panel_id = f"{card_id}-panel-{index + 1}"
        parts.append(
            f'<button type="button" class="listening-tab{active}" id="{_esc(tab_id)}" role="tab" '
            f'data-listening-tab="{index}" aria-controls="{_esc(panel_id)}" aria-selected="{selected}" tabindex="{tabindex}">'
            f'{_esc(track.get("label") or f"样曲 {index + 1}")}</button>'
        )
    parts.append('</div>')
    for index, track in enumerate(tracks):
        hidden = "" if index == 0 else " hidden"
        tab_id = f"{card_id}-tab-{index + 1}"
        panel_id = f"{card_id}-panel-{index + 1}"
        parts.append(
            f'<div class="listening-panel" id="{_esc(panel_id)}" role="tabpanel" '
            f'data-listening-panel="{index}" aria-labelledby="{_esc(tab_id)}"{hidden}>'
        )
        parts.append(
            f'<audio controls preload="none" data-listening-audio src="{_esc(track.get("url"))}">'
            '当前浏览器无法播放这段音频。</audio>'
        )
        parts.append(
            '<div class="listening-prompt"><span class="listening-label">生成提示词</span>'
            f'{_esc(track.get("prompt") or "未提供")}</div>'
        )
        points = [str(point).strip() for point in (track.get("listening_points") or []) if str(point).strip()]
        if points:
            parts.append('<span class="listening-label">重点听什么</span><ul class="listening-points">')
            parts.extend(f'<li>{_esc(point)}</li>' for point in points)
            parts.append('</ul>')
        if track.get("lyrics_excerpt"):
            parts.append(
                '<details class="listening-lyrics"><summary>歌词摘录</summary>'
                f'<p>{_esc(track.get("lyrics_excerpt"))}</p></details>'
            )
        parts.append('</div>')
    if card.get("boundary"):
        parts.append(f'<p class="listening-boundary">边界：{_esc(card.get("boundary"))}</p>')
    parts.append('</section>')
    return "".join(parts)


def _render_section(
    sec: dict,
    idx: int,
    visuals: list,
    experiments: list | None = None,
    case_stories: list | None = None,
    source_media: list | None = None,
    illustrations: list | None = None,
    number_stories: list | None = None,
    listening_cards: list | None = None,
    term_refs: list[dict] | None = None,
    margin_citations: list[dict] | None = None,
) -> str:
    """渲染正文段落，并用编号把来源引文关联到右侧旁注。"""
    title = _esc(_section_display_title(sec))
    content = sec.get("content") or ""
    analogies = sec.get("analogies") or []
    transition_hook = str(sec.get("transition_hook") or "").strip()

    parts = []
    if title:
        parts.append(f'<h2 id="{_section_dom_id(sec, idx)}">{title}</h2>')
    if content:
        parts.append(_render_prose_paragraphs(content, term_refs))
    parts.append(_render_analogies_inline(analogies))
    # Terminology and full quotations live in the off-flow margin rail.
    parts.append(_render_margin_citations(margin_citations or []))

    for item in source_media or []:
        parts.append(_render_source_media(item))
    for item in illustrations or []:
        parts.append(_render_ai_illustration(item))

    # 先给读者结论型视觉，再提供数字卡与可展开实验细节。
    for v in visuals:
        parts.append(_render_visual(v))

    for item in number_stories or []:
        parts.append(_render_number_story(item))
    for card in listening_cards or []:
        parts.append(_render_listening_card(card))

    for story in case_stories or []:
        parts.append(_render_case_story(story))
    for experiment in experiments or []:
        parts.append(_render_experiment(experiment))

    if transition_hook:
        parts.append(f'<p class="transition-hook">{_esc(transition_hook)}</p>')

    return "".join(parts)


def _assign_visuals_to_sections(sections: list, visuals: list) -> tuple[dict[int, list], list]:
    """把每个视觉组件最多分配一次；显式锚点优先，关键词仅作兼容回退。"""
    assigned: dict[int, list] = {i: [] for i in range(len(sections))}
    leftovers = []
    for visual in visuals:
        target = None
        has_explicit_anchor = any(
            key in visual and visual.get(key) not in (None, "")
            for key in ("after_section_id", "section_index", "section_tag")
        )

        anchor_id = str(visual.get("after_section_id") or "").strip()
        if anchor_id:
            for i, section in enumerate(sections):
                raw_id = str(section.get("id") or "").strip()
                if anchor_id in {raw_id, _section_dom_id(section, i), f"sec-{i}"}:
                    target = i
                    break

        if target is None and "section_index" in visual:
            raw_index = visual.get("section_index")
            if isinstance(raw_index, int) and not isinstance(raw_index, bool) and 0 <= raw_index < len(sections):
                target = raw_index

        anchor_tag = str(visual.get("section_tag") or "").strip().casefold()
        if target is None and anchor_tag:
            for i, section in enumerate(sections):
                if str(section.get("tag") or "").strip().casefold() == anchor_tag:
                    target = i
                    break

        if target is None and not has_explicit_anchor:
            visual_title = str(visual.get("title") or "").casefold()
            for i, section in enumerate(sections):
                tag = str(section.get("tag") or "").strip().casefold()
                title = str(section.get("title") or "").strip().casefold()
                keywords = [word for word in re.split(r"\s+", title) if len(word) > 2]
                if (tag and tag in visual_title) or any(word in visual_title for word in keywords):
                    target = i
                    break

        if target is None:
            leftovers.append(visual)
        else:
            assigned[target].append(visual)
    return assigned, leftovers


def _render_action_card(card: dict) -> str:
    if not card:
        return ""
    items = card.get("items") or []
    code_block = card.get("code_block") or ""
    if not items and not code_block:
        return ""
    parts = ['<div class="action-card">']
    if items:
        li = "".join(f"<li>{_esc(item)}</li>" for item in items)
        parts.append(f'<ul class="action-items">{li}</ul>')
    if code_block:
        parts.append(f'<pre class="action-code">{_esc(code_block)}</pre>')
    parts.append('</div>')
    return "".join(parts)


def _render_takeaway_list(items: list) -> str:
    if not items:
        return ""
    parts = ['<div class="takeaway-list">']
    for item in items:
        clean = item.replace("\u2705", "").strip()
        parts.append(
            '<div class="takeaway-item">'
            '<span class="takeaway-check">\u2705</span>'
            f'<span>{_esc(clean)}</span>'
            '</div>'
        )
    parts.append('</div>')
    return "".join(parts)


def _render_quick_scan(items: list) -> str:
    points = [str(item).strip() for item in items if str(item).strip()][:3]
    if not points:
        return ""
    return (
        '<section class="quick-scan" aria-labelledby="quick-scan-title">'
        '<div class="quick-scan-title" id="quick-scan-title">一分钟速览</div>'
        '<ul class="quick-scan-list">'
        + "".join(f"<li>{_esc(point)}</li>" for point in points)
        + "</ul></section>"
    )


def _render_evidence_gallery(items: list) -> str:
    figures = []
    for item in items:
        if not isinstance(item, dict) or item.get("registered") is not True:
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        caption = str(item.get("caption") or item.get("section_title") or "原始证据").strip()
        source_url = str(item.get("source_url") or "").strip()
        media_type = str(item.get("type") or "image").lower()
        preview_url = str(item.get("poster_url") or url).strip()
        if media_type == "video" and not item.get("poster_url"):
            media = '<div class="number-context">视频证据</div>'
        else:
            media = f'<img src="{_esc(preview_url)}" alt="{_esc(caption)}" loading="lazy" decoding="async">'
        media_link_label = "查看视频" if media_type == "video" else "查看原图"
        links = [f'<a href="{_esc(url)}" target="_blank" rel="noopener">{media_link_label}</a>']
        if source_url:
            links.append(f'<a href="{_esc(source_url)}" target="_blank" rel="noopener">来源页面</a>')
        source_label = str(item.get("source_label") or "").strip()
        source_prefix = "视频来源" if media_type == "video" else "图内来源"
        label_html = f'<br>{source_prefix}：{_esc(source_label)}' if source_label else ""
        figures.append(
            f'<figure data-media-id="{_esc(item.get("media_id") or "")}">'
            f'{media}<figcaption>{_esc(caption)}{label_html}<br>{" · ".join(links)}</figcaption></figure>'
        )
    if not figures:
        return ""
    return (
        '<details class="evidence-gallery"><summary>原始证据图库 '
        f'({len(figures)})</summary><div class="evidence-gallery-grid">'
        f'{"".join(figures)}</div></details>'
    )


# ── 主渲染函数 ─────────────────────────────────────────────


def render_html(article: Article, distilled: dict) -> str:
    d_title = distilled.get("distilled_title") or "AI \u84B8\u998F\u89E3\u8BFB"
    one_liner = distilled.get("one_liner") or ""
    category_tags = distilled.get("category_tags") or []
    source_bias = distilled.get("source_bias_declaration") or ""
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
    source_notes = distilled.get("source_notes") or ""
    site_note = distilled.get("site_note") or ""
    further_reading = distilled.get("further_reading") or []
    background = distilled.get("background") or ""

    # 向后兼容
    if not sections and key_points:
        sections = [
            {"tag": "", "title": p.get("title", ""), "content": p.get("insight", ""),
             "archive_original": [{"original": "", "translation": p.get("evidence", "")}]}
            for p in key_points
        ]
    # 构建各部分
    tags_html = _render_category_tags(category_tags)
    rec_reason_html = _render_rec_reason(recommendation_reason)
    quick_scan_html = _render_quick_scan(quick_scan)
    toc_html = _render_toc(sections)
    glossary_html, term_refs, margin_citations = _build_margin_rail(sections)

    # 正文 = 段落 + 一次性分配的视觉组件；未命中锚点的组件保留在末尾。
    section_visuals, leftover_items = _assign_visuals_to_sections(sections, visuals)
    section_experiments, leftover_experiments = _assign_visuals_to_sections(sections, experiments)
    section_cases, leftover_cases = _assign_visuals_to_sections(sections, case_stories)
    section_media, _leftover_media = _assign_visuals_to_sections(
        sections,
        [item for item in source_media if isinstance(item, dict) and item.get("registered") is True],
    )
    section_illustrations, leftover_illustrations = _assign_visuals_to_sections(
        sections,
        [item for item in illustrations if isinstance(item, dict) and item.get("status") == "generated"],
    )
    section_numbers, leftover_numbers = _assign_visuals_to_sections(sections, number_stories)
    section_listening, leftover_listening = _assign_visuals_to_sections(
        sections,
        [item for item in listening_cards if isinstance(item, dict) and item.get("registered") is True],
    )
    sections_html = "".join(
        _render_section(
            section,
            i,
            section_visuals[i],
            section_experiments[i],
            section_cases[i],
            section_media[i],
            section_illustrations[i],
            section_numbers[i],
            section_listening[i],
            term_refs[i],
            margin_citations[i],
        )
        for i, section in enumerate(sections)
    )
    leftover_depth = "".join(_render_case_story(x) for x in leftover_cases)
    leftover_depth += "".join(_render_experiment(x) for x in leftover_experiments)
    leftover_visuals = "".join(_render_visual(v) for v in leftover_items)
    leftover_visuals += "".join(_render_ai_illustration(v) for v in leftover_illustrations)
    leftover_visuals += "".join(_render_number_story(v) for v in leftover_numbers)
    leftover_visuals += "".join(_render_listening_card(v) for v in leftover_listening)

    action_html = _render_action_card(action_card)
    takeaway_html = _render_takeaway_list(takeaway_list)
    evidence_gallery_html = _render_evidence_gallery(evidence_gallery)
    source_panel_html = _render_source_panel(
        article,
        further_reading,
        site_note or source_notes or source_bias,
        fact_check,
    )

    # 组装
    body_html = ""
    if sections_html or leftover_depth or leftover_visuals:
        body_html = f'<div class="article-body">{sections_html}{leftover_depth}{leftover_visuals}</div>'

    # 背景补充（向后兼容）
    background_html = ""
    if background and not any(s.get("content") == background for s in sections):
        background_html = f'<div class="article-body"><h2>\u80CC\u666F\u8865\u5145</h2><p>{_esc(background)}</p></div>'

    one_liner_html = f'<div class="sub-title">{_esc(one_liner)}</div>' if one_liner else ""

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(d_title)}</title>
<style>{_CSS}</style>
</head>
<body>

<div class="theme-switcher">
  <div class="theme-btn theme-light active" onclick="setTheme('light')" title="\u4EAE\u8272"></div>
  <div class="theme-btn theme-dark" onclick="setTheme('dark')" title="\u6697\u8272"></div>
  <div class="theme-btn theme-sepia" onclick="setTheme('sepia')" title="\u62A4\u773C"></div>
</div>

<a class="scroll-top" id="scrollTop" href="#article-top" aria-label="返回文章顶部" title="返回文章顶部">\u2191</a>

<div class="wrap">
  <header id="article-top">
    {tags_html}
    <h1>{_esc(d_title)}</h1>
    {one_liner_html}
  </header>

  {rec_reason_html}
  {quick_scan_html}
  {toc_html}
  {glossary_html}
  {body_html}
  {background_html}
  {action_html}
  {takeaway_html}
  {evidence_gallery_html}
  {source_panel_html}

</div>

<script>
function setTheme(t){{
  document.body.setAttribute('data-theme',t);
  document.querySelectorAll('.theme-btn').forEach(b=>b.classList.remove('active'));
  document.querySelector('.theme-'+t).classList.add('active');
  try{{localStorage.setItem('ad-theme',t)}}catch(e){{}}
}}
(function(){{
  try{{
    var t=localStorage.getItem('ad-theme');
    if(t) setTheme(t);
  }}catch(e){{}}
}})();
window.addEventListener('scroll',function(){{
  var b=document.getElementById('scrollTop');
  if(window.scrollY>400) b.classList.add('show'); else b.classList.remove('show');
}});
document.getElementById('scrollTop').addEventListener('click',function(event){{
  var target=document.getElementById('article-top');
  if(!target) return;
  event.preventDefault();
  target.scrollIntoView({{behavior:'smooth',block:'start'}});
}});
function syncReadingRails(){{
  var wide=window.matchMedia('(min-width:1240px)').matches;
  document.querySelectorAll('[data-reading-rail]').forEach(function(rail){{rail.open=wide}});
}}
document.querySelectorAll('[data-reading-rail]').forEach(function(rail){{
  rail.addEventListener('toggle',function(){{
    if(!rail.open || window.matchMedia('(min-width:1240px)').matches) return;
    document.querySelectorAll('[data-reading-rail]').forEach(function(other){{
      if(other!==rail) other.open=false;
    }});
  }});
}});
var railMedia=window.matchMedia('(min-width:1240px)');
if(railMedia.addEventListener) railMedia.addEventListener('change',syncReadingRails);
syncReadingRails();
if('IntersectionObserver' in window){{
  var tocLinks=Array.from(document.querySelectorAll('.toc-link[data-section-target]'));
  var byId=new Map(tocLinks.map(function(link){{return [link.dataset.sectionTarget,link]}}));
  var observer=new IntersectionObserver(function(entries){{
    entries.forEach(function(entry){{
      if(!entry.isIntersecting) return;
      tocLinks.forEach(function(link){{link.classList.remove('active')}});
      var link=byId.get(entry.target.id); if(link) link.classList.add('active');
    }});
  }},{{rootMargin:'-18% 0px -68% 0px',threshold:0}});
  byId.forEach(function(_link,id){{var heading=document.getElementById(id);if(heading) observer.observe(heading)}});
}}
function positionTermPopover(wrapper){{
  var marker=wrapper&&wrapper.querySelector('.term-marker');
  var popover=wrapper&&wrapper.querySelector('.term-popover');
  if(!marker || !popover) return;
  var rect=marker.getBoundingClientRect();
  var half=Math.min(150,Math.max(120,(window.innerWidth-24)/2));
  var article=wrapper.closest('.article-body');
  var bounds=article?article.getBoundingClientRect():{{left:12,right:window.innerWidth-12}};
  var minCenter=Math.max(half+12,bounds.left+half);
  var maxCenter=Math.min(window.innerWidth-half-12,bounds.right-half);
  if(maxCenter<minCenter){{minCenter=half+12;maxCenter=window.innerWidth-half-12}}
  var center=Math.max(minCenter,Math.min(maxCenter,rect.left+rect.width/2));
  var placeBelow=rect.top<190;
  wrapper.style.setProperty('--term-popover-left',(center-rect.left)+'px');
  wrapper.style.setProperty('--term-popover-top',(placeBelow?rect.height:0)+'px');
  popover.classList.toggle('below',placeBelow);
}}
document.querySelectorAll('.term-marker-wrap').forEach(function(wrapper){{
  wrapper.addEventListener('mouseenter',function(){{positionTermPopover(wrapper)}});
  wrapper.addEventListener('focusin',function(){{positionTermPopover(wrapper)}});
}});
function closeTermPopovers(except){{
  document.querySelectorAll('.term-marker-wrap.is-open').forEach(function(wrapper){{
    if(wrapper===except) return;
    wrapper.classList.remove('is-open');
    var button=wrapper.querySelector('[data-term-popover-toggle]');
    if(button){{
      button.setAttribute('aria-expanded','false');
      if(document.activeElement===button) button.blur();
    }}
  }});
}}
document.addEventListener('click',function(event){{
  var openToc=document.querySelector('.toc-card[open]');
  if(openToc && !event.target.closest('.toc-card')) openToc.open=false;
  var termButton=event.target.closest('[data-term-popover-toggle]');
  if(termButton){{
    event.preventDefault();
    var wrapper=termButton.closest('.term-marker-wrap');
    var shouldOpen=!wrapper.classList.contains('is-open');
    closeTermPopovers(wrapper);
    wrapper.classList.toggle('is-open',shouldOpen);
    termButton.setAttribute('aria-expanded',shouldOpen?'true':'false');
    if(shouldOpen) positionTermPopover(wrapper);
    else termButton.blur();
    return;
  }}
  if(!event.target.closest('.term-popover')) closeTermPopovers();
  var citation=event.target.closest('[data-margin-note-target]');
  if(citation){{
    event.preventDefault();
    var note=document.getElementById(citation.getAttribute('data-margin-note-target'));
    var rail=note&&note.closest('[data-reading-rail="margin"]');
    if(!note || !rail) return;
    if(!window.matchMedia('(min-width:1240px)').matches) rail.open=true;
    document.querySelectorAll('.margin-note.is-highlighted').forEach(function(item){{
      item.classList.remove('is-highlighted');
    }});
    note.classList.add('is-highlighted');
    note.focus({{preventScroll:true}});
    note.scrollIntoView({{behavior:'smooth',block:'nearest'}});
    try{{history.replaceState(null,'','#'+note.id)}}catch(e){{}}
    window.setTimeout(function(){{note.classList.remove('is-highlighted')}},2200);
    return;
  }}
  var button=event.target.closest('[data-interactive-mode]');
  if(!button) return;
  var root=button.closest('[data-interactive-compare]');
  if(!root) return;
  var mode=button.getAttribute('data-interactive-mode');
  root.querySelectorAll('[data-interactive-mode]').forEach(function(item){{
    var active=item.getAttribute('data-interactive-mode')===mode;
    item.classList.toggle('active',active);
    item.setAttribute('aria-pressed',active?'true':'false');
  }});
  root.querySelectorAll('[data-interactive-state]').forEach(function(item){{
    item.hidden=item.getAttribute('data-interactive-state')!==mode;
  }});
}});
document.addEventListener('click',function(event){{
  var metricButton=event.target.closest('[data-metric-tab]');
  if(metricButton){{
    var metricRoot=metricButton.closest('[data-metric-bars]');
    if(!metricRoot) return;
    var metric=metricButton.getAttribute('data-metric-tab');
    metricRoot.querySelectorAll('[data-metric-tab]').forEach(function(item){{
      var active=item.getAttribute('data-metric-tab')===metric;
      item.classList.toggle('active',active);
      item.setAttribute('aria-pressed',active?'true':'false');
    }});
    metricRoot.querySelectorAll('[data-metric-panel]').forEach(function(item){{
      item.hidden=item.getAttribute('data-metric-panel')!==metric;
    }});
    return;
  }}
  var button=event.target.closest('[data-scenario-tab]');
  if(!button) return;
  var root=button.closest('[data-scenario-calculator]');
  if(!root) return;
  var tab=button.getAttribute('data-scenario-tab');
  root.querySelectorAll('[data-scenario-tab]').forEach(function(item){{
    var active=item.getAttribute('data-scenario-tab')===tab;
    item.classList.toggle('active',active);
    item.setAttribute('aria-pressed',active?'true':'false');
  }});
  root.querySelectorAll('[data-scenario-panel]').forEach(function(item){{
    item.hidden=item.getAttribute('data-scenario-panel')!==tab;
  }});
}});
document.querySelectorAll('[data-metric-bars]').forEach(function(root){{
  root.classList.add('metric-bars-ready');
  root.querySelectorAll('[data-metric-panel]').forEach(function(item,index){{item.hidden=index!==0;}});
}});
document.addEventListener('click',function(event){{
  var button=event.target.closest('[data-rank-tab]');
  if(!button) return;
  var root=button.closest('[data-rank-bars]');
  if(!root) return;
  var tab=button.getAttribute('data-rank-tab');
  root.querySelectorAll('[data-rank-tab]').forEach(function(item){{
    var active=item.getAttribute('data-rank-tab')===tab;
    item.classList.toggle('active',active);
    item.setAttribute('aria-pressed',active?'true':'false');
  }});
  root.querySelectorAll('[data-rank-panel]').forEach(function(item){{
    item.hidden=item.getAttribute('data-rank-panel')!==tab;
  }});
}});
document.querySelectorAll('[data-rank-bars]').forEach(function(root){{
  root.classList.add('rank-bars-ready');
  root.querySelectorAll('[data-rank-panel]').forEach(function(item,index){{item.hidden=index!==0;}});
}});
function setFlowStep(root,index){{
  var tabs=Array.from(root.querySelectorAll('[data-flow-step]'));
  var panels=Array.from(root.querySelectorAll('[data-flow-panel]'));
  if(!tabs.length || index<0 || index>=tabs.length) return;
  tabs.forEach(function(item,itemIndex){{
    var active=itemIndex===index;
    item.classList.toggle('active',active);
    item.setAttribute('aria-pressed',active?'true':'false');
  }});
  panels.forEach(function(item,itemIndex){{item.classList.toggle('active',itemIndex===index);}});
  root.setAttribute('data-flow-current',String(index));
  var prev=root.querySelector('[data-flow-prev]');
  var next=root.querySelector('[data-flow-next]');
  if(prev) prev.disabled=index===0;
  if(next) next.disabled=index===tabs.length-1;
}}
document.querySelectorAll('[data-flow-stepper]').forEach(function(root){{
  root.classList.add('flow-stepper-ready');
  setFlowStep(root,0);
}});
document.addEventListener('click',function(event){{
  var tab=event.target.closest('[data-flow-step]');
  var control=event.target.closest('[data-flow-prev],[data-flow-next]');
  var root=(tab||control)&&(tab||control).closest('[data-flow-stepper]');
  if(!root) return;
  if(tab){{setFlowStep(root,Number(tab.getAttribute('data-flow-step')));return;}}
  var current=Number(root.getAttribute('data-flow-current')||0);
  setFlowStep(root,current+(control.matches('[data-flow-prev]')?-1:1));
}});
document.querySelectorAll('[data-strategy-tabs]').forEach(function(root){{
  root.classList.add('strategy-tabs-ready');
  root.querySelectorAll('[data-strategy-panel]').forEach(function(item,index){{
    item.classList.toggle('active',index===0);
  }});
}});
document.addEventListener('click',function(event){{
  var button=event.target.closest('[data-strategy-tab]');
  if(!button) return;
  var root=button.closest('[data-strategy-tabs]');
  if(!root) return;
  var selected=button.getAttribute('data-strategy-tab');
  root.querySelectorAll('[data-strategy-tab]').forEach(function(item){{
    var active=item.getAttribute('data-strategy-tab')===selected;
    item.classList.toggle('active',active);
    item.setAttribute('aria-selected',active?'true':'false');
  }});
  root.querySelectorAll('[data-strategy-panel]').forEach(function(item){{
    item.classList.toggle('active',item.getAttribute('data-strategy-panel')===selected);
  }});
}});
document.querySelectorAll('[data-timeline-scrubber]').forEach(function(root){{
  root.classList.add('timeline-scrubber-ready');
}});
document.addEventListener('input',function(event){{
  var input=event.target.closest('[data-timeline-input]');
  if(!input) return;
  var root=input.closest('[data-timeline-scrubber]');
  var state=root&&root.querySelector('[data-timeline-event="'+input.value+'"]');
  if(!state) return;
  var time=root.querySelector('[data-timeline-time]');
  var title=root.querySelector('[data-timeline-title]');
  var description=root.querySelector('[data-timeline-description]');
  if(time) time.textContent=state.getAttribute('data-time')||'';
  if(title) title.textContent=state.getAttribute('data-title')||'';
  if(description) description.textContent=state.getAttribute('data-description')||'';
}});
document.addEventListener('click',function(event){{
  var button=event.target.closest('[data-listening-tab]');
  if(!button) return;
  var root=button.closest('[data-listening-card]');
  if(!root) return;
  var tab=button.getAttribute('data-listening-tab');
  root.querySelectorAll('[data-listening-audio]').forEach(function(audio){{audio.pause();}});
  root.querySelectorAll('[data-listening-tab]').forEach(function(item){{
    var active=item.getAttribute('data-listening-tab')===tab;
    item.classList.toggle('active',active);
    item.setAttribute('aria-selected',active?'true':'false');
    item.setAttribute('tabindex',active?'0':'-1');
  }});
  root.querySelectorAll('[data-listening-panel]').forEach(function(item){{
    item.hidden=item.getAttribute('data-listening-panel')!==tab;
  }});
}});
document.addEventListener('play',function(event){{
  if(!event.target.matches('[data-listening-audio]')) return;
  document.querySelectorAll('[data-listening-audio]').forEach(function(audio){{
    if(audio!==event.target) audio.pause();
  }});
}},true);
document.addEventListener('input',function(event){{
  var input=event.target.closest('[data-scenario-input]');
  if(!input) return;
  var root=input.closest('[data-scenario-calculator]');
  if(!root) return;
  var value=parseFloat(input.value);
  var base=parseFloat(root.getAttribute('data-scenario-base'));
  var decimals=parseInt(root.getAttribute('data-scenario-decimals')||'2',10);
  if(!Number.isFinite(value)||!Number.isFinite(base)) return;
  var inputOutput=root.querySelector('[data-scenario-input-value]');
  var resultOutput=root.querySelector('[data-scenario-result]');
  var prefix=root.getAttribute('data-scenario-prefix')||'';
  var inputPrefix=root.getAttribute('data-scenario-input-prefix')||'';
  var inputSuffix=root.getAttribute('data-scenario-input-suffix')||'';
  if(inputOutput) inputOutput.textContent=inputPrefix+value.toFixed(2)+inputSuffix;
  if(resultOutput) resultOutput.textContent=prefix+(base-value).toFixed(decimals);
}});
document.addEventListener('input',function(event){{
  var input=event.target.closest('[data-capacity-input]');
  if(!input) return;
  var root=input.closest('[data-capacity-curve]');
  if(!root) return;
  var value=Number(input.value);
  var nearest=null;
  var distance=Infinity;
  root.querySelectorAll('[data-capacity-state]').forEach(function(state){{
    var current=Math.abs(Number(state.getAttribute('data-position'))-value);
    if(current<distance){{distance=current;nearest=state;}}
  }});
  if(!nearest) return;
  var label=root.querySelector('[data-capacity-label]');
  var result=root.querySelector('[data-capacity-result]');
  if(label) label.textContent=nearest.getAttribute('data-label')||'';
  if(result) result.textContent=nearest.getAttribute('data-result')||'';
}});
document.addEventListener('click',function(event){{
  var button=event.target.closest('[data-cost-tab]');
  if(!button) return;
  var root=button.closest('[data-cost-ledger]');
  if(!root) return;
  var tab=button.getAttribute('data-cost-tab');
  root.querySelectorAll('[data-cost-tab]').forEach(function(item){{
    var active=item.getAttribute('data-cost-tab')===tab;
    item.classList.toggle('active',active);
    item.setAttribute('aria-pressed',active?'true':'false');
  }});
  root.querySelectorAll('[data-cost-panel]').forEach(function(item){{
    item.hidden=item.getAttribute('data-cost-panel')!==tab;
  }});
}});
document.addEventListener('keydown',function(event){{
  if(event.key==='Escape'){{
    closeTermPopovers();
    var openToc=document.querySelector('.toc-card[open]');
    if(openToc) openToc.open=false;
  }}
}});
</script>
</body>
</html>"""
