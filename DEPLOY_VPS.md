# 搬到 VPS（自架 Docker）

Railway 的**共享雲端 IP 被 Hyperliquid 限流**，候選池 300 會把速率額度燒在抓成交、
導致聰明錢持倉抓取被 429 擋掉（聰明錢顯示 0）。**VPS 有專屬 IP，不被限流**，可開回
`CRYPIG_POOL=300`、聰明錢實得約 48，整體也更穩。

## 一、開一台 VPS
任一家都可（1 vCPU / 1GB RAM 起跳即可，建議 2GB）：
DigitalOcean、Vultr、Hetzner、Linode… 選 Ubuntu 22.04/24.04。記下 **公網 IP**。

## 二、一鍵部署
SSH 進 VPS 後：

```bash
curl -fsSL https://raw.githubusercontent.com/virus11456/crypig/claude/brave-ptolemy-nn1nd8/deploy_vps.sh | bash
```

腳本會：裝 Docker → 拉程式 → 建立 `.env` → 建置啟動。
**首次**會建立 `.env`，編輯填金鑰（可全空）後再跑一次：

```bash
cd ~/crypig
nano .env                 # 填 COINGECKO_API_KEY 等（都可留空）
docker compose up -d --build
```

看板：`http://<VPS_IP>:8000` ，約 2–3 分鐘暖機後資料填滿。

## 三、（選用）上 HTTPS + 網域
用 Caddy 自動簽憑證，最省事。裝好 Caddy 後 `/etc/caddy/Caddyfile`：

```
你的網域.com {
    reverse_proxy 127.0.0.1:8000
}
```

`sudo systemctl reload caddy` 即可。

## 常用指令
```bash
docker compose logs -f crypig     # 看日誌
docker compose restart crypig     # 重啟
docker compose pull && docker compose up -d --build   # 更新到最新程式
docker compose down               # 停止（資料保留在 volume）
```

## 環境變數（docker-compose.yml 已設好預設）
| 變數 | 預設 | 說明 |
|---|---|---|
| `CRYPIG_POOL` | 300 | 聰明錢候選池（VPS 專屬 IP 可開 300→實得約 48） |
| `CRYPIG_INTERVAL_MIN` | 20 | 背景每幾分鐘跑一輪 |
| `CRYPIG_DATA_DIR` | /data | sqlite/知識圖譜落地（已掛 volume 持久化） |
| `USE_MOCK` | false | 真實資料源 |
| 金鑰 | （.env） | CoinGecko / Reddit / LunarCrush / Anthropic，皆可留空 |
