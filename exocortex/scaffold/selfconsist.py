"""E1 项目探索臂：N 次低强度采样 + 多数投票。

对标实验：单次高强度调用。等算力约束由 Ledger 对账：
本臂总 completion tokens ≈ 高强度臂单次 completion tokens。
"""

from __future__ import annotations

from exocortex.adapter import GenRequest, ModelAdapter
from exocortex.ledger import Ledger
from exocortex.scaffold.verifier import majority_vote


class SelfConsistencyArm:
    def __init__(self, adapter: ModelAdapter, ledger: Ledger, arm_name: str):
        self.adapter = adapter
        self.ledger = ledger
        self.arm_name = arm_name

    def run(self, user_prompt: str, *, n: int, effort: str | None,
            max_tokens: int, temperature: float = 0.7,
            system: str | None = None, seed0: int = 0) -> dict:
        """跑 N 次采样并投票。返回答案、分布与原始候选。"""
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": user_prompt}
        ]
        req = GenRequest(messages=messages, max_tokens=max_tokens,
                         effort=effort, thinking=True, temperature=temperature)
        gens = self.adapter.generate_n(req, n)
        for g in gens:
            self.ledger.log(self.arm_name, self.adapter.name, g)
        answers = [g.text for g in gens]
        top, dist = majority_vote(answers)
        return {
            "answer": top,
            "distribution": dist,
            "candidates": answers,
            "n": n,
            "truncated": sum(1 for g in gens if getattr(g, "truncated", False)),
        }


class SingleHighEffortArm:
    """对照臂：单次高强度（大预算）调用。"""

    def __init__(self, adapter: ModelAdapter, ledger: Ledger, arm_name: str):
        self.adapter = adapter
        self.ledger = ledger
        self.arm_name = arm_name

    def run(self, user_prompt: str, *, effort: str | None, max_tokens: int,
            system: str | None = None) -> dict:
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": user_prompt}
        ]
        req = GenRequest(messages=messages, max_tokens=max_tokens,
                         effort=effort, thinking=True)
        g = self.adapter.generate(req)
        self.ledger.log(self.arm_name, self.adapter.name, g)
        return {"answer": g.text, "truncated": g.truncated, "reasoning_len": len(g.reasoning)}
