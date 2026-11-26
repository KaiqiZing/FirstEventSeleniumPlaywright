# coding=utf-8
"""Playwright Demo：验收「UI 场景演练台」6 大分类、全部 37 个子界面的加载与标签/颜色一致性。

核对目标（测试地址 http://localhost:5173/）：
1. 遍历左侧菜单栏 6 大分类（页面交互类 / 等待与响应类 / 多窗口与多标签 / 浏览器兼容类 / 其他疑难类 / 数据加密类）下所有子界面；
2. 校验每个子界面加载正常（.page-title 渲染、无白屏、无 console error / pageerror、无 HTTP >= 400）；
3. 核对「右侧边缘标签 (.edge-tab)」「右上角标签 (.group-tag)」与「左侧分类标题 (.group-title)」文案一致；
4. 核对切换分类时，「左侧激活菜单项 (.item.active)」「右侧标签 (.edge-tab)」「右上角标签 (.group-tag)」背景色与文字色同步切换且完全一致。

运行方式（任选其一）：
    python demo/test_menu_tag_consistency.py
    python -m pytest demo/test_menu_tag_consistency.py -v -s
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

# 支持直接 `python demo/test_menu_tag_consistency.py` 运行
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from util.browser_factory import BrowserFactory  # noqa: E402

BASE_URL = "http://localhost:5173/"
EXPECTED_GROUPS = [
    "页面交互类",
    "等待与响应类",
    "多窗口与多标签",
    "浏览器兼容类",
    "其他疑难类",
    "数据加密类",
]


@dataclass
class PageCheckResult:
    group_title: str
    item_code: str
    item_label: str
    route: str
    page_title: str
    active_bg: str
    active_color: str
    edge_text: str
    edge_bg: str
    edge_color: str
    top_text: str
    top_bg: str
    top_color: str
    crumb_code_color: str
    console_errors: list[str]
    failed_requests: list[str]
    load_ok: bool
    text_match: bool
    color_match: bool
    elapsed_ms: float

    @property
    def passed(self) -> bool:
        return self.load_ok and self.text_match and self.color_match


def _rgb_to_hex(rgb: str) -> str:
    """将 computedStyle 的 rgb(r, g, b) 转为标准 #rrggbb 便于对照核验。"""
    raw = (rgb or "").strip().lower()
    if not raw.startswith("rgb"):
        return raw
    inside = raw[raw.find("(") + 1 : raw.rfind(")")]
    parts = [p.strip() for p in inside.split(",")]
    if len(parts) < 3:
        return raw
    try:
        r, g, b = int(float(parts[0])), int(float(parts[1])), int(float(parts[2]))
        if len(parts) == 4 and float(parts[3]) == 0:
            return "transparent"
        return f"#{r:02x}{g:02x}{b:02x}"
    except ValueError:
        return raw


