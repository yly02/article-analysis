# Article Analysis

面向非技术读者的 AI 深度文章解读 Skill。输入网页链接或本地 TXT、Markdown、HTML、PDF、DOCX、DOC 文件，生成经过研究、写作、主编审校和发布门禁的中文深度文章 HTML。

## 结构

```text
article-distiller/
|-- SKILL.md                  # 触发范围、执行流程、发布不变量与按需路由
|-- README.md                 # 安装、结构与最短使用说明
|-- examples/
|   |-- workflows.md         # URL、文件、媒体回灌和手动渲染实例
|   `-- casebook.md          # 17 篇真实测试文章的结构与视觉选择案例
|-- references/              # 写作、证据、媒体、视觉与审校的专项规则
|-- scripts/
|   |-- run.py               # 唯一公开入口与环境预检
|   |-- distill.py           # 抓取、研究、写作、审校和输出编排
|   |-- renderer.py          # 交互 HTML
|   `-- release_check.py     # 独立解包与发布检查
|-- tests/                   # 源码仓库中的行为回归测试，不进入发布 ZIP
`-- requirements.txt         # 最小 Python 依赖
```

运行框架保持单向：

```text
输入 -> 环境预检 -> 正文/媒体抓取 -> 研究证据账本
     -> 深度文章草稿 -> 主编审校 -> 确定性门禁
     -> HTML 渲染 -> 媒体对账与浏览器验收
```

`SKILL.md` 只保留每次任务都需要的规则；专项细节进入 `references/`，实际操作实例进入 [examples/workflows.md](examples/workflows.md)，真实文章经验进入 [examples/casebook.md](examples/casebook.md)。这样既能看清框架，也不会把全部说明一次塞进模型上下文。

## 安装

将仓库克隆到 Codex Skills 目录：

```bash
git clone https://github.com/yly02/article-analysis.git ~/.codex/skills/article-distiller
python3 ~/.codex/skills/article-distiller/scripts/check_environment.py --no-llm
```

需要 Python 3.10 或更新版本。环境检测和运行入口都会尝试自动安装缺少的 Python 依赖；无法自动安装时会给出对应命令。生成文章前需配置兼容 OpenAI Chat Completions 的模型接口：

```bash
export DISTILL_LLM_KEY="your-api-key"
export DISTILL_LLM_BASE_URL="https://your-endpoint.example/v1"
export DISTILL_LLM_MODEL="your-model"
```

## 使用

```bash
python3 ~/.codex/skills/article-distiller/scripts/run.py \
  "https://example.com/article" -o article

python3 ~/.codex/skills/article-distiller/scripts/run.py \
  report.pdf -o article
```

输出为单个深度解读 HTML。完整规则、证据边界与参数说明见 [SKILL.md](SKILL.md) 和 [references/cli.md](references/cli.md)。

更多完整例子见 [examples/workflows.md](examples/workflows.md) 和 [examples/casebook.md](examples/casebook.md)。
