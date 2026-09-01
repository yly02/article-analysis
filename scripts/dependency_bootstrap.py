"""Runtime dependency checks for the standalone article-distiller CLI.

Only standard-library imports live here so the CLI can recover when optional
runtime packages have not been installed yet.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys


PACKAGE_FOR_MODULE = {
    "trafilatura": "trafilatura>=2.2,<3",
    "lxml_html_clean": "lxml-html-clean>=0.4,<1",
    "openai": "openai>=1.0,<3",
    "docx": "python-docx>=1.1,<2",
    "pypdf": "pypdf>=5,<7",
    "playwright": "playwright>=1.50,<2",
}


def missing_modules(modules: list[str] | tuple[str, ...]) -> list[str]:
    return [module for module in modules if importlib.util.find_spec(module) is None]


def ensure_python_dependencies(
    modules: list[str] | tuple[str, ...],
    *,
    auto_install: bool = True,
) -> None:
    """Ensure importable modules, installing their pinned packages when possible."""
    missing = missing_modules(modules)
    if not missing:
        return
    packages = [PACKAGE_FOR_MODULE.get(module, module) for module in missing]
    command = [sys.executable, "-m", "pip", "install", *packages]
    if auto_install:
        print(
            "[依赖] 缺少 " + ", ".join(missing) + "，正在用当前 Python 自动安装…",
            file=sys.stderr,
            flush=True,
        )
        try:
            result = subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
            )
        except OSError as exc:
            result = None
            detail = str(exc)
        else:
            detail = "\n".join((result.stdout or "").splitlines()[-12:])
        if result is not None and result.returncode == 0 and not missing_modules(modules):
            print("[依赖] 自动安装完成：" + ", ".join(packages), flush=True)
            return
        status = detail or "pip 未返回可读错误"
        raise RuntimeError(
            "自动安装依赖失败。请确认当前 Python 为 3.10+ 且可访问 PyPI，"
            "然后手动执行：\n  " + " ".join(command) + "\n最近输出：\n" + status
        )
    raise RuntimeError(
        "缺少运行依赖：" + ", ".join(missing) + "。请执行：\n  " + " ".join(command)
    )


def runtime_python_check() -> None:
    if sys.version_info < (3, 10):
        raise RuntimeError(
            f"article-distiller 需要 Python 3.10+，当前是 {sys.version.split()[0]}。"
            "请安装 Python 3.10 或更新版本后重试。"
        )


def has_command(name: str) -> bool:
    from shutil import which

    return bool(which(name))
