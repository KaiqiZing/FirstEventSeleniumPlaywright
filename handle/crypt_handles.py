"""数据加密类（E-01~E-04）场景操作层（Playwright 版）。

四个场景的共同口径：**页面上能看到的都不是可信断言源**。
"""
from __future__ import annotations

import json
import time
from decimal import Decimal

from playwright.sync_api import Locator, Page

from handle import action_support as act
from handle.base_scenario_handle import BaseScenarioHandle
from log.user_log import get_logger
from util.amount_util import parse_amount
from util.api_client import ApiClient
from util.digest_util import password_digest
from util.network_recorder import get_network_recorder
from util.sqlite_source import SqliteSource


class E01Handle(BaseScenarioHandle):
    """传输字段加密（RSA-OAEP）：公钥异步签发 + 密文随机 + 明文通道被拒。"""

    NOT_READY = "—"
    KEY_READY = "密钥已就绪"
    PLAIN_REJECTED = "明文提交失败"
    ENCRYPT_FAILED = "加密提交失败"

    ENC_URL = "/api/crypto/login/encrypted"
    PLAIN_URL = "/api/crypto/login/plain"

    DIGEST_MATCHED = "一致"
    DIGEST_MISMATCHED = "不一致"
    DIGEST_NOT_COMPARED = "未比对"
    PLACEHOLDER = "—"

    def __init__(self, page: Page, timeout: int = 15):
        super().__init__(page, "E01", timeout)
        self.api = ApiClient()
        self.logger = get_logger()
        # 网络层记录器（按 page 共享）：Playwright 全内核支持
        self.net = get_network_recorder(page)

    # ---------------- 公钥（异步资源） ---------------- #
    def web_crypto_available(self) -> bool:
        """当前页面是否处于安全上下文并具备 Web Crypto（RSA-OAEP / SHA-256）。"""
        try:
            return bool(
                self.page.evaluate(
                    "() => !!(window.crypto && window.crypto.subtle && window.isSecureContext)"
                )
            )
        except Exception:
            return False

    def wait_pubkey_ready(self, timeout: int | None = None) -> str:
        deadline = time.time() + (timeout or self.wait.timeout)
        fingerprint = ""
        while time.time() < deadline:
            fingerprint = self.fingerprint()
            if fingerprint and fingerprint != self.NOT_READY:
                self.logger.info("通道公钥就绪，指纹: %s", fingerprint)
                return fingerprint
            self.page.wait_for_timeout(200)
        raise AssertionError(
            f"公钥在 {timeout or self.wait.timeout}s 内未签发完成，当前指纹: {fingerprint or '（空）'}"
        )

    def fingerprint(self) -> str:
        try:
            return self.text_of("fingerprint").strip()
        except Exception:
            return ""

    def state_text(self) -> str:
        return self.text_of("state_tag").strip()

    def wait_state_settled(self, expected: str | None = None, timeout: int | None = None) -> str:
        """等待状态标签过渡动画收敛并变为期望值后再取文本。"""
        deadline = time.time() + (timeout or self.wait.timeout)
        texts: list[str] = []
        locator = self.page.locator(self.loc("state_tag"))
        while time.time() < deadline:
            try:
                texts = locator.evaluate_all(
                    """els => els
                        .filter(el => {
                            const style = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            return style.display !== 'none'
                                && style.visibility !== 'hidden'
                                && parseFloat(style.opacity || '1') > 0
                                && rect.width > 0 && rect.height > 0;
                        })
                        .map(el => (el.innerText || '').trim())
                        .filter(Boolean)"""
                )
            except Exception:
                texts = []
            if len(texts) == 1 and (expected is None or texts[0] == expected):
                return texts[0]
            self.page.wait_for_timeout(200)
        raise AssertionError(
            f"状态标签未收敛为「{expected}」（可能仍在过渡动画中），当前: {texts}"
            if expected
            else f"状态标签未在超时时间内收敛（可能仍在过渡动画中），当前: {texts}"
        )

    def wait_fingerprint_changed(self, before: str, timeout: int | None = None) -> str:
        deadline = time.time() + (timeout or self.wait.timeout)
        current = before
        while time.time() < deadline:
            current = self.fingerprint()
            if current and current != before:
                return current
            self.page.wait_for_timeout(200)
        raise AssertionError(f"重新签发后公钥指纹未变化，仍为: {current or '（空）'}")

    def reload_pubkey(self, timeout: int | None = None) -> str:
        before = self.fingerprint()
        self.click("reload_pubkey")
        self.assert_log("通道公钥就绪", timeout)
        return self.wait_fingerprint_changed(before, timeout)

    # ---------------- 表单提交 ---------------- #
    def fill_credentials(self, account: str, password: str) -> None:
        self.js_fill("account", account)
        self.js_fill("password", password)

    def submit_encrypted(self) -> None:
        self.click("submit_encrypted")

    def submit_plain(self) -> None:
        self.click("submit_plain")

    def wait_submit_success(self, password: str, timeout: int | None = None) -> str:
        self.assert_log(
            "服务端解密成功",
            timeout,
            extra="；加密提交是否成功应以服务端解密结果为准",
        )
        expect = password_digest(password)
        self.wait_server_digest(expect, timeout)
        verdict = self.wait_digest_settled(timeout)
        if verdict == self.DIGEST_NOT_COMPARED:
            self.logger.warning("当前为非安全上下文，前端未做本地摘要比对，仅校验服务端摘要")
            return expect
        assert self.local_digest().upper() == expect, (
            f"前端本地摘要与脚本复算不一致: {self.local_digest()} != {expect}"
        )
        assert verdict == self.DIGEST_MATCHED, (
            f"摘要比对结论应为「{self.DIGEST_MATCHED}」，实际: {verdict}"
        )
        return expect

    # ---------------- 摘要比对区 ---------------- #
    def _text_or_empty(self, key: str) -> str:
        try:
            value = self.text_of(key).strip()
        except Exception:
            return ""
        return "" if value == self.PLACEHOLDER else value

    def server_digest(self) -> str:
        return self._text_or_empty("server_digest")

    def local_digest(self) -> str:
        return self._text_or_empty("local_digest")

    def digest_match(self) -> str:
        return self._text_or_empty("digest_match")

    def masked_password(self) -> str:
        return self._text_or_empty("masked_password")

    def wait_server_digest(self, expect: str, timeout: int | None = None) -> str:
        deadline = time.time() + (timeout or self.wait.timeout)
        current = ""
        while time.time() < deadline:
            current = self.server_digest()
            if current and current.upper() == expect.upper():
                return current
            self.page.wait_for_timeout(200)
        raise AssertionError(
            f"服务端摘要未刷新为期望值 {expect}，当前: {current or '（空）'}"
        )

    def wait_digest_settled(self, timeout: int | None = None) -> str:
        deadline = time.time() + (timeout or self.wait.timeout)
        verdict = ""
        while time.time() < deadline:
            verdict = self.digest_match()
            if verdict in (self.DIGEST_MATCHED, self.DIGEST_MISMATCHED, self.DIGEST_NOT_COMPARED):
                return verdict
            self.page.wait_for_timeout(200)
        raise AssertionError(f"摘要比对结论未渲染出终态，当前: {verdict or '（空）'}")

    def wait_digest_cleared(self, timeout: int | None = None) -> None:
        deadline = time.time() + (timeout or self.wait.timeout)
        while time.time() < deadline:
            if not (self.server_digest() or self.local_digest()):
                return
            self.page.wait_for_timeout(200)
        raise AssertionError(
            f"明文提交后摘要区未清空，仍残留: 服务端 {self.server_digest() or '（空）'}"
            f" / 本地 {self.local_digest() or '（空）'}"
        )

    # ---------------- 报文 ---------------- #
    def request_body(self) -> str:
        return self.text_of("request_body")

    def request_payload(self) -> dict:
        try:
            return json.loads(self.request_body())
        except (ValueError, TypeError):
            return {}

    def credential_b64(self) -> str:
        return str(self.request_payload().get("credentialB64") or "")

    def wait_request_body_ready(self, timeout: int | None = None) -> str:
        deadline = time.time() + (timeout or self.wait.timeout)
        body = ""
        while time.time() < deadline:
            body = self.request_body()
            if "credentialB64" in body:
                return body
            self.page.wait_for_timeout(200)
        raise AssertionError(f"报文区在超时时间内未出现 credentialB64 字段，当前: {body or '（空）'}")

    def wait_request_body_changed(self, before: str, timeout: int | None = None) -> str:
        deadline = time.time() + (timeout or self.wait.timeout)
        body = before
        while time.time() < deadline:
            body = self.request_body()
            if body and body != before:
                return body
            self.page.wait_for_timeout(200)
        raise AssertionError("重复提交后报文内容未刷新，无法验证密文随机性")

    # ---------------- 密钥轮换 ---------------- #
    def rotate_pubkey_by_api(self) -> str:
        body = self.api.crypto_pubkey_rotate()
        self.logger.info("服务端已轮换 RSA 密钥对: %s", body.get("data"))
        return str(body.get("data", {}).get("fingerprint") or "")


