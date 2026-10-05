"""预算守卫自检（全离线，零 API 成本）。

覆盖：档位初始配置 / finish_reason 反馈环的两个方向 / 边缘档位只升不降 /
下限保护 / thinking 开关。用例取自 reports/budget_guard_前后对比_2026-10-03.md
的实测情形。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from exocortex.scaffold.budget_guard import (BudgetGuard, MIN_TOKENS,  # noqa: E402
                                             TaskTier, recommended_config)

RESULTS = []


def check(name, cond, note=""):
    s = "PASS" if cond else "FAIL"
    RESULTS.append((name, s))
    print(f"  [{s}] {name}" + (f" ---- {note}" if note else ""))


def test_initial_config():
    print("档位初始配置")
    edge = BudgetGuard(TaskTier.EDGE_REASONING)
    check("边缘档位 thinking 开启且不封顶",
          edge.params() == {"thinking": True, "max_tokens": 16384},
          str(edge.params()))
    routine = BudgetGuard(TaskTier.ROUTINE_REASONING)
    check("常规档位 thinking 关闭且预算收紧",
          routine.params() == {"thinking": False, "max_tokens": 600},
          str(routine.params()))
    ext = BudgetGuard(TaskTier.EXTRACTION)
    check("提取档位预算最紧", ext.max_tokens == 400)
    check("推荐表带精度风险标注",
          "accuracy_risk" in recommended_config(TaskTier.EDGE_REASONING))


def test_feedback_up():
    print("反馈环：截断密集 → 升预算")
    g = BudgetGuard(TaskTier.EXTRACTION)
    # 复现报告 T1 max=800 的情形：预算不足，全部 length
    for _ in range(6):
        g.observe("length", 400)
    s = g.stats()
    check("截断率 1.0 被识别", s["truncation_rate"] == 1.0, str(s))
    change = g.recalibrate()
    check("预算上调", change.get("action") == "up"
          and change["after"] > change["before"], str(change))
    check("观测窗口被清空", g.stats()["n"] == 0)


def test_feedback_down():
    print("反馈环：stop 全量且余量大 → 降预算")
    g = BudgetGuard(TaskTier.OPEN_GENERATION)
    before = g.max_tokens
    # 复现报告 T2 baseline 的情形：10/10 stop，用量远低于预算
    for _ in range(4):
        g.observe("stop", 60)
    change = g.recalibrate()
    check("预算下调", change.get("action") == "down"
          and change["after"] < before, str(change))


def test_frozen_edge():
    print("边缘档位：只升不降")
    g = BudgetGuard(TaskTier.EDGE_REASONING)
    before = g.max_tokens
    for _ in range(4):
        g.observe("stop", 100)
    change = g.recalibrate()
    check("余量充足也不下调", change == {} and g.max_tokens == before,
          f"仍为 {g.max_tokens}")
    for _ in range(4):
        g.observe("length", 16384)
    up = g.recalibrate()
    check("截断时仍可上调", up.get("action") == "up", str(up))


def test_floor():
    print("下限保护")
    g = BudgetGuard(TaskTier.EXTRACTION, down_factor=0.1)
    for _ in range(20):
        for _ in range(2):
            g.observe("stop", 10)
        g.recalibrate()
    check("预算不会低于该档位下限",
          g.max_tokens >= MIN_TOKENS[TaskTier.EXTRACTION],
          f"{g.max_tokens} >= {MIN_TOKENS[TaskTier.EXTRACTION]}")


def test_thinking_switch():
    print("分任务 thinking 开关")
    g = BudgetGuard(TaskTier.ROUTINE_REASONING)
    check("常规档默认关闭", g.params()["thinking"] is False)
    g.set_thinking(True)
    check("可显式开启", g.params()["thinking"] is True)
    r = g.report()
    check("报告含档位与参数", r["tier"] == "routine_reasoning"
          and "params" in r)


if __name__ == "__main__":
    print("=" * 60)
    print("预算守卫自检（离线）")
    print("=" * 60)
    test_initial_config()
    test_feedback_up()
    test_feedback_down()
    test_frozen_edge()
    test_floor()
    test_thinking_switch()
    print("=" * 60)
    n_pass = sum(1 for r in RESULTS if r[1] == "PASS")
    print(f"总计：{n_pass}/{len(RESULTS)} PASS")
    print("BUDGET_GUARD_OK" if n_pass == len(RESULTS) else "BUDGET_GUARD_FAIL")
    sys.exit(0 if n_pass == len(RESULTS) else 1)
