# coding=utf-8
"""标准化项目验收统一调度脚本（配置驱动，零项目硬编码）。

职责：
1. 读取 references/env_config.yaml（支持 ${ENV:-default} 插值与自动脱敏）与 acceptance_cases.yaml；
2. 按选定 --profile 依次调度：
   Stage 1: Preflight（前后端健康预检 + 端口探测回退）
   Stage 2: API 契约校验（正常路径 + 业务异常码 + 已知后端缺陷标记）
   Stage 3: UI 菜单与标签/颜色一致性验收
   Stage 4: Playwright 场景自动化（pytest + JUnit XML 精确解析）
   Stage 5: 数据库与三方一致性核验（verify_data_consistency.py）
   Stage 6: 门禁规则判定 + 自动渲染标准 Markdown 验收报告（generate_report.py）

运行示例：
    python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile smoke
    python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile api-only
    python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile full --headless
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_PROJECT_ROOT = SKILL_DIR.parents[2]

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from generate_report import render_report  # noqa: E402
from verify_data_consistency import (  # noqa: E402
    get_by_dotted_path,
    load_yaml,
    run_data_consistency,
)


def _build_session(env_cfg: dict[str, Any]) -> requests.Session:
    session = requests.Session()
    token = str(get_by_dotted_path(env_cfg, "auth.token") or "").strip()
    if token and get_by_dotted_path(env_cfg, "auth.mode") == "bearer_token":
        hdr = str(get_by_dotted_path(env_cfg, "auth.header_name") or "Authorization")
        prefix = str(get_by_dotted_path(env_cfg, "auth.header_prefix") or "Bearer ")
        session.headers[hdr] = f"{prefix}{token}"
    return session


def _run_preflight(env_cfg: dict[str, Any], session: requests.Session) -> dict[str, Any]:
    """Stage 1: 服务健康预检（支持前端端口回退探测，不可达时快速阻断）。"""
    started = time.perf_counter()
    fe_cfg = get_by_dotted_path(env_cfg, "services.frontend") or {}
    be_cfg = get_by_dotted_path(env_cfg, "services.backend") or {}

    fe_url = str(fe_cfg.get("url") or "").rstrip("/")
    fe_path = str(fe_cfg.get("health_path") or "/")
    fe_timeout = int(fe_cfg.get("timeout_seconds") or 5)
    fallback_ports = fe_cfg.get("fallback_ports") or []

    fe_ok = False
    fe_detail = ""
    effective_fe_url = fe_url
    try:
        r = session.get(f"{fe_url}{fe_path}", timeout=fe_timeout)
        fe_ok = r.status_code < 500
        fe_detail = f"HTTP {r.status_code}"
    except Exception as exc:
        fe_detail = str(exc)
        for port in fallback_ports:
            cand = re.sub(r":\d+$", f":{port}", fe_url)
            if cand == fe_url:
                continue
            try:
                r = session.get(f"{cand}{fe_path}", timeout=fe_timeout)
                if r.status_code < 500:
                    fe_ok = True
                    effective_fe_url = cand
                    fe_detail = f"主端口不可达，已自动回退至 {cand} (HTTP {r.status_code})"
                    break
            except Exception:
                continue

    be_url = str(be_cfg.get("url") or "").rstrip("/")
    be_path = str(be_cfg.get("health_path") or "/api/health")
    be_timeout = int(be_cfg.get("timeout_seconds") or 5)
    expect_http = int(be_cfg.get("expected_http_status") or 200)
    expect_code = be_cfg.get("expected_json_code")

    be_ok = False
    be_detail = ""
    try:
        r = session.get(f"{be_url}{be_path}", timeout=be_timeout)
        body = r.json() if "application/json" in (r.headers.get("content-type") or "") else {}
        code_ok = expect_code is None or body.get("code") == expect_code
        be_ok = r.status_code == expect_http and code_ok
        be_detail = f"HTTP {r.status_code}, body={body}"
    except Exception as exc:
        be_detail = str(exc)

    passed = int(fe_ok) + int(be_ok)
    return {
        "status": "PASS" if (fe_ok and be_ok) else "FAIL",
        "passed": passed,
        "total": 2,
        "duration_s": round(time.perf_counter() - started, 3),
        "effective_frontend_url": effective_fe_url,
        "frontend_ok": fe_ok,
        "backend_ok": be_ok,
        "note": f"前端({effective_fe_url}): {fe_detail}；后端({be_url}): {be_detail}",
    }


def _run_api_checks(
    env_cfg: dict[str, Any],
    cases_cfg: dict[str, Any],
    session: requests.Session,
) -> dict[str, Any]:
    """Stage 2: 声明式 API 契约与异常码校验。"""
    started = time.perf_counter()
    be_url = str(get_by_dotted_path(env_cfg, "services.backend.url") or "").rstrip("/")
    specs = cases_cfg.get("api_checks") or []
    results: list[dict[str, Any]] = []

    for spec in specs:
        t0 = time.perf_counter()
        method = str(spec.get("method", "GET")).upper()
        path = str(spec.get("path", "/"))
        url = f"{be_url}{path}"
        status = "PASS"
        details = ""
        try:
            resp = session.request(
                method,
                url,
                params=spec.get("params"),
                json=spec.get("payload"),
                timeout=10,
            )
            expect_http = int(spec.get("expect_http", 200))
            if resp.status_code != expect_http:
                status = "FAIL"
                details = f"期望 HTTP {expect_http}，实际 HTTP {resp.status_code}"
            else:
                body = resp.json() if "application/json" in (resp.headers.get("content-type") or "") else {}
                for field, expected in (spec.get("expect_json") or {}).items():
                    actual = get_by_dotted_path(body, field)
                    if actual != expected:
                        status = "FAIL"
                        details = f"字段 {field} 期望 {expected!r}，实际 {actual!r}"
                        break
                if status == "PASS":
                    for field in spec.get("expect_non_empty") or []:
                        actual = get_by_dotted_path(body, field)
                        if not actual:
                            status = "FAIL"
                            details = f"必填字段 {field} 为空"
                            break
                if status == "PASS":
                    details = f"HTTP {resp.status_code}, code={body.get('code')}"
        except Exception as exc:
            status = "FAIL"
            details = str(exc)

        results.append(
            {
                "id": spec.get("id", "-"),
                "name": spec.get("name", path),
                "method": method,
                "path": path,
                "severity": spec.get("severity", "major"),
                "known_backend_issue": spec.get("known_backend_issue", ""),
                "status": status,
                "duration_s": round(time.perf_counter() - t0, 3),
                "details": details,
            }
        )

    passed = sum(1 for r in results if r["status"] == "PASS")
    unknown_fail = [r for r in results if r["status"] != "PASS" and not r["known_backend_issue"]]
    known_fail = [r for r in results if r["status"] != "PASS" and r["known_backend_issue"]]

    if unknown_fail:
        stage_status = "FAIL"
        note = f"存在 {len(unknown_fail)} 项未预期 API 契约失败"
    elif known_fail:
        stage_status = "CONDITIONAL_PASS"
        note = f"仅 {len(known_fail)} 项已知后端缺陷失败（{', '.join(r['id'] for r in known_fail)}）"
    else:
        stage_status = "PASS"
        note = "全部 API 契约校验通过"

    return {
        "status": stage_status,
        "passed": passed,
        "total": len(results),
        "duration_s": round(time.perf_counter() - started, 3),
        "note": note,
        "checks": results,
    }


def _parse_junit_xml(xml_path: Path) -> list[dict[str, Any]]:
    if not xml_path.exists():
        return []
    tree = ET.parse(xml_path)
    root = tree.getroot()
    cases: list[dict[str, Any]] = []
    for tc in root.iter("testcase"):
        classname = tc.attrib.get("classname", "")
        name = tc.attrib.get("name", "")
        duration_s = round(float(tc.attrib.get("time", 0.0)), 3)
        failure = tc.find("failure")
        error = tc.find("error")
        skipped = tc.find("skipped")
        if failure is not None:
            status = "FAIL"
            msg = failure.attrib.get("message") or (failure.text or "").splitlines()[0]
        elif error is not None:
            status = "FAIL"
            msg = error.attrib.get("message") or (error.text or "").splitlines()[0]
        elif skipped is not None:
            status = "SKIPPED"
            msg = skipped.attrib.get("message", "")
        else:
            status = "PASS"
            msg = ""
        cases.append(
            {
                "classname": classname,
                "name": name,
                "status": status,
                "duration_s": duration_s,
                "message": msg,
            }
        )
    return cases


def _run_ui_menu_consistency(
    project_root: Path,
    cases_cfg: dict[str, Any],
    work_dir: Path,
) -> dict[str, Any]:
    """Stage 3: 调度 UI 菜单加载与标签/颜色一致性校验。"""
    started = time.perf_counter()
    ui_cfg = cases_cfg.get("ui_menu_consistency") or {}
    target = str(ui_cfg.get("pytest_target") or "")
    if not target or not (project_root / target).exists():
        return {
            "status": "SKIPPED",
            "passed": 0,
            "total": 0,
            "duration_s": 0.0,
            "note": f"未配置或未找到 UI 菜单脚本: {target}",
        }

    junit_xml = work_dir / "junit_ui_menu.xml"
    cmd = [sys.executable, "-m", "pytest", target, "-v", "-s", f"--junitxml={junit_xml}"]
    proc = subprocess.run(
        cmd,
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = proc.stdout + "\n" + proc.stderr
    summary_line = ""
    color_line = ""
    for line in output.splitlines():
        if "总页面数:" in line:
            summary_line = line.strip()
        elif "去重颜色数:" in line:
            color_line = line.strip()

    ok = proc.returncode == 0
    return {
        "status": "PASS" if ok else "FAIL",
        "passed": 1 if ok else 0,
        "total": 1,
        "duration_s": round(time.perf_counter() - started, 3),
        "target": target,
        "summary_line": summary_line,
        "color_line": color_line,
        "error": "" if ok else (output.splitlines()[-1] if output.splitlines() else "执行失败"),
        "note": summary_line or ("通过" if ok else "存在不一致或加载失败"),
    }


def _run_pytest_suites(
    project_root: Path,
    profile_cfg: dict[str, Any],
    cases_cfg: dict[str, Any],
    work_dir: Path,
    browser_type: str,
    headless: bool,
    trace_mode: str,
) -> dict[str, Any]:
    """Stage 4: 调度 Playwright pytest 业务场景集并通过 JUnit XML 精确采集结果。"""
    started = time.perf_counter()
    targets = profile_cfg.get("pytest_targets") or []
    if not targets:
        return {
            "status": "SKIPPED",
            "passed": 0,
            "total": 0,
            "duration_s": 0.0,
            "note": "当前档位未配置 pytest 场景目标",
            "cases": [],
        }

    # 按函数名建立 scenario_catalog 索引
    catalog_by_func: dict[str, dict[str, Any]] = {}
    for entry in cases_cfg.get("scenario_catalog") or []:
        node = str(entry.get("node") or "")
        func_name = node.split("::")[-1] if "::" in node else node
        if func_name:
            catalog_by_func[func_name] = entry

    all_cases: list[dict[str, Any]] = []
    for idx, tgt in enumerate(targets):
        junit_xml = work_dir / f"junit_suite_{idx}.xml"
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            *list(tgt.get("args") or []),
            "--browser",
            browser_type,
            "--headless" if headless else "--headed",
            "--pw-trace",
            trace_mode,
            "--tb=short",
            f"--junitxml={junit_xml}",
        ]
        subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        parsed = _parse_junit_xml(junit_xml)
        for item in parsed:
            meta = catalog_by_func.get(item["name"], {})
            item["scenario_id"] = meta.get("id", "-")
            item["group"] = meta.get("group", "-")
            item["priority"] = meta.get("priority", "-")
            item["known_backend_issue"] = meta.get("known_backend_issue", "")
            all_cases.append(item)

    passed = sum(1 for c in all_cases if c["status"] == "PASS")
    unknown_fail = [c for c in all_cases if c["status"] != "PASS" and not c["known_backend_issue"]]
    known_fail = [c for c in all_cases if c["status"] != "PASS" and c["known_backend_issue"]]

    if not all_cases:
        stage_status = "FAIL"
        note = "pytest 未采集到任何用例结果"
    elif unknown_fail:
        stage_status = "FAIL"
        note = f"存在 {len(unknown_fail)} 条未预期失败用例"
    elif known_fail:
        stage_status = "CONDITIONAL_PASS"
        note = f"仅 {len(known_fail)} 条已知后端缺陷用例失败（{', '.join(c['scenario_id'] for c in known_fail)}）"
    else:
        stage_status = "PASS"
        note = "全部 Playwright 场景用例通过"

    return {
        "status": stage_status,
        "passed": passed,
        "total": len(all_cases),
        "duration_s": round(time.perf_counter() - started, 3),
        "note": note,
        "cases": all_cases,
    }


def _collect_defects_and_verdict(
    stages: dict[str, dict[str, Any]],
    blocking_rules: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    defects: list[dict[str, Any]] = []
    has_blocker = False
    has_known_backend = False

    pf = stages.get("preflight") or {}
    if pf.get("status") == "FAIL":
        has_blocker = True
        defects.append(
            {
                "severity": "blocker",
                "stage": "Preflight",
                "id": "ENV-PREFLIGHT",
                "owner": "运行环境/被测服务",
                "summary": pf.get("note", "前后端服务不可达"),
            }
        )

    for chk in (stages.get("api_checks") or {}).get("checks") or []:
        if chk["status"] != "PASS":
            if chk.get("known_backend_issue"):
                has_known_backend = True
                owner = "被测系统后端（已知缺陷）"
            else:
                owner = "被测后端 / API 契约"
                if chk.get("severity") == "blocker" or blocking_rules.get("blocker_api_must_pass", True):
                    has_blocker = True
            defects.append(
                {
                    "severity": chk.get("severity", "major"),
                    "stage": "API 契约校验",
                    "id": chk["id"],
                    "owner": owner,
                    "summary": f"{chk['name']}: {chk['details']}",
                }
            )

    um = stages.get("ui_menu_consistency") or {}
    if um.get("status") == "FAIL":
        if blocking_rules.get("ui_menu_must_pass", True):
            has_blocker = True
        defects.append(
            {
                "severity": "major",
                "stage": "UI 菜单与标签一致性",
                "id": "UI-MENU",
                "owner": "前端 UI / 样式联动",
                "summary": um.get("error") or um.get("note", "UI 菜单一致性失败"),
            }
        )

    for case in (stages.get("pytest_suites") or {}).get("cases") or []:
        if case["status"] != "PASS":
            if case.get("known_backend_issue"):
                has_known_backend = True
                owner = "被测系统后端（已知缺陷）"
                sev = "major"
            else:
                has_blocker = True
                owner = "被测系统或自动化脚本"
                sev = "blocker" if case.get("priority") == "P0" else "major"
            defects.append(
                {
                    "severity": sev,
                    "stage": "Playwright 场景自动化",
                    "id": case.get("scenario_id") or case["name"],
                    "owner": owner,
                    "summary": f"{case['name']}: {case.get('message') or case.get('known_backend_issue')}",
                }
            )

    for chk in (stages.get("data_consistency") or {}).get("checks") or []:
        if chk["status"] != "PASS":
            if blocking_rules.get("data_consistency_must_pass", True):
                has_blocker = True
            defects.append(
                {
                    "severity": "blocker",
                    "stage": "数据三方一致性",
                    "id": chk["id"],
                    "owner": "数据库/业务一致性",
                    "summary": f"{chk['name']}: {chk['details']}",
                }
            )

    if has_blocker:
        return "BLOCKED", defects
    if has_known_backend and blocking_rules.get("downgrade_on_known_backend_issue", True):
        return "CONDITIONAL_PASS", defects
    return "PASS", defects


def main() -> int:
    parser = argparse.ArgumentParser(description="标准化项目验收统一调度入口")
    parser.add_argument(
        "--profile",
        default="smoke",
        help="验收档位（定义在 references/acceptance_cases.yaml::profiles，如 smoke/quick/full/api-only/ui-menu/data-only）",
    )
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
    parser.add_argument("--browser", default="", help="覆盖浏览器类型")
    parser.add_argument("--headed", action="store_true", help="强制有头模式运行浏览器")
    parser.add_argument("--headless", action="store_true", help="强制无头模式运行浏览器")
    parser.add_argument("--output-dir", default="", help="覆盖验收报告输出目录")
    args = parser.parse_args()

    t_total = time.perf_counter()
    project_root = Path(args.project_root).resolve()
    env_cfg = load_yaml(Path(args.config))
    cases_cfg = load_yaml(Path(args.cases))

    profiles = cases_cfg.get("profiles") or {}
    if args.profile not in profiles:
        raise SystemExit(f"未知验收档位: {args.profile}，可选: {sorted(profiles)}")
    profile_cfg = profiles[args.profile]
    enabled_stages = list(profile_cfg.get("stages") or [])

    browser_type = args.browser or str(get_by_dotted_path(env_cfg, "browser.type") or "chromium")
    headless = (
        False
        if args.headed
        else (True if args.headless else bool(get_by_dotted_path(env_cfg, "browser.headless")))
    )
    trace_mode = str(get_by_dotted_path(env_cfg, "browser.trace_mode") or "retain-on-failure")

    out_dir_rel = args.output_dir or str(
        get_by_dotted_path(env_cfg, "paths.report_output_dir") or "report/acceptance"
    )
    out_dir = Path(out_dir_rel) if Path(out_dir_rel).is_absolute() else (project_root / out_dir_rel)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / ".tmp_junit"
    work_dir.mkdir(parents=True, exist_ok=True)

    session = _build_session(env_cfg)
    stages: dict[str, dict[str, Any]] = {}

    # Stage 1: Preflight
    effective_fe = str(get_by_dotted_path(env_cfg, "services.frontend.url") or "")
    preflight_passed = True
    if "preflight" in enabled_stages:
        stages["preflight"] = _run_preflight(env_cfg, session)
        effective_fe = stages["preflight"]["effective_frontend_url"]
        preflight_passed = stages["preflight"]["status"] == "PASS"

    # 若预检通过再执行后续阶段（预检失败快速阻断）
    if preflight_passed:
        if "api_checks" in enabled_stages:
            stages["api_checks"] = _run_api_checks(env_cfg, cases_cfg, session)
        if "ui_menu_consistency" in enabled_stages:
            stages["ui_menu_consistency"] = _run_ui_menu_consistency(project_root, cases_cfg, work_dir)
        if "pytest_suites" in enabled_stages:
            stages["pytest_suites"] = _run_pytest_suites(
                project_root,
                profile_cfg,
                cases_cfg,
                work_dir,
                browser_type,
                headless,
                trace_mode,
            )
        if "data_consistency" in enabled_stages:
            stages["data_consistency"] = run_data_consistency(env_cfg, cases_cfg, project_root)

    overall_status, defects = _collect_defects_and_verdict(
        stages, cases_cfg.get("blocking_rules") or {}
    )

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    result_json_path = out_dir / f"acceptance_result_{args.profile}_{stamp}.json"
    report_md_path = out_dir / f"acceptance_report_{args.profile}_{stamp}.md"

    result_payload: dict[str, Any] = {
        "profile": args.profile,
        "overall_status": overall_status,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_duration_s": round(time.perf_counter() - t_total, 2),
        "result_json_path": str(result_json_path),
        "env_snapshot": {
            "project_name": get_by_dotted_path(env_cfg, "project.name"),
            "project_code": get_by_dotted_path(env_cfg, "project.code"),
            "env": get_by_dotted_path(env_cfg, "project.env"),
            "frontend_url": effective_fe,
            "backend_url": get_by_dotted_path(env_cfg, "services.backend.url"),
            "browser_type": browser_type,
            "browser_headless": headless,
            "trace_mode": trace_mode,
            "auth_mode": get_by_dotted_path(env_cfg, "auth.mode"),
            "screenshot_dir": get_by_dotted_path(env_cfg, "paths.screenshot_dir"),
            "trace_dir": get_by_dotted_path(env_cfg, "paths.trace_dir"),
            "download_dir": get_by_dotted_path(env_cfg, "paths.download_dir"),
        },
        "stages": stages,
        "defects": defects,
        "rerun_commands": [
            f"python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile {args.profile}",
            "python .agents/skills/project-acceptance/scripts/verify_data_consistency.py",
            "python -m pytest case/test_misc.py::test_x04_seed_data --headless -q",
        ],
    }

    result_json_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "latest_result.json").write_text(
        json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    render_report(result_payload, output_path=report_md_path)
    render_report(result_payload, output_path=out_dir / "latest_report.md")

    print("=" * 72)
    print(f"[project-acceptance] 验收完成 | 档位={args.profile} | 结论={overall_status} | 耗时={result_payload['total_duration_s']}s")
    print(f"结构化结果: {result_json_path}")
    print(f"验收报告:   {report_md_path}")
    print("=" * 72)

    return 1 if overall_status == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
