#!/usr/bin/env python3
"""Fixed standalone entrypoint for the deep article-distiller Skill."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

from check_environment import check_environment, format_report


SHARED_SCRIPT = Path(__file__).resolve().with_name("distill.py")


def _option_value(argv: list[str], name: str) -> str | None:
    for index, value in enumerate(argv):
        if value.startswith(name + "="):
            return value.split("=", 1)[1]
        if value == name and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _input_path(argv: list[str]) -> str | None:
    explicit = _option_value(argv, "--from-text")
    if explicit:
        return explicit
    for value in argv:
        if value.startswith("-"):
            continue
        path = Path(value).expanduser()
        if path.is_file():
            return str(path)
    return None


def _preflight(argv: list[str]) -> None:
    if "--help" in argv or "-h" in argv:
        return
    if "--check" in argv:
        check_args = [value for value in argv if value != "--check"]
        report = check_environment(
            require_llm="--no-llm" not in check_args,
            config_path=_option_value(check_args, "--config"),
            input_path=_option_value(check_args, "--input"),
            chart_ocr="--chart-ocr" in check_args,
            dynamic_media="--no-dynamic-media" not in check_args,
        )
        print(format_report(report))
        raise SystemExit(0 if report["ok"] else 1)
    source_only = "--source-only" in argv
    render_mode = "--render" in argv
    report = check_environment(
        require_llm=not source_only and not render_mode,
        config_path=_option_value(argv, "--config"),
        input_path=_input_path(argv),
        chart_ocr="--chart-ocr" in argv,
        dynamic_media="--no-dynamic-media" not in argv and "--render" not in argv,
    )
    print(format_report(report), file=sys.stderr)
    if not report["ok"]:
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    _preflight(args)
    sys.path.insert(0, str(SHARED_SCRIPT.parent))
    sys.argv = [str(SHARED_SCRIPT), *args]
    runpy.run_path(str(SHARED_SCRIPT), run_name="__main__")


if __name__ == "__main__":
    main()
