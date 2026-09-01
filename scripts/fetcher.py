"""原文抓取模块：用 trafilatura 从 URL 提取正文与元数据。"""

from __future__ import annotations

import json
import hashlib
import io
import re
from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

import trafilatura
from pypdf import PdfReader

from chart_ocr import enrich_chart_assets, source_label_from_text


_LAZY_URL_ATTRS = (
    "src", "data-src", "data-lazy-src", "data-original", "data-url",
    "data-video-src", "data-audio-src", "data-mp4-src", "data-mp4-url",
)
_EMBED_VIDEO_HOSTS = (
    "youtube.com", "youtube-nocookie.com", "youtu.be", "vimeo.com", "wistia.",
    "brightcove.", "bilibili.com", "cloudflarestream.com", "player.",
)


def _srcset_url(value: str | None) -> str:
    candidates = [item.strip().split()[0] for item in str(value or "").split(",") if item.strip()]
    return candidates[-1] if candidates else ""


def _attribute_url(attrs: dict[str, str | None], *extra: str) -> str:
    for name in (*extra, *_LAZY_URL_ATTRS):
        value = str(attrs.get(name) or "").strip()
        if value:
            return value
    return _srcset_url(attrs.get("srcset") or attrs.get("data-srcset"))


def _style_background_urls(style: str | None) -> list[str]:
    return [
        match.strip()
        for match in re.findall(r"url\([\"']?([^\"')]+)[\"']?\)", str(style or ""), flags=re.I)
        if match.strip()
    ]


