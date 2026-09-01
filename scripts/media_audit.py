"""Deterministic reconciliation between registered, selected and rendered media."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit


def _url_key(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


class _RenderedMediaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.current_source_media = ""
        self.source_media: dict[str, set[str]] = {}
        self.audio_urls: set[str] = set()
        self.rendered_urls: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_d = dict(attrs)
        classes = set(str(attrs_d.get("class") or "").split())
        if tag == "figure" and "source-media" in classes:
            self.current_source_media = str(attrs_d.get("data-media-id") or "")
            self.source_media.setdefault(self.current_source_media, set())
            return
        if tag in {"img", "video", "audio", "iframe", "source"}:
            url = str(attrs_d.get("src") or "").strip()
            if url:
                self.rendered_urls.add(_url_key(url))
            if tag == "audio" and url:
                self.audio_urls.add(_url_key(url))
            if self.current_source_media and url:
                self.source_media[self.current_source_media].add(_url_key(url))

    def handle_endtag(self, tag: str) -> None:
        if tag == "figure" and self.current_source_media:
            self.current_source_media = ""


def audit_rendered_media(article, distilled: dict, html_text: str) -> dict:
    parser = _RenderedMediaParser()
    parser.feed(html_text or "")
    registry = {
        str(item.get("id") or ""): item
        for item in (getattr(article, "media_assets", []) or [])
        if isinstance(item, dict) and item.get("id")
    }
    used_ids = {
        str(item.get("media_id") or "")
        for item in (distilled.get("source_media") or [])
        if isinstance(item, dict) and item.get("registered") is True and item.get("media_id")
    }
    omitted_ids = {
        str(item.get("media_id") or "")
        for item in (distilled.get("media_omissions") or [])
        if isinstance(item, dict) and item.get("registered") is True and item.get("media_id")
    }
    important_ids = {
        media_id
        for media_id, item in registry.items()
        if str(item.get("type") or "").lower() in {"image", "video", "audio"}
        and str(item.get("asset_role") or "").lower() in {"chart", "demo", "hero", "screenshot"}
    }
    accounted_ids = used_ids | omitted_ids
    unaccounted_ids = sorted(set(registry) - accounted_ids)
    unaccounted_important_ids = sorted(important_ids - accounted_ids)
    missing_nodes = []
    mismatched_urls = []
    for item in distilled.get("source_media") or []:
        if not isinstance(item, dict) or item.get("registered") is not True:
            continue
        media_id = str(item.get("media_id") or "")
        expected_url = _url_key(str(item.get("url") or registry.get(media_id, {}).get("url") or ""))
        rendered_urls = parser.source_media.get(media_id)
        if not rendered_urls:
            missing_nodes.append(media_id)
        elif expected_url and expected_url not in rendered_urls:
            mismatched_urls.append(media_id)

    missing_audio = []
    for card in distilled.get("listening_cards") or []:
        if not isinstance(card, dict):
            continue
        for track in card.get("tracks") or []:
            if isinstance(track, dict) and track.get("registered") is True:
                url = _url_key(str(track.get("url") or ""))
                if url and url not in parser.audio_urls:
                    missing_audio.append(str(track.get("media_id") or url))

    errors = []
    if missing_nodes:
        errors.append(f"已采用媒体没有渲染到最终 HTML：{missing_nodes}")
    if mismatched_urls:
        errors.append(f"最终 HTML 的媒体 URL 与注册表不一致：{mismatched_urls}")
    if missing_audio:
        errors.append(f"已采用音频没有渲染到最终 HTML：{missing_audio}")
    if unaccounted_important_ids:
        errors.append(
            "原页的重要图表、截图或演示媒体既未渲染，也没有省略理由："
            f"{unaccounted_important_ids}"
        )
    return {
        "ok": not errors,
        "errors": errors,
        "inventory_count": len(registry),
        "used_count": len(used_ids),
        "omitted_count": len(omitted_ids),
        "unaccounted_count": len(unaccounted_ids),
        "unaccounted_media_ids": unaccounted_ids,
        "unaccounted_important_media_ids": unaccounted_important_ids,
        "rendered_source_media_count": len(parser.source_media),
        "rendered_media_url_count": len(parser.rendered_urls),
        "rendered_audio_count": len(parser.audio_urls),
    }


def assert_rendered_media(article, distilled: dict, html_text: str) -> dict:
    result = audit_rendered_media(article, distilled, html_text)
    if not result["ok"]:
        raise ValueError("；".join(result["errors"]))
    return result
