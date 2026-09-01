# 信息源清单

只登记本次确实读取、且能长期提供一手材料的 A/B 级来源。对标站、聚合页、媒体转述、未读取链接和只有线索价值的页面不入库。

默认清单位于 `~/.article-distiller/source-registry.md`。可用 `ARTICLE_DISTILLER_SOURCE_REGISTRY=/path/to/list.md` 指定已有清单；首次写入默认路径时脚本会创建规范表格。

```bash
python3 <skill-root>/scripts/source_registry.py \
  --level A --category 模型 \
  --title "来源名称" --publisher "发布方" \
  --url "https://example.com" --label "官方发布"
```

同一规范化 URL 只登记一次。等级只允许 A/B，分类只允许模型、产品、行业、工具、行业动态。
