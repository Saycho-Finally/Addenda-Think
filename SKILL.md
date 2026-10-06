---
name: ppb-sample
description: "推理强度与采样广度的等算力分配：三模型矩阵、十八任务点 Pareto 与输出预算守卫。适用于「该不该开思考模式」「采样几次最划算」「输出成本过高」的场景。"
---

# ppb-sample

> **数据状态：完善中（2026-10-07）**：成本类数字需重跑才能出（实现缺陷已修，未重跑）。
> 本技能当前**只能用于精度类结论**（档位选择、采样是否有帮助），
> **不要**引用其中的成本对比。详见仓库 `DATA_STATUS.md`。

## 能力

- 强度×采样矩阵实测（三模型 / 18 任务点 / 逐笔成本对账）
- 等算力 Pareto 前沿（含 max 档全程无最优、off×4 满分 @ high×4 半价等实测结论）
- 早停投票（票型收敛即停，零精度损失；**样本条数**省 17-53%，**成本**节省须按修复后的实现重测，见 CHANGELOG 2026-10-07）
- budget_guard 输出预算守卫（finish_reason 反馈环 + 分任务 thinking 开关）

## 何时使用

- 任务逼近模型能力边缘（需要强度档位决策）
- 输出 token 成本占比高（思考 token 是主要开销）
- 需要低成本高可靠的采样配置

## 接口

`from exocortex.scaffold.budget_guard import BudgetGuard`；采样与早停在 `experiments/e1_formal.py`。

## 边界

结论基于 Countdown/GSM8K/MATH 子集；任务域与样本量局限照实标注。

---

*本技能为 PPBExt-Sample 仓库的 agent 可加载形态（SKILL.md 标准）。完整文档与数据见仓库 README。*
