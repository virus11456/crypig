#!/usr/bin/env bash
# Crypig /data 每日備份：一致性快照 + 壓縮 + 輪替 + 空間守門員。
#
#   - 一致性：用 sqlite 線上備份 API（不會抓到寫一半的壞檔），json 直接複製
#   - 防爆 ①輪替：只留最近 $KEEP 份，舊的自動刪（總量 = KEEP × 單份，不會無限長）
#   - 防爆 ②壓縮：tar + gzip（sqlite 壓縮率很高）
#   - 防爆 ③守門員：剩餘空間 < $MIN_FREE_MB 就跳過不寫（先清舊檔救空間）再離開
#
# 安裝（VPS 上）：
#   chmod +x /root/crypig/backup_data.sh
#   ( crontab -l 2>/dev/null; echo "10 4 * * * /root/crypig/backup_data.sh" ) | crontab -
# 還原：tar -xzf crypig-data-YYYYmmdd-HHMMSS.tar.gz -C /某處 後，把檔案放回 volume。
set -euo pipefail

VOLUME="${CRYPIG_VOLUME:-crypig-data}"     # docker named volume
DEST="${CRYPIG_BACKUP_DIR:-/root/crypig-backups}"
KEEP="${CRYPIG_BACKUP_KEEP:-7}"            # 保留份數
MIN_FREE_MB="${CRYPIG_BACKUP_MIN_FREE_MB:-500}"  # 剩餘空間下限(MB)

mkdir -p "$DEST"
log() { echo "$(date -Is) $*" >> "$DEST/backup.log"; }

# 防爆 ③：空間不足就不寫（並先把舊檔清到只剩 KEEP 份，盡量救空間）
free_mb=$(df --output=avail -m "$DEST" | tail -1 | tr -d ' ')
if [ "$free_mb" -lt "$MIN_FREE_MB" ]; then
  ls -1t "$DEST"/crypig-data-*.tar.gz 2>/dev/null | tail -n +$((KEEP+1)) | xargs -r rm -f
  log "ABORT 剩餘僅 ${free_mb}MB (< ${MIN_FREE_MB}MB)，跳過本次備份"
  exit 1
fi

stamp=$(date +%Y%m%d-%H%M%S)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# 一致性快照：在拋棄式容器內掛 volume，用 sqlite 線上備份 API 抓每個 .db，json 直接複製
docker run --rm -v "$VOLUME":/data -v "$tmp":/out python:3.11-slim \
  python -c "
import sqlite3, glob, shutil, os
for f in glob.glob('/data/*.db'):
    dst = sqlite3.connect('/out/' + os.path.basename(f))
    src = sqlite3.connect(f)
    src.backup(dst); dst.close(); src.close()
for f in glob.glob('/data/*.json'):
    shutil.copy2(f, '/out/')
"

tar -czf "$DEST/crypig-data-$stamp.tar.gz" -C "$tmp" .

# 防爆 ①：輪替，只留最近 KEEP 份
ls -1t "$DEST"/crypig-data-*.tar.gz | tail -n +$((KEEP+1)) | xargs -r rm -f

size=$(du -h "$DEST/crypig-data-$stamp.tar.gz" | cut -f1)
log "OK $stamp 大小 $size，備份前剩 ${free_mb}MB，現存 $(ls -1 "$DEST"/crypig-data-*.tar.gz | wc -l) 份"
