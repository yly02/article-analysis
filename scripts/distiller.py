"""LLM 解读模块：把原文喂给大模型，输出结构化解读 JSON。

v9.11：三阶段质量链、补丁式主编审校、PDF/Word 本地输入、流式 LLM、来源快照和可恢复检查点。
默认通过研究、写作、编辑审校三阶段产出深度文章结构化 JSON。
输出包含一分钟速览、论点式段落、证据边界、行动建议和可视化。

使用 OpenAI 兼容接口，因此 DeepSeek / 智谱 / 通义 / Kimi 等国内模型均可直接用。
配置优先级：环境变量 > config.json > 默认值。
"""

from __future__ import annotations

import copy
import json
import hashlib
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from fetcher import Article
from editorial_quality import assert_publishable, audit_distilled
from evidence import normalize_distilled, url_key
from language_quality import apply_safe_language_fixes


_COMMON_MODE_RULES = """共同规则：
- 只使用原文、已抓取证据材料和研究账本；不得新增材料外的事实、URL、数字、产品、价格或日期。
- 原文和 official 官方附件自证只能写“原文声称”；supplemental 只能补充背景；只有已抓取 independent 来源支持时才能写“交叉验证”。
- research_ledger 中 importance=high 的 claim 必须进入 covered_claim_ids，或在 omitted_claims 中给出具体理由。
- 日期、数量和单位只保留一种清楚格式；不要把同一信息换一种写法放进括号，例如不得写 `2026-07-31（2026 年 7 月 31 日）`。
- unknowns、限制条件和反例不能被改写成确定结论。
- 成品正文直接陈述事实、机制和判断，不以“原文说、原博客强调、本文发现、当前材料显示”等研究过程话术组织段落。需要说明来源时点名具体主体或资料（如厂商测试、模型卡、许可条款）；需要表达限制时自然写“官方尚未公布”“没有独立复现”“现有数据不足以支持”。`原文声称` 等审计术语只放在 fact_check、source_notes 和研究账本中。
- 严格输出 JSON，不要使用 markdown 代码块，不要输出解释文字。
"""


_FULL_VOICE_GUIDE = """深度文章写作总纲：真实为底，讲透为骨，人话为形，朋友感为声。
- 默认读者是希望了解 AI 并进入该领域的聪明初学者。成品要能作为博客和视频母稿，但首先是一篇自然、完整、值得读下去的文章。
- 动笔前完成一条内部写作链：唯一核心机制与独特见解 -> 目标读者与真实判断困难 -> 开头真实锚点 -> 读者具体利害 -> 有材料依据的共鸣 -> 可辩护立场与改变条件 -> 读后判断。缺一项就先补策划，不用文风掩盖内容缺口。
- 全文只保留一个一句话因果机制。事实、案例、术语和观点只能证明、解释、限制或应用它；独特见解必须从材料中的机制、矛盾、取舍或后果推出。
- 标题先争取点击，再由首屏兑现。存在高认知公司、平台、产品或人物时，title_contract.recognition_anchor 只填一个常用名，该名称必须逐字出现在标题前半句；陌生型号或项目代号必须紧跟其知名归属方，不能单独占据标题第一认知位。再接真实动作、反常结果、明确后果或口径完整的关键数字；不能制造材料外人物、动作、数字、结果和极限结论。
- 写标题前建立 title_contract：只选一个 click_reason，写清标题承诺和不能越过的证据边界。标题不靠形容词堆冲击力；数字只有分母、时间和口径完整时才进入标题。
- 新闻、案件和事件型材料先讲清谁、何时、何地、做了什么、结果怎样。开头优先使用材料中能代表中心矛盾的真实小事、人物动作、反常结果或数字，并完成 opening_sequence 的“真实细节 -> 矛盾转折 -> 事件主体与机制”；没有合适锚点就直接陈述事实。
- 解释型文章优先采用“具体处境/例子 -> 它为什么反常 -> 一句核心判断 -> 机制与规则”的进入顺序。先让读者看见问题，再介绍仓库、参数或目录；一句有记忆点的判断后必须紧跟具体动作、例子或证据，不能让金句替代论证。
- 规则和参数先写成读者能想象的动作，再给专业名词、比例或实现细节；抽象规则至少配一个真实例子或准确类比。若一段同时承担事实、技术、边界和许可说明，拆成相邻短段，并把边界贴回它约束的主张。
- 章节标题按问题、动作、结果或选择标记推进，避免把正文切成“背景、分析、影响、总结”的空分类；读者只看标题也应能复述从问题进入到最终判断的主线。
- 全文至少保留一句能被读者复述的“钉子判断”，把材料中的机制或矛盾重新命名；只出现一两次，并用具体动作、例子或证据兑现，不能反复当口号。
- 抽象规则先落到“谁在什么场景下做了什么”，再补比例、目录、脚本或术语。若找不到对应动作或画面，删掉规则或改成普通解释，不硬塞技术名词。
- 动笔前做一次 HKR 预检：选题是否有趣、是否有新知识、是否有材料支持的真实连接点。没有第一手经历时，不用虚构个人情绪，改用材料中的处境、冲突、取舍或后果建立共鸣。
- 多个模型、案例、报价或测试结果采用“逐一展示 + 升番”递进：先给基础现象，再给更明显的差异，最后保留最能改变判断的结果；每项只补事实性观察，不用吐槽制造材料外信息。
- 背景知识要像聊天时顺手想起的一块拼图，从当前例子自然引出；不要另起“科普一下”小节，不要为了哲学感强接文化参照物。
- 提出判断前先完整呈现合理的另一种选择和成立条件；方法论文章还要说清学习曲线、常见失败点和不适用场景。
- 可在开头埋下一个具体意象或问题，结尾最多回扣一次；转折处可有独立短句，但不让每段都靠金句、断句或情绪标点收束。
- 共鸣来自已核实的处境、冲突、取舍和后果。reader_stake 必须具体到一种判断、选择、成本或机会；不得虚构读者经历、内心戏、朋友案例、现场细节或第一人称体验。
- 立场要明确但可复核：说明判断依靠哪些事实、涉及什么取舍，以及什么条件会使判断改变。遇到真实合理异议，先准确呈现它及其成立条件，再补新证据；没有异议就不制造对手。
- 每一节只完成新发现、因果答案、认知反转、现实后果或可执行选择中的一种推进，并增加新信息。背景、术语和边界若不能推进主线，就合并或删除。
- 写正文前选择 event、investigation、product、research、multi-theme 或 explainer 中最适合材料的一个主原型，形成 chapter_system。每节登记角色、读者理解缺口、新增推进、关键证据和承接；原型允许删改，不允许把多套模板并排拼成目录。
- 知识只在主线需要时自然出现，先让读者遇到现象或问题，再补足刚好够用的背景。不要单独“科普一下”，也不要为了显得深刻强接历史、文化或哲学。
- 关键解释章节可用“具体问题 -> 前 1-2 句直接回答 -> 证据与原因 -> 适用边界”；其他章节从事件、结果、数据、例子、冲突或判断进入。不要把全文写成同一种问答模板。
- transition_hook 只提出下一节立即回答的自然追问，全文通常 3-5 处；不编造悬念，不与下一标题逐字重复，最后一节通常留空。
- 多个实验或案例按理解成本和信息张力递进，但不能重排真实时间线、改写证据强度或夸大差异。同一组开头例子不得在后文完整重播。
- 证据边界紧跟它约束的事实，在读者看懂事实后用一两句自然收住。严谨来自事实、判断和未知分层，不来自连续免责声明。
- 首次出现且妨碍理解的术语先讲作用，再给准确名称、条件和边界。存在稳定常用中文名时，导语或正文首次出现必须写成“原名（常用中文名）”，不能只用 concept_explainers 代替；人名、品牌、产品、代码、模型编号、文件名和大众熟悉缩写不机械翻译。译名不稳定时保留原名，标题、图表标题和表头不追加翻译括注。
- 语言优先具体主体和动作，长句承载必要条件，短句负责停顿和重点。较长 content 拆成 2-4 个自然段；不靠网络梗、粗口、感叹号、故意病句和频繁称呼读者制造朋友感。
- 标题、小标题和视觉卡片标题要让读者直接看出“谁做了什么”。不要用“如何被接住、被托住、被兜住、跑通闭环”等抽象动作代替调查、处理、回滚、验证等真实动作；隐喻若不能增加准确含义，就改成日常说法。
- 完稿后检查知识倾倒、段段金句、匀速句长、固定连接词、连续“不是 X 而是 Y”、虚构反问、假脆弱、假故事和强行升华。保留少数真正有力的句子，其余回到正常讲事。
- 结尾必须回答开头问题；若开头有自然意象、结果或疑问，可回扣一次。删掉最后一段若更有力，就提前结束。
- category_tags 输出 3-5 个用于长期归档的稳定大类名词，优先选择主体公司或机构、产品或模型家族、技术领域、应用领域、发布类型。中文标签 2-8 个汉字，纯英文不超过 12 个字符；不要写完整判断、动作、数据、证据边界或营销话术，也不要单独使用“AI、科技、行业”等无法有效归档的过宽词。
- 有三项以上对比、明确时间顺序、多步机制、层级依赖、因果分支或数字关系时优先可视化；一句话能讲清时不硬加组件。先写 reader_question，再按关系选组件：音视频证据用播放器或来源媒体；平级异同用 compare_table；平行策略的作用对象与限制用 strategy_tabs；同一指标的旧版/新版或调整前后用 delta_table；多对象多维支持状态用 status_matrix；条件决定结果并对应行动用 decision_table；同一口径的数值排序用 rank_bars；多口径双方案数字用 metric_bars；上下层依赖用 layer_stack；普通先后动作或因果链用 flow，复杂阶段可用 stepper；资格逐关淘汰用 funnel_flow；日期演进用 timeline，阶段解释较多可用 scrubber；切换条件改变结果用 interactive_compare；可靠基数加读者假设用 scenario_calculator；连续变量出现拐点用 capacity_curve；不同计入项目改变结论用 cost_ledger。交互只有在读者操作后能看到关系、状态或结果变化时才使用，不设置交互组件数量配额。
- 产品发布或模型演示若有多段内容不同的视频，先按“总览/首屏锚点、代表性案例、机制操作、前后差异、限制或应用场景”建立能力覆盖清单，再选择互补的 2-6 段；不因页面长度一刀切只留一段，也不为凑数量机械全收。正文开头明确依赖的首屏视频必须采用，或在 media_omissions 写出具体可核对的理由。
- 原文出现真实提示词、时间码、参考素材分工、旧版基线或平台入口时，不只做抽象总结：把会改变读者判断的片段整理成紧凑指令卡、分镜时间线、参考素材分层、代际对比或平台状态表；不要整段复制长提示词，也不要让组件与正文重复同一事实。
- 视觉布局先拆清维度，不能把整个组件粗暴判成“横向”或“纵向”。时间、流程、因果、前后变化和带解释的数字字段按主阅读顺序从上到下展开。`compare_table.data.layout` 按内容选择：叙事较长、需要强调每个主题时用 `paired`；列名固定、每行字段一致、需要快速逐行逐列扫视时用 `matrix` 表格；其余用 `stacked`。例如“环节 × Claude 职责 × 人的职责”应优先使用 `matrix`，窄屏允许单元格自然换行。
- 视觉颜色只表达固定语义，不能为了丰富页面随机上色。`primary` 表示主方案、核心结果或正向进展，用绿色；`baseline` 表示对照方案，用蓝色；`warning` 表示限制、条件或待确认项，用琥珀色；`danger` 只用于材料明确支持的风险、失败或损失，用红色。`compare_table.data.column_roles` 与 headers 一一对应；主题列和没有明确语义的列写 `neutral` 或留空。`stat.data.items[].tone` 使用同一套角色。无法确定时保持中性色。
"""


