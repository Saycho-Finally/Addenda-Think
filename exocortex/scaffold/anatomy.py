"""阶段 1：高强度思维链解剖。

立项分析的问题：强度旋钮拧大的到底是什么？本模块把 reasoning 文本按
四类事件（探索/验证/回溯/工作记忆管理）做规则标注，输出每千 token 事件密度。

方法说明：规则标注（中英文特征词正则）是阶段 1 的频次坐标，语义级标注
（人工/模型判定事件边界）留待有语料后做抽样校验。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 四类事件的触发模式（R1 类思维链的中英文特征词，小写匹配）
PATTERNS: dict[str, list[str]] = {
    "exploration": [
        r"\bwait\b", r"\balternatively\b", r"\bmaybe\b", r"\banother way\b",
        r"\blet me try\b", r"\bor perhaps\b", r"\bwhat if\b",
        r"等等", r"或者说", r"另一个思路", r"换个角度", r"换个思路",
        r"另一种", r"再试", r"不妨", r"或者可以",
    ],
    "verification": [
        r"\bcheck\b", r"\bverify\b", r"\bconfirm\b", r"\bdouble.check\b",
        r"\bmake sure\b", r"\blet me confirm\b",
        r"检查", r"验证", r"核对", r"代入", r"检验", r"确认",
        r"确保", r"核算", r"复核",
    ],
    "backtracking": [
        r"\bmistake\b", r"\bwrong\b", r"\bredoit\b", r"\blet me redo\b",
        r"\bscratch that\b", r"\bI made an error\b", r"\bactually\b",
        r"回到", r"重来", r"重新", r"刚才错", r"不对，", r"算错",
        r"推翻", r"撤销", r"出错了", r"失误",
    ],
    "memory_mgmt": [
        r"\bgiven that\b", r"\bwe have\b", r"\bso far\b", r"\bto summarize\b",
        r"\bknown\b", r"\brecall\b",
        r"已知", r"条件是", r"列出", r"回顾", r"整理一下", r"到目前为止",
        r"现在有", r"记下", r"综上信息",
    ],
}
COMPILED = {k: [re.compile(p, re.IGNORECASE) for p in v] for k, v in PATTERNS.items()}


@dataclass
class AnatomyReport:
    arm: str
    task: str
    n_samples: int
    n_tokens: int
    counts: dict = field(default_factory=dict)      # 事件 -> 总次数
    density_per_kilo: dict = field(default_factory=dict)  # 事件 -> 次/千token

    def to_dict(self) -> dict:
        return {
            "arm": self.arm, "task": self.task, "n_samples": self.n_samples,
            "n_tokens": self.n_tokens,
            "counts": self.counts,
            "events_per_1k_tokens": {k: round(v, 3) for k, v in self.density_per_kilo.items()},
        }


def analyze_reasoning(reasoning: str, tokens: int | None = None) -> dict:
    """单条思维链的事件计数。tokens 不传则按 ~4 字符/token 估算（中英混合粗估）。"""
    if tokens is None:
        tokens = max(len(reasoning) // 4, 1)
    counts = {}
    for ev, regexes in COMPILED.items():
        counts[ev] = sum(len(rx.findall(reasoning)) for rx in regexes)
    return {"tokens": tokens, "counts": counts}


def aggregate(reports: list[dict], arm: str, task: str) -> AnatomyReport:
    """把多条 analyze_reasoning 的输出聚合成密度报告。"""
    total_tokens = sum(r["tokens"] for r in reports) or 1
    merged: dict[str, int] = {}
    for r in reports:
        for ev, c in r["counts"].items():
            merged[ev] = merged.get(ev, 0) + c
    density = {ev: c * 1000 / total_tokens for ev, c in merged.items()}
    return AnatomyReport(arm=arm, task=task, n_samples=len(reports),
                         n_tokens=total_tokens, counts=merged,
                         density_per_kilo=density)
