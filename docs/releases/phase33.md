# 第三十三批：Vercel 前端與 Hostinger 後端分離

2026-09-17。基準版本 127f292e7e1c05bcc8d15287c8f89733c9d6b02d。保留既有同系列網站導覽與持倉回放更新。

正式架構：GitHub virus11456/crypig 保存同一版本；Vercel hypeboss 專案提供 hypeboss.cc／www 前端；Hostinger VPS1542946（72.60.110.37）提供 api.hypeboss.cc 後端、資料收集、排程與 SQLite。Vercel 將非靜態路由透過 HTTPS 轉送到獨立 API 網域，避免正式網域轉到 Vercel 後出現自我轉送。前端仍以同源路徑呼叫，不需放寬 CORS。

VPS 保留原資料卷，僅更新 crypig 服務。Caddy 僅將 api.hypeboss.cc 加入原 Crypig 主機區塊，其他主機設定保持原樣；驗證設定後 reload。先驗證 API TLS 與接口，再發布 Vercel 代理更新，最後改主網域 DNS。GitHub、Vercel 與 VPS 必須核對到相同提交與實際接口，不能只靠發布狀態宣稱同步。

基準完整測試：47 項前端、96 項 Python 通過。新增匯出路由測試驗證靜態首頁、HTTPS 後端、帶查詢參數路由與防止主網域代理迴圈。VPS 預檢9個接口200及vault.zip可讀，實際歷史288筆。正式切換與最終版本驗證另記 outputs 本批上線紀錄。

回復資料與映像：/root/crypig-preopt-phase33-20260917，crypig:rollback-20260917-phase33；Caddyfile 亦另備份。原 DNS @ 與 www 為 A 72.60.110.37、TTL300。需要回復時先讓前端代理有可用後端，再依記錄還原對應設定，不得停止其他服務。
