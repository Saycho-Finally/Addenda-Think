"""无 GPU 冒烟：countdown 生成/验证、mathbench、FakeAdapter 全链路、Ledger 对账。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from exocortex.adapter import FakeAdapter, GenRequest
from exocortex.ledger import Ledger
from exocortex.scaffold.selfconsist import SelfConsistencyArm, SingleHighEffortArm
from exocortex.scaffold.verifier import coverage_selection_split, majority_vote
from exocortex.tasks import CountdownTask, MathBenchTask


def test_countdown():
    task = CountdownTask(seed=42)
    items = task.make_suite(n_per_level=30)
    assert len(items) == 90
    # 全部生成题的参考解必须通过自己的验证器（生成器自洽性）
    for it in items:
        assert CountdownTask.check(it, f"#### {it.solution_expr}"), \
            f"参考解未过验证: {it.solution_expr} -> {it.numbers} = {it.target}"
    # 负例：错误答案必须被拒
    it = items[0]
    wrong = it.target + 1
    assert not CountdownTask.check(it, f"#### {wrong}")
    # 抽取：#### 标记与无标记
    assert CountdownTask.extract_answer("思考... #### 3*4+2") == "3*4+2"
    print(f"countdown OK: 90 题生成+参考解全过验证, 抽取正常, 负例被拒")


def test_mathbench():
    task = MathBenchTask()
    suite = task.builtin_suite()
    assert len(suite) == 30
    # 抽取与判分
    it = suite[0]
    assert MathBenchTask.check(it, f"推理过程... #### {it.answer}")
    assert MathBenchTask.check(it, f"答案是 $\\boxed{{{it.answer}}}$")
    print("mathbench OK: 内置 30 题, #### 与 boxed 抽取判分正常")


def test_fake_full_chain():
    # FakeAdapter：正确率 60%，投票应显著高于单次；等算力对账完整
    adapter = FakeAdapter(["42", "43", "44"], probs=[0.6, 0.25, 0.15], correct="42")
    ledger = Ledger(meta={"smoke": True})
    sc = SelfConsistencyArm(adapter, ledger, arm_name="low256xN8")
    res = sc.run("fake question", n=8, effort="low", max_tokens=512)
    top, dist = majority_vote(res["candidates"])
    assert top == "42", f"投票结果 {top} 分布 {dist}"
    hi = SingleHighEffortArm(adapter, ledger, arm_name="high@4096")
    hi.run("fake question", effort="high", max_tokens=4096)
    rep = ledger.equal_compute_report()
    arms = {a["arm"]: a for a in rep["arms"]}
    assert arms["low256xN8"]["n_calls"] == 8
    assert arms["high@4096"]["n_calls"] == 1
    # token 记账: 8×300 vs 1×300
    assert arms["low256xN8"]["completion_tokens"] == 2400
    assert arms["high@4096"]["completion_tokens"] == 300
    # coverage/selection 分解
    split = coverage_selection_split(res["candidates"], lambda a: a.strip() == "42")
    assert split["coverage"] is True
    ledger.dump("results/smoke_ledger.json")
    print("fake chain OK: 投票正确, 记账对齐 (8x300 vs 300), coverage 分解正常, ledger 落盘")


def test_gen_request_guard():
    # effort 不在声明面必须报错（不静默降级）
    adapter = FakeAdapter(["x"], [1.0], correct="x")
    adapter.capabilities = type(adapter.capabilities)(
        thinking_toggle=True, effort_levels=("low", "high"), returns_reasoning=False)
    try:
        adapter.generate(GenRequest(messages=[{"role": "user", "content": "q"}],
                                    effort="max"))
        raise AssertionError("应当拒绝未声明 effort")
    except (ValueError, AttributeError):
        pass
    print("guard OK: 未声明 effort 会被拒绝")


if __name__ == "__main__":
    os.makedirs("results", exist_ok=True)
    test_countdown()
    test_mathbench()
    test_fake_full_chain()
    test_gen_request_guard()
    print("ALL_SMOKE_OK")
