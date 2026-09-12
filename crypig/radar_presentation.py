"""Describe observed indicator differences without inferring trades or returns."""
import math


def describe_radar(radar):
    result = dict(radar or {})
    m = dict(result.get("market") or {})
    crowd, smart = m.get("crowd_m"), m.get("smart_avg")
    valid = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    if not valid(crowd) or not valid(smart):
        verdict = "資料不足或更新異常，暫不判定市場背離"
    elif crowd > .1 and smart < -.05:
        verdict = "情緒偏貪婪；追蹤合約樣本平均淨空，兩項指標方向相反"
    elif crowd < -.1 and smart > .05:
        verdict = "情緒偏恐懼；追蹤合約樣本平均淨多，兩項指標方向相反"
    else:
        verdict = "未達市場背離門檻；情緒與合約部位不代表現貨買賣"
    m["verdict"] = verdict
    m["crowd_dir"] = "資料不足" if not valid(crowd) else "偏貪婪" if crowd > .1 else "偏恐懼" if crowd < -.1 else "中性"
    result["market"] = m
    result["interpretation"] = "費率指標經縮放，百分比不是交易人數比例；合約指標為各幣淨多空比的等權平均。分歧不確認頂底、現貨買賣或獲利機會。"
    result["coins"] = [dict(c, type="正費率／樣本淨空" if c.get("crowd", 0) > 0 else "負費率／樣本淨多", bias="方向分歧") for c in result.get("coins", [])]
    return result


def convergence_note(history):
    tail = []
    for row in history:
        gap = row.get("gap")
        if not isinstance(gap, (int, float)) or isinstance(gap, bool) or not math.isfinite(gap):
            tail = []
        else:
            tail.append(gap)
    if len(tail) < 4:
        return None
    k = min(5, len(tail) // 2)
    recent = sum(map(abs, tail[-k:])) / k
    previous = sum(map(abs, tail[-2*k:-k])) / k
    return ("背離幅度縮小；不能單憑收斂確認價格反轉" if recent < previous - .03 else
            "背離幅度擴大；情緒與合約方向差距增加" if recent > previous + .03 else
            "背離幅度大致持平；無法據此判定進場時機")
