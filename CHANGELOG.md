# 更新日誌

本檔記錄 Crypig 的重要變更。日期格式 YYYY-MM-DD。

## [Unreleased]

### 2026-06-24（中台擴充：全市場掃描 / 大戶持倉 / 情緒 / Obsidian）

#### 新增
- **兩頁式中台**：📊 市場看板 / 🧠 策略·Obsidian，頂部 nav 切換。
- **大玩家決心**：聰明錢(獲利前N)/鯨魚(帳戶淨值前N)各幣淨多空、**20 分鐘變化
  delta**、多空人數/比例/槓桿摘要面板（看決心）。
- **全市場 230 幣輕量評分**：用整批 HL 資料（聰明錢持倉+資金費率擁擠+日線背離）
  幫所有幣算判斷/分數/信心，零額外 API。
- **全幣日線量價背離**（底/頂，並發抓 HL 日線）；**整輪優化 39s→13s**（並發化）。
- **鏈上 BTC 鯨魚每日持倉折線圖**（bitcoin-data 歷史，≥100BTC 大戶）。
- **宏觀/資金**：全市場 OI-Cap、Vol-Cap、各幣市值（CoinGecko Demo 金鑰）；
  **DefiLlama** 資金動向（TVL/穩定幣/各鏈）。
- **情緒層（取代推特）**：恐懼貪婪指數（alternative.me，免費）、**Reddit 散戶
  討論熱度/情緒**（官方唯讀 OAuth）、LunarCrush（需付費）整合預留。
- **幣別總表**：合併決策+宏觀+持倉+背離+費率為單一可排序/可搜尋全市場表。
- **資金費率異常**（過熱/偏擁擠/空方擁擠）+ Hyperliquid 全市場費率掃描。
- **Obsidian 知識庫匯出** `/vault.zip`：Coins/Journal/KOL/Strategies markdown
  （frontmatter + 雙向連結），在 Graph View 連成個人交易知識圖找 alpha。

#### 變更
- 卡片式詳情移除（全市場總表已涵蓋）；費率合併單欄（採完整的 HL 場內）。
- 所有外部源改背景每輪抓一次並快取，請求端只讀（CoinGecko 從每次刷新→20分鐘
  3 支，符合免費額度、避免雲端 IP 被封）。

#### 修正
- CoinGecko 雲端 IP 限流：背景快取 + Demo 金鑰（`x-cg-demo-api-key`）；失敗沿用快取。
- Hyperliquid 並發抓取調節（16→8）避免一次抓太多。

### 2026-06-24（基礎：決策層 / 看板 / 回測 / 部署）

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
