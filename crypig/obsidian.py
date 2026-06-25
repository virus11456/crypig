"""Obsidian 知識庫匯出：把每輪資料寫成 markdown（frontmatter + [[雙向連結]]）。

目錄結構（vault/）：
  Coins/<SYMBOL>.md   每幣一頁：判斷/聰明錢淨/鯨魚淨/背離/費率/OI-Cap，連結到 KOL
  Journal/<date>.md   當日快照：大玩家決心、全市場傾向、異常、重點幣
  KOL/<name>.md       KOL 情緒頁（結構先建好，待接 LunarCrush/X 情緒源）
  Strategies/我的策略.md  範本，供你寫假設、掛回測

用途：在 Obsidian Graph View 把 訊號↔幣↔交易者↔KOL 連成個人交易知識圖，找 alpha。
"""
from __future__ import annotations

import os
from pathlib import Path

# 先放幾個常被引用的 KOL；之後接情緒源自動更新
_KOL = [
    ("Saylor", "saylor", "對 BTC 長期看多（機構積累代表）"),
    ("CZ", "cz_binance", "幣安創辦人，市場情緒指標"),
    ("Arthur_Hayes", "CryptoHayes", "宏觀/總經觀點"),
    ("PowellFed", "federalreserve", "美聯儲態度（鷹/鴿影響風險資產）"),
]


def _fm(d: dict) -> str:
    """YAML frontmatter。"""
    lines = ["---"]
    for k, v in d.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(map(str, v))}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def _dir_label(label: str) -> str:
    return label or "—"


def export_vault(data: dict, vault_dir: str) -> dict:
    """data：彙整好的匯出資料（見 build_export_data）。回寫出檔數統計。"""
    root = Path(vault_dir)
    coins_n = _write_coins(root, data)
    _write_journal(root, data)
    kol_n = _write_kols(root, data)
    _write_strategy_template(root)
    return {"coins": coins_n, "kol": kol_n, "vault": str(root)}


def _write_coins(root: Path, data: dict) -> int:
    d = root / "Coins"
    d.mkdir(parents=True, exist_ok=True)
    coins = data["coins"]
    for c in coins:
        s = c["symbol"]
        fm = _fm({
            "symbol": s, "score": c.get("score"), "label": _dir_label(c.get("label")),
            "smart_money_net": c.get("sm_net"), "whale_net": c.get("whale_net"),
            "divergence": c.get("divergence") or "neutral",
            "funding_ann": c.get("funding_ann"), "oi_cap": c.get("oi_cap"),
            "updated": data["ts"], "tags": ["crypig/coin"],
        })
        div = {"bull": "📈 底背離", "bear": "📉 頂背離"}.get(c.get("divergence"), "無")
        pct = lambda x: "—" if x is None else f"{x*100:+.0f}%"
        body = f"""# {s}

- 綜合判斷：**{_dir_label(c.get('label'))}**（score {c.get('score')}）
- 🧠 聰明錢淨多空：{pct(c.get('sm_net'))}
- 🐋 巨鯨淨多空：{pct(c.get('whale_net'))}
- 📉 日線背離：{div}
- 資金費率(年化)：{pct(c.get('funding_ann'))}
- OI/Cap：{('%.2f%%' % (c['oi_cap']*100)) if c.get('oi_cap') else '—'}

## 對照（找 alpha 的線索）
- KOL 看法：{' '.join(f'[[KOL/{k[0]}]]' for k in _KOL)}
- 若此處「聰明錢做空」但「KOL 看多」→ 留意反指標背離
- 每日快照：[[Journal/{data['date']}]]
"""
        (d / f"{s}.md").write_text(fm + "\n\n" + body, encoding="utf-8")
    return len(coins)