FULL_SYSTEM_PROMPT = _COMMON_MODE_RULES + _FULL_VOICE_GUIDE + """
你是中文深度解读主编。只生成完整文章，不生成一页纸和小红书卡片。目标读者渴望了解 AI 知识、资讯并进入 AI 领域，但未必具备技术背景。文章必须围绕一个中心问题形成“判断 -> 实验/证据 -> 机制/案例 -> 边界 -> 回答”的论证链，让聪明的非专业读者看懂、愿意读完，并获得一条有材料支撑的独特见解。

严格输出：
{
  "distilled_title": "从真实人物、动作、冲突或结果中提炼的营销标题；足够吸引点击，但不编造事实",
  "one_liner": "首屏导语；事件型材料用 1-2 句交代谁、何时、何地、做了什么、结果怎样",
  "category_tags": ["3-5 个归档型短标签，如主体、产品家族、技术领域和应用领域"],
  "quick_scan": ["严格 3 条、每条 35-60 字、合计不超过 180 字；依次回答它是什么/变了什么、为什么值得看/怎么起作用、读者最后该怎么判断或使用；不要把内部审计或孤立数字当作主句"],
  "recommendation_reason": "为什么值得读，不是摘要",
  "source_bias_declaration": "作者、利益关系、样本和来源局限",
  "narrative_plan": {
    "target_reader": "本篇具体面向哪类 AI 初学者，以及他们已有和缺少的认知",
    "reader_tension": "目标读者面对这件事时真实存在的担心、误解、错过或判断困难；只能来自材料及任务语境，不编造心理",
    "title_contract": {"recognition_anchor": "必须逐字进入标题前半句的一个高认知主体常用名；没有才填最具体对象", "click_reason": "标题唯一使用的真实冲突、反差、结果或关键数字", "reader_promise": "读完会弄清什么", "evidence_guardrail": "标题不能越过的事实边界"},
    "opening_anchor": "来自已读取材料、用于启动文章的真实小事、人物动作、反常结果或数字；没有合适锚点就写直接陈述事实",
    "opening_sequence": {"scene": "一到三个真实细节", "turn": "这些细节共同暴露的矛盾、反差或问题", "reveal": "主体、时间、动作和核心机制"},
    "reader_stake": "这件事具体影响目标读者哪一种判断、选择、成本或机会，不能泛写与每个人有关",
    "resonance_basis": "文章依靠哪项已核实处境、冲突、取舍或后果建立共鸣，并注明对应材料依据",
    "stance": "编辑站在哪个可辩护判断上、依据是什么、什么条件会改变判断",
    "reader_takeaway": "读完能复述的事件或机制、AI 领域意义与实用判断",
    "core_mechanism": "全文只保留的一句因果解释；所有章节都要证明、解释、限制或应用它",
    "distinctive_insight": "由材料中的机制、矛盾、取舍或后果推出，全文需要论证的独特观点",
    "central_question": "全文唯一中心问题",
    "short_answer": "先给出的简短回答",
    "section_logic": ["逐节写清：本节唯一任务、开场动作、关键证据、与上一节的承接关系"],
    "chapter_system": {"archetype": "event|investigation|product|research|multi-theme|explainer", "throughline": "全篇章节共同推进的主线动作", "chapters": [{"section_id": "对应 sections[].id", "role": "进入|发现|解释|举证|转折|后果|选择|收束", "reader_need": "本节解决的一个理解缺口，不必都写成问句", "advance": "相对上一节新增的事实、区别、机制、后果或选择", "evidence": "本节关键材料", "handoff": "下一节为何必须接着出现；没有自然承接时留空"}]},
    "closing_answer": "结尾如何回答中心问题"
  },
  "sections": [{
    "id": "全文唯一 ASCII id",
    "tag": "2-4 字内部分类，仅用于锚定，不写进章节标题",
    "title": "准确标记论证进度的具体标题；关键解释章节可用读者会问且本节能回答的问题，其他章节可用事件、结果或论点式标题",
    "content": "本节只完成一个主要任务；问题标题在前 1-2 句直接回答，其他章节从具体事件、结果、数据、例子、冲突或判断进入，再组织证据、解释和边界",
    "transition_hook": "可选：由下一节立即回答的自然追问；不适合时留空",
    "analogies": [{"concept": "概念", "analogy": "准确类比"}],
    "concept_explainers": [{"term": "术语", "definition": "定义", "analogy": "可选类比"}],
    "archive_original": [{"original": "仅在措辞不可替代时保留的逐字原句", "translation": "忠实中文翻译；默认空数组"}]
  }],
  "experiment_ledger": [{
    "id": "对应 research_ledger.experiments[].id",
    "title": "论点式实验标题",
    "after_section_id": "对应 sections[].id",
    "question": "实验回答的问题",
    "setup": "环境、流程和人工条件",
    "sample": "样本量、轮数或测试次数；未知就写未知",
    "models": ["材料明确出现的模型"],
    "metric": "指标与成功判定口径",
    "result": "包含必要数字和比较口径的结果",
    "control": "对照或基线；没有则写无明确对照",
    "limitations": "不能外推到什么",
    "claim_ids": ["research claim id"]
  }],
  "case_stories": [{
    "id": "对应 research_ledger.cases[].id",
    "title": "案例标题",
    "after_section_id": "对应 sections[].id",
    "source_mode": "reconstruction|quoted",
    "setup": "案例初始状态",
    "beats": [{"label": "阶段", "text": "有证据的动作或状态变化", "source_quote": "可选逐字引文"}],
    "outcome": "结果",
    "boundary": "案例不能证明什么",
    "claim_ids": ["research claim id"]
  }],
  "visuals": [{"type": "compare_table|strategy_tabs|delta_table|status_matrix|decision_table|rank_bars|metric_bars|layer_stack|flow|funnel_flow|stat|timeline|interactive_compare|scenario_calculator|capacity_curve|cost_ledger", "title": "标题", "after_section_id": "section id", "reader_question": "这个组件替读者回答什么问题", "data": {}}],
  "illustration_plan": [{"id": "ASCII id", "role": "mechanism|workflow|concept|case_context", "title": "标题", "after_section_id": "section id", "purpose": "帮助理解什么", "scene": "无文字画面与构图", "visual_mapping": [{"element": "画面元素", "meaning": "正文概念"}], "alt": "替代文本", "caption": "AI 概念示意，不是原始证据"}],
  "source_media": [{"media_id": "登记媒体 id", "type": "image|video", "url": "登记媒体 URL", "poster_url": "可选", "caption": "自然中文图注，说明画面是什么", "purpose": "它解释正文中的哪个具体概念、动作、案例或结果", "language": "zh|en|其他语言代码", "reader_note": "读者具体看哪里，以及这能帮助理解什么；外语素材必须用中文", "translation_note": "可选中文化说明", "after_section_id": "section id", "source_url": "素材上游来源 URL"}],
  "media_omissions": [{"media_id": "未采用的重要视频 id", "reason": "具体省略理由"}],
  "listening_cards": [{"id": "ASCII id", "title": "试听标题", "intro": "选择依据", "after_section_id": "section id", "boundary": "样曲证据边界", "tracks": [{"media_id": "audio 媒体 id", "label": "曲目标签", "prompt": "真实提示词", "lyrics_excerpt": "可选摘录", "listening_points": ["具体听感"]}]}],
  "number_stories": [{"id": "ASCII id", "title": "数字回答的问题", "value": "主数字", "unit": "单位", "denominator": "分母、样本或计时口径", "scope": "适用范围", "period": "时间口径", "baseline": "对照", "change": "变化", "boundary": "不能推出什么", "display_variant": "compact|expanded，默认 compact", "display_note": "紧凑展示的一句自然口径说明", "labels": {"denominator": "统计对象或计时口径", "scope": "适用场景", "period": "统计时间", "baseline": "对照情况", "change": "结果变化", "boundary": "这个数字不能说明什么"}, "source_url": "登记来源 URL", "source_asset_ids": ["媒体 id"], "claim_ids": ["metric claim id"], "after_section_id": "section id", "importance": "high|medium|low"}],
  "evidence_gallery": [{"media_id": "已登记媒体 id", "caption": "证据图说明", "claim_ids": ["claim id"]}],
  "fact_check": [{"claim": "关键主张", "verdict": "确认|原文声称|交叉验证|存疑|夸大|无法核实", "note": "理由", "evidence": [{"url": "输入中真实 URL", "source_type": "original|official|supplemental|independent", "publisher": "发布者", "quote": "短引文", "support": "支持什么"}]}],
  "action_card": {"items": ["行动建议"], "code_block": "可选"},
  "takeaway_list": ["行动导向结论"],
  "further_reading": [{"title": "补充材料的准确标题", "url": "输入中已读取且确实有助于继续理解的真实 URL"}],
  "site_note": "给读者看的 1-2 句来源属性与关键证据边界，不写核查过程",
  "source_notes": "来源与可信度说明",
  "editorial_coverage": {"covered_claim_ids": ["c1"], "omitted_claims": [{"id": "c2", "reason": "具体理由"}]}
}

额外要求：
- sections 至少 3 段，每段 id 稳定且唯一；不要用多个相似段落重复同一结论。
- archive_original 默认留空，全文最多 2 条。仅当原句措辞本身影响理解、转述会损失关键含义，或争议性主张需要核对措辞时保留；普通事实、数字、结论和已有证据图支持的内容直接融入正文并标注来源，不为丰富侧栏重复摘引。
- 关键解释章节可以使用具体问题标题，content 前 1-2 句必须直接回答；不得连续抛出多个问题后才统一作答，也不得用材料无法回答的问题吸引点击。不要把所有章节机械写成问答，其他章节应按材料从事件、结果、数据、例子、冲突或明确判断进入。
- transition_hook 全文通常使用 3-5 次，只问下一节确实会回答的问题；下一标题可压缩重述但不得逐字复制，不编造悬念，最后一节通常留空。
- distilled_title 可以从原题与证据材料中重新选择最有点击动机的事实角度，允许使用冲突、反差、后果和口语化表达；但 title_contract.recognition_anchor 必须逐字出现在标题前半句，陌生项目名不能隐去其知名归属方。标题承诺必须在首屏兑现，不能编造人物、动作、数字或结果。
- 产品发布若有明确、可核验且构成真实点击理由的新规格，标题优先写具体规格，不用“全面升级”“更可控”等抽象判断替代。多个同类上限可靠合计后进入标题时，首屏必须立刻拆回原始组成、单位和适用口径。
- 新闻、案件和事件型材料的 one_liner 与第一节开头必须先交代谁、何时、何地、做了什么、结果怎样，再进入证据、机制与边界。
- 默认读者不具备 AI 技术背景。首次专有名词、缩写、指标和机制先用人话说明作用，再给准确术语与条件；读者不查外部资料也应能复述主线。
- 可用来源媒体含 audio 时，listening_cards 只能引用其中登记的 media_id；每条曲目保留真实提示词，给出可被实际听见的重点，并明确官方精选样曲的证据边界。没有登记音频就留空，不补外部播放器。
- narrative_plan 必须填写 target_reader、reader_tension、title_contract、opening_anchor、opening_sequence、reader_stake、resonance_basis、stance、reader_takeaway、core_mechanism、distinctive_insight 和 chapter_system，并把 central_question、section_logic、closing_answer 组成内部阅读契约。title_contract 只保留一个点击理由并写清证据边界；opening_sequence 必须在首屏完成；chapter_system 的 chapters 必须与 sections id 一一对应。opening_anchor 与 resonance_basis 必须来自已读取材料，reader_stake 必须具体到判断、选择、成本或机会，stance 必须说明依据和改变条件。core_mechanism 必须是一句能解释“为什么”的因果关系；每一节只能证明、解释、限制或应用它。独特见解必须来自材料中的机制、矛盾、取舍或后果，并由正文完整论证，不能是通用行业口号。
- 每节只完成一个主要任务，并至少增加新事实、新区别、新机制或新后果。优先让具体证据、动作、数字或案例先出现，再解释意义；能删掉而不削弱中心论证的段落不要保留。
- 产品页若存在“完整结果明显超过单次能力限制”的已核实反差，优先用它建立开篇问题，再沿真实演示拆解中间工作流。深层机制判断放在案例之后得出，不要抢在首屏用抽象行业结论替读者总结。
- 检查章节结构变化：相邻章节不要重复同一种开场动作，三个以上章节不要共享完全相同的内部骨架。结构变化必须服从材料，不能为求花样虚构故事或场景。
- 正文要能作为博客和视频的母稿：主线连续、章节观点可独立提取、关系适合可视化、结论有记忆点；不得写成口播提纲或卡片拼盘。
- research_ledger.experiments/cases 为空时，对应输出必须是空数组，不能为了丰富文章编造实验或故事。
- high 实验与案例必须覆盖；实验保留样本、判定口径、对照和人工条件；案例只能重建材料明确支持的事件链，不能编造对话。
- 每个 experiment/case/visual 必须用 after_section_id 放进最相关的论证段。
- interactive_compare 至少包含 2 个 options 和 2 个 modes，每个 mode 的 selected_index 必须落在候选范围内；无真实概率时不得编造数字，并明确标为机制示意。
- metric_bars 至少包含 2 个回答不同问题的 groups；每组至少 2 行，保留主方案和对照的正数原值、显示单位、比较方向与倍数。条长只在同一行内归一化，boundary 必须提醒读者不同指标不能混用。不要把适合普通二维表格的内容强行做成切换卡。
- rank_bars 包含1至4个同口径分组；每组2至18项同单位数值，按绝对值降序排列，direction 与数值正负一致，tone 使用固定语义色。caption 说明归一化方式，boundary 说明数值不能推出什么；不同单位或时间口径不得混排。
- funnel_flow 包含2至5道真实资格关口，必须有入口、每关标题与说明、caption；显式 width 必须逐级递减。没有真实淘汰关系时改用 flow；没有真实转化率时，caption 必须说明宽度不代表精确比例。
- delta_table 包含2至8个同指标前后变化项，必须写 baseline_label、current_label、旧值、新值、变化、方向、语义色和 boundary。变化值只能引用来源或由同口径旧值与新值可靠计算；无时间或版本关系的平级比较改用 compare_table。
- status_matrix 包含2至6个固定维度和2至8个对象，每行 cells 数量与 columns 一致，每格写状态和固定语义色；caption 定义状态，boundary 说明定性覆盖不等于性能评分。禁止为了多彩给普通单元格随机染色。
- decision_table 包含2至8条条件分支，每条写 condition、result、action、tone，并提供版本、范围和例外 boundary。condition/result 必须忠于材料，action 明确是面向读者的应对建议，不能把编辑建议伪装成原始规则。
- flow.presentation=stepper 只接受3至7个完整对象步骤，每步必须有 label、title、description，可选 result，并提供 caption；普通 static 流程仍可用文字步骤。互动必须帮助读者聚焦复杂阶段，不能为了减少首屏文字把关键事实默认隐藏。
- timeline.presentation=scrubber 只接受3至8个完整时间节点，每个节点必须有 time、title、description，并提供 caption；无脚本时静态展开所有节点。只有拖动节点能帮助理解阶段变化时才使用，日期清单继续使用 static。
- layer_stack 只用于真实存在的层级或上下游依赖，包含2至7层；每层必须有 label、title、description，caption 说明层级依据与不能推出的结论。时间先后用 flow 或 timeline，平级比较用 compare_table，不能为追求样式多元错判关系。
- 同一章节通常只放一个承担解释任务的主视觉；来源图片、音频或视频可作为证据补充。每个 source_media 必须写清 purpose、after_section_id 和 reader_note，说明它解释什么、为什么放在这里、读者看哪里；中文媒体同样需要自然的观看重点，不得只写“配图”。不要连续使用三个相同结构的组件，也不要让视觉复述紧邻正文。matrix 超过6行、4列或24个单元格时，只有“逐格查数”本身是阅读任务才保留，否则拆分或改用分层、指标切换。
- 优先从内容本身提取视觉结构：提示词含真实时间段时可做分镜 `timeline.scrubber`；多份参考素材被明确分配给场景、人物、区域或声音时可做紧凑分组或可展开 `layer_stack`；不同官方来源对同一能力说法冲突时可做带来源列的紧凑 `compare_table`。这些组件已回答问题时，删除复述同一信息的通用能力矩阵与公开数字卡。
- scenario_calculator 至少包含 2 个 tabs、每个 tab 至少 1 个有来源的指标、合法 slider 与 result.base，并登记 source_asset_ids。滑块值是用户假设而非证据；若多个数值不属于同一平台、样本或时间口径，必须在指标 note、formula_note 和 caption 中明确说明。
- capacity_curve 包含3至5个 position 严格递增的定性状态，每项写 label、result 和语义 tone；不得把示意滑块伪装成精确预测器，caption 必须说明转折点随条件变化。
- cost_ledger 包含1至4个 cost_labels 和2至6个唯一情景；included 只能引用 cost_labels，每个情景写清 verdict 与 explanation，并提供统一 boundary。
- strategy_tabs 包含2至6个平行方案；每项必须有 label、target、mechanism、expected_effect、open_questions 和语义 tone，并提供统一 boundary。
- action_card 与 takeaway_list 不得复述同一组建议；内容相近时只保留一种，另一项输出空结构。
- further_reading 只收录本次实际读取、能补充实现细节或独立证据的 1-5 条材料；不重复主材料，不放搜索结果页，不用发布方名称代替材料标题。完整文章页末会把主材料、延伸阅读和简短来源说明统一排成资料区。
- further_reading 的 title 使用准确、自然的中文标题，必要时保留论文、模型、机构或产品的官方专名；不能直接把一串英文标题端给中文读者，也不能为了中文化改变原题含义。
- site_note 是发布页“本站说明”，只用 1-2 句交代会改变读者判断的来源属性与证据边界；不写“本次读取了、核查了、抓取了”等工作过程。完整审计仍放在 `research_ledger`、`fact_check`、`source_notes` 和 `editorial_quality`，这些字段只供内部运行时追溯，禁止渲染到 HTML 或来源区。
- illustration_plan 只选 1-2 个需要空间、材质、尺度、氛围或确实难以代码化的机制与案例环境；流程、层级、时间、对比和因果关系改用 HTML/CSS 组件。已有来源图、官方视频或代码化视觉足够时留空。不得规划跑分图、产品截图、真实人物或案例结果，不得要求图中生成文字、数字、Logo 或 UI；caption 必须明确“AI 概念示意，不是原始证据”。
- source_media 只能使用输入中登记的来源媒体，不得编造图片或视频 URL；每段媒体都必须有解释增量，能让读者看见正文文字无法同样快表达的画面、过程、尺度、前后差异或原始证据；不相关的装饰图不要使用。
- 外语 source_media 必须同时提供中文 caption 和中文 reader_note；翻译、字幕和画面说明只能依据实际读取内容，不得脑补。
- media_omissions 必须覆盖所有未进入 source_media 的重要演示或首屏视频，并给出具体理由；已经采用的媒体不得同时列为省略。
- high 且 claim_kind=metric 的研究主张必须生成 number_stories；完整写清主数字、单位、分母、时间、对照或变化、范围、边界与登记来源。任一口径未知时如实写未知，并在正文解释；“未知”不算完整，不得为了生成大数字卡自行补齐。
- number_stories 负责审计覆盖，不要求逐条公开展示。正文、metric_bars、rank_bars、实验详情或来源图已经表达同一组数字时，将重叠项设为 suppress_visual=true；每个 after_section_id 最多保留一张公开数字卡，不得形成连续大型数据卡。
- number_stories 的 denominator、scope、period、baseline、change、boundary 是内部审计字段，不能原样当作读者标签。labels 必须根据内容说明关系：样本用“统计对象”，计时起点用“计时口径”，具体事件用“对应事件”；限制项优先写成“这个数字不能说明什么”或带数字的具体问法。标签必须脱离字段名也能看懂。
- evidence_gallery 只选择已登记且直接支撑正文的原始图表、实验截图或案例证据；不放装饰图，同一 URL 不重复。
- 最终逐段清理元叙述：正文 sections[].content 中不要出现“原文/原博客/本文/当前材料”作为叙事主语；将其改写为自然文章语气，或点名真正的信息主体。
- 最终做一次读者体验复查：删掉报告腔开场和空泛总结，解释首次出现的术语，拆开文字墙，并改变连续重复的句式。再脱离标题、摘要、提纲和来源说明冷读正文，确认它自身能说清中心、关键支撑和最终完成的结果或选择；把最后两段分别删掉试读，删后更有力就提前结束。不要为了口语化删掉证据条件或把概率结论写成确定事实。
- 最终做一次活人感反查：不要让每一节都有金句、反转、反问和完整收束；删除虚构的读者声音、假故事、假犹豫、材料不支持的第一人称体验和强行升华。用自然的长短句变化、准确的读者处境、一次有效回环和具体判断建立朋友感，不模仿任何作者的固定口癖。
"""


