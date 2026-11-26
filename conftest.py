# coding=utf-8
"""根级 pytest 配置：注册命令行级选项。

说明：pytest_addoption 必须在命令行解析前完成注册（根目录 conftest 在 parse 阶段即被加载，
而 case/ 下的子目录 conftest 解析期未必加载），故把选项注册放在根目录；
选项的读取与使用保留在 case/conftest.py 的 browser / context / page fixture 中。
"""


def pytest_addoption(parser):
    parser.addoption(
        "--browser",
        default=None,
        help="覆盖 settings.yaml 的 browser.type：chromium/chrome/edge/firefox/webkit"
        "（360/qq 自动归一为 chromium，safari 自动归一为 webkit）",
    )
    parser.addoption(
        "--headless",
        action="store_true",
        default=None,
        help="以无头模式运行浏览器（覆盖 settings.yaml 的 browser.headless）",
    )
    parser.addoption(
        "--headed",
        action="store_true",
        default=None,
        help="以有头模式运行浏览器（覆盖 settings.yaml 的 browser.headless）",
    )
    parser.addoption(
        "--pw-trace",
        choices=["on", "off", "retain-on-failure"],
        default=None,
        help="覆盖 settings.yaml 的 trace.mode（on / off / retain-on-failure）",
    )
