# 项目协作与 Git 提交规范（Plan-Driven Commit Checkpoints）

## 1. 按执行计划设置 Commit 检查点
- 凡涉及多步骤开发、架构改造或模块重构的任务，**先制定执行计划**，并将任务拆分为若干可独立验证的阶段（Phase / Step）。
- 在执行计划中为每个阶段显式标注 **Commit 检查点**（明确本阶段纳入的文件范围与预期提交类型）。
- 若执行中途调整或拆分计划，同步更新后续阶段的 Commit 检查点。

## 2. 逐阶段验证与原子提交
- **每完成一个计划阶段，且通过本阶段最小验证**（如语法/收集检查、关联分组 `pytest` 或脚本实测）后，立即执行一次原子提交，再进入下一阶段。
- 提交前只 `git add` 本阶段相关文件，**禁止将多个不相关阶段或模块混在同一次大 commit 中**，也禁止提交未通过验证的半成品。
- 提交信息统一采用 Conventional Commits 格式：
  - `feat(<scope>): ...`（新功能 / 新模块）
  - `fix(<scope>): ...`（缺陷修复）
  - `refactor(<scope>): ...`（架构或代码重构）
  - `test(<scope>): ...`（用例或 Demo 补充）
  - `docs: ...` / `chore(<scope>): ...`（文档、配置、规则与工程脚手架）

## 3. 提交前自检与推送安全红线
- 每次 `git commit` 前检查 `git status --short`，确保 `logs/`、`report/`、`downloads/`、`docs/` 等忽略目录及临时文件未被误入库。
- 默认仅执行本地 `git commit`，**未经用户明确指令，禁止自动执行 `git push`、`git push --force` 或重写远端历史**。
