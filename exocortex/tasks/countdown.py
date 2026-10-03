"""Countdown 任务（程序可验证，无污染，难度可控）。

Illusion of Thinking（Apple, 2506）同款任务域：给 N 个数字与目标值，
用四则运算（每数恰好用一次）凑出目标。本题生成器通过"先造表达式再出题"
保证每题必有解；验证用 AST 白名单求值 + 数字多重集检查（分数精确运算）。

难度由数字个数控制：3 个=中，4 个=中难，5 个=难。
"""

from __future__ import annotations

import ast
import operator
import random
from dataclasses import dataclass
from fractions import Fraction

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}

ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)
MAX_EXPONENT = 6  # 幂运算限制指数，防爆炸


def safe_eval_expr(expr: str, allowed_numbers: list[int]) -> Fraction:
    """AST 白名单求值 + 数字使用检查。返回精确分数结果。

    抛 ValueError 的一切情况：非法语法、非法运算、数字不匹配、除零、
    负数中间结果（Countdown 惯例）、指数超限。
    """
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as e:
        raise ValueError(f"语法错误: {e}") from e

    used: list[Fraction] = []

    def ev(node: ast.AST) -> Fraction:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, int) and not isinstance(node.value, bool):
                used.append(Fraction(node.value))
                return Fraction(node.value)
            raise ValueError(f"非法常量 {node.value!r}")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ALLOWED_BINOPS):
            l, r = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Div) and r == 0:
                raise ValueError("除零")
            val = _OPS[type(node.op)](l, r)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            val = -ev(node.operand)
        else:
            raise ValueError(f"非法节点 {type(node).__name__}")
        if val.denominator != 1:
            raise ValueError("中间结果出现非整数（Countdown 惯例不允许）")
        if val < 0:
            raise ValueError("中间结果为负")
        return val

    result = ev(tree)

    if any(n.numerator == n.denominator and n.numerator == 1 for n in []):  # pragma: no cover
        pass
    # 数字多重集匹配：每个给定数恰好用一次
    if sorted(int(x) for x in used) != sorted(allowed_numbers):
        raise ValueError(f"数字使用不匹配: 用了 {sorted(int(x) for x in used)}，给定 {sorted(allowed_numbers)}")
    return result


@dataclass
class CountdownItem:
    numbers: list[int]
    target: int
    level: int                    # 3/4/5 = 数字个数，即难度；6/7 = 大模型边缘档
    solution_expr: str            # 生成时的参考解（仅用于调试/抽样核对，不进 prompt）

    # 缓存友好拆分（CACHE 工程实测：共享说明应长且稳定，题目只占尾巴）
    INSTRUCTION = (
        "你是一个计算谜题求解器。规则：\n"
        "1. 使用给定的数字和四则运算（+ - * /，可用括号），每个数字恰好使用一次。\n"
        "2. 可以使用幂运算 **，但指数不得超过 6。\n"
        "3. 中间结果必须保持为正整数。\n"
        "4. 一步步推理，检查每一步。\n"
        "5. 最终单独一行输出：#### <表达式>\n"
        "表达式只允许使用 + - * / ( ) ** 和给定数字。"
    )

    @property
    def tail(self) -> str:
        """每题变化的部分（缓存友好模式下的 user 尾巴）。"""
        nums = ", ".join(map(str, self.numbers))
        return f"数字：{nums}。目标：{self.target}。"

    @property
    def prompt(self) -> str:
        """旧口径（说明+题目混合），保留以兼容已有数据对比。"""
        nums = ", ".join(map(str, self.numbers))
        return (
            f"用数字 {nums} 和四则运算（每个数字恰好用一次，可用括号），"
            f"使结果等于 {self.target}。\n"
            "一步步想，最后单独一行输出：#### <表达式>\n"
            "表达式只允许使用 + - * / ( ) 和上述数字（整数，可用幂 ** 但指数不超过 6）。"
        )


def _random_expr(rng: random.Random, numbers: list[int]) -> tuple[str, int]:
    """对给定数字随机造一棵合法表达式树，返回 (表达式, 值)。中间结果保持正整数。"""
    nums = list(numbers)
    rng.shuffle(nums)
    # 从第一个数开始，逐步用运算合并剩余数
    acc_val = Fraction(nums[0])
    parts = [str(nums[0])]
    for n in nums[1:]:
        for _attempt in range(50):
            op = rng.choice(["+", "-", "*", "/"])
            if op == "+":
                new_val, new_expr = acc_val + n, f"({parts[0]} + {n})"
            elif op == "-":
                if acc_val - n <= 0:
                    continue
                new_val, new_expr = acc_val - n, f"({parts[0]} - {n})"
            elif op == "*":
                new_val, new_expr = acc_val * n, f"({parts[0]} * {n})"
            else:
                if n == 0 or acc_val % n != 0 or acc_val / n <= 0:
                    continue
                new_val, new_expr = acc_val / n, f"({parts[0]} / {n})"
            acc_val, parts = new_val, [new_expr]
            break
        else:
            # 50 次都造不出合法合并，回退为加法（总是合法）
            acc_val, parts = acc_val + n, [f"({parts[0]} + {n})"]
    return parts[0], int(acc_val)


class CountdownTask:
    """生成与验证。target_range 限制目标值规模，防止验证写起来失真。"""

    def __init__(self, seed: int = 0, big_number_prob: float = 0.25):
        self.rng = random.Random(seed)
        self.big_number_prob = big_number_prob

    def _draw_number(self) -> int:
        if self.rng.random() < self.big_number_prob:
            return self.rng.choice([25, 50, 75, 100])
        return self.rng.randint(1, 13)

    def make_item(self, level: int) -> CountdownItem:
        assert 3 <= level <= 7, "3-5=经典档，6-7=大模型能力边缘档"
        for _ in range(200):
            numbers = [self._draw_number() for _ in range(level)]
            expr, val = _random_expr(self.rng, numbers)
            # 目标别太离谱（>9999 或 <25 的题没有区分度）
            if 25 <= val <= 9999 and val not in (0, 1):
                return CountdownItem(numbers=numbers, target=val,
                                     level=level, solution_expr=expr)
        raise RuntimeError("200 次未能生成合法 Countdown 题（不应发生）")

    def make_suite(self, n_per_level: int = 20,
                   levels: tuple = (3, 4, 5)) -> list[CountdownItem]:
        return [self.make_item(lv) for lv in levels for _ in range(n_per_level)]

    @staticmethod
    def extract_answer(text: str) -> str | None:
        """从模型输出抽 #### 后的表达式。"""
        marker = "####"
        idx = text.rfind(marker)
        if idx == -1:
            # 兜底：最后一个形如表达式的行
            for line in reversed([l.strip() for l in text.strip().splitlines()]):
                if line and any(c in line for c in "+-*/") and any(ch.isdigit() for ch in line):
                    return line
            return None
        tail = text[idx + len(marker):].strip().splitlines()
        return tail[0].strip().strip("`") if tail and tail[0].strip() else None

    @staticmethod
    def check(item: CountdownItem, answer_text: str) -> bool:
        expr = CountdownTask.extract_answer(answer_text)
        if not expr:
            return False
        try:
            val = safe_eval_expr(expr, item.numbers)
        except (ValueError, RecursionError, OverflowError):
            return False
        return val == item.target
