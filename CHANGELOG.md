# 更新日誌

本檔記錄 Crypig 的重要變更。日期格式 YYYY-MM-DD。

## [Unreleased]

### 2026-06-24

#### 新增
- **線上部署（Railway）**：`railway.toml` / `Procfile`（綁 `$PORT`），Nixpacks
  自動建置；公開網址 https://web-production-f997d.up.railway.app 。
- **CI/CD 自動部署**：service 連結 GitHub repo，push 到部署分支即自動重部署。
- **背景排程**：看板 app 加 FastAPI lifespan，部署後每 `CRYPIG_INTERVAL_MIN`
  分鐘自動跑一輪累積決策（`CRYPIG_SCHEDULER=0` 可關），單輪失敗不拖垮排程。
- **環境變數覆寫**：`USE_MOCK`（切真實源）、`CRYPIG_DATA_DIR`（sqlite/知識圖譜
  落到掛載 volume 以跨部署持久化）、`CRYPIG_SCHEDULER`、`CRYPIG_INTERVAL_MIN`。
- **回測引擎**（`crypig/backtest.py`）：對每筆非中性決策跟隨訊號方向進出，輸出
  方向命中率、平均/累積損益、損益曲線、信心度分層表現；尚未到期計為 pending。
- **真實價歷史回測**：`OHLCVPriceHistory` 從 OKX 拉 K 線、依決策時間對齊進/出
  場價，免等系統跑滿即可回測既有決策（`price_source=ohlcv`）。
- **決策持久化**（`crypig/storage/decisions.py`）：每輪決策（含當下價）落地
  sqlite，供看板與回測；含舊表 `price` 欄遷移。
- **視覺化看板**：`GET /` 自帶 HTML 看板（零前端建置）——方向標籤、分數量表、
  信心度、操作建議、理由、各訊號貢獻明細、分數 sparkline；頂部回測面板。
- 看板/API 端點：`/decisions`、`/decisions/history`、`/backtest`。

#### 變更
- **綜合決策層**（`aggregate.py`）：從單純加權分數升級為完整決策——加入信心度
  （覆蓋率 × 方向一致度 × 表態力度）、多空共識佔比、衝突偵測（訊號分歧）、
  主導訊號理由、操作建議。
- **鯨魚 Agent**：由「全市場衍生品 OI」改為**真正的鯨魚錢包持倉**——用
  bitcoin-data `wallet-bands` 追蹤 ≥100 BTC 大戶鏈上總持倉的跨輪變化（增=累積
  偏多、減=分配偏空）；非 BTC 退回 OI+資金費率以保留多資產覆蓋。
- **長期持有者（LTH）Agent**：改用真正的 `long-term-hodler-supply-btc`（≥155天）
  取代 illiquid-supply 代理，更貼近「超過 151 天即長期」。
- **requirements**：移除未用的 `ccxt`（改 httpx 直打 OKX）加快部署；`anthropic`
  標註僅 `provider=claude` 時需要。

#### 修正
- sqlite 跨執行緒：`SnapshotStore` / `DecisionStore` 連線加 `check_same_thread=False`
  （FastAPI 端點在 worker thread 執行）。
- `divergence` 觀察補帶 `price`，mock 種子加時間桶讓價格隨輪次漂移（否則回測
  報酬恆為 0）。
- 回測 `horizon_hours=0` 被當 falsy 忽略的問題。

### 2026-06-23

#### 新增
- **專案骨架**：多 agent 量化分析中台 + 自我學習 RAG 知識圖譜。
- **聰明錢 Agent**：接 Hyperliquid 真實多空持倉。
- **量價背離 Agent**：接 OKX 真實 OHLCV，RSI 背離 + 量能輔助。
- **長期持有者（LTH）Agent**：接 bitcoin-data.com 真實鏈上資料（免費源）。

#### 變更
- 全市場持倉改用 CoinGecko 跨所聚合 OI（真正的「整個市場」）。
- LTH client 增強健壯性（`/last` 404 退回 base、時序陣列取末筆、`value_key`）。
