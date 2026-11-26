# coding=utf-8
"""M-01 ~ M-04 多窗口类场景主流程用例（Playwright 版）。"""
from __future__ import annotations

from business.window_business import WindowBusiness
from handle.window_handles import M01Handle, M02Handle, M04Handle
from util import allure_compat
from util.scenario_support import open_scenario


@allure_compat.feature("多窗口")
def test_m01_new_tab(page):
    """target=_blank 新标签 + 脚本打开新标签。"""
    open_scenario(page, "/m/01")
    bill_no, blank_title = WindowBusiness(page).run_m01()
    assert "SO-20260901-118" in bill_no, f"新标签页详情单号不符: {bill_no}"
    assert blank_title == "新标签占位页"
    handle = M01Handle(page)
    handle.assert_log("已通过脚本触发打开新标签（成功）")


@allure_compat.feature("多窗口")
def test_m02_oauth_popup(page):
    """OAuth 小窗授权：同意后自动回传并关闭。"""
    open_scenario(page, "/m/02")
    WindowBusiness(page).run_m02()
    handle = M02Handle(page)
    handle.assert_log("授权窗口已确认：授权成功并自动关闭，主窗口已收到结果")
    handle.assert_log("已使用授权票据拉取渠道数据")
    assert "已授权" in page.locator("b.text-ok").first.inner_text()


@allure_compat.feature("多窗口")
def test_m03_window_iframe(page):
    """新窗口内嵌 iframe：在窗口内层提交后回主窗口登记。"""
    open_scenario(page, "/m/03")
    WindowBusiness(page).run_m03("采购办公桌椅", "3200", "研发中心")
    handle = M01Handle(page)
    handle.assert_log("已在新窗口打开申请处理页（内含一层 iframe，iframe 内又有二层表单）")
    handle.assert_log("主档登记完成：第 1 次")


@allure_compat.feature("多窗口")
def test_m04_popup_blocked(page):
    """弹窗策略：手势内打开成功，延时脚本打开按浏览器实际策略断言计数。"""
    open_scenario(page, "/m/04")
    direct_opened, delayed_opened = WindowBusiness(page).run_m04()
    handle = M04Handle(page)
    handle.assert_log("立即预览：预览窗口已打开（成功 1 次）")
    if delayed_opened:
        handle.assert_log("延时打开：预览窗口已打开（成功 2 次）")
    else:
        handle.assert_log("延时打开：window.open 返回 null，弹出窗口未创建（被拦截 1 次）")
    assert direct_opened is True