def _is_video_embed(url: str) -> bool:
    host = (urlsplit(url).hostname or "").casefold()
    return any(token in host for token in _EMBED_VIDEO_HOSTS)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict] = []
        self.media_assets: list[dict] = []
        self._active_link: dict | None = None
        self._active_video: dict | None = None
        self._active_audio: dict | None = None
        self._active_heading: dict | None = None
        self._current_heading = ""
        self._active_figure: dict | None = None
        self._in_figcaption = False
        self._active_row: dict | None = None
        self._active_cell: list[str] | None = None
        self._document_order = 0

    def _record_media(self, asset: dict) -> None:
        self.media_assets.append(asset)
        index = len(self.media_assets) - 1
        if self._active_figure is not None:
            self._active_figure["asset_indexes"].append(index)
        if self._active_row is not None:
            self._active_row["asset_indexes"].append(index)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_d = dict(attrs)
        for background_url in _style_background_urls(attrs_d.get("style")):
            self._document_order += 1
            self._record_media({
                "type": "image",
                "url": background_url,
                "alt": (attrs_d.get("aria-label") or attrs_d.get("title") or "").strip(),
                "section_title": self._current_heading,
                "document_order": self._document_order,
                "css_background": True,
            })
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._active_heading = {"text": []}
            return
        if tag == "figure":
            self._active_figure = {"caption": [], "links": [], "asset_indexes": []}
            return
        if tag == "tr":
            self._active_row = {"cells": [], "asset_indexes": []}
            self._active_cell = None
            return
        if tag in {"td", "th"} and self._active_row is not None:
            self._active_cell = []
            return
        if tag == "figcaption" and self._active_figure is not None:
            self._in_figcaption = True
            return
        if tag == "a":
            href = attrs_d.get("href")
            if href and href.startswith(("http://", "https://", "/")):
                self._active_link = {"href": href, "text": []}
                if self._active_figure is not None:
                    self._active_figure["links"].append(href)
            return
        if tag == "img":
            src = _attribute_url(attrs_d)
            if src:
                self._document_order += 1
                self._record_media({
                    "type": "image",
                    "url": src,
                    "alt": (attrs_d.get("alt") or "").strip(),
                    "section_title": self._current_heading,
                    "document_order": self._document_order,
                })
            return
        if tag == "video":
            src = _attribute_url(attrs_d)
            poster = _attribute_url(attrs_d, "poster", "data-poster", "data-poster-url") if (
                attrs_d.get("poster") or attrs_d.get("data-poster") or attrs_d.get("data-poster-url")
            ) else ""
            self._document_order += 1
            self._active_video = {
                "type": "video",
                "url": src or "",
                "poster_url": poster,
                "alt": (attrs_d.get("aria-label") or attrs_d.get("title") or "").strip(),
                "section_title": self._current_heading,
                "document_order": self._document_order,
                "emitted": False,
            }
            if src:
                self._record_media({key: value for key, value in self._active_video.items() if key != "emitted"})
                self._active_video["emitted"] = True
            return
        if tag == "audio":
            src = _attribute_url(attrs_d)
            self._document_order += 1
            self._active_audio = {
                "type": "audio",
                "url": src or "",
                "poster_url": "",
                "alt": (attrs_d.get("aria-label") or attrs_d.get("title") or "").strip(),
                "section_title": self._current_heading,
                "document_order": self._document_order,
                "emitted": False,
            }
            if src:
                self._record_media({key: value for key, value in self._active_audio.items() if key != "emitted"})
                self._active_audio["emitted"] = True
            return
        if tag == "source":
            src = _attribute_url(attrs_d)
            mime = (attrs_d.get("type") or "").lower()
            path = (src or "").lower().split("?", 1)[0]
            if src and (mime.startswith("audio/") or path.endswith((".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"))):
                if self._active_audio is not None and not self._active_audio.get("emitted"):
                    self._active_audio["url"] = src
                    self._record_media({
                        key: value for key, value in self._active_audio.items() if key != "emitted"
                    })
                    self._active_audio["emitted"] = True
                elif self._active_audio is None:
                    self._record_media({"type": "audio", "url": src, "poster_url": "", "alt": ""})
            elif src and (mime.startswith("video/") or path.endswith((".mp4", ".webm", ".mov"))):
                if self._active_video is not None and not self._active_video.get("emitted"):
                    self._active_video["url"] = src
                    self._record_media({
                        key: value for key, value in self._active_video.items() if key != "emitted"
                    })
                    self._active_video["emitted"] = True
                elif self._active_video is None:
                    self._record_media({"type": "video", "url": src, "poster_url": "", "alt": ""})
            return

        if tag == "iframe":
            src = _attribute_url(attrs_d)
            if src and _is_video_embed(src):
                self._document_order += 1
                self._record_media({
                    "type": "video",
                    "url": src,
                    "poster_url": "",
                    "alt": (attrs_d.get("aria-label") or attrs_d.get("title") or "").strip(),
                    "section_title": self._current_heading,
                    "document_order": self._document_order,
                    "embed": True,
                    "asset_role": "demo",
                })
            return

        # Publisher design systems sometimes keep video URLs on custom
        # elements instead of native <video> nodes in the source HTML.
        video_attr_names = (
            "or-mp4-video-url",
            "video-url",
            "data-video-url",
            "data-video-src",
            "data-mp4-url",
            "data-mp4-src",
        )
        custom_video_url = next(
            (attrs_d.get(name) for name in video_attr_names if attrs_d.get(name)),
            None,
        )
        if custom_video_url:
            path = str(custom_video_url).lower().split("?", 1)[0]
            if path.endswith((".mp4", ".webm", ".mov")):
                self._document_order += 1
                alt = (
                    attrs_d.get("alt-text")
                    or attrs_d.get("aria-label")
                    or attrs_d.get("video-title")
                    or attrs_d.get("title")
                    or ""
                ).strip()
                poster = (
                    attrs_d.get("poster")
                    or attrs_d.get("poster-url")
                    or attrs_d.get("data-poster")
                    or attrs_d.get("data-poster-url")
                    or ""
                )
                section_title = (
                    attrs_d.get("section-header")
                    or self._current_heading
                    or ""
                ).strip()
                self._record_media({
                    "type": "video",
                    "url": custom_video_url,
                    "poster_url": poster,
                    "alt": alt,
                    "caption": alt,
                    "section_title": section_title,
                    "document_order": self._document_order,
                })

    def handle_data(self, data: str) -> None:
        if self._active_heading is not None and data.strip():
            self._active_heading["text"].append(data.strip())
        if self._active_figure is not None and self._in_figcaption and data.strip():
            self._active_figure["caption"].append(data.strip())
        if self._active_link is not None and data.strip():
            self._active_link["text"].append(data.strip())
        if self._active_cell is not None and data.strip():
            self._active_cell.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self._active_heading is not None:
            self._current_heading = " ".join(self._active_heading["text"]).strip()
            self._active_heading = None
            return
        if tag == "figcaption":
            self._in_figcaption = False
            return
        if tag in {"td", "th"} and self._active_row is not None and self._active_cell is not None:
            self._active_row["cells"].append(" ".join(self._active_cell).strip())
            self._active_cell = None
            return
        if tag == "tr" and self._active_row is not None:
            cells = self._active_row["cells"]
            for index in self._active_row["asset_indexes"]:
                if index >= len(self.media_assets) or self.media_assets[index].get("type") != "audio":
                    continue
                if cells:
                    self.media_assets[index]["prompt"] = cells[0][:4000]
                if len(cells) > 1:
                    self.media_assets[index]["lyrics"] = cells[1][:4000]
                elif cells:
                    labeled = re.match(
                        r"\s*(?:prompt|description)\s*[:：]\s*(.*?)\s*(?:lyrics?|歌词)\s*[:：]\s*(.+)\s*$",
                        cells[0],
                        flags=re.IGNORECASE | re.DOTALL,
                    )
                    if labeled:
                        self.media_assets[index]["prompt"] = labeled.group(1).strip()[:4000]
                        self.media_assets[index]["lyrics"] = labeled.group(2).strip()[:4000]
                context = "\n".join(cell for cell in cells[:2] if cell)
                if context:
                    self.media_assets[index]["context_text"] = context[:8000]
            self._active_row = None
            self._active_cell = None
            return
        if tag == "figure" and self._active_figure is not None:
            caption = " ".join(self._active_figure["caption"]).strip()
            source_label = source_label_from_text(caption)
            figure_links = list(dict.fromkeys(self._active_figure["links"]))
            for index in self._active_figure["asset_indexes"]:
                if index >= len(self.media_assets):
                    continue
                self.media_assets[index]["caption"] = caption
                self.media_assets[index]["upstream_source_candidates"] = figure_links
                if source_label:
                    self.media_assets[index]["source_label"] = source_label
            self._active_figure = None
            return
        if tag == "video" and self._active_video is not None:
            if not self._active_video.get("emitted") and self._active_video.get("poster_url"):
                self._record_media({
                    "type": "video_poster",
                    "url": self._active_video["poster_url"],
                    "poster_url": self._active_video["poster_url"],
                    "alt": self._active_video.get("alt") or "",
                })
            self._active_video = None
            return
        if tag == "audio" and self._active_audio is not None:
            self._active_audio = None
            return
        if tag == "a" and self._active_link is not None:
            self.links.append({
                "href": self._active_link["href"],
                "text": " ".join(self._active_link["text"]).strip(),
            })
            self._active_link = None


