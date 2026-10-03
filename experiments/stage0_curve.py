"""阶段 0 主脚本：强度-精度坐标系。

跑法（在 exocortex/ 根目录）：
  # 本地，内置 mini 集（最快冒烟）
  python experiments/stage0_curve.py --suite builtin --n 30
  # 本地，GSM8K 100 题
  python experiments/stage0_curve.py --suite gsm8k --n 100
  # 本地 + Countdown
  python experiments/stage0_curve.py --suite countdown --n 20

  # DeepSeek API（任一模型）
  python experiments/stage0_curve.py --suite gsm8k --n 100 \
      --api base_url=https://api.deepseek.com model=deepseek-flash key=$DEEPSEEK_API_KEY

强度阶梯：
  本地：local@xlow(64) low(256) medium(1024) high(4096)   [budget forcing]
  API： thinking off（零思考端点）→ effort low → effort high → effort max
每个 (任务, 强度) 格输出 accuracy / avg completion tokens / avg wall clock。
全部结果 + Ledger 对账落 results/stage0_curve_result_<ts>.json
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from exocortex.adapter import adapter_from_config  # noqa: E402
from exocortex.ledger import Ledger  # noqa: E402
from exocortex.tasks import CountdownTask, MathBenchTask  # noqa: E402

LOCAL_LADDER = [
    ("xlow", 64), ("low", 256), ("medium", 1024), ("high", 4096),
]


def parse_ladder(spec: str | None):
    """--ladder 64,256,1024,2048：冒烟用小阶梯；不传则用默认四档。
    返回 [(标签, 预算值), ...]，标签仅用于展示。"""
    if not spec:
        return [(name, b) for name, b in LOCAL_LADDER]
    out = []
    for tok_budget in spec.split(","):
        b = int(tok_budget)
        name = ("xlow" if b <= 64 else "low" if b <= 256 else
                "medium" if b <= 1024 else "high")
        out.append((name, b))
    return out
API_LADDER = [("off", None), ("low", "low"), ("high", "high"), ("max", "max")]


def build_suite(name: str, n: int):
    if name == "builtin":
        return MathBenchTask().builtin_suite(n)
    if name == "gsm8k":
        return MathBenchTask().gsm8k_suite(n)
    if name == "math500":
        return MathBenchTask().math500_suite(levels=(4, 5), n=n)
    if name == "countdown":
        return CountdownTask(seed=42).make_suite(n_per_level=max(n // 3, 5))
    if name == "countdown5":
        # 只跑 level 5（5 个数字），主战场难度；n 为题数
        return CountdownTask(seed=42).make_suite(n_per_level=n, levels=(5,))
    if name == "countdown6":
        return CountdownTask(seed=42).make_suite(n_per_level=n, levels=(6,))
    if name == "countdown7":
        return CountdownTask(seed=42).make_suite(n_per_level=n, levels=(7,))
    raise ValueError(name)


def _progress(path: str | None, payload: dict) -> None:
    """逐题进度落盘（append-only JSONL）。解决长批的进度可观测性缺口：
    任何时刻 tail 此文件即可精确回答"跑到哪个 suite 哪一题"。"""
    if not path:
        return
    payload = {**payload, "ts": time.time()}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run_local(cfg: dict, suite_name: str, n: int, seed: int, ladder=None,
              progress_file: str | None = None) -> dict:
    from exocortex.scaffold.verifier import coverage_selection_split

    adapter = adapter_from_config({"type": "local", "model_path": cfg["model_path"]})
    items = build_suite(suite_name, n)
    ledger = Ledger(meta={"suite": suite_name, "n_items": len(items),
                          "adapter": adapter.name, "ts": time.time()})
    grid = []
    for arm_label, budget in (ladder or LOCAL_LADDER):
        arm = f"local@{arm_label}(budget={budget})"
        recs = []
        for i, item in enumerate(items):
            prompt = item.prompt if hasattr(item, "numbers") else item.question
            checker = (lambda text, it=item: CountdownTask.check(it, text)) \
                if hasattr(item, "numbers") else (lambda text, it=item: MathBenchTask.check(it, text))
            req_messages = [{"role": "user", "content": prompt}]
            # KV 实测 145.9KB/token，6GB 卡思考预算上限 ~4.9k（含激活余量），
            # 生成上限取 6144 保证 prompt+思考+作答的 KV 峰值安全；
            # 本地 adapter 接受数字预算（effort=str(budget)），强度=预算值
            g = adapter.generate(_req(req_messages, str(budget), 6144, seed + i))
            ledger.log(arm, adapter.name, g)
            ok = checker(g.text)
            _progress(progress_file, {
                "suite": suite_name, "arm": arm, "idx": i, "of": len(items),
                "item": (f"cd:{getattr(item, 'target', '?')}" if hasattr(item, "numbers")
                         else f"q{i}"),
                "correct": ok, "truncated": g.truncated,
                "completion_tokens": g.completion_tokens, "wall": round(g.wall_clock, 2),
            })
            recs.append({
                "idx": i, "correct": ok, "truncated": g.truncated,
                "completion_tokens": g.completion_tokens,
                "reasoning_tokens": g.reasoning_tokens, "wall": round(g.wall_clock, 2),
            })
            if (i + 1) % 10 == 0:
                acc = sum(r["correct"] for r in recs) / len(recs)
                print(f"  {arm} {i+1}/{len(items)} acc={acc:.3f}", flush=True)
        # coverage/selection 分解只在最高预算臂做一次采样参考（阶段 2 再展开）
        acc = sum(r["correct"] for r in recs)
        grid.append({
            "arm": arm, "arm_label": arm_label, "budget": budget,
            "n": len(recs), "n_correct": acc,
            "accuracy": round(acc / len(recs), 4),
            "avg_completion_tokens": round(sum(r["completion_tokens"] for r in recs) / len(recs), 1),
            "avg_wall": round(sum(r["wall"] for r in recs) / len(recs), 2),
            "truncation_rate": round(sum(r["truncated"] for r in recs) / len(recs), 4),
        })
        print(f"[arm done] {arm} acc={grid[-1]['accuracy']}", flush=True)
    return {"grid": grid, "ledger": ledger}


def _req(messages, effort, max_tokens, seed, thinking=True):
    from exocortex.adapter import GenRequest
    return GenRequest(messages=messages, max_tokens=max_tokens, effort=effort,
                      thinking=thinking, temperature=0.6, seed=seed)


def run_api(cfg: dict, suite_name: str, n: int, seed: int,
            args_max_tokens: int = 8192, cache_friendly: bool = False,
            progress_file: str | None = None) -> dict:
    adapter = adapter_from_config({
        "type": "openai",
        "base_url": cfg["base_url"],
        "api_key": cfg.get("api_key") or cfg.get("key"),
        "model": cfg["model"],
    })
    items = build_suite(suite_name, n)
    # 缓存友好模式：共享说明进 system（前缀稳定），题目只占 user 尾巴。
    # 代价：prompt 结构与旧口径不同，acc 对比需注明口径（先 A/B 验证等价）。
    shared_system = None
    if cache_friendly and items and hasattr(items[0], "numbers"):
        shared_system = type(items[0]).INSTRUCTION
    ledger = Ledger(meta={"suite": suite_name, "n_items": len(items),
                          "adapter": adapter.name, "cache_friendly": cache_friendly,
                          "ts": time.time()})
    grid = []
    for effort_name, effort in API_LADDER:
        arm = f"{cfg['model']}@{effort_name}"
        recs = []
        for i, item in enumerate(items):
            prompt = item.prompt if hasattr(item, "numbers") else item.question
            checker = (lambda text, it=item: CountdownTask.check(it, text)) \
                if hasattr(item, "numbers") else (lambda text, it=item: MathBenchTask.check(it, text))
            # effort=None → thinking 关闭（零思考端点）；一次调用到位，不重复请求
            thinking = effort is not None
            if cache_friendly and shared_system:
                tail = item.tail if hasattr(item, "tail") else item.question
                msgs = [{"role": "system", "content": shared_system},
                        {"role": "user", "content": tail}]
            else:
                msgs = [{"role": "user", "content": prompt}]
            g = adapter.generate(_req(msgs,
                                      effort, args_max_tokens, seed + i,
                                      thinking=thinking))
            ledger.log(arm, adapter.name, g)
            _progress(progress_file, {
                "suite": suite_name, "arm": arm, "idx": i, "of": len(items),
                "item": (f"cd:{getattr(item, 'target', '?')}" if hasattr(item, "numbers")
                         else f"q{i}"),
                "correct": checker(g.text), "completion_tokens": g.completion_tokens,
                "wall": round(g.wall_clock, 2),
            })
            recs.append({
                "idx": i, "correct": checker(g.text),
                "completion_tokens": g.completion_tokens, "wall": round(g.wall_clock, 2),
            })
            if (i + 1) % 10 == 0:
                acc = sum(r["correct"] for r in recs) / len(recs)
                print(f"  {arm} {i+1}/{len(items)} acc={acc:.3f}", flush=True)
        acc = sum(r["correct"] for r in recs)
        grid.append({
            "arm": arm, "effort": effort_name,
            "n": len(recs), "n_correct": acc,
            "accuracy": round(acc / len(recs), 4),
            "avg_completion_tokens": round(sum(r["completion_tokens"] for r in recs) / len(recs), 1),
            "avg_wall": round(sum(r["wall"] for r in recs) / len(recs), 2),
        })
        print(f"[arm done] {arm} acc={grid[-1]['accuracy']}", flush=True)
    return {"grid": grid, "ledger": ledger}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=["builtin", "gsm8k", "countdown", "countdown5",
                                        "countdown6", "countdown7", "math500"],
                    default="builtin")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--model-path", default="model_cache/Qwen3-4B-Thinking-2507")
    ap.add_argument("--api", nargs="*", default=None,
                    help="key=value 形式: base_url=... model=... key=...")
    ap.add_argument("--ladder", default=None,
                    help="逗号分隔思考预算，如 64,256,1024,2048；仅本地模式")
    ap.add_argument("--max-tokens", type=int, default=8192,
                    help="API 生成上限；countdown6/7 建议 16384")
    ap.add_argument("--cache-friendly", action="store_true",
                    help="共享说明进 system（缓存友好口径）；acc 口径与旧数据不同，需先 A/B 验证等价")
    ap.add_argument("--progress-file", default=None,
                    help="逐题进度 JSONL 落盘路径（默认 results/progress_<tag>.jsonl）")
    args = ap.parse_args()

    default_progress = f"results/progress_{args.suite}_{args.seed}.jsonl"
    progress_path = args.progress_file or default_progress
    os.makedirs("results", exist_ok=True)

    if args.api:
        cfg = dict(kv.split("=", 1) for kv in args.api)
        result = run_api(cfg, args.suite, args.n, args.seed,
                         args_max_tokens=args.max_tokens,
                         cache_friendly=args.cache_friendly,
                         progress_file=progress_path)
        tag = cfg["model"].replace("/", "_")
    else:
        result = run_local({"model_path": args.model_path}, args.suite, args.n,
                           args.seed, ladder=parse_ladder(args.ladder),
                           progress_file=progress_path)
        tag = "local"

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = f"results/stage0_curve_{tag}_{args.suite}_{ts}.json"
    result["ledger"].dump(out_path.replace(".json", "_ledger.json"))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"meta": {"suite": args.suite, "n": args.n, "tag": tag, "ts": ts},
                   "grid": result["grid"]}, f, ensure_ascii=False, indent=2)
    print(json.dumps(result["grid"], ensure_ascii=False, indent=2))
    print("SAVED", out_path)


if __name__ == "__main__":
    main()
