#!/usr/bin/env python3
"""跑所有來源 → 合併去重 → 寫出 data/events.json。

要加新來源：在 sources/ 底下寫一支有 fetch() 與 NAME 的模組，
然後把它加進下面的 SOURCES 清單。其他什麼都不用改。

單一來源掛掉不會讓整包失敗 —— 會記在輸出 JSON 的 errors 欄位裡，
前端會把它顯示出來，這樣來源網站改版時看得見，而不是資料默默變少。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sources import eschool  # noqa: E402
from sources.base import TAIPEI, Event, cutoff_iso, drain_warnings  # noqa: E402

SOURCES = [eschool]

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "events.json"


def _norm_title(title: str) -> str:
    """去掉積分/時數註記與所有空白標點，用來判斷兩筆是不是同一場活動。"""
    text = re.sub(r"[(（][^)）]*[)）]", "", title)
    text = re.sub(r"[【\[][^】\]]*[】\]]", "", text)  # 【線上】這類前綴標記不算差異
    return re.sub(r"[\s\-—－_、,，.。:：;；]", "", text).lower()


def _completeness(event: Event) -> int:
    score = 0
    for value in (event.location, event.organizer, event.url, event.time):
        if value:
            score += 1
    if event.credits is not None:
        score += 1
    if event.region != "其他":
        score += 1
    return score


def dedupe(events: List[Event]) -> List[Event]:
    """同一天 + 標題實質相同 = 同一場。保留欄位比較齊的那筆。"""
    best: Dict[tuple, Event] = {}
    for event in events:
        key = (event.date, _norm_title(event.title))
        current = best.get(key)
        if current is None or _completeness(event) > _completeness(current):
            best[key] = event
    return sorted(best.values(), key=lambda e: (e.date, e.title))


def _write(payload: dict) -> None:
    """原子寫入：中途失敗不會留下半截 JSON。"""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(OUTPUT)


def _flag_stale(errors: List[str]) -> bool:
    """把「這次沒抓到東西」寫進既有檔案的 errors 欄，活動資料原封不動保留。

    回傳有沒有成功寫出去（既有檔不存在或壞掉就沒得寫）。
    """
    try:
        existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(existing, dict) or not existing.get("events"):
        return False

    stale_since = existing.get("updated_at", "未知時間")
    notice = "本次更新沒有抓到任何活動，以下顯示的是 {} 的舊資料".format(stale_since)
    # updated_at 刻意不動 —— 那個欄位的意思是「資料有多新」，
    # 把它改成現在只會讓過期資料看起來是剛更新的。
    existing["errors"] = [notice] + list(errors)
    _write(existing)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只印統計，不寫檔")
    args = parser.parse_args()

    # 台灣的今天（見 sources/base.py 的 TAIPEI 註解 —— runner 跑在 UTC，不能用機器日期）
    cutoff = cutoff_iso()

    collected: List[Event] = []
    errors: List[str] = []
    per_source: Dict[str, int] = {}

    for module in SOURCES:
        name = getattr(module, "NAME", module.__name__)
        try:
            fetched = module.fetch()
        except Exception as exc:  # noqa: BLE001 - 單源失敗不中斷全體
            errors.append("{}：{}".format(name, exc))
            per_source[name] = 0
            print("[FAIL] {} — {}".format(name, exc), file=sys.stderr)
            fetched = None
        else:
            # 多日活動看結束日：跨越今天的兩天課還在進行中，不該當成過期
            fresh = [e for e in fetched if (e.end_date or e.date) >= cutoff]
            collected.extend(fresh)
            per_source[name] = len(fresh)
            print("[ok] {} — {} 筆（原始 {}）".format(name, len(fresh), len(fetched)))

        # 抓到了但不完整（例如來源改版）也要浮出來，不能只有整個掛掉才報。
        # 🔴 成功與失敗兩條路都要 drain：來源可能先發了幾個 warning 才拋例外，
        # 只在成功分支 drain 的話那些訊息會卡在緩衝區裡消失
        # （若它剛好是最後一個來源，就永遠沒人看得到）。
        for message in drain_warnings():
            errors.append(message)
            print("[warn] {}".format(message), file=sys.stderr)

    events = dedupe(collected)

    payload = {
        "updated_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "count": len(events),
        "sources": per_source,
        "errors": errors,
        "events": [e.to_dict() for e in events],
    }

    print(
        "合計 {} 筆（去重前 {}），來源 {} 個，錯誤 {} 個".format(
            len(events), len(collected), len(per_source), len(errors)
        )
    )

    # 一筆都沒有就是失敗，不管來源有沒有丟錯誤。
    #
    # 不能寫成「有 errors 且沒 events 才算失敗」：來源改版時很可能一個例外都沒有
    # （HTTP 200、HTML 解析成功、只是選擇器對不上），errors 是空的、events 也是空的，
    # 那種寫法會判定成功並用 0 筆覆蓋掉正常的舊資料 —— 正是最該防的失敗形態。
    # 代價是「學會真的一場課都沒排」會被當成故障，但那在半年份的月會排程下不會發生，
    # 而且就算發生，保留舊資料加一條告警也比把網站清空安全。
    # dry-run 也要套同一套判斷，否則拿它當健康檢查會永遠得到成功碼。
    exit_code = 1 if not events else 0

    if args.dry_run:
        return exit_code

    # 全部來源都掛掉時保留既有 events.json 的**活動**—— 寧可資料舊，也不要把網站洗成 0 筆。
    #
    # 但錯誤訊息要換成這次的：否則「來源改版 → 解析出 0 筆 → 只發 warning」這種情況，
    # 舊檔原封不動、網站看起來一切正常，警訊只留在 CI 的 stderr 裡沒人看
    # （Codex review 2026-08-25 抓到的洞）。這正是這個站最該避免的失敗形態：
    # 資料默默停止更新，而畫面上完全看不出來。
    if exit_code == 1:
        print("本次抓取沒有任何活動，保留既有活動資料並更新告警", file=sys.stderr)
        if not _flag_stale(errors):
            print("既有 {} 不存在或無法解析，這次不寫檔".format(OUTPUT), file=sys.stderr)
        return exit_code

    _write(payload)
    print("已寫入 {}".format(OUTPUT))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
