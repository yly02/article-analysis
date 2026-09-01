# 深度文章解释配图

用户要求在原始素材之外补充解释性图片时读取。该阶段依赖已安装的 `relay-imagegen`，CLI 默认关闭；只有用户明确要求实际生图时才使用 `generate`。授权后，非空 `illustration_plan` 表示成稿确实需要解释图：最终发布必须生成或复用对应图片，不能把只有提示词的 HTML 当成完成品。

## 适用范围

- 适合：需要空间、材质、尺度、氛围或难以代码化的机制剖面与案例环境。
- 不适合：跑分、价格、发布日期、产品 UI、真实人物、真实案例结果、原始证据截图。
- 已有原始证据图能清楚说明时，优先使用原图；不要为凑数量重复画一遍。原文或已抓取官方材料包含架构图时，先登记并使用来源图；只有没有直接图示、但正文确实需要解释时，才补 AI 概念图。
- 流程、资格漏斗、数值排名、前后变化、状态覆盖、条件决策、层级、时间、对比和因果关系优先使用 HTML/CSS 组件。已有 `flow`、`funnel_flow`、`rank_bars`、`delta_table`、`status_matrix`、`decision_table`、`layer_stack`、`timeline`、`compare_table` 或相关官方视频时，不得把相同信息再自动推导成 AI 位图。
- 每篇默认最多 2 张，只有三个不同机制都确有解释价值时才增加到 3 张。

图片必须标为“AI 概念示意”，caption 说明它帮助理解什么，并明确“不是原始证据”。图片不得提升任何 claim 的核验等级。

默认视觉风格：现代科技编辑视觉，使用精确几何、清晰边缘、克制纵深、明确焦点和充足留白；配色以白、冰蓝、石墨色为主，青色只用于关键强调。画面必须从具体机制推导形体，不能用通用图标代替内容。禁止水彩、暖白纸张、手绘纹理、草图线、涂鸦、素材库图标拼贴、塑料感 3D clip art、模板化信息图、装饰性科幻背景、通用剪辑/调色/控制台界面、产品仪表盘、伪文字、Logo、水印和品牌硬件；不要让读者把概念图误认成真实产品截图。

## 候选筛选

AI 位图不能一张直出即发布。先用同一内容目标生成至少 2 个构图候选，再逐张检查：信息是否具体、层级是否清楚、是否出现通用图标拼贴或错误暗示、与相邻官方媒体和代码化组件是否重复。只保留最能降低理解成本的一张；候选都不合格时，回到 `illustration_plan` 修改构图，或取消生图。当前 CLI 每次生成一个候选，批量候选应使用不同输出基名重复运行，人工选定后再以 `reuse` 嵌入成稿，避免把未审核候选直接发布。

## illustration_plan

长文 JSON 可提供：

```json
{
  "illustration_plan": [
    {
      "id": "rendering-mechanism",
      "role": "mechanism",
      "title": "结构生成与细节渲染分阶段",
      "after_section_id": "rendering-mechanism",
      "purpose": "让读者看懂结构规划和细节还原为什么分成两个阶段",
      "scene": "左侧是稀疏的运动骨架和少量清晰关键帧，右侧逐步还原为完整连续画面",
      "visual_mapping": [
        {"element": "稀疏骨架", "meaning": "压缩潜空间中的运动结构"},
        {"element": "清晰关键帧", "meaning": "细节锚点"}
      ],
      "alt": "结构规划与细节渲染分阶段的概念示意",
      "caption": "结构生成与细节渲染的 AI 概念示意；用于辅助理解，不是模型架构原图。"
    }
  ]
}
```

`role` 只能是 `mechanism|workflow|concept|case_context`。`after_section_id` 必须命中正文 section。`scene` 描述可见主体、空间关系和构图，不写风格口号，不要求生成文字、数字、Logo 或界面。

## 命令

只生成提示词和 manifest，不调用图片接口：

```bash
python scripts/run.py --render pack.json distilled.json \
  --article-images prompts -o article
```

实际生成 2 张 16:9 解释图并嵌入 HTML：

```bash
python scripts/run.py --render pack.json distilled.json \
  --article-images generate --article-image-count 2 \
  --article-image-plan illustration-plan.json -o article
```

文章文字改动后复用已经审核通过的图片，不产生新的图片 token：

```bash
python scripts/run.py --render pack.json distilled.json \
  --article-images reuse --article-image-plan illustration-plan.json \
  --article-image-manifest previous_article_assets/manifest.json -o article-revised
```

输出位于 `<output-base>_article_assets/`，包含 prompts、图片、relay 的非密钥 sidecar 和 manifest。生成失败时停止发布并报告非密钥错误，不静默输出缺图版本。默认 `1536x864` 足够正文窄栏的 Retina 显示，也比 2560x1440 更省图片 token；需要印刷或大屏再显式提高尺寸。

执行完成后把已审核图片的 `status=generated` 与 `image_path` 保留在文章 JSON，或在后续渲染中使用 `reuse` manifest。否则再次使用默认 `off` 重渲染时，策划仍在但图片会消失。

`--article-image-plan` 接受上述数组，或包含 `illustration_plan` 数组的 JSON 对象。它适合给旧文章补图和人工精修构图，不会改写原始 distilled JSON。

## 生成后检查

接口成功不等于图片可发布。逐张查看并检查：

- 是否出现伪文字、数字、Logo、水印或容易被误认成真实产品的 UI。
- 是否忠实表达 `visual_mapping`，而不是只生成主题相关的装饰场景。
- 是否暗示正文没有证据支持的性能、因果关系、人物或案例结果。
- 主体在桌面和移动端裁切后是否仍清楚，画面内是否留有足够呼吸空间。
- caption 是否准确说明图意并保留“AI 概念示意、不是原始证据”的边界。
- 是否与本章的官方图、视频或代码化组件重复；重复时删除 AI 图。
- 是否出现水彩纸张、手绘线条、通用工具图标、模板信息图或廉价 3D 素材感；出现任一项即退回重做。

manifest 的 `requested_size`、`actual_size` 和 `size_match` 用于发现 relay 降采样；`visual_review` 在人工看图前保持 `required`。不合格时修改 plan 后重新生成，不要只改 caption 掩盖画面问题。
