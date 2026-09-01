# 使用实例

这些例子说明如何选择输入、补充材料和输出路径。它们不是固定写作模板，示例链接与标题也不能进入另一篇文章的事实账本。

## 例 1：网页文章直接生成 HTML

用户需求：

> 解读这篇产品发布文章，给非技术读者看，并保留真正有信息量的视频和图片。

```bash
python3 <skill-root>/scripts/run.py \
  "https://example.com/product-release" \
  -o output/article
```

系统应完成：

1. 抓取正文、元数据、链接与静态媒体。
2. 用浏览器渲染补查 iframe、懒加载图片和特殊播放器。
3. 读取相关官方附件、仓库和必要的独立来源。
4. 建立研究账本，生成深度文章并进行主编审校。
5. 输出 `output/article.html`，写盘前核对采用和省略的媒体。

媒体没有信息增量时登记省略理由，不因为原网页存在就机械照搬。

## 例 2：PDF 或 Word 研究材料

用户需求：

> 把这份研究报告写成通俗深度解读，实验条件和限制不能丢。

```bash
python3 <skill-root>/scripts/run.py report.pdf -o output/report
python3 <skill-root>/scripts/run.py report.docx -o output/report
```

PDF 有文本层时直接提取；扫描 PDF 必须先 OCR，不能把空白提取结果当正文。旧 `.doc` 需要 LibreOffice。研究型材料的实验记录应保留问题、样本、模型、指标、结果、对照、人工条件和外推限制。

## 例 3：显式补充来源和浏览器素材

用户需求：

> 原网页抓取不到视频；另有一篇独立评测可用于核验。

```bash
python3 <skill-root>/scripts/run.py \
  "https://example.com/original" \
  --page-assets page-assets.json \
  --independent-url "https://independent.example/review" \
  -o output/article
```

`page-assets.json` 只负责回灌浏览器发现的链接和媒体。候选链接必须成功读取后才算证据；同一发布方的模型卡、仓库和附件仍是官方证据，不能冒充独立复现。

## 例 4：先生成材料包，再手动渲染

没有可用 LLM 配置时：

```bash
python3 <skill-root>/scripts/run.py \
  "https://example.com/article" \
  --source-only \
  -o work/article.pack.json
```

把材料包中的 prompt 交给兼容模型，获得结构化解读 JSON 后：

```bash
python3 <skill-root>/scripts/run.py \
  --render work/article.pack.json work/distilled.json \
  -o output/article
```

渲染已有 JSON 仍执行证据、语言、结构与媒体门禁，不会把半成品直接端上页面。

## 成文骨架示例

下面展示的是信息推进关系，不是必须照抄的章节名：

```text
标题：先出现读者认识的主体，再给具体动作、冲突或结果
一分钟速览：变化 / 意义 / 证据边界，共三条
开头：真实动作或反常结果 -> 为什么值得在意 -> 主体与机制
正文 1：事情具体发生了什么
正文 2：为什么会出现这个结果
正文 3：实验、案例或关键数字怎样支撑判断
正文 4：哪些条件下结论不成立
结尾：明确回答开头问题，并说明读者下一步如何判断
页末：资料来源、独立核验与仍未知的边界
```

事件、产品、论文、调查和机制解释应选择不同的章节原型。每一节必须增加新事实、新区别、新机制或新后果；如果删掉一节不影响中心论证，这一节就不该存在。

真实材料的结构与视觉选择实例见 [casebook.md](casebook.md)。按当前材料选择最接近的 1-3 个案例即可，不要把案例库全部加载或机械拼接。
