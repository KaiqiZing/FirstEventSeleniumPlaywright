"""多模式测试运行脚本（Playwright + pytest）。"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "report"
ALLURE_RESULTS_DIR = REPORT_DIR / "allure-results"
ALLURE_HTML_DIR = REPORT_DIR / "allure-html"


def run_command(command: list[str]) -> int:
    print("执行命令:", " ".join(command))
    completed = subprocess.run(command, cwd=BASE_DIR)
    return completed.returncode


def build_pytest_command(mode: str, extra_args: list[str]) -> list[str]:
    command = [sys.executable, "-m", "pytest"]
    if mode == "smoke":
        command.extend(["-m", "smoke"])
    elif mode == "regression":
        command.extend(["-m", "regression"])
    elif mode == "allure":
        ALLURE_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        command.extend(["--alluredir", str(ALLURE_RESULTS_DIR)])
    command.extend(extra_args)
    return command


def generate_allure_report() -> int:
    allure_bin = shutil.which("allure")
    if not allure_bin:
        print("未检测到 allure 命令，已保留结果目录:", ALLURE_RESULTS_DIR)
        return 0

    ALLURE_HTML_DIR.mkdir(parents=True, exist_ok=True)
    return run_command(
        [
            allure_bin,
            "generate",
            str(ALLURE_RESULTS_DIR),
            "-o",
            str(ALLURE_HTML_DIR),
            "--clean",
        ]
    )


def parse_args() -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description="FirstEventSeleniumPlaywright 全场景自动化运行脚本")
    parser.add_argument(
        "--mode",
        choices=["smoke", "regression", "all", "allure"],
        default="all",
        help="运行模式",
    )
    args, unknown = parser.parse_known_args()
    if unknown and unknown[0] == "--":
        unknown = unknown[1:]
    return args, unknown


def main() -> int:
    args, pytest_args = parse_args()
    exit_code = run_command(build_pytest_command(args.mode, pytest_args))
    if exit_code != 0:
        return exit_code

    if args.mode == "allure":
        return generate_allure_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
