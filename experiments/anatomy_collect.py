"""阶段 1 采集脚本：跑模型收集 reasoning 语料 + 事件密度表。

用法（在 exocortex/ 根目录）：
  # 本地 4B，Countdown5 × 高预算
  python experiments/anatomy_collect.py --suite countdown5 --n 20 --ladder 1024,2048
  # 云端 pro，Countdown6 × high/max
  python experiments/anatomy_collect.py --suite countdown6 --n 10 \
      --api base_url=https://api.deepseek.com model=deepseek-v4-pro key=... \
      --efforts low,high,max

产出：
  results/anatomy_raw_<tag>.jsonl   每行一条完整 reasoning（供语义级标注）
  results/anatomy_density_<tag>.json  四类事件密度表
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from exocortex.adapter import GenRequest, adapter_from_config  # noqa: E402
from exocortex.scaffold.anatomy import aggregate, analyze_reasoning  # noqa: E402
from exocortex.tasks import CountdownTask, MathBenchTask  # noqa: E402


def build_suite(name: str, n: int):
    if name == "countdown5":
        return CountdownTask(seed=42).make_suite(n_per_level=n, levels=(5,))
    if name == "countdown6":
        return CountdownTask(seed=42).make_suite(n_per_level=n, levels=(6,))
    if name == "countdown7":
        return CountdownTask(seed=42).make_suite(n_per_level=n, levels=(7,))
    if name == "gsm8k":
        return MathBenchTask().gsm8k_suite(n)
    if name == "math500":
        return MathBenchTask().math500_suite(n=n)
    raise ValueError(name)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=["countdown5", "countdown6", "countdown7",
                                        "gsm8k", "math500"], default="countdown5")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--ladder", default=None, help="本地：逗号分隔思考预算")
    ap.add_argument("--efforts", default=None, help="API：逗号分隔档位，如 low,high,max")
    ap.add_argument("--api", nargs="*", default=None)
    ap.add_argument("--model-path", default="model_cache/Qwen3-4B-Thinking-2507")
    args = ap.parse_args()

    items = build_suite(args.suite, args.n)
    tag = "local"
    if args.api:
        cfg = dict(kv.split("=", 1) for kv in args.api)
        adapter = adapter_from_config({
            "type": "openai", "base_url": cfg["base_url"],
            "api_key": cfg.get("api_key") or cfg.get("key"), "model": cfg["model"],
        })
        tag = cfg["model"].replace("/", "_")
        efforts = (args.efforts or "low,high,max").split(",")
    else:
        adapter = adapter_from_config({"type": "local", "model_path": args.model_path})
        efforts = (args.ladder or "1024,2048").split(",")

    raw_path = f"results/anatomy_raw_{tag}_{args.suite}_{time.strftime('%H%M%S')}.jsonl"
    density_path = raw_path.replace("anatomy_raw_", "anatomy_density_")
    os.makedirs("results", exist_ok=True)
    density_out = []

    with open(raw_path, "w", encoding="utf-8") as raw_f:
        for effort in efforts:
            per_arm = []
            for i, item in enumerate(items):
                prompt = item.prompt if hasattr(item, "numbers") else item.question
                if args.api:
                    req = GenRequest(messages=[{"role": "user", "content": prompt}],
                                     max_tokens=16384, effort=effort if effort != "off" else None,
                                     thinking=effort != "off", temperature=0.6)
                    g = adapter.generate(req)
                else:
                    req = GenRequest(messages=[{"role": "user", "content": prompt}],
                                     max_tokens=6144, effort=str(effort),
                                     thinking=True, temperature=0.6)
                    g = adapter.generate(req)
                analysis = analyze_reasoning(g.reasoning, g.reasoning_tokens)
                per_arm.append(analysis)
                raw_f.write(json.dumps({
                    "arm": effort, "idx": i,
                    "prompt": prompt[:80],
                    "reasoning": g.reasoning,
                    "answer": g.text,
                    "tokens": analysis["tokens"],
                    "counts": analysis["counts"],
                }, ensure_ascii=False) + "\n")
                if (i + 1) % 5 == 0:
                    print(f"  {effort} {i+1}/{len(items)}", flush=True)
            rep = aggregate(per_arm, arm=effort, task=args.suite)
            density_out.append(rep.to_dict())
            print(f"[arm] {effort}: {json.dumps(rep.to_dict()['events_per_1k_tokens'], ensure_ascii=False)}",
                  flush=True)

    with open(density_path, "w", encoding="utf-8") as f:
        json.dump({"tag": tag, "suite": args.suite, "n": args.n, "arms": density_out},
                  f, ensure_ascii=False, indent=2)
    print("SAVED", raw_path)
    print("SAVED", density_path)


if __name__ == "__main__":
    main()
