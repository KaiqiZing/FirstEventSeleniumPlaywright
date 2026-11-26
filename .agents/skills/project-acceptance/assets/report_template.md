# 《${project_name} 系统验收测试报告》

> **验收结论**：${overall_badge}  
> **执行档位**：`${profile}`  
> **报告生成时间**：${generated_at}  
> **总耗时**：${total_duration_s}s  

---

## 一、执行环境与配置快照（已脱敏）

| 配置项 | 当前值 |
| --- | --- |
| 项目名称 / 标识 | ${project_name}（`${project_code}`） |
| 目标环境 | `${env}` |
| 前端地址 | ${frontend_url} |
| 后端地址 | ${backend_url} |
| 浏览器配置 | `${browser_type}`（headless=${browser_headless}，trace=`${trace_mode}`） |
| 鉴权模式 | `${auth_mode}`（凭证已脱敏，未明文落盘） |

---

## 二、验收总览指标

| 验收阶段 | 状态 | 通过 / 总计 | 耗时 | 备注 |
| --- | :---: | :---: | :---: | --- |
| 1. 服务健康预检（Preflight） | ${preflight_status} | ${preflight_ratio} | ${preflight_duration} | ${preflight_note} |
| 2. API 契约校验 | ${api_status} | ${api_ratio} | ${api_duration} | ${api_note} |
| 3. UI 菜单与标签一致性 | ${ui_menu_status} | ${ui_menu_ratio} | ${ui_menu_duration} | ${ui_menu_note} |
| 4. Playwright 场景自动化 | ${pytest_status} | ${pytest_ratio} | ${pytest_duration} | ${pytest_note} |
| 5. 数据库与三方一致性核验 | ${data_status} | ${data_ratio} | ${data_duration} | ${data_note} |

---

## 三、各阶段验收明细

### 3.1 API 契约校验明细

${api_table}

### 3.2 UI 菜单与标签一致性明细

${ui_menu_section}

### 3.3 Playwright 场景自动化明细

${pytest_table}

### 3.4 数据库与三方一致性核验明细

${data_consistency_table}

---

## 四、阻塞项与缺陷归属清单

${defects_section}

---

## 五、取证产物与复测指引

- **结构化结果 JSON**：`${result_json_path}`
- **失败截图目录**：`${screenshot_dir}`
- **Playwright Trace 目录**：`${trace_dir}`（可用 `playwright show-trace <trace.zip>` 回放）
- **下载产物目录**：`${download_dir}`

### 复测命令

```bash
${rerun_commands}
```
