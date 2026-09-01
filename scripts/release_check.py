#!/usr/bin/env python3
"""Deterministic release checks for the standalone deep article Skill."""

from __future__ import annotations

import argparse
import json
import os
import py_compile
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from package_skill import FILES, GENERATED_FILES, build


CORE_TESTS = (
    "test_hardening.py",
    "test_sources_media.py",
    "test_primary_repository.py",
    "test_file_ingest.py",
    "test_language_quality.py",
    "test_article_depth.py",
    "test_visual_selection.py",
    "test_interactive_progression.py",
    "test_metric_bars.py",
    "test_number_evidence.py",
    "test_responsive_article.py",
    "test_environment_portability.py",
)


def _run(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode:
        raise RuntimeError("命令失败：" + " ".join(command) + "\n" + result.stdout[-5000:])
    return result.stdout


def validate_source(source_root: Path, *, run_tests: bool = True) -> list[str]:
    errors: list[str] = []
    requirements = (source_root / "requirements.txt").read_text(encoding="utf-8")
    if "playwright" not in requirements:
        errors.append("requirements.txt 缺少 playwright")

    scan_files = [source_root / relative for relative in FILES if relative.endswith((".py", ".md", ".txt"))]
    for path in scan_files:
        text = path.read_text(encoding="utf-8")
        if ("/" + "Users/") in text or ("\\" + "Users\\") in text:
            errors.append(f"包含个人绝对路径：{path.relative_to(source_root)}")

    cli = (source_root / "references/cli.md").read_text(encoding="utf-8").casefold()
    for forbidden in ("--format all", "--format cards", "--format onepager", "小红书卡片"):
        if forbidden in cli:
            errors.append(f"深度版 CLI 文档含越界功能：{forbidden}")

    for path in (source_root / "scripts").glob("*.py"):
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(str(exc))
        legacy_copy = source_root / path.name
        if legacy_copy.is_file() and legacy_copy.read_bytes() != path.read_bytes():
            errors.append(f"根目录兼容副本与 scripts 主源码不一致：{path.name}")

    if run_tests:
        for name in CORE_TESTS:
            path = source_root / name
            if not path.is_file():
                errors.append(f"缺少核心测试：{name}")
                continue
            try:
                _run([sys.executable, str(path)], cwd=source_root)
            except RuntimeError as exc:
                errors.append(str(exc))
    return errors


def validate_archive(source_root: Path) -> list[str]:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="article-distiller-release-") as temp:
        temp_root = Path(temp)
        archive = temp_root / "article-distiller.zip"
        build(source_root, archive)
        with zipfile.ZipFile(archive) as handle:
            handle.extractall(temp_root / "unpacked")
        unpacked = temp_root / "unpacked/article-distiller"
        index = json.loads((unpacked / "data/concept_index.json").read_text(encoding="utf-8"))
        if index != {"concepts": {}, "articles": []}:
            errors.append("发行包概念索引不是空白运行时索引")
        try:
            help_text = _run([sys.executable, str(unpacked / "scripts/run.py"), "--help"], cwd=unpacked)
        except RuntimeError as exc:
            errors.append(str(exc))
        else:
            if "--format {full}" not in help_text or "onepager" in help_text or "cards" in help_text:
                errors.append("独立解包入口没有锁定为深度文章")
        source = temp_root / "sample.md"
        source.write_text("# 测试文章\n\n这是用于独立解包冒烟测试的正文。" * 20, encoding="utf-8")
        pack = temp_root / "sample.pack.json"
        try:
            output = _run([
                sys.executable,
                str(unpacked / "scripts/run.py"),
                "--from-text",
                str(source),
                "--source-only",
                "--no-dynamic-media",
                "--no-index",
                "-o",
                str(pack),
            ], cwd=unpacked)
        except RuntimeError as exc:
            errors.append(str(exc))
        else:
            if not pack.is_file():
                errors.append("独立解包 source-only 未生成材料包")
            if "onepager" in output.casefold() or "cards" in output.casefold() or "一页纸" in output:
                errors.append("独立解包 source-only 仍提示越界输出格式")
        for relative in [*FILES, *GENERATED_FILES]:
            if not (unpacked / relative).is_file():
                errors.append(f"发行包缺少：{relative}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="检查并冒烟测试 article-distiller 发布包")
    parser.add_argument("--source-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument(
        "--with-tests",
        action="store_true",
        help="同时运行开发目录中的核心行为与浏览器测试；发行包自检时不需要",
    )
    args = parser.parse_args()
    root = Path(args.source_root).expanduser().resolve()
    errors = [
        *validate_source(root, run_tests=args.with_tests),
        *validate_archive(root),
    ]
    if errors:
        print("article-distiller 发布检查失败：")
        for item in errors:
            print("- " + item)
        raise SystemExit(1)
    print("article-distiller 发布检查通过")


if __name__ == "__main__":
    main()
