"""Convert local text, PDF and Word files into the Article input contract."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from dependency_bootstrap import ensure_python_dependencies, has_command
from fetcher import Article, article_from_text


TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".text"}
HTML_EXTENSIONS = {".html", ".htm"}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
DOC_EXTENSIONS = {".doc"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | HTML_EXTENSIONS | PDF_EXTENSIONS | DOCX_EXTENSIONS | DOC_EXTENSIONS


def _fallback_title(path: Path) -> str:
    value = re.sub(r"[_-]+", " ", path.stem).strip()
    return value or "未命名文章"


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法按 UTF-8 或 GB18030 读取文件：{path}")


def _extract_pdf(path: Path) -> tuple[str, str, str]:
    ensure_python_dependencies(["pypdf"])
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    text = "\n\n".join(page for page in pages if page)
    metadata = reader.metadata or {}
    title = str(metadata.get("/Title") or "").strip()
    author = str(metadata.get("/Author") or "").strip()
    if not text:
        raise ValueError(
            f"PDF 没有可提取的文字：{path}。它可能是扫描件，请先 OCR，或提供可复制文字版。"
        )
    return text, title, author


def _iter_docx_blocks(document) -> Iterable[str]:
    """Yield paragraphs and tables in their original OOXML body order."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P

    parent = document.element.body
    for child in parent.iterchildren():
        if isinstance(child, CT_P):
            block = Paragraph(child, parent)
            value = block.text.strip()
            if value:
                yield value
        elif isinstance(child, CT_Tbl):
            table = Table(child, parent)
            rows = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                yield "\n".join(rows)


def _extract_docx(path: Path) -> tuple[str, str, str]:
    ensure_python_dependencies(["docx"])
    from docx import Document

    document = Document(str(path))
    text = "\n\n".join(_iter_docx_blocks(document)).strip()
    props = document.core_properties
    title = (props.title or "").strip()
    author = (props.author or "").strip()
    if not text:
        raise ValueError(f"Word 文档没有可提取的正文：{path}")
    return text, title, author


def _extract_legacy_doc(path: Path) -> tuple[str, str, str]:
    if not has_command("soffice"):
        raise RuntimeError(
            "读取 .doc 需要 LibreOffice（soffice），当前环境未找到。"
            "请安装 LibreOffice，或将文件另存为 .docx 后重试。"
        )
    with tempfile.TemporaryDirectory(prefix="article-distiller-doc-") as temp_dir:
        result = subprocess.run(
            [
                "soffice",
                "--headless",
                "--convert-to",
                "docx",
                "--outdir",
                temp_dir,
                str(path),
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        converted = Path(temp_dir) / f"{path.stem}.docx"
        if result.returncode != 0 or not converted.exists():
            detail = (result.stdout or "").strip() or "LibreOffice 未生成转换文件"
            raise RuntimeError(f".doc 转换失败：{detail}")
        return _extract_docx(converted)


def _extract_html(path: Path) -> str:
    ensure_python_dependencies(["trafilatura", "lxml_html_clean"])
    import trafilatura

    raw = _read_text(path)
    return (trafilatura.extract(raw, include_comments=False, include_tables=True, favor_recall=True) or "").strip()


def article_from_file(
    file_path: str,
    *,
    url: str = "",
    title: str = "",
    author: str = "",
) -> Article:
    path = Path(os.path.abspath(os.path.expanduser(file_path)))
    if not path.is_file():
        raise FileNotFoundError(f"本地文件不存在：{path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"暂不支持 {suffix or '(无扩展名)'} 文件；支持：{supported}")

    extracted_title = ""
    extracted_author = ""
    if suffix in TEXT_EXTENSIONS:
        text = _read_text(path).strip()
    elif suffix in HTML_EXTENSIONS:
        text = _extract_html(path)
    elif suffix in PDF_EXTENSIONS:
        text, extracted_title, extracted_author = _extract_pdf(path)
    elif suffix in DOCX_EXTENSIONS:
        text, extracted_title, extracted_author = _extract_docx(path)
    else:
        text, extracted_title, extracted_author = _extract_legacy_doc(path)
    if not text:
        raise ValueError(f"文件正文为空：{path}")
    source_url = url.strip() or path.as_uri()
    return article_from_text(
        text,
        url=source_url,
        title=title.strip() or extracted_title or _fallback_title(path),
        author=author.strip() or extracted_author,
    )
