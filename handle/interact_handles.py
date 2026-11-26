"""页面交互类（I-01~I-18）场景操作层（Playwright 版）。"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Callable

from playwright.sync_api import Locator, Page

from handle import action_support as act
from handle.base_scenario_handle import BaseScenarioHandle
from log.user_log import get_logger
from util.amount_util import amount_equal, cents_to_yuan, parse_amount
from util.api_client import ApiClient
from util.sqlite_source import SqliteSource


class I01Handle(BaseScenarioHandle):
    """元素不可交互：勾选须知使按钮可用；先展开折叠再操作内部控件。"""

    def __init__(self, page: Page):
        super().__init__(page, "I01")

    def submit_handover(self, operator: str, note: str) -> None:
        self.fill("operator", operator)
        self.fill("note", note)
        # 勾选须知 -> 保存按钮由 disabled 变为可点击
        self.click("agree")
        self.clickable("save_btn")
        self.click("save_btn")

    def apply_advanced(self, reviewer: str) -> None:
        # 折叠内元素未展开前不存在：先展开折叠项
        self.click("collapse_adv")
        self.fill("reviewer", reviewer)
        self.click("apply_adv")


class I02Handle(BaseScenarioHandle):
    """点击被拦截：等遮罩消失 / 下载按钮可点后再下载。"""

    def __init__(self, page: Page):
        super().__init__(page, "I02")

    def generate_and_wait(self, timeout: int = 15) -> None:
        self.click("gen_btn")
        # 遮罩出现后等待其消失
        act.wait_loading_mask_gone(self.page, self.loc("mask"), timeout=timeout)

    def download_result(self) -> None:
        self.clickable("download_btn")
        self.click("download_btn")


class I03Handle(BaseScenarioHandle):
    """元素引用失效：先开启自动刷新观察整表重建，再停刷新并点击（Locator 天然防 Stale）。"""

    def __init__(self, page: Page):
        super().__init__(page, "I03")

    def enable_auto_refresh(self, settle_seconds: float = 6.5) -> None:
        """打开自动刷新，等待至少一次整表重建。"""
        switch = self.presence("auto_switch")
        if "is-checked" not in (switch.get_attribute("class") or ""):
            switch.click()
        self.page.wait_for_timeout(int(settle_seconds * 1000))

    def disable_auto_refresh(self) -> None:
        """关闭自动刷新，稳定当前列表。"""
        switch = self.presence("auto_switch")
        if "is-checked" in (switch.get_attribute("class") or ""):
            switch.click()
        self.page.wait_for_timeout(500)

    def view_first_task(self) -> None:
        self.presence("table_body")
        self.click("row_view")


class I04Handle(BaseScenarioHandle):
    """双层 iframe 内提交报销单（Playwright 无状态 FrameLocator 穿透）。"""

    def __init__(self, page: Page):
        super().__init__(page, "I04")

    def submit_reimburse(self, reason: str, amount: str, dept: str) -> None:
        outer = self.page.frame_locator(self.loc("frame_a"))
        inner = outer.frame_locator(self.loc("frame_b"))
        inner.locator(self.loc("reason")).fill(reason)
        inner.locator(self.loc("amount")).fill(amount)
        inner.locator(self.loc("dept")).select_option(label=dept)
        inner.locator(self.loc("submit")).click()


class I05Handle(BaseScenarioHandle):
    """Shadow DOM：两层 shadowRoot 穿透操作。

    避坑：Playwright CSS 选择器默认穿透开放 Shadow DOM，因此 `#shadowBox button.sbtn`
    会同时命中外层与内层 `shadow-inner-box` 中的按钮，须分别精确限定外层 `.first`
    与内层 `shadow-inner-box button.sbtn`。
    """

    def __init__(self, page: Page):
        super().__init__(page, "I05")

    def save_outer(self, content: str) -> None:
        host = self.page.locator(self.loc("shadow_host"))
        host.locator("input.sinp").first.fill(content)
        host.locator("button.sbtn").first.click()

    def run_inner(self) -> None:
        self.page.locator(f"{self.loc('shadow_host')} shadow-inner-box button.sbtn").first.click()

    def read_state(self) -> None:
        self.click("read_state")


class I06Handle(BaseScenarioHandle):
    """动态 id/class：只依赖 placeholder 与按钮文本。"""

    def __init__(self, page: Page):
        super().__init__(page, "I06")

    def submit_asset(self, asset_no: str, asset_name: str) -> None:
        self.fill("asset_no", asset_no)
        self.fill("asset_name", asset_name)
        self.click("submit_btn")

    def regen_attributes(self) -> None:
        self.click("regen_btn")


class I07Handle(BaseScenarioHandle):
    """原生 select + 自绘下拉混排。"""

    def __init__(self, page: Page):
        super().__init__(page, "I07")

    def native_query(self, region: str, period: str) -> None:
        self.visible("region").select_option(label=region)
        self.visible("period").select_option(label=period)
        self.click("query_native")

    def biz_query(self, biz_type: str, scope: str) -> None:
        self.click("biz_trigger")
        act.click_el_option(self.page, biz_type)
        self.click("scope_trigger")
        act.click_el_option(self.page, scope)
        self.click("query_biz")


class I08Handle(BaseScenarioHandle):
    """悬浮菜单。"""

    def __init__(self, page: Page):
        super().__init__(page, "I08")

    def batch_label(self) -> None:
        act.hover(self.page, self.loc("drop_trigger"))
        self.click("drop_batch")

    def edit_customer(self) -> None:
        act.hover(self.page, self.loc("customer_row"))
        self.click("row_edit")


class I09Handle(BaseScenarioHandle):
    """HTML5 拖拽分配。"""

    def __init__(self, page: Page):
        super().__init__(page, "I09")

    def drag_first_to_picked(self) -> None:
        act.drag_and_drop(self.page, self.loc("chip"), self.loc("picked_drop"))
        self.page.wait_for_timeout(500)

    def confirm(self) -> None:
        self.click("commit")

    def reset(self) -> None:
        self.click("reset")


class I10Handle(BaseScenarioHandle):
    """文件上传：对隐藏 input[type=file] 直接 set_input_files 本地绝对路径。"""

    def __init__(self, page: Page):
        super().__init__(page, "I10")

    def upload_and_register(self, abs_path: str) -> None:
        act.upload_file(self.page, self.loc("file_input"), abs_path)
        self.click("submit_reg")


class I11Handle(BaseScenarioHandle):
    """原生 alert/confirm/prompt（前置注册 dialog 监听）。"""

    def __init__(self, page: Page):
        super().__init__(page, "I11")

    def alert_view(self) -> str:
        return act.accept_dialog_on(self.page, lambda: self.click("alert_btn"))

    def confirm_stock(self) -> str:
        return act.accept_dialog_on(self.page, lambda: self.click("confirm_btn"))

    def prompt_note(self, note: str) -> str:
        return act.accept_dialog_on(self.page, lambda: self.click("prompt_btn"), prompt_text=note)


class I12Handle(BaseScenarioHandle):
    """contenteditable 富文本。"""

    def __init__(self, page: Page):
        super().__init__(page, "I12")

    def publish(self, title: str, body: str) -> None:
        self.fill("title", title)
        act.fill_contenteditable(self.page, self.loc("editor"), body)
        self.click("publish")


class I13Handle(BaseScenarioHandle):
    """渐入动画：等待动画进入完成态再操作。"""

    def __init__(self, page: Page):
        super().__init__(page, "I13")

    def open_and_confirm(self, timeout: int = 20) -> None:
        self.click("open_panel")
        # 等待动画完成日志出现（事件驱动，比样式类更可靠）
        self.wait.wait_for_visible(self.loc("slide_panel"))
        self.wait_log("推送面板动画完成，内容就绪", timeout=timeout)
        self.click("confirm_btn")


class I14Handle(BaseScenarioHandle):
    """滚动懒加载：容器内滚动直至加载完全部。"""

    def __init__(self, page: Page, max_pages: int = 20, timeout: int = 90):
        super().__init__(page, "I14")
        self.max_pages = max_pages
        self.timeout = timeout

    def load_all(self) -> int:
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            count = self.page.locator(".scroll-box .row").count()
            if count == 0:
                act.scroll_container_to_bottom(self.page, self.loc("scroll_box"))
                self.page.wait_for_timeout(400)
                continue
            tip_text = ""
            try:
                tip = self.page.locator(".more-tip").first
                if tip.is_visible():
                    tip_text = tip.inner_text()
            except Exception:
                pass
            if count >= 160 or "已加载全部" in tip_text:
                return count
            act.scroll_container_to_bottom(self.page, self.loc("scroll_box"))
            self.page.wait_for_timeout(600)
        raise AssertionError("懒加载在超时时间内未加载完 160 条任务")

    def back_first_page(self) -> None:
        self.click("reset_btn")


class I15Handle(BaseScenarioHandle):
    """坐标偏移：先展开完整区域再点击目标点。"""

    def __init__(self, page: Page):
        super().__init__(page, "I15")

    def expand_and_mark(self) -> None:
        self.click("expand_btn")
        self.click("target_dot", force_js=True)

    def inspect(self) -> None:
        self.click("inspect_btn")


class I16Handle(BaseScenarioHandle):
    """受控输入 + 异步联想：真实键入、等待联想、正确清空。"""

    def __init__(self, page: Page):
        super().__init__(page, "I16")

    def submit_ticket(self, customer: str, ticket_type: str) -> None:
        self.fill("cust_input", customer)
        self.click("type_trigger")
        act.click_el_option(self.page, ticket_type)
        self.click("submit_ticket")

    def search_suggest(self, keyword: str, expect_option: str) -> None:
        self.fill("kw_input", keyword)
        self.wait.wait_for_visible(self.loc("suggest_item"))
        items = self.page.locator(self.loc("suggest_item")).all()
        for item in items:
            if expect_option in item.inner_text():
                item.click()
                break
        else:
            items[0].click()
        self.click("search_btn")

    def clear_remark(self) -> None:
        self.fill("remark", "临时备注")
        self.click("clear_remark")


class I17Handle(BaseScenarioHandle):
    """结算单父子金额勾稽：树形行按 level 区分同名列，异步重算等待，金额用 Decimal 清洗后比较。"""

    PARENT_LEVEL = 0
    CHILD_LEVEL = 1

    def __init__(self, page: Page, timeout: int = 15):
        super().__init__(page, "I17", timeout)

    # ---------------- 行定位：父子同名列靠 level class 区分 ---------------- #
    def row_xpath(self, row_id: str, level: int = PARENT_LEVEL) -> str:
        """按「单号 + 行层级」定位树形表格行（子行需先展开才存在）。"""
        return (
            f"//tr[contains(@class,'el-table__row--level-{level}')]"
            f"[.//span[contains(@class,'mono')][normalize-space(.)='{row_id}']]"
        )

    def row(self, row_id: str, level: int = PARENT_LEVEL) -> Locator:
        return self.wait.wait_for_visible(f"xpath={self.row_xpath(row_id, level)}")

    def rows(self, level: int = PARENT_LEVEL) -> list[Locator]:
        """只统计可见行：Element Plus 折叠子行时仅置 display:none，DOM 节点仍在。"""
        key = "parent_row" if level == self.PARENT_LEVEL else "child_row"
        return self.page.locator(self.loc(key)).locator("visible=true").all()

    def row_count(self, level: int = PARENT_LEVEL) -> int:
        key = "parent_row" if level == self.PARENT_LEVEL else "child_row"
        return self.page.locator(self.loc(key)).locator("visible=true").count()

    def wait_row_count(self, level: int, expected: int, timeout: int | None = None) -> int:
        """轮询指定层级行数直到等于 expected。"""
        deadline = time.time() + (timeout or self.wait.timeout)
        count = self.row_count(level)
        while count != expected and time.time() < deadline:
            self.page.wait_for_timeout(250)
            count = self.row_count(level)
        if count != expected:
            role = "父" if level == self.PARENT_LEVEL else "子"
            raise AssertionError(f"{role}单行在超时时间内未达到 {expected} 行，当前 {count} 行")
        return count

    def wait_child_rows_gone(self, timeout: int | None = None) -> None:
        """等待子行不可见（折叠后子行仍在 DOM 中，只是 display:none）。"""
        if not self.wait.wait_for_disappear(self.loc("child_row"), timeout or self.wait.timeout):
            raise AssertionError("收起后子单明细行仍然可见")

    # ---------------- 展开 / 收起 ---------------- #
    def expand_all(self, expect_children: int = 11, timeout: int | None = None) -> int:
        self.click("expand_all")
        return self.wait_row_count(self.CHILD_LEVEL, expect_children, timeout)

    def expand_parent(self, parent_id: str, timeout: int | None = None) -> int:
        self.row(parent_id, self.PARENT_LEVEL).locator(self.xpath("expand_icon")).first.click()
        deadline = time.time() + (timeout or self.wait.timeout)
        while time.time() < deadline:
            count = self.row_count(self.CHILD_LEVEL)
            if count > 0:
                return count
            self.page.wait_for_timeout(250)
        raise AssertionError(f"展开父单 {parent_id} 后子单明细行始终未渲染")

    def collapse_all(self, timeout: int | None = None) -> None:
        self.click("collapse_all")
        self.wait_child_rows_gone(timeout)

    def reset_data(self, expect_parents: int = 3, timeout: int | None = None) -> None:
        self.click("reset_btn")
        self.wait_row_count(self.PARENT_LEVEL, expect_parents, timeout)
        self.wait_child_rows_gone(timeout)

    # ---------------- 金额读取（文本 -> Decimal） ---------------- #
    def amount_text(self, row_id: str, level: int = CHILD_LEVEL) -> str:
        return self.row(row_id, level).locator(self.xpath("cell_amount")).first.inner_text().strip()

    def amount_of(self, row_id: str, level: int = CHILD_LEVEL) -> Decimal:
        return parse_amount(self.amount_text(row_id, level))

    def parent_state_text(self, parent_id: str) -> str:
        return (
            self.row(parent_id, self.PARENT_LEVEL)
            .locator(self.xpath("cell_state"))
            .first.inner_text()
            .strip()
        )

    def parent_child_total_text(self, parent_id: str) -> str:
        return (
            self.row(parent_id, self.PARENT_LEVEL)
            .locator(self.xpath("cell_child_total"))
            .first.inner_text()
            .strip()
        )

    def parent_child_total(self, parent_id: str) -> Decimal:
        return parse_amount(self.parent_child_total_text(parent_id))

    def summary_text(self, field: str) -> str:
        return self.text_of(f"summary_{field}")

    def summary_value(self, field: str) -> Decimal:
        return parse_amount(self.summary_text(field))

    # ---------------- 调整子单金额 + 等待后台重算 ---------------- #
    def adjust_child_amount(self, child_id: str, amount: str) -> None:
        row = self.row(child_id, self.CHILD_LEVEL)
        row.locator("xpath=.//button[contains(.,'调整')]").first.click()
        self.js_fill("edit_input", amount)
        self.click("save_btn")

    def wait_parent_state(self, parent_id: str, expect: str, timeout: int | None = None) -> str:
        deadline = time.time() + (timeout or self.wait.timeout)
        text = ""
        while time.time() < deadline:
            try:
                text = self.parent_state_text(parent_id)
                if expect in text:
                    self.logger.info("父单 %s 勾稽状态已刷新为: %s", parent_id, text)
                    return text
            except Exception:
                pass
            self.page.wait_for_timeout(250)
        raise AssertionError(
            f"父单 {parent_id} 勾稽状态在超时时间内未变为含「{expect}」的文本，当前: {text or '（未读取到）'}"
        )

    def wait_recalc_done(
        self, parent_id: str, expect_state: str = "金额一致", timeout: int | None = None
    ) -> str:
        timeout = timeout or self.wait.timeout
        self.assert_log(f"{parent_id} 重算完成", timeout=timeout)
        return self.wait_parent_state(parent_id, expect_state, timeout)


class I18Handle(BaseScenarioHandle):
    """页面数字 与 数据库一致性核对（SQLite 真实落库）。"""

    UNSETTLED_TEXT = "—"
    ACCOUNT_COLUMN = {"available": 3, "frozen": 4}

    def __init__(self, page: Page, timeout: int = 15):
        super().__init__(page, "I18", timeout)
        self.api = ApiClient()
        self.logger = get_logger()
        self._source: SqliteSource | None = None

    # ---------------- 页面：汇总卡与快照 ---------------- #
    def summary_text(self, field: str) -> str:
        return self.text_of(f"summary_{field}")

    def summary_value(self, field: str) -> Decimal:
        return parse_amount(self.summary_text(field))

    def summary_count(self) -> int:
        return int(self.summary_text("count").replace(",", "").strip())

    def snapshot_text(self) -> str:
        return self.text_of("snapshot")

    # ---------------- 页面：明细分页行 ---------------- #
    def detail_rows(self) -> list[Locator]:
        return self.page.locator(self.loc("detail_rows")).all()

    def row_xpath(self, item_no: str) -> str:
        return self.xpath("detail_row").format(item=item_no)

    def row(self, item_no: str) -> Locator:
        self.ensure_row_visible(item_no)
        return self.wait.wait_for_visible(f"xpath={self.row_xpath(item_no)}")

    def amount_text(self, item_no: str) -> str:
        return self.row(item_no).locator(self.xpath("cell_amount")).first.inner_text().strip()

    def amount_of(self, item_no: str) -> Decimal | None:
        text = self.amount_text(item_no)
        if text == self.UNSETTLED_TEXT:
            return None
        return parse_amount(text)

    def page_items(self) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        for row in self.detail_rows():
            try:
                item_no = row.locator("span.mono").first.inner_text().strip()
                amount = row.locator(self.xpath("cell_amount")).first.inner_text().strip()
            except Exception:
                continue
            items.append((item_no, amount))
        return items

    def page_count(self) -> int:
        return self.page.locator(self.loc("pager_numbers")).count()

    def active_page(self) -> int:
        return int(self.text_of("pager_active").strip())

    def wait_page_size(self, expect_rows: int, timeout: int | None = None) -> list[tuple[str, str]]:
        deadline = time.time() + (timeout or self.wait.timeout)
        items: list[tuple[str, str]] = []
        while time.time() < deadline:
            items = self.stable_page_items()
            if len(items) == expect_rows:
                return items
            self.page.wait_for_timeout(200)
        raise AssertionError(f"表格行数超时未达到 {expect_rows}，当前 {len(items)} 行")

    def stable_page_items(self, timeout: int | None = None) -> list[tuple[str, str]]:
        deadline = time.time() + (timeout or self.wait.timeout)
        last: list[tuple[str, str]] = []
        while time.time() < deadline:
            current = self.page_items()
            if current and current == last:
                return current
            last = current
            self.page.wait_for_timeout(150)
        raise AssertionError("明细表格在超时时间内未渲染稳定")

    def goto_page(
        self,
        no: int,
        expect_rows: int | None = None,
        timeout: int | None = None,
    ) -> list[tuple[str, str]]:
        before = [item for item, _ in self.page_items()]
        target = f"xpath={self.xpath('pager_item').format(no=no)}"
        self.wait.click_params(target)
        deadline = time.time() + (timeout or self.wait.timeout)
        items: list[tuple[str, str]] = []
        while time.time() < deadline:
            try:
                items = self.stable_page_items(timeout=max(1.0, deadline - time.time()))
            except AssertionError:
                continue
            changed = [item for item, _ in items] != before
            if changed and (expect_rows is None or len(items) == expect_rows):
                return items
            self.page.wait_for_timeout(200)
        raise AssertionError(f"第 {no} 页明细在超时时间内未刷新")

    def _page_contains(self, item_no: str) -> bool:
        return any(item == item_no for item, _ in self.page_items())

    def ensure_row_visible(self, item_no: str) -> int:
        if self._page_contains(item_no):
            return self.active_page()
        start = self.active_page()
        total = self.page_count()
        for offset in range(1, total + 1):
            no = (start - 1 + offset) % total + 1
            self.goto_page(no)
            if self._page_contains(item_no):
                return no
        raise AssertionError(f"全部 {total} 页中均未找到明细 {item_no}")

    def collect_all_details(self) -> dict[str, Decimal | None]:
        total = self.summary_count()
        pages = self.page_count()
        if self.active_page() != 1:
            self.goto_page(1)
        page_size = len(self.stable_page_items()) or total
        if pages > 1 and total > page_size:
            assert (total + page_size - 1) // page_size == pages, (
                f"页大小推导异常：共 {total} 条 / 每页 {page_size} 条，却显示 {pages} 页"
            )
        collected: dict[str, Decimal | None] = {}
        for no in range(1, pages + 1):
            expect_rows = max(1, min(page_size, total - (no - 1) * page_size))
            if self.active_page() == no:
                items = self.wait_page_size(expect_rows)
            else:
                items = self.goto_page(no, expect_rows)
            for item_no, text in items:
                collected[item_no] = None if text == self.UNSETTLED_TEXT else parse_amount(text)
        if self.active_page() != 1:
            self.goto_page(1, min(page_size, total))
        return collected

    # ---------------- 页面：资金账户 ---------------- #
    def account_row_xpath(self, account_no: str) -> str:
        return self.xpath("account_row").format(account=account_no)

    def account_amount_text(self, account_no: str, kind: str = "available") -> str:
        row = self.wait.wait_for_visible(f"xpath={self.account_row_xpath(account_no)}")
        cell_xpath = f"xpath={self.xpath('account_cell').format(idx=self.ACCOUNT_COLUMN[kind])}"
        return row.locator(cell_xpath).first.inner_text().strip()

    def account_amount(self, account_no: str, kind: str = "available") -> Decimal:
        return parse_amount(self.account_amount_text(account_no, kind))

    def account_numbers(self) -> list[str]:
        numbers = []
        for row in self.page.locator(self.loc("account_rows")).all():
            try:
                numbers.append(row.locator("span.mono").first.inner_text().strip())
            except Exception:
                continue
        return numbers

    # ---------------- 数据库：按「角色」动态挑选样本 ---------------- #
    @staticmethod
    def ROLE_UNSETTLED(row: dict) -> bool:
        return row["amount_cents"] is None

    @staticmethod
    def ROLE_NEGATIVE(row: dict) -> bool:
        return (row["amount_cents"] or 0) < 0

    def pick_detail(self, role: Callable[[dict], bool]) -> str:
        for row in self.db_rows("settle_detail"):
            if role(row):
                return row["item_no"]
        raise AssertionError(f"库中不存在符合角色 {getattr(role, '__name__', role)} 的明细样本")

    def pick_detail_in_matched_bill(self) -> tuple[str, str]:
        for bill in self.db_rows("settle_bill"):
            bill_no = bill["bill_no"]
            if bill["total_amount_cents"] != self.db_detail_sum_cents(bill_no):
                continue
            for row in self.db_rows("settle_detail", bill_no):
                if row["amount_cents"] is not None:
                    return row["item_no"], bill_no
        raise AssertionError("库中不存在「汇总字段与明细求和一致」的结算单")

    # ---------------- 页面异步刷新：轮询等待 ---------------- #
    def wait_page_decimal(
        self,
        reader: Callable[[], Decimal | None],
        expected: Decimal,
        timeout: int | None = None,
    ) -> Decimal:
        deadline = time.time() + (timeout or self.wait.timeout)
        actual: Decimal | None = None
        while time.time() < deadline:
            try:
                actual = reader()
            except Exception:
                actual = None
            if actual is not None and amount_equal(actual, expected):
                return actual
            self.page.wait_for_timeout(250)
        raise AssertionError(f"页面数字在超时时间内未刷新为 {expected}，当前: {actual}")

    def wait_detail_amount(self, item_no: str, expected: Decimal, timeout: int | None = None) -> Decimal:
        return self.wait_page_decimal(lambda: self.amount_of(item_no), expected, timeout)

    def wait_account_amount(
        self,
        account_no: str,
        expected: Decimal,
        kind: str = "available",
        timeout: int | None = None,
    ) -> Decimal:
        return self.wait_page_decimal(lambda: self.account_amount(account_no, kind), expected, timeout)

    # ---------------- 数据库：SQLite 直读 ---------------- #
    def source(self) -> SqliteSource:
        if self._source is None:
            meta = self.api.dbconsistency_meta()["data"]
            self._source = SqliteSource(meta["dbPath"])
        return self._source

    def db_rows(self, table: str, key: str | None = None) -> list[dict]:
        return self.source().rows(table, key)

    def db_detail(self, item_no: str) -> dict:
        for row in self.db_rows("settle_detail"):
            if row["item_no"] == item_no:
                return row
        raise AssertionError(f"数据库中不存在明细 {item_no}")

    def db_detail_cents(self, item_no: str) -> int | None:
        return self.db_detail(item_no)["amount_cents"]

    def db_detail_count(self) -> int:
        return len(self.db_rows("settle_detail"))

    def db_detail_sum_cents(self, bill_no: str | None = None) -> int:
        return sum((row["amount_cents"] or 0) for row in self.db_rows("settle_detail", bill_no))

    def db_bill_total_cents(self, bill_no: str) -> int:
        rows = self.db_rows("settle_bill", bill_no)
        if not rows:
            raise AssertionError(f"数据库中不存在结算单 {bill_no}")
        return rows[0]["total_amount_cents"]

    def db_bill_sum_cents(self) -> int:
        return sum(row["total_amount_cents"] for row in self.db_rows("settle_bill"))

    def db_account_cents(self, account_no: str, column: str = "available_cents") -> int:
        rows = self.db_rows("fund_account", account_no)
        if not rows:
            raise AssertionError(f"数据库中不存在资金账号 {account_no}")
        return rows[0][column]

    def db_available_sum_cents(self) -> int:
        return sum(row["available_cents"] for row in self.db_rows("fund_account"))

    def db_frozen_sum_cents(self) -> int:
        return sum(row["frozen_cents"] for row in self.db_rows("fund_account"))

    # ---------------- 数据库：轮询等待落库 ---------------- #
    def wait_db_equals(self, reader: Callable[[], object], expected, timeout: int | None = None):
        deadline = time.time() + (timeout or self.wait.timeout)
        actual = None
        while time.time() < deadline:
            try:
                actual = reader()
            except Exception:
                actual = None
            if actual == expected:
                return actual
            self.page.wait_for_timeout(250)
        raise AssertionError(f"数据库值在超时时间内未刷新为 {expected}，当前: {actual}")

    def wait_db_changed(self, reader: Callable[[], object], old_value, timeout: int | None = None):
        deadline = time.time() + (timeout or self.wait.timeout)
        actual = old_value
        while time.time() < deadline:
            try:
                actual = reader()
            except Exception:
                actual = old_value
            if actual != old_value:
                return actual
            self.page.wait_for_timeout(250)
        raise AssertionError(f"数据库值在超时时间内未发生变化，仍为 {old_value}")

    # ---------------- 页面操作 ---------------- #
    def refresh(self) -> str:
        self.click("refresh_btn")
        self.assert_log("已刷新数据快照")
        return self.snapshot_text()

    def reset_data(self) -> None:
        self.click("reset_btn")
        self.assert_log("数据库已重建")

    def adjust_detail(self, item_no: str, amount: str) -> None:
        row = self.row(item_no)
        row.locator(self.loc("row_adjust")).first.click()
        self.js_fill("edit_input", amount)
        row.locator(self.loc("row_save")).first.click()
        self.assert_log(f"提交明细 {item_no} 金额调整为")

    def recap_bill(self, item_no: str) -> None:
        self.row(item_no).locator(self.loc("row_recap")).first.click()

    def post_account(self) -> None:
        self.click("post_btn")
        self.assert_log("页面数据未自动刷新")

    # ---------------- 数据库查询弹窗 ---------------- #
    def open_db_dialog(self) -> str:
        self.click("open_db_btn")
        self.visible("dialog")
        self.wait.wait_for_presence(self.loc("db_rows"))
        return self.text_of("db_path")

    def query_db_table(self, table: str) -> int:
        act.el_select_by_text(self.page, self.loc("db_select"), table)
        self.click("db_query_btn")
        self.page.wait_for_timeout(600)
        deadline = time.time() + self.wait.timeout
        last = -1
        rows = 0
        while time.time() < deadline:
            rows = self.page.locator(self.loc("db_rows")).count()
            if rows > 0 and rows == last:
                return rows
            last = rows
            self.page.wait_for_timeout(200)
        raise AssertionError(f"数据库查询弹窗未渲染出 {table} 的查询结果，当前 {rows} 行")

    def close_db_dialog(self) -> None:
        self.click("dialog_close")
        if not self.wait.wait_for_disappear(self.loc("dialog")):
            raise AssertionError("数据库查询弹窗未能关闭")
