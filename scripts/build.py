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

from sources import eschool, kaohsing, tea, tua_meetings, tuoa  # noqa: E402
from sources.base import (  # noqa: E402
    KIND_CME,
    KIND_MEETING,
    TAIPEI,
    Event,
    cutoff_iso,
    drain_warnings,
)

# 順序無所謂（輸出會重新排序），但積分來源放前面，讀 log 時比較好對。
SOURCES = [eschool, tua_meetings, tea, tuoa, kaohsing]

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


def _previous() -> dict:
    """上一次寫出去的 events.json。讀不到或壞掉就回空 dict。"""
    try:
        existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(existing, dict) or not isinstance(existing.get("events"), list):
        return {}
    return existing


def _kept_from_previous(previous: dict, kind: str) -> List[dict]:
    """舊檔裡屬於某一種 kind 的活動。"""
    return [
        event
        for event in previous.get("events", [])
        if isinstance(event, dict) and event.get("kind", KIND_CME) == kind
    ]


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
    fresh = {
        kind: [e.to_dict() for e in events if e.kind == kind]
        for kind in (KIND_CME, KIND_MEETING)
    }

    print(
        "合計 {} 筆（積分課程 {} ／學會會議 {}；去重前 {}），來源 {} 個，錯誤 {} 個".format(
            len(events),
            len(fresh[KIND_CME]),
            len(fresh[KIND_MEETING]),
            len(collected),
            len(per_source),
            len(errors),
        )
    )

    # 「某一種 kind 這次抓到 0 筆」就是那條線失敗了，不管來源有沒有丟例外。
    #
    # 不能寫成「有 errors 且沒 events 才算失敗」：來源改版時很可能一個例外都沒有
    # （HTTP 200、HTML 解析成功、只是選擇器對不上），errors 是空的、events 也是空的，
    # 那種寫法會判定成功並用 0 筆覆蓋掉正常的舊資料 —— 正是最該防的失敗形態。
    # 代價是「學會真的一場都沒排」會被當成故障，但積分課程有半年份的月會排程、
    # 會議留兩年份歷史，兩邊都不會真的歸零；就算發生，保留舊資料加一條告警
    # 也比把網站清空安全。
    #
    # 🔴 **兩種 kind 各判各的，不看合計**（codex review 2026-08-25 第 2 輪抓到）。
    # 看合計會讓兩邊互相掩護：會議來源合計 5 筆就足以蓋掉「主來源整個掛掉、
    # 積分課程 0 筆」；反過來 31 筆課也會蓋掉「三個會議來源全滅」。
    # 那正是這整段防線要擋的事 —— 資料默默清空，畫面上看不出來 —— 只是換一頁重演。
    stale_kinds = [kind for kind in (KIND_CME, KIND_MEETING) if not fresh[kind]]
    exit_code = 1 if stale_kinds else 0

    # dry-run 也要套同一套判斷，否則拿它當健康檢查會永遠得到成功碼。
    if args.dry_run:
        return exit_code

    previous = _previous() if stale_kinds else {}
    final: List[dict] = []
    kept_counts: Dict[str, int] = {}
    for kind in (KIND_CME, KIND_MEETING):
        if kind not in stale_kinds:
            final.extend(fresh[kind])
            continue
        # 這一種這次沒抓到 —— 沿用舊檔裡的，寧可資料舊也不要把那一頁洗成 0 筆。
        # 另一種照樣用這次的新資料，兩條線互不牽連。
        kept = _kept_from_previous(previous, kind)
        kept_counts[kind] = len(kept)
        final.extend(kept)

    if not final:
        print("這次與既有檔案都沒有任何活動，不寫檔（不要把網站洗成 0 筆）", file=sys.stderr)
        return exit_code

    final.sort(key=lambda e: (e.get("date", ""), e.get("title", "")))
    cme_count = len([e for e in final if e.get("kind", KIND_CME) == KIND_CME])

    if stale_kinds:
        labels = {KIND_CME: "積分課程", KIND_MEETING: "學會會議"}
        stale_since = previous.get("updated_at", "未知時間")
        # 先照迭代順序組好再一次插到最前面。逐條 insert(0, …) 會把順序反過來，
        # 兩種都掛掉時 errors[0] 反而變成後處理的那一種（codex review 2026-08-25 第 3 輪）。
        messages = []
        for kind in stale_kinds:
            if kept_counts.get(kind):
                messages.append(
                    "本次沒有抓到任何{}，{}顯示的是 {} 的舊資料".format(
                        labels[kind], labels[kind], stale_since
                    )
                )
            else:
                messages.append("本次沒有抓到任何{}，而且沒有舊資料可以沿用".format(labels[kind]))
            print("[stale] {}".format(messages[-1]), file=sys.stderr)
        errors[:0] = messages

    # updated_at 的意思是「資料有多新」，所以只要有任何一種沿用了舊資料就不能往前推
    # —— 推了只會讓過期資料看起來是剛更新的。哪一部分是舊的寫在 errors 裡。
    now = datetime.now(TAIPEI).isoformat(timespec="seconds")
    updated_at = previous.get("updated_at") or now if stale_kinds else now

    payload = {
        "updated_at": updated_at,
        "count": len(final),
        "counts": {KIND_CME: cme_count, KIND_MEETING: len(final) - cme_count},
        # sources 一律換成這次的：某個來源這次抓到 0 筆就該顯示 0，不要沿用上一次的數字
        "sources": per_source,
        "errors": errors,
        "events": final,
    }

    _write(payload)
    print("已寫入 {}".format(OUTPUT))
    return exit_code

if __name__ == "__main__":
    raise SystemExit(main())
