"""为深度文章生成证据边界清晰的解释性配图。"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import struct
import sys
from typing import Any, Callable

from fetcher import Article


RELAY_SCRIPT = Path.home() / ".codex" / "skills" / "relay-imagegen" / "scripts" / "relay_imagegen.py"
ALLOWED_ROLES = {"mechanism", "workflow", "concept", "case_context"}


def _clean_text(value: Any, limit: int = 320) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _concept_text(value: Any, limit: int = 420) -> str:
    """移除易被误画成事实截图的 URL 和精确量化信息。"""
    text = _clean_text(value, limit * 2)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[$￥¥]?\d+(?:[.,]\d+)*(?:%|倍|秒|分钟|小时|GB|GiB|B|元|美元)?", "", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _slug(value: Any, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", str(value or "").strip().lower()).strip("-")
    return slug[:64] or fallback


def _relay_script(path: str | None = None) -> Path:
    configured = path or os.environ.get("RELAY_IMAGEGEN_SCRIPT")
    script = Path(configured).expanduser() if configured else RELAY_SCRIPT
    if not script.is_file():
        raise FileNotFoundError(
            f"找不到 relay-imagegen：{script}。请先安装 relay-imagegen，"
            "或用 RELAY_IMAGEGEN_SCRIPT 指定脚本。"
        )
    return script


def _normalize_targets(article: Article, distilled: dict, max_images: int) -> list[dict]:
    sections = distilled.get("sections") or []
    section_ids = {
        str(section.get("id") or "").strip()
        for section in sections
        if isinstance(section, dict) and str(section.get("id") or "").strip()
    }
    raw_plan = distilled.get("illustration_plan")
    if not isinstance(raw_plan, list):
        raw_plan = []

    targets = []
    seen = set()
    for index, raw in enumerate(raw_plan, 1):
        if len(targets) >= max_images:
            break
        if not isinstance(raw, dict):
            continue
        anchor = str(raw.get("after_section_id") or "").strip()
        if not anchor or anchor not in section_ids:
            continue
        target_id = _slug(raw.get("id"), f"illustration-{index:02d}")
        if target_id in seen:
            continue
        role = str(raw.get("role") or "concept").strip().lower()
        if role not in ALLOWED_ROLES:
            role = "concept"
        title = _clean_text(raw.get("title") or "解释性配图", 120)
        purpose = _concept_text(raw.get("purpose"), 300)
        scene = _concept_text(raw.get("scene") or raw.get("prompt"), 520)
        if not scene:
            continue
        mapping = raw.get("visual_mapping") or []
        mapping_text = "；".join(
            f"{_concept_text(item.get('element'), 80)} represents {_concept_text(item.get('meaning'), 120)}"
            for item in mapping
            if isinstance(item, dict) and item.get("element") and item.get("meaning")
        )
        prompt = (
            "Create a 16:9 landscape editorial explanatory illustration for a serious Chinese technology article.\n"
            f"Editorial topic: {_concept_text(article.title or distilled.get('distilled_title'), 160)}\n"
            f"Illustration role: {role}.\n"
            f"Reader learning goal: {purpose or title}\n"
            f"Scene and composition: {scene}\n"
            f"Visual mapping: {mapping_text or 'Use spatial hierarchy and material contrast to make the mechanism understandable.'}\n"
            "Art direction: high-end contemporary technology editorial visual with precision geometry, crisp edges, controlled "
            "depth, deliberate negative space, and a restrained white, ice-blue, graphite, and selective cyan palette. Use "
            "specific forms derived from the described mechanism instead of symbolic clip art. The result should feel authored, "
            "calm, exact, and publication-ready, with one clear focal hierarchy and coherent studio lighting.\n"
            "This is a conceptual explanation, not documentary evidence. Do not invent results or depict exact statistics, "
            "benchmarks, dates, prices, product interfaces, dashboards, editing consoles, color-grading screens, charts, identifiable "
            "people, logos, watermarks, or branded hardware. No visible words, letters, numbers, labels, pseudo-text, or UI. Avoid generic AI brains, humanoid robots, "
            "glowing circuit backgrounds, decorative sci-fi imagery, watercolor, hand-drawn paper texture, sketch lines, doodles, "
            "generic tool symbols, stock icon collages, template infographic styling, plastic 3D clip art, and arbitrary decoration."
        )
        seen.add(target_id)
        targets.append({
            **raw,
            "id": target_id,
            "role": role,
            "title": title,
            "purpose": purpose,
            "scene": scene,
            "after_section_id": anchor,
            "alt": _clean_text(raw.get("alt") or f"{title}的 AI 概念示意", 180),
            "caption": _clean_text(
                raw.get("caption") or f"{title}：根据正文制作的 AI 概念示意，用于辅助理解，不是原始证据。",
                260,
            ),
            "prompt": prompt,
        })
    return targets


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    if mime not in {"image/png", "image/jpeg", "image/webp"}:
        raise ValueError(f"不支持内嵌的图片格式：{path.suffix}")
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError(f"图片超过 20 MB，拒绝内嵌：{path}")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    """无需额外依赖读取 PNG 尺寸；未知格式返回 None。"""
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) >= 24 and header[:8] == b"\x89PNG\r\n\x1a\n" and header[12:16] == b"IHDR":
        return struct.unpack(">II", header[16:24])
    return None


def enhance_article_images(
    article: Article,
    distilled: dict,
    output_base: str,
    mode: str = "prompts",
    max_images: int = 2,
    size: str = "1536x864",
    relay_config: str | None = None,
    plan_file: str | None = None,
    reuse_manifest: str | None = None,
    relay_script: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    """准备长文解释图提示词；generate 模式会生图并写回 illustration_plan。"""
    if mode not in {"prompts", "generate", "reuse"}:
        raise ValueError("article image mode 必须是 prompts、generate 或 reuse")
    if plan_file:
        plan_path = Path(plan_file).expanduser().resolve()
        if not plan_path.is_file():
            raise FileNotFoundError(f"长文配图计划不存在：{plan_path}")
        raw_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if isinstance(raw_plan, dict):
            raw_plan = raw_plan.get("illustration_plan")
        if not isinstance(raw_plan, list):
            raise ValueError("长文配图计划必须是数组，或包含 illustration_plan 数组的 JSON 对象")
        distilled["illustration_plan"] = raw_plan
    max_images = max(1, min(int(max_images), 3))
    root = Path(f"{output_base}_article_assets").expanduser().resolve()
    prompt_dir = root / "prompts"
    image_dir = root / "images"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    if mode == "generate":
        image_dir.mkdir(parents=True, exist_ok=True)

    targets = _normalize_targets(article, distilled, max_images)
    if not targets:
        raise ValueError(
            "没有可用的 illustration_plan。请为至少一个正文 section 提供 scene 和 after_section_id，"
            "并先确认已有来源媒体或代码化视觉组件无法更清楚地解释同一内容。"
        )
    script = _relay_script(relay_script) if mode == "generate" else None
    reusable_items = {}
    if mode == "reuse":
        if not reuse_manifest:
            raise ValueError("reuse 模式需要 --article-image-manifest")
        reuse_path = Path(reuse_manifest).expanduser().resolve()
        if not reuse_path.is_file():
            raise FileNotFoundError(f"复用 manifest 不存在：{reuse_path}")
        previous = json.loads(reuse_path.read_text(encoding="utf-8"))
        reusable_items = {
            str(item.get("id") or ""): item
            for item in (previous.get("items") or [])
            if isinstance(item, dict) and item.get("id") and item.get("output")
        }
    manifest_items = []
    rendered_plan = []

    for target in targets:
        prompt_path = prompt_dir / f"{target['id']}.txt"
        prompt_path.write_text(target["prompt"] + "\n", encoding="utf-8")
        item = {
            "id": target["id"],
            "role": target["role"],
            "after_section_id": target["after_section_id"],
            "prompt_file": str(prompt_path),
            "status": "prompt_ready",
        }
        rendered = {key: value for key, value in target.items() if key != "prompt"}
        rendered["status"] = "prompt_ready"
        if mode == "reuse":
            previous_item = reusable_items.get(target["id"])
            if not previous_item:
                raise ValueError(f"复用 manifest 缺少图片：{target['id']}")
            output_path = Path(str(previous_item["output"])).expanduser().resolve()
            if not output_path.is_file():
                raise FileNotFoundError(f"待复用图片不存在：{output_path}")
            dimensions = _image_dimensions(output_path)
            rendered.update({
                "status": "generated",
                "image_path": str(output_path),
                "image_data_uri": _data_uri(output_path),
            })
            item.update({
                "status": "reused",
                "output": str(output_path),
                "metadata": previous_item.get("metadata"),
                "requested_size": previous_item.get("requested_size"),
                "actual_size": f"{dimensions[0]}x{dimensions[1]}" if dimensions else previous_item.get("actual_size"),
                "size_match": previous_item.get("size_match"),
                "visual_review": previous_item.get("visual_review") or "required",
                "reused_from": str(reuse_path),
            })
        elif mode == "generate":
            output_path = image_dir / f"{target['id']}.png"
            cmd = [
                sys.executable,
                str(script),
                "generate",
                "--prompt-file",
                str(prompt_path),
                "--out",
                str(output_path),
                "--size",
                size,
                "--force",
            ]
            if relay_config:
                cmd.extend(["--config", str(Path(relay_config).expanduser())])
            result = runner(cmd, text=True, capture_output=True)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "relay-imagegen 调用失败").strip()
                raise RuntimeError(f"{target['id']} 长文配图生成失败：{detail[-1600:]}")
            if not output_path.is_file():
                raise RuntimeError(f"{target['id']} 生成后没有找到输出：{output_path}")
            dimensions = _image_dimensions(output_path)
            rendered.update({
                "status": "generated",
                "image_path": str(output_path),
                "image_data_uri": _data_uri(output_path),
            })
            item.update({
                "status": "generated",
                "output": str(output_path),
                "metadata": str(output_path.with_suffix(".meta.json")),
                "requested_size": size,
                "actual_size": f"{dimensions[0]}x{dimensions[1]}" if dimensions else None,
                "size_match": bool(dimensions and f"{dimensions[0]}x{dimensions[1]}" == size),
                "visual_review": "required",
            })
        rendered_plan.append(rendered)
        manifest_items.append(item)

    distilled["illustration_plan"] = rendered_plan
    manifest = {
        "version": 1,
        "mode": mode,
        "size": size,
        "image_count": len(manifest_items),
        "policy": "AI explanatory illustrations are not source evidence.",
        "items": manifest_items,
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"manifest": str(manifest_path), "items": manifest_items, "mode": mode}
