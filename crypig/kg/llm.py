"""可插拔 LLM 介面。

預設 provider="mock"，無金鑰即可端到端跑通。
provider="claude" 時用 Anthropic（建議，預設 claude-opus-4-8）。
provider="openai" 預留位。
兩個能力：
  extract_triples(text)  —— 從自然語言抽 (主, 謂, 受) 三元組（自動建圖用）
  answer(question, ctx)  —— 依檢索到的子圖脈絡作答
"""
from __future__ import annotations

import os

from ..config import LLMConfig
from ..storage.models import Triple


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    def extract_triples(self, text: str) -> list[Triple]:
        if self.cfg.provider == "mock":
            return []   # mock：觀察已自帶 relations，不需再抽
        return self._real_extract(text)

    def answer(self, question: str, context_triples: list[Triple]) -> str:
        if self.cfg.provider == "mock":
            return self._mock_answer(question, context_triples)
        return self._real_answer(question, context_triples)

    # ---- mock ----
    def _mock_answer(self, question: str, ctx: list[Triple]) -> str:
        if not ctx:
            return "（mock）知識圖譜中尚無與此問題相關的資訊。"
        lines = "\n".join(f"  - {s} —[{p}]→ {o}" for s, p, o in ctx[:20])
        return (
            f"（mock 作答，未呼叫真實 LLM）\n問題：{question}\n"
            f"依知識圖譜檢索到的相關關係：\n{lines}\n"
            f"提示：將 config.llm.provider 改為 'claude' 即可用 Claude 生成自然語言回答。"
        )

    # ---- 真實 provider（骨架）----
    def _client_key(self) -> str:
        key = os.environ.get(self.cfg.api_key_env, "")
        if not key:
            raise RuntimeError(f"環境變數 {self.cfg.api_key_env} 未設定")
        return key

    def _real_extract(self, text: str) -> list[Triple]:
        # TODO: 用 self.cfg.model 呼叫 LLM，要求輸出 JSON 三元組陣列
        raise NotImplementedError("真實 LLM 三元組抽取待實作")

    def _real_answer(self, question: str, ctx: list[Triple]) -> str:
        # TODO: 把 ctx 組成 prompt 脈絡，呼叫 Anthropic / OpenAI 生成回答
        raise NotImplementedError("真實 LLM 問答待實作")