def _asset_role(asset: dict) -> str:
    """Best-effort media role used for discovery and gallery grouping."""
    haystack = " ".join(
        str(asset.get(key) or "")
        for key in ("url", "alt", "caption", "section_title")
    ).casefold()
    if any(token in haystack for token in (
        "chart", "graph", "plot", "benchmark", "metric", "results", "performance",
        "图表", "曲线", "柱状", "折线", "基准", "数据", "结果",
    )):
        return "chart"
    if any(token in haystack for token in (
        "screenshot", "screen shot", "interface", "dashboard", "ui ", "界面", "截图", "控制台",
    )):
        return "screenshot"
    if str(asset.get("type") or "").lower() in {"audio", "video"}:
        return "demo"
    if any(token in haystack for token in ("demo", "workflow", "演示", "流程")):
        return "demo"
    if any(token in haystack for token in ("photo", "portrait", "摄影", "照片", "合影")):
        return "photo"
    return "other"


def _content_media(asset: dict, page_url: str) -> dict | None:
    raw_url = str(asset.get("url") or "").strip()
    if not raw_url or raw_url.startswith(("data:", "blob:")):
        return None
    url = urljoin(page_url, raw_url)
    parsed = urlsplit(url)
    path = (parsed.path or "").lower()
    host_path = f"{parsed.hostname or ''}{path}".lower()
    if any(token in host_path for token in (
        "favicon", "logo", "avatar", "badge", "icon", "sprite", "flag-", "/funders/",
    )):
        return None
    if "x-amz-signature=" in (parsed.query or "").lower():
        return None
    if (parsed.hostname or "").lower() == "private-user-images.githubusercontent.com":
        return None
    alt = str(asset.get("alt") or "").strip()
    if any(token in alt.casefold() for token in (
        "profile picture", "profile photo", "avatar", "blue dot", "share icon", "close icon",
    )):
        return None
    if (parsed.hostname or "").lower() == "camo.githubusercontent.com" and alt.casefold() in {
        "website", "model", "demo", "paper", "discord"
    }:
        return None
    media_type = str(asset.get("type") or "image")
    if media_type == "video_poster":
        media_type = "image"
    if media_type == "image" and path.endswith(".svg"):
        return None
    poster = str(asset.get("poster_url") or "").strip()
    return {
        "type": media_type,
        "url": url,
        "poster_url": urljoin(page_url, poster) if poster else "",
        "alt": alt,
        "source_url": page_url,
        "source_type": "original_media",
        "extracted": True,
        "caption": str(asset.get("caption") or "").strip(),
        "prompt": str(asset.get("prompt") or "").strip(),
        "lyrics": str(asset.get("lyrics") or "").strip(),
        "context_text": str(asset.get("context_text") or "").strip(),
        "section_title": str(asset.get("section_title") or "").strip(),
        "document_order": int(asset.get("document_order") or 0),
        "source_label": str(asset.get("source_label") or "").strip(),
        "upstream_source_candidates": [
            urljoin(page_url, str(candidate))
            for candidate in (asset.get("upstream_source_candidates") or [])
            if str(candidate).strip()
        ],
        "asset_role": str(asset.get("asset_role") or _asset_role(asset)).strip(),
        "language": str(asset.get("language") or "").strip(),
        "reader_note": str(asset.get("reader_note") or "").strip(),
        "translation_note": str(asset.get("translation_note") or "").strip(),
        "embed": bool(asset.get("embed")),
        "css_background": bool(asset.get("css_background")),
    }


