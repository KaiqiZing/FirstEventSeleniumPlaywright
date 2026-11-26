"""多窗口类业务（M-01~M-04）。"""
from __future__ import annotations

from playwright.sync_api import Page

from business.business_context import biz_step
from handle.window_handles import M01Handle, M02Handle, M03Handle, M04Handle
from util import allure_compat


@allure_compat.feature("多窗口")
class WindowBusiness:
    def __init__(self, page: Page):
        self.page = page

    @allure_compat.story("M-01 新标签页")
    def run_m01(self) -> tuple[str, str]:
        """返回 (详情单号, 占位页标题)。"""
        handle = M01Handle(self.page)
        with biz_step("在新标签页打开单据详情并读取单号"):
            bill_no = handle.open_bill_detail()
        with biz_step("脚本打开空白标签"):
            blank_title = handle.open_script_blank()
        return bill_no, blank_title

    @allure_compat.story("M-02 OAuth 小窗")
    def run_m02(self) -> None:
        h = M02Handle(self.page)
        with biz_step("发起授权并在小窗内同意授权"):
            h.start_and_approve()
        with biz_step("使用授权票据查询"):
            h.use_ticket()

    @allure_compat.story("M-03 新窗口内嵌 iframe")
    def run_m03(self, reason: str, amount: str, dept: str) -> None:
        h = M03Handle(self.page)
        with biz_step("在新窗口处理采购申请"):
            win = h.open_process_window()
        with biz_step("在窗口内层 iframe 提交申请"):
            try:
                h.submit_inner_apply(win, reason, amount, dept)
            finally:
                h.close_window(win)
        with biz_step("回主窗口登记主档"):
            h.register_main()

    @allure_compat.story("M-04 弹窗拦截")
    def run_m04(self) -> tuple[bool, bool]:
        h = M04Handle(self.page)
        with biz_step("手势内立即预览"):
            direct_opened = h.direct_open()
        with biz_step("延时脚本触发预览"):
            delayed_opened = h.delayed_open()
        return direct_opened, delayed_opened
