"""通用 Playwright 显式等待与元素操作封装。"""
from __future__ import annotations

import time
from typing import Any

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from base.find_element import to_playwright_selector
from common.exceptions import ElementNotFoundError
from log.user_log import get_logger
from util.screenshot_util import ScreenshotUtil

_DEFAULT_TIMEOUT = 15


def _load_timeout_from_config() -> int:
    try:
        from config.settings import Config

        cfg = Config()
        val = cfg.get("browser.action_timeout")
        if val is not None:
            return int(val)
        return int(cfg.get_env_config().get("timeout", _DEFAULT_TIMEOUT))
    except Exception:
        return _DEFAULT_TIMEOUT


def resolve_selector(locator: Any) -> str:
    """统一将定位器转换为 Playwright Selector 字符串。

    兼容：
    - 已转换的 Playwright Selector 字符串（如 `#id`、`.cls`、`xpath=//div`、`text=foo`）
    - 裸 XPath 字符串（以 `//`、`(//`、`.//` 开头，自动补 `xpath=` 前缀）
    - 历史 `(by, value)` 二元组（如 `("css selector", ".foo")`）
    """
    if isinstance(locator, tuple) and len(locator) == 2:
        by, value = locator
        return to_playwright_selector(str(by), str(value))
    if isinstance(locator, str):
        raw = locator.strip()
        if raw.startswith(("//", "(//", ".//")):
            return f"xpath={raw}"
        return raw
    raise ValueError(f"不支持的定位器格式: {locator!r}")


class PageWaitCommon:
    """所有元素等待与基础交互的统一入口（对标原 WebDriverWaitCommon）。"""

    def __init__(self, page: Page, timeout: int | float | None = None):
        self.page = page
        self.logger = get_logger()
        self.timeout = float(timeout if timeout is not None else _load_timeout_from_config())

    def _timeout_ms(self, timeout: int | float | None = None) -> float:
        return float(self.timeout if timeout is None else timeout) * 1000.0

    def locator(self, selector: Any) -> Locator:
        """返回对应 Playwright Locator（若已是 Locator 则原样返回）。"""
        if isinstance(selector, Locator):
            return selector
        return self.page.locator(resolve_selector(selector))

    def _build_not_found_error(self, locator: Any, action: str) -> ElementNotFoundError:
        screenshot_path = ""
        try:
            screenshot_path = ScreenshotUtil.capture(self.page, f"{action}_{locator}")
        except Exception as capture_error:
            self.logger.warning("元素异常时截图失败: %s", capture_error)
        return ElementNotFoundError(
            message=f"{action}失败，未找到目标元素",
            locator=locator,
            screenshot_path=screenshot_path or None,
        )

    def wait_for_visible(self, locator: Any, timeout: int | float | None = None) -> Locator:
        """等待元素可见（默认取首个匹配，规避多匹配 strict mode 冲突）。"""
        target = self.locator(locator).first
        try:
            target.wait_for(state="visible", timeout=self._timeout_ms(timeout))
            return target
        except PlaywrightTimeoutError as exc:
            raise self._build_not_found_error(locator, "等待元素可见") from exc

    def wait_for_presence(self, locator: Any, timeout: int | float | None = None) -> Locator:
        """等待元素挂载到 DOM（不一定可见）。"""
        target = self.locator(locator).first
        try:
            target.wait_for(state="attached", timeout=self._timeout_ms(timeout))
            return target
        except PlaywrightTimeoutError as exc:
            raise self._build_not_found_error(locator, "等待元素出现") from exc

    def wait_for_clickable(self, locator: Any, timeout: int | float | None = None) -> Locator:
        """等待元素可见且可用（非 disabled）。"""
        sec = float(self.timeout if timeout is None else timeout)
        deadline = time.time() + sec
        target = self.locator(locator).first
        try:
            target.wait_for(state="visible", timeout=sec * 1000.0)
            while time.time() < deadline:
                if target.is_visible() and target.is_enabled():
                    return target
                time.sleep(0.1)
            raise PlaywrightTimeoutError(f"元素在 {sec}s 内仍处于禁用态: {locator}")
        except PlaywrightTimeoutError as exc:
            raise self._build_not_found_error(locator, "等待元素可点击") from exc

    def wait_for_disappear(self, locator: Any, timeout: int | float | None = None) -> bool:
        """等待匹配的全部元素不可见或移出 DOM，超时返回 False。

        注意：针对 Element Plus 折叠树表格（多行同时置 display:none）与弹窗遮罩，
        用 `visible=true` 统计可见元素个数，避免多节点触发 Playwright strict mode 报错。
        """
        sec = float(self.timeout if timeout is None else timeout)
        deadline = time.time() + sec
        visible_loc = self.locator(locator).locator("visible=true")
        while time.time() < deadline:
            try:
                if visible_loc.count() == 0:
                    return True
            except Exception:
                return True
            time.sleep(0.15)
        try:
            return visible_loc.count() == 0
        except Exception:
            return False

    def is_element_visible(self, locator: Any, timeout: int | float | None = None) -> bool:
        """判断元素是否在超时内可见，不抛异常。"""
        target = self.locator(locator).first
        try:
            target.wait_for(state="visible", timeout=self._timeout_ms(timeout))
            return True
        except PlaywrightTimeoutError:
            return False

    def get_text(self, locator: Any) -> str:
        """获取元素可见文本（inner_text 与 Selenium .text 语义一致）。"""
        return self.wait_for_visible(locator).inner_text()

    def get_attribute(self, locator: Any, attr: str) -> str | None:
        """获取元素属性值。"""
        return self.wait_for_visible(locator).get_attribute(attr)

    def scroll_to_element(self, locator: Any) -> Locator:
        """滚动到元素附近，方便后续点击与截图。"""
        target = self.wait_for_visible(locator)
        target.scroll_into_view_if_needed()
        return target

    def send_keys_params(
        self,
        locator: Any,
        params_contents: str,
        clear_first: bool = True,
    ) -> Locator:
        """健壮输入：等待可见 -> 填充（自动清空并触发 input/change 事件）。"""
        target = self.wait_for_visible(locator)
        text = str(params_contents)
        if clear_first:
            target.fill(text)
        else:
            target.click()
            target.press_sequentially(text)
        return target

    def click_params(self, locator: Any, force_js: bool = False) -> Locator:
        """健壮点击：等待可点击 -> 原生点击；原生失败自动 JS 点击兜底。"""
        if force_js:
            target = self.wait_for_presence(locator)
            target.evaluate("el => el.click()")
            return target
        target = self.wait_for_clickable(locator)
        try:
            target.click(timeout=self._timeout_ms())
        except Exception as exc:
            self.logger.warning("原生点击失败，尝试使用 JS 点击兜底: %s", exc)
            target.evaluate("el => el.click()")
        return target

    def wait_for_text_present(
        self,
        locator: Any,
        text: str,
        timeout: int | float | None = None,
    ) -> bool:
        """等待元素文本包含指定内容，超时返回 False。"""
        sec = float(self.timeout if timeout is None else timeout)
        deadline = time.time() + sec
        target = self.locator(locator).first
        while time.time() < deadline:
            try:
                if target.is_visible() and text in target.inner_text():
                    return True
            except Exception:
                pass
            time.sleep(0.15)
        return False

    def execute_script(self, expression: str, arg: Any = None) -> Any:
        """统一 JS 执行入口。"""
        if arg is None:
            return self.page.evaluate(expression)
        return self.page.evaluate(expression, arg)