def _page_asset_collections(payload: dict) -> list[tuple[str, list]]:
    """Return supported browser/search export collections without guessing nested prose."""
    aliases = {
        "images": "image",
        "videos": "video",
        "audio": "audio",
        "media": "",
        "media_assets": "",
    }
    result = []
    for key, default_type in aliases.items():
        values = payload.get(key)
        if isinstance(values, list):
            result.append((default_type, values))
    return result


def merge_page_assets(article: "Article", payload: dict) -> dict:
    """Merge a structured browser/search export into the source and media registries."""
    if not isinstance(payload, dict):
        raise ValueError("page-assets JSON 顶层必须是对象")

    article.source_links = list(article.source_links or [])
    article.media_assets = list(article.media_assets or [])
    source_keys = {
        urlsplit(str(item.get("url") or "")).geturl()
        for item in article.source_links
        if isinstance(item, dict) and item.get("url")
    }
    added_links = 0
    for key in ("links", "sources", "research_sources", "related_articles"):
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        for raw in values:
            if isinstance(raw, str):
                raw = {"url": raw}
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or raw.get("href") or "").strip()
            if not url.startswith(("http://", "https://")) or url == article.url:
                continue
            lowered = url.casefold()
            if any(token in lowered for token in (
                "facebook.com/sharer", "twitter.com/intent", "linkedin.com/sharearticle",
                "/login", "/signup", "/privacy", "/terms",
            )):
                continue
            normalized = urlsplit(url).geturl()
            if normalized in source_keys:
                continue
            source_keys.add(normalized)
            article.source_links.append({
                "url": url,
                "title": str(raw.get("title") or raw.get("text") or "").strip(),
                "source_type": str(raw.get("source_type") or "discovered").strip(),
                "fetched": bool(raw.get("fetched", False)),
                "origin": str(raw.get("origin") or "page_assets").strip(),
            })
            added_links += 1

    media_keys = {
        str(item.get("url") or "").strip()
        for item in article.media_assets
        if isinstance(item, dict) and item.get("url")
    }
    media_ids = {
        str(item.get("id") or "").strip()
        for item in article.media_assets
        if isinstance(item, dict) and item.get("id")
    }
    added_media = 0
    order = max(
        (int(item.get("document_order") or 0) for item in article.media_assets if isinstance(item, dict)),
        default=0,
    )
    for default_type, values in _page_asset_collections(payload):
        for raw in values:
            if not isinstance(raw, dict):
                continue
            media_type = str(raw.get("type") or default_type or "image").strip().lower()
            raw_url = str(raw.get("url") or raw.get("src") or "").strip()
            if media_type not in {"image", "video", "audio"} or not raw_url:
                continue
            source_page = str(raw.get("source_page") or raw.get("source_url") or article.url).strip()
            order += 1
            candidate = {
                "type": media_type,
                "url": raw_url,
                "poster_url": str(raw.get("poster_url") or raw.get("poster") or "").strip(),
                "alt": str(raw.get("alt") or raw.get("title") or "").strip(),
                "caption": str(raw.get("caption") or "").strip(),
                "section_title": str(raw.get("section_title") or raw.get("context") or "").strip(),
                "document_order": int(raw.get("document_order") or order),
                "source_label": str(raw.get("source_label") or "").strip(),
                "upstream_source_candidates": list(
                    raw.get("upstream_source_candidates") or raw.get("upstream_sources") or []
                ),
                "asset_role": str(raw.get("asset_role") or raw.get("role") or "").strip(),
                "language": str(raw.get("language") or "").strip(),
                "reader_note": str(raw.get("reader_note") or "").strip(),
                "translation_note": str(raw.get("translation_note") or "").strip(),
                "embed": bool(raw.get("embed")),
                "css_background": bool(raw.get("css_background")),
            }
            asset = _content_media(candidate, source_page or article.url)
            if not asset or asset["url"] in media_keys:
                continue
            media_keys.add(asset["url"])
            if candidate["asset_role"]:
                asset["asset_role"] = candidate["asset_role"]
            asset["source_url"] = source_page or article.url
            asset["source_type"] = str(raw.get("source_type") or (
                "original_media" if source_page == article.url else "supplemental_media"
            )).strip()
            requested_id = str(raw.get("id") or "").strip()
            if requested_id and requested_id not in media_ids:
                asset["id"] = requested_id
            else:
                next_index = len(article.media_assets) + 1
                while f"media-{next_index}" in media_ids:
                    next_index += 1
                asset["id"] = f"media-{next_index}"
            media_ids.add(asset["id"])
            asset["origin"] = str(raw.get("origin") or "page_assets").strip()
            article.media_assets.append(asset)
            added_media += 1
            if len(article.media_assets) >= 30:
                break
        if len(article.media_assets) >= 30:
            break
    return {"links": added_links, "media": added_media}


