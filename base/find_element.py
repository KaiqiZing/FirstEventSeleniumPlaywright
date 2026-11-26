# coding=utf-8
"""元素定位解析器（Playwright 场景码注册版）。

读取 config/*Element.ini 并把 "by>value" 定位串解析为 Playwright Selector 字符串，
与浏览器对象解耦。每个场景码 (I01..E04) 映射到对应分组 INI 中的同名 Section。
INI 值格式：`css>.scene-card` 或 `xpath>//button[...]` 或 `=>//button[...]`（by 缺省=xpath）。
"""
from __future__ import annotations

from log.user_log import get_logger
from util.read_ini import ReadIni

# 场景码前缀 -> 分组 INI 文件（相对工程根目录）
GROUP_INI = {
    "I": "../config/InteractElement.ini",
    "W": "../config/WaitElement.ini",
    "M": "../config/WindowElement.ini",
    "C": "../config/CompatElement.ini",
    "X": "../config/MiscElement.ini",
    "E": "../config/CryptElement.ini",
}


def to_playwright_selector(by: str, value: str) -> str:
    """将 INI 的 (by, value) 转换为 Playwright Selector 字符串。"""
    norm = by.strip().lower().replace(" ", "_")
    val = value.strip()
    if norm in ("css", "css_selector", "tag", "tag_name"):
        return val
    if norm == "xpath":
        return f"xpath={val}"
    if norm == "id":
        return f'[id="{val}"]'
    if norm == "name":
        return f'[name="{val}"]'
    if norm in ("class", "class_name"):
        return f".{val}"
    if norm in ("text", "link_text"):
        return f'text="{val}"'
    if norm in ("partial", "partial_link_text"):
        return f"text={val}"
    return f"xpath={val}"


class FindElement:
    def __init__(self, page=None):
        # page 仅为兼容历史调用（self.fd = FindElement(page)），本类与 Page 对象解耦
        self.page = page
        self.logger = get_logger()

        self._ini_cache: dict[str, ReadIni] = {}
        self.locator_cache: dict[str, tuple[str, str]] = {}

    def _get_ini(self, module: str) -> ReadIni:
        prefix = str(module)[0].upper()
        ini_file = GROUP_INI.get(prefix)
        if not ini_file:
            raise ValueError(f"❌ 未知的场景码前缀: {module}")
        if prefix not in self._ini_cache:
            self._ini_cache[prefix] = ReadIni(ini_file)
        return self._ini_cache[prefix]

    def _parse_locator(self, key: str, module: str) -> tuple[str, str]:
        """安全解析定位信息并缓存。node/section 名 = 场景码本身。"""
        cache_key = f"{module}_{key}"
        if cache_key in self.locator_cache:
            return self.locator_cache[cache_key]

        ini_instance = self._get_ini(module)
        try:
            data = ini_instance.get_value(key=key, node=module)
        except ValueError as e:
            self.logger.error(str(e))
            raise

        parts = data.split(">", 1)
        if len(parts) == 2:
            by, value = parts[0].strip(), parts[1].strip()
            if by == "":
                by = "xpath"
        else:
            by, value = "xpath", data.strip()

        by = by.lower().replace(" ", "_")
        self.locator_cache[cache_key] = (by, value)
        return by, value

    def get_text(self, key: str, module: str) -> str:
        """获取未加前缀的原始定位串（用于 .format(...) 拼接或局部子定位）。"""
        _by, value = self._parse_locator(key, module)
        return value if value else ""

    def get_locator(self, key: str, module: str) -> str:
        """获取 Playwright Selector 字符串（css 直接返回，xpath 自动带 xpath= 前缀）。"""
        by, value = self._parse_locator(key, module)
        return to_playwright_selector(by, value)

    def clear_cache(self) -> None:
        """清除定位器缓存。"""
        self.locator_cache.clear()
