# 证据结构与判定规则

修改证据规范化、事实核查、来源展示或研究 prompt 时读取。

## 来源注册表

`Article.source_links[]` 是本次运行实际知道的来源注册表：

```json
{
  "url": "https://example.com/report",
  "title": "可选标题",
  "author": "可选作者",
  "source_type": "discovered|official|supplemental|independent",
  "fetched": true,
  "retrieved_at": "ISO-8601 UTC",
  "content_hash": "SHA-256"
}
```

- 页面解析出的普通链接登记为 `discovered`、`fetched:false`。
- 原文自身是 `original`。
- 发布方模型卡、文档、仓库、论文和许可证登记为 `official`。
- 跨站但尚未确认独立性的材料登记为 `supplemental`。
- 只有明确通过 `--independent-url` 提供且成功抓取的材料登记为 `independent`。
- 相同规范化 URL 如同时存在 discovered 与 fetched 记录，采用 fetched 记录。
- 自动发现只抓取原文页面实际链接的高置信官方附件，默认上限为 5；发现但未读取的链接不算证据。版本公告、版本特定模型卡和仓库优先于通用文档与许可证页。

## 每条主张

```json
{
  "claim": "可核查的原子主张",
  "verdict": "确认|原文声称|交叉验证|存疑|夸大|无法核实",
  "note": "判定解释",
  "evidence_status": "cross_checked|source_only|missing",
  "evidence": [
    {
      "url": "真实来源 URL",
      "source_type": "original|official|supplemental|independent|unverified_link",
      "publisher": "发布者",
      "quote": "支持主张的短引文",
      "support": "支持或反驳什么",
      "registered": true,
      "fetched": true,
      "retrieved_at": "ISO-8601 UTC",
      "content_hash": "SHA-256"
    }
  ]
}
```

规范化器以注册表为准覆盖 LLM 声称的 `source_type`：

- 原文 URL → `original`
- 注册且成功抓取的独立来源 → `independent`
- 注册且成功抓取的官方附件或补充材料 → 保留 `official` 或 `supplemental`
- 其他 URL → `unverified_link`

`cross_checked` 必须至少包含一条 fetched independent evidence。原文、同一 URL 的变体、页面发现链接、抓取失败链接或仅由 LLM 给出的链接都不满足条件。

## 来源媒体

`Article.media_assets[]` 是抓取阶段登记的原始素材注册表：

```json
{
  "id": "media-1",
  "type": "image|video|audio",
  "url": "https://example.com/demo.webp",
  "poster_url": "",
  "alt": "可选替代文本",
  "source_url": "https://example.com/article",
  "source_type": "original_media|official_media|supplemental_media|independent_media",
  "extracted": true,
  "caption": "原页面 figure caption",
  "section_title": "最近的章节标题",
  "document_order": 3,
  "asset_role": "chart|screenshot|demo|hero|photo|other",
  "source_label": "图注或 OCR 识别的来源标签",
  "upstream_source_candidates": ["https://example.com/methodology"]
}
```

音频素材还可带抓取阶段从同一演示行提取的 `prompt` 与 `lyrics`。成稿不把音频混入普通 `source_media` 或证据图库，而用 `listening_cards[]` 绑定登记的 audio `media_id`：

```json
{
  "id": "style-range",
  "title": "同一模型怎样跨越不同曲风",
  "intro": "选择差异明显的官方样曲，听它怎样处理节奏、音色与语言。",
  "after_section_id": "capabilities",
  "boundary": "官方精选样曲展示能力范围，不等于随机样本或独立盲测。",
  "tracks": [{
    "media_id": "media-7",
    "label": "电子舞曲",
    "prompt": "抓取登记中的真实提示词",
    "lyrics_excerpt": "可选歌词摘录",
    "listening_points": ["副歌进入前的层次变化", "人声与鼓点是否互相遮挡"]
  }]
}
```

规范化器以媒体注册表覆盖曲目 URL、来源、提示词和歌词，写入 `registered`。缺少登记音频、真实章节锚点、提示词、听感重点或证据边界时，严格发布被阻止。HTML 切换曲目时暂停其他音频；Markdown 降级为官方音频链接、提示词和要点列表。

