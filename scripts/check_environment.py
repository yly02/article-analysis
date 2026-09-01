#!/usr/bin/env python3
"""Portable installation preflight for the standalone deep-article Skill."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

from dependency_bootstrap import ensure_python_dependencies, missing_modules


MIN_PYTHON = (3, 10)


def _config_has_key(config_path: str | None) -> tuple[bool, str]:
    if not config_path:
        return False, ""
    path = Path(config_path).expanduser()
    if not path.is_file():
        return False, f"配置文件不存在：{path}"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, f"配置文件不可读或不是合法 JSON：{path}"
    if isinstance(value, dict) and str(value.get("api_key") or "").strip():
        return True, str(path)
    return False, f"配置文件缺少 api_key：{path}"


def _input_suffix(input_path: str | None) -> str:
    return Path(input_path).expanduser().suffix.lower() if input_path else ""


def _ccswitch_is_usable(path: Path) -> bool:
    connection = None
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        provider = connection.execute(
            "select id, settings_config from providers "
            "where app_type=? and is_current=1 limit 1",
            ("codex",),
        ).fetchone()
        if provider is None:
            return False
        settings = json.loads(provider["settings_config"] or "{}")
        auth = settings.get("auth") if isinstance(settings.get("auth"), dict) else {}
        api_key = any(
            str(auth.get(key) or "").strip()
            for key in ("api_key", "apiKey", "key", "token", "openai_api_key", "OPENAI_API_KEY")
        )
        endpoint = connection.execute(
            "select url from provider_endpoints "
            "where app_type=? and provider_id=? order by id asc limit 1",
            ("codex", provider["id"]),
        ).fetchone()
        config_text = settings.get("config") if isinstance(settings.get("config"), str) else ""
        base_match = re.search(
            r'(?m)^\s*(?:base_url|baseUrl|baseURL|api_base|endpoint|openai_base_url|OPENAI_BASE_URL)\s*=\s*["\']([^"\']+)["\']',
            config_text,
        )
        base_url = base_match.group(1) if base_match else str(endpoint["url"] if endpoint else "")
        return bool(api_key and base_url.strip())
    except (sqlite3.Error, json.JSONDecodeError, OSError, TypeError, ValueError):
        return False
    finally:
        if connection is not None:
            connection.close()


def check_environment(
    *,
    require_llm: bool = True,
    config_path: str | None = None,
    input_path: str | None = None,
    chart_ocr: bool = False,
    dynamic_media: bool = True,
    auto_install: bool = True,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    actions: list[str] = []

    if sys.version_info < MIN_PYTHON:
        errors.append(
            f"Python 版本过低：当前 {platform.python_version()}，需要 Python 3.10+。"
            "请安装新版 Python 后，用同一个解释器重新运行。"
        )

    modules = ["trafilatura", "lxml_html_clean"]
    suffix = _input_suffix(input_path)
    if suffix == ".pdf":
        modules.append("pypdf")
    elif suffix == ".docx":
        modules.append("docx")
    if require_llm:
        modules.append("openai")
    if dynamic_media:
        modules.append("playwright")

    missing = missing_modules(modules)
    if missing and auto_install and sys.version_info >= MIN_PYTHON:
        try:
            ensure_python_dependencies(missing)
            actions.append("已自动安装：" + ", ".join(missing))
            missing = missing_modules(modules)
        except RuntimeError as exc:
            errors.append(str(exc))
    if missing:
        errors.append("缺少 Python 依赖：" + ", ".join(missing))

    if suffix == ".doc" and not shutil.which("soffice"):
        errors.append(
            "读取 .doc 需要 LibreOffice（soffice），当前未找到；"
            "请安装 LibreOffice，或将文件另存为 .docx。"
        )
    if suffix == ".pdf":
        actions.append("PDF 将在本地提取文字，不上传第三方转换服务")
    if suffix in {".doc", ".docx"}:
        actions.append("Word 正文将在本地提取")

    if require_llm:
        configured = bool(os.environ.get("DISTILL_LLM_KEY", "").strip())
        source = "DISTILL_LLM_KEY"
        config_detail = ""
        if not configured and config_path:
            configured, config_detail = _config_has_key(config_path)
            source = config_detail or str(Path(config_path).expanduser())
        if not configured and not config_path:
            ccswitch = Path.home() / ".cc-switch/cc-switch.db"
            if ccswitch.is_file() and _ccswitch_is_usable(ccswitch):
                configured, source = True, str(ccswitch)
        if not configured:
            detail = f"（{config_detail}）" if config_detail else ""
            errors.append(
                "未找到 LLM API Key" + detail + "。请设置 DISTILL_LLM_KEY，或用 --config 指向含 api_key 的 JSON；"
                "也可以配置 ccswitch 当前提供商。"
            )
        else:
            actions.append(f"已发现 LLM 配置：{source}")

    if chart_ocr and not (shutil.which("tesseract") or platform.system() == "Darwin"):
        warnings.append("未找到 tesseract；图表 OCR 需要安装 Tesseract，或在 macOS 使用 Vision。")
    if dynamic_media and "playwright" not in missing:
        actions.append("已具备动态网页媒体发现模块；首次运行会自动寻找或安装 Chromium")

    return {
        "ok": not errors,
        "python": platform.python_version(),
        "input_suffix": suffix,
        "errors": errors,
        "warnings": warnings,
        "actions": actions,
    }


def format_report(report: dict[str, Any]) -> str:
    lines = [f"article-distiller 环境检查：{'通过' if report['ok'] else '未通过'}"]
    lines.append(f"Python：{report['python']}")
    for item in report.get("actions", []):
        lines.append(f"已满足：{item}")
    for item in report.get("warnings", []):
        lines.append(f"可选提醒：{item}")
    for item in report.get("errors", []):
        lines.append(f"需要处理：{item}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="检查 article-distiller 安装环境")
    parser.add_argument("--config", help="config.json 路径")
    parser.add_argument("--input", help="待处理的本地文件路径，用于检查 PDF/Word 环境")
    parser.add_argument("--no-llm", action="store_true", help="只检查抓取和文件转换，不要求 LLM key")
    parser.add_argument("--chart-ocr", action="store_true", help="同时检查图表 OCR 可选环境")
    parser.add_argument("--no-dynamic-media", action="store_true", help="不检查动态网页媒体发现环境")
    parser.add_argument("--json", action="store_true", dest="as_json", help="以 JSON 输出检查结果")
    args = parser.parse_args()
    report = check_environment(
        require_llm=not args.no_llm,
        config_path=args.config,
        input_path=args.input,
        chart_ocr=args.chart_ocr,
        dynamic_media=not args.no_dynamic_media,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.as_json else format_report(report))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
