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

from sources import eschool, kaohsing, tea, tuoa  # noqa: E402
from sources.base import (  # noqa: E402
    KIND_CME,
    KIND_MEETING,
    TAIPEI,
    Event,
    cutoff_iso,
    drain_warnings,
)

# 順序無所謂（輸出會重新排序），但積分來源放前面，讀 log 時比較好對。
SOURCES = [eschool, tea, tuoa, kaohsing]

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
    """同一天 + 標題實質相同 = 同一場。保留欄位比較齊的那筆。

    🔴 kind 是 key 的一部分，所以「同一場活動同時是積分課程也是學會會議」時
    **兩邊都會留一份**，這是刻意的：兩個分頁問的是不同問題（這堂課給幾點 vs
    他們什麼時候開會），任一邊少掉那筆，該分頁就是不完整的。
    合併成一筆再讓前端兩邊顯示看似更省，但那要求 Event 帶一個 kind 陣列，
    篩選與計數全部要跟著變成集合運算 —— 為了省幾 KB JSON 不值得。
    """
    best: Dict[tuple, Event] = {}
    for event in events:
        key = (event.kind, event.date, _norm_title(event.title))
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


def _flag_stale(
    errors: List[str], fresh_meetings: List[dict], per_source: Dict[str, dict]
) -> bool:
    """積分課程抓不到東西時的降級寫入：留住舊的課，但**這次抓到的會議照樣寫進去**。

    🔴 不能整份檔案原封不動地跳過寫入（本函式原本的作法）。積分課程與學會會議是
    兩條互相獨立的來源，主來源掛掉不代表 TEA／TUOA／高杏 也掛了 —— 那樣做會讓
    會議那一頁跟著默默停止更新，而且告警文字只講積分課程，畫面上完全看不出來。
    「資料默默停止更新、畫面上看不出來」正是這整段防線要擋的事，換一頁發生而已。

    回傳有沒有成功寫出去（既有檔不存在或壞掉、或裡面連一筆舊的積分課程都沒有，
    就沒有東西可以留，這次不寫檔）。
    """
    try:
        existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(existing, dict) or not isinstance(existing.get("events"), list):
        return False

    old_cme = [
        e
        for e in existing["events"]
        if isinstance(e, dict) and e.get("kind", KIND_CME) == KIND_CME
    ]
    if not old_cme:
        return False

    merged = sorted(
        old_cme + list(fresh_meetings),
        key=lambda e: (e.get("date", ""), e.get("title", "")),
    )
    stale_since = existing.get("updated_at", "未知時間")
    notice = "本次更新沒有抓到任何積分課程，積分課程顯示的是 {} 的舊資料".format(stale_since)
    if fresh_meetings:
        notice += "（學會會議已照常更新）"

    existing["events"] = merged
    existing["count"] = len(merged)
    existing["counts"] = {
        KIND_CME: len(old_cme),
        KIND_MEETING: len(merged) - len(old_cme),
    }
    # sources 換成這次的：某個來源這次抓到 0 筆就該顯示 0，不要沿用上一次的數字
    existing["sources"] = per_source
    # updated_at 刻意不動 —— 那個欄位的意思是「資料有多新」，而檔案裡最舊的那部分
    # （積分課程）就是停在這個時間。把它改成現在只會讓過期資料看起來是剛更新的。
    existing["errors"] = [notice] + list(errors)
    _write(existing)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只印統計，不寫檔")
    args = parser.parse_args()

    # 台灣的今天（見 sources/base.py 的 TAIPEI 註解 —— runner 跑在 UTC，不能用機器日期）
    # 兩種 kind 的保留下界不同：積分課程過期就丟，學會會議保留兩年份
    # （見 sources/base.py 的 MEETING_KEEP_PAST_DAYS）。
    cutoffs = {KIND_CME: cutoff_iso(KIND_CME), KIND_MEETING: cutoff_iso(KIND_MEETING)}

    collected: List[Event] = []
    errors: List[str] = []
    per_source: Dict[str, Dict[str, object]] = {}

    for module in SOURCES:
        name = getattr(module, "NAME", module.__name__)
        # 來源模組自己宣告它產出哪一種（沒宣告就是積分課程，維持舊行為）。
        # 前端要靠這張表算「這個分頁有幾個來源」，不能從 events 反推 ——
        # 來源掛掉或當期沒活動時它就消失了，那正是最該讓人看到它還在的時候。
        kind = getattr(module, "KIND", KIND_CME)
        try:
            fetched = module.fetch()
        except Exception as exc:  # noqa: BLE001 - 單源失敗不中斷全體
            errors.append("{}：{}".format(name, exc))
            per_source[name] = {"kind": kind, "count": 0}
            print("[FAIL] {} — {}".format(name, exc), file=sys.stderr)
            fetched = None
        else:
            # 多日活動看結束日：跨越今天的兩天課還在進行中，不該當成過期
            fresh = [
                e
                for e in fetched
                if (e.end_date or e.date) >= cutoffs.get(e.kind, cutoffs[KIND_CME])
            ]
            collected.extend(fresh)
            per_source[name] = {"kind": kind, "count": len(fresh)}
            print("[ok] {} — {} 筆（原始 {}）".format(name, len(fresh), len(fetched)))

        # 抓到了但不完整（例如來源改版）也要浮出來，不能只有整個掛掉才報。
        # 🔴 成功與失敗兩條路都要 drain：來源可能先發了幾個 warning 才拋例外，
        # 只在成功分支 drain 的話那些訊息會卡在緩衝區裡消失
        # （若它剛好是最後一個來源，就永遠沒人看得到）。
        for message in drain_warnings():
            errors.append(message)
            print("[warn] {}".format(message), file=sys.stderr)

    events = dedupe(collected)
    cme_events = [e for e in events if e.kind == KIND_CME]

    payload = {
        "updated_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "count": len(events),
        "counts": {
            KIND_CME: len(cme_events),
            KIND_MEETING: len(events) - len(cme_events),
        },
        "sources": per_source,
        "errors": errors,
        "events": [e.to_dict() for e in events],
    }

    print(
        "合計 {} 筆（積分課程 {} ／學會會議 {}；去重前 {}），來源 {} 個，錯誤 {} 個".format(
            len(events),
            len(cme_events),
            len(events) - len(cme_events),
            len(collected),
            len(per_source),
            len(errors),
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
    #
    # 🔴 只看**積分課程**的筆數，不看總數。會議來源的筆數天生就少（一年一到兩場），
    # 把它們算進來會讓這道防線變鬆：三個會議來源合計 5 筆就足以掩蓋
    # 「主來源整個掛掉、積分課程 0 筆」這個最該被抓到的情況。
    # 會議來源自己壞掉走的是另一條路 —— 每支解析器在「頁面拿得到卻解不出東西」時
    # 會發 warning，那些 warning 會進 errors 顯示在站上。
    exit_code = 1 if not cme_events else 0

    if args.dry_run:
        return exit_code

    # 全部來源都掛掉時保留既有 events.json 的**活動**—— 寧可資料舊，也不要把網站洗成 0 筆。
    #
    # 但錯誤訊息要換成這次的：否則「來源改版 → 解析出 0 筆 → 只發 warning」這種情況，
    # 舊檔原封不動、網站看起來一切正常，警訊只留在 CI 的 stderr 裡沒人看
    # （Codex review 2026-08-25 抓到的洞）。這正是這個站最該避免的失敗形態：
    # 資料默默停止更新，而畫面上完全看不出來。
    if exit_code == 1:
        print("本次抓取沒有任何積分課程，保留既有的課並寫入這次的會議資料", file=sys.stderr)
        fresh_meetings = [e.to_dict() for e in events if e.kind == KIND_MEETING]
        if not _flag_stale(errors, fresh_meetings, per_source):
            print("既有 {} 不存在或無法解析，這次不寫檔".format(OUTPUT), file=sys.stderr)
        return exit_code

    _write(payload)
    print("已寫入 {}".format(OUTPUT))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
