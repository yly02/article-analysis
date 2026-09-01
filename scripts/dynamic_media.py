"""Discover media from a JavaScript-rendered article page with Playwright."""

from __future__ import annotations

import os
import subprocess
import sys
from urllib.parse import urlsplit


SYSTEM_BROWSER_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)


def _launch_browser(playwright):
    errors = []
    for path in SYSTEM_BROWSER_PATHS:
        if not os.path.isfile(path):
            continue
        try:
            return playwright.chromium.launch(executable_path=path, headless=True), errors
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: {exc}")
    try:
        return playwright.chromium.launch(headless=True), errors
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
    return None, errors


def _install_chromium() -> tuple[bool, str]:
    command = [sys.executable, "-m", "playwright", "install", "chromium"]
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    detail = "\n".join((result.stdout or "").splitlines()[-12:])
    return result.returncode == 0, detail


def discover_dynamic_page_assets(
    url: str,
    *,
    timeout_ms: int = 25000,
    auto_install_browser: bool = True,
) -> dict:
    """Return page-assets compatible media collected after JavaScript rendering."""
    if urlsplit(url).scheme not in {"http", "https"}:
        return {"status": "skipped", "reason": "仅远程 HTTP(S) 页面需要动态媒体发现", "media": []}
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        return {"status": "failed", "reason": "缺少 Python 模块 playwright", "media": []}

    browser = None
    launch_errors = []
    try:
        with sync_playwright() as playwright:
            browser, launch_errors = _launch_browser(playwright)
            if browser is None and auto_install_browser:
                installed, detail = _install_chromium()
                if not installed:
                    return {
                        "status": "failed",
                        "reason": "Playwright 浏览器自动安装失败：" + detail,
                        "media": [],
                    }
                browser, launch_errors = _launch_browser(playwright)
            if browser is None:
                return {
                    "status": "failed",
                    "reason": "无法启动动态页面浏览器：" + " | ".join(launch_errors[-3:]),
                    "media": [],
                }
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            network_assets: dict[str, dict] = {}

            def capture_response(item) -> None:
                try:
                    asset_url = str(item.url or "")
                    resource_type = str(item.request.resource_type or "")
                    path = asset_url.split("?", 1)[0].lower()
                    media_type = ""
                    if resource_type == "media" or path.endswith((".mp4", ".webm", ".mov", ".m3u8")):
                        media_type = "video"
                    elif path.endswith((".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac")):
                        media_type = "audio"
                    elif resource_type == "image":
                        media_type = "image"
                    if media_type and asset_url and not asset_url.startswith(("data:", "blob:")):
                        network_assets[asset_url] = {
                            "type": media_type,
                            "url": asset_url,
                            "source_page": url,
                            "origin": "dynamic_network",
                            **({"asset_role": "demo"} if media_type in {"video", "audio"} else {}),
                        }
                except Exception:  # noqa: BLE001 - response may disappear during navigation
                    return

            page.on("response", capture_response)
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if response is not None and response.status >= 400:
                return {"status": "failed", "reason": f"动态页面返回 HTTP {response.status}", "media": []}
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 6000))
            except Exception:  # noqa: BLE001 - many article pages keep analytics connections open
                pass
            for selector in (
                'button:has-text("Accept")',
                'button:has-text("同意")',
                'button:has-text("接受")',
                '[aria-label*="accept" i]',
                '[aria-label*="同意"]',
            ):
                try:
                    candidate = page.locator(selector).first
                    if candidate.is_visible(timeout=250):
                        candidate.click(timeout=750)
                        break
                except Exception:  # noqa: BLE001 - consent UI is optional
                    continue
            page.evaluate(
                r"""
                () => {
                  document.querySelectorAll('details').forEach(node => { node.open = true; });
                  document.querySelectorAll('iframe[data-src], iframe[data-lazy-src]').forEach(node => {
                    if (!node.src) node.src = node.dataset.src || node.dataset.lazySrc || '';
                  });
                  document.querySelectorAll('video, audio').forEach(node => {
                    node.preload = 'auto';
                    try { node.load(); } catch (_) {}
                  });
                }
                """
            )
            page.wait_for_timeout(1200)
            for fraction in (0.25, 0.5, 0.75, 1):
                page.evaluate("fraction => window.scrollTo(0, document.body.scrollHeight * fraction)", fraction)
                page.wait_for_timeout(500)
            page.wait_for_timeout(1000)
            media = page.evaluate(
                r"""
                () => {
                  const result = [];
                  const add = (type, url, node, extra = {}) => {
                    if (!url || /^(data:|blob:)/i.test(url)) return;
                    const heading = node?.closest?.('section,article,main,figure')?.querySelector?.('h1,h2,h3,h4,h5,h6');
                    result.push({
                      type,
                      url,
                      alt: node?.getAttribute?.('alt') || node?.getAttribute?.('aria-label') || node?.getAttribute?.('title') || '',
                      caption: node?.closest?.('figure')?.querySelector?.('figcaption')?.innerText?.trim() || '',
                      section_title: heading?.innerText?.trim() || '',
                      poster_url: node?.poster || node?.getAttribute?.('poster') || '',
                      source_page: location.href,
                      origin: 'dynamic_browser',
                      ...extra,
                    });
                  };
                  const roots = [document];
                  const seenRoots = new Set(roots);
                  for (let index = 0; index < roots.length; index += 1) {
                    roots[index].querySelectorAll('*').forEach(node => {
                      if (node.shadowRoot && !seenRoots.has(node.shadowRoot)) {
                        seenRoots.add(node.shadowRoot);
                        roots.push(node.shadowRoot);
                      }
                    });
                  }
                  const nodes = selector => roots.flatMap(root => [...root.querySelectorAll(selector)]);
                  nodes('img').forEach(node => add(
                    'image', node.currentSrc || node.src || node.dataset.src || node.dataset.lazySrc || node.dataset.original, node
                  ));
                  nodes('video').forEach(node => {
                    const sources = [node.currentSrc, node.src, ...[...node.querySelectorAll('source')].map(x => x.src)].filter(Boolean);
                    [...new Set(sources)].forEach(src => add('video', src, node));
                  });
                  nodes('audio').forEach(node => {
                    const sources = [node.currentSrc, node.src, ...[...node.querySelectorAll('source')].map(x => x.src)].filter(Boolean);
                    [...new Set(sources)].forEach(src => add('audio', src, node));
                  });
                  nodes('iframe').forEach(node => {
                    const src = node.src || node.dataset.src || node.dataset.lazySrc || '';
                    if (/(youtube(?:-nocookie)?\.com|youtu\.be|vimeo\.com|wistia\.|brightcove\.|bilibili\.com|cloudflarestream\.com|player\.)/i.test(src)) {
                      add('video', src, node, {embed: true, asset_role: 'demo'});
                    }
                  });
                  nodes('*').slice(0, 12000).forEach(node => {
                    const bg = getComputedStyle(node).backgroundImage || '';
                    for (const match of bg.matchAll(/url\(["']?([^"')]+)["']?\)/g)) add('image', match[1], node, {css_background: true});
                  });
                  for (const entry of performance.getEntriesByType('resource')) {
                    const path = (entry.name || '').split('?')[0].toLowerCase();
                    if (/\.(mp4|webm|mov|m3u8)$/.test(path)) add('video', entry.name, null, {asset_role: 'demo'});
                    else if (/\.(mp3|wav|m4a|ogg|aac|flac)$/.test(path)) add('audio', entry.name, null);
                  }
                  return result;
                }
                """
            )
            combined = [*(media or []), *network_assets.values()]
            return {
                "status": "completed",
                "reason": "",
                "media": combined,
                "dom_count": len(media or []),
                "network_count": len(network_assets),
            }
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "reason": f"动态媒体发现失败：{exc}", "media": []}
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
