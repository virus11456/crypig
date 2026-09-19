"""加密領域本體（按需本體論）。

定義實體型別與關係詞彙，並提供「依問題挑出相關起點節點」的功能，
讓 RAG 只針對與問題相關的子圖做檢索，而非掃整張圖。
"""
from __future__ import annotations

# 實體型別
ENTITY_TYPES = {
    "asset",        # BTC / ETH ...
    "cohort",       # smart_money / whales
    "venue",        # exchanges
    "indicator",    # RSI / OBV
    "person",       # KOL / 交易所負責人 / 美聯儲官員（二期）
    "institution",  # 機構（二期）
}

# 關係詞彙（謂詞）
RELATION_TYPES = {
    "is_bull_on", "is_bear_on", "is_neutral_on",
    "net_inflow_to_exchanges", "net_outflow_from_exchanges",
    "shows_bull_divergence_on", "shows_bear_divergence_on",
    "mentions", "influences",   # 二期推特情緒用
}


def relevant_anchors(question: str, symbols: list[str]) -> list[str]:
    """從問題文字中挑出可能的起點節點（按需：只取相關概念）。"""
    q = question.lower()
    anchors: list[str] = []
    for s in symbols:
        if s.lower() in q:
            anchors.append(s)
    keyword_map = {
        "聰明錢": "smart_money", "smart money": "smart_money",
        "鯨魚": "whales", "whale": "whales",
        "交易所": "exchanges", "exchange": "exchanges",
        "背離": "RSI", "divergence": "RSI", "rsi": "RSI",
    }
    for kw, node in keyword_map.items():
        if kw in q:
            anchors.append(node)
    # 沒抓到就退回所有標的當起點
    return anchors or list(symbols)
