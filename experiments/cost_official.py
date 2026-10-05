"""官方口径成本对账（2026-10-01 全天）。

数据源：DeepSeek 官方后台结算页（10-01 24:00 结算口径）：
  deepseek-flash   请求 753   输入命中 0        输入未命中 65,250    输出 752,962
  deepseek-v4-pro  请求 1,048  输入命中 10,240   输入未命中 102,790   输出 1,956,095

价目（官方 pricing，off-peak，peak ×2）：
  flash  input-hit $0.006/M  input-miss $0.15/M   output $0.60/M
  pro    input-hit $0.036/M  input-miss $0.66/M   output $1.98/M
Peak = UTC 周一至五 01-04 与 06-10 = 北京 09-12 与 14-18。

逐笔与汇总结果见 results/cost_official_2026-10-01.json
"""

import json

CNY = 7.15

# 时段拆分（按各 run 的开跑时间归桶）：
#   off-peak：12:30 builtin、12:50 cd5、13:03 gsm8k、13:07 cd5-pro、13:32 gsm8k-pro、
#             18:05-22:40 automation 全部（cd6/cd7/E1/anatomy/math500）
#   peak    ：15:20 E1(wYJFUl 强度臂)、15:47 cd6(84c47J)、15:51 anatomy(崩)、
#             16:10 fhmYqA/gqkIOO 各 8 分钟
# 按 output token 近似拆分（hit/miss 输入几乎全在 off-peak，误差可控）：
OFF_PEAK_SHARE = {
    "deepseek-flash": {"out": 0.78, "in": 0.85},   # 大头在 12:30-13:33 + automation
    "deepseek-v4-pro": {"out": 0.80, "in": 0.85},  # 同上；peak 部分是 cd6/E1 首跑
}

OFFICIAL = {
    "deepseek-flash":  {"calls": 753,  "in_hit": 0,      "in_miss": 65_250,  "out": 752_962},
    "deepseek-v4-pro": {"calls": 1048, "in_hit": 10_240, "in_miss": 102_790, "out": 1_956_095},
}

RATES = {
    "deepseek-flash":  {"in_hit": 0.006e-6, "in_miss": 0.15e-6,  "out": 0.60e-6},
    "deepseek-v4-pro": {"in_hit": 0.036e-6, "in_miss": 0.66e-6,  "out": 1.98e-6},
}


def cost(model: str, in_hit: int, in_miss: int, out: int, off_share: float) -> dict:
    r = RATES[model]
    c_off = in_hit * r["in_hit"] + in_miss * r["in_miss"] + out * r["out"]
    c_peak = c_off * 2
    c_mix = c_off * off_share + c_peak * (1 - off_share)
    return {"off_only_usd": c_off, "peak_only_usd": c_peak, "mix_est_usd": c_mix}


def main() -> None:
    rows = []
    total_mix = 0.0
    for model, o in OFFICIAL.items():
        share = OFF_PEAK_SHARE[model]
        c = cost(model, o["in_hit"], o["in_miss"], o["out"],
                 share["out"] * 0.9 + share["in"] * 0.1)
        total_mix += c["mix_est_usd"]
        rows.append({
            "model": model, **o, **{k: round(v, 3) for k, v in c.items()},
            "mix_est_cny": round(c["mix_est_usd"] * CNY, 1),
        })

    out = {
        "date": "2026-10-01",
        "source": "DeepSeek 官方后台结算页",
        "cache_note": (
            "缓存命中几乎为零：flash 0/65,250，pro 10,240/113,030 (9%)。"
            "原因：stage0/curve 类调用每题 prompt 各不相同，无前缀可共享；"
            "E1 的 low×N 采样本应命中同 prompt 前缀（pro 的 10,240 命中即来自它），"
            "但 prompt 仅 ~100-200 token，命中收益上限就低；"
            "输出思考 token（占总量 92-95%）永远不命中。"
            "结论：缓存优化对本项目成本结构影响 <5%，不是杠杆；真正的杠杆是 off-peak 时段与档位选择。"
        ),
        "reconciliation_note": (
            "ledger 覆盖率：flash 597K/753K=79%，pro 845K/1956K=43%。"
            "缺口来自未落盘的崩掉/中止 run（402 中断、TaskStop、E1 首跑强度臂）。"
            "官方后台为唯一真账，本文件即按官方口径。"
        ),
        "rows": rows,
        "total_mix_usd": round(total_mix, 2),
        "total_mix_cny": round(total_mix * CNY, 1),
    }
    with open("results/cost_official_2026-10-01.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    for r in rows:
        print(f"{r['model']:16s} calls={r['calls']:5d} out={r['out']:9,d} "
              f"off=${r['off_only_usd']:.2f} mix=${r['mix_est_usd']:.2f} (¥{r['mix_est_cny']})")
    print(f"TOTAL mix est: ${out['total_mix_usd']} ≈ ¥{out['total_mix_cny']}")


if __name__ == "__main__":
    main()
