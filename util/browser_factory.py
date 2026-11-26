"""统一 Playwright Browser / BrowserContext / Page 创建工厂。"""
from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright

from common.exceptions import ConfigError
from config.settings import Config
from log.user_log import get_logger


class BrowserFactory:
    logger = get_logger()

    #: 浏览器别名归一（360/QQ -> chromium，msedge -> edge，safari -> webkit）。
    BROWSER_ALIASES = {
        "360": "chromium",
        "360se": "chromium",
        "360chrome": "chromium",
        "qq": "chromium",
        "qqbrowser": "chromium",
        "msedge": "edge",
        "safari": "webkit",
    }

    SUPPORTED_BROWSERS = ("chromium", "chrome", "edge", "firefox", "webkit")

    @staticmethod
    def _project_dir() -> Path:
        return Path(__file__).resolve().parent.parent

    @staticmethod
    def resolve_download_dir() -> Path | None:
        cfg = Config()
        raw = cfg.get("browser.download_dir", "downloads")
        if not raw:
            return None
        path = BrowserFactory._project_dir() / str(raw).strip()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def resolve_trace_dir() -> Path:
        cfg = Config()
        raw = cfg.get("trace.path", "logs/traces")
        path = BrowserFactory._project_dir() / str(raw).strip()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def resolve_browser_name(browser_type: str | None = None) -> str:
        cfg = Config()
        browser_cfg = cfg.get("browser", {}) or {}
        name = str(browser_type or browser_cfg.get("type", "chromium")).strip().lower()
        if name in BrowserFactory.BROWSER_ALIASES:
            alias = name
            name = BrowserFactory.BROWSER_ALIASES[alias]
            BrowserFactory.logger.info("浏览器类型 %s 归一化为 %s", alias, name)
        if name not in BrowserFactory.SUPPORTED_BROWSERS:
            raise ConfigError(
                "不支持的浏览器类型，可选: " + "/".join(BrowserFactory.SUPPORTED_BROWSERS)
                + "（360/qq 自动归一为 chromium，safari 自动归一为 webkit）",
                config_key="browser.type",
                config_file=str(cfg.settings_file),
            )
        return name

    @staticmethod
    def _resolve_headless(headless: bool | None = None) -> bool:
        browser_cfg = Config().get("browser", {}) or {}
        return bool(browser_cfg.get("headless", False) if headless is None else headless)

    @staticmethod
    def _resolve_executable_path(browser_cfg: dict[str, Any]) -> str | None:
        for key in ("executable_path", "binary_path"):
            raw = browser_cfg.get(key, "")
            if raw and str(raw).strip():
                return str(raw).strip()
        return None

    @staticmethod
    def launch_browser(
        playwright: Playwright,
        browser_type: str | None = None,
        headless: bool | None = None,
    ) -> Browser:
        """启动 Playwright Browser（建议 session 级复用，配合 function 级 Context 隔离）。

        红线说明：不注入 `--disable-blink-features=AutomationControlled` 或反检测脚本，
        保证 X-02 / C-02 对 navigator.webdriver 的检测结果真实可观测。
        """
        cfg = Config()
        browser_cfg = cfg.get("browser", {}) or {}
        browser_name = BrowserFactory.resolve_browser_name(browser_type)
        use_headless = BrowserFactory._resolve_headless(headless)
        slow_mo = int(browser_cfg.get("slow_mo", 0) or 0)
        maximize = bool(browser_cfg.get("maximize_window", False))
        download_dir = BrowserFactory.resolve_download_dir()

        launch_kwargs: dict[str, Any] = {
            "headless": use_headless,
        }
        if slow_mo > 0:
            launch_kwargs["slow_mo"] = slow_mo
        if download_dir:
            launch_kwargs["downloads_path"] = str(download_dir)

        if browser_name in ("chromium", "chrome", "edge"):
            args: list[str] = []
            if platform.system() == "Linux":
                args.extend(["--no-sandbox", "--disable-dev-shm-usage"])
            if maximize and not use_headless:
                args.append("--start-maximized")
            if args:
                launch_kwargs["args"] = args

            exec_path = BrowserFactory._resolve_executable_path(browser_cfg)
            if browser_name == "chromium":
                if exec_path:
                    launch_kwargs["executable_path"] = exec_path
                    BrowserFactory.logger.info("Chromium executable_path: %s", exec_path)
                    browser = playwright.chromium.launch(**launch_kwargs)
                else:
                    try:
                        browser = playwright.chromium.launch(**launch_kwargs)
                    except Exception as exc:
                        if "Executable doesn't exist" not in str(exc):
                            raise
                        BrowserFactory.logger.warning(
                            "未检测到匹配版本的 Playwright 内置 Chromium，尝试回退使用本机 Chrome/Edge 通道"
                        )
                        browser = None
                        for fallback_channel in ("chrome", "msedge"):
                            try:
                                browser = playwright.chromium.launch(
                                    channel=fallback_channel, **launch_kwargs
                                )
                                BrowserFactory.logger.info(
                                    "已回退至本机浏览器通道: channel=%s", fallback_channel
                                )
                                break
                            except Exception:
                                continue
                        if browser is None:
                            raise
            elif browser_name == "chrome":
                launch_kwargs["channel"] = "chrome"
                browser = playwright.chromium.launch(**launch_kwargs)
            elif browser_name == "edge":
                launch_kwargs["channel"] = "msedge"
                browser = playwright.chromium.launch(**launch_kwargs)
        elif browser_name == "firefox":
            browser = playwright.firefox.launch(**launch_kwargs)
        else:
            browser = playwright.webkit.launch(**launch_kwargs)

        BrowserFactory.logger.info(
            "Playwright 浏览器已启动: type=%s, headless=%s", browser_name, use_headless
        )
        return browser

    @staticmethod
    def create_context(
        browser: Browser,
        browser_type: str | None = None,
        headless: bool | None = None,
    ) -> BrowserContext:
        """创建隔离的 BrowserContext（独立 Cookie / Storage / 下载与弹窗上下文）。"""
        cfg = Config()
        browser_cfg = cfg.get("browser", {}) or {}
        env_cfg = cfg.get_env_config()
        browser_name = BrowserFactory.resolve_browser_name(browser_type)
        use_headless = BrowserFactory._resolve_headless(headless)
        maximize = bool(browser_cfg.get("maximize_window", False))
        viewport_cfg = browser_cfg.get("viewport") or browser_cfg.get("window_size") or [1920, 1080]

        ctx_kwargs: dict[str, Any] = {
            "accept_downloads": True,
        }
        if maximize and not use_headless and browser_name in ("chromium", "chrome", "edge"):
            ctx_kwargs["no_viewport"] = True
        elif isinstance(viewport_cfg, (list, tuple)) and len(viewport_cfg) == 2:
            ctx_kwargs["viewport"] = {
                "width": int(viewport_cfg[0]),
                "height": int(viewport_cfg[1]),
            }

        context = browser.new_context(**ctx_kwargs)

        default_timeout = int(
            browser_cfg.get("action_timeout", env_cfg.get("timeout", 15)) or 15
        )
        nav_timeout = int(browser_cfg.get("navigation_timeout", 30) or 30)
        context.set_default_timeout(default_timeout * 1000)
        context.set_default_navigation_timeout(nav_timeout * 1000)
        return context

    @staticmethod
    def create_page(context: BrowserContext) -> Page:
        return context.new_page()
