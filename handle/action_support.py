"""被测平台通用动作支持层（Playwright 版）。

把跨场景的浏览器/页面级平台动作收敛在此，供各场景 handle 复用：
原生弹窗 dialog 前置监听、hover、HTML5 拖拽、文件上传、contenteditable、
内部滚动容器、Vue v-model 原生 setter、Element Plus 浮层等。
"""
from __future__ import annotations

from typing import Any, Callable

from playwright.sync_api import Dialog, Locator, Page, TimeoutError as PlaywrightTimeoutError

from common.page_wait_common import PageWaitCommon, resolve_selector
from log.user_log import get_logger

logger = get_logger()


def _to_locator(page: Page, target: Any) -> Locator:
    if isinstance(target, Locator):
        return target
    return page.locator(resolve_selector(target))


# --------------------------------------------------------------------------- #
# 原生 JS 弹窗 alert / confirm / prompt（Playwright 必须前置注册监听）
# --------------------------------------------------------------------------- #
def handle_dialog_on(
    page: Page,
    trigger: Callable[[], Any],
    *,
    accept: bool = True,
    prompt_text: str | None = None,
) -> str:
    """在触发动作之前注册一次性 dialog 监听器，返回弹窗提示文案。

    注意：Playwright 在未监听 dialog 时会自动 dismiss，因此必须在点击前注册。
    """
    captured: list[str] = []

    def _on_dialog(dialog: Dialog) -> None:
        captured.append(dialog.message)
        if accept:
            if prompt_text is not None:
                dialog.accept(prompt_text)
            else:
                dialog.accept()
        else:
            dialog.dismiss()

    page.once("dialog", _on_dialog)
    trigger()
    return captured[0] if captured else ""


def accept_dialog_on(page: Page, trigger: Callable[[], Any], prompt_text: str | None = None) -> str:
    return handle_dialog_on(page, trigger, accept=True, prompt_text=prompt_text)


def dismiss_dialog_on(page: Page, trigger: Callable[[], Any]) -> str:
    return handle_dialog_on(page, trigger, accept=False)


# --------------------------------------------------------------------------- #
# hover / HTML5 拖拽 / 文件上传 / contenteditable / 滚动容器
# --------------------------------------------------------------------------- #
def hover(page: Page, element_or_locator: Any, timeout: int = 10) -> None:
    """悬停到元素上展开菜单。"""
    target = _to_locator(page, element_or_locator).first
    target.wait_for(state="visible", timeout=timeout * 1000)
    target.hover(timeout=timeout * 1000)


def drag_and_drop(page: Page, source: Any, target: Any, timeout: int = 10) -> None:
    """HTML5 拖拽（Playwright 原生触发 dragstart/dragover/drop）。"""
    src = _to_locator(page, source).first
    dst = _to_locator(page, target).first
    src.wait_for(state="attached", timeout=timeout * 1000)
    dst.wait_for(state="attached", timeout=timeout * 1000)
    src.drag_to(dst, timeout=timeout * 1000)


def upload_file(page: Page, file_input_locator: Any, abs_path: str, timeout: int = 10) -> None:
    """文件上传：对隐藏 input[type=file] 直接 set_input_files 本地绝对路径。"""
    el = _to_locator(page, file_input_locator).first
    el.wait_for(state="attached", timeout=timeout * 1000)
    el.set_input_files(abs_path)


def fill_contenteditable(page: Page, locator: Any, text: str, timeout: int = 10) -> None:
    """富文本 contenteditable：点击聚焦并写入正文。"""
    el = _to_locator(page, locator).first
    el.wait_for(state="visible", timeout=timeout * 1000)
    el.click(timeout=timeout * 1000)
    el.fill(text)


def scroll_container_to_bottom(page: Page, container_locator: Any, timeout: int = 10) -> None:
    """内部滚动容器滚到底部，触发懒加载。"""
    el = _to_locator(page, container_locator).first
    el.wait_for(state="attached", timeout=timeout * 1000)
    el.evaluate("el => { el.scrollTop = el.scrollHeight; }")


def element_in_viewport(page: Page, locator: Any) -> bool:
    """判断元素是否已渲染到视口内。"""
    try:
        el = _to_locator(page, locator).first
        return bool(
            el.evaluate(
                "el => { const r = el.getBoundingClientRect(); "
                "return r.top < window.innerHeight && r.bottom > 0; }"
            )
        )
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Vue v-model 可靠输入：原生 value setter + input/change 事件
# --------------------------------------------------------------------------- #
def set_input_value(locator: Locator, value: str) -> None:
    """通过原生 value setter 写入并派发 input/change 事件，确保 Vue v-model 与原生日期控件同步。"""
    locator.evaluate(
        """(el, val) => {
            const proto = el.tagName === 'TEXTAREA'
                ? window.HTMLTextAreaElement.prototype
                : window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
            setter.call(el, val);
            el.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        str(value),
    )


def set_input_value_by_locator(page: Page, locator: Any, value: str, timeout: int = 10) -> None:
    el = _to_locator(page, locator).first
    el.wait_for(state="attached", timeout=timeout * 1000)
    set_input_value(el, value)


# --------------------------------------------------------------------------- #
# Element Plus 公共控件动作
# --------------------------------------------------------------------------- #
def click_el_checkbox_by_text(page: Page, text: str, timeout: int = 10) -> None:
    """按 label 文本点击 el-checkbox。"""
    selector = f"xpath=//label[contains(@class,'el-checkbox')][contains(.,'{text}')]"
    page.locator(selector).first.click(timeout=timeout * 1000)


def click_el_radio_by_text(page: Page, text: str, timeout: int = 10) -> None:
    selector = f"xpath=//label[contains(@class,'el-radio-button')][contains(.,'{text}')]"
    page.locator(selector).first.click(timeout=timeout * 1000)


def click_el_option(page: Page, option_text: str, timeout: int = 10) -> None:
    """点击已展开的 el-select 浮层选项（过滤可见浮层，避免命中其他隐藏 popper）。"""
    selector = f"xpath=//li[contains(@class,'el-select-dropdown__item')][contains(.,'{option_text}')]"
    target = page.locator(selector).locator("visible=true").first
    target.wait_for(state="visible", timeout=timeout * 1000)
    target.click(timeout=timeout * 1000)


def el_select_by_text(page: Page, trigger_locator: Any, option_text: str, timeout: int = 10) -> None:
    """打开 el-select 并选择选项文本。"""
    _to_locator(page, trigger_locator).first.click(timeout=timeout * 1000)
    click_el_option(page, option_text, timeout=timeout)


def wait_loading_mask_gone(page: Page, mask_locator: Any, timeout: int = 15) -> bool:
    """等待 loading 遮罩全部消失。"""
    return PageWaitCommon(page, timeout).wait_for_disappear(mask_locator, timeout=timeout)


def click_with_js(locator: Locator) -> None:
    locator.evaluate("el => el.click()")


def wait_for_new_page_after_click(page: Page, current_url: str, timeout: int = 15) -> bool:
    try:
        page.wait_for_url(lambda url: url != current_url, timeout=timeout * 1000)
        return True
    except PlaywrightTimeoutError:
        return False
