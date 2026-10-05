"""预算守卫：按任务档位给输出预算，并用 finish_reason 统计反馈调节。

依据（见 reports/budget_guard_前后对比_2026-10-03.md 的三条实测规律）：

  1. 输出省钱的容许度 = 任务离能力边缘的距离
     —— 能力边缘任务（Countdown-6 级）封顶即崩：max=800 时思考吃光预算，
        答案根本没有生成（6/6 length，精度归零）
  2. max_tokens 封顶是危险杠杆，必须按任务类型校准初始值
     —— 公开资料里"封顶省 40-60%"只在思考较短的任务上成立
  3. finish_reason 是自动校准的完备信号
     —— length 密集 = 预算不足；stop 全量 = 预算过松

本模块实现三件事：预算封顶（按档位给初始值）／finish_reason 反馈环／
分任务 thinking 开关。纯确定性实现，不调模型，可离线复现。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskTier(str, Enum):
    """任务档位：决定初始预算与 thinking 开关。"""
    EDGE_REASONING = "edge_reasoning"        # 能力边缘推理（Countdown-6/7 级）
    ROUTINE_REASONING = "routine_reasoning"  # 常规推理（Countdown-5 级）
    EXTRACTION = "extraction"                # 摘要 / 提取 / 分类
    OPEN_GENERATION = "open_generation"      # 不可验证生成


# 初始配置：实测校准值（报告第四节的分任务推荐配置表）
INITIAL_CONFIG = {
    TaskTier.EDGE_REASONING: {"thinking": True, "max_tokens": 16384,
                              "frozen": True},
    TaskTier.ROUTINE_REASONING: {"thinking": False, "max_tokens": 600,
                                 "frozen": False},
    TaskTier.EXTRACTION: {"thinking": False, "max_tokens": 400,
                          "frozen": False},
    TaskTier.OPEN_GENERATION: {"thinking": False, "max_tokens": 1024,
                               "frozen": False},
}

# 预算下限：避免反馈环把预算压到无法生成答案
MIN_TOKENS = {
    TaskTier.EDGE_REASONING: 8192,
    TaskTier.ROUTINE_REASONING: 256,
    TaskTier.EXTRACTION: 128,
    TaskTier.OPEN_GENERATION: 256,
}


@dataclass
class Observation:
    """一次调用的完成信号。"""
    finish_reason: str      # stop / length
    completion_tokens: int


class BudgetGuard:
    """按档位给预算，并用 finish_reason 统计反馈调节。

    调节规则（阈值可配）：
      - 截断率超过 tolerance → 预算乘 up_factor
      - 全部 stop 且平均用量低于 max_tokens 的 headroom_ratio → 预算乘 down_factor
      - 边缘档位 frozen：只升不降（实测封顶即精度归零）
    """

    def __init__(self, tier: TaskTier, tolerance: float = 0.2,
                 up_factor: float = 2.0, down_factor: float = 0.5,
                 headroom_ratio: float = 0.5, config: dict | None = None):
        cfg = dict(config or INITIAL_CONFIG[tier])
        self.tier = tier
        self.thinking = cfg["thinking"]
        self.max_tokens = cfg["max_tokens"]
        self.frozen = cfg.get("frozen", False)
        self.tolerance = tolerance
        self.up_factor = up_factor
        self.down_factor = down_factor
        self.headroom_ratio = headroom_ratio
        self.observations: list[Observation] = []
        self.adjustments: list[dict] = []

    # ---- 消费端接口 ----

    def params(self) -> dict:
        """当前建议的请求参数。"""
        return {"thinking": self.thinking, "max_tokens": self.max_tokens}

    def set_thinking(self, on: bool) -> None:
        """分任务 thinking 开关（简单任务的主要省法来源）。"""
        self.thinking = bool(on)

    def observe(self, finish_reason: str, completion_tokens: int) -> None:
        """记录一次调用的完成信号。"""
        self.observations.append(Observation(finish_reason,
                                             int(completion_tokens)))

    # ---- 反馈环 ----

    def stats(self) -> dict:
        n = len(self.observations)
        if n == 0:
            return {"n": 0, "truncation_rate": 0.0, "stop_rate": 0.0,
                    "mean_tokens": 0.0}
        n_len = sum(1 for o in self.observations if o.finish_reason == "length")
        mean_tok = sum(o.completion_tokens for o in self.observations) / n
        return {"n": n,
                "truncation_rate": round(n_len / n, 4),
                "stop_rate": round((n - n_len) / n, 4),
                "mean_tokens": round(mean_tok, 1)}

    def recalibrate(self) -> dict:
        """按累计观测调一次预算；返回本次调整（未调整则返回空字典）。

        每次调整后清空观测窗口，避免同一批信号被重复消费。
        """
        s = self.stats()
        if s["n"] == 0:
            return {}
        before = self.max_tokens
        action = None

        if s["truncation_rate"] > self.tolerance:
            self.max_tokens = int(before * self.up_factor)
            action = "up"
        elif s["stop_rate"] == 1.0 and \
                s["mean_tokens"] < before * self.headroom_ratio:
            if not self.frozen:
                self.max_tokens = max(int(before * self.down_factor),
                                      MIN_TOKENS[self.tier])
                action = "down"

        if action is None or self.max_tokens == before:
            self.observations.clear()
            return {}
        change = {"action": action, "before": before,
                  "after": self.max_tokens, "evidence": s}
        self.adjustments.append(change)
        self.observations.clear()
        return change

    def report(self) -> dict:
        return {"tier": self.tier.value, "params": self.params(),
                "frozen": self.frozen, "n_adjustments": len(self.adjustments),
                "last_window": self.stats()}


def recommended_config(tier: TaskTier) -> dict:
    """分任务推荐配置（报告第四节的表，附精度风险标注）。"""
    risk = {
        TaskTier.EDGE_REASONING: "无（封顶即崩，不封顶）",
        TaskTier.ROUTINE_REASONING: "无（实测零损失）",
        TaskTier.EXTRACTION: "无（结构完整率未降）",
        TaskTier.OPEN_GENERATION: "需效果代理监控（不可验证）",
    }
    return {**INITIAL_CONFIG[tier], "accuracy_risk": risk[tier]}
