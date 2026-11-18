"""自我學習 RAG：把 Agent 觀察堆進知識圖譜，並支援關聯性問答。

對齊參考設計：
  - 自動更新：每筆 Observation 進來就把其三元組併入圖（含 LLM 抽取補充）
  - 遞迴檢索 / 多跳推理：問答時從相關錨點出發走訪子圖
  - 記憶：保存每次問答產生的子圖，作為後續查詢背景
"""
from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..storage.models import Observation, Triple
from .graph import KnowledgeGraph
from .llm import LLMClient
from .ontology import relevant_anchors


class SelfLearningRAG:
    def __init__(self, config: Config):
        self.config = config
        self.graph = KnowledgeGraph()
        self.graph.load(config.kg.path)
        self.llm = LLMClient(config.llm)
        # 記憶：歷史問答產生的子圖（多階段推理背景）
        self.memory: list[dict] = []

    # ---- 學習：把觀察併入圖 ----
    def ingest(self, obs: Observation) -> int:
        added = 0
        for subj, pred, obj in obs.relations:
            self.graph.add_triple(subj, pred, obj, source=obs.source, ts=obs.ts,
                                  summary=obs.summary)
            added += 1
        # 額外用 LLM 從摘要抽補充三元組（mock 時回空）
        for subj, pred, obj in self.llm.extract_triples(obs.summary):
            self.graph.add_triple(subj, pred, obj, source=obs.source, ts=obs.ts)
            added += 1
        return added

    def ingest_many(self, observations: list[Observation]) -> int:
        total = sum(self.ingest(o) for o in observations)
        self.persist()
        return total

    # ---- 問答：遞迴檢索 + 多跳 + 記憶 ----
    def ask(self, question: str) -> dict:
        anchors = relevant_anchors(question, self.config.symbols)
        triples: list[Triple] = self.graph.subgraph(anchors, max_hops=self.config.kg.max_hops)
        answer = self.llm.answer(question, triples)
        record = {"question": question, "anchors": anchors,
                  "triples": triples, "answer": answer}
        self.memory.append(record)      # 記憶此次問答子圖
        return record

    def persist(self) -> None:
        Path(self.config.kg.path).parent.mkdir(parents=True, exist_ok=True)
        self.graph.save(self.config.kg.path)

    def stats(self) -> dict:
        return {**self.graph.stats(), "memory_queries": len(self.memory)}
