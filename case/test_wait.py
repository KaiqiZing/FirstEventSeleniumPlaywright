# coding=utf-8
"""W-01 ~ W-05 等待响应类场景主流程用例（Playwright 版）。"""
from __future__ import annotations

import pytest

from business.wait_business import WaitBusiness
from handle.interact_handles import I01Handle as ResultBoxHandle
from handle.wait_handles import W02Handle, W03Handle
from util import allure_compat
from util.scenario_support import open_scenario


@pytest.mark.smoke
@allure_compat.feature("等待响应")
def test_w01_slow_loading(page):
    """慢接口：等待 loading 遮罩消失与表格行稳定。"""
    open_scenario(page, "/w/01")
    count = WaitBusiness(page).run_w01()
    assert count >= 10, f"慢接口返回行数异常: {count}"
    ResultBoxHandle(page).assert_log("查询完成")


@allure_compat.feature("等待响应")
def test_w02_spa_route_switch(page):
    """SPA 无刷新路由切换：切到收支明细并等待 URL/内容变化。"""
    open_scenario(page, "/w/02")
    WaitBusiness(page).run_w02()
    h = W02Handle(page)
    assert "view=flow" in page.url
    strong_text = h.text_of("view_card")
    assert "收支明细" in strong_text, f"视图卡片内容未切换: {strong_text}"
    ResultBoxHandle(page).assert_log("当前子视图：flow")


@allure_compat.feature("等待响应")
def test_w03_export_task(page):
    """异步导出：等待任务完成后再触发下载并验证落盘产物。"""
    open_scenario(page, "/w/03")
    saved_file = WaitBusiness(page).run_w03()
    h = W03Handle(page)
    h.assert_log("导出完成")
    h.assert_log("已触发下载导出文件")
    if saved_file is not None:
        assert saved_file.exists() and saved_file.stat().st_size > 0, (
            f"导出下载产物不存在或为空: {saved_file}"
        )


@allure_compat.feature("等待响应")
def test_w04_race_assert(page):
    """保存落库竞态：先等完成再刷新断言，避免断言跑在落库前。"""
    open_scenario(page, "/w/04")
    content = f"临时调整门店营业时间-{__import__('time').time_ns() % 10000}"
    WaitBusiness(page).run_w04(content)


@allure_compat.feature("等待响应")
def test_w05_unstable_api(page):
    """不稳定接口：页面内重试直至同步成功。"""
    open_scenario(page, "/w/05")
    attempts = WaitBusiness(page).run_w05()
    assert attempts >= 1
    ResultBoxHandle(page).assert_log("同步成功")