class E02Handle(BaseScenarioHandle):
    """敏感字段脱敏展示：页面只有掩码，完整值需单独申请且限时可见。"""

    UNREGISTERED = "—"
    MASK_SIGN = "****"

    def __init__(self, page: Page, timeout: int = 15):
        super().__init__(page, "E02", timeout)
        self.api = ApiClient()
        self.logger = get_logger()

    # ---------------- 列表（掩码） ---------------- #
    def refresh_list(self) -> None:
        self.click("refresh_btn")
        self.assert_log("档案列表已刷新")

    def rows(self) -> list[Locator]:
        return self.page.locator(self.loc("cust_row")).all()

    def row(self, cust_id: int) -> Locator:
        return self.wait.wait_for_visible(self.xpath("row_by_id").format(id=cust_id))

    def cell_text(self, cust_id: int, field: str) -> str:
        return self.row(cust_id).locator(self.xpath(f"cell_{field}")).first.inner_text().strip()

    def data_raw(self, cust_id: int) -> str | None:
        return self.row(cust_id).locator(self.xpath("cell_mobile")).first.get_attribute("data-raw")

    def cust_ids(self) -> list[int]:
        rows = self.api.crypto_masked_customers().get("data", {}).get("rows", [])
        return [int(r["id"]) for r in rows]

    # ---------------- 抽屉：限时查看明文 ---------------- #
    def click_reveal(self, cust_id: int) -> None:
        self.wait.click_params(self.xpath("reveal_btn").format(id=cust_id))

    def reveal(self, cust_id: int) -> None:
        self.click_reveal(cust_id)
        self.wait.wait_for_visible(self.loc("reveal_mobile"))

    def revealed_text(self, field: str) -> str:
        return self.text_of(f"reveal_{field}").strip()

    def countdown(self) -> int:
        try:
            return int(self.text_of("reveal_countdown").strip())
        except ValueError:
            return 0

    def close_drawer(self) -> None:
        try:
            self.click("drawer_close")
            return
        except Exception:
            self.logger.info("关闭按钮不可用，改用 ESC 关闭抽屉")
        self.page.keyboard.press("Escape")

    def wait_auto_collapsed(self, cust_no: str, timeout: int | None = None) -> None:
        self.assert_log(f"{cust_no} 的敏感信息已自动收起", timeout or 12)

    def wait_cooldown_rejected(self, cust_no: str, timeout: int | None = None) -> None:
        self.assert_log(f"查看客户 {cust_no} 失败", timeout)

    # ---------------- 服务端原始数据 ---------------- #
    def export_server_raw(self) -> dict[str, str]:
        self.click("raw_btn")
        self.assert_log("已取服务端原始数据")
        return self.raw_table_map()

    def raw_table_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for row in self.page.locator(self.loc("raw_row")).all():
            try:
                cust_no = row.locator("td:nth-child(1)").first.inner_text().strip()
                mobile = row.locator(self.xpath("raw_mobile")).first.inner_text().strip()
            except Exception:
                continue
            out[cust_no] = mobile
        return out

    def server_raw_map(self) -> dict[str, dict]:
        rows = self.api.crypto_masked_raw().get("data", {}).get("rows", [])
        return {r["custNo"]: r for r in rows}


