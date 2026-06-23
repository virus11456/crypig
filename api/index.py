"""Vercel serverless 入口。

Vercel 的檔案系統唯讀（僅 /tmp 可寫）且無常駐程序，故：
  - 關閉背景排程（CRYPIG_SCHEDULER=0），改由端點在空表時惰性跑一輪
  - sqlite / 知識圖譜寫到 /tmp
Vercel 的 @vercel/python 會偵測此檔匯出的 ASGI `app`。
"""
import os
import sys

# 預設環境（部署面板的 env 可覆寫）
os.environ.setdefault("CRYPIG_SCHEDULER", "0")     # serverless 無常駐，關排程
os.environ.setdefault("CRYPIG_DATA_DIR", "/tmp/crypig")
os.environ.setdefault("USE_MOCK", "true")          # 公開 demo 用 mock，免外部限流

# 讓 `import crypig` 找得到（repo 根目錄＝本檔的上兩層）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crypig.dashboard.api import app   # noqa: E402  (Vercel 取用此 ASGI app)