RESEARCH_PROMPT = """你是事实研究员，不负责写文章。请把原文和已抓取的独立材料整理成证据账本，严格输出 JSON：
{
  "claims": [
    {
      "id": "c1",
      "claim": "可核查的原子主张，一条只说一件事",
      "claim_kind": "metric|date|version|fact",
      "importance": "high|medium|low",
      "status": "source_only|cross_checked|disputed|unknown",
      "evidence": [
        {"url": "只能使用输入中出现的 URL", "publisher": "发布者", "source_type": "original|official|supplemental|independent", "quote": "短引文", "support": "支持或反驳什么"}
      ],
      "caveat": "口径、样本、利益相关或尚未解决的问题"
    }
  ],
  "experiments": [
    {
      "id": "e1",
      "importance": "high|medium|low",
      "question": "实验回答的问题",
      "setup": "环境、步骤和人工条件",
      "sample": "样本量、轮数或测试次数；材料未给出则写未知",
      "models": ["材料明确列出的模型"],
      "metric": "指标与成功判定口径",
      "result": "包含必要数字和比较口径的结果",
      "control": "对照组或基线；材料没有则写无明确对照",
      "limitations": "样本、评判器、环境和外推限制",
      "claim_ids": ["c1"]
    }
  ],
  "cases": [
    {
      "id": "case1",
      "importance": "high|medium|low",
      "setup": "案例初始状态",
      "events": [
        {"label": "阶段名", "text": "材料明确支持的动作或状态变化", "source_quote": "可选逐字引文"}
      ],
      "outcome": "案例结果",
      "boundary": "该案例不能证明什么",
      "claim_ids": ["c1"]
    }
  ],
  "background": ["理解原文所需的背景，只写材料能支持的内容"],
  "unknowns": ["当前材料无法回答的问题"],
  "source_assessment": "来源结构和偏见总结"
}

规则：
- 不写标题、导语、卡片或宣传文案。
- 不得使用输入中没有出现的 URL、数字、产品名、价格或日期。
- 只有至少一篇“已抓取的独立证据材料”支持时，status 才能是 cross_checked。
- 原文发布方自证只能写 source_only。
- 每个关键数字必须有 evidence；没有证据就写 unknown。
- 所有含数量、比例、价格、性能、样本或增减幅度的主张标为 claim_kind=metric；日期、版本和普通事实分别标为 date、version、fact。
- 只有原文确实描述实验时才填 experiments；必须保留样本、判定口径、对照和人工条件，缺失信息写未知，不能自行补齐。
- 只有材料确实提供可复述的具体事件链时才填 cases；events 只记录有证据的动作和状态变化，不写宣传性故事，不编造对话。逐字引文放 source_quote，否则留空。
- experiments/cases 的 claim_ids 必须引用 claims 中实际存在的 id；普通资讯没有实验或案例时返回空数组。
"""


