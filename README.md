# Crypig — 加密貨幣量化分析中台

多資料源 **Agent** 採集 → **自我學習 RAG 知識圖譜** 記憶 → **綜合決策＋全市場掃描＋分歧雷達**，
並可匯出 **Obsidian 知識庫** 持續優化個人交易策略、尋找 alpha。

> **核心命題**：偵測**散戶/群眾情緒（恐懼貪婪·資金費率·新聞·Reddit）** 與
> **大戶持倉（聰明錢·鯨魚）** 之間的**分歧**——兩者反向時，往往是 alpha 進場點。

## 🌐 線上

- **VPS（主）**：`http://72.60.110.37:8000`（Hostinger 專屬 IP、真實資料、Docker 自架）
- 網域：`hypeboss.cc`（DNS 指向後，Caddy 自動 HTTPS）
- 手機可「加入主畫面」當 **PWA App**（離線載入 App 殼、有圖示與啟動畫面）

兩頁式中台（**響應式 RWD**，電腦/平板/手機自適應）：

- **📊 市場看板**：🎯 分歧雷達（含背離時間軸）/ 全市場宏觀 / 資金動向(DefiLlama) /
  🧭 大玩家決心（聰明錢 vs 巨鯨）/ 🐋 巨鯨 BTC 合約淨持倉時間軸 /
  幣別總表（全市場 230 幣：判斷·聰明錢多空·鯨魚多空·日線背離·資金費率·OI-Cap·市值）
- **🧠 策略·Obsidian**：下載知識庫 vault / 📰 新聞分析（利多·利空＋影響幣）/
  😱 恐懼貪婪指數（全區間）/ Reddit 散戶情緒 / RAG 問答 / 策略回測

## 找 alpha 的兩大支柱

### 1. 聰明錢 vs 巨鯨（兩群獨立的人）
- **🧠 聰明錢** ＝ **近 100 筆平倉「勝率＋獲利」最佳**的方向交易者。**排除做市商/高頻**
  （近 100 筆需橫跨 ≥24h，剔除幾小時內刷單、多空中性的帳號）。
  採**跨輪累積＋抓成交節流**：每輪只抓一小批成交（固定速率、不觸發 HL 限流），
  存活者併進**持久化累積池**，幾輪後滾到上限（~100），TTL 汰舊持續刷新。
- **🐋 巨鯨** ＝ **全市場淨值（accountValue）前 N 名**，與獲利/聰明錢**無關**（錢最多的人），
  並**過濾 HLP/做市金庫**等超大非個人帳號。
- 兩群為**獨立母體**（會量測重疊人數）——**方向相反時＝值得注意的分歧訊號**
  （例：會交易的贏家在做空，但最有錢的大戶在做多）。

### 2. 分歧雷達（群眾 vs 大戶）
- 群眾（各幣資金費率→擁擠方向、全市場恐懼貪婪）⟷ 大戶（聰明錢/鯨魚淨多空）反向＝候選。
- **背離時間軸**：每輪落地「背離量 gap」，趨近 0＝群眾向聰明錢靠攏＝**收斂＝接近進場時機**，
  並自動判讀「收斂中／擴大中／持平」。

## 功能總覽

| 層 | 內容 | 來源（皆免費/免金鑰或免費層） |
|---|---|---|
| 大玩家決心 | 聰明錢(近期勝率/獲利)/巨鯨(全市場淨值前N) 各幣淨多空＋20分鐘變化＋多空人數·槓桿·勝率 | Hyperliquid |
| 分歧雷達 | 群眾(情緒·費率) vs 大戶(聰明錢·鯨魚) 反向偵測＋背離時間軸(收斂=進場) | 綜合 |
| 全市場掃描 | 230 幣判斷·分數·信心（聰明錢＋資金費率＋日線背離輕量評分） | Hyperliquid |
| 量價背離 | 全幣日線底/頂背離（RSI＋量能） | Hyperliquid 日線 |
| 巨鯨持倉軸 | HL 巨鯨 BTC 合約淨持倉逐輪累積時間軸（穿越零軸＝翻多/翻空） | Hyperliquid |
| 宏觀 | 總市值/OI/OI-Cap/Vol-Cap/BTC市佔、各幣市值 | CoinGecko(Demo金鑰) |
| 資金動向 | DeFi TVL/穩定幣/各鏈 TVL | DefiLlama |
| 新聞分析 | 6 家媒體 RSS 關鍵字利多/利空＋影響幣、整體情緒、各幣淨情緒 | 加密媒體 RSS |
| 情緒 | 恐懼貪婪指數(全區間) / Reddit 散戶討論熱度 / (LunarCrush 需付費) | alternative.me / Reddit API |
| 決策/回測 | 綜合評分·信心·共識·動作建議；命中率＋損益曲線(真實K線對齊) | — |
| 知識庫 | Obsidian markdown 匯出(Coins/Journal/KOL/Strategies)、RAG 問答 | — |

## 架構

```
   ┌────────────────── Orchestrator（協調中台）──────────────────┐
┌──┴───────┐ ┌──────────┐ ┌───────────┐         ┌──────────────┐
│SmartMoney│ │  Whale   │ │ Divergence│  ...    │     LTH      │   ← 多個 Agent
│  Agent   │ │  Agent   │ │   Agent   │         │    Agent     │
└──┬───────┘ └────┬─────┘ └─────┬─────┘         └──────┬───────┘
   │ 產生 Observation（多空方向 + 強度 + KG 三元組）       │
   └──────────────┬──────────────────────────────────────┘
                  ▼
   ┌──────────────────────────────────────────────────────┐
   │  自我學習 RAG 知識圖譜（自動更新 + 按需本體論 + 多跳推理） │
   └───────────────┬──────────────────────────────────────┘
                   ▼
   全市場掃描 + 分歧雷達 + 綜合評分 + 關聯性問答(/ask) + Obsidian 匯出
```

