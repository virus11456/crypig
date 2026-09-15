"""Calendar-based LTH supply observations, not executed purchases or sales."""
from datetime import datetime, timezone, timedelta
from .btc_cohorts import normalize

SLUG = "long-term-hodler-supply-btc"

def build_lth(rows, today=None):
    today = today or datetime.now(timezone.utc).date()
    values = normalize(rows, "longTermHodlerSupplyBtc")
    values = {d:v for d,v in values.items() if d <= today.isoformat()}
    if not values:
        raise ValueError("No valid LTH daily supply")
    latest = max(values)
    day = datetime.fromisoformat(latest).date()
    changes = {str(n): values[latest]-values[target] if target in values else None
               for n in (1,7,30)
               for target in [(day-timedelta(days=n)).isoformat()]}
    return {"as_of":latest, "balance_btc":values[latest], "changes_btc":changes,
            "history":[{"date":d,"btc":values[d]} for d in sorted(values)],
            "source":"https://bitcoin-data.com/v1/"+SLUG,
            "note":"按來源 LTH 幣齡分類。供給增加可能來自幣齡成熟，減少可能來自舊幣移動；兩者均不直接代表成交買賣。"}
