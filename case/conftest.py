# coding=utf-8
"""case 级 Pytest 配置：会话级服务预检、Playwright Browser 复用、用例级 Context/Page 隔离、失败自动取证。"""
from __future__ import annotations

import time

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from common.exceptions import find_in_chain, format_exception_chain
from config.settings import Config
from log.user_log import get_logger
from util import allure_compat
from util.browser_factory import BrowserFactory
from util.scenario_support import get_base_url, preflight_services
from util.screenshot_util import ScreenshotUtil

logger = get_logger()


def _resolve_headless_option(config: pytest.Config) -> bool | None:
    if config.getoption("--headless"):
        return True
    if config.getoption("--headed"):
        return False
    return None


def _resolve_trace_mode(config: pytest.Config) -> str:
    cli_mode = config.getoption("--pw-trace")
    if cli_mode:
        return str(cli_mode).lower()
    return str(Config().get("trace.mode", "retain-on-failure")).strip().lower()


@pytest.fixture(scope="session", autouse=True)
def service_preflight():
    """全量执行前先校验被测前后端可用，快速失败并给出启动指引。"""
    preflight_services()
    yield


@pytest.fixture(scope="session")
def playwright_instance():
    """会话级 Playwright 驱动实例。"""
    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def browser(request, playwright_instance) -> Browser:
    """会话级浏览器进程复用（配合函数级 BrowserContext 实现完全隔离与高速执行）。"""
    browser_type = request.config.getoption("--browser")
    headless = _resolve_headless_option(request.config)
    b = BrowserFactory.launch_browser(
        playwright_instance,
        browser_type=browser_type,
        headless=headless,
    )
    yield b
    b.close()


@pytest.fixture(scope="function")
def context(request, browser: Browser) -> BrowserContext:
    """用例级隔离 BrowserContext（独立 Cookie / Storage / 下载 / 弹窗），并按策略录制 Trace。"""
    browser_type = request.config.getoption("--browser")
    headless = _resolve_headless_option(request.config)
    ctx = BrowserFactory.create_context(
        browser,
        browser_type=browser_type,
        headless=headless,
    )

    trace_mode = _resolve_trace_mode(request.config)
    trace_active = trace_mode in ("on", "retain-on-failure")
    if trace_active:
        try:
            ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
        except Exception as exc:
            logger.warning("启动 Playwright Tracing 失败: %s", exc)
            trace_active = False

    # 挂在 request.node 上供 makereport hook 按需落盘并归档
    request.node._pw_trace_active = trace_active
    request.node._pw_trace_mode = trace_mode
    request.node._pw_trace_saved = False

    yield ctx

    if trace_active and not getattr(request.node, "_pw_trace_saved", False):
        try:
            if trace_mode == "on":
                trace_path = _build_trace_path(request.node.name)
                ctx.tracing.stop(path=trace_path)
                allure_compat.attach_zip("Playwright Trace", trace_path)
            else:
                ctx.tracing.stop()
        except Exception as exc:
            logger.warning("停止 Playwright Tracing 失败: %s", exc)

    try:
        ctx.close()
    except Exception as exc:
        logger.debug("关闭 BrowserContext 时发生异常: %s", exc)


@pytest.fixture(scope="function")
def page(context: BrowserContext) -> Page:
    """用例级 Page 入口：打开被测前端首页根地址，用例内通过 open_scenario 直达目标路由。"""
    p = BrowserFactory.create_page(context)
    p.goto(get_base_url(), wait_until="domcontentloaded")
    yield p


def _build_trace_path(case_name: str) -> str:
    safe_name = ScreenshotUtil.sanitize_name(case_name)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return str(BrowserFactory.resolve_trace_dir() / f"trace_{safe_name}_{timestamp}.zip")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """用例失败自动取证并归档：setup/call 失败时收敛 4 类证据进 Allure。

    架构第 ⑤ 层（收敛层）：不看异常类型、不做业务分支，统一收拢：
      1. 异常链全文（__cause__ 展开，含业务上下文 / 定位器 / 截图路径）；
      2. 元素级截图（ElementNotFoundError 抛出瞬间已拍，沿链捞取）；
      3. 用例级现场截图（pytest 判定失败之后）；
      4. Playwright Trace（.zip，可在 `playwright show-trace` 中完整回放 DOM/网络/控制台）。

    取证任一步失败只降级为 warning，绝不掩盖原始失败。
    """
    outcome = yield
    rep = outcome.get_result()

    if rep.when not in ("setup", "call") or not rep.failed:
        return

    exc_value = call.excinfo.value if getattr(call, "excinfo", None) else None

    # 1) 异常链全文：不依赖浏览器，启动阶段失败也能留证
    if exc_value is not None:
        allure_compat.attach_text("失败异常链", format_exception_chain(exc_value))

    # 2) 元素级截图：抛出瞬间拍下的原始现场，沿异常链捞取
    element_shot = find_in_chain(exc_value, "screenshot_path")
    if element_shot:
        allure_compat.attach_png("元素超时现场", element_shot)

    # 3) 用例级现场截图：判定失败后的最终页面状态
    pg = item.funcargs.get("page") if hasattr(item, "funcargs") else None
    if pg is not None:
        try:
            on_failure = bool(Config().get("screenshot.on_failure", True))
        except Exception:
            on_failure = True
        if on_failure:
            try:
                screenshot_path = ScreenshotUtil.capture(pg, item.name)
                print(f"\n[全局拦截] 用例失败，已保存崩溃现场截图: {screenshot_path}")
                allure_compat.attach_png("用例失败现场", screenshot_path)
            except Exception as capture_error:
                logger.warning("用例失败截图失败（不掩盖原始失败）: %s", capture_error)

    # 4) Playwright Trace：失败立即落盘并附入当前用例报告
    ctx = item.funcargs.get("context") if hasattr(item, "funcargs") else None
    if (
        ctx is not None
        and getattr(item, "_pw_trace_active", False)
        and not getattr(item, "_pw_trace_saved", False)
    ):
        try:
            trace_path = _build_trace_path(item.name)
            ctx.tracing.stop(path=trace_path)
            item._pw_trace_saved = True
            print(f"[全局拦截] 已保存 Playwright Trace: {trace_path}")
            allure_compat.attach_zip("Playwright Trace", trace_path)
        except Exception as trace_error:
            logger.warning("保存 Playwright Trace 失败（不掩盖原始失败）: %s", trace_error)
