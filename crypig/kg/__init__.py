"""知識圖譜記憶層：自我學習 RAG。

設計對齊「遞迴檢索 + 按需本體論 + 記憶與多跳推理 + 自動更新」：
  - graph.py     圖儲存（節點=實體，邊=關係），多跳走訪
  - ontology.py  加密領域本體；按需依問題挑相關子圖
  - llm.py       可插拔 LLM（預設 mock，可換 Claude / OpenAI）
  - rag.py       串起來：觀察入圖、問答檢索、記憶歷史子圖
"""
from .graph import KnowledgeGraph
from .rag import SelfLearningRAG

__all__ = ["KnowledgeGraph", "SelfLearningRAG"]
