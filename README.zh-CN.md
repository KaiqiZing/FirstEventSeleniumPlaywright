# FirstEventSeleniumPlaywright

针对被测平台 **FirstSeleniumUIEvent**（Vue 3 + Element Plus 前端 `http://localhost:5173`，Flask 后端 `http://127.0.0.1:5050`）的独立 **Playwright + pytest** UI 自动化与标准化验收工程。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Playwright-Sync%20API-45ba4b.svg)](https://playwright.dev/python/)
[![pytest](https://img.shields.io/badge/tested%20with-pytest-green.svg)](https://docs.pytest.org/)

[English](README.md) | 简体中文

---

## 一、核心特性

- **六层单向架构**：`case → business → handle → base + common` + `util / config / log` 横切支撑；6 个 `*Element.ini` 外置定位资产零重写复用。
- **高效隔离执行**：Session 级 `Browser` 复用 + Function 级 `BrowserContext / Page` 隔离，兼顾速度与状态隔离。
- **可信断言体系**：页面日志区（`.result-box`）+ 后端 API + SQLite 只读直连（`I-18` / `E-03`）+ Playwright 全内核原生网络抓包（`E-01`）。
- **4 级失败取证**：2 层异常链 + 元素超时截图 + 失败页截图 + **Playwright Trace（`.zip`）**自动归档进 Allure。
- **配置驱动验收 Skill**：内置 `.agents/skills/project-acceptance/`，支持一键调度预检、API 契约、UI 菜单一致性、pytest 套件与数据库三方核验并输出标准 Markdown 报告。

---

## 二、目录结构

```text
FirstEventSeleniumPlaywright/
├── config/                   # settings.yaml（环境/浏览器/Trace）+ 6 个 *Element.ini（37 场景定位）
├── base/                     # find_element.py：INI -> Playwright Selector 双级缓存解析
├── common/                   # page_wait_common.py（自动等待+超时截图）+ exceptions.py（2 层异常链）
├── util/                     # browser_factory / network_recorder / sqlite_source / amount_util / digest_util / api_client
├── handle/                   # 场景元素操作层（FrameLocator / Shadow DOM / expect_popup / expect_download）
├── business/                 # 业务编排层（biz_step 异常打标 + allure.step）
├── case/                     # conftest.py（Fixture + 失败取证 Hook）+ 6 组 37 个 pytest 用例
├── demo/                     # test_menu_tag_consistency.py（6 大分类 / 37 界面菜单与颜色一致性 Demo）
├── .agents/skills/project-acceptance/  # 可跨项目复用的标准化验收 Agent Skill
└── run_tests.py              # 多模式测试入口（all / smoke / regression / allure）
```

---

## 三、快速开始

### 1. 环境准备

```bash
# 1) 启动被测系统（前端 :5173，后端 :5050）
# 2) 安装测试依赖（Python 3.11+，已在 3.13.5 + Playwright 1.62.0 验证）
cd FirstEventSeleniumPlaywright
pip install -r requirements.txt
python -m playwright install chromium   # 可选：未安装时自动回退本机 Chrome/Edge
```

### 2. 常用运行命令

```bash
# 冒烟 / 全量 / Allure 报告
python run_tests.py --mode smoke --headless
python run_tests.py --mode all --headless
python run_tests.py --mode allure --headless

# 指定浏览器与调试模式（chromium / chrome / edge / firefox / webkit）
python -m pytest case/ --browser chrome --headed
python -m pytest case/ --browser edge --pw-trace on
playwright show-trace logs/traces/trace_xxx.zip

# UI 菜单与标签/颜色一致性 Demo（37 页面）
python -m pytest demo/test_menu_tag_consistency.py -v -s

# 标准化验收 Agent Skill（输出 report/acceptance/latest_report.md）
python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile smoke
python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile full
```

---

## 四、Selenium vs Playwright vs 内置 AI 浏览器 实测对比

以下均为同一套被测系统（`http://localhost:5173/` + `http://127.0.0.1:5050`）上的真实跑批数据：

### 1. 全量 37 场景业务跑批对比

| 对比维度 | Selenium 4（改造前） | Playwright（改造后） | 内置 AI 浏览器（`/browser`） |
| --- | --- | --- | --- |
| **全量耗时** | ~5m30s（37 次冷启动浏览器） | **~3m49s（提速 ~31%）** | ~13m（多轮大模型推理交互） |
| **实测通过情况** | 32/33（另单独统计 E 组；`X-04` 后端 500） | **36/37**（自动化有效通过率 **100%**，仅 `X-04` 后端 500） | 35/37（`M-02` Webview `window.open` 限制 + `X-04` 后端 500） |
| **Token 成本** | 0 Token | **0 Token** | 每次跑批消耗多轮 AI Token |
| **深层校验能力** | SQLite 直读 + 仅 Chromium CDP 抓包 | SQLite 直读 + **全内核原生网络抓包** + `expect_download` 落盘 | 仅页面 UI 与日志（无落表直读 / 无底层网络取证） |
| **失败取证** | 异常链 + 双截图（3 级） | **4 级取证（新增 Playwright Trace `.zip` 全程回放）** | 文字总结 + 末帧截图 |
| **多浏览器 / 环境** | 依赖各浏览器 WebDriver 版本匹配 | `chromium`/`chrome`/`edge`/`firefox`/`webkit` 统一驱动 | 受限于内置 Webview 沙箱策略 |

### 2. 前端 37 界面菜单加载与标签/颜色一致性对比

| 验收方式 | 端到端耗时 | Token 消耗 | 核验结果 | 典型适用场景 |
| --- | :---: | :---: | --- | --- |
| **Playwright Demo**（`demo/test_menu_tag_consistency.py`） | **14.46s**（单页均值 287ms，**快约 16 倍**） | **0 Token** | 37/37 加载、文案、6 色切换全部通过 | 高频回归、CI 门禁 |
| **内置 AI 浏览器**（自然语言零代码） | ~233s（3m53s） | 持续消耗 Token | 37/37 结果 100% 吻合（并发现 `.crumb-code` 固定色细节） | 零代码快速探路、一次性视觉验收 |

> **实践建议（Hybrid AI Testing）**：高频核心回归、资金/SQLite 核对与 CI 门禁交给 **Playwright 代码**；一次性视觉验收、需求摸排与 Canvas/图表/主题对比度等 DOM 死角场景交给 **内置 AI 浏览器 / 视觉大模型** 兜底。

---

## 五、覆盖场景与红线说明

| 分组 | 用例文件 | 数量 | 核心覆盖点 |
| --- | --- | :---: | --- |
| 页面交互类 `I-01~I-18` | `case/test_interact.py` | 18 | 遮罩拦截、Stale、双层 iframe/Shadow DOM、拖拽上传、弹窗、160 条懒加载、I-17 父子金额勾稽、I-18 SQLite 一致性 |
| 等待响应类 `W-01~W-05` | `case/test_wait.py` | 5 | 慢接口 loading、SPA 路由、异步导出下载落盘、保存竞态、不稳定接口重试 |
| 多窗口类 `M-01~M-04` | `case/test_window.py` | 4 | 新标签页、OAuth 小窗自动关闭回传、新窗内嵌 iframe、弹窗拦截策略 |
| 兼容类 `C-01~C-02` | `case/test_compat.py` | 2 | 原生日期时间控件、运行环境与 `navigator.webdriver` 采集 |
| 疑难类 `X-01~X-04` | `case/test_misc.py` | 4 | 万能码 `1234` 验证码、webdriver 特征只读校验、Cookie 会话、服务端造数（`X-04` 已知后端 500） |
| 数据加密类 `E-01~E-04` | `case/test_crypt.py` | 4 | RSA-OAEP 传输加密与三方摘要互校、脱敏限时冷却、AES-GCM 密文库核对、报文解密与验签分离 |

**严格遵守红线**：不接 OCR 破解验证码、不注入反自动化伪装参数、不篡改浏览器弹窗策略、不替被测系统掩盖后端 500 缺陷。

---

## 六、延伸文档与许可证

- [标准化验收 Agent Skill 说明](.agents/skills/project-acceptance/SKILL.md)
- [业务口径与异常码规则](.agents/skills/project-acceptance/references/business_rules.md)
- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md) · 许可证：[MIT License](LICENSE)