def merge_page_assets_file(article: "Article", path: str) -> dict:
    """Read and merge a browser/search export created before the LLM stages."""
    asset_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(asset_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"无法读取 page-assets 文件：{asset_path}（{exc}）") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"page-assets 不是合法 JSON：{asset_path}（{exc}）") from exc
    result = merge_page_assets(article, payload)
    discovery = payload.get("media_discovery")
    if isinstance(discovery, dict):
        result["discovery"] = discovery
    return result


@dataclass
class Article:
    url: str
    title: str = ""
    author: str = ""
    date: str = ""
    text: str = ""
    text_chars: int = 0
    error: Optional[str] = None
    retrieved_at: str = ""
    content_hash: str = ""
    source_links: list[dict] | None = None
    source_type: str = "original"
    media_assets: list[dict] | None = None
    repository_files: list[dict] | None = None
    repository_read: dict | None = None
    media_discovery: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _fetch_pdf_article(url: str, source_type: str) -> Article:
    """Download and extract a remote research PDF into the normal Article contract."""
    art = Article(url=url, source_links=[], source_type=source_type, media_assets=[], media_discovery={})
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 article-distiller/9.16"})
        with urlopen(request, timeout=30) as response:  # noqa: S310 - explicit user/source URL
            payload = response.read(30 * 1024 * 1024 + 1)
        if len(payload) > 30 * 1024 * 1024:
            raise ValueError("PDF 超过 30 MB 安全上限")
        reader = PdfReader(io.BytesIO(payload))
        chunks = []
        for page in reader.pages[:120]:
            text = (page.extract_text() or "").strip()
            if text:
                chunks.append(text)
            if sum(len(item) for item in chunks) >= 120000:
                break
        art.text = "\n\n".join(chunks).strip()[:120000]
        metadata = reader.metadata or {}
        art.title = str(metadata.get("/Title") or "").strip()
        art.author = str(metadata.get("/Author") or "").strip()
    except Exception as exc:  # noqa: BLE001
        art.error = f"远程 PDF 读取失败：{exc}"
        return art
    art.text_chars = len(art.text)
    art.retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    art.content_hash = hashlib.sha256(art.text.encode("utf-8")).hexdigest()
    if not art.text:
        art.error = "远程 PDF 没有可提取文字，可能是扫描件；请先 OCR。"
    return art


