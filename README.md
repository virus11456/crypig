# Crypig — 加密貨幣量化分析 Agent 中台

多個資料源各派一隻 **Agent** 採集 → 觀察堆進 **自我學習 RAG 知識圖譜** 當記憶 →
產出 **綜合偏多/偏空評分** 與 **關聯性問答**。

## 架構

```
   ┌────────────────── Orchestrator（協調中台）──────────────────┐
   │                                                             │
┌──┴───────┐ ┌──────────┐ ┌───────────┐         ┌──────────────┐
│SmartMoney│ │  Whale   │ │ Divergence│  ...    │ Twitter(二期) │   ← 多個 Agent
│  Agent   │ │  Agent   │ │   Agent   │         │              │
└──┬───────┘ └────┬─────┘ └─────┬─────┘         └──────┬───────┘
   │ 產生 Observation（多空方向 + 強度 + KG 三元組）       │
   └──────────────┬──────────────────────────────────────┘
                  ▼
   ┌──────────────────────────────────────────────────────┐
   │  自我學習 RAG 知識圖譜（記憶 + 學習）                     │
   │   • 自動更新：新觀察即時併入圖                            │
   │   • 按需本體論：依問題挑相關子圖檢索                       │
   │   • 遞迴檢索 + 多跳推理：跨概念走訪關係                    │
   └───────────────┬──────────────────────────────────────┘
                   ▼
        Aggregate → 綜合偏多/偏空評分  +  關聯性問答 API（/ask）
```

**三層解耦**：採集（Agent）/ 記憶（KG）/ 分析（Aggregate）彼此獨立，任一資料源故障不影響其他。

## 資料源

| Agent | 訊號 | 來源 | 狀態 |
|---|---|---|---|
| `smart_money` | 聰明錢多空 | Hyperliquid leaderboard + 持倉 | ✅ 真實資料 |
| `whale_flow` | 全市場持倉量 + 資金費率 | CoinGecko 聚合各交易所衍生品 OI（含快照算變化）| ✅ 真實資料 |
| `divergence` | 量價頂/底背離 | OKX OHLCV（httpx REST）| ✅ 真實資料（RSI + 量能）|
| `lth_supply` | 長期持有者(≥151天)供給變化 | bitcoin-data.com 鏈上（illiquid-supply）| ✅ 真實資料（BTC；含快照算變化）|
| `twitter`(二期) | KOL/機構/美聯儲情緒 | X API + LLM 打分 | 規劃中 |

> **網路/地緣備註**：環境為美國 IP，`binance.com` 被封鎖(451)；改用 OKX。
> ccxt 在沙箱無法走 proxy，故用 httpx 直打 REST。時序快照存 SQLite（`snapshots.db`），
> 讓「持倉變化 / LTH 變化」可跨輪計算。

## 知識圖譜（自我學習 RAG）

對齊「遞迴檢索 + 按需本體論 + 記憶與多跳推理 + 自動更新」：

- `kg/graph.py` — 圖儲存與多跳走訪（純 Python，可換 Neo4j/RDFLib）
- `kg/ontology.py` — 加密領域本體；依問題挑相關起點（按需）
- `kg/llm.py` — 可插拔 LLM（預設 mock，可換 **Claude** / OpenAI）
- `kg/rag.py` — 串接：觀察入圖、問答檢索、記憶歷史子圖

> 預設 LLM 用 Claude（`claude-opus-4-8`），而非範例文章的 OpenAI；介面可插拔，要換隨時換。

## 快速開始

```bash
pip install -r requirements.txt        # 骨架核心其實零外部相依也能跑
cp config.example.yaml config.yaml     # 預設 use_mock=true，無需金鑰

# 跑一輪（採集 → 入圖 → 評分 → 示範問答）
python scheduler.py --once

# 常駐排程
python scheduler.py

# 另開終端啟動 API
uvicorn crypig.dashboard.api:app --reload
#   POST /cycle  跑一輪      GET /signal  綜合評分
#   POST /ask    關聯性問答   GET /kg/stats 圖譜現況
```

## 接真實資料 / 真實 LLM

- 每個 agent 的 `fetch()` 內有 `TODO` 標好接點，替換即可，`analyze()` 不用動。
- `llm.py` 把 `provider` 改 `claude`、設好 `ANTHROPIC_API_KEY` 即啟用真實問答。
- 目前 mock 模式可端到端跑通，方便先驗證資料流與圖譜成長。

## 路線圖

1. ✅ 骨架：多 agent + 自我學習 KG + 綜合評分 + 問答（mock）
2. 接 Hyperliquid / 交易所淨流 / ccxt OHLCV 真實資料
3. 切換 Claude 真實問答與三元組抽取
4. 二期：Twitter 情緒 agent（KOL / 機構 / 美聯儲）
