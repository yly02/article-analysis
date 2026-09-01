#!/usr/bin/env python3
"""Browser-level desktop/mobile regression for the finished article renderer."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from fetcher import Article  # noqa: E402
from renderer import render_html  # noqa: E402


ARTICLE = Article(url="https://example.com/article", title="响应式验收", author="测试", text="正文", text_chars=2)
PAYLOAD = {
    "distilled_title": "一篇文章如何在手机和桌面上都保持清楚",
    "dek": "用真实浏览器检查正文、目录、对比组和长词是否越界。",
    "quick_scan": ["标题可读", "正文不横向溢出", "交互组件保持稳定"],
    "sections": [
        {"id": "context", "title": "先把问题讲清楚", "content": "这是面向普通读者的开场。" * 8},
        {"id": "compare", "title": "再比较两种做法", "content": "对比关系应该扫一眼就能理解。" * 8},
        {"id": "decision", "title": "最后给出判断", "content": "结论需要落在具体选择上。" * 8},
    ],
    "visuals": [{
        "type": "compare_table",
        "title": "两种做法的差别",
        "after_section_id": "compare",
        "data": {
            "layout": "paired",
            "headers": ["环节", "自动处理", "人工确认"],
            "rows": [["发布前", "检查结构和证据", "确认语气与重点"], ["遇到异常", "明确阻断", "决定是否继续"]],
        },
    }],
}


def test_responsive_article() -> None:
    from playwright.sync_api import sync_playwright

    html = render_html(ARTICLE, PAYLOAD)
    with tempfile.TemporaryDirectory(prefix="article-responsive-") as temp, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for name, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844)):
                page = browser.new_page(viewport={"width": width, "height": height})
                page.set_content(html, wait_until="domcontentloaded")
                page.wait_for_timeout(150)
                metrics = page.evaluate(
                    """() => ({
                      bodyText: document.body.innerText.trim().length,
                      bodyWidth: document.documentElement.scrollWidth,
                      viewportWidth: document.documentElement.clientWidth,
                      offenders: [...document.querySelectorAll('main, article, section, table, pre, img, video, iframe')]
                        .filter(node => {
                          const box = node.getBoundingClientRect();
                          return box.width > 0 && (box.left < -1 || box.right > window.innerWidth + 1);
                        }).map(node => node.tagName + '.' + node.className).slice(0, 10)
                    })"""
                )
                assert metrics["bodyText"] > 100, metrics
                assert metrics["bodyWidth"] <= metrics["viewportWidth"] + 1, metrics
                assert not metrics["offenders"], metrics
                screenshot = Path(temp) / f"{name}.png"
                page.screenshot(path=str(screenshot), full_page=True)
                assert screenshot.stat().st_size > 10_000
                page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    test_responsive_article()
    print("responsive article tests passed")