def _system_prompt_for_modes(_required_modes: tuple[str, ...]) -> str:
    return FULL_SYSTEM_PROMPT


def _editorial_review_prompt_for_modes(required_modes: tuple[str, ...]) -> str:
    if set(required_modes) != {"full"}:
        raise ValueError("article-distiller 只支持 full 深度文章审校")
    mode = "full"
    required = "narrative_plan、sections、experiment_ledger、case_stories、number_stories、source_media、media_omissions、evidence_gallery、fact_check、editorial_coverage"
    focus = "先检查是否真正面向希望了解并进入 AI 领域的聪明初学者：首屏承诺清楚，首次术语可懂，读者能复述主线、领域意义和独特见解。再检查标题点击动机、事件 5W、论证链、实验条件、案例来源、限制与结尾回答，以及母稿的博客/视频可复用性。quick_scan 必须是 3 条且总计不超过 180 字；不得把重建案例写成逐字对话。"
    voice_requirement = ""
    voice_report_fields = ""
    if mode == "full":
        voice_requirement = """
- 按“真实为底、讲透为骨、人话为形、朋友感为声”重读全文：保留事实精度，把术语先翻译成直观意思，把长文字墙拆成自然短段。
- 以希望了解并进入 AI 领域、但没有技术背景的聪明初学者通读：首次术语是否先讲作用，主线是否无需外部资料即可复述，AI 领域意义是否明确。
- 检查标题、图表标题、表头与正文中的专有名词：保留官方或原始拼写，不得用编辑自创的中文别称替换。存在稳定常用中文名且确实帮助理解时，导语或正文首次出现必须写成“原名（常用中文名）”，缺少括注必须在完整修订稿中补齐；concept_explainers 不能代替正文括注。译法不确定或属于人名、品牌、产品、代码、模型编号、文件名及大众熟悉缩写时保留原名，并按需把作用写进正文或 concept_explainers。
- 检查 narrative_plan.target_reader、reader_tension、title_contract、opening_anchor、opening_sequence、reader_stake、resonance_basis、stance、reader_takeaway、core_mechanism、distinctive_insight 和 chapter_system 是否具体。title_contract 是否只有一个点击理由、承诺能在首屏兑现且证据边界清楚；opening_sequence 是否在首屏完成真实细节、矛盾转折和主体/机制揭示；chapter_system 是否选择适合材料的主原型并与全部 sections id 对齐。reader_stake 是否具体到判断、选择、成本或机会；resonance_basis 是否能回指材料而非抽象情绪；stance 是否说明依据和改变条件。读者张力不能代编心理；全文只能有一个一句话因果机制，每节都要证明、解释、限制或应用它。并列争夺中心的观点要降为支撑或删除。
- 检查文章是否可作为博客与视频母稿：一句话主旨、连续主线、可独立提取的章节观点、可视化关系和记忆点是否清楚，同时保持自然文章形态。
- 检查每个视觉组件的主维度和组内维度：有先后、因果、层级或前后变化的外层主题必须保留清楚顺序；同一主题下真正平级、同口径且需要比较的对象可以并排。字段固定、行列关系稳定且需要高效扫视的二维内容使用 `matrix` 表格；文字较长或需要强调每组语境时使用 `paired`；普通顺序说明使用 `stacked`。不要一刀切成全横向或全纵向。
- 先检查价值、可读性、共鸣：读者是否先获得明确答案，是否能轻松看懂，是否由真实处境而不是编造情绪产生连接。
- 再检查灵魂、骨架、血肉、颜值：主旨与受众是否清楚，结构是否闭环且详略得当，素材与表达是否站得住，标题和形式是否只是在放大而非替代内容。
- 标题可以营销化，但承诺必须来自材料并在首屏兑现。事件型文章必须在 one_liner 和第一节开头交代谁、何时、何地、做了什么、结果怎样；删掉抢在事件之前的免责声明与抽象分析。
- 若草稿有已核实的具体例子却以媒体名称、抽象判断或机制定义开场，优先改成“例子或动作 -> 背景矛盾 -> 事件主体与机制”；例子不得来自对比文章，移到开头后要删除后文的成组重复。
- 若是解释型文章，检查首屏是否遵循“具体处境/例子 -> 反常之处 -> 一句判断 -> 机制与规则”。如果首屏被发布日期、目录、能力清单或连续免责声明占满，先把能让读者看见问题的真实细节前置，再将来源与边界放回对应论点旁。
- 逐节检查抽象规则是否先被翻译成读者能想象的动作，且至少有一个真实例子或准确类比；若金句、参数或概念没有后续证据，删除或改写为普通陈述。
- 做一次 HKR 复核：文章是否同时提供阅读兴趣、可带走的新知识和材料支持的真实连接点；若共鸣依赖虚构第一人称或假设人物，改成可回指材料的处境、冲突或后果。
- 对多个同类对象检查是否逐一展示并遵循递进：基础现象在前，最能改变判断的结果在后；若只是把同一结论换成多张卡片或多段吐槽，合并为一次说明。
- 检查背景知识是否从当前例子自然引出，是否存在脱离主线的科普段、强行文化升华或空泛哲学收束；删掉不改变机制理解的参照物。
- 检查合理对立面是否被完整呈现，以及方法论文章是否交代学习成本、常见失败和不适用条件；不要只展示成功案例。
- 检查开头埋下的意象、动作或问题是否在结尾得到一次自然回扣；独立短句、情绪标点和金句只能用于少数转折，不能形成固定模板。
- 检查 chapter_system：事件、调查、产品、研究、多主题或机制解释只能选择一个主原型；每节必须解决新的理解缺口、增加一种推进并由具体证据支撑。只读标题应能看见从进入到回答的连续动作，而不是“背景、分析、影响、总结”的分类目录。
- 关键解释章节可以改成“具体问题标题 → 前 1-2 句直接回答 → 证据和原因 → 边界”。问题必须是读者此刻真实会问、且材料能回答的；不能连续堆问，也不能把答案拖到末尾。不要把所有章节统一改成问答，其他章节按材料从事件、结果、数据、例子、冲突或明确判断进入。
- 逐一检查非空 transition_hook：只能追问本节自然留下的问题，下一节必须立即回答；全文通常保留 3-5 处。下一标题可压缩重述，但删掉逐字重复、空悬念和末节未收束的问题。
- 把 narrative_plan 当作内部阅读契约检查：开头承诺、正文主链和读后判断必须一致；每节只完成一个主要任务并增加新信息，能删掉而不削弱中心论证的段落应删除。
- 检查结构变化：相邻章节不要重复同一种开场动作，三个以上章节不要共享完全相同的内部骨架；不得为求变化虚构故事或场景。
- 检查是否存在一条清楚的钉子判断，并能在至少两个不同场景中得到兑现；如果判断只在标题或速览出现、正文没有动作和证据承接，改写或删除。
- 逐段检查抽象规则之后是否紧跟具体动作、画面或选择；连续出现比例、目录、脚本和术语而没有场景落点时，拆段、补例子或删减。
- 脱离标题、摘要、提纲和来源说明冷读正文，确认它自身能说清中心、关键支撑和最终完成的结果或选择；把最后两段分别删掉试读，删后更有力就提前结束。
- 朋友感是平等、诚实和具体，不是频繁使用“你”、网络热词、感叹号或故作轻松。所有风格修订必须在 revised_article 中真正落地。
- 先准确复述最合理的异议和读者处境，再回应新增条件；没有真实异议时不要虚构“你可能会觉得”。检查段段金句、匀速排比、固定连接词、假脆弱、假故事、材料不支持的第一人称体验和强行哲学升华。允许节奏有自然毛边，但语病和事实漏洞必须修复。
- 知识点要在主线需要时自然出现；开头若已有真实意象、反常结果或具体问题，结尾可回到它一次形成闭环。不要模仿任何作者的固定口癖、粗口或网络梗。
- 对照输入材料检查 distilled_title：先逐字确认 title_contract.recognition_anchor 已出现在标题前半句；若材料中的知名公司、平台、产品或人物被陌生项目代号取代，必须恢复知名主体及其归属关系。允许从真实冲突、反差或结果重新取角度，但不得新增人物、动作、数字或结果；如果标题没有点击动机，重写为更具体、更口语、能在首屏兑现的版本。
"""
        voice_report_fields = (
            '    "title_click_score": 0,\n'
            '    "title_rewrites": ["平直或失实标题 -> 有点击动机且可兑现的标题"],\n'
            '    "title_contract_fixes": ["如何对齐认知主体、唯一点击理由、读者承诺和证据边界"],\n'
            '    "event_5w_fixes": ["补齐或前置了哪些人物、时间、地点、动作和结果"],\n'
            '    "content_value_fixes": ["如何补足价值、可读性或真实共鸣"],\n'
            '    "article_layers_fixed": ["如何修复灵魂、骨架、血肉或颜值"],\n'
            '    "beginner_clarity_fixes": ["为 AI 初学者解释了哪些术语、机制或背景"],\n'
            '    "distinctive_insight_fixes": ["如何把通用观点改成材料支持的独特见解"],\n'
            '    "repurposing_fixes": ["如何增强博客或视频母稿的主线、模块与记忆点"],\n'
            '    "reader_voice_score": 0,\n'
            '    "stiff_phrases_rewritten": ["报告腔原句 -> 自然表达"],\n'
            '    "jargon_explanations_added": ["补充了哪些直观解释"],\n'
            '    "rhythm_fixes": ["拆分或调整了哪些文字墙与重复句式"],\n'
            '    "transition_hooks_fixed": ["补充、改写或删除了哪些阅读钩子，以及下一节如何回答"],\n'
            '    "question_answer_loops_fixed": ["哪些章节的问题、开篇短答案或证据展开得到修复"],\n'
            '    "reading_contract_fixes": ["开头承诺、正文主链或读后判断如何重新对齐"],\n'
            '    "opening_anchor_fixes": ["真实开头锚点如何选择、前置或落地"],\n'
            '    "example_entry_fixes": ["真实例子如何同时承担场景、转折和主体/机制揭示"],\n'
            '    "reader_stake_fixes": ["如何把泛泛相关性改成具体判断、选择、成本或机会"],\n'
            '    "resonance_fixes": ["如何用材料中的真实处境、冲突、取舍或后果建立连接"],\n'
            '    "stance_fixes": ["如何明确可辩护立场、依据与改变条件"],\n'
            '    "knowledge_timing_fixes": ["删除或移动了哪些脱离主线的知识倾倒"],\n'
            '    "human_specificity_fixes": ["把哪些抽象情绪或评价改成具体主体、动作和后果"],\n'
            '    "structural_variety_fixes": ["哪些机械重复的章节开场或内部骨架得到调整"],\n'
            '    "chapter_system_fixes": ["如何选择章节原型、补齐逐节推进或修复章节承接"],\n'
            '    "evidence_visual_fixes": ["哪些原图、案例、引用、表格或互动被移到真正支撑的论点旁"],\n'
            '    "cold_read_fixes": ["冷读和删除测试删改了哪些不推进论证的段落或结尾"],\n'
            '    "core_mechanism_fixes": ["如何把并列观点收束成一个核心机制"],\n'
            '    "human_voice_fixes": ["清理了哪些假共鸣、匀速节奏、段段金句、虚构反问或强行升华"],\n'
        )
    return f"""你是严格的中文主编。你会收到研究证据账本和一份单一输出模式的完整草稿。请实际修订，而不是只给建议。

重点：{focus}
共同要求：
- importance=high 的 claim 必须被覆盖或明确说明舍弃原因。
- 不得新增研究账本和草稿中没有的事实、URL、数字、产品、价格或日期。
- 逐一复核登记的重要视频和图片：只保留有信息增量的素材；外语媒体必须补准确中文图注与中文观看重点/读图提示，不得编造字幕或画面。
- 逐一复核登记的重要视频和图片：每段都要有明确的 purpose、对应章节和观看重点，说明它具体解释了什么、读者看哪里、为什么文字或其他视觉无法等价替代；没有解释增量的素材省略，不因原网页存在或页面更丰富而保留。
- 复核媒体是否形成能力覆盖组合：首屏锚点、代表性案例、机制操作和前后差异等不同角色不要被“一段代表全部”替代；原文有真实提示词、时间码、参考分工、代际基线或平台状态时，补成紧凑可读组件，不把长原文整段塞进正文。
- 不得提升来源证据等级；限制、反例和 unknowns 不得丢失。
- 删除重复表达，保持事实、数字和比较口径一致。
- 逐句先抽主干，再检查并列搭配、前后照应、成分残缺或赘余、句式杂糅、指代与歧义、句内逻辑、两面对一面、否定、关联词、数量范围和标点。每处区分“明确病句 / 存疑依赖语境 / 无明显语病”；明确病句做不改变事实的最小修改，存疑项只登记风险，不猜原意。不能把“通过……使……、是否/能否、由于……因此……”等表面形式机械判错，也不能把文风润色冒充语病修复。
{voice_requirement}

严格输出：
{{
  "quality_report": {{
    "coherence_score": 0,
    "coverage_score": 0,
    "problems_found": ["具体问题"],
    "content_gaps_fixed": ["实际补回的内容"],
    "duplicates_removed": ["实际删除或合并的重复"],
    "language_issues_fixed": ["原句 -> 修订句"],
    "grammar_diagnoses": [{{"path": "字段路径", "judgment": "明确病句|存疑依赖语境", "category": "病句类型", "problem": "具体问题", "minimal_fix": "最小修改；存疑时留空"}}],
    "grammar_false_positive_checks": ["经语境判断后保留的高风险表面结构及理由"],
{voice_report_fields}    "remaining_risks": ["材料无法解决的问题"]
  }},
  "revised_article": {{
    "要求": "返回完整修订稿，保留草稿全部顶层结构；必须含 {required}"
  }}
}}
"""


