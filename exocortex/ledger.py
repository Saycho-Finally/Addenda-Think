"""Ledger：等算力记账器。

立项分析的方法论硬规矩：任何"低强度×外挂 vs 高强度裸奔"的对比必须在
等总 completion token + 报告 wall-clock 的约束下做，否则测的是噪声
（对应 PPBExt-Knowledge 三分解的血统：不匹配算力的对比是无效对比）。

本模块只做一件事：把每次调用的真实开销记下来，汇总成两臂对账表。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field


@dataclass
class CallRecord:
    arm: str                # 实验臂名，如 "high@4096" / "low256×N8"
    adapter: str
    prompt_tokens: int
    completion_tokens: int  # 含思考
    reasoning_tokens: int | None
    wall_clock: float
    ts: float = field(default_factory=time.time)


class Ledger:
    def __init__(self, meta: dict | None = None):
        self.meta = meta or {}
        self.calls: list[CallRecord] = []

    def log(self, arm: str, adapter_name: str, gen) -> None:
        self.calls.append(CallRecord(
            arm=arm, adapter=adapter_name,
            prompt_tokens=getattr(gen, "prompt_tokens", 0),
            completion_tokens=getattr(gen, "completion_tokens", 0),
            reasoning_tokens=getattr(gen, "reasoning_tokens", None),
            wall_clock=getattr(gen, "wall_clock", 0.0),
        ))

    def arm_summary(self, arm: str) -> dict:
        rows = [c for c in self.calls if c.arm == arm]
        comp = sum(c.completion_tokens for c in rows)
        prompt = sum(c.prompt_tokens for c in rows)
        r_tok = [c.reasoning_tokens for c in rows if c.reasoning_tokens is not None]
        return {
            "arm": arm,
            "n_calls": len(rows),
            "completion_tokens": comp,
            "prompt_tokens": prompt,
            "reasoning_tokens": sum(r_tok) if r_tok else None,
            "wall_clock": round(sum(c.wall_clock for c in rows), 3),
        }

    def equal_compute_report(self) -> dict:
        """全臂对账。比对基准：每臂 completion token 总量与 wall-clock。"""
        arms = sorted({c.arm for c in self.calls})
        rep = {"meta": self.meta, "arms": [self.arm_summary(a) for a in arms]}
        comps = [a["completion_tokens"] for a in rep["arms"]]
        if comps and max(comps) > 0:
            base = max(comps)
            for a in rep["arms"]:
                a["completion_ratio_vs_max"] = round(a["completion_tokens"] / base, 4) if base else None
        return rep

    def dump(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.equal_compute_report(), f, ensure_ascii=False, indent=2)
