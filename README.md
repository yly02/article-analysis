# Article Analysis

面向非技术读者的 AI 深度文章解读 Skill。输入网页链接或本地 TXT、Markdown、HTML、PDF、DOCX、DOC 文件，生成经过研究、写作、主编审校和发布门禁的中文深度文章 HTML/Markdown。

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
  "https://example.com/article" --both -o article

python3 ~/.codex/skills/article-distiller/scripts/run.py \
  report.pdf --both -o article
```

输出为深度解读 HTML 和 Markdown。完整规则、证据边界与参数说明见 [SKILL.md](SKILL.md) 和 [references/cli.md](references/cli.md)。
