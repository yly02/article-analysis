"""Best-effort OCR for registered chart images.

The default path uses macOS Vision through the bundled Swift helper. Tesseract is
used as a fallback when available. OCR text is discovery metadata, never primary
evidence, and callers must keep the original image and source URL.
"""

from __future__ import annotations

import json
import mimetypes
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


MAX_IMAGE_BYTES = 12 * 1024 * 1024
SOURCE_LABEL_RE = re.compile(
    r"(?:^|[\n.;。])\s*(?:source|sources|data source|来源|数据来源|资料来源)\s*[:：]\s*(.+)",
    flags=re.IGNORECASE,
)


def source_label_from_text(text: str) -> str:
    match = SOURCE_LABEL_RE.search(text or "")
    return match.group(1).strip()[:300] if match else ""


def _suffix_for(url: str, content_type: str) -> str:
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff", ".bmp"}:
        return suffix
    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    return guessed if guessed in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff", ".bmp"} else ".img"


def _download_image(url: str, timeout: int, max_bytes: int) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": "article-distiller/1.0"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-selected source media
        content_type = str(response.headers.get("Content-Type") or "")
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError(f"image exceeds {max_bytes} bytes")
    return payload, _suffix_for(url, content_type)


def _vision_ocr(path: str, timeout: int) -> dict | None:
    swift = shutil.which("swift")
    helper = Path(__file__).with_name("chart_ocr.swift")
    if not swift or not helper.exists():
        return None
    process = subprocess.run(
        [swift, str(helper), path],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError((process.stderr or process.stdout or "Vision OCR failed").strip()[:600])
    result = json.loads(process.stdout or "{}")
    return result if isinstance(result, dict) else {}


def _tesseract_ocr(path: str, timeout: int) -> dict | None:
    executable = shutil.which("tesseract")
    if not executable:
        return None
    process = subprocess.run(
        [executable, path, "stdout", "tsv"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError((process.stderr or "Tesseract OCR failed").strip()[:600])
    words: list[str] = []
    confidences: list[float] = []
    for line in process.stdout.splitlines()[1:]:
        fields = line.split("\t")
        if len(fields) < 12:
            continue
        word = fields[11].strip()
        if not word:
            continue
        words.append(word)
        try:
            confidence = float(fields[10])
        except ValueError:
            continue
        if confidence >= 0:
            confidences.append(confidence / 100)
    return {
        "text": " ".join(words),
        "confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
        "engine": "tesseract",
    }


def ocr_image_url(
    url: str,
    timeout: int = 30,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> dict:
    """Download one registered image and return bounded OCR metadata."""
    if not str(url or "").startswith(("http://", "https://")):
        return {"status": "skipped", "text": "", "confidence": 0.0, "source_label": ""}
    try:
        payload, suffix = _download_image(url, min(timeout, 20), max_bytes)
        with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
            handle.write(payload)
            handle.flush()
            result = _vision_ocr(handle.name, timeout) or _tesseract_ocr(handle.name, timeout)
        if result is None:
            return {"status": "unavailable", "text": "", "confidence": 0.0, "source_label": ""}
        text = str(result.get("text") or "").strip()[:6000]
        return {
            "status": "success" if text else "empty",
            "text": text,
            "confidence": round(float(result.get("confidence") or 0.0), 3),
            "engine": str(result.get("engine") or "vision"),
            "source_label": source_label_from_text(text),
        }
    except ValueError as exc:
        return {"status": "too_large", "text": "", "confidence": 0.0, "source_label": "", "error": str(exc)}
    except (OSError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"status": "failed", "text": "", "confidence": 0.0, "source_label": "", "error": str(exc)[:600]}


def enrich_chart_assets(
    assets: list[dict],
    enabled: bool = False,
    max_assets: int = 5,
    runner: Callable[[str], dict] | None = None,
) -> list[dict]:
    """OCR only likely charts; preserve all assets and never raise on OCR failure."""
    result = [dict(item) for item in assets]
    if not enabled:
        return result
    run = runner or ocr_image_url
    processed = 0
    for item in result:
        if processed >= max_assets:
            break
        if item.get("type") != "image" or item.get("asset_role") != "chart":
            continue
        ocr = run(str(item.get("url") or ""))
        processed += 1
        item["ocr_status"] = str(ocr.get("status") or "failed")
        item["ocr_text"] = str(ocr.get("text") or "")
        item["ocr_confidence"] = float(ocr.get("confidence") or 0.0)
        item["ocr_engine"] = str(ocr.get("engine") or "")
        if ocr.get("source_label") and not item.get("source_label"):
            item["source_label"] = str(ocr["source_label"])
        if ocr.get("error"):
            item["ocr_error"] = str(ocr["error"])
    return result