**三層解耦**：採集（Agent）/ 記憶（KG）/ 分析（Aggregate）彼此獨立，任一資料源故障不影響其他。
所有外部源**背景每輪抓一次並快取**，請求端只讀快取（避免雲端 IP 被限流）；
`run_cycle` 有**非重入鎖**避免並發跑輪。

## 資料源

| 訊號 | 來源 | 狀態 |
|---|---|---|
| 聰明錢（近期勝率/獲利、排除做市、跨輪累積） | Hyperliquid leaderboard + userFills + 持倉 | ✅ |
| 巨鯨（全市場淨值前N、排除 HLP/金庫） | Hyperliquid leaderboard accountValue + 持倉 | ✅ |
| 量價頂/底背離 | Hyperliquid / OKX 日線（RSI＋量能） | ✅ |
| 長期持有者(≥155天)供給變化 | bitcoin-data.com | ✅（BTC）|
| 宏觀 / 各幣市值 | CoinGecko（Demo 金鑰，header `x-cg-demo-api-key`） | ✅ |
| 資金動向 TVL/穩定幣 | DefiLlama | ✅ |
| 新聞 利多/利空 | Cointelegraph/Decrypt/CryptoSlate/NewsBTC/CryptoPotato/AMBCrypto RSS | ✅ |
| 恐懼貪婪指數 | alternative.me（全區間 2018至今） | ✅ |
| Reddit 散戶情緒 | Reddit 官方唯讀 OAuth（需 app 憑證） | ✅（需憑證）|

## 部署（Docker / VPS）

專屬 IP 的 VPS 不會被 Hyperliquid 限流，可開大候選池、聰明錢累積到 ~100。

```bash
# VPS（Ubuntu）一鍵
curl -fsSL https://raw.githubusercontent.com/virus11456/crypig/claude/brave-ptolemy-nn1nd8/deploy_vps.sh | bash

# 或手動
git clone -b claude/brave-ptolemy-nn1nd8 https://github.com/virus11456/crypig.git && cd crypig
cp .env.example .env            # 填金鑰，皆可留空
docker compose up -d --build    # 看板：http://<VPS_IP>:8000
```

網域＋HTTPS（Caddy 自動憑證）見 `DEPLOY_VPS.md`。

### 環境變數（docker-compose.yml / .env）

| 變數 | 預設 | 說明 |
|---|---|---|
| `USE_MOCK` | false | `false` 用真實資料源 |
| `CRYPIG_DATA_DIR` | /data | sqlite/累積池/知識圖譜落地（掛 volume **持久化**，重啟不歸零）|
| `CRYPIG_POOL` | 600 | 聰明錢候選輪轉母體（每輪只抓一小批，非一次全抓）|
| `CRYPIG_INTERVAL_MIN` | 20 | 背景每幾分鐘跑一輪（可調小→更新更勤、累積更快）|
| `CRYPIG_SCHEDULER` | 1 | 背景排程開關 |
| 金鑰 | （.env） | `COINGECKO_API_KEY` / `REDDIT_CLIENT_ID`·`SECRET` / `LUNARCRUSH_API_KEY` / `ANTHROPIC_API_KEY`，皆可留空 |

> 資料持久化在 `crypig-data` volume；`docker compose down -v` 的 `-v` 才會刪。

也支援 Railway（含 `railway.toml`/`Procfile`），但**共享 IP 會被 HL 限流**，聰明錢填不滿，
故正式部署建議用 VPS。

## 本機開發

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml     # 預設 use_mock=true，無需金鑰
python scheduler.py --once             # 跑一輪（採集→入圖→評分→示範問答）
uvicorn crypig.dashboard.api:app --reload   # 看板 http://127.0.0.1:8000/
```

主要端點：`/`（看板）·`/positioning`（大玩家決心）·`/radar`·`/radar_history`·
`/scores`（全市場評分）·`/hl_market`·`/macro`·`/news`·`/social`·`/defi`·`/reddit`·
`/whale_history`·`/backtest`·`/decisions`·`/vault.zip`（Obsidian）·`POST /ask`（RAG）。

## 知識圖譜（自我學習 RAG）

- `kg/graph.py` 圖儲存與多跳走訪（純 Python，可換 Neo4j/RDFLib）
- `kg/ontology.py` 加密領域本體；依問題挑相關起點（按需）
- `kg/llm.py` 可插拔 LLM（預設 mock，可換 **Claude**）
- `kg/rag.py` 觀察入圖、問答檢索、記憶歷史子圖

預設 LLM 用 Claude（`claude-opus-4-8`）；介面可插拔。

## 路線圖

1. ✅ 多 agent + 自我學習 KG + 綜合評分 + 全市場掃描
2. ✅ 聰明錢(勝率/獲利)·巨鯨(全市場淨值) 分離、分歧雷達＋時間軸、新聞分析、Obsidian 匯出
3. ✅ Docker/VPS 部署、PWA/RWD、抓成交節流＋跨輪累積（不被限流滾到 ~100）
4. 切換 Claude 真實問答與三元組抽取；LunarCrush 社群情緒/KOL（付費後啟用）