def _editorial_patch_review_prompt_for_modes(required_modes: tuple[str, ...]) -> str:
    """Use the same editorial standards while returning only changed fields."""
    full_prompt = _editorial_review_prompt_for_modes(required_modes)
    guidance = full_prompt.split("\n严格输出：", 1)[0]
    return guidance + """

输出必须是可确定合并的修订补丁。你仍须完整阅读和审校全文，但不要回传未修改字段：
{
  "quality_report": {
    "coherence_score": 0,
    "coverage_score": 0,
    "problems_found": ["具体问题"],
    "content_gaps_fixed": ["实际补回的内容"],
    "duplicates_removed": ["实际删除或合并的重复"],
    "language_issues_fixed": ["原句 -> 修订句"],
    "remaining_risks": ["材料无法解决的问题"]
  },
  "article_patch": {
    "set_fields": {
      "distilled_title": "只有修改标题时才出现",
      "quick_scan": ["只有修改该字段时才返回完整新值"],
      "narrative_plan": {"只有修改该字段时才返回完整新值"}
    },
    "section_updates": [
      {
        "id": "必须对应草稿中已有的 section id",
        "set": {"title": "只放修改字段", "content": "修改后的完整本节正文"}
      }
    ]
  }
}

规则：
- `set_fields` 只放确实修改过的顶层字段，并为每个字段返回完整新值；未修改字段必须省略。
- 修改已有章节时优先使用 `section_updates`，每项只放该章节实际修改的字段。
- 需要新增、删除、合并或重排章节时，在 `set_fields.sections` 返回完整的新 sections 数组，不再同时使用 `section_updates`。
- 输入含 `missing_high_metric_story_ids`、`incomplete_number_story_ids` 或 `incomplete_high_metric_story_claim_ids` 时，必须在 `set_fields.number_stories` 返回修订后的完整数组；不能只在正文或 quality_report 中解释数字。
- 输入含 `meta_narration_section_indexes` 时，必须修改对应章节；输入含 `meta_narration_public_paths` 时，必须在 `set_fields` 修改对应顶层字段。客户可见内容不得残留“本文、原文、原博客、当前材料、现有材料、本次材料”等写作过程话术。
- 输入含 `semantically_missing_high_claim_ids` 时，必须在读者可见的章节、实验、案例、数字故事或视觉字段中补回对应事实；`fact_check`、`source_notes` 和 quality_report 不算正文覆盖。
- 不得修改或添加 `research_ledger`、`editorial_quality` 等审计字段。
- 没有必要修改时，返回空的 `set_fields` 和 `section_updates`；不得为了显示工作量改写已经准确自然的内容。
- 输出前逐条对照输入中的每个 blocker，确认都有对应的 `set_fields` 或 `section_updates`；评分、建议和 quality_report 不能代替修订。
- 报告中声称已修复的内容必须真实出现在补丁里；若材料无法补齐某项证据口径，应按门禁要求降级展示，而不是用“未知”占位冒充完整。
"""


QUALITY_REPAIR_PATCH_PROMPT = """你是发布前质量修复编辑。你会收到当前完整文章、研究证据账本和确定性门禁阻断项。
只修复阻断项，不重写无关内容，不新增材料外事实、URL、数字、产品、价格或日期；必须保留当前文章已有的媒体登记、省略理由、数字来源、证据等级、限制和章节结构。
输出 JSON：{"quality_report":{"problems_fixed":["实际修复"],"remaining_risks":["仍无法解决的问题"]},"article_patch":{"set_fields":{},"section_updates":[]}}。
set_fields 只放需要替换的完整顶层字段；修改已有章节优先放 section_updates，每项包含已有 section id 和实际修改字段。不得修改 research_ledger、editorial_quality。
如果阻断项是语义覆盖，必须把事实写进读者可见的章节、实验、案例、数字故事或视觉字段；如果是媒体或数字登记问题，必须修正对应的 source_media、media_omissions、number_stories 或 evidence_gallery 字段。不要返回完整 revised_article。
"""


def _apply_article_patch(draft: dict, patch: dict) -> dict:
    """Apply a constrained top-level/section patch without losing untouched data."""
    if not isinstance(draft, dict) or not isinstance(patch, dict):
        raise ValueError("编辑审校阶段的 article_patch 不是对象")
    set_fields = patch.get("set_fields") or {}
    section_updates = patch.get("section_updates") or []
    if not isinstance(set_fields, dict) or not isinstance(section_updates, list):
        raise ValueError("article_patch.set_fields 或 section_updates 类型无效")
    forbidden = {"research_ledger", "editorial_quality"}
    unknown_fields = sorted(set(set_fields) - set(draft))
    forbidden_fields = sorted(set(set_fields) & forbidden)
    if unknown_fields or forbidden_fields:
        details = unknown_fields + forbidden_fields
        raise ValueError(f"article_patch 包含不允许的顶层字段：{details}")

    result = copy.deepcopy(draft)
    for key, value in set_fields.items():
        result[key] = copy.deepcopy(value)

    if "sections" in set_fields and section_updates:
        raise ValueError("替换完整 sections 时不能同时提交 section_updates")
    if not section_updates:
        return result

    sections = result.get("sections")
    if not isinstance(sections, list):
        raise ValueError("草稿缺少可更新的 sections")
    by_id = {
        str(item.get("id") or ""): item
        for item in sections
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    seen_ids: set[str] = set()
    for update in section_updates:
        if not isinstance(update, dict):
            raise ValueError("section_updates 中存在非对象条目")
        section_id = str(update.get("id") or "")
        fields = update.get("set") or {}
        if not section_id or section_id not in by_id:
            raise ValueError(f"section_updates 引用了不存在的 section id：{section_id or '(空)'}")
        if section_id in seen_ids:
            raise ValueError(f"section_updates 重复修改 section id：{section_id}")
        if not isinstance(fields, dict) or not fields:
            raise ValueError(f"section_updates[{section_id}] 缺少非空 set")
        unknown_section_fields = sorted(set(fields) - set(by_id[section_id]))
        if unknown_section_fields:
            raise ValueError(
                f"section_updates[{section_id}] 包含未知字段：{unknown_section_fields}"
            )
        for key, value in fields.items():
            by_id[section_id][key] = copy.deepcopy(value)
        seen_ids.add(section_id)
    return result


def _merge_repair_candidate(base: dict, repaired: dict, article: Article) -> dict:
    """合并定向修复稿，避免修复模型丢失已登记的证据和媒体决策。

    质量修复只应改阻断项。模型返回完整 JSON 时，字段遗漏、空列表或略写来源
    不应把已经通过前一阶段的媒体对账、数字来源和证据记录一起删除。
    """
    if not isinstance(base, dict) or not isinstance(repaired, dict):
        return copy.deepcopy(repaired)
    result = copy.deepcopy(base)
    known_urls = {url_key(str(getattr(article, "url", "") or ""))}
    for source in getattr(article, "source_links", []) or []:
        if isinstance(source, dict):
            key = url_key(str(source.get("url") or ""))
            if key:
                known_urls.add(key)
    for asset in getattr(article, "media_assets", []) or []:
        if isinstance(asset, dict):
            for value in (asset.get("url"), asset.get("source_url")):
                key = url_key(str(value or ""))
                if key:
                    known_urls.add(key)

    keyed_lists = {
        "source_media": "media_id",
        "media_omissions": "media_id",
        "evidence_gallery": "media_id",
        "number_stories": "id",
    }
    for key, value in repaired.items():
        if key in {"research_ledger", "editorial_quality"}:
            continue
        if key not in keyed_lists or not isinstance(value, list):
            result[key] = copy.deepcopy(value)
            continue
        previous = result.get(key)
        if not isinstance(previous, list):
            result[key] = copy.deepcopy(value)
            continue
        if not value and previous:
            continue
        id_field = keyed_lists[key]
        merged = {
            str(item.get(id_field) or ""): copy.deepcopy(item)
            for item in previous
            if isinstance(item, dict) and str(item.get(id_field) or "")
        }
        order = list(merged)
        for item in value:
            if not isinstance(item, dict):
                continue
            item_copy = copy.deepcopy(item)
            item_id = str(item_copy.get(id_field) or "")
            if key == "number_stories" and item_id:
                old = merged.get(item_id) or {}
                new_url = url_key(str(item_copy.get("source_url") or ""))
                old_url = url_key(str(old.get("source_url") or ""))
                if old_url in known_urls and new_url not in known_urls:
                    item_copy["source_url"] = old.get("source_url")
                if old.get("source_asset_ids") and not item_copy.get("source_asset_ids"):
                    item_copy["source_asset_ids"] = copy.deepcopy(old["source_asset_ids"])
            if item_id and item_id not in merged:
                order.append(item_id)
            if item_id:
                merged[item_id] = item_copy
        result[key] = [merged[item_id] for item_id in order]
    return result


def _review_output_mode() -> str:
    explicit = os.getenv("DISTILL_REVIEW_OUTPUT_MODE", "").strip().lower()
    if explicit in {"patch", "full"}:
        return explicit
    return "patch"


def _env_int(name: str, fallback: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(fallback))))
    except (TypeError, ValueError):
        return fallback


def _compact_source_registry(article: Article, evidence_articles: list[Article]) -> list[dict]:
    sources = [{
        "url": article.url,
        "title": article.title,
        "source_type": "original",
    }]
    sources.extend({
        "url": item.url,
        "title": item.title,
        "source_type": str(getattr(item, "source_type", "supplemental") or "supplemental"),
    } for item in evidence_articles if item.url)
    return sources


