"""证据账本与解读结果校验。

这个模块不替 LLM 猜事实。它只负责把“来源元数据、证据链接、核查状态”
整理成稳定结构，并在缺少证据时降低结论强度，避免把“原文声称”渲染成
“系统确认”。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit


VERDICTS = {"确认", "原文声称", "交叉验证", "存疑", "夸大", "无法核实"}
TRUST_WARNING = "当前仅能证明这些内容出现在原文或原文提供的来源中，尚未完成独立来源交叉核验。"
UNKNOWN_NUMBER_VALUES = {"未知", "不详", "未提供", "材料未提供", "无明确对照", "unknown", "n/a", "na"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def source_kind(url: str, original_url: str = "") -> str:
    if not url:
        return "unknown"
    if original_url and url_key(url) == url_key(original_url):
        return "original"
    host = (urlsplit(url).hostname or "").lower()
    if host.startswith("x.com") or host.startswith("twitter.com"):
        return "social"
    if host.endswith(".gov") or host.endswith(".gov.cn"):
        return "government"
    return "external"


def normalize_url(url: str) -> str:
    return (url or "").strip().rstrip(".,;:)]}>")


def url_key(url: str) -> str:
    """生成用于去重和同源判断的稳定 URL key，不丢弃 query。"""
    clean = normalize_url(url)
    if not clean:
        return ""
    try:
        parts = urlsplit(clean)
    except ValueError:
        return clean.rstrip("/")
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if not scheme or not host:
        return clean.rstrip("/")
    try:
        port = parts.port
    except ValueError:
        return clean.rstrip("/")
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if not port or default_port else f"{host}:{port}"
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def urls_from_text(text: str) -> list[str]:
    """从 LLM 备注或旧 JSON 中提取 URL，去重并保持顺序。"""
    found: list[str] = []
    for raw in re.findall(r"https?://[^\s<>\"']+", text or ""):
        url = normalize_url(raw)
        if url and url not in found:
            found.append(url)
    return found


def _evidence_item(item: Any, article_url: str) -> dict:
    if isinstance(item, str):
        return {
            "url": normalize_url(item),
            "source_type": source_kind(item, article_url),
            "quote": "",
            "support": "未提供逐字引文；仅记录来源链接。",
        }
    if not isinstance(item, dict):
        return {}
    url = normalize_url(str(item.get("url") or ""))
    result = {
        "url": url,
        "source_type": item.get("source_type") or source_kind(url, article_url),
        "publisher": str(item.get("publisher") or ""),
        "quote": str(item.get("quote") or ""),
        "support": str(item.get("support") or ""),
    }
    if item.get("retrieved_at"):
        result["retrieved_at"] = str(item["retrieved_at"])
    if item.get("content_hash"):
        result["content_hash"] = str(item["content_hash"])
    return result


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _known_number_context(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.casefold() not in UNKNOWN_NUMBER_VALUES


def _normalize_number_stories(
    raw_stories: Any,
    media_by_id: dict[str, dict],
    registered_source_urls: set[str],
) -> list[dict]:
    stories = []
    if not isinstance(raw_stories, list):
        return stories
    for index, raw in enumerate(raw_stories):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
        source_asset_ids = _clean_string_list(item.get("source_asset_ids"))
        registered_asset_ids = [asset_id for asset_id in source_asset_ids if asset_id in media_by_id]
        missing_asset_ids = [asset_id for asset_id in source_asset_ids if asset_id not in media_by_id]
        source_url = normalize_url(str(item.get("source_url") or ""))
        source_registered = bool(source_url and url_key(source_url) in registered_source_urls)
        suppress_visual = item.get("suppress_visual") is True or item.get("display_mode") == "audit_only"
        has_source = source_registered or bool(registered_asset_ids)
        has_change_context = _known_number_context(item.get("baseline")) or _known_number_context(item.get("change"))
        complete = all(
            _known_number_context(item.get(field))
            or _known_number_context(labels.get(field))
            for field in ("value", "unit", "denominator", "scope", "period", "boundary")
        ) and has_change_context and has_source
        item.update({
            "id": str(item.get("id") or f"number-{index + 1}").strip(),
            "title": str(item.get("title") or "").strip(),
            "value": str(item.get("value") or "").strip(),
            "unit": str(item.get("unit") or "").strip(),
            "denominator": str(item.get("denominator") or "").strip(),
            "scope": str(item.get("scope") or "").strip(),
            "period": str(item.get("period") or "").strip(),
            "baseline": str(item.get("baseline") or "").strip(),
            "change": str(item.get("change") or "").strip(),
            "boundary": str(item.get("boundary") or "").strip(),
            "source_url": source_url,
            "source_asset_ids": source_asset_ids,
            "registered_source_asset_ids": registered_asset_ids,
            "unregistered_source_asset_ids": missing_asset_ids,
            "source_registered": source_registered,
            "claim_ids": _clean_string_list(item.get("claim_ids")),
            "after_section_id": str(item.get("after_section_id") or "").strip(),
            "importance": str(item.get("importance") or "medium").strip().lower(),
            "complete": complete,
            # Incomplete numbers may remain as prose, but never become visual headline stats.
            "suppress_visual": suppress_visual,
            "display_mode": "audit_only" if suppress_visual else ("stat" if complete else "prose"),
        })
        stories.append(item)
    return stories


def _normalize_evidence_gallery(
    raw_gallery: Any,
    normalized_media: list[dict],
    number_stories: list[dict],
    media_by_id: dict[str, dict],
) -> list[dict]:
    requested: list[dict] = []
    if isinstance(raw_gallery, list):
        requested.extend(item for item in raw_gallery if isinstance(item, dict))
    requested.extend(
        {"media_id": item.get("media_id"), "caption": item.get("caption") or ""}
        for item in normalized_media
        if item.get("registered") is True
    )
    for story in number_stories:
        requested.extend(
            {
                "media_id": media_id,
                "caption": story.get("title") or "数字依据",
                "claim_ids": story.get("claim_ids") or [],
            }
            for media_id in story.get("registered_source_asset_ids") or []
        )

    gallery = []
    seen_urls = set()
    for raw in requested:
        media_ids = _clean_string_list(raw.get("source_asset_ids"))
        single = str(raw.get("media_id") or raw.get("id") or "").strip()
        if single:
            media_ids.insert(0, single)
        for media_id in dict.fromkeys(media_ids):
            asset = media_by_id.get(media_id)
            if not asset:
                continue
            url = normalize_url(str(asset.get("url") or ""))
            key = url_key(url)
            if not key or key in seen_urls:
                continue
            seen_urls.add(key)
            gallery.append({
                "media_id": media_id,
                "type": str(asset.get("type") or "image"),
                "url": url,
                "poster_url": str(asset.get("poster_url") or ""),
                "caption": str(raw.get("caption") or asset.get("caption") or asset.get("alt") or "").strip(),
                "asset_role": str(asset.get("asset_role") or "other"),
                "section_title": str(asset.get("section_title") or ""),
                "source_url": str(asset.get("source_url") or ""),
                "source_label": str(asset.get("source_label") or ""),
                "upstream_source_candidates": _clean_string_list(asset.get("upstream_source_candidates")),
                "ocr_status": str(asset.get("ocr_status") or ""),
                "ocr_confidence": asset.get("ocr_confidence"),
                "claim_ids": _clean_string_list(raw.get("claim_ids")),
                "registered": True,
            })
    return gallery


def _normalize_listening_cards(raw_cards: Any, media_by_id: dict[str, dict], media_by_url: dict[str, dict]) -> list[dict]:
    """Bind listening tracks to audio assets captured during fetching."""
    if not isinstance(raw_cards, list):
        return []
    cards = []
    for card_index, raw_card in enumerate(raw_cards):
        if not isinstance(raw_card, dict):
            continue
        card = dict(raw_card)
        tracks = []
        raw_tracks = card.get("tracks") if isinstance(card.get("tracks"), list) else []
        for track_index, raw_track in enumerate(raw_tracks):
            if not isinstance(raw_track, dict):
                continue
            track = dict(raw_track)
            media_id = str(track.get("media_id") or track.get("id") or "").strip()
            requested_url = normalize_url(str(track.get("url") or ""))
            asset = media_by_id.get(media_id) or media_by_url.get(url_key(requested_url))
            registered = bool(asset and str(asset.get("type") or "").strip().lower() == "audio")
            track.update({
                "id": str(track.get("id") or f"track-{card_index + 1}-{track_index + 1}").strip(),
                "media_id": str(asset.get("id") or media_id).strip() if asset else media_id,
                "registered": registered,
                "listening_points": _clean_string_list(track.get("listening_points")),
            })
            if asset:
                track["type"] = str(asset.get("type") or "")
                track["url"] = str(asset.get("url") or requested_url)
                track["source_url"] = str(asset.get("source_url") or "")
                track["prompt"] = str(track.get("prompt") or asset.get("prompt") or "").strip()
                track["lyrics_excerpt"] = str(
                    track.get("lyrics_excerpt") or asset.get("lyrics") or ""
                ).strip()[:800]
                track["label"] = str(
                    track.get("label") or asset.get("title") or asset.get("alt") or f"样曲 {track_index + 1}"
                ).strip()
            tracks.append(track)
        card.update({
            "id": str(card.get("id") or f"listening-{card_index + 1}").strip(),
            "title": str(card.get("title") or "听一听模型真正做出了什么").strip(),
            "intro": str(card.get("intro") or "").strip(),
            "boundary": str(card.get("boundary") or "").strip(),
            "after_section_id": str(card.get("after_section_id") or "").strip(),
            "tracks": tracks,
            "registered": bool(tracks) and all(track.get("registered") is True for track in tracks),
        })
        cards.append(card)
    return cards


def normalize_distilled(distilled: dict, article: Any) -> dict:
    """给旧/新 JSON 补齐证据字段，并降低无证据结论的强度。"""
    if not isinstance(distilled, dict):
        raise ValueError("解读 JSON 顶层必须是对象")
    data = dict(distilled)
    article_url = str(getattr(article, "url", "") or "")
    article_hash = str(getattr(article, "content_hash", "") or "")
    source_links = list(getattr(article, "source_links", []) or [])
    registry: dict[str, dict] = {}
    for source in source_links:
        if not isinstance(source, dict) or not source.get("url"):
            continue
        key = url_key(str(source.get("url") or ""))
        current = registry.get(key)
        if current is None or (not current.get("fetched") and source.get("fetched")):
            registry[key] = source

    prior_policy = data.get("evidence_policy") if isinstance(data.get("evidence_policy"), dict) else {}
    data["evidence_policy"] = {
        **prior_policy,
        "original_url": article_url,
        "retrieved_at": getattr(article, "retrieved_at", "") or "",
        "article_hash": article_hash,
        "source_links": source_links,
    }
    media_assets = [
        asset for asset in (getattr(article, "media_assets", []) or [])
        if isinstance(asset, dict) and asset.get("url")
    ]
    media_by_id = {
        str(asset.get("id") or "").strip(): asset
        for asset in media_assets
        if str(asset.get("id") or "").strip()
    }
    media_by_url = {url_key(str(asset.get("url") or "")): asset for asset in media_assets}
    normalized_media = []
    raw_media = data.get("source_media") or []
    if not isinstance(raw_media, list):
        raw_media = []
    for raw in raw_media:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        media_id = str(item.get("media_id") or item.get("id") or "").strip()
        requested_url = normalize_url(str(item.get("url") or ""))
        asset = media_by_id.get(media_id) or media_by_url.get(url_key(requested_url))
        item["registered"] = bool(asset)
        if asset:
            item["media_id"] = str(asset.get("id") or media_id)
            item["type"] = str(asset.get("type") or item.get("type") or "image")
            item["url"] = str(asset.get("url") or requested_url)
            item["poster_url"] = str(asset.get("poster_url") or "")
            item["source_url"] = str(asset.get("source_url") or article_url)
            item["source_type"] = str(asset.get("source_type") or "source_media")
            item["caption"] = str(
                item.get("caption") or asset.get("caption") or asset.get("alt") or ""
            ).strip()
            item["language"] = str(item.get("language") or asset.get("language") or "").strip()
            item["reader_note"] = str(
                item.get("reader_note") or asset.get("reader_note") or ""
            ).strip()
            item["translation_note"] = str(
                item.get("translation_note") or asset.get("translation_note") or ""
            ).strip()
            item["embed"] = bool(asset.get("embed"))
        normalized_media.append(item)
    data["source_media"] = normalized_media
    normalized_omissions = []
    raw_omissions = data.get("media_omissions") or []
    if not isinstance(raw_omissions, list):
        raw_omissions = []
    for raw in raw_omissions:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        media_id = str(item.get("media_id") or item.get("id") or "").strip()
        requested_url = normalize_url(str(item.get("url") or ""))
        asset = media_by_id.get(media_id) or media_by_url.get(url_key(requested_url))
        item["registered"] = bool(asset)
        if asset:
            item["media_id"] = str(asset.get("id") or media_id)
            item["type"] = str(asset.get("type") or item.get("type") or "")
            item["url"] = str(asset.get("url") or requested_url)
            item["asset_role"] = str(asset.get("asset_role") or "other")
        normalized_omissions.append(item)
    data["media_omissions"] = normalized_omissions
    data["media_policy"] = {
        "available_assets": media_assets,
        "available_count": len(media_assets),
        "used_count": sum(1 for item in normalized_media if item.get("registered")),
        "unregistered_count": sum(1 for item in normalized_media if not item.get("registered")),
        "omitted_count": sum(1 for item in normalized_omissions if item.get("registered")),
        "unregistered_omission_count": sum(
            1 for item in normalized_omissions if not item.get("registered")
        ),
        "discovery": dict(getattr(article, "media_discovery", None) or {}),
    }
    listening_cards = _normalize_listening_cards(data.get("listening_cards"), media_by_id, media_by_url)
    data["listening_cards"] = listening_cards
    data["listening_policy"] = {
        "card_count": len(listening_cards),
        "track_count": sum(len(card.get("tracks") or []) for card in listening_cards),
        "unregistered_track_count": sum(
            1
            for card in listening_cards
            for track in card.get("tracks") or []
            if track.get("registered") is not True
        ),
    }
    registered_source_urls = {
        key for key in registry if key
    }
    if article_url:
        registered_source_urls.add(url_key(article_url))
    for asset in media_assets:
        for raw_url in [asset.get("source_url"), *(asset.get("upstream_source_candidates") or [])]:
            key = url_key(str(raw_url or ""))
            if key:
                registered_source_urls.add(key)
    number_stories = _normalize_number_stories(
        data.get("number_stories"), media_by_id, registered_source_urls
    )
    data["number_stories"] = number_stories
    data["evidence_gallery"] = _normalize_evidence_gallery(
        data.get("evidence_gallery"), normalized_media, number_stories, media_by_id
    )
    original_key = url_key(article_url)

    checks = []
    independent = 0
    supported = 0
    raw_checks = data.get("fact_check") or []
    if not isinstance(raw_checks, list):
        raw_checks = []
    for raw in raw_checks:
        if isinstance(raw, dict):
            item = dict(raw)
        else:
            item = {
                "claim": str(raw or "未提供主张"),
                "verdict": "无法核实",
                "note": "事实核查项结构异常，已按无法核实处理。",
            }
        verdict = str(item.get("verdict") or "无法核实")
        if verdict not in VERDICTS:
            verdict = "无法核实"

        raw_evidence = item.get("evidence") or []
        if not isinstance(raw_evidence, list):
            raw_evidence = []
        evidence = [_evidence_item(x, article_url) for x in raw_evidence]
        evidence = [x for x in evidence if x.get("url")]
        # 兼容旧 JSON：从 note 中提取链接，但不会把它们伪装成独立核验。
        if not evidence:
            for url in urls_from_text(str(item.get("note") or "")):
                evidence.append(_evidence_item(url, article_url))
        if not evidence and article_url:
            evidence.append({
                "url": article_url,
                "source_type": "original",
                "publisher": "原文发布方",
                "quote": "",
                "support": "该主张来自原文；未提供独立来源或逐字证据。",
            })

        for e in evidence:
            key = url_key(str(e.get("url") or ""))
            source_meta = registry.get(key, {})
            is_original = bool(original_key and key == original_key)
            registered = is_original or key in registry
            fetched = is_original or bool(source_meta.get("fetched"))
            e["registered"] = registered
            e["fetched"] = fetched
            if source_meta.get("retrieved_at"):
                e["retrieved_at"] = source_meta["retrieved_at"]
            if source_meta.get("content_hash"):
                e["content_hash"] = source_meta["content_hash"]
            if is_original:
                e["source_type"] = "original"
            else:
                if fetched:
                    e["source_type"] = source_meta.get("source_type") or "independent"
                else:
                    e["source_type"] = "unverified_link"

        has_independent = any(
            x.get("fetched") and x.get("source_type") == "independent"
            for x in evidence
        )
        if has_independent:
            independent += 1
        if evidence:
            supported += 1
        if verdict == "确认" and not has_independent:
            verdict = "原文声称"
        if verdict == "交叉验证" and not has_independent:
            verdict = "原文声称"

        item["verdict"] = verdict
        item["evidence"] = evidence
        item["evidence_status"] = "cross_checked" if has_independent else ("source_only" if evidence else "missing")
        checks.append(item)

    data["fact_check"] = checks
    total = len(checks)
    data["evidence_summary"] = {
        "claims": total,
        "claims_with_evidence": supported,
        "claims_with_independent_source": independent,
        "coverage": round(supported / total, 3) if total else 0,
        "independent_coverage": round(independent / total, 3) if total else 0,
    }

    old = str(data.get("source_notes") or "").replace(TRUST_WARNING, "").strip()
    if total and independent == 0:
        data["source_notes"] = f"{old} {TRUST_WARNING}".strip()
    elif old or "source_notes" in data:
        data["source_notes"] = old
    return data
