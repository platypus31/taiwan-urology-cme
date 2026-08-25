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
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sources import (  # noqa: E402
    eschool,
    icsfeed,
    kaohsing,
    tea,
    tua_calendar,
    tua_international,
    tua_meetings,
    tuoa,
)
from sources.base import (  # noqa: E402
    KIND_CME,
    KIND_MEETING,
    REGION_SLUGS,
    TAIPEI,
    Event,
    cutoff_iso,
    drain_warnings,
    is_current,
    norm_title,
)

# 順序無所謂（輸出會重新排序），但積分來源放前面，讀 log 時比較好對。
SOURCES = [eschool, tua_meetings, tua_international, tua_calendar, tea, tuoa, kaohsing]

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "events.json"


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
        key = (event.kind, event.date, norm_title(event.title))
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


# 每個分頁「全部」那份訂閱檔的檔名與行事曆名稱。地區檔是 `<prefix>-<slug>.ics`。
FEED_NAMES = {
    KIND_CME: ("cme", "泌尿科 積分課程"),
    KIND_MEETING: ("meeting", "泌尿科 學會會議"),
}


def _write_ics(target: Path, text: str) -> None:
    """原子寫出一份 .ics。

    newline="" 是必要的：ics 規範要求 CRLF 換行，`icsfeed.render()` 已經產好 \\r\\n，
    用預設模式寫檔會被再翻譯一次變成 \\r\\r\\n（`Path.write_text` 在 3.9 沒有
    newline 參數，所以這裡用 open）。
    """
    tmp = target.with_suffix(".ics.tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    tmp.replace(target)


def _drop_feed(target: Path) -> None:
    """刪掉這一輪沒有內容的訂閱檔。

    ⚠️ 空的不是「產一份沒有事件的行事曆」而是**不產檔並刪掉舊的**：
    零 VEVENT 的 ics 在訂閱端顯示成壞掉的行事曆而不是「這個範圍目前沒有活動」；
    而留著上一輪的舊檔更糟 —— 已經訂閱的人會永遠收到那份不再更新的資料，
    完全沒有徵兆。前端讀不到對應的 feeds 鍵時會把那個選項（或整區）藏起來。
    """
    if target.exists():
        target.unlink()
        print("已移除 {}（這次沒有活動）".format(target))


def _write_feeds(final: List[dict], updated_at: str) -> Dict[str, Dict[str, str]]:
    """產出 .ics 訂閱檔，回傳 {kind: {地區: 檔名}} 給前端用（""＝該分頁全部）。

    站主 2026-08-25 要的「訂閱制按鈕」，2026-08-26 加上地區粒度。

    🔴 **規則刻意最簡單：訂閱檔＝那個分頁的資料（可再切地區），不另外過濾。**
    所以 `cme*.ics` 只有未結束的課（events.json 裡本來就沒有過期的課），
    `meeting*.ics` 跟著會議線保留兩年份的已結束場次 —— 跟站上該分頁看到的是
    同一批資料。這樣使用者不必猜「訂閱到的跟我看到的一不一樣」。

    ⚠️ 這裡**不能**做成「只收即將舉行」：三個學會的即將舉行目前是 0，
    那樣產出的會是一份空日曆，訂閱端只會顯示成壞掉的行事曆。

    ── 為什麼是「分頁 × 地區」而不是別的切法 ──────────────────────

    🔴 **地區檔一定要留在分頁底下，不可以把兩個分頁混進同一份地區檔。**
    `dedupe()` 的 key 含 `kind`，所以同一場活動**可以同時是積分課程也是學會會議**
    （見該函式註解，兩邊各留一份是刻意的）。真的發生時，兩筆的 UID 不同
    （UID 也含 kind），混進同一份 .ics 就是同一場活動在使用者日曆上出現兩次，
    而日曆 App 不會幫忙合併。更直接的理由是：兩個分頁問的是不同問題
    （這堂課給幾點 vs 他們什麼時候開會），混一起就變成「以為只訂積分課程、
    結果混進學會會議」—— 那比沒有這個功能更糟。

    🔴 **只切「地區」這一軸，不再加第二軸。** 地區是唯一「一筆活動恰好落在一個值」
    的軸，切成檔案不會讓同一場活動出現在兩份訂閱裡；主題（categories）可複標，
    切下去同一場會同時進兩份檔。地區同時也是真正決定「去不去得成」的條件 ——
    值班的人到不了外縣市，那正是要濾掉的雜訊。

    檔案數是**有上限的常數不是組合爆炸**：只為「真的有資料的（分頁, 地區）組合」
    產檔，上限 2 分頁 × 7 地區 + 2 份全部 = 16 份。會爆炸的是「多軸組合」
    （時間 × 積分 × 主題 …），那才是這裡刻意不做的事。
    """
    stamp = icsfeed.utc_stamp(updated_at)
    data_dir = OUTPUT.parent
    feeds: Dict[str, Dict[str, str]] = {}

    for kind, (prefix, calendar_name) in FEED_NAMES.items():
        rows = [Event(**row) for row in final if row.get("kind", KIND_CME) == kind]
        per_kind: Dict[str, str] = {}

        # 該分頁「全部」那份也適用「空的不產檔」規則 —— 某一種 kind 整個抓不到
        # 並非不可能（build 的 stale 保護會保留舊資料，但舊資料也可能是空的）。
        all_target = data_dir / "{}.ics".format(prefix)
        if rows:
            _write_ics(all_target, icsfeed.render(rows, calendar_name, dtstamp=stamp))
            per_kind[""] = all_target.name  # 空字串＝沒選地區（該分頁全部）
            print("已寫入 {}（{} 筆）".format(all_target, len(rows)))
        else:
            _drop_feed(all_target)

        for region, slug in REGION_SLUGS.items():
            target = data_dir / "{}-{}.ics".format(prefix, slug)
            subset = [e for e in rows if e.region == region]
            if not subset:
                _drop_feed(target)
                continue
            name = "{}（{}）".format(calendar_name, region)
            _write_ics(target, icsfeed.render(subset, name, dtstamp=stamp))
            per_kind[region] = target.name
            print("已寫入 {}（{} 筆）".format(target, len(subset)))

        feeds[kind] = per_kind

    # 地區在資料裡但沒收進 REGION_SLUGS：不會有自己的訂閱檔（仍在該分頁「全部」
    # 那份裡），前端也不會顯示那個選項。浮出來讓人看得見，不要默默發生。
    missing = sorted(
        {row.get("region") for row in final if row.get("region")} - set(REGION_SLUGS)
    )
    if missing:
        print(
            "[warn] 這些地區沒有對應的檔名代號，不會有專屬訂閱檔：{}"
            "（請補進 sources/base.py 的 REGION_SLUGS）".format("、".join(missing)),
            file=sys.stderr,
        )
    return feeds


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
            # 判準本體在 sources/base.is_current()（放那裡才測得到 —— scripts/ 沒有
            # __init__.py，selftest import 不到 scripts.build）。邊界規則見該函式註解：
            # 活動當天仍算未結束、多日活動看結束日、日期一律是台北的日期。
            fresh = [e for e in fetched if is_current(e, cutoffs)]
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

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    # 🔴 訂閱檔先寫、events.json 後寫：`feeds`（分頁×地區 → 檔名）要進 payload 給前端，
    # 而且順序這樣排的話，前端讀到新的 feeds 時對應的 .ics 一定已經在磁碟上了。
    feeds = _write_feeds(final, updated_at)

    payload = {
        "updated_at": updated_at,
        "count": len(final),
        "counts": {KIND_CME: cme_count, KIND_MEETING: len(final) - cme_count},
        # sources 一律換成這次的：某個來源這次抓到 0 筆就該顯示 0，不要沿用上一次的數字
        "sources": per_source,
        "errors": errors,
        "feeds": feeds,
        "events": final,
    }

    _write(payload)
    print("已寫入 {}".format(OUTPUT))
    return exit_code

if __name__ == "__main__":
    raise SystemExit(main())