class E03Handle(BaseScenarioHandle):
    """密文存储核对（AES-256-GCM 真实落库）：页面是解密结果，库里是密文。"""

    COL_CUST_NO = 1
    COL_CUST_NAME = 2
    COL_MOBILE = 3
    COL_IDCARD = 4
    COL_BALANCE = 5
    COL_KEY_VERSION = 6

    FAIL_TEXT = "解密失败"
    NULL_TEXT = "—"
    REVOKED_VERSION = "K0"

    def __init__(self, page: Page, timeout: int = 15):
        super().__init__(page, "E03", timeout)
        self.api = ApiClient()
        self.logger = get_logger()
        self._source: SqliteSource | None = None

    # ---------------- 库表直读 ---------------- #
    @property
    def source(self) -> SqliteSource:
        if self._source is None:
            meta = self.api.crypto_vault_db_meta().get("data", {})
            self._source = SqliteSource(meta["dbPath"])
        return self._source

    def db_rows(self) -> list[dict]:
        return self.source.rows("cust_profile")

    def db_row(self, cust_no: str) -> dict:
        for row in self.db_rows():
            if row["cust_no"] == cust_no:
                return row
        raise AssertionError(f"密文库中未找到客户 {cust_no}")

    def db_meta(self) -> dict:
        return self.api.crypto_vault_db_meta().get("data", {})

    def pick_row(self, key_version: str, field: str = "mobile_enc") -> dict:
        for row in self.db_rows():
            if row["key_version"] == key_version and row.get(field):
                return row
        raise AssertionError(f"密文库中没有「密钥版本={key_version} 且 {field} 非空」的样本行")

    def current_key_version(self) -> str:
        return str(self.db_meta().get("currentKeyVersion") or "")

    def decrypt_by_api(self, cipher_b64: str, iv_b64: str, key_version: str | None = None) -> dict:
        return self.api.crypto_vault_decrypt(cipher_b64, iv_b64, key_version)

    # ---------------- 页面（解密后的明文） ---------------- #
    def vault_rows(self) -> list[Locator]:
        return self.page.locator(self.loc("vault_row")).all()

    def _td_text(self, row: Locator, col: int) -> str:
        return row.locator(f"td:nth-child({col})").first.inner_text().strip()

    def row_cust_nos(self) -> list[str]:
        cust_nos: list[str] = []
        for row in self.vault_rows():
            try:
                cust_nos.append(self._td_text(row, self.COL_CUST_NO))
            except Exception:
                continue
        return cust_nos

    def wait_rows_loaded(self, timeout: int | None = None) -> list[str]:
        deadline = time.time() + (timeout or self.wait.timeout)
        cust_nos: list[str] = []
        while time.time() < deadline:
            cust_nos = self.row_cust_nos()
            if cust_nos:
                return cust_nos
            self.page.wait_for_timeout(200)
        raise AssertionError("档案明细在超时时间内未渲染")

    def read_current_page(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for row in self.vault_rows():
            try:
                out[self._td_text(row, self.COL_CUST_NO)] = {
                    "mobile": self._td_text(row, self.COL_MOBILE),
                    "idcard": self._td_text(row, self.COL_IDCARD),
                    "balance": self._td_text(row, self.COL_BALANCE),
                    "keyVersion": self._td_text(row, self.COL_KEY_VERSION),
                }
            except Exception:
                continue
        return out

    # ---------------- 分页 ---------------- #
    def page_info(self) -> dict:
        return self.api.crypto_vault_page(1).get("data", {})

    def can_next_page(self) -> bool:
        return self.page.locator(self.loc("page_next")).first.is_enabled()

    def goto_next_page(self, timeout: int | None = None) -> bool:
        if not self.can_next_page():
            return False
        before = self.row_cust_nos()
        self.wait.click_params(self.loc("page_next"))
        self.wait_rows_changed(before, timeout)
        return True

    def wait_rows_changed(self, before: list[str], timeout: int | None = None) -> list[str]:
        deadline = time.time() + (timeout or self.wait.timeout)
        current = before
        while time.time() < deadline:
            current = self.row_cust_nos()
            if current and current != before:
                return current
            self.page.wait_for_timeout(200)
        raise AssertionError("翻页后档案明细未刷新")

    def collect_all_rows(self, timeout: int | None = None) -> dict[str, dict[str, str]]:
        self.wait_rows_loaded(timeout)
        collected = self.read_current_page()
        for _ in range(max(0, int(self.page_info().get("pages", 1)) - 1)):
            if not self.goto_next_page(timeout):
                break
            collected.update(self.read_current_page())
        return collected

    # ---------------- 库表原始行 / 库元信息 ---------------- #
    def query_db_raw(self) -> int:
        self.click("db_query_btn")
        self.assert_log("已读取库表原始行")
        return self.page.locator(self.loc("raw_row")).count()

    def load_meta(self, timeout: int | None = None) -> str:
        self.click("db_meta_btn")
        self.wait.is_element_visible(self.loc("db_meta_text"), timeout or self.wait.timeout)
        return self.text_of("db_meta_text").strip()

    def cipher_cells(self) -> list[str]:
        return [t.strip() for t in self.page.locator(self.loc("cipher_cell")).all_inner_texts()]

    # ---------------- 新档案登记 ---------------- #
    def write_profile(self, cust_no: str, cust_name: str, mobile: str, balance: str = "") -> None:
        self.js_fill("write_custno", cust_no)
        self.js_fill("write_name", cust_name)
        self.js_fill("write_mobile", mobile)
        self.js_fill("write_balance", balance)
        self.click("write_btn")
        self.assert_log(f"登记成功：{cust_no}")

    # ---------------- 密文解密核验 ---------------- #
    def decrypt_on_page(self, cipher_b64: str, iv_b64: str, key_version_label: str | None = None) -> str:
        self.js_fill("decrypt_input", cipher_b64)
        self.js_fill("decrypt_iv", iv_b64)
        if key_version_label:
            act.el_select_by_text(self.page, self.loc("keyversion_select"), key_version_label)
        self.click("decrypt_btn")
        return self.text_of("decrypt_output").strip()

    def wait_decrypt_success(self, plain: str, timeout: int | None = None) -> None:
        self.assert_log("解密成功", timeout)
        deadline = time.time() + (timeout or self.wait.timeout)
        output = ""
        while time.time() < deadline:
            output = self.text_of("decrypt_output").strip()
            if plain and plain in output:
                return
            self.page.wait_for_timeout(200)
        raise AssertionError(f"解密输出未还原出明文 {plain}，当前输出: {output or '（空）'}")

    def wait_decrypt_failed(self, timeout: int | None = None) -> str:
        self.assert_log("解密失败", timeout)
        return self.text_of("decrypt_output").strip()

    # ---------------- 重置 ---------------- #
    def reset_vault(self) -> None:
        self.click("reset_btn")
        self.assert_log("密文库已重置")
        self.wait_rows_loaded()


class E04Handle(BaseScenarioHandle):
    """接口报文整体加密 + 时间戳/签名校验：解密成功 ≠ 校验通过。"""

    MODES = {"normal": "正常报文", "expired": "过期时间戳", "tampered": "签名被篡改"}

    def __init__(self, page: Page, timeout: int = 15):
        super().__init__(page, "E04", timeout)
        self.api = ApiClient()
        self.logger = get_logger()

    # ---------------- 拉取报文 ---------------- #
    def pick_mode(self, mode: str) -> None:
        selector = f"xpath={self.xpath('mode_radio').format(mode=self.MODES[mode])}"
        self.wait.click_params(selector)

    def fetch_envelope(self, mode: str) -> None:
        self.pick_mode(mode)
        before = self.envelope_value_or_empty("enc")
        self.click("fetch_btn")
        self.assert_log(f"已拉取 {mode} 报文")
        self.wait_envelope_refreshed(before)
        self.assert_log("本地解密成功")

    def envelope_value_or_empty(self, field: str) -> str:
        try:
            return self.envelope_value(field)
        except Exception:
            return ""

    def wait_envelope_refreshed(self, before: str, timeout: int | None = None) -> str:
        deadline = time.time() + (timeout or self.wait.timeout)
        current = before
        while time.time() < deadline:
            current = self.envelope_value_or_empty("enc")
            if current and current != before:
                return current
            self.page.wait_for_timeout(200)
        raise AssertionError("拉取后报文密文未刷新，无法确认页面已换用新报文")

    def envelope_value(self, field: str) -> str:
        return self.text_of(f"envelope_{field}").strip()

    def envelope_payload(self) -> dict:
        session = self.session_key()
        return {
            "ts": self.envelope_value("ts"),
            "sign": self.envelope_value("sign"),
            "encB64": self.envelope_value("enc"),
            "ivB64": self.envelope_value("iv"),
            "keyVersion": session.get("keyVersion"),
            "alg": session.get("alg"),
        }

    # ---------------- 解密后的成交明细 ---------------- #
    def decoded_rows(self) -> list[Locator]:
        return self.page.locator(self.loc("env_row")).all()

    def decoded_amounts(self) -> list[Decimal]:
        amounts: list[Decimal] = []
        for row in self.decoded_rows():
            try:
                amounts.append(
                    parse_amount(row.locator(self.xpath("env_amount")).first.inner_text())
                )
            except Exception:
                continue
        return amounts

    # ---------------- 脚本侧解密口径 ---------------- #
    def session_key(self) -> dict:
        return self.api.crypto_session_key().get("data", {})

    def decrypt_envelope_api(self, envelope: dict) -> list[dict]:
        self.session_key()
        body = self.api.crypto_decrypt(
            envelope["encB64"], envelope["ivB64"], envelope.get("keyVersion")
        )
        assert body.get("code") == 0, f"报文解密失败: {body}"
        return json.loads(body["data"]["plainText"]).get("rows", [])

    # ---------------- 时间戳 / 签名校验 ---------------- #
    def verify(self) -> None:
        self.click("verify_btn")

    def wait_verify_passed(self, timeout: int | None = None) -> None:
        self.assert_log("签名校验通过", timeout)

    def wait_verify_failed(self, keyword: str, timeout: int | None = None) -> None:
        self.assert_log("签名校验未通过", timeout)
        self.assert_log(keyword, timeout)

    def verify_by_api(self, ts, sign: str, enc_b64: str) -> dict:
        return self.api.crypto_envelope_verify(ts, sign, enc_b64)
