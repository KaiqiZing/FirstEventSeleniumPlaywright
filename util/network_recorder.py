"""浏览器真实网络层记录（Playwright 原生事件版）：全浏览器内核通用。

背景：页面 DOM 上的报文区（如 E-01 的 `#request-body`）与摘要区都是**前端自证**，
前端伪造一份假密文照样能显示。本模块通过 Playwright 原生 `page.on("response")`
监听浏览器网络栈真实收发的请求体与响应体，支持 Chromium / Firefox / WebKit 全内核，
不再依赖 Chromium 专属的 CDP 或 `performance` 日志缓冲。

对外接口与原 Selenium CDP 版完全一致（start / stop / clear / records / wait_record /
try_wait_record / last_record / get_network_recorder），用例侧零侵入。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from playwright.sync_api import Page, Response

from log.user_log import get_logger


class NetworkRecorder:
    """按 URL 抓取浏览器真实收发的请求体 / 响应体（全浏览器通用）。"""

    def __init__(self, page: Page, timeout: int = 10):
        self.page = page
        self.timeout = timeout
        self.logger = get_logger()
        self._enabled = False
        self._records: list[dict[str, Any]] = []

    # ---------------- 生命周期 ---------------- #
    @property
    def supported(self) -> bool:
        """Playwright 原生网络事件在 Chromium / Firefox / WebKit 均可用。"""
        if os.environ.get("UIEVENT_DISABLE_PERF_LOG"):
            return False
        return hasattr(self.page, "on")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _on_response(self, response: Response) -> None:
        if not self._enabled:
            return
        url = response.url or ""
        req = response.request
        resource_type = getattr(req, "resource_type", "")
        # 仅抓取接口/XHR/Fetch 请求，跳过静态 JS/CSS/图片，避免无谓读取大响应体
        if resource_type not in ("fetch", "xhr") and "/api/" not in url:
            return

        post_data = req.post_data
        body: str | None = None
        try:
            body = response.text()
        except Exception as exc:
            self.logger.debug("响应体不可读 %s: %s", url, exc)

        self._records.append(
            {
                "url": url,
                "method": req.method,
                "status": response.status,
                "mimeType": response.headers.get("content-type"),
                "postData": post_data,
                "body": body,
                "req_json": self._safe_json(post_data),
                "resp_json": self._safe_json(body),
                "finished": True,
            }
        )

    def start(self) -> bool:
        """开始监听网络响应并清空历史记录，返回是否可用。"""
        if not self.supported:
            self.logger.warning("网络层记录已关闭或当前对象不支持事件监听，跳过网络层断言")
            return False
        if self._enabled:
            self._records.clear()
            return True
        self._records.clear()
        self.page.on("response", self._on_response)
        self._enabled = True
        return True

    def stop(self) -> None:
        """停止监听并移除回调。"""
        if not self._enabled:
            return
        try:
            self.page.remove_listener("response", self._on_response)
        except Exception as exc:
            self.logger.debug("移除 response 监听失败（page 可能已关闭）: %s", exc)
        self._enabled = False

    def clear(self) -> None:
        """清空已捕获记录（同一用例内分阶段比对时使用）。"""
        self._records.clear()

    @staticmethod
    def _safe_json(raw: str | None) -> Any:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    # ---------------- 取数 ---------------- #
    def records(self, url_contains: str) -> list[dict[str, Any]]:
        """返回 URL 命中的全部记录，按响应到达顺序排列。"""
        return [item for item in self._records if url_contains in (item.get("url") or "")]

    def wait_record(self, url_contains: str, timeout: int | None = None) -> dict[str, Any]:
        """等待命中 URL 的第一条记录；超时抛 AssertionError。"""
        if not self._enabled:
            raise AssertionError("网络层记录未开启或已禁用")
        wait_sec = timeout or self.timeout
        deadline = time.time() + wait_sec
        while time.time() < deadline:
            items = self.records(url_contains)
            if items:
                return items[0]
            # 使用 page.wait_for_timeout 泵动 Playwright 事件循环，确保回调及时触发
            self.page.wait_for_timeout(200)
        raise AssertionError(f"未在 {wait_sec}s 内捕获请求: {url_contains}")

    def try_wait_record(self, url_contains: str, timeout: int | None = None) -> dict[str, Any] | None:
        """降级版：抓不到只告警并返回 None，不阻断用例。"""
        try:
            return self.wait_record(url_contains, timeout)
        except AssertionError as exc:
            if self._enabled:
                self.logger.warning("未捕获到网络请求，跳过网络层断言: %s", exc)
            return None

    def last_record(self, url_contains: str) -> dict[str, Any] | None:
        """命中 URL 的最后一条记录。"""
        items = self.records(url_contains)
        return items[-1] if items else None


_CACHE: dict[int, NetworkRecorder] = {}


def get_network_recorder(page: Page) -> NetworkRecorder:
    """取与 page 绑定的共享记录器。"""
    key = id(page)
    rec = _CACHE.get(key)
    if rec is None or rec.page is not page:
        rec = NetworkRecorder(page)
        _CACHE[key] = rec
    return rec
