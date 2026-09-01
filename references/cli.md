# CLI 与运行环境

仅在需要运行脚本、配置接口或排查环境时读取。本 Skill 只输出深度文章 HTML/Markdown；入口始终是 `scripts/run.py`，不要直接调用内部共享模块 `distill.py`。

## 安装与预检

```bash
PY=python3
SKILL_ROOT=/path/to/article-distiller

$PY --version
$PY -m pip install -r "$SKILL_ROOT/requirements.txt"
$PY "$SKILL_ROOT/scripts/run.py" --check
```

要求 Python 3.10+。正常运行也会执行预检；缺少 Python 模块时优先用当前解释器自动安装，失败后给出同一解释器的手动命令。Playwright 优先使用系统 Chrome、Edge 或 Chromium，没有可用浏览器时安装 Playwright Chromium。旧 `.doc` 另需 LibreOffice `soffice`；扫描 PDF 没有文本层时需先 OCR。

LLM 配置优先级：环境变量、显式配置文件、ccswitch 当前 Codex 提供商。支持：

- `DISTILL_LLM_KEY`
- `DISTILL_LLM_BASE_URL`
- `DISTILL_LLM_MODEL`
- `--config /path/to/config.json`

接口须兼容 OpenAI Chat Completions。ccswitch 只有在能解析出当前提供商、密钥和基础地址时才算配置有效；不得仅凭数据库文件存在就通过预检。

## 常用命令

```bash
# 深度文章 HTML；默认执行研究、写作、主编审校
$PY "$SKILL_ROOT/scripts/run.py" <URL> -o article

# 同时输出 HTML 与 Markdown
$PY "$SKILL_ROOT/scripts/run.py" <URL> --both -o article

# PDF、Word 或本地正文
$PY "$SKILL_ROOT/scripts/run.py" report.pdf --both -o article
$PY "$SKILL_ROOT/scripts/run.py" report.docx --both -o article
$PY "$SKILL_ROOT/scripts/run.py" --from-text raw.md --title "标题" --both -o article

# 无 LLM 配置时先生成 prompt 包，之后渲染深度文章
$PY "$SKILL_ROOT/scripts/run.py" <URL> --source-only -o pack.json
$PY "$SKILL_ROOT/scripts/run.py" --render pack.json distilled.json --both -o article

# 回灌浏览器发现的来源和媒体
$PY "$SKILL_ROOT/scripts/run.py" <URL> --page-assets page-assets.json --both -o article

# 显式补充官方和独立来源
$PY "$SKILL_ROOT/scripts/run.py" <URL> \
  --official-url <OFFICIAL_URL> \
  --independent-url <INDEPENDENT_URL> \
  --both -o article

# 可选解释配图
$PY "$SKILL_ROOT/scripts/run.py" <URL> --article-images generate \
  --article-image-count 2 --article-image-size 1536x864 -o article
```

## 关键参数

- `--both`：输出 HTML 和 Markdown；`--md` 只输出 Markdown。深度版不接受 `--format`。
- `--source-only`：只抓取材料并生成 prompt 包，不调用 LLM。
- `--render PACK DISTILLED`：使用已有材料包和解读 JSON 渲染，仍执行确定性证据与质量门禁。
- `--page-assets FILE`：合并浏览器导出的来源与媒体清单；候选链接仍须成功读取后才算证据。
- `--no-dynamic-media`：显式跳过动态媒体发现，仅在用户接受可能遗漏时使用。
- `--dynamic-media-timeout MS`：动态检查超时，默认 25000 毫秒。
- `--official-url`、`--independent-url`、`--evidence-url`：补充来源；只有成功读取的独立来源可产生交叉核验。
- `--official-source-limit 0..5`：补充来源总数上限。候选合并后统一评分，再截取前 N 个。
- `--repo-file-limit 0..8`：GitHub 仓库最多读取的关键文件数；失败状态会进入材料包和发布门禁，不得静默退化。
- `--no-repo-deep-read`：显式关闭仓库深读。
- `--chart-ocr`：对疑似图表执行本地 OCR，仅用于追溯来源线索。
- `--article-images off|prompts|generate|reuse`：关闭、只生成提示词、实际生成或复用长文解释图。
- `--skip-editorial-review`：保留研究和写作，跳过主编审校。
- `--single-pass`：只调用一次写作模型，与 `--skip-editorial-review` 互斥。
- `--stage-cache-dir`、`--no-stage-cache`：指定或关闭来源与模型阶段缓存。
- `--no-index`：不查询或更新用户运行时概念索引。
- `--gen-skill`：把本文知识体系写入用户运行时数据目录。

## 缓存与运行时数据

默认用户数据目录为 `~/.article-distiller/`，可用 `ARTICLE_DISTILLER_DATA_DIR` 覆盖。概念索引、领域知识包和可选信息源清单都写入该目录，不写回 Skill 安装目录，也不依赖某台电脑的绝对路径。

模型请求默认流式返回并有限重试。来源快照与阶段缓存默认有效 24 小时；网页正常抓取时始终以最新正文计算指纹，只有同一 URL 抓取失败时才恢复有效期内的真实材料快照。

## 维护验证

```bash
$PY "$SKILL_ROOT/scripts/release_check.py" --source-root "$SKILL_ROOT" --with-tests
$PY /path/to/skill-creator/scripts/quick_validate.py "$SKILL_ROOT"
```

发布检查必须验证：依赖清单、无个人绝对路径、深度版入口、空白运行时索引、Python 编译、核心行为测试和独立解包冒烟测试。
