---
name: project-acceptance
description: >-
  Config-driven, zero-code-migration system acceptance skill for running preflight health checks,
  API contract validation, Playwright UI menu/scenario verification, read-only database three-way
  consistency checks, and standardized Markdown acceptance report generation. Use when the user asks
  to run project acceptance, smoke/full regression verification, data consistency auditing, or
  generate a formal acceptance test report.
---

# Project Acceptance Skill（标准化项目验收）

本 Skill 将项目验收封装为 **「核心入口 (`SKILL.md`) + 确定性执行层 (`scripts/`) + 可变配置层 (`references/`) + 交付模板层 (`assets/`)」** 四层结构，实现配置驱动执行与**跨项目零代码迁移**。

---

## 一、触发条件

当用户提出以下任一诉求时激活本 Skill：
- 执行项目验收 / 冒烟验收 / 发布前全量回归（如「跑一遍验收」「执行全量验收」「验证发布门禁」）；
- 核对页面/接口与落盘数据库的三方一致性（如金额分转元、密文库解密、异常码契约）；
- 验收前端左侧菜单、标签文案及分类色切换一致性；
- 生成标准《系统验收测试报告》。

---

## 二、目录与职责约定

| 文件 | 角色 | 跨项目迁移时 |
| --- | --- | --- |
| [SKILL.md](./SKILL.md) | 核心入口、全局 SOP、阻塞红线与输出规范 | 复用（零改动） |
| [scripts/run_acceptance.py](./scripts/run_acceptance.py) | 统一调度器：按 YAML 档位编排预检 / API / UI / 数据核验 / 报告生成 | 复用（零改动） |
| [scripts/verify_data_consistency.py](./scripts/verify_data_consistency.py) | 数据库只读直连 + API/页面/独立复算三方核验 + 日志扫描 | 复用（零改动） |
| [scripts/generate_report.py](./scripts/generate_report.py) | 结构化 JSON → 标准 Markdown 验收报告渲染器 | 复用（零改动） |
| [references/env_config.yaml](./references/env_config.yaml) | 环境地址、数据库动态元信息端点、鉴权脱敏配置（支持 `${ENV:-default}`） | **替换为新项目配置** |
| [references/acceptance_cases.yaml](./references/acceptance_cases.yaml) | 验收档位（profile）、API 契约、用例清单与门禁规则 | **替换为新项目用例** |
| [references/business_rules.md](./references/business_rules.md) | 项目业务口径、状态机流转、异常码字典与红线说明 | **替换为新项目口径** |
| [assets/report_template.md](./assets/report_template.md) | 标准《系统验收测试报告》Markdown 模板 | 按需微调 |

---

## 三、全局验收 SOP（5 步闭环）

### Step 1：读取业务口径与核对配置
- 按需阅读 [references/business_rules.md](./references/business_rules.md) 与 [references/env_config.yaml](./references/env_config.yaml)，确认目标环境地址、浏览器策略与鉴权环境变量已就绪（严禁在配置文件写入明文生产密码/Token）。

### Step 2：选择验收档位并一键执行
通过统一入口脚本 [scripts/run_acceptance.py](./scripts/run_acceptance.py) 触发确定性流水线：

```bash
# 1. 快速冒烟验收（推荐日常 PR / 改动后验证：预检 + API 契约 + 37页菜单/标签一致性 + P0冒烟 + 数据三方一致性）
python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile smoke

# 2. 核心验收（预检 + API + UI菜单 + 等待/多窗/兼容/加密用例 + 数据一致性）
python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile quick

# 3. 发布前全量验收（包含全部 37 场景 + 数据三方一致性）
python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile full

# 4. 单项专项验收
python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile api-only
python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile ui-menu
python .agents/skills/project-acceptance/scripts/run_acceptance.py --profile data-only
```

### Step 3：独立核验数据库与日志（可单独复跑）
```bash
python .agents/skills/project-acceptance/scripts/verify_data_consistency.py
```

### Step 4：门禁判定与缺陷归属
脚本依据 `references/acceptance_cases.yaml::blocking_rules` 自动输出三态结论：
- **`PASS`**：所有启用阶段 100% 通过，0 缺陷；
- **`CONDITIONAL_PASS`**：核心门禁与自动化脚本 100% 通过，仅命中已登记的 `known_backend_issue`（如被测后端 `POST /api/seed/new` HTTP 500），报告中必须显式标红为「待后端修复」；
- **`BLOCKED`**：服务预检失败、阻断级 API 失败、数据三方一致性失败、UI 菜单一致性失败或出现未预期用例失败。

### Step 5：渲染并交付标准验收报告
- 调度脚本自动产出结构化 JSON 与标准 Markdown 报告至 `report/acceptance/`（含 `latest_result.json` 与 `latest_report.md`）。
- 如需基于已有 JSON 重新套用模板渲染：
  ```bash
  python .agents/skills/project-acceptance/scripts/generate_report.py \
    --input report/acceptance/latest_result.json \
    --output report/acceptance/latest_report.md
  ```

---

## 四、阻塞红线（Hard Red Lines）

1. **服务预检失败立即阻断**：前后端不可达时禁止继续空跑后续 UI 用例，必须快速失败并明确提示启动指引。
2. **严禁绕过被测安全与校验机制**：不得接入 OCR 破解验证码、不得注入反自动化特征规避检测、不得篡改浏览器默认拦截逻辑来伪造通过。
3. **严禁替被测系统掩盖缺陷**：被测后端报错（如 HTTP 500）时必须如实记录为「被测系统缺陷」并留存证据，严禁跳过或放宽断言强行绿灯。
4. **严禁使用不可信断言口径**：金融金额禁止 `float` 直接比对（必须 `Decimal` + 容差）；加密场景禁止断言密文相等（必须比对独立复算摘要或按版本解密明文）。
5. **只读核验与数据自洁**：数据库核验必须以只读模式（`mode=ro`）连接；写库类验收前后须调用复位接口恢复环境。
6. **配置与凭证脱敏**：所有敏感 Token / 密码必须通过 `${ENV_VAR}` 注入，严禁明文出现在代码或生成的验收报告中。

---

## 五、输出交付规范

验收完成后向用户交付以下四要素：
1. **验收结论与档位**：明确给出 `PASS` / `CONDITIONAL_PASS` / `BLOCKED` 及总耗时；
2. **各阶段统计摘要**：预检、API 契约、UI 菜单一致性、Playwright 场景集、数据三方一致性的通过比；
3. **缺陷归属与证据路径**：清晰区分「被测系统缺陷」与「脚本/环境问题」，给出截图、Playwright Trace（`.zip`）与 JSON 路径；
4. **标准报告链接**：提供生成的 `report/acceptance/latest_report.md` 可点击路径及复测命令。

---

## 六、跨项目零代码迁移指南

将 `.agents/skills/project-acceptance/` 目录整体复制到新项目根目录后，**仅需修改 `references/` 下 3 个文件**：
1. 修改 `references/env_config.yaml`：配置新项目的前后端 URL、健康检查端点、鉴权环境变量与数据库元信息；
2. 修改 `references/acceptance_cases.yaml`：填入新项目的 API 契约、pytest 目标集、数据核验开关与门禁规则；
3. 更新 `references/business_rules.md`：记录新项目的核心业务口径、异常码字典与红线要求。
`SKILL.md`、`scripts/*` 与 `assets/report_template.md` 均可零代码改动直接运行。
