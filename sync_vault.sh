#!/usr/bin/env bash
# 把當下的 Obsidian Vault 推進私有 Git repo，給 Obsidian Git 外掛自動 pull。
#
# 流程：抓本機 /vault.zip → 解壓 → 疊加覆蓋進 $REPO(不刪舊檔，保留歷史 Journal)
#       → 有變動才 commit+push。掛 cron 後 Obsidian 端自動更新，零手動。
#
# 一次性設定(VPS 上)：
#   1) 在 GitHub 開一個「私有」repo，例：virus11456/crypig-vault
#   2) git clone git@github.com:virus11456/crypig-vault.git /root/crypig-vault
#      (用 SSH deploy key，或 https + PAT；push 要能通)
#   3) chmod +x /root/crypig/sync_vault.sh
#      ( crontab -l 2>/dev/null | grep -v sync_vault.sh; \
#        echo "*/20 * * * * /root/crypig/sync_vault.sh >> /root/crypig-vault.log 2>&1" ) | crontab -
set -euo pipefail

REPO="${CRYPIG_VAULT_REPO:-/root/crypig-vault}"
URL="${CRYPIG_VAULT_URL:-http://127.0.0.1:8000/vault.zip}"

if [ ! -d "$REPO/.git" ]; then
  echo "$(date -Is) ERROR: $REPO 不是 git repo，先 clone 你的私有 vault repo 到這" >&2
  exit 1
fi

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
curl -fsS --max-time 90 "$URL" -o "$tmp/v.zip"
python3 -m zipfile -e "$tmp/v.zip" "$tmp/x"           # → $tmp/x/CrypigVault/...

# 疊加覆蓋：更新 Coins/今日 Journal，保留 repo 內過去日期與你自己的筆記
cp -a "$tmp/x/CrypigVault/." "$REPO/"

cd "$REPO"
git add -A
if git diff --cached --quiet; then
  echo "$(date -Is) no change"
  exit 0
fi
git -c user.name=crypig-bot -c user.email=bot@hypeboss.cc \
    commit -q -m "vault sync $(date -Is)"
for i in 1 2 3; do
  git push -q origin HEAD && { echo "$(date -Is) pushed"; exit 0; }
  sleep $((2**i))
done
echo "$(date -Is) ERROR: push 失敗(檢查 remote 認證)" >&2
exit 1