def _read_tag_style(page: Page, selector: str) -> dict[str, Any]:
    return page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            if (!el) return { exists: false, visible: false, text: '', bg: '', color: '' };
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            const visible = style.display !== 'none'
                && style.visibility !== 'hidden'
                && rect.width > 0 && rect.height > 0;
            return {
                exists: true,
                visible,
                text: (el.innerText || el.textContent || '').replace(/\\s+/g, '').trim(),
                bg: style.backgroundColor,
                color: style.color,
            };
        }""",
        selector,
    )


def run_menu_tag_acceptance(headless: bool = True) -> dict[str, Any]:
    """执行全量左侧菜单遍历与三处标签文案/颜色一致性核验，返回结构化统计与明细。"""
    t_total_start = time.perf_counter()
    results: list[PageCheckResult] = []
    group_summary: dict[str, dict[str, Any]] = {}

    with sync_playwright() as pw:
        browser = BrowserFactory.launch_browser(pw, headless=headless)
        # 使用 1440x900 宽屏视口，确保响应式阈值 (>1320px) 下右侧 .edge-tab 正常显示
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        console_errors: list[str] = []
        failed_requests: list[str] = []

        page.on(
            "console",
            lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
        )
        page.on("pageerror", lambda err: console_errors.append(str(err)))
        page.on(
            "response",
            lambda resp: failed_requests.append(f"{resp.status} {resp.url}")
            if resp.status >= 400
            else None,
        )

        page.goto(BASE_URL, wait_until="networkidle")
        # 等待左侧菜单分类加载就绪
        page.locator(".group-title").first.wait_for(state="visible", timeout=10000)

        t_traverse_start = time.perf_counter()

        # 按 DOM 文档顺序一次性读取左侧 6 大分类及其下属菜单项全局索引（兼容平铺或分组容器结构）
        menu_plan: list[dict[str, Any]] = page.evaluate(
            """() => {
                const firstTitle = document.querySelector('.group-title');
                const sidebar = firstTitle.closest('aside, nav, .sidebar, .side, .menu') || firstTitle.parentElement.parentElement;
                const nodes = sidebar.querySelectorAll('.group-title, .item');
                const groups = [];
                let current = null;
                let globalIndex = 0;
                nodes.forEach((el) => {
                    if (el.classList.contains('group-title')) {
                        current = {
                            groupName: (el.innerText || el.textContent || '').trim(),
                            items: [],
                        };
                        groups.push(current);
                    } else if (el.classList.contains('item') && current) {
                        const rawText = (el.innerText || el.textContent || '').trim();
                        const lines = rawText.split(/\\s+/).filter(Boolean);
                        current.items.push({
                            globalIndex,
                            code: lines[0] || rawText,
                            label: lines.slice(1).join(' ') || rawText,
                        });
                        globalIndex += 1;
                    }
                });
                return groups;
            }"""
        )

        discovered_groups = [g["groupName"] for g in menu_plan]
        assert discovered_groups == EXPECTED_GROUPS, (
            f"左侧分类列表与预期不符: 实际={discovered_groups} / 预期={EXPECTED_GROUPS}"
        )

        all_items = page.locator(".item")

        for group in menu_plan:
            group_name = group["groupName"]

            for item in group["items"]:
                item_start = time.perf_counter()
                console_errors.clear()
                failed_requests.clear()

                item_loc = all_items.nth(item["globalIndex"])
                item_loc.scroll_into_view_if_needed()
                expected_route = "/" + item["code"].lower().replace("-", "/")
                item_loc.click()

                # 等待 Vue Router 完成路由切换与新页面主标题/面包屑就绪（避免 SPA 读到上一页旧态）
                page.wait_for_url(f"**{expected_route}", timeout=10000)
                page.locator(".page-title").first.wait_for(state="visible", timeout=10000)
                page.wait_for_function(
                    """(expectedCode) => {
                        const crumb = document.querySelector('.crumb-code');
                        return crumb && crumb.textContent.trim() === expectedCode;
                    }""",
                    arg=item["code"],
                    timeout=5000,
                )
                # 等待三处标签的有限时长 CSS 过渡动画完成，确保读取终态计算色值
                page.evaluate(
                    """async () => {
                        const targets = document.querySelectorAll('.item.active, .edge-tab, .group-tag');
                        const animations = [];
                        targets.forEach((el) => {
                            el.getAnimations().forEach((anim) => {
                                const timing = anim.effect && anim.effect.getTiming ? anim.effect.getTiming() : null;
                                if (!timing || timing.iterations !== Infinity) {
                                    animations.push(anim.finished.catch(() => {}));
                                }
                            });
                        });
                        if (animations.length) await Promise.all(animations);
                    }"""
                )

                page_title = page.locator(".page-title").first.inner_text().strip()
                route = page.url.replace(BASE_URL.rstrip("/"), "") or "/"

                active_style = _read_tag_style(page, ".item.active")
                edge_style = _read_tag_style(page, ".edge-tab")
                top_style = _read_tag_style(page, ".env .group-tag, .group-tag")
                crumb_style = _read_tag_style(page, ".crumb-code")

                active_bg = _rgb_to_hex(active_style["bg"])
                active_color = _rgb_to_hex(active_style["color"])
                edge_bg = _rgb_to_hex(edge_style["bg"])
                edge_color = _rgb_to_hex(edge_style["color"])
                top_bg = _rgb_to_hex(top_style["bg"])
                top_color = _rgb_to_hex(top_style["color"])
                crumb_color = _rgb_to_hex(crumb_style["color"])

                load_ok = (
                    bool(page_title)
                    and len(console_errors) == 0
                    and len(failed_requests) == 0
                    and edge_style["visible"]
                    and top_style["visible"]
                )
                text_match = (
                    edge_style["text"] == group_name
                    and top_style["text"] == group_name
                )
                color_match = (
                    bool(active_bg)
                    and active_bg == edge_bg == top_bg
                    and active_color == edge_color == top_color
                )

                rec = PageCheckResult(
                    group_title=group_name,
                    item_code=item["code"],
                    item_label=item["label"],
                    route=route,
                    page_title=page_title,
                    active_bg=active_bg,
                    active_color=active_color,
                    edge_text=edge_style["text"],
                    edge_bg=edge_bg,
                    edge_color=edge_color,
                    top_text=top_style["text"],
                    top_bg=top_bg,
                    top_color=top_color,
                    crumb_code_color=crumb_color,
                    console_errors=list(console_errors),
                    failed_requests=list(failed_requests),
                    load_ok=load_ok,
                    text_match=text_match,
                    color_match=color_match,
                    elapsed_ms=(time.perf_counter() - item_start) * 1000.0,
                )
                results.append(rec)

                group_summary.setdefault(
                    group_name,
                    {
                        "count": 0,
                        "passed": 0,
                        "bg": active_bg,
                        "color": active_color,
                        "edge_bg": edge_bg,
                        "top_bg": top_bg,
                    },
                )
                group_summary[group_name]["count"] += 1
                if rec.passed:
                    group_summary[group_name]["passed"] += 1

        traverse_seconds = time.perf_counter() - t_traverse_start
        context.close()
        browser.close()

    total_seconds = time.perf_counter() - t_total_start
    return {
        "total": len(results),
        "load_ok_count": sum(1 for r in results if r.load_ok),
        "text_match_count": sum(1 for r in results if r.text_match),
        "color_match_count": sum(1 for r in results if r.color_match),
        "passed_count": sum(1 for r in results if r.passed),
        "total_seconds": total_seconds,
        "traverse_seconds": traverse_seconds,
        "avg_ms_per_page": (traverse_seconds * 1000.0 / len(results)) if results else 0.0,
        "group_summary": group_summary,
        "results": results,
    }


def _print_report(report: dict[str, Any]) -> None:
    print("\n" + "=" * 78)
    print("Playwright Demo 验收报告：6 大分类 & 37 子页面加载与标签/颜色一致性")
    print("=" * 78)
    print(
        f"总页面数: {report['total']} | 加载正常: {report['load_ok_count']}/{report['total']} | "
        f"文案一致: {report['text_match_count']}/{report['total']} | "
        f"颜色一致: {report['color_match_count']}/{report['total']}"
    )
    print(
        f"端到端总耗时(含启停浏览器): {report['total_seconds']:.2f}s | "
        f"37 页遍历+断言耗时: {report['traverse_seconds']:.2f}s | "
        f"单页均值: {report['avg_ms_per_page']:.1f}ms"
    )
    print("-" * 78)
    print(f"{'分类标题':<12} {'数量':>4} {'左侧高亮bg':<10} {'右侧标签bg':<10} {'右上角bg':<10} {'状态'}")
    for g_name, info in report["group_summary"].items():
        status = "PASS" if info["passed"] == info["count"] else "FAIL"
        print(
            f"{g_name:<12} {info['count']:>4} {info['bg']:<10} "
            f"{info['edge_bg']:<10} {info['top_bg']:<10} {status} ({info['passed']}/{info['count']})"
        )
    print("-" * 78)
    # 校验 6 大分类之间颜色互不重复（确实发生了切换）
    distinct_colors = {info["bg"] for info in report["group_summary"].values()}
    print(f"6 大分类去重颜色数: {len(distinct_colors)} -> {sorted(distinct_colors)}")
    crumb_colors = {r.crumb_code_color for r in report["results"]}
    print(f"附注：左上角 .crumb-code 字体色集合: {sorted(crumb_colors)}")
    failures = [r for r in report["results"] if not r.passed]
    if failures:
        print("\n[失败项明细]")
        for f in failures:
            print(
                f"  - {f.item_code} ({f.route}): load={f.load_ok}, text={f.text_match}, "
                f"color={f.color_match}, errors={f.console_errors}, failed_req={f.failed_requests}"
            )
    print("=" * 78)


def test_menu_and_tag_consistency_demo():
    """pytest 入口：一键运行并断言 37/37 全部一致、6 类颜色独立切换。"""
    report = run_menu_tag_acceptance(headless=True)
    _print_report(report)

    assert report["total"] == 37, f"预期 37 个子界面，实际 {report['total']}"
    assert report["load_ok_count"] == 37, "存在加载异常或报错的页面"
    assert report["text_match_count"] == 37, "存在右侧/右上角标签文案与左侧分类标题不一致的页面"
    assert report["color_match_count"] == 37, "存在三处标签颜色切换不一致的页面"
    distinct_colors = {info["bg"] for info in report["group_summary"].values()}
    assert len(distinct_colors) == 6, f"6 大分类应有 6 种不同分类色，实际: {distinct_colors}"


if __name__ == "__main__":
    summary = run_menu_tag_acceptance(headless=True)
    _print_report(summary)
    if summary["passed_count"] != summary["total"]:
        raise SystemExit(1)
