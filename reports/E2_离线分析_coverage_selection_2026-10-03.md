# E2 离线分析 ｜ coverage/selection 分解与早停动态（2026-10-03）

数据：E1 正式版 cd6（11 臂 × 12 题）+ cd7（7 臂 × 6 题）逐臂 coverage_rate / accuracy / 采样次数。
零 API 成本（全部离线计算）。

---

## 一、臂级 coverage/selection 分解

**Selection 损失 = coverage − accuracy**（coverage 高但 acc 低 = 投票选错；两者相等 = 选择无损失）。

- **cd6：11 臂全部 selection 损失 = 0.0000**
- **cd7：7 臂全部 selection 损失 = 0.0000**

**结论 A（可验证任务域）**：数值投票即无失败的选择器——coverage 内的多数投票零失败。
在 Countdown 类可验证任务上，selection 是**已解决的廉价步骤**（S0 的第四条结论获得臂级全量确认）。

**对 E2 的方向修正**：原设计"程序验证器作黑盒选择器"在这类任务上**增量空间为零**——
投票本身已经是验证器（数值键即谓词）。E2 的价值域转移：
1. **不可验证任务**（开放生成/主观评价）——selection 真正开放的地方
2. **置信度审计器**——为无法验证的 selection 标注可信度（DecisionCore 的 DecisionRecord 已含此字段）

## 二、早停动态

| 臂 | 名义采样 | 实际平均 | 节省 | 精度 |
|---|---|---|---|---|
| low×4 | 4 | 3.3 | 17% | 1.00 |
| low×8 | 8 | 3.8 | **53%** | 1.00 |
| high×4 | 4 | 3.3 | 17% | 1.00 |

**结论 B**：早停零精度损失（全部臂满分），成本节省 17-53%——**票型收敛即信息饱和**，
额外的采样在这个任务域是纯浪费。

## 三、Pareto 前沿图

`reports/figures/e1_pareto_cd6_cd7.png`（双面板）：

- **cd6 前沿**：off×1（0.33 @ $0.04）→ low×1/high×1（0.83-0.92 @ $0.12-0.13）→ **off×4（1.00 @ $0.48）**→ low×4/off×8（1.00 @ $0.86-0.90）→ high×4/low×8（1.00 @ $1.0+，被支配）
- **cd7 前沿**：off×1（0.50 @ $0.01）→ low×1（1.00 @ $0.04）→ off×4（1.00 @ $0.20）→ high×4（1.00 @ $0.29）

**读法**：两个任务的前沿形状一致——**陡升段（off→low）之后平台期**。max×1 在 cd6
被前沿支配（同价位 low×2/high×1 精度更高）；low×8 与 high×4 在 cd6 被完全支配
（off×4/low×4 同精度更便宜）。

## 四、决策外挂（DecisionCore）的输入

1. **verifiable 决策点的实证支撑**：可验证任务上 selection 零损失——DecisionCore 的
   program_verifier 光谱位在这类任务上是最优解（已实现并测试）
2. **E2 转向后的新实验设计**：open 决策点的 selection 质量需要一个**不可验证任务族**
   （候选：开放问答的 judge 一致性 / 代码评审的真人对照）——这是 E2 正式实验的下一步
3. **审计字段就位**：DecisionRecord 的 outcome_check 字段（可验证回填）在 Countdown
   上全量可填；不可验证任务的 outcome_check 将为空——两类决策的可信度差异由此显式化

## 五、结论

1. 可验证任务域：selection 零损失（18 臂），投票即验证——E2 在此域无增量，转向不可验证域
2. 早停零损失且省 17-53% 成本——票型收敛是可靠的信息饱和信号
3. Pareto 前沿形状跨任务一致：陡升段（off→low）→ 平台期；max 档全程被支配


---

## 七、LLM fusion 正式对照（2026-10-03 晚，追加实验）

> 数据：`addenda-decide/results/e2_llm_fusion_results.json`（复用第一轮 30 候选，
> LLM fusion 重跑，pro thinking-off + max=2500——fusion 是轻认知合并任务）

### 三层对照（均值，flash 评测口径）

| 层 | F1 | 说明 |
|---|---|---|
| best-single（最好单候选） | ~0（类型口径）/ 0.46-0.86（语义口径） | selection 的上限 |
| deterministic fusion（零 LLM 聚类） | 0.216 | 机械并集的底线 |
| **LLM fusion（Fusion-of-N 式，pro thinking-off）** | **0.716** | recall 全 1.0；t2 F1=1.000 零误报 |

### 结论 C（fusion 显著优于 selection，假设验证）

1. **LLM fusion（0.716）vs 最好单候选（类型口径 0 / 语义口径均值 ~0.6）**：合并显著优于选择
2. **LLM fusion vs deterministic fusion = 3.3 倍**：LLM 合并的语义去重能力远超机械聚类
3. **fusion recall 全 1.0**：5 个 gold bug 全覆盖（union 上界被 LLM fusion 完整兑现）
4. **budget_guard 机制第三次复现并被修复合用**：fusion（轻认知合并）用 thinking=False——
   分任务 thinking 开关在真实管线里的实战验证

### 决策外挂的最终答案（批判→假设→验证闭环）

- 可验证任务（E1）：selection 零损失，投票即验证 → `verifiable` 决策点用程序判定
- 不可验证任务（E2）：selection 损失巨大，**fusion 的 F1 显著高于最好单候选** → `open` 决策点的
  默认判定器从"选最好"改为**"合并"**（fusion 档），LLM judge 降级为 fusion 的质量抽检
- 决策模型的正确姿势：不是"挑一个"，是"合所有"——且合并可以由确定性程序 + 轻量 LLM 完成
