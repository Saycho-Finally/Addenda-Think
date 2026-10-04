"""E1：项目探索 vs 强度裸奔 的等算力 Pareto 对比（阶段 2 首个核心实验）。

设计（立项分析阶段 2 的 E1 + 等算力记账硬规矩）：
  强度曲线：单次调用，effort ∈ {off, low, high, max} → 4 个 (总token, acc) 点
  项目曲线：effort=low × N 次采样多数投票，N ∈ {2,4,8} → 3 个点（N=1 与强度曲线 low 重合）
  比较方式：在等总 completion token 处，项目曲线是否高于强度曲线
  （即项目是否把 Pareto 前沿外推，sleep-time compute 论文的检验框架）

Countdown 投票键：按表达式的**数值结果**投票（3*4 与 4*3 同票），
非法表达式的候选记废票——这是 Countdown 专属的正确投票语义。

用法：
  python experiments/e1_pareto.py --suite countdown6 --n 10 \
      --api base_url=https://api.deepseek.com model=deepseek-v4-pro key=...
"""

import argparse
import json
import os
import sys
import time
from fractions import Fraction

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from exocortex.adapter import GenRequest, adapter_from_config  # noqa: E402
from exocortex.ledger import Ledger  # noqa: E402
from exocortex.scaffold.verifier import coverage_selection_split  # noqa: E402
from exocortex.tasks import CountdownTask, MathBenchTask  # noqa: E402
from exocortex.tasks.countdown import safe_eval_expr  # noqa: E402

STRENGTH_LADDER = ["off", "low", "high", "max"]
N_LADDER = [2, 4, 8]


def build_suite(name: str, n: int):
    if name.startswith("countdown"):
        lv = int(name.replace("countdown", "") or 5)
        return CountdownTask(seed=42).make_suite(n_per_level=n, levels=(lv,))
    if name == "math500":
        return MathBenchTask().math500_suite(levels=(4, 5), n=n)
    raise ValueError(name)


def countdown_vote_key(text: str, numbers: list[int]) -> str | None:
    """投票键 = 表达式数值。提取失败/非法表达式 → None（废票）。"""
    expr = CountdownTask.extract_answer(text)
    if not expr:
        return None
    try:
        return str(safe_eval_expr(expr, numbers))
    except (ValueError, RecursionError, OverflowError):
        return None


def vote_by_value(candidates: list[str], numbers: list[int]) -> tuple[str | None, dict]:
    """数值多数投票。返回 (获胜值或 None, 票型)。"""
    from collections import Counter
    keys = [k for k in (countdown_vote_key(c, numbers) for c in candidates) if k]
    if not keys:
        return None, {}
    counter = Counter(keys)
    top, cnt = counter.most_common(1)[0]
    if list(counter.values()).count(cnt) > 1:
        return None, dict(counter)
    return top, dict(counter)


