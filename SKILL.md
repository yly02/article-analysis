---
name: article-distiller
description: 将网页、论文、技术报告或本地文档转成面向非技术读者的中文深度解读 HTML；适用于需要来源核验、媒体提取、通俗写作、交互可视化和发布自检的 AI 内容。
---

# 深度文章解读

把原始材料写成一篇能独立阅读的深度文章，不做扩写摘要。成品围绕一个中心问题组织判断、证据、实验、案例、机制、限制与行动含义，写作标准是：真实为底，讲透为骨，人话为形，朋友感为声。

本 Skill 只生成深度文章 HTML，不生成一页纸、小红书卡片或多视图发布壳。

## 执行

要求 Python 3.10+。入口是 `scripts/run.py`：

```bash
python3 <skill-root>/scripts/run.py <URL-or-file> -o <output-base>
```

安装后可先运行：

```bash
python3 <skill-root>/scripts/run.py --check
python3 <skill-root>/scripts/run.py --check --no-llm
```

输入支持 URL、TXT、Markdown、HTML、PDF、DOCX 和 DOC。依赖缺失时入口会尝试用当前解释器安装；无法自动处理的 Python、浏览器、LibreOffice、OCR 或 API 配置必须给出可执行提示，不能静默降级。完整参数、环境变量、缓存和文件输入行为见 [references/cli.md](references/cli.md)。

第一次使用或需要确认输入方式、产物和失败边界时，读取 [examples/workflows.md](examples/workflows.md)。需要为具体材料选择叙事结构、媒体和交互组件时，按材料类型读取 [examples/casebook.md](examples/casebook.md) 中最接近的案例。示例用于说明决策，不是固定文章模板，也不能作为事实来源。

默认运行“研究账本 -> 正文写作 -> 主编审校 -> 成稿后统一质量门禁”三阶段。完整门禁不会在模型逐字生成过程中反复运行，而是在审校稿完成后集中检查；只有发现阻断项才追加一次定向修复和复检。`--source-only` 只生成深度文章 prompt 包；`--render` 渲染已有材料包与解读 JSON。不要为了提速默认跳过研究、主编审校或高优先级证据。

## 工作流

1. 读取原文、官方附件、相关仓库和必要的独立来源。网页抓取或媒体发现受阻时，先解决抓取，或使用浏览器限定到文章容器导出正文与 `page-assets.json`；不能基于空正文写作。
2. 建立原子主张、数字、实验、案例、来源和未知项组成的研究账本。只有实际读取且独立于发布方的材料才允许形成 `cross_checked`。
3. 先确定唯一中心问题、核心机制、目标读者、标题承诺、真实开头锚点和章节推进，再写正文。高优先级主张必须进入公开内容，或记录具体舍弃理由。
4. 根据读者要解决的问题选择正文、来源媒体或交互组件。每个章节通常只有一个主视觉；同一事实不得用正文、大表格、数字卡和原图重复铺陈。原页存在多个能力不同的演示时，按“能力覆盖”组合精选媒体，不得为了省篇幅一刀切只留一个；开头依赖的首屏视频必须采用，或记录具体、可核对的省略理由。
5. 主编审校完成后统一运行中文语病、事实与结构、证据与媒体对账、HTML 渲染和浏览器验收；若质量门禁发现阻断项，只做一次定向修复并复检后再交付。

## 按需读取

- 不确定如何处理 URL、本地文件、动态媒体或手动渲染：读取 [examples/workflows.md](examples/workflows.md)。
- 不确定某类文章适合什么开头、章节推进或视觉组件：只读取 [examples/casebook.md](examples/casebook.md) 中最接近的 1-3 个案例，不要复制案例标题、事实或整套结构。
- 开始写作或审稿：读取 [references/article-depth.md](references/article-depth.md)、[references/human-writing.md](references/human-writing.md)、[references/editorial-patterns.md](references/editorial-patterns.md) 和 [references/chinese-grammar-review.md](references/chinese-grammar-review.md)。
- 扩展来源、深读仓库或检查图片、视频、音频：读取 [references/research-and-media.md](references/research-and-media.md)。
- 修改主张、来源等级、实验、案例或数字结构：读取 [references/evidence-schema.md](references/evidence-schema.md)。
- 选择表格、播放器、关系组件或交互：读取 [references/visual-selection.md](references/visual-selection.md)。
- 修改确定性审校规则：读取 [references/editorial-quality.md](references/editorial-quality.md)。
- 用户明确授权生成解释配图：读取 [references/article-imagegen.md](references/article-imagegen.md)。默认不调用生图接口。
- 维护高质量信息源清单：读取 [references/source-registry.md](references/source-registry.md)。

