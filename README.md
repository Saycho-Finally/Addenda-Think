# PPBExt-Sample

**一句话**：推理强度旋钮（effort 档位）的价值**只在任务的能力边缘存在，且集中在第一档**——本项目用三个模型（deepseek-flash / deepseek-v4-pro / 本地 Qwen3-4B）× 三类任务 × 18 个强度-采样任务点实测了这一点，并提出用**项目采样（N 路便宜采样 + 数值投票 + 早停）替代高价位档位**：在能力边缘与深边缘任务上，零思考 × 4 路采样（off×4）达到 100% 精度，成本为同精度替代方案（high×4）的约一半（cd6：$0.48 vs $1.02）。

> 作者：Saycho-Finally（独立研究者） ｜ AI 使用声明见 [AI_DISCLOSURE.md](AI_DISCLOSURE.md) ｜ License: MIT ｜ 依赖：requests（API 实验）｜ Python ≥3.10

---

## 这个仓库能做什么（四件事，均有实验数字）

1. **强度-精度曲线的三模型实测**——deepseek-flash、deepseek-v4-pro、本地 Qwen3-4B（budget forcing）在 GSM8K-100 / Countdown-5/6/7 / MATH-500 L4-5 上的完整 effort 档位曲线，18 个任务点的精度与逐笔成本。
2. **overthinking 的四次独立复现**——高价位档位（max）在 4 个独立场景中无一最优，其中 n=100 规模上 medium 档比 64-token 档**低 14 分**（0.77 vs 0.91，统计显著）。
3. **E1 等算力对账框架**——11 臂（4 强度档 × 1 + low×{2,4,8} + high×{2,4} + off×{4,8}）× 逐笔 hit/miss/token 记账，直接输出"每百分点精度值多少美元"的 Pareto 对账。
4. **项目采样的边界实测**——零思考 × 4 路采样（off×4）在能力边缘（Countdown-6，n=12）与深边缘（Countdown-7，n=6）双双 100%，成本为**同精度的高价档采样臂**（high×4）的约一半（cd6：$0.48 vs $1.02）。**注意**：off×4 的成本包含实现缺陷造成的浪费调用（见 CHANGELOG 2026-10-07），修复后应当更低；单档 max×1（$0.11）本身比 off×4 便宜，但它只有 0.83 精度。同时给出**不成立的边界**（详见「这个仓库不是什么」）。

## 核心结果：E1 等算力 Pareto（pro，off-peak，Countdown-6，n=12）

| 臂 | 精度 | off-peak 成本 |
|---|---|---|
| off×1（零思考） | 0.33 | $0.04 |
| low×1 | 0.83 | $0.12 |
| high×1 | 0.92 | $0.13 |
| **max×1** | **0.83** | $0.11 |
| low×2（早停投票） | 0.92 | $0.36 |
| **off×4（零思考采样）** | **1.00** | **$0.48** |
| low×4 | **1.00** | $0.86 |
| off×8 | **1.00** | $0.90 |
| high×4 | **1.00** | $1.02 |
| low×8 | **1.00** | $1.37 |

（Countdown-7 深边缘任务同构复现，见 [reports/阶段0_三模型全表_2026-10-02.md](reports/阶段0_三模型全表_2026-10-02.md) 第五节）

## 四条主要发现

1. **max 档在全部 18 个任务点上无一次最优**：overthinking 不是例外而是规律，且已被量化（cd6 上 max×1 是全表最差性价比：0.83 精度 @ $0.11，被 off×4 以 4 倍成本反超满分）。
2. **深度可被广度替代（边界：Countdown 类可验证任务）**：零思考 × 4 路采样 + 数值投票在能力边缘与深边缘双双满分，成本为同精度替代方案（high×4）的约一半到七成（cd6：$0.48 vs $1.02；cd7：$0.20 vs $0.29）。
3. **采样应配低价档**：low×4 与 high×4 同为满分，但 low 档单价约为一半——**档位溢价在采样范式下没有回报**。
4. **任务越接近能力边缘，第一档（off→low）的边际收益越大**：Countdown-7 上 off→low 从 0.50 → 1.00（+100%），是全部实验中最陡的档位增益。

## 这个仓库不是什么

先说边界：