def check_by_value(item, value: str | None) -> bool:
    return value is not None and Fraction(item.target) == Fraction(value)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="countdown6")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--api", nargs="*", required=True,
                    help="key=value: base_url=... model=... key=...")
    ap.add_argument("--max-tokens", type=int, default=16384)
    args = ap.parse_args()

    cfg = dict(kv.split("=", 1) for kv in args.api)
    adapter = adapter_from_config({
        "type": "openai", "base_url": cfg["base_url"],
        "api_key": cfg.get("api_key") or cfg.get("key"), "model": cfg["model"],
    })
    items = build_suite(args.suite, args.n)
    ledger = Ledger(meta={"suite": args.suite, "n": len(items),
                          "model": cfg["model"], "ts": time.time()})

    def run_prompt(prompt: str, effort: str | None, thinking: bool = True):
        req = GenRequest(messages=[{"role": "user", "content": prompt}],
                         max_tokens=args.max_tokens, effort=effort,
                         thinking=thinking, temperature=0.7)
        g = adapter.generate(req)
        return g

    def run_prompt_n(prompt: str, effort: str, n: int):
        req = GenRequest(messages=[{"role": "user", "content": prompt}],
                         max_tokens=args.max_tokens, effort=effort,
                         thinking=True, temperature=0.7)
        return adapter.generate_n(req, n)

    results = {"meta": {"suite": args.suite, "model": cfg["model"],
                        "n_items": len(items)}, "arms": []}

    # ---- 强度曲线（单次 × off/low/high/max）
    for effort in STRENGTH_LADDER:
        arm = f"{cfg['model']}@{effort}"
        recs = []
        for i, item in enumerate(items):
            prompt = item.prompt if hasattr(item, "numbers") else item.question
            g = run_prompt(prompt, None if effort == "off" else effort,
                           thinking=effort != "off")
            ledger.log(arm, adapter.name, g)
            if hasattr(item, "numbers"):
                key = countdown_vote_key(g.text, item.numbers)
                ok = check_by_value(item, key)
            else:
                ok = MathBenchTask.check(item, g.text)
            recs.append(ok)
        results["arms"].append({
            "arm": arm, "kind": "strength", "effort": effort, "n_multi": 1,
            "accuracy": round(sum(recs) / len(recs), 4),
            **ledger.arm_summary(arm),
        })
        print(f"[strength] {arm} acc={results['arms'][-1]['accuracy']} "
              f"tok={ledger.arm_summary(arm)['completion_tokens']}", flush=True)

    # ---- 项目曲线（low × N 投票，顺序早停：连续 stop_k 票一致即停）
    stop_k = 3
    for n_multi in N_LADDER:
        arm = f"{cfg['model']}@lowx{n_multi}"
        recs = []
        cov_sel = []
        for i, item in enumerate(items):
            prompt = item.prompt if hasattr(item, "numbers") else item.question
            # 顺序采样早停：期望成本远低于固定 N（等算力账的关键修正）
            gens = []
            req = GenRequest(messages=[{"role": "user", "content": prompt}],
                             max_tokens=args.max_tokens, effort="low",
                             thinking=True, temperature=0.7)
            for _ in range(n_multi):
                g = adapter.generate(req)
                gens.append(g)
                ledger.log(arm, adapter.name, g)
                if hasattr(item, "numbers") and len(gens) >= stop_k:
                    keys = [k for k in (countdown_vote_key(x.text, item.numbers)
                                        for x in gens) if k]
                    if len(keys) >= stop_k and len(set(keys[-stop_k:])) == 1:
                        break
            if hasattr(item, "numbers"):
                top, _ = vote_by_value([g.text for g in gens], item.numbers)
                ok = check_by_value(item, top)
                keys = [k for k in (countdown_vote_key(g.text, item.numbers)
                                    for g in gens) if k]
                # 注意 item.target 可能是 int，键是 str(Fraction)，统一转 str 比较
                cov = str(item.target) in keys
                sel = ok if cov else None
                cov_sel.append({"coverage": cov, "selection": sel})
            else:
                from exocortex.scaffold.verifier import majority_vote
                top, _ = majority_vote([g.text for g in gens])
                ok = MathBenchTask.check(item, top or "")
                cov_sel.append({"coverage": None, "selection": None})
            recs.append(ok)
        cov_cov = sum(1 for c in cov_sel if c["coverage"]) / max(len(cov_sel), 1)
        results["arms"].append({
            "arm": arm, "kind": "external", "effort": "low", "n_multi": n_multi,
            "accuracy": round(sum(recs) / len(recs), 4),
            "coverage_rate": round(cov_cov, 4),
            **ledger.arm_summary(arm),
        })
        print(f"[external] {arm} acc={results['arms'][-1]['accuracy']} "
              f"cov={cov_cov:.2f} tok={ledger.arm_summary(arm)['completion_tokens']}",
              flush=True)

    # ---- Pareto 对账表
    ledger.dump(f"results/e1_pareto_{cfg['model']}_{args.suite}_ledger.json")
    out = f"results/e1_pareto_{cfg['model']}_{args.suite}_{time.strftime('%H%M%S')}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(json.dumps(results["arms"], ensure_ascii=False, indent=2))
    print("SAVED", out)


if __name__ == "__main__":
    main()
