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

## 三、（選用）上 HTTPS + 網域（含 www）
用 Caddy 自動簽憑證，最省事。DNS 把根網域與 `www` 都用 A 紀錄指到 VPS IP，
然後寫 `/etc/caddy/Caddyfile`（用 shell 變數組出 `www`，避免貼上時被改成連結）：

```bash
D=你的網域.com
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
${D}, www.${D} {
    reverse_proxy 127.0.0.1:8000
}
EOF
sudo systemctl reload caddy
```

一個站台區塊同時服務根網域與 `www`，兩者自動取得 Let's Encrypt 憑證。驗證：
```bash
curl -sS -o /dev/null -w "root %{http_code}\n" https://你的網域.com
curl -sS -o /dev/null -w "www  %{http_code}\n" https://www.你的網域.com   # 皆應 200
```

## 四、（建議）關閉對外 IP:8000，只走網域
預設 `docker-compose.yml` 已把埠綁成 `127.0.0.1:8000:8000`——外面連不到 `IP:8000`，
只有同主機的 Caddy 能轉發進來（走網域＋HTTPS），掃描器/搜尋引擎也找不到。
> 注意：**Docker 發佈埠會自己寫 iptables 繞過 ufw**，用 `ufw deny 8000` 擋不住；
> 唯一可靠做法就是讓 Docker 只綁 `127.0.0.1`（已預設）。想直連對外才改回 `8000:8000`。

驗證：
```bash
curl -sS -o /dev/null -w "domain %{http_code}\n" https://你的網域.com          # 200
curl -sS --max-time 8 http://<VPS_IP>:8000 || echo "ip:8000 已封閉 ✅"          # 連不上
curl -sS -o /dev/null -w "local %{http_code}\n" http://127.0.0.1:8000          # 200
```

## 五、（建議）每日 /data 備份
`backup_data.sh`：sqlite 線上備份(一致性快照)＋gzip＋只留最近 7 份＋空間守門員
（剩餘 < 500MB 就跳過並先清舊檔），總量被鎖在「7 × 單份」不會把硬碟弄爆。
```bash
cd ~/crypig && git pull
chmod +x backup_data.sh
./backup_data.sh                          # 先手動跑一次
ls -lh ~/crypig-backups/ ; cat ~/crypig-backups/backup.log
( crontab -l 2>/dev/null | grep -v backup_data.sh; \
  echo "10 4 * * * $HOME/crypig/backup_data.sh" ) | crontab -   # 每天 04:10
```
可調：`CRYPIG_BACKUP_KEEP`(留幾份)、`CRYPIG_BACKUP_MIN_FREE_MB`(空間下限)。
還原：解開某個 `crypig-data-*.tar.gz`，把 `.db`/`.json` 放回 `crypig-data` volume。

## 六、（選用）Obsidian Vault 自動同步（Obsidian Git）
讓 Obsidian 自己更新，零手動：**VPS 每輪把 vault 推到私有 Git repo → 桌機 Obsidian Git 外掛自動 pull**。

1) GitHub 開一個 **Private** repo（與程式碼分開，例 `你/crypig-vault`）。
2) VPS 端用 SSH deploy key 讓它能 push：
```bash
ssh-keygen -t ed25519 -f ~/.ssh/crypig_vault -N "" -C crypig-vault
cat ~/.ssh/crypig_vault.pub      # 貼到 repo → Settings → Deploy keys（勾 Allow write access）
cat >> ~/.ssh/config <<'EOF'
Host github-vault
  HostName github.com
  User git
  IdentityFile ~/.ssh/crypig_vault
EOF
git clone git@github-vault:你/crypig-vault.git ~/crypig-vault
```
3) 掛同步 cron（`sync_vault.sh` 抓本機 `/vault.zip` → 疊加覆蓋進 repo→ 有變動才 commit+push，
   保留過去日期的 Journal）：
```bash
cd ~/crypig && git pull && chmod +x sync_vault.sh
CRYPIG_VAULT_REPO=$HOME/crypig-vault ./sync_vault.sh      # 先手動驗證
( crontab -l 2>/dev/null | grep -v sync_vault.sh; \
  echo "*/20 * * * * CRYPIG_VAULT_REPO=$HOME/crypig-vault $HOME/crypig/sync_vault.sh >> $HOME/crypig-vault.log 2>&1" ) | crontab -
```
4) 桌機 Obsidian：把該私有 repo `git clone` 到本機 → **Open folder as vault** →
   裝社群外掛 **Obsidian Git** → 設 **Auto pull interval = 20**、**Pull on startup = 開**。
   之後 Obsidian 每 20 分鐘自己 pull，Coins 更新、Journal 逐日累積。

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
