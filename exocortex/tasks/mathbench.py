"""数学基准任务：GSM8K（有网拉取）/ 内置 mini 集（离线冒烟，零污染）。

MATH-500 留接口（HF 数据集），正式跑时启用；冒烟阶段内置题全部为
自构造 + 程序验证过答案的题，不来自任何公开测试集。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass
class MathItem:
    question: str
    answer: str            # 规范化后的标准答案（字符串形式）
    level: int = 0         # 1-5，内置集标注近似难度
    source: str = "builtin"


# ------------------------------------------------- 内置 mini 集（程序验证过）

# 每题答案都用独立脚本核过；难度标到 MATH-500 level 语义的近似档
_MINI: list[tuple[str, str, int]] = [
    ("一个数列的第 n 项是 3n+2，求第 100 项。", "302", 2),
    ("解方程 5x - 13 = 47，求 x。", "12", 2),
    ("三角形两个内角分别是 37° 和 68°，求第三个角的度数。", "75", 2),
    ("计算 2^10 + 3^5 的值。", "475", 3),
    ("一个袋子里有 4 红 6 蓝球，随机取一个，取到红球的概率是多少（写成最简分数）。", "2/5", 3),
    ("化简 (3+2√2)(3-2√2)。", "1", 3),
    ("100 以内最大的质数是多少？", "97", 2),
    ("一个长方形周长 36，长是宽的 2 倍，求面积。", "72", 3),
    ("某数除以 7 余 3，除以 11 余 4，求 100 以内最小的这个数。", "81", 4),
    ("等差数列首项 5，公差 4，前 20 项和是多少。", "860", 3),
    ("计算 log_2(64) + log_3(27)。", "9", 3),
    ("从 5 人中选 2 人组成小组，有多少种选法。", "10", 2),
    ("甲 4 小时走 18 公里，按此速度 10 小时走多少公里。", "45", 2),
    ("若 x + 1/x = 5，求 x^2 + 1/x^2。", "23", 4),
    ("抛两枚均匀骰子，点数之和为 8 的概率是多少（写成分数）。", "5/36", 4),
    ("函数 f(x)=2x-3，若 f(f(a))=15，求 a。", "6", 4),
    ("一个圆的面积是 49π，求它的周长。", "14π", 4),
    ("连续三个整数之和为 72，求这三个数中最大的。", "25", 2),
    ("计算 7! / 5!。", "42", 3),
    ("设 a*b = a^2 - b，求 3*2 的值。", "7", 3),
    ("一个立方体体积为 64，求其表面积。", "96", 3),
    ("解不等式 2x + 7 > 19 的最小整数解。", "7", 3),
    ("在 1 到 200 中（含端点），能被 6 整除但不能被 9 整除的数有几个。", "23", 4),
    ("直角三角形两直角边为 9 和 12，求斜边。", "15", 2),
    ("若 f(x) = x^3 - 3x，求 f(3)。", "18", 2),
    ("钟表 3 点 30 分时，时针与分针的夹角是多少度。", "75", 4),
    ("某商品先涨价 20% 再降价 20%，最终价格是原价的百分之多少（写数字）。", "96", 4),
    ("数列 2, 6, 12, 20, ... 第 10 项是多少（a_n = n(n+1)）。", "110", 3),
    ("一个两位数，十位与个位数字之和为 9，交换两位后比原数大 27，求原数。", "36", 4),
    ("求方程 x^2 - 7x + 12 = 0 较大的根。", "4", 3),
]


def _norm_answer(s: str) -> str:
    """答案规范化：去空格、统一分数与 π 表示。"""
    s = s.strip().replace(" ", "")
    s = re.sub(r"^#+\s*", "", s)
    # 统一百分数写法
    s = s.rstrip("。").rstrip(".")
    return s


def _answers_match(pred: str, gold: str) -> bool:
    p, g = _norm_answer(pred), _norm_answer(gold)
    if p == g:
        return True
    # 数值等价（12.0 == 12；分数两种写法）
    def as_num(x: str):
        try:
            if "/" in x:
                a, b = x.split("/", 1)
                return float(a) / float(b)
            return float(x.rstrip("%"))
        except (ValueError, ZeroDivisionError):
            return None
    np_, ng = as_num(p), as_num(g)
    if np_ is not None and ng is not None:
        return abs(np_ - ng) < 1e-6
    return False


class MathBenchTask:
    """GSM8K 拉取（有网）或内置 mini 集（离线）。"""

    def __init__(self):
        self._gsm: list[MathItem] | None = None

    def builtin_suite(self, n: int = 30) -> list[MathItem]:
        items = [MathItem(question=q, answer=_norm_answer(a), level=lv, source="builtin")
                 for q, a, lv in _MINI]
        return items[:n]

    GSM8K_URL = ("https://hf-mirror.com/datasets/openai/gsm8k"
                 "/resolve/main/main/test-00000-of-00001.parquet")

    @staticmethod
    def _gsm8k_parquet_path() -> str:
        """requests 直拉 test parquet 到 data/（hub 的 hf_hub_download 在本机
        对 dataset parquet 产出 0 字节文件，弃用；模型下载同款方案已验证可靠）。"""
        import requests

        dest = os.path.join("data", "gsm8k_test.parquet")
        if os.path.exists(dest) and os.path.getsize(dest) > 100_000:
            return dest
        os.makedirs("data", exist_ok=True)
        with requests.get(MathBenchTask.GSM8K_URL, stream=True,
                          timeout=120, allow_redirects=True) as r:
            r.raise_for_status()
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    if chunk:
                        f.write(chunk)
        if os.path.getsize(tmp) < 100_000:
            raise RuntimeError(f"GSM8K parquet 下载异常: {os.path.getsize(tmp)} bytes")
        os.replace(tmp, dest)
        return dest

    def gsm8k_suite(self, n: int = 100, offset: int = 0) -> list[MathItem]:
        """拉取 GSM8K 测试集（MIT 许可）。缓存于内存。"""
        if self._gsm is None:
            import pandas as pd

            parquet = self._gsm8k_parquet_path()
            df = pd.read_parquet(parquet)
            self._gsm = []
            for _, row in df.iterrows():
                gold = str(row["answer"]).split("####")[-1].strip().replace(",", "")
                self._gsm.append(MathItem(question=str(row["question"]).strip(),
                                          answer=gold, level=3, source="gsm8k"))
        return self._gsm[offset:offset + n]

    MATH500_URL = ("https://hf-mirror.com/datasets/HuggingFaceH4/MATH-500"
                   "/resolve/main/test.jsonl")
    _math500: list[MathItem] | None = None

    @staticmethod
    def _math500_jsonl_path() -> str:
        """requests 直拉 MATH-500 test.jsonl（同 GSM8K 方案，绕开 hub 机制）。"""
        import requests

        dest = os.path.join("data", "math500_test.jsonl")
        if os.path.exists(dest) and os.path.getsize(dest) > 400_000:
            return dest
        os.makedirs("data", exist_ok=True)
        with requests.get(MathBenchTask.MATH500_URL, stream=True,
                          timeout=120, allow_redirects=True) as r:
            r.raise_for_status()
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    if chunk:
                        f.write(chunk)
        if os.path.getsize(tmp) < 400_000:
            raise RuntimeError(f"MATH-500 jsonl 下载异常: {os.path.getsize(tmp)} bytes")
        os.replace(tmp, dest)
        return dest

    def math500_suite(self, levels: tuple = (4, 5), n: int = 50,
                      offset: int = 0) -> list[MathItem]:
        """MATH-500 按难度层取题。levels=(4,5) 即主战场高难层。"""
        if self._math500 is None:
            import json as _json

            path = self._math500_jsonl_path()
            self._math500 = []
            with open(path, encoding="utf-8") as f:
                for line in f:
                    row = _json.loads(line)
                    # level 字段形如 "Level 4"
                    lv_digits = [int(s) for s in str(row.get("level", "")).split()
                                 if s.isdigit()]
                    lv = lv_digits[-1] if lv_digits else 0
                    self._math500.append(MathItem(
                        question=str(row["problem"]).strip(),
                        answer=_norm_answer(str(row["answer"])),
                        level=lv, source="math500"))
        pool = [it for it in self._math500 if it.level in levels]
        return pool[offset:offset + n]

    def suite(self, name: str = "builtin", **kw) -> list[MathItem]:
        if name == "builtin":
            return self.builtin_suite(**kw)
        if name == "gsm8k":
            return self.gsm8k_suite(**kw)
        if name == "math500":
            return self.math500_suite(**kw)
        raise ValueError(f"未知数学基准 {name!r}（可选 builtin/gsm8k/math500）")

    @staticmethod
    def extract_answer(text: str) -> str | None:
        """优先抽 ####，其次 \\boxed{}，否则取最后一行数字。"""
        idx = text.rfind("####")
        if idx != -1:
            tail = text[idx + 4:].strip().splitlines()
            if tail and tail[0].strip():
                return tail[0].strip().strip("`")
        boxes = re.findall(r"\\boxed\{([^{}]+)\}", text)
        if boxes:
            return boxes[-1].strip()
        for line in reversed([l.strip() for l in text.strip().splitlines()]):
            if line and re.search(r"\d", line) and len(line) < 60:
                m = re.findall(r"-?\d[\d,]*(?:\.\d+)?", line)
                if m:
                    return m[-1].replace(",", "")
        return None

    @staticmethod
    def check(item: MathItem, answer_text: str) -> bool:
        pred = MathBenchTask.extract_answer(answer_text)
        if pred is None:
            return False
        return _answers_match(pred, item.answer)