def _write_journal(root: Path, data: dict) -> None:
    d = root / "Journal"
    d.mkdir(parents=True, exist_ok=True)
    sm = data.get("smart_summary") or {}
    wh = data.get("whale_summary") or {}
    ov = data.get("overall") or {}
    top = data["coins"][:12]
    fm = _fm({"date": data["date"], "tags": ["crypig/journal"]})

    def conv(g):
        if not g or not g.get("total"):
            return "無資料"
        return (f"多 {g.get('long')} / 空 {g.get('short')} / 觀望 {g.get('flat')}"
                f"，表態空佔 {('%.0f%%' % (g['short_pct']*100)) if g.get('short_pct') is not None else '—'}"
                f"，槓桿中位 {g.get('lev_median')}x")

    lines = [fm, "", f"# {data['date']} 市場快照", "",
             "## 🧭 大玩家決心",
             f"- 🧠 聰明錢：{conv(sm)}",
             f"- 🐋 巨鯨：{conv(wh)}", ""]
    # 🎯 分歧雷達結論（群眾 vs 大戶背離＋收斂判讀＋alpha 候選幣）
    radar = data.get("radar") or {}
    rm = radar.get("market") or {}
    if rm:
        lines += ["## 🎯 分歧雷達結論",
                  f"- 市場判讀：**{rm.get('verdict', '—')}**",
                  f"- 群眾(恐懼貪婪 {rm.get('fear_greed', '—')}/{rm.get('fg_label', '')}) "
                  f"⟷ 聰明錢整體 {('%+.0f%%' % (rm['smart_avg']*100)) if rm.get('smart_avg') is not None else '—'}"
                  f"｜背離量 gap {('%+.2f' % rm['gap']) if rm.get('gap') is not None else '—'}"
                  f"（背離幣 {rm.get('n_div', 0)}：頂 {rm.get('n_top', 0)}／底 {rm.get('n_bottom', 0)}）"]
        if data.get("radar_conv"):
            lines.append(f"- ⏱ 時間軸：**{data['radar_conv']}**")
        rc = radar.get("coins") or []
        if rc:
            lines.append("- Alpha 候選（背離最大）：")
            for c in rc[:8]:
                lines.append(f"    - [[Coins/{c['symbol']}]] {c.get('type', '')}·{c.get('bias', '')}"
                             f"（群眾 {('%+.0f%%' % (c['crowd']*100)) if c.get('crowd') is not None else '—'}"
                             f" ⟷ 聰明錢 {('%+.0f%%' % (c['smart']*100)) if c.get('smart') is not None else '—'}"
                             f"，強度 {c.get('score')}）")
        lines.append("")
    if ov:
        lines += ["## 全市場傾向",
                  f"- 聰明錢整體淨多空：{ov.get('sm_net_pct', '—')}",
                  f"- BTC 巨鯨合約(HL 淨值前N)：{ov.get('whale_chain', '—')}", ""]
    lines += ["## 重點幣（依部位/OI）"]
    for c in top:
        div = {"bull": "底背離", "bear": "頂背離"}.get(c.get("divergence"), "")
        lines.append(f"- [[Coins/{c['symbol']}]] {_dir_label(c.get('label'))}"
                     f"（聰明錢 {('%+.0f%%' % (c['sm_net']*100)) if c.get('sm_net') is not None else '—'}"
                     f"{('，'+div) if div else ''}）")
    (d / f"{data['date']}.md").write_text("\n".join(lines), encoding="utf-8")


def _write_kols(root: Path, data: dict) -> int:
    d = root / "KOL"
    d.mkdir(parents=True, exist_ok=True)
    for name, handle, note in _KOL:
        fm = _fm({"name": name, "handle": handle,
                  "sentiment": "待接情緒源", "tags": ["crypig/kol"]})
        body = f"""# {name}（@{handle}）

> {note}

- 情緒分數：_待接 LunarCrush / X API 後自動更新_
- 近期關注：[[Coins/BTC]] [[Coins/ETH]]
- 用法：與 [[Journal/{data['date']}]] 的聰明錢方向對照，找「群眾 vs 聰明錢」分歧
"""
        (d / f"{name}.md").write_text(fm + "\n\n" + body, encoding="utf-8")
    return len(_KOL)


def _write_strategy_template(root: Path) -> None:
    d = root / "Strategies"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "我的策略範本.md"
    if f.exists():
        return
    f.write_text("""---
tags: [crypig/strategy]
status: 草稿
---
# 我的策略範本

## 假設
（例：當 [[聰明錢]] 對某幣淨空 > 50% 且出現 [[底背離]]，反轉做多）

## 進場條件
-

## 回測命中率
_系統可掛上 /backtest 結果_

## 觀察筆記
-
""", encoding="utf-8")
