"""多窗口/多标签类（M-01~M-04）场景操作层（Playwright 原生 Page / expect_popup 版）。"""
from __future__ import annotations

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from handle.base_scenario_handle import BaseScenarioHandle
from util.scenario_support import wait_result_contains


class M01Handle(BaseScenarioHandle):
    """新标签页：target=_blank 打开单据详情 / 脚本打开空白标签。"""

    def __init__(self, page: Page):
        super().__init__(page, "M01")

    def open_bill_detail(self) -> str:
        self.wait.wait_for_visible(self.loc("bill_link"))
        with self.page.expect_popup(timeout=10000) as popup_info:
            self.click("bill_link")
        new_page = popup_info.value
        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=10000)
            target = new_page.locator(self.loc("detail_billno")).first
            target.wait_for(state="visible", timeout=10000)
            return target.inner_text()
        finally:
            if not new_page.is_closed():
                new_page.close()

    def open_script_blank(self) -> str:
        try:
            with self.page.expect_popup(timeout=5000) as popup_info:
                self.click("open_blank")
        except PlaywrightTimeoutError:
            return ""
        new_page = popup_info.value
        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=10000)
            return new_page.title()
        finally:
            if not new_page.is_closed():
                new_page.close()


class M02Handle(BaseScenarioHandle):
    """OAuth 小窗授权：小窗自动回传并关闭（事件驱动 expect_event('close')）。"""

    def __init__(self, page: Page):
        super().__init__(page, "M02")

    def start_and_approve(self, timeout: int = 12) -> None:
        with self.page.expect_popup(timeout=5000) as popup_info:
            self.click("start_auth")
        popup = popup_info.value
        popup.wait_for_load_state("domcontentloaded", timeout=10000)
        approve = popup.locator("#approveBtn").first
        approve.wait_for(state="visible", timeout=10000)
        # 事件驱动等待授权小窗自动关闭
        with popup.expect_event("close", timeout=timeout * 1000):
            approve.click()

    def use_ticket(self) -> None:
        self.click("use_ticket")


class M03Handle(BaseScenarioHandle):
    """新窗口内嵌 iframe（窗口内容即 frame-a，内含二级 iframe frame-b）。"""

    def __init__(self, page: Page):
        super().__init__(page, "M03")

    def open_process_window(self) -> Page:
        with self.page.expect_popup(timeout=5000) as popup_info:
            self.click("open_win")
        win = popup_info.value
        win.wait_for_load_state("domcontentloaded", timeout=10000)
        return win

    def submit_inner_apply(self, win: Page, reason: str, amount: str, dept: str) -> None:
        inner = win.frame_locator("#innerFrame")
        inner.locator(self.loc("reason")).fill(reason)
        inner.locator(self.loc("amount")).fill(amount)
        inner.locator(self.loc("dept")).select_option(label=dept)
        inner.locator(self.loc("submit")).click()

    def close_window(self, win: Page) -> None:
        if win and not win.is_closed():
            win.close()

    def register_main(self) -> None:
        self.click("main_register")


class M04Handle(BaseScenarioHandle):
    """弹窗拦截策略：手势内直接打开 vs 延时脚本打开。"""

    def __init__(self, page: Page):
        super().__init__(page, "M04")

    def direct_open(self) -> bool:
        try:
            with self.page.expect_popup(timeout=5000) as popup_info:
                self.click("direct_btn")
            popup = popup_info.value
            if not popup.is_closed():
                popup.close()
            return True
        except PlaywrightTimeoutError:
            return False

    def delayed_open(self) -> bool:
        before_pages = list(self.page.context.pages)
        self.click("delayed_btn")
        # 1.2s 后脚本触发 window.open
        self.page.wait_for_timeout(2000)
        extra_pages = [p for p in self.page.context.pages if p not in before_pages]
        opened = len(extra_pages) > 0
        for p in extra_pages:
            if not p.is_closed():
                p.close()
        return opened

    def wait_result_contains(self, keyword: str, timeout: int = 10) -> bool:
        return wait_result_contains(self.page, keyword, timeout)