成稿的 `source_media[]` 只能引用这个注册表中的 `media_id` 或 URL，并提供 `caption` 与真实的 `after_section_id`。原文素材登记为 `original_media`；实际抓取附件中的素材按来源角色登记。规范化器会覆盖 URL、类型和来源，写入 `registered`；未登记、重复或锚点无效的媒体会阻止严格发布。渲染器只显示 `registered:true` 的项目。媒体属于来源素材，不提升事实主张的独立证据等级。

每个 `asset_role=demo|hero` 的视频都必须在发布前作出明确决定：进入 `source_media[]`，或进入 `media_omissions[]`。省略记录格式为 `{"media_id": "media-1", "reason": "具体理由"}`；理由必须说明素材为何只是装饰、与正文重复或与中心论证无关。未登记、空理由、重复记录、同一媒体既采用又省略，都会阻止严格发布。

## 数字叙事

研究账本先用 `claim_kind=metric|date|version|fact` 区分主张。所有数量、比例、价格、性能、样本和增减幅度都属于 `metric`。high metric 必须映射到 `number_stories[]`：

```json
{
  "id": "benchmark-success",
  "title": "这个数字回答的问题",
  "value": "68",
  "unit": "%",
  "denominator": "100 次测试",
  "scope": "厂商给定测试集",
  "period": "2026 年 8 月发布时",
  "baseline": "对照组 50%",
  "change": "+18 个百分点",
  "boundary": "不能外推为所有真实任务的成功率",
  "labels": {
    "denominator": "统计对象",
    "scope": "适用场景",
    "period": "统计时间",
    "baseline": "对照情况",
    "change": "结果变化",
    "boundary": "这个数字不能说明什么"
  },
  "source_url": "https://example.com/report",
  "source_asset_ids": ["media-3"],
  "claim_ids": ["c4"],
  "after_section_id": "results",
  "importance": "high"
}
```

规范化器校验来源 URL 与媒体 ID，写入 `registered_source_asset_ids`、`unregistered_source_asset_ids`、`source_registered` 和 `complete`。只有同时具备主数字、单位、分母或计时口径、适用范围、时间、对照或变化、限制说明以及至少一个登记来源时，`display_mode` 才是 `stat`；否则强制为 `prose`。“未知”“未提供”“无明确对照”等占位内容不算完整口径。不完整 high metric 会阻止严格发布，普通数字只产生降级警告。

`labels` 只控制发布页用词，不参与完整性判断。没有提供时，HTML 使用“统计对象、适用场景、统计时间、对照情况、结果变化、这个数字不能说明什么”。若字段实际描述计时起点、单次事件或特定比较，应改成“计时口径、对应事件、过去的处理方式”等具体关系，不能把内部字段名“分母、范围、边界”直接展示给读者。

## 原始证据图库

`evidence_gallery[]` 只引用已登记媒体。规范化器会自动合并显式图库、正文 `source_media` 和数字故事的 `source_asset_ids`，按规范化 URL 去重。HTML 与 Markdown 均默认折叠展示缩略图、说明、原始文件和来源页面。OCR 的 `source_label` 与 `ocr_confidence` 只用于追踪线索，不改变 verdict、`evidence_status` 或独立覆盖率。

## 汇总

```json
{
  "claims": 5,
  "claims_with_evidence": 5,
  "claims_with_independent_source": 2,
  "coverage": 1.0,
  "independent_coverage": 0.4
}
```

`claims_with_evidence` 包含只有原文证据的主张；它不表示独立核验。UI 必须优先显示 `independent_coverage` 的含义，避免把“有链接”包装成“多源验证”。

## 幂等性

`normalize_distilled()` 可以重复运行：

- 不重复追加可信度 warning。
- 当前已有独立覆盖时，移除之前由规范化器添加的“尚未完成独立来源交叉核验”warning。
- 保留用户或 LLM 的其他 `source_notes`。
- 更新 `evidence_policy` 中属于当前 Article 的 URL、抓取时间、哈希和来源注册表。
