"""E1 正式版：外挂探索 vs 强度裸奔的等算力 Pareto 对比（扩展臂矩阵）。

相对首战（e1_pareto.py）的扩展：
  1. 外挂曲线从 low×N 扩展到 off×N（便宜海量采样）与 high×N（贵档采样）——
     回答"采样应该配哪个档"而不是"low 采样是否有效"
  2. 双任务：cd6（pro 能力边缘）+ cd7（深边缘），由 --suite 分别运行
  3. 逐题进度 JSONL 落盘（长批可观测性）
  4. 等算力记账附美元换算（off-peak 价，DeepSeek v4-pro）

臂矩阵（每任务）：
  strength : off / low / high / max            （4 臂，单次）
  external : low×{2,4,8} + high×{2,4} + off×{4,8}（7 臂，顺序早停 stop_k=3）

投票语义（Countdown）：按表达式数值投票，非法表达式记废票。
覆盖/选择分解：coverage = 正确数值出现在候选中；selection = 投票选中正确值。

用法（off-peak 时段运行，pro 单价减半）：
  python experiments/e1_formal.py --suite countdown6 --n 12 \
      --api base_url=https://api.deepseek.com model=deepseek-v4-pro key=... \
      --progress-file results/progress_e1f_cd6.jsonl
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
from exocortex.tasks import CountdownTask, MathBenchTask  # noqa: E402
from exocortex.tasks.countdown import safe_eval_expr  # noqa: E402

# 臂矩阵：(effort, n_multi)。n_multi=1 为强度曲线；>1 为外挂采样曲线。
ARMS = [
    ("off", 1), ("low", 1), ("high", 1), ("max", 1),
    ("low", 2), ("low", 4), ("low", 8),
    ("high", 2), ("high", 4),
    ("off", 4), ("off", 8),
]
STOP_K = 3

# DeepSeek v4-pro off-peak 单价（USD/token）
PRICE_OFF = {"in_hit": 0.022e-6, "in_miss": 0.66e-6, "out": 1.98e-6}  # 官方定价页：pro hit off-peak $0.022/M（2026-10-03 核对）


def build_suite(name: str, n: int):
    if name.startswith("countdown"):
        lv = int(name.replace("countdown", "") or 5)
        return CountdownTask(seed=42).make_suite(n_per_level=n, levels=(lv,))
    if name == "math500":
        return MathBenchTask().math500_suite(levels=(4, 5), n=n)
    raise ValueError(name)


def countdown_vote_key(text: str, numbers: list[int]) -> str | None:
    expr = CountdownTask.extract_answer(text)
    if not expr:
        return None
    try:
        return str(safe_eval_expr(expr, numbers))
    except (ValueError, RecursionError, OverflowError):
        return None


def vote_by_value(candidates: list[str], numbers: list[int]) -> tuple[str | None, dict]:
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


def usd(in_hit: int, in_miss: int, out: int) -> float:
    """按 off-peak pro 价折算美元（hit/miss/out 分计）。"""
    return in_hit * PRICE_OFF["in_hit"] + in_miss * PRICE_OFF["in_miss"] \
        + out * PRICE_OFF["out"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="countdown6")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--api", nargs="*", required=True,
                    help="key=value: base_url=... model=... key=...")
    ap.add_argument("--max-tokens", type=int, default=16384)
    ap.add_argument("--arms", nargs="*", default=None,
                    help="仅运行指定臂（如 lowx4 highx2 offx1）；默认全部")
    ap.add_argument("--progress-file", default=None)
    ap.add_argument("--cache-friendly", action="store_true",
                    help="共享说明进 system（缓存友好口径）。默认关：INSTRUCTION 仅 ~84 tok，"
                         "收益 <3 美分，而口径变化破坏与阶段 0 强度曲线的可比性——"
                         "预算器的诚实输出：此场景缓存杠杆太小。命中率记账（同题采样命中）不受影响")
    args = ap.parse_args()

    cfg = dict(kv.split("=", 1) for kv in args.api)
    adapter = adapter_from_config({
        "type": "openai", "base_url": cfg["base_url"],
        "api_key": cfg.get("api_key") or cfg.get("key"), "model": cfg["model"],
    })
    items = build_suite(args.suite, args.n)
    # 缓存友好口径（默认开）：共享说明进 system（跨臂跨题命中），题面只占 user 尾巴。
    # 采样独立性不受影响（温度 0.7 的采样分布与 prompt 前缀无关）；附带产出
    # "共享前缀 + 多样尾巴 + 跨臂复用"场景的命中率数据（缓存外挂新数据点）。
    shared_system = None
    if args.cache_friendly and items and hasattr(items[0], "numbers"):
        shared_system = type(items[0]).INSTRUCTION
    ledger = Ledger(meta={"suite": args.suite, "n": len(items),
                          "model": cfg["model"], "ts": time.time(),
                          "cache_friendly": shared_system is not None})

    pf = args.progress_file or f"results/progress_e1f_{args.suite}_{args.seed}.jsonl"

    total_hit = 0
    total_miss = 0

    def progress(arm: str, idx: int, payload: dict) -> None:
        with open(pf, "a", encoding="utf-8") as f:
            f.write(json.dumps({"suite": args.suite, "arm": arm, "idx": idx,
                                "of": len(items), "ts": time.time(), **payload},
                               ensure_ascii=False) + "\n")

    def build_msgs(item) -> list[dict]:
        if shared_system:
            tail = item.tail if hasattr(item, "tail") else item.question
            return [{"role": "system", "content": shared_system},
                    {"role": "user", "content": tail}]
        prompt = item.prompt if hasattr(item, "numbers") else item.question
        return [{"role": "user", "content": prompt}]

    def run_prompt_n(prompt_msgs: list[dict], effort: str | None, n: int):
        req = GenRequest(messages=prompt_msgs,
                         max_tokens=args.max_tokens, effort=effort,
                         thinking=effort is not None, temperature=0.7)
        return adapter.generate_n(req, n)

    results = {"meta": {"suite": args.suite, "model": cfg["model"],
                        "n_items": len(items), "price": "off-peak pro"},
               "arms": []}

    for effort, n_multi in ARMS:
        arm_key = f"{effort}x{n_multi}"
        if args.arms and arm_key not in args.arms:
            continue
        arm = f"{cfg['model']}@{effort}x{n_multi}"
        recs = []
        cov_sel = []
        arm_hit = 0
        arm_miss = 0
        t0 = time.time()
        for i, item in enumerate(items):
            msgs = build_msgs(item)
            gens = run_prompt_n(msgs, None if effort == "off" else effort, n_multi)
            for g in gens:
                ledger.log(arm, adapter.name, g)
                raw = g.raw or {}
                arm_hit += raw.get("prompt_cache_hit_tokens") or 0
                arm_miss += raw.get("prompt_cache_miss_tokens") or 0
            if hasattr(item, "numbers"):
                # 顺序早停在 generate_n 内部不可用（批量生成），改为逐个生成+早停
                gens = gens[:1]
                req = GenRequest(messages=msgs,
                                 max_tokens=args.max_tokens,
                                 effort=None if effort == "off" else effort,
                                 thinking=effort is not None, temperature=0.7)
                for k in range(1, n_multi):
                    g = adapter.generate(req)
                    gens.append(g)
                    ledger.log(arm, adapter.name, g)
                    raw = g.raw or {}
                    arm_hit += raw.get("prompt_cache_hit_tokens") or 0
                    arm_miss += raw.get("prompt_cache_miss_tokens") or 0
                    keys = [kk for kk in (countdown_vote_key(x.text, item.numbers)
                                          for x in gens) if kk]
                    if len(keys) >= STOP_K and len(set(keys[-STOP_K:])) == 1:
                        break
                top, _ = vote_by_value([g.text for g in gens], item.numbers)
                ok = check_by_value(item, top)
                keys = [k for k in (countdown_vote_key(x.text, item.numbers)
                                    for x in gens) if k]
                cov = str(item.target) in keys
                sel = ok if cov else None
                cov_sel.append({"coverage": cov, "selection": sel})
            else:
                from exocortex.scaffold.verifier import majority_vote
                top, _ = majority_vote([g.text for g in gens])
                ok = MathBenchTask.check(item, top or "")
                cov_sel.append({"coverage": None, "selection": None})
            recs.append(ok)
            progress(arm, i, {"correct": ok, "n_gens": len(gens),
                              "elapsed": round(time.time() - t0, 1)})
        summary = ledger.arm_summary(arm)
        results["arms"].append({
            "arm": arm, "effort": effort, "n_multi": n_multi,
            "accuracy": round(sum(recs) / len(recs), 4),
            "coverage_rate": (round(sum(1 for c in cov_sel if c["coverage"])
                                    / max(len(cov_sel), 1), 4)
                              if any(c["coverage"] is not None for c in cov_sel)
                              else None),
            "usd_offpeak": round(usd(arm_hit, arm_miss,
                                     summary["completion_tokens"]), 4),
            "arm_hit_tokens": arm_hit, "arm_miss_tokens": arm_miss,
            **summary,
        })
        a = results["arms"][-1]
        print(f"[{arm}] acc={a['accuracy']} tok={a['completion_tokens']} "
              f"usd=${a['usd_offpeak']}", flush=True)

    ledger.dump(f"results/e1f_{cfg['model']}_{args.suite}_ledger.json")
    out = f"results/e1f_{cfg['model']}_{args.suite}_{time.strftime('%H%M%S')}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(json.dumps(results["arms"], ensure_ascii=False, indent=2))
    print("SAVED", out)


if __name__ == "__main__":
    main()
