"""场景导航 / 结果区断言 / 服务预检等通用工具（Playwright 版，不依赖具体 handle）。"""
from __future__ import annotations

import os
import re
import time

import requests
from playwright.sync_api import Page

from config.settings import Config
from log.user_log import get_logger

logger = get_logger()

_RESULT_BOX_SELECTOR = "xpath=//div[contains(@class, 'result-box')]"
_LOG_LINE_SELECTOR = "xpath=//div[contains(@class, 'result-box')]//*[contains(@class,'log-line')]"
_TITLE_SELECTOR = "xpath=//div[contains(@class, 'page-title')]"

# 前端常用端口：Vite 默认 5173，端口被占用时会顺延（如 5174）——配置不通时自动回退
_FRONTEND_PORTS = ("5173", "5174")
# 会话内解析成功的可用前端地址（避免每次请求都探测）
_effective_base_url: str | None = None


def get_base_url() -> str:
    if _effective_base_url:
        return _effective_base_url
    env_override = os.environ.get("ACCEPTANCE_FRONTEND_URL", "").strip()
    if env_override:
        return env_override.rstrip("/")
    env_config = Config().get_env_config()
    return str(env_config.get("base_url", "http://localhost:5173")).rstrip("/")


def _probe(url: str, timeout: int = 3) -> bool:
    try:
        return requests.get(f"{url}/", timeout=timeout).status_code < 500
    except Exception:
        return False


def resolve_base_url(timeout: int = 3) -> str:
    """确定可用前端地址：配置端口不通时回退到另一个常用端口并告警。"""
    global _effective_base_url
    if _effective_base_url:
        return _effective_base_url

    base = get_base_url()
    if _probe(base, timeout):
        _effective_base_url = base
        return base
    for port in _FRONTEND_PORTS:
        candidate = re.sub(r":\d+$", f":{port}", base)
        if candidate != base and _probe(candidate, timeout):
            logger.warning("配置的前端地址 %s 不可达，已自动切换为 %s", base, candidate)
            _effective_base_url = candidate
            return candidate
    _effective_base_url = base
    return base


def get_api_base_url() -> str:
    env_override = os.environ.get("ACCEPTANCE_API_URL", "").strip()
    if env_override:
        return env_override.rstrip("/")
    env_config = Config().get_env_config()
    return str(env_config.get("api_base_url", "http://127.0.0.1:5050")).rstrip("/")


def open_scenario(page: Page, route: str, timeout: int = 15) -> None:
    """直达场景路由并等待页面标题出现。"""
    url = f"{get_base_url()}{route}"
    logger.info("打开场景页面: %s", url)
    page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
    page.locator(_TITLE_SELECTOR).first.wait_for(state="attached", timeout=timeout * 1000)


def wait_page_title(page: Page, timeout: int = 15) -> str:
    title_loc = page.locator(_TITLE_SELECTOR).first
    title_loc.wait_for(state="visible", timeout=timeout * 1000)
    return title_loc.inner_text()


def result_logs(page: Page) -> list[str]:
    """读取页面底部「操作结果」区全部日志行文本。"""
    try:
        if page.locator(_RESULT_BOX_SELECTOR).count() == 0:
            return []
        return page.locator(_LOG_LINE_SELECTOR).all_inner_texts()
    except Exception:
        return []


def wait_result_contains(page: Page, keyword: str, timeout: int | float = 15) -> bool:
    """轮询「操作结果」区直到出现包含 keyword 的日志行。"""
    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        for text in result_logs(page):
            if keyword in text:
                logger.info("结果区命中关键字「%s」: %s", keyword, text)
                return True
        page.wait_for_timeout(250)
    return False


def assert_result_contains(page: Page, keyword: str, timeout: int | float = 15, extra: str = "") -> None:
    if not wait_result_contains(page, keyword, timeout):
        recent = result_logs(page)
        raise AssertionError(
            f"「操作结果」区在 {timeout}s 内未出现关键字「{keyword}」{extra}；当前日志: {recent or '（空）'}"
        )


def preflight_services() -> None:
    """会话级服务预检：前端可达 + 5050 后端健康。失败给出明确提示。"""
    base_url = resolve_base_url()
    api_base_url = get_api_base_url()

    try:
        resp = requests.get(f"{base_url}/", timeout=5)
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(
            f"被测前端不可达 {base_url}（请先启动: cd frontend && npm run dev），原因: {e}"
        ) from e

    try:
        resp = requests.get(f"{api_base_url}/api/health", timeout=5)
        resp.raise_for_status()
        body = (
            resp.json()
            if resp.headers.get("content-type", "").startswith("application/json")
            else {}
        )
    except Exception as e:
        raise RuntimeError(
            f"被测后端不可达 {api_base_url}/api/health（请先启动: cd backend && python app.py），原因: {e}"
        ) from e
    logger.info("服务预检通过: frontend=%s backend=%s body=%s", base_url, api_base_url, body)
