"""排程入口。

  python scheduler.py --once    跑一輪就結束（適合測試/CI）
  python scheduler.py           常駐，依各 agent 設定間隔定時跑
"""
from __future__ import annotations

import argparse
import json
import logging

from crypig.config import get_config
from crypig.orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def run_once() -> None:
    orc = Orchestrator()
    result = orc.run_cycle()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # 示範一次關聯性問答
    demo = orc.ask("聰明錢和鯨魚現在對 BTC 的態度一致嗎？")
    print("\n=== 關聯性問答示範 ===")
    print(demo["answer"])


def run_forever() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler

    cfg = get_config()
    orc = Orchestrator()
    sched = BlockingScheduler()
    # 簡化：用分析間隔當主迴圈；各 agent 細緻間隔可再拆 job
    interval = cfg.analyzers.interval_minutes
    sched.add_job(orc.run_cycle, "interval", minutes=interval, next_run_time=None)
    logging.info("排程啟動，每 %d 分鐘跑一輪。Ctrl+C 結束。", interval)
    orc.run_cycle()   # 啟動先跑一次
    sched.start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="跑一輪就結束")
    args = parser.parse_args()
    run_once() if args.once else run_forever()