def _build_draft_context(
    article: Article,
    evidence_articles: list[Article],
    research: dict | None,
    full_user_prompt: str,
) -> str:
    """Avoid resending raw attachments after research while preserving the original."""
    if not isinstance(research, dict):
        return full_user_prompt
    ledger_limit = 40000
    sources = _compact_source_registry(article, evidence_articles)
    context = (
        f"原文标题：{article.title or '(未提取到)'}\n"
        f"作者：{article.author or '(未知)'}\n"
        f"发布日期：{article.date or '(未知)'}\n"
        f"原文 URL：{article.url}\n"
        f"允许引用的已抓取来源：{json.dumps(sources, ensure_ascii=False)}\n\n"
    )
    source_links = [
        item for item in (getattr(article, "source_links", []) or [])
        if isinstance(item, dict) and (item.get("fetched") or item.get("url") == article.url)
    ][:16]
    media_assets = []
    for item in (getattr(article, "media_assets", []) or []):
        if not isinstance(item, dict):
            continue
        # 只把模型真正需要做取舍的媒体元数据送入写作阶段，避免把网络请求、
        # CSS 背景图等重复的长字段塞进提示词。
        media_assets.append({
            key: item.get(key)
            for key in ("id", "type", "url", "poster_url", "alt", "section_title", "asset_role")
            if item.get(key)
        })
        if len(media_assets) >= 16:
            break
    context += (
        f"可用来源链接：{json.dumps(source_links, ensure_ascii=False)}\n"
        f"可用来源媒体：{json.dumps(media_assets, ensure_ascii=False)}\n\n"
        f"--- 原始文章正文（共 {article.text_chars} 字）---\n{article.text}\n\n"
    )
    context += (
        "--- 研究员生成的证据账本 ---\n"
        + _serialize_research_ledger(research, max_chars=ledger_limit)
        + "\n\n写作只能使用原始文章、证据账本和上列 URL。unknowns 不得被写成确定结论；"
        "不得因为附件正文不再重复发送而省略高优先级主张、实验、案例或证据边界。"
    )
    return context


_PIPELINE_CACHE_VERSION = "article-distiller-stage-cache-v2"


def _stable_asset_url(value: str) -> str:
    """去掉签名 query，避免动态媒体每次加载造成阶段缓存失效。"""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        if parts.scheme and parts.netloc:
            return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))
    except ValueError:
        pass
    return raw.split("?", 1)[0].split("#", 1)[0]


def _stable_media_fingerprint(article: Article) -> list[dict]:
    """只用重要媒体的稳定身份参与缓存指纹，不让装饰素材和签名 URL 触发重跑。"""
    important_roles = {"chart", "demo", "hero", "screenshot"}
    seen: set[tuple[str, str]] = set()
    items = []
    for item in (getattr(article, "media_assets", []) or []):
        if not isinstance(item, dict) or not item.get("url"):
            continue
        media_type = str(item.get("type") or "").lower()
        role = str(item.get("asset_role") or "").lower()
        if role not in important_roles and media_type not in {"video", "audio"}:
            continue
        stable_url = _stable_asset_url(str(item.get("url") or ""))
        key = (media_type, stable_url)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "type": media_type,
            "url": stable_url,
            "poster_url": _stable_asset_url(str(item.get("poster_url") or "")),
            "asset_role": role,
            "source_url": _stable_asset_url(str(item.get("source_url") or "")),
        })
    return sorted(items, key=lambda item: (item["type"], item["url"], item["asset_role"]))


def _hash_payload(value) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _article_fingerprint_data(article: Article, include_content: bool = True) -> dict:
    repository_files = [
        {
            "path": item.get("path"),
            "url": item.get("url"),
            **({"content_hash": _hash_payload(str(item.get("content") or ""))} if include_content else {}),
        }
        for item in (getattr(article, "repository_files", []) or [])
        if isinstance(item, dict)
    ]
    data = {
        "url": article.url,
        "title": article.title,
        "author": article.author,
        "date": article.date,
        "source_type": getattr(article, "source_type", "original"),
        "repository_files": sorted(repository_files, key=lambda item: (str(item.get("path")), str(item.get("url")))),
        "repository_read": dict(getattr(article, "repository_read", None) or {}),
    }
    if include_content:
        data["content_hash"] = getattr(article, "content_hash", "") or _hash_payload(article.text)
        data["media_assets"] = _stable_media_fingerprint(article)
    return data


def _pipeline_fingerprint(
    article: Article,
    evidence_articles: list[Article],
    cfg: dict,
    required_modes: tuple[str, ...],
    writing_prompt: str,
    _review_prompt: str,
    two_stage: bool,
    editorial_review: bool,
) -> str:
    return _hash_payload({
        "cache_version": _PIPELINE_CACHE_VERSION,
        "article": _article_fingerprint_data(article, include_content=True),
        # Evidence pages and GitHub landing pages often contain volatile counters or timestamps.
        # The output-specific cache expires after one day, so URL identity is safer for retries.
        "evidence": [_article_fingerprint_data(item, include_content=False) for item in evidence_articles],
        "model": cfg.get("model"),
        "base_url": cfg.get("base_url"),
        "required_modes": required_modes,
        "two_stage": two_stage,
        "editorial_review": editorial_review,
        "research_prompt_hash": _hash_payload(RESEARCH_PROMPT),
        "writing_prompt_hash": _hash_payload(writing_prompt),
        # Review protocol changes do not alter research or writing inputs. The
        # review checkpoint hashes its own prompt separately so switching
        # between patch/full output can reuse the expensive upstream stages.
        "draft_context_mode": "original+research-ledger",
    })


def _load_stage_checkpoint(
    checkpoint_dir: str | None,
    stage: str,
    fingerprint: str,
    parent_hash: str = "",
) -> dict | None:
    if not checkpoint_dir:
        return None
    path = Path(checkpoint_dir) / f"{stage}.json"
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        max_age = _env_int("DISTILL_STAGE_CACHE_MAX_AGE_SECONDS", 86400, 1)
        created_at = float(stored.get("created_at") or path.stat().st_mtime)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"[阶段缓存] {stage} 检查点不可读，将重新生成：{type(exc).__name__}")
        return None
    age = time.time() - created_at
    if age > max_age:
        print(f"[阶段缓存] {stage} 检查点已过期（{int(age)} 秒），将重新生成")
        return None
    if not isinstance(stored, dict) or not isinstance(stored.get("payload"), dict):
        print(f"[阶段缓存] {stage} 检查点结构无效，将重新生成")
        return None
    stored_fingerprint = str(stored.get("fingerprint") or "")
    if stored_fingerprint != fingerprint:
        print(
            f"[阶段缓存] {stage} 流水线指纹变化 "
            f"({stored_fingerprint[:8] or 'missing'} -> {fingerprint[:8]})，将重新生成"
        )
        return None
    if stored.get("parent_hash", "") != parent_hash:
        print(f"[阶段缓存] {stage} 上游结果变化，将重新生成")
        return None
    print(f"[阶段缓存] 复用{stage}阶段结果：{path}")
    return stored["payload"]


def _save_stage_checkpoint(
    checkpoint_dir: str | None,
    stage: str,
    fingerprint: str,
    payload: dict,
    parent_hash: str = "",
) -> None:
    if not checkpoint_dir:
        return
    directory = Path(checkpoint_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stage}.json"
    temporary = directory / f".{stage}.{os.getpid()}.tmp"
    stored = {
        "fingerprint": fingerprint,
        "parent_hash": parent_hash,
        "created_at": time.time(),
        "payload": payload,
    }
    temporary.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
    print(f"[阶段缓存] 已保存{stage}阶段结果：{path}")


def _load_config(config_path: Optional[str]) -> dict:
    if not config_path or not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _load_ccswitch_config(db_path: Optional[str] = None) -> dict:
    """读取 ccswitch 当前 Codex 提供商；失败时安静回退。"""
    path = os.path.expanduser(db_path or "~/.cc-switch/cc-switch.db")
    if not os.path.exists(path):
        return {}
    connection = None
    try:
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        provider = connection.execute(
            "select id, settings_config from providers "
            "where app_type=? and is_current=1 limit 1",
            ("codex",),
        ).fetchone()
        if provider is None:
            return {}
        settings = json.loads(provider["settings_config"] or "{}")
        auth = settings.get("auth") if isinstance(settings.get("auth"), dict) else {}
        api_key = next(
            (
                str(auth[key])
                for key in ("api_key", "apiKey", "key", "token", "openai_api_key", "OPENAI_API_KEY")
                if auth.get(key)
            ),
            "",
        )
        config_text = settings.get("config") if isinstance(settings.get("config"), str) else ""
        endpoint = connection.execute(
            "select url from provider_endpoints "
            "where app_type=? and provider_id=? order by id asc limit 1",
            ("codex", provider["id"]),
        ).fetchone()
        base_match = re.search(
            r'(?m)^\s*(?:base_url|baseUrl|baseURL|api_base|endpoint|openai_base_url|OPENAI_BASE_URL)\s*=\s*["\']([^"\']+)["\']',
            config_text,
        )
        base_url = base_match.group(1) if base_match else str(endpoint["url"] if endpoint else "")
        model_match = re.search(r'(?m)^\s*model\s*=\s*["\']([^"\']+)["\']', config_text)
        model = str(settings.get("model") or (model_match.group(1) if model_match else ""))
        if base_url and not base_url.rstrip("/").endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        if not api_key or not base_url:
            return {}
        return {"api_key": api_key, "base_url": base_url, "model": model or "deepseek-chat"}
    except (sqlite3.Error, json.JSONDecodeError, OSError, TypeError, ValueError):
        return {}
    finally:
        if connection is not None:
            connection.close()


def resolve_llm_settings(config: dict) -> dict:
    """合并优先级：环境变量 > config > ccswitch > 默认。"""
    explicit = {
        "base_url": os.getenv("DISTILL_LLM_BASE_URL")
        or config.get("base_url")
        or "https://api.deepseek.com",
        "api_key": os.getenv("DISTILL_LLM_KEY") or config.get("api_key") or "",
        "model": os.getenv("DISTILL_LLM_MODEL") or config.get("model") or "deepseek-chat",
    }
    if explicit["api_key"]:
        return explicit
    return _load_ccswitch_config() or explicit


def _repository_files_block(article: Article, max_chars: int = 12000) -> str:
    files = [
        item for item in (getattr(article, "repository_files", []) or [])
        if isinstance(item, dict) and item.get("path") and item.get("content")
    ]
    if not files:
        status = getattr(article, "repository_read", None) or {}
        if status.get("status") == "failed":
            return "\n[仓库深读未完成]\n" + str(status.get("reason") or "未能读取关键文件") + "\n"
        return ""
    parts = []
    used = 0
    for item in files:
        remaining = max_chars - used
        if remaining <= 0:
            break
        content = str(item.get("content") or "")[:remaining]
        used += len(content)
        parts.append(
            f"[仓库关键文件：{item.get('path')}]\n"
            f"URL：{item.get('url')}\n{content}"
        )
    return "\n\n" + "\n\n".join(parts) if parts else ""


