"""ModelAdapter：模型无关的统一访问层（ExoCortex 的硬约束所在）。

设计原则（对应立项分析的"模型无关"需求）：
1. 一切脚手架（投票/验证/回溯）只通过本协议调用模型，黑盒、零权重访问。
2. 每个 adapter 用 capabilities 诚实声明自己支持什么，不支持的能力由调用方降级，
   绝不静默伪造（例：无 effort 旋钮的端点收到 effort 参数时报错，而不是忽略）。
3. 记账字段统一：prompt_tokens / completion_tokens(含思考) / reasoning_tokens(能分则分)。

已覆盖的端点形态：
- LocalTransformersAdapter：本地 transformers（4bit），budget forcing（截断+注入 </think>）
- OpenAICompatAdapter：DeepSeek 官方 API（deepseek-flash / deepseek-v4-pro）、
  任何 OpenAI 兼容端点（vllm / 中转站）
- FakeAdapter：测试与冒烟用，无 GPU 依赖
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Capabilities:
    """诚实声明能力面。调用方据此降级，adapter 不做静默回退。"""

    thinking_toggle: bool = False       # 能否显式开/关思考模式
    effort_levels: tuple = ()           # 支持的思考强度档位，如 ("low","high","max")
    returns_reasoning: bool = False     # 能否拿到思维链文本
    supports_temperature: bool = True   # 思考模式下部分端点忽略温度
    notes: str = ""


@dataclass
class Generation:
    """单次采样的完整产物与记账。"""

    text: str                                   # 最终答案部分
    reasoning: str = ""                         # 思维链（拿不到则空串）
    prompt_tokens: int = 0
    completion_tokens: int = 0                  # 含思考 token
    reasoning_tokens: Optional[int] = None      # 端点能分则分，否则 None
    wall_clock: float = 0.0
    truncated: bool = False                     # budget forcing 是否触发了截断
    raw: dict = field(default_factory=dict)


@dataclass
class GenRequest:
    """一次生成的请求规格。effort 与 thinking 的组合由各 adapter 映射到自己的旋钮。"""

    messages: list                              # OpenAI 格式 [{"role","content"}]
    max_tokens: int = 4096                      # 输出上限（含思考）
    effort: Optional[str] = None                # None=端点默认; "low"/"high"/"max"/...
    thinking: bool = True
    temperature: float = 0.6
    seed: Optional[int] = None


class ModelAdapter(ABC):
    """所有模型的唯一入口。name 用于记账分臂。"""

    name: str = "base"
    capabilities: Capabilities = Capabilities()

    @abstractmethod
    def generate(self, req: GenRequest) -> Generation:
        ...

    def _validate_request(self, req: GenRequest) -> None:
        """统一校验：effort 不在声明面必须报错（绝不静默降级）。
        capabilities.effort_levels 为空表示该 adapter 用自己的 effort 语义
        （如本地 budget forcing 的数值映射），交由子类自行裁决。"""
        levels = self.capabilities.effort_levels
        if req.effort is not None and levels and req.effort not in levels:
            raise ValueError(f"{self.name} 支持 effort {levels}，收到 {req.effort!r}")

    def generate_n(self, req: GenRequest, n: int) -> list[Generation]:
        """n 次独立采样。端点原生支持 n 时可覆盖；默认循环串行（诚实计 wall-clock）。"""
        return [self.generate(req) for _ in range(n)]


# ---------------------------------------------------------------- 本地 transformers

class LocalTransformersAdapter(ModelAdapter):
    """本地 4bit 模型 + budget forcing。

    budget forcing（s1 式）：思考 token 超过 budget 且尚未出现 </think> 时，
    截断生成、硬拼 "</think>" 后让模型直接作答。实现取两段式 generate：
    第一段生成思考（带 stop 条件），第二段重前向续写答案。
    代价是可能多一次 prefill（wall-clock 开销，不影响正确性），阶段 0 接受。
    """

    CLOSE_THINK = "</think>"

    def __init__(self, model_path: str, gpu_max_kv_tokens: int = 8192,
                 kv_8bit: bool = False):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        self.torch = torch
        self.kv_8bit = kv_8bit
        bnb = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
        )
        self.tok = AutoTokenizer.from_pretrained(model_path)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            quantization_config=bnb,
            device_map="cuda:0",
        )
        self.model.eval()
        self.gpu_max_kv_tokens = gpu_max_kv_tokens
        # 关键 id，预算注入用
        self.close_id = self.tok.encode(self.CLOSE_THINK, add_special_tokens=False)
        self.name = "local:" + model_path.split("/")[-1].split("\\")[-1]
        self.capabilities = Capabilities(
            thinking_toggle=False,      # Thinking 版只支持思考模式（模板强制 <think>）
            effort_levels=(),           # 无原生 effort 旋钮，强度由 budget 数值控制
            returns_reasoning=True,
            supports_temperature=True,
            notes=("budget forcing via token截断+注入</think>；强度=budget数值"
                   + ("；KV 8bit 量化启用" if kv_8bit else "")),
        )
        # KV 8bit 量化配置（transformers QuantizedCacheConfig，运行时探测可用性）
        self._quant_cache_config = None
        if kv_8bit:
            try:
                from transformers.cache_utils import QuantizedCacheConfig
                self._quant_cache_config = QuantizedCacheConfig(nbits=8)
            except Exception as e:   # 版本不支持则诚实回退
                print(f"[kv_8bit] 不可用，回退 fp16 KV：{e}")
                self._quant_cache_config = None

    def _apply_chat(self, messages: list) -> str:
        return self.tok.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

    @staticmethod
    def _effort_to_budget(effort: Optional[str], req_max: int) -> Optional[int]:
        """把 effort 档位映射为思考 token 预算（本地模型的强度旋钮）。
        None → 不限制（用满 max_tokens）。"""
        table = {"xlow": 64, "low": 256, "medium": 1024, "high": 4096}
        if effort is None:
            return None
        if effort in table:
            return table[effort]
        if effort.isdigit():
            return int(effort)          # 允许直接传数字预算
        raise ValueError(f"本地 adapter 不支持 effort={effort!r}，可用：{list(table)} 或数字预算")

    def generate(self, req: GenRequest) -> Generation:
        torch = self.torch
        t0 = time.perf_counter()
        prompt_ids = self.tok.encode(self._apply_chat(req.messages), add_special_tokens=False)
        input_ids = torch.tensor([prompt_ids], device="cuda:0")
        prompt_len = input_ids.shape[1]

        budget = self._effort_to_budget(req.effort, req.max_tokens)
        budget = min(budget, req.max_tokens) if budget else req.max_tokens
        budget = min(budget, self.gpu_max_kv_tokens - prompt_len)
        answer_room = max(req.max_tokens - budget, 256)

        # 第一段：生成思考（到 budget 为止）
        with torch.no_grad():
            gen_kw = dict(
                max_new_tokens=budget,
                do_sample=req.temperature > 0,
                temperature=max(req.temperature, 1e-4),
                top_p=0.95,
                top_k=20,
                pad_token_id=self.tok.eos_token_id,
            )
            if self._quant_cache_config is not None:
                gen_kw["cache_implementation"] = "quantized"
                gen_kw["cache_config"] = self._quant_cache_config
            out = self.model.generate(
                input_ids,
                **gen_kw,
            )
        gen_ids = out[0][prompt_len:].tolist()
        truncated = False

        # 思考是否自然闭合
        gen_text = self.tok.decode(gen_ids, skip_special_tokens=True)
        if self.CLOSE_THINK not in gen_text:
            truncated = True
            # 第二段：硬拼 </think> 强制作答（重新前向，代价换可靠性）
            forced = gen_ids + list(self.close_id)
            forced_tensor = torch.tensor([prompt_ids + forced], device="cuda:0")
            with torch.no_grad():
                gen_kw2 = dict(
                    max_new_tokens=answer_room,
                    do_sample=req.temperature > 0,
                    temperature=max(req.temperature, 1e-4),
                    top_p=0.95,
                    top_k=20,
                    pad_token_id=self.tok.eos_token_id,
                )
                if self._quant_cache_config is not None:
                    gen_kw2["cache_implementation"] = "quantized"
                    gen_kw2["cache_config"] = self._quant_cache_config
                out2 = self.model.generate(
                    forced_tensor,
                    **gen_kw2,
                )
            full_ids = out2[0].tolist()
            full_ids = full_ids[len(prompt_ids):]
            gen_ids = full_ids
            gen_text = self.tok.decode(gen_ids, skip_special_tokens=True)

        # 拆思考与答案
        if self.CLOSE_THINK in gen_text:
            reasoning, _, answer = gen_text.partition(self.CLOSE_THINK)
        else:
            reasoning, answer = gen_text, ""
        n_reason = len(self.tok.encode(reasoning, add_special_tokens=False))
        n_total = len(self.tok.encode(gen_text, add_special_tokens=False))
        return Generation(
            text=answer.strip(),
            reasoning=reasoning.strip(),
            prompt_tokens=prompt_len,
            completion_tokens=n_total,
            reasoning_tokens=n_reason,
            wall_clock=time.perf_counter() - t0,
            truncated=truncated,
        )


# ---------------------------------------------------------------- OpenAI 兼容端点

class OpenAICompatAdapter(ModelAdapter):
    """DeepSeek 官方 API / 任何 OpenAI 兼容端点。

    DeepSeek 形态（api-docs，2026-10 核对）：
    - 开关：extra_body {"thinking": {"type": "enabled"/"disabled"}}，默认开
    - 强度：reasoning_effort in {"low","high","max"}（官方映射表 flash/pro 一致，
      low→low, high→high, max→max；传 medium 会被映射为 high，因此只暴露三档）
    - CoT 在 message.reasoning_content；usage.completion_tokens 含思考
    """

    def __init__(self, base_url: str, api_key: str, model: str,
                 effort_levels: tuple = ("low", "high", "max")):
        import requests
        self.requests = requests
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_id = model
        self.name = f"api:{model}"
        self.capabilities = Capabilities(
            thinking_toggle=True,
            effort_levels=tuple(effort_levels),
            returns_reasoning=True,
            supports_temperature=False,  # DeepSeek 思考模式下温度参数无效
            notes="reasoning_effort + thinking.type；completion_tokens 含思考",
        )

    def generate(self, req: GenRequest) -> Generation:
        self._validate_request(req)
        body: dict = {
            "model": self.model_id,
            "messages": req.messages,
            "max_tokens": req.max_tokens,
            "stream": False,
        }
        if self.capabilities.thinking_toggle:
            body["thinking"] = {"type": "enabled" if req.thinking else "disabled"}
        if req.effort is not None and req.thinking:
            body["reasoning_effort"] = req.effort
        if req.seed is not None:
            body["seed"] = req.seed
        if req.thinking is False or self.capabilities.supports_temperature:
            body["temperature"] = req.temperature

        t0 = time.perf_counter()
        resp = self.requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
            timeout=600,
        )
        wall = time.perf_counter() - t0
        if resp.status_code != 200:
            raise RuntimeError(f"{self.name} HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        msg = data["choices"][0]["message"]
        usage = data.get("usage", {})
        reasoning = msg.get("reasoning_content") or ""
        content = msg.get("content") or ""
        # DeepSeek 的 completion_tokens 已含思考；OpenAI o 系可从 details 拆
        comp = int(usage.get("completion_tokens", 0))
        details = usage.get("completion_tokens_details") or {}
        r_tok = details.get("reasoning_tokens")
        if r_tok is None and reasoning:
            r_tok = None  # 端点没单列就诚实置 None，不猜
        return Generation(
            text=content.strip(),
            reasoning=reasoning.strip(),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=comp,
            reasoning_tokens=int(r_tok) if r_tok else None,
            wall_clock=wall,
            truncated=data["choices"][0].get("finish_reason") == "length",
            raw={
                "id": data.get("id", ""),
                # DeepSeek 分时缓存计价字段（hit 比 miss 便宜 20-40×，成本分析必需）
                "prompt_cache_hit_tokens": usage.get("prompt_cache_hit_tokens"),
                "prompt_cache_miss_tokens": usage.get("prompt_cache_miss_tokens"),
                "finish_reason": data["choices"][0].get("finish_reason"),
            },
        )


# ---------------------------------------------------------------- 测试替身

class FakeAdapter(ModelAdapter):
    """冒烟/单测用：按给定分布返回伪答案，全程零 GPU。"""

    def __init__(self, answers: list[str], probs: list[float],
                 correct: str, tokens_per_call: int = 300):
        assert abs(sum(probs) - 1.0) < 1e-6
        import random
        self._rng = random.Random(0)
        self._answers, self._probs, self._correct = answers, probs, correct
        self._tokens = tokens_per_call
        self.name = "fake"
        self.capabilities = Capabilities(
            thinking_toggle=True, effort_levels=("low", "high"), returns_reasoning=False,
            notes="test double",
        )
        self.n_calls = 0

    def generate(self, req: GenRequest) -> Generation:
        self._validate_request(req)
        self.n_calls += 1
        text = self._rng.choices(self._answers, weights=self._probs, k=1)[0]
        return Generation(
            text=text,
            reasoning="",
            prompt_tokens=100,
            completion_tokens=self._tokens,
            reasoning_tokens=self._tokens - 40,
            wall_clock=0.01,
        )


def adapter_from_config(cfg: dict) -> ModelAdapter:
    """从配置字典构造 adapter。cfg 例：
    {"type":"local","model_path":...}
    {"type":"openai","base_url":"https://api.deepseek.com","api_key":...,"model":"deepseek-flash"}
    """
    kind = cfg["type"]
    if kind == "local":
        return LocalTransformersAdapter(cfg["model_path"])
    if kind == "openai":
        return OpenAICompatAdapter(
            cfg["base_url"], cfg["api_key"], cfg["model"],
            effort_levels=tuple(cfg.get("effort_levels", ("low", "high", "max"))),
        )
    if kind == "fake":
        return FakeAdapter(**cfg["args"])
    raise ValueError(f"未知 adapter 类型 {kind!r}")
