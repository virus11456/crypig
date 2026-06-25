#!/usr/bin/env bash
# 在 VPS 上一鍵部署 Crypig（Ubuntu/Debian）。用法：
#   curl -fsSL <raw>/deploy_vps.sh | bash      或   bash deploy_vps.sh
set -euo pipefail

REPO="${CRYPIG_REPO:-https://github.com/virus11456/crypig.git}"
BRANCH="${CRYPIG_BRANCH:-claude/brave-ptolemy-nn1nd8}"
DIR="${CRYPIG_DIR:-$HOME/crypig}"

echo "==> 1/4 安裝 Docker（若尚未安裝）"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || { echo "需要 docker compose v2"; exit 1; }

echo "==> 2/4 取得程式碼到 $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch origin "$BRANCH" && git -C "$DIR" checkout "$BRANCH" && git -C "$DIR" pull origin "$BRANCH"
else
  git clone -b "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR"

echo "==> 3/4 準備 .env（首次會從範本建立，請填金鑰後重跑）"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "   已建立 .env —— 編輯它填入金鑰（可全空），再執行：cd $DIR && docker compose up -d --build"
fi

echo "==> 4/4 建置並啟動"
docker compose up -d --build
echo
echo "完成！看板：http://<你的VPS_IP>:8000"
echo "資料約 2-3 分鐘暖機後填滿（聰明錢 pool 300 ≈ 48）。"
echo "看日誌：docker compose logs -f crypig"
