# coding=utf-8
"""将结构化验收结果 JSON 渲染为标准 Markdown《系统验收测试报告》。

设计原则：
- 仅依赖 Python 标准库（string.Template + json），零第三方模板依赖；
- 报告样式完全由 assets/report_template.md 驱动，跨项目可自由替换模板。

运行示例：
    python .agents/skills/project-acceptance/scripts/generate_report.py \
        --input report/acceptance/latest_result.json \
        --output report/acceptance/latest_report.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from string import Template
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = SKILL_DIR / "assets" / "report_template.md"


def _status_badge(status: str) -> str:
    mapping = {
        "PASS": "✅ PASS",
        "CONDITIONAL_PASS": "⚠️ 有条件通过（存在已知后端缺陷）",
        "FAIL": "❌ FAIL",
        "BLOCKED": "❌ BLOCKED（验收未通过）",
        "SKIPPED": "⏭️ SKIPPED",
    }
    return mapping.get(status, status)


def _overall_badge(status: str) -> str:
    mapping = {
        "PASS": "✅ **验收通过（PASS）**",
        "CONDITIONAL_PASS": "⚠️ **有条件通过（仅存在已登记的被测后端缺陷，自动化与核心门禁全绿）**",
        "BLOCKED": "❌ **验收不通过（BLOCKED，存在阻断项）**",
    }
    return mapping.get(status, status)


def _escape_cell(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def _render_api_table(stage: dict[str, Any]) -> str:
    if stage.get("status") == "SKIPPED":
        return "_本档位未启用 API 契约校验。_"
    items = stage.get("checks") or []
    if not items:
        return "_无 API 校验项。_"
    lines = [
        "| 编号 | 校验项 | 方法与路径 | 状态 | 耗时 | 实测详情 / 归属说明 |",
        "| --- | --- | --- | :---: | :---: | --- |",
    ]
    for it in items:
        note = it.get("details", "")
        if it.get("known_backend_issue") and it.get("status") != "PASS":
            note = f"[已知后端缺陷] {note}（{it['known_backend_issue']}）"
        lines.append(
            f"| `{it['id']}` | {_escape_cell(it['name'])} | `{it['method']} {it['path']}` | "
            f"{_status_badge(it['status'])} | {it.get('duration_s', 0)}s | {_escape_cell(note)} |"
        )
    return "\n".join(lines)


def _render_ui_menu_section(stage: dict[str, Any]) -> str:
    if stage.get("status") == "SKIPPED":
        return "_本档位未启用 UI 菜单与标签一致性验收。_"
    lines = [
        f"- **执行目标**：`{stage.get('target', '')}`",
        f"- **执行状态**：{_status_badge(stage.get('status', 'SKIPPED'))}（耗时 `{stage.get('duration_s', 0)}s`）",
    ]
    if stage.get("summary_line"):
        lines.append(f"- **核心实测**：{stage['summary_line']}")
    if stage.get("color_line"):
        lines.append(f"- **分类色校验**：{stage['color_line']}")
    if stage.get("error"):
        lines.append(f"- **异常信息**：`{_escape_cell(stage['error'])}`")
    return "\n".join(lines)


def _render_pytest_table(stage: dict[str, Any]) -> str:
    if stage.get("status") == "SKIPPED":
        return "_本档位未启用 Playwright 场景用例执行。_"
    cases = stage.get("cases") or []
    if not cases:
        return f"_未采集到细粒度用例（状态：{stage.get('status')}，备注：{stage.get('note', '')}）。_"
    lines = [
        "| 场景码 | 所属分组 | 优先级 | 用例名称 | 状态 | 耗时 | 说明 |",
        "| --- | --- | :---: | --- | :---: | :---: | --- |",
    ]
    for c in cases:
        note = c.get("message") or ""
        if c.get("known_backend_issue") and c.get("status") != "PASS":
            note = f"[已知后端缺陷: {c['known_backend_issue']}] {note}"
        lines.append(
            f"| `{c.get('scenario_id', '-')}` | {_escape_cell(c.get('group', '-'))} | "
            f"{c.get('priority', '-')} | `{c.get('name', '')}` | {_status_badge(c['status'])} | "
            f"{c.get('duration_s', 0)}s | {_escape_cell(note[:140])} |"
        )
    return "\n".join(lines)


def _render_data_table(stage: dict[str, Any]) -> str:
    if stage.get("status") == "SKIPPED":
        return "_本档位未启用数据库与三方一致性核验。_"
    checks = stage.get("checks") or []
    if not checks:
        return "_无数据核验项。_"
    lines = [
        "| 编号 | 核验项 | 状态 | 耗时 | 实测证据 |",
        "| --- | --- | :---: | :---: | --- |",
    ]
    for c in checks:
        lines.append(
            f"| `{c['id']}` | {_escape_cell(c['name'])} | {_status_badge(c['status'])} | "
            f"{c.get('duration_s', 0)}s | {_escape_cell(c.get('details', ''))} |"
        )
    return "\n".join(lines)


def _render_defects(defects: list[dict[str, Any]]) -> str:
    if not defects:
        return "✅ **无阻断项，无新增缺陷。**"
    lines = [
        "| 级别 | 来源阶段 | 标识 | 缺陷归属 | 现象与复现证据 |",
        "| :---: | --- | --- | --- | --- |",
    ]
    for d in defects:
        lines.append(
            f"| `{d.get('severity', 'major')}` | {d.get('stage', '-')} | `{d.get('id', '-')}` | "
            f"**{d.get('owner', '待定位')}** | {_escape_cell(d.get('summary', ''))} |"
        )
    return "\n".join(lines)


def _stage_summary_fields(stage: dict[str, Any] | None) -> tuple[str, str, str, str]:
    if not stage or stage.get("status") == "SKIPPED":
        return "⏭️ SKIPPED", "-", "0s", "当前档位未包含此阶段"
    status = _status_badge(stage.get("status", "SKIPPED"))
    total = stage.get("total", 0)
    passed = stage.get("passed", 0)
    ratio = f"{passed} / {total}" if total else "-"
    duration = f"{stage.get('duration_s', 0)}s"
    note = _escape_cell(stage.get("note", ""))
    return status, ratio, duration, note


def render_report(
    result_data: dict[str, Any],
    template_path: Path = DEFAULT_TEMPLATE,
    output_path: Path | None = None,
) -> str:
    template = Template(template_path.read_text(encoding="utf-8"))
    env_snap = result_data.get("env_snapshot") or {}
    stages = result_data.get("stages") or {}

    pf_st, pf_ra, pf_du, pf_no = _stage_summary_fields(stages.get("preflight"))
    ap_st, ap_ra, ap_du, ap_no = _stage_summary_fields(stages.get("api_checks"))
    um_st, um_ra, um_du, um_no = _stage_summary_fields(stages.get("ui_menu_consistency"))
    py_st, py_ra, py_du, py_no = _stage_summary_fields(stages.get("pytest_suites"))
    da_st, da_ra, da_du, da_no = _stage_summary_fields(stages.get("data_consistency"))

    rerun_lines = result_data.get("rerun_commands") or [
        "python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile smoke",
        "python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile full",
    ]

    rendered = template.safe_substitute(
        project_name=env_snap.get("project_name", "Unknown Project"),
        project_code=env_snap.get("project_code", "APP"),
        env=env_snap.get("env", "dev"),
        frontend_url=env_snap.get("frontend_url", "-"),
        backend_url=env_snap.get("backend_url", "-"),
        browser_type=env_snap.get("browser_type", "chromium"),
        browser_headless=str(env_snap.get("browser_headless", True)).lower(),
        trace_mode=env_snap.get("trace_mode", "retain-on-failure"),
        auth_mode=env_snap.get("auth_mode", "none"),
        overall_badge=_overall_badge(result_data.get("overall_status", "BLOCKED")),
        profile=result_data.get("profile", "smoke"),
        generated_at=result_data.get("generated_at", ""),
        total_duration_s=result_data.get("total_duration_s", 0),
        preflight_status=pf_st,
        preflight_ratio=pf_ra,
        preflight_duration=pf_du,
        preflight_note=pf_no,
        api_status=ap_st,
        api_ratio=ap_ra,
        api_duration=ap_du,
        api_note=ap_no,
        ui_menu_status=um_st,
        ui_menu_ratio=um_ra,
        ui_menu_duration=um_du,
        ui_menu_note=um_no,
        pytest_status=py_st,
        pytest_ratio=py_ra,
        pytest_duration=py_du,
        pytest_note=py_no,
        data_status=da_st,
        data_ratio=da_ra,
        data_duration=da_du,
        data_note=da_no,
        api_table=_render_api_table(stages.get("api_checks") or {"status": "SKIPPED"}),
        ui_menu_section=_render_ui_menu_section(stages.get("ui_menu_consistency") or {"status": "SKIPPED"}),
        pytest_table=_render_pytest_table(stages.get("pytest_suites") or {"status": "SKIPPED"}),
        data_consistency_table=_render_data_table(stages.get("data_consistency") or {"status": "SKIPPED"}),
        defects_section=_render_defects(result_data.get("defects") or []),
        result_json_path=result_data.get("result_json_path", "-"),
        screenshot_dir=env_snap.get("screenshot_dir", "logs/screenshots"),
        trace_dir=env_snap.get("trace_dir", "logs/traces"),
        download_dir=env_snap.get("download_dir", "downloads"),
        rerun_commands="\n".join(rerun_lines),
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(description="渲染标准 Markdown 系统验收测试报告")
    parser.add_argument("--input", required=True, help="结构化验收结果 JSON 路径")
    parser.add_argument("--template", default=str(DEFAULT_TEMPLATE), help="Markdown 模板路径")
    parser.add_argument("--output", required=True, help="输出 Markdown 报告路径")
    args = parser.parse_args()

    result_data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    render_report(result_data, Path(args.template), Path(args.output))
    print(f"验收报告已生成: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
