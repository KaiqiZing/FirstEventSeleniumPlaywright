"""场景句柄基类（Playwright 版）：统一封装元素解析 / 显式等待 / 日志 / 结果区断言。

每个场景的 handle 继承本类并传入场景码（module，如 "I01"），
元素 key 统一通过 fd.get_locator(key, module) 从对应分组 INI 读取为 Playwright Selector。
"""
from __future__ import annotations

from playwright.sync_api import Locator, Page

from base.find_element import FindElement
from common.page_wait_common import PageWaitCommon
from handle.action_support import set_input_value
from log.user_log import get_logger
from util.scenario_support import (
    assert_result_contains,
    result_logs,
    wait_result_contains,
)


class BaseScenarioHandle:
    def __init__(self, page: Page, module: str, timeout: int | float | None = None):
        self.page = page
        self.module = str(module).upper()
        self.logger = get_logger()
        self.fd = FindElement(page)
        self.wait = PageWaitCommon(page, timeout)

    # ---------------- 定位器 ---------------- #
    def loc(self, key: str) -> str:
        """返回 Playwright Selector 字符串（css 直接返回，xpath 自动带 xpath= 前缀）。"""
        return self.fd.get_locator(key, self.module)

    def xpath(self, key: str) -> str:
        """返回未加前缀的原始定位串（用于 .format(...) 拼接或局部子定位）。"""
        return self.fd.get_text(key, self.module)

    def locator(self, key: str) -> Locator:
        """直接返回对应元素的 Playwright Locator。"""
        return self.page.locator(self.loc(key))

    # ---------------- 等待 ---------------- #
    def visible(self, key: str) -> Locator:
        return self.wait.wait_for_visible(self.loc(key))

    def presence(self, key: str) -> Locator:
        return self.wait.wait_for_presence(self.loc(key))

    def clickable(self, key: str) -> Locator:
        return self.wait.wait_for_clickable(self.loc(key))

    # ---------------- 操作 ---------------- #
    def click(self, key: str, force_js: bool = False) -> Locator:
        return self.wait.click_params(self.loc(key), force_js=force_js)

    def fill(self, key: str, value: str, clear_first: bool = True) -> Locator:
        return self.wait.send_keys_params(self.loc(key), value, clear_first=clear_first)

    def js_fill(self, key: str, value: str) -> Locator:
        """用原生 value setter 写入并派发 input/change 事件，确保 Vue v-model 与原生日期控件同步。"""
        element = self.wait.wait_for_visible(self.loc(key))
        set_input_value(element, value)
        return element

    def text_of(self, key: str) -> str:
        return self.wait.get_text(self.loc(key))

    def attr_of(self, key: str, attr: str) -> str | None:
        return self.wait.get_attribute(self.loc(key), attr)

    def scroll_to(self, key: str) -> Locator:
        return self.wait.scroll_to_element(self.loc(key))

    # ---------------- 结果区断言 ---------------- #
    def logs(self) -> list[str]:
        return result_logs(self.page)

    def wait_log(self, keyword: str, timeout: int | float | None = None) -> bool:
        return wait_result_contains(self.page, keyword, timeout or self.wait.timeout)

    def assert_log(self, keyword: str, timeout: int | float | None = None, extra: str = "") -> None:
        assert_result_contains(self.page, keyword, timeout or self.wait.timeout, extra)