- **不是"思考无用"的结论**。本实验的任务族是 Countdown（可数值验证的组合搜索）与 GSM8K/MATH 子集（有标准答案）；这些任务的判定器是确定性的（数值验证 / 程序校验），采样+投票的收益依赖这一前提。判定器不可用的任务（开放生成、主观评价）不在本文覆盖范围。
- **不是新 SOTA 方法**。采样+投票（self-consistency）与早停来自公开研究（见「引用的先行者」）；本仓库的增量是：**effort 档位旋钮出现后的等算力分配实测**、逐笔 hit/miss/token 的成本对账框架、以及 overthinking 的多场景量化。
- **不是大规模评估**。三个模型、少量任务族、多数为单种子；Countdown 是玩具级探针任务，GSM8K/MATH 子集样本量 50-100；多 seed 标准误与更多任务族列入后续工作。
- **不是对 Reasonix/DeepSeek 官方的复核**。所有数字来自本仓库脚本的独立运行，口径与官方后台一致（逐笔对账见 `results/`），但模型行为可能随版本更新变化。
- **不是有长期维护承诺的产品**。个人研究项目，业余维护；`results/` 是 2026-10-02/03 的研究快照。

反过来说，它**是**：一张把"哪条结论有多硬、哪个旋钮在什么条件下值多少钱"写清楚的三模型实验笔记，和一套逐笔可对账的成本框架。

## 仓库结构

```
exocortex/         核心库（adapter 多模型接入 / ledger 逐笔记账 / tasks 任务族 / scaffold 早停·验证·预算守卫·解剖）
experiments/       全部实验脚本（stage0 强度曲线 / e1 等算力对账 / anatomy 推理解剖 / 成本对账）
results/           原始运行数据（JSON，含逐笔 usage 与早停过程）
reports/           阶段 0 收官报告 / 三模型全表 / 架构前沿分析
```

## 复现

```bash
pip install requests
# 支出级自检（纯离线，零成本）：预算守卫档位配置与反馈环
python experiments/budget_guard_check.py
# 强度曲线（单模型 × 4 档 × n 题）
python experiments/stage0_curve.py --suite countdown6 --n 12 \
    --api base_url=https://api.deepseek.com model=deepseek-v4-pro key=$DEEPSEEK_API_KEY
# E1 等算力对账（11 臂，off-peak 时段运行成本减半）
python experiments/e1_formal.py --suite countdown6 --n 12 \
    --api base_url=https://api.deepseek.com model=deepseek-v4-pro key=$DEEPSEEK_API_KEY \
    --progress-file results/progress_e1f_cd6.jsonl
```

本地 4B 对照（6GB 显卡，budget forcing）：
```bash
python experiments/stage0_curve.py --suite gsm8k --n 100 --model_path <Qwen3-4B-Thinking 路径> \
    --ladder 64,256,1024,2048 --progress-file results/progress_local.jsonl
```

成本提示：E1 全套（cd6 n=12 + cd7 n=6）约 $6.7（off-peak）；GSM8K-100 本地 4B 约 19 小时（6GB 显卡受散热降频限制）。

## 引用的先行者

- Snell et al.（ICLR 2025）：test-time compute 的最优分配——总框架来源，本文在其未覆盖的 effort 旋钮维度做实测
- Self-Consistency（Wang et al. 2022）与早停变体（ESC/ASC/CGES）：采样与投票机制来源
- LLMThinkBench：基础任务上推理增益有限的先例
- Apple（2025）：推理链的三区制（有效/冗余/有害）——overthinking 的概念来源
- Reasonix：DeepSeek 前缀缓存纪律与三区会话
- NVIDIA Dynamo 文档：块价值分层（thinking token 零复用）
- Vercel Jev / AWS Strands Decider：决策模型品类（本文的"判定应项目化"立场的对照面）


---

## 贡献与引用

- 贡献指南见 [CONTRIBUTING.md](CONTRIBUTING.md)；行为准则见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 安全问题请走 [SECURITY.md](SECURITY.md) 的私密渠道（勿开公开 Issue）
- 版本变更见 [CHANGELOG.md](CHANGELOG.md)；学术引用格式见 [CITATION.cff](CITATION.cff)
- 许可：MIT
