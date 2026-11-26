# FirstEventSeleniumPlaywright

Independent, self-contained **Playwright + pytest** UI automation and standardized acceptance suite for **FirstSeleniumUIEvent** (Vue 3 + Element Plus frontend at `http://localhost:5173`, Flask backend at `http://127.0.0.1:5050`).

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Playwright-Sync%20API-45ba4b.svg)](https://playwright.dev/python/)
[![pytest](https://img.shields.io/badge/tested%20with-pytest-green.svg)](https://docs.pytest.org/)

English | [简体中文](README.zh-CN.md)

---

## Highlights

- **6-Layer Unidirectional Architecture**: `case → business → handle → base + common` with cross-cutting `util / config / log`; all 6 external `*Element.ini` locator files reused as-is.
- **Fast Isolated Execution**: Session-scoped `Browser` + function-scoped `BrowserContext / Page` for speed without losing cookie/storage/popup isolation.
- **Trusted Multi-Source Assertions**: Bottom result log + backend API + read-only SQLite checks (`I-18` / `E-03`) + cross-browser native Playwright network capture (`E-01`).
- **4-Tier Failure Forensics**: 2-layer exception chain + element screenshot + page screenshot + **Playwright Trace (`.zip`)** archived to Allure.
- **Reusable Acceptance Agent Skill**: Config-driven `.agents/skills/project-acceptance/` orchestrating preflight, API contracts, UI menu checks, pytest suites, DB three-way consistency, and Markdown report rendering.

---

## Structure

```text
FirstEventSeleniumPlaywright/
├── config/                   # settings.yaml + 6 *Element.ini files (37 scenarios)
├── base/                     # find_element.py: INI -> Playwright Selector cache
├── common/                   # page_wait_common.py + exceptions.py (2-layer chain)
├── util/                     # browser_factory / network_recorder / sqlite_source / amount_util / digest_util / api_client
├── handle/                   # Scenario operations (FrameLocator / Shadow DOM / expect_popup / expect_download)
├── business/                 # Business orchestration (biz_step + allure.step)
├── case/                     # conftest.py (fixtures + failure hook) + 37 pytest cases
├── demo/                     # test_menu_tag_consistency.py (37-page menu/tag/color check)
├── .agents/skills/project-acceptance/  # Portable config-driven acceptance Agent Skill
└── run_tests.py              # Multi-mode CLI runner (all / smoke / regression / allure)
```

---

## Quick Start

```bash
# Prerequisites: start SUT frontend (:5173) & backend (:5050), Python 3.11+
cd FirstEventSeleniumPlaywright
pip install -r requirements.txt
python -m playwright install chromium   # optional; auto-falls back to local Chrome/Edge

# Run tests
python run_tests.py --mode smoke --headless
python run_tests.py --mode all --headless
python -m pytest case/ --browser chrome --headed
python -m pytest demo/test_menu_tag_consistency.py -v -s

# Run standardized Acceptance Agent Skill
python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile smoke
python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile full
```

---

## Benchmark: Selenium vs Playwright vs Built-in AI Browser

Measured against the same SUT (`http://localhost:5173/` + `http://127.0.0.1:5050`):

### 1. Full 37-Scenario Batch Run

| Dimension | Selenium 4 (Before) | Playwright (Current) | Built-in AI Browser (`/browser`) |
| --- | --- | --- | --- |
| **Total Duration** | ~5m30s (37 cold launches) | **~3m49s (~31% faster)** | ~13m (multi-turn LLM inference) |
| **Pass Result** | 32/33 (+ E-group separate; `X-04` backend 500) | **36/37** (**100%** script pass rate; only `X-04` backend 500) | 35/37 (`M-02` Webview `window.open` limit + `X-04` backend 500) |
| **Token Cost** | 0 Token | **0 Token** | High per-run LLM token cost |
| **Assertion Depth** | SQLite + Chromium-only CDP | SQLite + **cross-browser native network capture** + `expect_download` | UI & logs only (no DB / wire capture) |
| **Failure Evidence** | Exception chain + screenshots | **4-tier (+ Playwright Trace `.zip` replay)** | Summary + final screenshot |

### 2. 37-Page UI Menu, Tag & Color Consistency Check

| Approach | End-to-End Time | Token Cost | Result | Best Fit |
| --- | :---: | :---: | --- | --- |
| **Playwright Demo** (`demo/test_menu_tag_consistency.py`) | **14.46s** (**~16x faster**, 287ms/page) | **0 Token** | 37/37 passed (all 6 category colors matched) | Frequent regression & CI gates |
| **Built-in AI Browser** (zero-code natural language) | ~233s (3m53s) | Multi-turn tokens | 37/37 identical findings (also flagged `.crumb-code` fixed color) | Ad-hoc visual checks & exploration |

---

## Scenario Groups (37 Cases)

| Group | Test Module | Count | Scope |
| --- | --- | :---: | --- |
| Interaction `I-01~I-18` | `case/test_interact.py` | 18 | Overlay, stale DOM, nested iframe/Shadow DOM, drag/upload, dialogs, 160-row lazy load, parent-child amounts, SQLite consistency |
| Wait `W-01~W-05` | `case/test_wait.py` | 5 | Slow API loading, SPA routing, async export download, save race, flaky API retry |
| Multi-Window `M-01~M-04` | `case/test_window.py` | 4 | New tab, OAuth auto-closing popup, window + iframe, popup blocking policy |
| Compatibility `C-01~C-02` | `case/test_compat.py` | 2 | Native date/time inputs, runtime environment & `navigator.webdriver` |
| Misc `X-01~X-04` | `case/test_misc.py` | 4 | Universal CAPTCHA `1234`, read-only webdriver check, cookie session, seeding (`X-04` known backend 500) |
| Encryption `E-01~E-04` | `case/test_crypt.py` | 4 | RSA-OAEP transport + digest cross-check, masking/cooldown, AES-GCM vault, envelope decrypt vs signature verify |

---

## Docs & License

- [Acceptance Agent Skill](.agents/skills/project-acceptance/SKILL.md)
- [Business Rules & Error Codes](.agents/skills/project-acceptance/references/business_rules.md)
- [Contributing](CONTRIBUTING.md) · [MIT License](LICENSE)
