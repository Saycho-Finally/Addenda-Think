"""验证与聚合工具。

阶段 0 的"项目验证"用答案级验证（程序比对）；
真·代码执行器 sandbox 是阶段 2 E2 的事，放这里同族但不混用。
"""

from __future__ import annotations

from collections import Counter


def normalize_answer(text: str) -> str:
    """投票前的答案键规范化：去空白、统一大小写。"""
    return text.strip().replace(" ", "").replace("，", ",").lower()


def majority_vote(answers: list[str]) -> tuple[str | None, dict[str, int]]:
    """多数投票。返回 (获胜答案或 None, 计数分布)。空答案不参与。"""
    keys = [normalize_answer(a) for a in answers if a and a.strip()]
    if not keys:
        return None, {}
    counter = Counter(keys)
    top, cnt = counter.most_common(1)[0]
    # 并列时返回 None（诚实：不确定就不装确定），计数分布照报
    if list(counter.values()).count(cnt) > 1:
        return None, dict(counter)
    return top, dict(counter)


def coverage_selection_split(candidates: list[str], checker) -> dict:
    """coverage/selection 误差分解（立项分析的第三个空位）。

    coverage：N 个候选里是否存在正确答案（项目搜索救不了 coverage 失败）
    selection：正确答案存在时，投票/验证能否选中
    """
    keys = [a for a in candidates if a and a.strip()]
    hit = [a for a in keys if checker(a)]
    cov = len(hit) > 0
    if not cov:
        return {"coverage": False, "selection": None, "n_candidates": len(keys)}
    # 用与投票同构的规则选，看选中的是否正确
    top, _ = majority_vote(keys)
    sel_ok = (top is not None) and checker(top)
    return {"coverage": True, "selection": sel_ok, "n_candidates": len(keys)}