def distill(
    article: Article,
    config_path: Optional[str] = None,
    evidence_articles: Optional[list[Article]] = None,
    two_stage: bool = True,
    editorial_review: bool = True,
    required_modes: tuple[str, ...] = ("full",),
    checkpoint_dir: str | None = None,
) -> dict:
    """把 Article 喂给 LLM，返回通过质量门禁的解读 dict。"""
    cfg = resolve_llm_settings(_load_config(config_path))
    if not cfg["api_key"]:
        raise RuntimeError(
            "没找到 LLM API key。请配置 ccswitch 当前 Codex 提供商、设置环境变量 "
            "DISTILL_LLM_KEY，或在 config.json 里填 api_key。\n"
            "国内可填 DeepSeek / 智谱 / 通义 / Kimi 的 key（都兼容 OpenAI 格式），并设 base_url。"
        )

    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("缺少 openai 库，请先 pip install openai") from e

    evidence_articles = evidence_articles or []
    if set(required_modes) != {"full"}:
        raise ValueError("article-distiller 只支持 full 深度文章")
    evidence_limit = 5
    evidence_char_limit = 12000
    repository_char_limit = 12000
    evidence_block = ""
    if evidence_articles:
        chunks = []
        for i, ev in enumerate(evidence_articles[:evidence_limit], 1):
            role = str(getattr(ev, "source_type", "supplemental") or "supplemental")
            label = {"official": "官方附件", "independent": "独立来源", "supplemental": "补充材料"}.get(role, "补充材料")
            chunks.append(
                f"[{label} {i} · role={role}]\n"
                f"标题：{ev.title or '(未提取到)'}\n"
                f"作者：{ev.author or '(未知)'}\n"
                f"URL：{ev.url}\n"
                f"正文：\n{ev.text[:evidence_char_limit]}"
                f"{_repository_files_block(ev, max_chars=repository_char_limit)}"
            )
        evidence_block = (
            "\n\n--- 已抓取的补充来源 ---\n"
            "official 只能佐证发布方口径，supplemental 只能补背景；只有 independent 可计为独立交叉核验。未抓取链接不能计入。\n\n"
            + "\n\n".join(chunks)
        )

    source_links = getattr(article, "source_links", []) or []
    media_assets = getattr(article, "media_assets", []) or []
    user_prompt = (
        f"原文标题：{article.title or '(未提取到)'}\n"
        f"作者：{article.author or '(未知)'}\n"
        f"发布日期：{article.date or '(未知)'}\n"
        f"来源 URL：{article.url}\n"
        f"抓取时间：{getattr(article, 'retrieved_at', '') or '(未知)'}\n"
        f"原文内容哈希：{getattr(article, 'content_hash', '') or '(未知)'}\n"
        f"可用来源链接（不得编造新链接）：{json.dumps(source_links, ensure_ascii=False)}\n"
        f"可用来源媒体（来自原文或已抓取附件；source_media 只能从这里选择）：{json.dumps(media_assets, ensure_ascii=False)}\n"
        f"正文（共 {article.text_chars} 字）：\n\n{article.text}"
        f"{evidence_block}"
    )

    writing_system_prompt = _system_prompt_for_modes(required_modes)
    full_review_system_prompt = _editorial_review_prompt_for_modes(required_modes)
    review_output_mode = _review_output_mode()
    review_system_prompt = (
        _editorial_patch_review_prompt_for_modes(required_modes)
        if review_output_mode == "patch"
        else full_review_system_prompt
    )
    fingerprint = _pipeline_fingerprint(
        article,
        evidence_articles[:evidence_limit],
        cfg,
        required_modes,
        writing_system_prompt,
        review_system_prompt,
        two_stage,
        editorial_review,
    )

    cfg = dict(cfg)
    timeout_default = _env_int("DISTILL_LLM_TIMEOUT_SECONDS", 240, 30)
    retry_default = _env_int("DISTILL_LLM_MAX_RETRIES", 1, 0)
    retry_delay_default = _env_int("DISTILL_LLM_RETRY_DELAY_SECONDS", 4, 0)
    retry_wait_default = _env_int("DISTILL_LLM_RETRY_MAX_WAIT_SECONDS", 15, 0)
    stream_default = os.getenv("DISTILL_LLM_STREAM", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }
    cfg["_manual_max_retries"] = retry_default
    cfg["_retry_delay_seconds"] = retry_delay_default
    cfg["_retry_max_wait_seconds"] = retry_wait_default
    cfg["_stream"] = stream_default
    stage_timings: dict[str, float] = {}

    def call_stage(system_prompt: str, user_prompt: str, temperature: float, stage: str) -> dict:
        started = time.monotonic()
        try:
            return _call_json(client, cfg, system_prompt, user_prompt, temperature, stage=stage)
        finally:
            stage_timings[stage] = round(time.monotonic() - started, 3)

    client_kwargs = {
        "base_url": cfg["base_url"],
        "api_key": cfg["api_key"],
        "timeout": timeout_default,
        "max_retries": 0,
    }
    client = OpenAI(**client_kwargs)

    research = _load_stage_checkpoint(checkpoint_dir, "research", fingerprint) if two_stage else None
    if two_stage:
        if research is None:
            try:
                research = call_stage(
                    RESEARCH_PROMPT,
                    user_prompt,
                    temperature=0.1,
                    stage="研究阶段",
                )
                _save_stage_checkpoint(checkpoint_dir, "research", fingerprint, research)
            except ValueError as exc:
                print(f"[研究阶段警告] {exc}；已回退为单阶段写作。", file=sys.stderr)
            except Exception:  # noqa: BLE001
                raise
        if research is not None:
            editorial_prompt = _build_draft_context(
                article,
                evidence_articles[:evidence_limit],
                research,
                user_prompt,
            )
        else:
            editorial_prompt = user_prompt
    else:
        editorial_prompt = user_prompt

    research_hash = _hash_payload(research or {})
    draft = _load_stage_checkpoint(
        checkpoint_dir, "writing", fingerprint, parent_hash=research_hash
    )
    if draft is None:
        draft = call_stage(
            writing_system_prompt,
            editorial_prompt,
            temperature=0.35,
            stage="写作阶段",
        )
        _save_stage_checkpoint(
            checkpoint_dir, "writing", fingerprint, draft, parent_hash=research_hash
        )
    result = draft
    review_meta: dict = {"status": "skipped", "selected_version": "draft"}
    selected_language_fixes: list[dict] = []
    if editorial_review:
        try:
            ledger_limit = 40000
            review_context = (
                "--- 原文标题 ---\n"
                + (article.title or "(未提取到)")
                + "\n\n--- 研究证据账本 ---\n"
                + _serialize_research_ledger(research or {}, max_chars=ledger_limit)
                + "\n\n--- 待审校完整草稿 ---\n"
                + _serialize_draft(draft)
            )
            if review_output_mode == "patch":
                review_prompt = (
                    review_context
                    + "\n\n请完整审校草稿，修复你发现的事实覆盖、结构、表达、语病、媒体和视觉组织问题，"
                    "返回 quality_report 和 article_patch。"
                    "只回传实际修改字段，不要回传未修改内容。"
                )
            else:
                review_prompt = (
                    review_context
                    + "\n\n请完整审校草稿，修复你发现的事实覆盖、结构、表达、语病、媒体和视觉组织问题，"
                    "并返回完整 revised_article，"
                    "不要只返回修改建议或局部字段。"
                )
            review_parent_hash = _hash_payload({
                "research": research or {},
                "draft": draft,
                "review_prompt_hash": _hash_payload(review_system_prompt),
            })
            reviewed = _load_stage_checkpoint(
                checkpoint_dir, "review", fingerprint, parent_hash=review_parent_hash
            )
            if reviewed is None:
                reviewed = call_stage(
                    review_system_prompt,
                    review_prompt,
                    temperature=0.15,
                    stage="编辑审校阶段",
                )
                _save_stage_checkpoint(
                    checkpoint_dir,
                    "review",
                    fingerprint,
                    reviewed,
                    parent_hash=review_parent_hash,
                )

            def load_full_review_fallback(reason: str) -> dict:
                print(
                    f"[编辑审校阶段] 补丁无效（{reason}），自动回退完整修订",
                    flush=True,
                )
                fallback_parent_hash = _hash_payload({
                    "research": research or {},
                    "draft": draft,
                    "full_review_prompt_hash": _hash_payload(full_review_system_prompt),
                })
                fallback_prompt = (
                    review_context
                    + "\n\n上一次补丁响应无法安全合并。请重新完成主编审校，并返回完整 "
                    "revised_article；不要返回 article_patch、修改建议或局部字段。"
                )
                fallback = _load_stage_checkpoint(
                    checkpoint_dir,
                    "review_full_fallback",
                    fingerprint,
                    parent_hash=fallback_parent_hash,
                )
                if fallback is None:
                    fallback = call_stage(
                        full_review_system_prompt,
                        fallback_prompt,
                        temperature=0.15,
                        stage="编辑审校完整回退阶段",
                    )
                    _save_stage_checkpoint(
                        checkpoint_dir,
                        "review_full_fallback",
                        fingerprint,
                        fallback,
                        parent_hash=fallback_parent_hash,
                    )
                return fallback

            actual_review_output_mode = review_output_mode
            revised = reviewed.get("revised_article")
            if isinstance(revised, dict):
                actual_review_output_mode = "full"
            elif isinstance(reviewed.get("article_patch"), dict):
                try:
                    revised = _apply_article_patch(draft, reviewed["article_patch"])
                    actual_review_output_mode = "patch"
                except ValueError as patch_exc:
                    if review_output_mode != "patch":
                        raise
                    reviewed = load_full_review_fallback(str(patch_exc))
                    revised = reviewed.get("revised_article")
                    if not isinstance(revised, dict):
                        raise ValueError("编辑审校完整回退阶段缺少 revised_article 对象")
                    actual_review_output_mode = "full_fallback"
            elif review_output_mode == "patch":
                reviewed = load_full_review_fallback("缺少可合并的 article_patch 对象")
                revised = reviewed.get("revised_article")
                if not isinstance(revised, dict):
                    raise ValueError("编辑审校完整回退阶段缺少 revised_article 对象")
                actual_review_output_mode = "full_fallback"
            else:
                raise ValueError("编辑审校阶段缺少完整 revised_article 对象")
            fixed_revised, revised_language_fixes = apply_safe_language_fixes(revised)
            result = fixed_revised
            selected = "revised"
            selected_language_fixes = revised_language_fixes
            review_meta = {
                "status": "completed",
                "selected_version": selected,
                "output_mode": actual_review_output_mode,
                "model_report": reviewed.get("quality_report") if isinstance(reviewed.get("quality_report"), dict) else {},
                "selection_basis": "审校稿默认进入成稿后统一质检；不在写作过程中重复运行完整门禁",
            }
        except ValueError as exc:
            print(f"[编辑审校警告] {exc}；将检查草稿是否达到发布门槛。", file=sys.stderr)
            review_meta = {
                "status": "review_failed",
                "selected_version": "draft",
                "output_mode": review_output_mode,
                "error": str(exc),
            }

    result, final_language_fixes = apply_safe_language_fixes(result)
    language_fixes = selected_language_fixes + final_language_fixes
    # 统一门禁必须在来源、媒体和数字字段完成确定性规范化后运行；否则
    # 原始 LLM JSON 中尚未补齐的 registered 标记会被误判为未登记素材。
    result = normalize_distilled(dict(result), article)
    final_audit = audit_distilled(result, research, required_modes, strict_editorial=True)

    if editorial_review and not final_audit.get("publishable"):
        repair_parent_hash = _hash_payload({
            "research": research or {},
            "result": result,
            "blockers": final_audit.get("blockers") or [],
            "repair_prompt_hash": _hash_payload(QUALITY_REPAIR_PATCH_PROMPT),
        })
        repair_prompt = (
            "--- 原文标题 ---\n"
            + (article.title or "(未提取到)")
            + "\n\n--- 必须消除的严格发布阻断项 ---\n"
            + json.dumps({
                "blockers": final_audit.get("blockers") or [],
                "warnings": final_audit.get("warnings") or [],
                "metrics": {
                    key: value
                    for key, value in (final_audit.get("metrics") or {}).items()
                    if key in {
                        "semantically_missing_high_claim_ids",
                        "unsupported_numbers",
                        "missing_high_metric_story_ids",
                        "incomplete_number_story_ids",
                        "incomplete_high_metric_story_claim_ids",
                        "meta_narration_section_indexes",
                        "meta_narration_public_paths",
                    }
                },
            }, ensure_ascii=False)
            + "\n\n--- 研究证据账本（仅保留修复所需口径） ---\n"
            + _serialize_research_ledger(research or {}, max_chars=12000)
            + "\n\n--- 当前完整文章 ---\n"
            + _serialize_draft(result, max_chars=36000)
            + "\n\n只修复上述阻断项，不删减已经通过的事实、实验、案例、来源和边界。"
            "请返回可确定合并的 article_patch，不要返回完整 revised_article。"
        )
        print(
            f"[质量修复阶段] 严格门禁仍有 {len(final_audit.get('blockers') or [])} 个阻断项，"
            "启动一次定向修复"
        )
        repaired_response = _load_stage_checkpoint(
            checkpoint_dir, "repair", fingerprint, parent_hash=repair_parent_hash
        )
        if repaired_response is None:
            repaired_response = call_stage(
                QUALITY_REPAIR_PATCH_PROMPT,
                repair_prompt,
                temperature=0.1,
                stage="质量修复阶段",
            )
            _save_stage_checkpoint(
                checkpoint_dir,
                "repair",
                fingerprint,
                repaired_response,
                parent_hash=repair_parent_hash,
            )
        repair_patch = repaired_response.get("article_patch")
        repaired = None
        if isinstance(repair_patch, dict):
            repaired = _apply_article_patch(result, repair_patch)
        elif isinstance(repaired_response.get("revised_article"), dict):
            # 兼容旧缓存/旧端点，但新请求协议默认只返回 patch。
            repaired = _merge_repair_candidate(result, repaired_response["revised_article"], article)
        if isinstance(repaired, dict):
            fixed_repaired, repair_language_fixes = apply_safe_language_fixes(repaired)
            result = normalize_distilled(fixed_repaired, article)
            language_fixes += repair_language_fixes
            review_meta = {
                **review_meta,
                "repair_status": "completed",
                "repair_selected_version": "revised",
                "repair_model_report": repaired_response.get("quality_report")
                if isinstance(repaired_response.get("quality_report"), dict)
                else {},
            }
            final_audit = audit_distilled(result, research, required_modes, strict_editorial=True)
        else:
            review_meta = {
                **review_meta,
                "repair_status": "invalid_response",
                "repair_error": "质量修复阶段缺少可合并的 article_patch 对象",
            }

    assert_publishable(final_audit, "编辑审校后的文章")
    result["editorial_quality"] = {
        **review_meta,
        "language_fixes": language_fixes,
        "language_fix_count": len(language_fixes),
        "stage_timings_seconds": stage_timings,
        "final_audit": final_audit,
    }
    if research is not None:
        result["research_ledger"] = research
    return result


