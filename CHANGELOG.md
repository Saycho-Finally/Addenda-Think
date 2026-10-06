# 变更记录 (Changelog)

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- `reports/E1数据盘点与重跑预算_2026-10-07.md`：现有 E1 数据的可用性盘点
  （完全可用 $0.548 / 部分可用 $4.559 / 不可用 $1.586，合计记录账单 $6.694）
  与重跑预算（最小方案 105 次调用 $0.29-0.63；完整方案 317 次调用 $2.35-2.89，
  因修复消除了浪费，完整重跑反而比原运行便宜约六成）
- 同报告结论：**干净成本无法从留存数据反推**——`Ledger` 的逐次记录只在内存，
  落盘仅臂级汇总，逐项进度文件（`progress_e1f_*.jsonl`）亦未归档；
  重跑前应先补 per-call 落盘

### Fixed

- **`e1_formal.py` 两处调用缺陷**（2026-10-07 外部评审触发，已复核确认）：
  ① Countdown 类先批量跑满 n 再丢弃 `n-1` 条重跑，被丢弃的调用**全额计费**——
  ×4 臂实际调用达名义的 1.58 倍、×8 达 1.34 倍（据 `results/e1f_*_ledger.json` 复算）；
  ② 串行段 `thinking=effort is not None` 中 `effort` 是臂名字符串，`"off"` 不是 None，
  导致 off 臂的串行调用实际开着思考（证据：off×1 的 reasoning=0，off×4 的 reasoning=182,047）。
  已改为跳过批量 + `thinking=effort != "off"`
- 口径更正：E2 报告"成本节省 17-53%"实为**样本条数**节省，成本结论**不成立**，
  需重跑重测；README 一句无出处的"成本比 1×max 低 56%~78%"方向相反（max×1 $0.11
  比 off×4 $0.48 便宜），已改写；阶段0 报告"反超 8 倍成本"更正为约 4.3 倍
- 新增 `reports/实现缺陷更正_2026-10-07.md`（含复算证据与影响范围）

### Added

- `reports/外部对照_查新_2026-10-06.md`：与 Overthinking（ACL 2026 Findings，
  arXiv:2604.10739）等测试时计算文献的对照（S2）。方向与已发表结论一致；
  本仓库增量在等算力协议、预算守卫模块与粒度二分实测，README/文档中
  相应表述按此校准

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
- 报告《E2 离线分析》中的跨仓库路径引用改为按功能描述
- `PPB_SAMPLE_ROOT` 的默认值改为以脚本位置解析（原相对路径依赖当前工作目录）

## [0.2.0] - 2026-10-03

- budget_guard 输出预算组件 + 三任务前后对比；E2 离线 coverage/selection 分析 + Pareto 图

## [0.1.0] - 2026-10-03

- E1 正式版：cd6 十一臂 + cd7 七臂等算力 Pareto（max 档 18 任务点无一最优）

