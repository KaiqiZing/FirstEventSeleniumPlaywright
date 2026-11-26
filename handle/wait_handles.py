"""等待响应类（W-01~W-05）场景操作层（Playwright 版）。"""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import Page

from handle import action_support as act
from handle.base_scenario_handle import BaseScenarioHandle
from util.browser_factory import BrowserFactory
from util.scenario_support import result_logs, wait_result_contains


class W01Handle(BaseScenarioHandle):
    """慢接口：点击查询后先等 loading 遮罩消失再读表格。"""

    def __init__(self, page: Page):
        super().__init__(page, "W01")

    def pick_normal_speed(self) -> None:
        act.click_el_radio_by_text(self.page, "常规（3s）")

    def query_and_wait_rows(self, timeout: int = 20) -> int:
        self.click("query_btn")
        act.wait_loading_mask_gone(self.page, self.loc("loading_mask"), timeout=timeout)
        deadline = time.time() + timeout
        last_count = 0
        stable_since = time.time()
        while time.time() < deadline:
            count = self.page.locator(self.loc("table_rows")).count()
            if count and count == last_count:
                if time.time() - stable_since > 0.8:
                    return count
            else:
                last_count = count
                stable_since = time.time()
            self.page.wait_for_timeout(250)
        return last_count


class W02Handle(BaseScenarioHandle):
    """SPA 路由切换：点击 tab 后从 URL 与视图卡片双重确认已切换。"""

    def __init__(self, page: Page):
        super().__init__(page, "W02")

    def switch_to_flow(self, timeout: int = 10) -> None:
        self.click("tab_flow")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if "view=flow" in self.page.url:
                break
            self.page.wait_for_timeout(200)
        else:
            raise AssertionError("切换子视图后 URL 未包含 view=flow")
        self.wait.wait_for_visible(self.loc("view_card"))


class W03Handle(BaseScenarioHandle):
    """异步导出长任务：页面内部轮询，等待任务完成再通过 expect_download 确定性落盘下载。"""

    def __init__(self, page: Page):
        super().__init__(page, "W03")

    def start_export(self) -> None:
        self.click("start_btn")

    def wait_export_done(self, timeout: int = 40) -> bool:
        return wait_result_contains(self.page, "导出完成", timeout)

    def click_download(self, timeout: int = 20) -> Path | None:
        self.wait.wait_for_visible(self.loc("download_link"))
        download_dir = BrowserFactory.resolve_download_dir()
        try:
            with self.page.expect_download(timeout=timeout * 1000) as dl_info:
                self.click("download_link")
            download = dl_info.value
            if download_dir:
                target = download_dir / download.suggested_filename
                download.save_as(str(target))
                return target
            return Path(download.path()) if download.path() else None
        except Exception as exc:
            self.logger.warning("捕获下载事件异常（将回退由结果区日志确认）: %s", exc)
            return None


class W04Handle(BaseScenarioHandle):
    """保存后落库竞态：等待保存完成后再刷新列表断言。"""

    def __init__(self, page: Page):
        super().__init__(page, "W04")

    def save_record(self, content: str, timeout: int = 15) -> bool:
        self.fill("content", content)
        self.click("save_btn")
        return wait_result_contains(self.page, "保存请求完成", timeout)

    def refresh_list(self) -> None:
        self.click("refresh_btn")

    def wait_record_shown(self, content: str, timeout: int = 10) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for text in self.page.locator(self.loc("rec_list")).all_inner_texts():
                if content in text:
                    return True
            self.page.wait_for_timeout(300)
        return False


class W05Handle(BaseScenarioHandle):
    """不稳定接口：页面内带重试，直到成功为止。"""

    def __init__(self, page: Page, max_seconds: int = 60):
        super().__init__(page, "W05")
        self.max_seconds = max_seconds

    def sync_until_success(self, timeout_each: int = 10) -> int:
        deadline = time.time() + self.max_seconds
        attempts = 0
        while time.time() < deadline:
            attempts += 1
            self.click("sync_btn")
            if wait_result_contains(self.page, "同步成功", timeout_each):
                return attempts
            self.page.wait_for_timeout(500)
        raise AssertionError(f"W-05 不稳定接口在 {self.max_seconds}s 内始终未同步成功")

    def result_row_count(self) -> int:
        try:
            return self.page.locator(self.loc("result_table")).count()
        except Exception:
            return 0

    def last_logs(self) -> list[str]:
        return result_logs(self.page)
