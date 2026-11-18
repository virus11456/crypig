# Crypig 量化交易分析中台 —— VPS 自架用映像
FROM python:3.11-slim

WORKDIR /app

# 先裝相依（利用 layer 快取）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再複製程式
COPY . .

# 預設值（可被 docker-compose / -e 覆寫）
ENV USE_MOCK=false \
    CRYPIG_DATA_DIR=/data \
    CRYPIG_POOL=300 \
    CRYPIG_INTERVAL_MIN=20 \
    CRYPIG_SCHEDULER=1 \
    PORT=8000

# sqlite/知識圖譜落在掛載 volume 以持久化
RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8000

# 健康檢查走靜態「/」(秒回)，不打會觸發整輪的端點
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/',timeout=8); sys.exit(0)" || exit 1

CMD ["sh", "-c", "uvicorn crypig.dashboard.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