def fetch_article(url: str, source_type: str = "original", chart_ocr: bool = False) -> Article:
    """抓取一个 URL，返回结构化文章。失败时 Article.error 非空。"""
    if (urlsplit(url).path or "").lower().endswith(".pdf"):
        return _fetch_pdf_article(url, source_type)
    art = Article(url=url, source_links=[], source_type=source_type, media_assets=[], media_discovery={})
    try:
        downloaded = trafilatura.fetch_url(url)
    except Exception as e:  # noqa: BLE001
        art.error = f"抓取失败（网络层）：{e}"
        return art

    if not downloaded:
        art.error = (
            "抓取失败：拿不到网页内容（可能是反爬 / JS 渲染页 / 需要登录）。"
            "可用 --from-text 模式手动贴正文。"
        )
        return art

    parser = _LinkParser()
    try:
        parser.feed(downloaded)
    except Exception:
        parser.links = []
        parser.media_assets = []
    seen: set[str] = set()
    for link in parser.links:
        href = str(link.get("href") or "")
        absolute = urljoin(url, href).strip()
        if absolute and absolute not in seen and absolute != url:
            seen.add(absolute)
            art.source_links.append({
                "url": absolute,
                "title": str(link.get("text") or "").strip(),
                "source_type": "discovered",
                "fetched": False,
            })

    seen_media: set[str] = set()
    for raw_asset in parser.media_assets:
        asset = _content_media(raw_asset, url)
        if not asset or asset["url"] in seen_media:
            continue
        seen_media.add(asset["url"])
        asset["id"] = f"media-{len(art.media_assets) + 1}"
        art.media_assets.append(asset)
        if len(art.media_assets) >= 30:
            break
    art.media_assets = enrich_chart_assets(art.media_assets, enabled=chart_ocr)

    # 正文提取（倾向多召回）
    text = (
        trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
        or ""
    )

    # 元数据
    meta_raw = (
        trafilatura.extract(downloaded, output_format="json", with_metadata=True)
        or "{}"
    )
    try:
        meta = json.loads(meta_raw)
    except json.JSONDecodeError:
        meta = {}

    art.text = text.strip()
    art.text_chars = len(art.text)
    art.retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    art.content_hash = hashlib.sha256(art.text.encode("utf-8")).hexdigest()
    art.title = (meta.get("title") or "").strip()
    art.author = (meta.get("author") or "").strip()
    art.date = (meta.get("date") or "").strip()

    if not art.text:
        art.error = (
            "正文提取为空：页面可能是 JS 渲染或非标准文章页。"
            "可用 --from-text 模式手动贴正文。"
        )
    return art


def article_from_text(text: str, url: str = "", title: str = "", author: str = "") -> Article:
    """从手动粘贴的正文构造 Article（应对抓不到的页面）。"""
    clean = text.strip()
    return Article(
        url=url,
        title=title,
        author=author,
        text=clean,
        text_chars=len(clean),
        retrieved_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        content_hash=hashlib.sha256(clean.encode("utf-8")).hexdigest(),
        source_links=[],
        source_type="original",
        media_assets=[],
        repository_files=[],
    )
