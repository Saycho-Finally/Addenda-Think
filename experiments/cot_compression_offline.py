"""CoT 压缩离线实验：预算守卫（截断）vs 步骤熵剪枝（Step Entropy 式）。

数据：anatomy 语料（30 条完整思考链，含 reasoning 文本与 token 统计）。
零 API 成本。

对照三种压缩的离线估算：
  A. 无压缩（基线）
  B. budget_guard 式：尾部截断到预算（粗暴——可能砍掉关键推导）
  C. Step Entropy 式：剪"低熵步骤"（重复/无新信息），保留关键推导

指标：
  可剪 token 比例（压缩率）
  关键步骤保留率（以"含数字或运算符的步骤"为关键代理——数学题）
  砍掉关键步骤的比例（B 的软肋 vs C 的设计目标）

参照：Step Entropy 论文（ICLR 2026）报告 80% 低熵中间步可剪且精度微降。
"""

import json
import os
import re
import sys

CORPUS = ("D:/agentwork/workbuddy/code/1-思维方式/exocortex/results/"
          "anatomy_raw_deepseek-v4-pro_countdown6_211114.jsonl")

KEY_PAT = re.compile(r"\d|[+\-*/×÷=]")     # 关键代理：含数字或运算符


def split_steps(text: str) -> list[str]:
    """按行/句切步骤（合并过短行）。"""
    raw = re.split(r"[\n]+|(?<=[。；;.!?])", text)
    steps, buf = [], ""
    for s in raw:
        s = s.strip()
        if not s:
            continue
        buf += s
        if len(buf) >= 30:          # 合并到最小步长
            steps.append(buf)
            buf = ""
    if buf:
        steps.append(buf)
    return steps


def step_entropy_proxy(step: str, prev_text: str) -> float:
    """低熵代理（0=最冗余 1=最新信息）：基于
      ①与先前文本的 n-gram 重叠（重复 = 低熵）
      ②步骤内自身重复
      ③信息密度（数字/运算符/新词占比）"""
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", step)
    if not tokens:
        return 0.0
    # 1) 与先前文本重叠
    prev_set = set(re.findall(r"[\w\u4e00-\u9fff]+", prev_text))
    overlap = sum(1 for t in tokens if t in prev_set) / len(tokens)
    # 2) 自身重复率
    uniq = len(set(tokens)) / len(tokens)
    # 3) 信息密度（数字/运算符突出）
    digits = len(re.findall(r"\d", step)) / max(len(step), 1) * 10
    return min(1.0, (1 - overlap) * 0.5 + uniq * 0.3 + min(digits, 1) * 0.2)


def compress_entropy(steps: list[str], threshold: float = 0.4) -> tuple[list[str], list[int]]:
    """剪低熵步骤（阈值以下），返回保留的步骤与剪掉的索引。"""
    kept, dropped = [], []
    prev = ""
    for i, s in enumerate(steps):
        e = step_entropy_proxy(s, prev)
        if e >= threshold or KEY_PAT.search(s):   # 关键步骤永不剪（设计目标）
            kept.append(s)
        else:
            dropped.append(i)
        prev += s
    return kept, dropped


def compress_truncate(steps: list[str], budget_ratio: float) -> tuple[list[str], int]:
    """budget_guard 式：保留前 budget_ratio 比例的步骤（尾部截断的等价离线形式）。"""
    n_keep = max(1, int(len(steps) * budget_ratio))
    kept = steps[:n_keep]
    dropped_key = sum(1 for s in steps[n_keep:] if KEY_PAT.search(s))
    return kept, dropped_key


def main() -> None:
    rows = [json.loads(l) for l in open(CORPUS, encoding="utf-8")]
    print("=" * 72)
    print(f"CoT 压缩离线实验（{len(rows)} 条思考链）")
    print("=" * 72)

    tot_steps = tot_reason_chars = 0
    results = []
    for r in rows:
        text = r.get("reasoning", "")
        if not text or len(text) < 200:
            continue
        steps = split_steps(text)
        tot_steps += len(steps)
        tot_reason_chars += len(text)

        # C：步骤熵剪枝
        kept_c, dropped_c = compress_entropy(steps)
        chars_c = sum(len(s) for s in kept_c)
        key_total = sum(1 for s in steps if KEY_PAT.search(s))
        key_kept_c = sum(1 for s in kept_c if KEY_PAT.search(s))

        # B：截断到与 C 相同的保留比例（等预算公平对照）
        keep_ratio = chars_c / max(len(text), 1)
        kept_b, key_lost_b = compress_truncate(steps, keep_ratio)
        chars_b = sum(len(s) for s in kept_b)
        key_kept_b = key_total - key_lost_b

        results.append({
            "n_steps": len(steps), "chars": len(text),
            "entropy_compress_ratio": round(1 - chars_c / len(text), 3),
            "truncate_compress_ratio": round(1 - chars_b / len(text), 3),
            "key_steps_total": key_total,
            "key_kept_entropy": key_kept_c,
            "key_kept_truncate": key_kept_b,
        })

    n = len(results)
    avg = lambda k: sum(x[k] for x in results) / n  # noqa: E731
    key_total = sum(x["key_steps_total"] for x in results)
    key_entropy = sum(x["key_kept_entropy"] for x in results)
    key_trunc = sum(x["key_kept_truncate"] for x in results)

    print(f"\n语料：{n} 条，平均 {avg('n_steps'):.0f} 步骤/条，"
          f"{avg('chars'):.0f} 字符/条")
    print(f"\n{'策略':16s} {'压缩率':>8s} {'关键保留率':>10s}")
    print(f"{'预算守卫（截断）':16s} {avg('truncate_compress_ratio'):>8.3f} "
          f"{key_trunc/key_total:>10.3f}")
    print(f"{'步骤熵剪枝':16s} {avg('entropy_compress_ratio'):>8.3f} "
          f"{key_entropy/key_total:>10.3f}")

    print(f"\n参照：Step Entropy 论文报告 80% 低熵中间步可剪（精度微降）")
    print(f"本实验的等预算对照：两策略压缩率对齐（{avg('entropy_compress_ratio'):.2f}），"
          f"关键步骤保留率 {key_entropy/key_total:.2f} vs {key_trunc/key_total:.2f}")

    out = {"n_chains": n, "avg_steps": round(avg("n_steps"), 1),
           "truncate": {"compress_ratio": round(avg("truncate_compress_ratio"), 3),
                        "key_keep_rate": round(key_trunc / key_total, 3)},
           "entropy_prune": {"compress_ratio": round(avg("entropy_compress_ratio"), 3),
                             "key_keep_rate": round(key_entropy / key_total, 3)},
           "reference": "Step Entropy (ICLR 2026): 80% low-entropy steps prunable"}
    os.makedirs("results", exist_ok=True)
    with open("results/cot_compression_offline.json", "w", encoding="utf-8") as f:
        json.dump({"summary": out, "per_chain": results}, f,
                  ensure_ascii=False, indent=2)
    print("\nSAVED results/cot_compression_offline.json")


if __name__ == "__main__":
    main()