def _is_response_format_error(exc: Exception) -> bool:
    """只对明确的 response_format 兼容性错误重试，避免吞掉鉴权/限流等错误。"""
    message = str(exc).lower()
    status_code = getattr(exc, "status_code", None)
    mentions_format = "response_format" in message or "json_object" in message
    unsupported = any(word in message for word in ("unsupported", "not support", "unknown", "invalid"))
    return mentions_format and unsupported and status_code in (None, 400, 404, 422)


def _serialize_research_ledger(research: dict, max_chars: int = 40000) -> str:
    """限制账本注入体积；保留结构，优先裁掉低优先级尾部主张。"""
    serialized = json.dumps(research, ensure_ascii=False)
    if len(serialized) <= max_chars:
        return serialized

    compact = dict(research)
    claims = list(compact.get("claims") or [])[:50]
    compact["claims"] = claims
    compact["background"] = list(compact.get("background") or [])[:20]
    compact["unknowns"] = list(compact.get("unknowns") or [])[:20]
    compact["experiments"] = list(compact.get("experiments") or [])[:12]
    compact["cases"] = list(compact.get("cases") or [])[:12]
    compact["source_assessment"] = str(compact.get("source_assessment") or "")[:3000]
    compact["ledger_truncated"] = True
    while claims and len(json.dumps(compact, ensure_ascii=False)) > max_chars:
        claims.pop()
    serialized = json.dumps(compact, ensure_ascii=False)
    if len(serialized) > max_chars:
        compact = {
            "claims": [],
            "experiments": [],
            "cases": [],
            "background": [],
            "unknowns": ["证据账本因体积过大已省略；写作必须保守，不得补写材料外事实。"],
            "source_assessment": str(research.get("source_assessment") or "")[:1000],
            "ledger_truncated": True,
        }
        serialized = json.dumps(compact, ensure_ascii=False)
    return serialized


def _serialize_draft(draft: dict, max_chars: int = 60000) -> str:
    """限制审校阶段的草稿体积，并始终返回合法 JSON。"""
    serialized = json.dumps(draft, ensure_ascii=False)
    if len(serialized) <= max_chars:
        return serialized
    compact = dict(draft)
    compact["draft_truncated_for_review"] = True
    for field, limit in (
        ("sections", 12), ("experiment_ledger", 12), ("case_stories", 12),
        ("number_stories", 20), ("evidence_gallery", 20),
        ("fact_check", 20), ("visuals", 8), ("source_media", 12),
        ("media_omissions", 20),
    ):
        if isinstance(compact.get(field), list):
            compact[field] = compact[field][:limit]
    serialized = json.dumps(compact, ensure_ascii=False)
    if len(serialized) > max_chars:
        raise ValueError("草稿过大，无法在不破坏 JSON 的情况下送入编辑审校阶段")
    return serialized


def _llm_error_summary(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if status:
        return f"HTTP {status} {exc.__class__.__name__}"
    return exc.__class__.__name__


def _is_retryable_llm_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status in {408, 409, 429, 500, 502, 503, 504, 524}:
        return True
    name = exc.__class__.__name__.lower()
    return "timeout" in name or "connection" in name


def _retry_wait_seconds(exc: Exception, cfg: dict, attempt: int) -> float:
    base = float(cfg.get("_retry_delay_seconds", 8) or 0) * attempt
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    retry_after = headers.get("retry-after") if hasattr(headers, "get") else None
    try:
        requested = float(retry_after) if retry_after is not None else 0.0
    except (TypeError, ValueError):
        requested = 0.0
    maximum = float(cfg.get("_retry_max_wait_seconds", 30) or 0)
    return max(0.0, min(max(base, requested), maximum))


def _is_streaming_error(exc: Exception) -> bool:
    message = str(exc).lower()
    status_code = getattr(exc, "status_code", None)
    return (
        status_code in (None, 400, 404, 422)
        and ("stream" in message or "streaming" in message)
        and any(word in message for word in ("unsupported", "not support", "unknown", "invalid"))
    )


def _create_completion(client, kwargs: dict, streaming: bool):
    request_kwargs = dict(kwargs)
    if streaming:
        request_kwargs["stream"] = True
    try:
        return client.chat.completions.create(
            response_format={"type": "json_object"}, **request_kwargs
        )
    except Exception as exc:  # noqa: BLE001
        if not _is_response_format_error(exc):
            raise
        return client.chat.completions.create(**request_kwargs)


def _completion_content(response, streaming: bool) -> str:
    choices = getattr(response, "choices", None)
    if choices is not None:
        try:
            return choices[0].message.content or ""
        except (AttributeError, IndexError, TypeError) as exc:
            raise ValueError("模型返回结构异常，未找到 choices[0].message.content") from exc
    if not streaming:
        raise ValueError("模型返回结构异常，非流式响应缺少 choices")

    chunks: list[str] = []
    try:
        for chunk in response:
            try:
                choice = chunk.choices[0]
            except (AttributeError, IndexError, TypeError):
                continue
            delta = getattr(choice, "delta", None)
            content = getattr(delta, "content", None) if delta is not None else None
            if isinstance(content, str):
                chunks.append(content)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    return "".join(chunks)


def _call_json(
    client,
    cfg: dict,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    stage: str = "LLM 阶段",
) -> dict:
    kwargs = dict(
        model=cfg["model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    manual_retries = cfg.get("_manual_max_retries")
    total_attempts = int(manual_retries) + 1 if manual_retries is not None else 1
    input_chars = len(system_prompt) + len(user_prompt)
    content = None
    streaming = bool(cfg.get("_stream", True))
    for attempt in range(1, total_attempts + 1):
        started = time.monotonic()
        suffix = f"/{total_attempts}" if total_attempts > 1 else ""
        transport = "流式" if streaming else "非流式"
        print(
            f"[{stage}] 模型调用 {attempt}{suffix} · 输入 {input_chars} 字 · {transport}",
            flush=True,
        )
        try:
            try:
                response = _create_completion(client, kwargs, streaming)
            except Exception as exc:  # noqa: BLE001
                if not streaming or not _is_streaming_error(exc):
                    raise
                print(f"[{stage}] 当前端点不支持流式返回，回退为非流式", flush=True)
                response = _create_completion(client, kwargs, False)
            content = _completion_content(response, streaming and not hasattr(response, "choices"))
        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - started
            retryable = manual_retries is not None and _is_retryable_llm_error(exc)
            if not retryable or attempt >= total_attempts:
                print(
                    f"[{stage}] 调用失败 · {elapsed:.1f} 秒 · {_llm_error_summary(exc)}",
                    file=sys.stderr,
                    flush=True,
                )
                raise
            wait_seconds = _retry_wait_seconds(exc, cfg, attempt)
            print(
                f"[{stage}] 第 {attempt} 次失败 · {elapsed:.1f} 秒 · "
                f"{_llm_error_summary(exc)} · {wait_seconds:.0f} 秒后重试",
                file=sys.stderr,
                flush=True,
            )
            if wait_seconds:
                time.sleep(wait_seconds)
            continue
        elapsed = time.monotonic() - started
        print(f"[{stage}] 模型返回 · {elapsed:.1f} 秒", flush=True)
        break
    if content is None:
        raise RuntimeError(f"{stage}未获得模型响应")

    try:
        result = _safe_json_load(content)
    except (json.JSONDecodeError, TypeError, AttributeError) as exc:
        preview = str(content).strip().replace("\n", " ")[:160]
        raise ValueError(f"{stage}未返回合法 JSON（开头：{preview!r}）") from exc
    if not isinstance(result, dict):
        raise ValueError(f"{stage}返回的 JSON 顶层必须是对象")
    return result


def _safe_json_load(content: str) -> dict:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # 兜底：剥掉可能的 ```json 包裹
        if content.startswith("```"):
            content = content.strip("`")
            if "{" in content and "}" in content:
                content = content[content.find("{") : content.rfind("}") + 1]
        return json.loads(content)


def build_manual_prompt(
    article: Article,
    evidence_articles: Optional[list[Article]] = None,
    required_modes: tuple[str, ...] = ("full",),
) -> str:
    """没 key 时的降级：返回让用户自己拿去任意 LLM 跑的解读 prompt 文本。"""
    evidence_articles = evidence_articles or []
    if set(required_modes) != {"full"}:
        raise ValueError("article-distiller 只支持 full 深度文章")
    evidence_limit = 5
    evidence_char_limit = 12000
    repository_char_limit = 12000
    evidence_block = ""
    if evidence_articles:
        chunks = []
        for i, ev in enumerate(evidence_articles[:evidence_limit], 1):
            role = str(getattr(ev, "source_type", "supplemental") or "supplemental")
            label = {"official": "官方附件", "independent": "独立来源", "supplemental": "补充材料"}.get(role, "补充材料")
            chunks.append(
                f"[{label} {i} · role={role}] {ev.title}\nURL：{ev.url}\n"
                f"{ev.text[:evidence_char_limit]}"
                f"{_repository_files_block(ev, max_chars=repository_char_limit)}"
            )
        evidence_block = "\n\n--- 已抓取的补充来源 ---\n只有 independent 可计为独立交叉核验。\n" + "\n\n".join(chunks)
    return (
        "# 解读 Prompt（复制到任意 LLM 对话框使用）\n\n"
        "把下面这段原文按下列要求做二次解读，严格输出 JSON：\n\n"
        "--- 原文信息 ---\n"
        f"标题：{article.title or '(未提取到)'}\n"
        f"作者：{article.author or '(未知)'}\n"
        f"来源：{article.url or '(未知)'}\n\n"
        f"可用来源媒体：{json.dumps(getattr(article, 'media_assets', []) or [], ensure_ascii=False)}\n\n"
        "--- 原文正文 ---\n"
        f"{article.text}\n\n"
        f"{evidence_block}\n\n"
        "--- 解读要求与输出格式 ---\n"
        f"{_system_prompt_for_modes(required_modes)}\n"
    )