## 发布不变量

- 事实、判断和未知必须分开。原文、模型卡、官方仓库和官方附件仍属于发布方证据；发现但未读取的链接不算证据。
- 原文确有实验时保留问题、环境、样本、模型、指标、结果、对照、人工条件和外推限制；原文确有事件链时才能重建案例，且不得伪装成逐字对话。
- 高优先级数字必须保留单位、统计对象或计时口径、时间、范围、对照或变化、限制和登记来源。审计字段不能原样暴露给读者，也不能连续渲染成多张大型数字卡。
- 来源媒体只能从注册表选用。视频必须展示产品操作、实验过程、前后差异、人物关键表述或机制变化；品牌片头、气氛动画、重复长图和装饰素材应登记省略理由。
- 原文中有可复用的提示词、时间码、参考素材分工或平台入口时，优先把它们整理成紧凑的指令卡、分镜时间线、素材分层或平台状态表；不要整段倾倒原文，也不要只做抽象概括。
- 外语媒体要补自然中文图注和具体观看重点；不得猜画面、伪造字幕或把第三方加工素材冒充原始证据。
- HTML 写盘前必须运行媒体对账，确保目标文章媒体、`Article.media_assets`、采用/省略决定和最终节点一致。动态发现失败时不得声称素材完整。
- 标题先放高认知主体，再放材料支持的具体动作、冲突、结果或完整口径数字；不能用陌生代号取代知名归属方，也不能编造极限结论。
- 首次出现且妨碍理解的术语先解释作用。存在稳定常用中文名时，正文首次出现写成 `原名（常用中文名）`；人名、品牌、产品、代码、模型编号和大众熟悉缩写不机械翻译，标题和表头不追加翻译括注。日期、数量和单位只保留一种清楚格式，不用括号重复同义写法。
- 文章必须有一条材料支持的独特判断和唯一核心机制。章节逐步增加事实、区别、机制、后果或选择，不能写成“背景、分析、影响、总结”的分类目录。
- 共鸣只能来自材料支持的真实处境、冲突、取舍与后果；不得虚构读者内心、朋友案例、第一人称经历、反问或强行升华。
- 视觉组件按关系选择，颜色只表达固定语义。流程、时间、层级、平级比较和数字关系不得为追求样式而互相冒充；窄屏不得溢出。
- `quick_scan` 是严格三条的一分钟速览；目录只负责章节导航。术语解释使用正文首处脚标浮层，必要原文引文才进入旁注。目录可点击空白或 Escape 收起，返回顶部控件必须真实可用。
- 发布页不显示内部 claim id、实验 id、审查过程、生成器名称或功能说明。资料来源放文章末尾，正文媒体图注不重复显示审计链接。
- 客户可见文本必须通过中文语病、指代、搭配、逻辑、数量范围和标点检查；高置信错误做最小修改，语境不明项不得猜原意。

## 交付与数据

只交付 HTML，并说明实际读取的独立材料以及仍仅来自发布方的结论。运行时数据默认写入 `~/.article-distiller/`，可由 `ARTICLE_DISTILLER_DATA_DIR` 覆盖；不得把历史索引、密钥或个人绝对路径打入发行包。

发布前运行 `scripts/release_check.py`、核心行为测试、Python 编译和 Skill validator。最终审计与阶段耗时写入运行时缓存中的 `final-quality.json`，不暴露到文章前端；发布检查必须从独立解包目录验证 `scripts/run.py`，不能只测试当前工作树。
