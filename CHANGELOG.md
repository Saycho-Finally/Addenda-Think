# 变更记录 (Changelog)

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.3.0] - 2026-10-05

### Added

- `exocortex/scaffold/budget_guard.py`：预算守卫由策略实现封装为独立模块
  （档位初始配置 + finish_reason 反馈环 + 分任务 thinking 开关 + 预算下限保护）
- `experiments/budget_guard_check.py`：离线自检，14 项全过

### Changed

- `scaffold` 包导出更新（`BudgetGuard` / `TaskTier` / `recommended_config`）

### Fixed

- `exocortex/__init__.py` 的 `__version__` 与 CHANGELOG 对齐（0.1.0 → 0.3.0）
- `experiments/cost_official.py` 的 docstring 指向了一个不存在的 .md（悬空引用），
  改为指向实际产物；该脚本的输出文件名改为 ASCII（`cost_official_2026-10-01.json`）

## [0.2.0] - 2026-10-03

- budget_guard 输出预算组件 + 三任务前后对比；E2 离线 coverage/selection 分析 + Pareto 图

## [0.1.0] - 2026-10-03

- E1 正式版：cd6 十一臂 + cd7 七臂等算力 Pareto（max 档 18 任务点无一最优）

