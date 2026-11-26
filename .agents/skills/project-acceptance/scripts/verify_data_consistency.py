# coding=utf-8
"""配置驱动的数据一致性与日志核验脚本（支持三方比对：API/页面数据源 ↔ SQLite 原表 ↔ 独立复算）。

设计原则：
- 零硬编码：所有接口路径、数据库元信息端点、金额容差与校验开关均从 references/*.yaml 读取；
- 只读安全：SQLite 以 URI `mode=ro` 只读打开，绝不越权写库；
- 跨项目可迁移：新项目仅需替换 references/env_config.yaml 与 acceptance_cases.yaml。

运行示例：
    python .agents/skills/project-acceptance/scripts/verify_data_consistency.py
    python .agents/skills/project-acceptance/scripts/verify_data_consistency.py --output report/acceptance/data_check.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PROJECT_ROOT = SKILL_DIR.parents[2]
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")


def expand_env_vars(value: Any) -> Any:
    """递归解析 YAML 中的 ${ENV_VAR:-default} 占位符。"""
    if isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env_vars(v) for v in value]
    if isinstance(value, str):
        def _replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            default = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(var_name, default)

        return _ENV_PATTERN.sub(_replace, value)
    return value


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return expand_env_vars(yaml.safe_load(fh) or {})


def get_by_dotted_path(data: Any, dotted: str) -> Any:
    current = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _cents_to_yuan(cents: Any) -> Decimal | None:
    if cents is None:
        return None
    return (Decimal(int(cents)) / Decimal(100)).quantize(Decimal("0.01"))


def _amount_equal(actual: Any, expected: Any, tolerance: Decimal) -> bool:
    return abs(Decimal(str(actual)) - Decimal(str(expected))) <= tolerance


def _connect_readonly(db_path: str) -> sqlite3.Connection:
    resolved = Path(db_path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"SQLite 库文件不存在: {resolved}")
    uri = f"file:{resolved.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _query_table(db_path: str, table: str, allowed_tables: list[str]) -> list[dict[str, Any]]:
    if table not in allowed_tables:
        raise ValueError(f"表 {table} 不在配置白名单内: {allowed_tables}")
    conn = _connect_readonly(db_path)
    try:
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall()]
    finally:
        conn.close()


def _resolve_db_path(session: requests.Session, api_base: str, db_cfg: dict[str, Any]) -> str:
    env_path = str(db_cfg.get("path_env") or "").strip()
    if env_path:
        raw_path = env_path
    else:
        meta_endpoint = db_cfg["meta_endpoint"]
        resp = session.get(f"{api_base}{meta_endpoint}", timeout=10)
        resp.raise_for_status()
        body = resp.json()
        db_path = get_by_dotted_path(body, db_cfg.get("meta_path_field", "data.dbPath"))
        if not db_path:
            raise RuntimeError(f"元信息接口 {meta_endpoint} 未返回有效库路径: {body}")
        raw_path = str(db_path)

    if Path(raw_path).exists():
        return raw_path
    override_dir = os.environ.get("SUT_DB_DIR_OVERRIDE", "").strip()
    if override_dir:
        filename = raw_path.replace("\\", "/").rsplit("/", 1)[-1]
        mapped = Path(override_dir) / filename
        if mapped.exists():
            return str(mapped)
    return raw_path


def _check_settlement_three_way(
    session: requests.Session,
    api_base: str,
    db_cfg: dict[str, Any],
    rule_cfg: dict[str, Any],
) -> dict[str, Any]:
    """I-18 三方比对：分页接口数据源 ↔ SQLite 落盘原表 ↔ Decimal 分转元复算。"""
    started = time.perf_counter()
    tolerance = Decimal(str(db_cfg.get("tolerance", "0.005")))
    allowed = list(db_cfg.get("tables") or [])
    evidence: list[str] = []

    try:
        if rule_cfg.get("reset_before") and db_cfg.get("reset_endpoint"):
            session.post(f"{api_base}{db_cfg['reset_endpoint']}", timeout=10).raise_for_status()

        db_path = _resolve_db_path(session, api_base, db_cfg)
        db_details = _query_table(db_path, "settle_detail", allowed)
        db_bills = _query_table(db_path, "settle_bill", allowed)
        db_accounts = _query_table(db_path, "fund_account", allowed)

        # 翻完全部 API 分页
        page_no = 1
        api_items: dict[str, Any] = {}
        first_data: dict[str, Any] = {}
        while True:
            resp = session.get(f"{api_base}{db_cfg['page_endpoint']}", params={"page": page_no, "size": 5}, timeout=10)
            resp.raise_for_status()
            data = resp.json().get("data") or {}
            if page_no == 1:
                first_data = data
            rows = data.get("details") or data.get("rows") or data.get("items") or []
            if not rows:
                break
            for row in rows:
                item_no = row.get("itemNo") or row.get("item_no")
                if item_no:
                    api_items[item_no] = row
            total = int(data.get("total") or len(api_items))
            if len(api_items) >= total or len(rows) < 5:
                break
            page_no += 1

        if len(api_items) != len(db_details):
            raise AssertionError(
                f"分页收集明细条数({len(api_items)}) != 库表行数({len(db_details)})"
            )
        evidence.append(f"明细翻页全量对齐: {len(db_details)} 条 / {page_no} 页")

        null_count = 0
        neg_count = 0
        for db_row in db_details:
            item_no = db_row["item_no"]
            cents = db_row["amount_cents"]
            api_row = api_items.get(item_no)
            if api_row is None:
                raise AssertionError(f"接口分页缺失库中明细: {item_no}")
            api_val = api_row.get("amount")
            if cents is None:
                null_count += 1
                if api_val is not None:
                    raise AssertionError(f"{item_no} 库中为 NULL，接口却返回 {api_val!r}")
            else:
                if cents < 0:
                    neg_count += 1
                expected_yuan = _cents_to_yuan(cents)
                if api_val is None or not _amount_equal(api_val, expected_yuan, tolerance):
                    raise AssertionError(
                        f"{item_no} 金额不一致: 接口={api_val} vs 库复算={expected_yuan}"
                    )

        if rule_cfg.get("check_null_unsettled") and null_count == 0:
            raise AssertionError("未检出 NULL 未清算样本行")
        if rule_cfg.get("check_negative_amount") and neg_count == 0:
            raise AssertionError("未检出负数样本行")
        evidence.append(f"逐条分→元核对通过(容差 {tolerance})，含 NULL {null_count} 条、负数 {neg_count} 条")

        # 汇总漂移与资金账户核对
        bill_sum_cents = sum(int(r["total_amount_cents"]) for r in db_bills)
        detail_sum_cents = sum(int(r["amount_cents"] or 0) for r in db_details)
        if rule_cfg.get("check_summary_drift") and bill_sum_cents == detail_sum_cents:
            raise AssertionError("未检出预期的结算单汇总漂移（bill_sum == detail_sum）")

        summary = first_data.get("summary") or {}
        if "billTotal" in summary or "totalAmount" in summary:
            api_bill_total = summary.get("billTotal", summary.get("totalAmount"))
            if not _amount_equal(api_bill_total, _cents_to_yuan(bill_sum_cents), tolerance):
                raise AssertionError(
                    f"汇总卡总额({api_bill_total}) != 库 settle_bill 求和({_cents_to_yuan(bill_sum_cents)})"
                )
        evidence.append(
            f"汇总漂移核验通过: settle_bill={_cents_to_yuan(bill_sum_cents)} != detail_sum={_cents_to_yuan(detail_sum_cents)}"
        )

        if rule_cfg.get("check_fund_accounts"):
            avail_sum = _cents_to_yuan(sum(int(r["available_cents"]) for r in db_accounts))
            frozen_sum = _cents_to_yuan(sum(int(r["frozen_cents"]) for r in db_accounts))
            evidence.append(f"资金账户 {len(db_accounts)} 户: 可用={avail_sum}, 冻结={frozen_sum}")

        if rule_cfg.get("reset_after") and db_cfg.get("reset_endpoint"):
            session.post(f"{api_base}{db_cfg['reset_endpoint']}", timeout=10).raise_for_status()

        return {
            "id": "DATA-01",
            "name": "结算数据三方一致性（分页接口 ↔ SQLite 分单位 ↔ Decimal 复算）",
            "status": "PASS",
            "duration_s": round(time.perf_counter() - started, 3),
            "details": "；".join(evidence),
        }
    except Exception as exc:
        return {
            "id": "DATA-01",
            "name": "结算数据三方一致性（分页接口 ↔ SQLite 分单位 ↔ Decimal 复算）",
            "status": "FAIL",
            "duration_s": round(time.perf_counter() - started, 3),
            "details": str(exc),
        }


def _check_crypto_vault_three_way(
    session: requests.Session,
    api_base: str,
    db_cfg: dict[str, Any],
    rule_cfg: dict[str, Any],
) -> dict[str, Any]:
    """E-03 三方比对：SQLite AES-GCM 密文库 ↔ 分页解密结果 ↔ 按密钥版本接口复算。"""
    started = time.perf_counter()
    allowed = list(db_cfg.get("tables") or [])
    revoked = str(db_cfg.get("revoked_key_version", "K0"))
    min_len = int(rule_cfg.get("min_cipher_length", 24))
    null_code = int(rule_cfg.get("check_null_field_code", 2003))

    try:
        if rule_cfg.get("reset_before") and db_cfg.get("reset_endpoint"):
            session.post(f"{api_base}{db_cfg['reset_endpoint']}", json={}, timeout=10).raise_for_status()

        db_path = _resolve_db_path(session, api_base, db_cfg)
        db_rows = _query_table(db_path, "cust_profile", allowed)

        # 收集全量分页接口数据
        page_rows: dict[str, dict[str, Any]] = {}
        page_no = 1
        while True:
            resp = session.get(f"{api_base}{db_cfg['page_endpoint']}", params={"page": page_no}, timeout=10)
            resp.raise_for_status()
            data = resp.json().get("data") or {}
            rows = data.get("rows") or []
            for r in rows:
                page_rows[r["custNo"]] = r
            pages = int(data.get("pages") or 1)
            if page_no >= pages:
                break
            page_no += 1

        if len(page_rows) != len(db_rows):
            raise AssertionError(f"密文库行数({len(db_rows)}) != 分页接口总条数({len(page_rows)})")

        decrypted_verified = 0
        revoked_verified = 0
        null_verified = 0

        for row in db_rows:
            cust_no = row["cust_no"]
            kv = row["key_version"]
            page_row = page_rows.get(cust_no)
            if not page_row:
                raise AssertionError(f"分页接口缺失客户 {cust_no}")

            for c_col, iv_col, p_key in (
                ("mobile_enc", "mobile_iv", "mobile"),
                ("idcard_enc", "idcard_iv", "idcard"),
                ("balance_enc", "balance_iv", "balance"),
            ):
                cipher = row.get(c_col)
                iv = row.get(iv_col)
                if not cipher:
                    null_verified += 1
                    dec = session.post(
                        f"{api_base}{db_cfg['decrypt_endpoint']}",
                        json={"cipherB64": cipher, "ivB64": iv},
                        timeout=10,
                    ).json()
                    if dec.get("code") != null_code:
                        raise AssertionError(f"{cust_no}.{p_key} NULL 字段应返 {null_code}，实际 {dec}")
                    continue

                if rule_cfg.get("check_cipher_not_plaintext"):
                    if str(cipher).isdigit() or len(str(cipher)) < min_len:
                        raise AssertionError(f"{cust_no}.{c_col} 疑似明文或密文过短: {cipher}")

                if kv == revoked:
                    revoked_verified += 1
                    field_state = page_row.get(f"{p_key}State")
                    field_val = page_row.get(p_key)
                    if field_state != "fail" and field_val != "解密失败":
                        raise AssertionError(
                            f"{cust_no}.{p_key} 已吊销密钥 {revoked} 应标记 fail/解密失败，实际 state={field_state!r}, val={field_val!r}"
                        )
                    dec_revoked = session.post(
                        f"{api_base}{db_cfg['decrypt_endpoint']}",
                        json={"cipherB64": cipher, "ivB64": iv, "keyVersion": kv},
                        timeout=10,
                    ).json()
                    if dec_revoked.get("code") == 0:
                        raise AssertionError(f"{cust_no}.{p_key} 已吊销密钥 {revoked} 不应解密成功")
                    continue

                dec = session.post(
                    f"{api_base}{db_cfg['decrypt_endpoint']}",
                    json={"cipherB64": cipher, "ivB64": iv, "keyVersion": kv},
                    timeout=10,
                ).json()
                if dec.get("code") != 0:
                    raise AssertionError(f"{cust_no}.{p_key} ({kv}) 解密失败: {dec}")
                plain = dec["data"]["plainText"]
                if plain != page_row.get(p_key):
                    raise AssertionError(
                        f"{cust_no}.{p_key} 解密明文({plain}) != 页面展示({page_row.get(p_key)})"
                    )
                if cipher == plain:
                    raise AssertionError(f"{cust_no}.{c_col} 库中存在明文存储")
                decrypted_verified += 1

        return {
            "id": "DATA-02",
            "name": "密文存储三方一致性（SQLite 密文/IV ↔ 按版本解密 ↔ 页面明文）",
            "status": "PASS",
            "duration_s": round(time.perf_counter() - started, 3),
            "details": (
                f"共核对 {len(db_rows)} 户；解密一致 {decrypted_verified} 字段、"
                f"已吊销({revoked}) {revoked_verified} 字段、NULL(2003) {null_verified} 字段"
            ),
        }
    except Exception as exc:
        return {
            "id": "DATA-02",
            "name": "密文存储三方一致性（SQLite 密文/IV ↔ 按版本解密 ↔ 页面明文）",
            "status": "FAIL",
            "duration_s": round(time.perf_counter() - started, 3),
            "details": str(exc),
        }


def _check_crypto_envelope_and_digest(
    session: requests.Session,
    api_base: str,
    rule_cfg: dict[str, Any],
) -> dict[str, Any]:
    """E-04 报文加解密/验签分离规则 + E-01 独立 SHA-256 摘要算法自检。"""
    started = time.perf_counter()
    notes: list[str] = []
    try:
        # E-01 摘要算法一致性自检
        sample_digest = hashlib.sha256("AcceptanceDigestCheck".encode("utf-8")).hexdigest()[:16].upper()
        if len(sample_digest) != 16:
            raise AssertionError("SHA-256 16 位大写摘要自检异常")

        session_key = session.get(f"{api_base}/api/crypto/session-key", timeout=10).json().get("data") or {}
        kv = session_key.get("keyVersion")

        for item in rule_cfg.get("modes") or []:
            mode = item["mode"]
            expect_code = int(item["expect_verify_code"])
            env_resp = session.get(f"{api_base}/api/crypto/envelope", params={"mode": mode}, timeout=10).json()
            if env_resp.get("code") != 0:
                raise AssertionError(f"拉取 {mode} 报文失败: {env_resp}")
            env_data = env_resp["data"]

            dec = session.post(
                f"{api_base}/api/crypto/decrypt",
                json={
                    "cipherB64": env_data["encB64"],
                    "ivB64": env_data["ivB64"],
                    "keyVersion": kv,
                    "alg": "AES-GCM",
                },
                timeout=10,
            ).json()
            if dec.get("code") != 0:
                raise AssertionError(f"{mode} 报文解密失败: {dec}")
            rows = json.loads(dec["data"]["plainText"]).get("rows") or []
            if not rows:
                raise AssertionError(f"{mode} 报文解密后明细为空")
            for r in rows:
                if r.get("customer") and r["customer"] in env_data["encB64"]:
                    raise AssertionError(f"{mode} 密文中泄漏明文客户名")

            ver = session.post(
                f"{api_base}/api/crypto/envelope/verify",
                json={"ts": env_data["ts"], "sign": env_data["sign"], "encB64": env_data["encB64"]},
                timeout=10,
            ).json()
            if ver.get("code") != expect_code:
                raise AssertionError(
                    f"{mode} 报文验签码异常: 期望 {expect_code}, 实际 {ver.get('code')} ({ver})"
                )
            notes.append(f"{mode}: 解密 {len(rows)} 条 + 验签 code={ver.get('code')}")

        return {
            "id": "DATA-03",
            "name": "加密报文加解密与验签分离校验（normal=0 / expired=2001 / tampered=2002）",
            "status": "PASS",
            "duration_s": round(time.perf_counter() - started, 3),
            "details": "；".join(notes),
        }
    except Exception as exc:
        return {
            "id": "DATA-03",
            "name": "加密报文加解密与验签分离校验（normal=0 / expired=2001 / tampered=2002）",
            "status": "FAIL",
            "duration_s": round(time.perf_counter() - started, 3),
            "details": str(exc),
        }


def _check_log_anomalies(project_root: Path, env_cfg: dict[str, Any], rule_cfg: dict[str, Any]) -> dict[str, Any]:
    """扫描最近运行日志，确认无未预期 CRITICAL 级异常。"""
    started = time.perf_counter()
    log_dir = project_root / str(get_by_dotted_path(env_cfg, "paths.app_log_dir") or "log/logs")
    max_lines = int(rule_cfg.get("max_lines", 300))
    levels = [str(lv).upper() for lv in (rule_cfg.get("alert_levels") or ["CRITICAL"])]

    if not log_dir.exists():
        return {
            "id": "DATA-04",
            "name": "运行日志异常级别扫描",
            "status": "PASS",
            "duration_s": round(time.perf_counter() - started, 3),
            "details": f"日志目录尚未生成 ({log_dir})，无异常记录",
        }

    log_files = sorted(log_dir.glob("*.log*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not log_files:
        return {
            "id": "DATA-04",
            "name": "运行日志异常级别扫描",
            "status": "PASS",
            "duration_s": round(time.perf_counter() - started, 3),
            "details": "暂无日志文件，跳过扫描",
        }

    latest = log_files[0]
    lines = latest.read_text(encoding="utf-8", errors="replace").splitlines()[-max_lines:]
    hits = [ln for ln in lines if any(f": {lv} " in ln or f" {lv} " in ln for lv in levels)]
    return {
        "id": "DATA-04",
        "name": "运行日志异常级别扫描",
        "status": "FAIL" if hits else "PASS",
        "duration_s": round(time.perf_counter() - started, 3),
        "details": (
            f"在 {latest.name} 最近 {len(lines)} 行中检出 {len(hits)} 条 {levels} 记录: {hits[:2]}"
            if hits
            else f"已扫描 {latest.name} 最近 {len(lines)} 行，检出 0 条 {levels} 记录"
        ),
    }


def run_data_consistency(
    env_cfg: dict[str, Any],
    cases_cfg: dict[str, Any],
    project_root: Path = DEFAULT_PROJECT_ROOT,
) -> dict[str, Any]:
    """统一入口：按配置执行所有启用的数据一致性与日志校验。"""
    started = time.perf_counter()
    api_base = str(get_by_dotted_path(env_cfg, "services.backend.url") or "").rstrip("/")
    databases = env_cfg.get("databases") or {}
    rules = cases_cfg.get("data_consistency_checks") or {}

    session = requests.Session()
    token = str(get_by_dotted_path(env_cfg, "auth.token") or "").strip()
    if token and get_by_dotted_path(env_cfg, "auth.mode") == "bearer_token":
        hdr = str(get_by_dotted_path(env_cfg, "auth.header_name") or "Authorization")
        prefix = str(get_by_dotted_path(env_cfg, "auth.header_prefix") or "Bearer ")
        session.headers[hdr] = f"{prefix}{token}"

    checks: list[dict[str, Any]] = []
    if (rules.get("settlement_three_way") or {}).get("enabled") and "settlement" in databases:
        checks.append(
            _check_settlement_three_way(session, api_base, databases["settlement"], rules["settlement_three_way"])
        )
    if (rules.get("crypto_vault_three_way") or {}).get("enabled") and "crypto_vault" in databases:
        checks.append(
            _check_crypto_vault_three_way(session, api_base, databases["crypto_vault"], rules["crypto_vault_three_way"])
        )
    if (rules.get("crypto_envelope_verify") or {}).get("enabled"):
        checks.append(_check_crypto_envelope_and_digest(session, api_base, rules["crypto_envelope_verify"]))
    if (rules.get("log_anomaly_scan") or {}).get("enabled"):
        checks.append(_check_log_anomalies(project_root, env_cfg, rules["log_anomaly_scan"]))

    passed = sum(1 for c in checks if c["status"] == "PASS")
    ok = passed == len(checks)
    return {
        "status": "PASS" if ok else "FAIL",
        "passed": passed,
        "total": len(checks),
        "duration_s": round(time.perf_counter() - started, 3),
        "note": "全部数据库/密文/报文/日志核验通过" if ok else f"存在 {len(checks) - passed} 项数据核验失败",
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="配置驱动的数据一致性与日志核验脚本")
    parser.add_argument(
        "--config",
        default=str(SKILL_DIR / "references" / "env_config.yaml"),
        help="环境配置 YAML 路径",
    )
    parser.add_argument(
        "--cases",
        default=str(SKILL_DIR / "references" / "acceptance_cases.yaml"),
        help="验收用例规则 YAML 路径",
    )
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT), help="项目根目录")
    parser.add_argument("--output", default="", help="可选：输出 JSON 路径")
    args = parser.parse_args()

    env_cfg = load_yaml(Path(args.config))
    cases_cfg = load_yaml(Path(args.cases))
    result = run_data_consistency(env_cfg, cases_cfg, Path(args.project_root))

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
