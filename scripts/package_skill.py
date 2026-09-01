#!/usr/bin/env python3
"""Build the standalone deep-article Skill package."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


FILES = [
    "SKILL.md",
    "README.md",
    "requirements.txt",
    "examples/workflows.md",
    "examples/casebook.md",
    "references/article-depth.md",
    "references/article-imagegen.md",
    "references/chinese-grammar-review.md",
    "references/cli.md",
    "references/editorial-patterns.md",
    "references/editorial-quality.md",
    "references/evidence-schema.md",
    "references/human-writing.md",
    "references/research-and-media.md",
    "references/source-registry.md",
    "references/visual-selection.md",
    "scripts/article_imagegen.py",
    "scripts/chart_ocr.py",
    "scripts/chart_ocr.swift",
    "scripts/config.example.json",
    "scripts/check_environment.py",
    "scripts/dependency_bootstrap.py",
    "scripts/distill.py",
    "scripts/dynamic_media.py",
    "scripts/distiller.py",
    "scripts/editorial_quality.py",
    "scripts/evidence.py",
    "scripts/fetcher.py",
    "scripts/file_ingest.py",
    "scripts/language_quality.py",
    "scripts/media_audit.py",
    "scripts/package_skill.py",
    "scripts/renderer.py",
    "scripts/repository_reader.py",
    "scripts/runtime_paths.py",
    "scripts/run.py",
    "scripts/release_check.py",
    "scripts/source_registry.py",
]


def build(source_root: Path, output: Path) -> None:
    missing = [relative for relative in FILES if not (source_root / relative).is_file()]
    if missing:
        raise SystemExit("打包所需文件缺失：" + ", ".join(missing))
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in FILES:
            path = source_root / relative
            archive.write(path, Path("article-distiller") / relative)
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        required = {f"article-distiller/{relative}" for relative in FILES}
        if not required.issubset(names):
            raise SystemExit("压缩包缺少清单文件")


def main() -> None:
    parser = argparse.ArgumentParser(description="打包深度文章 article-distiller Skill")
    parser.add_argument("-o", "--output", required=True, help="输出 ZIP 路径")
    parser.add_argument(
        "--source-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Skill 源目录，默认取当前 scripts 的上级目录",
    )
    args = parser.parse_args()
    build(Path(args.source_root).resolve(), Path(args.output).expanduser().resolve())
    print(f"已生成深度版 Skill：{Path(args.output).expanduser().resolve()}")


if __name__ == "__main__":
    main()
