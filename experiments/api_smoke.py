"""DeepSeek API 冒烟：验证 OpenAICompatAdapter 对 deepseek-flash / deepseek-v4-pro 的
真实连通性。用法：
  set DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY（环境变量，勿提交真实 key）
  python experiments/api_smoke.py deepseek-flash
  python experiments/api_smoke.py deepseek-v4-pro
做四件事：零思考 / low / max 各一次 + 一次非法 effort（应报错），
打印思考长度、答案与 token 记账。**不跑批量实验，只验通路。**
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from exocortex.adapter import GenRequest, OpenAICompatAdapter  # noqa: E402


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "deepseek-flash"
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        print("请先设置 DEEPSEEK_API_KEY 环境变量")
        sys.exit(1)
    ad = OpenAICompatAdapter("https://api.deepseek.com", key, model)
    q = "9.11 和 9.8 哪个大？给出理由，最后一行输出 #### <你的答案>"

    print(f"=== {model} 零思考 ===")
    g = ad.generate(GenRequest(messages=[{"role": "user", "content": q}],
                               max_tokens=512, thinking=False, effort=None))
    print(f"answer={g.text!r}\ntokens: prompt={g.prompt_tokens} completion={g.completion_tokens} "
          f"reasoning={g.reasoning_tokens} wall={g.wall_clock:.1f}s")

    for effort in ("low", "max"):
        print(f"=== {model} effort={effort} ===")
        g = ad.generate(GenRequest(messages=[{"role": "user", "content": q}],
                                   max_tokens=8192, thinking=True, effort=effort))
        print(f"reasoning_len={len(g.reasoning)}ch answer={g.text!r}\n"
              f"tokens: prompt={g.prompt_tokens} completion={g.completion_tokens} "
              f"reasoning={g.reasoning_tokens} wall={g.wall_clock:.1f}s")

    print(f"=== {model} 非法 effort=xhigh（应当报错）===")
    try:
        ad.generate(GenRequest(messages=[{"role": "user", "content": q}],
                               max_tokens=512, thinking=True, effort="xhigh"))
        print("!!! 未报错：非法 effort 被静默接受，guard 失效")
        sys.exit(2)
    except ValueError as e:
        print(f"正确拒绝: {e}")
    print("API_SMOKE_OK")


if __name__ == "__main__":
    main()
