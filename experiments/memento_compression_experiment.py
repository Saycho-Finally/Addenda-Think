"""Memento 式 CoT 自压缩实验（补齐压缩策略对照的第四档）。

四策略对照（同一批 30 条思考链）：
  A 无压缩        原文推理 → 读推理给答案（基线）
  B 预算守卫截断   保留前 50% → 读推理给答案
  C 步骤熵剪枝    剪低熵步骤（关键保护）→ 读推理给答案
  D Memento 自压缩 模型把推理压缩到 ~50% 长度 → 读压缩版给答案

指标：压缩率 + 答案一致率（相对 A 的答案）——一致率 = 信息保留代理。
预算：30 条 × 5 类调用 ≈ 150 次 flash ≈ $0.08。
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.environ.get("EXOCORTEX_ROOT", "../exocortex"))

from exocortex.adapter import GenRequest, adapter_from_config  # noqa: E402

CORPUS = os.environ.get(
    "ANATOMY_CORPUS",
    "../exocortex/results/anatomy_raw_deepseek-v4-pro_countdown6_211114.jsonl")

ANSWER_PROMPT = ("以下是一段问题求解的推理过程。请**仅根据这段推理**写出最终答案"
                 "（表达式形式）。若推理信息不足以确定答案，输出「信息不足」。\n\n"
                 "推理过程：\n{reasoning}\n\n最终答案：")

COMPRESS_PROMPT = ("把以下推理过程压缩成大约一半的长度，**保留所有对得出最终答案"
                   "必要的信息**（关键数字组合、运算步骤、结论），删去重复与试探性"
                   "分支。只输出压缩后的推理，不要评论。\n\n{reasoning}")


def make_adapter(key):
    return adapter_from_config({"type": "openai",
                                "base_url": "https://api.deepseek.com",
                                "api_key": key, "model": "deepseek-flash"})


def ask(ad, prompt, max_tokens=600):
    g = ad.generate(GenRequest(messages=[{"role": "user", "content": prompt}],
                               max_tokens=max_tokens, thinking=False,
                               temperature=0.2))
    return g.text.strip(), g.completion_tokens


def norm_answer(text: str) -> str:
    """答案归一化：提取表达式中的数字与运算符（去空格/换行/标记）。"""
    t = text.replace("####", " ").replace("\\", " ")
    m = re.findall(r"[\d+\-*/()×÷\s]{6,}", t)
    if m:
        t = max(m, key=len)
    t = re.sub(r"\s+", "", t)
    return t[:120]


def split_steps(text: str) -> list[str]:
    raw = re.split(r"[\n]+|(?<=[。；;.!?])", text)
    steps, buf = [], ""
    for s in raw:
        s = s.strip()
        if not s:
            continue
        buf += s
        if len(buf) >= 30:
            steps.append(buf)
            buf = ""
    if buf:
        steps.append(buf)
    return steps


KEY_PAT = re.compile(r"\d|[+\-*/×÷=]")


def step_entropy_proxy(step: str, prev_text: str) -> float:
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", step)
    if not tokens:
        return 0.0
    prev_set = set(re.findall(r"[\w\u4e00-\u9fff]+", prev_text))
    overlap = sum(1 for t in tokens if t in prev_set) / len(tokens)
    uniq = len(set(tokens)) / len(tokens)
    digits = len(re.findall(r"\d", step)) / max(len(step), 1) * 10
    return min(1.0, (1 - overlap) * 0.5 + uniq * 0.3 + min(digits, 1) * 0.2)


def prune_steps(text: str, threshold: float = 0.4) -> str:
    steps = split_steps(text)
    kept, prev = [], ""
    for s in steps:
        e = step_entropy_proxy(s, prev)
        if e >= threshold or KEY_PAT.search(s):
            kept.append(s)
        prev += s
    return "".join(kept)


def main() -> None:
    key = sys.argv[1] if len(sys.argv) > 1 else os.environ["DEEPSEEK_API_KEY"]
    ad = make_adapter(key)
    rows = [json.loads(l) for l in open(CORPUS, encoding="utf-8")]

    stats = {k: {"n": 0, "consistent": 0, "chars": 0, "orig_chars": 0}
             for k in ["A_original", "B_truncate", "C_prune", "D_memento"]}
    detail = []
    for i, r in enumerate(rows):
        text = r.get("reasoning", "")
        if not text or len(text) < 300:
            continue
        # A 基线
        ans_a, _ = ask(ad, ANSWER_PROMPT.format(reasoning=text))
        base = norm_answer(ans_a)
        variants = {
            "A_original": text,
            "B_truncate": text[:int(len(text) * 0.5)],
            "C_prune": prune_steps(text),
        }
        # D Memento 自压缩
        comp, _ = ask(ad, COMPRESS_PROMPT.format(reasoning=text[:8000]),
                      max_tokens=2000)
        variants["D_memento"] = comp

        row = {"idx": i, "orig_chars": len(text), "base_answer": base}
        for k, v in variants.items():
            s = stats[k]
            s["n"] += 1
            s["chars"] += len(v)
            s["orig_chars"] += len(text)
            if k == "A_original":
                s["consistent"] += 1
                row[k] = {"ratio": 1.0, "consistent": True, "answer": base}
                continue
            ans, _ = ask(ad, ANSWER_PROMPT.format(reasoning=v))
            same = norm_answer(ans) == base and base != ""
            s["consistent"] += int(same)
            row[k] = {"ratio": round(len(v) / len(text), 3),
                      "consistent": same, "answer": norm_answer(ans)}
        detail.append(row)
        print(f"[{i}] base={base[:20]} | B={row['B_truncate']['consistent']} "
              f"C={row['C_prune']['consistent']} D={row['D_memento']['consistent']}",
              flush=True)
        time.sleep(0.1)

    print("\n" + "=" * 72)
    print(f"{'策略':14s} {'压缩率':>8s} {'答案一致率':>10s}")
    summary = {}
    for k, s in stats.items():
        if not s["n"]:
            continue
        cr = 1 - s["chars"] / s["orig_chars"]
        cons = s["consistent"] / s["n"]
        summary[k] = {"compress_ratio": round(cr, 3),
                      "answer_consistency": round(cons, 3), "n": s["n"]}
        print(f"{k:14s} {cr:>8.3f} {cons:>10.3f}")

    os.makedirs("results", exist_ok=True)
    with open("results/memento_compression.json", "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "detail": detail}, f,
                  ensure_ascii=False, indent=2)
    print("\nSAVED results/memento_compression.json")


if __name__ == "__main__":
    main()
