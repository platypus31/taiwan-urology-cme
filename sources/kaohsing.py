"""高雄市高杏泌尿照護協會 —— 開會時間（kind=meeting）。

🔴 **這個協會沒有查得到的官方網站**（2026-08-25 查證：搜尋引擎、台灣泌尿科醫學會
的「相關網站」清單、Facebook 專頁全都找不到；它是高雄在地的協會，不是全國性學會）。
所以這裡不編一個網址出來，改用它**實際留下公開紀錄的地方** ——
台灣泌尿科醫學會 E-School 的會議列表：任何場次只要它掛名主辦或協辦，
就會出現在那張表的「主辦單位／協辦單位」欄裡。

實測到的兩筆長這樣（原文，2026-08-25 掃 2025-01～2026-08 各月列表）：

    2025-11-22  2025 TUA南區月會暨高杏泌尿論壇
                主辦單位：高雄醫學大學附設高醫岡山醫院泌尿科、奇美醫院泌尿科、高杏泌尿照護協會
    2026-06-06  TAASM 115年度第十二屆第1次會員大會暨第57次學術演講會
                主辦單位：台灣男性學暨性醫學醫學會、…  協辦單位：高雄市高杏泌尿照護協會

所以收錄門檻是「主辦／協辦欄裡有『高杏』」，而不是積分 —— 這是本站
「會議」與「積分課程」兩條線的差別：那邊問「這堂課給幾點」，這邊問「他們什麼時候開會」。

⚠️ 因此本來源的涵蓋度**受限於對方有沒有替該場次申請積分**（沒申請就不會登在
E-School 上）。這是已知缺口，不是 bug；等哪天協會有了自己的公告管道再換來源。
"""
from __future__ import annotations

from typing import List

from . import eschool
from .base import KIND_MEETING, Event, cutoff_iso

# 🔴 這是**顯示用的來源名**，刻意掛在「台灣泌尿科醫學會」底下當子項目，
# 不是與 TEA／TUOA 並列的第四個學會（站主 2026-08-25 指定：
# 「高杏泌尿照護協會應該是歸在台灣泌尿科醫學會下面的子項目」）。
#
# 為什麼這樣寫是誠實的而不是硬掰：高杏沒有自己的發布管道，它的場次就是登在
# TUA 的 E-School 列表上（站主原話「高杏泌尿照護協會就是在台灣泌尿科協會發文」），
# 所以這一條抓到的本來就是「TUA 列表裡跟高杏有關的場次」。真正的主辦單位不會被
# 這個名字蓋掉 —— 卡片上另外標「高杏主辦／高杏協辦」（見 role_badge()）。
#
# 命名沿用同一個父層下已有的寫法「台灣泌尿科醫學會 年會／半年會」
# （sources/tua_meetings.py）。
#
# 🔴 **講清楚這個「子項目」是怎麼成立的，免得後人以為有分組機制**：
# 程式裡**沒有任何父子／分組邏輯** —— 沒有 parent 欄位，前端也沒有前綴比對
# （`assets/app.js` 的來源軸就是 `Object.keys(...).sort()` 平鋪成一排 chip）。
# 「掛在 TUA 底下」完全是**靠命名前綴 + 字典序自然相鄰**達成的視覺效果：
# 學會會議分頁的來源排序是
#   台灣泌尿內視鏡醫學會 → 台灣泌尿科醫學會 年會／半年會 → 台灣泌尿科醫學會 高杏場次 → 台灣泌尿腫瘤醫學會
# 兩條 TUA 線相鄰（實測，非推論）。這是刻意選的最小改動：站主要的是
# 「不要並列成第四個學會」，不是要一個分組元件。
# ⚠️ 注意是**兩條**不是三條：積分課程那條「台灣泌尿科醫學會」kind=cme，
#    在另一個分頁，永遠不會跟這兩條出現在同一個篩選器裡。
# 若哪天真的需要層級 UI，那是新需求，要另外做 parent 欄位，不要靠改名硬撐。
# ⚠️ **不可以直接取成跟其他來源一樣的名字**：build.py 的 per_source 用 NAME 當 key，
#    同名會互相覆蓋（帳面只剩一個、kind 還會變成後跑那支的）。父子關係走命名前綴，
#    不走「共用同一個 NAME」。
NAME = "台灣泌尿科醫學會 高杏場次"
KIND = KIND_MEETING

# 協會名稱在來源網站上有兩種寫法（「高杏泌尿照護協會」與「高雄市高杏泌尿照護協會」），
# 而且未來很可能再冒出第三種。用「高杏」兩個字當錨點，比對整串會漏。
# 這兩個字在泌尿科的公開活動資料裡不會有別的意思（實測 20 個月份的列表，
# 唯二命中的就是上面那兩筆），所以不會誤收。
KEYWORD = "高杏"

# 往前掃幾個月。它一年只辦一到兩場，只看未來的話這個分頁幾乎永遠是空的；
# 掃 12 個月才看得出「上一場什麼時候開的」。往後 8 個月與積分來源一致。
#
# ⚠️ **這個數字比 base.MEETING_KEEP_PAST_DAYS（730 天≈24 個月）短，是刻意的**。
# 另外兩個來源的歷史是一次請求就整份拿到，這裡卻是**一個月一個請求**：掃到 24 個月
# 等於每天多打 12 個請求到別人的網站，只為了一個一年辦一兩場的地方協會。
# 代價是這個來源查不到 12～24 個月前的場次 —— README 有標，不要以為是漏抓。
MONTHS_BACK = 12
MONTHS_AHEAD = 8


def _accept(credits_raw: str, division_raw: str) -> bool:
    return KEYWORD in (division_raw or "")


def role_badge(organizer: str) -> str:
    """這場是它主辦還是協辦。

    判法看似取巧其實是精確的：Event.organizer 是 primary_organizer() 的產物，
    而那支函式**只留主辦、切掉協辦之後的所有內容**。所以「高杏」出現在 organizer 裡
    就代表它掛在主辦欄，沒出現就代表它在被切掉的協辦欄裡（能進到這裡的每一筆，
    _accept 都已經確認整格有「高杏」）。

    為什麼要標：卡片上的「主辦」欄刻意只顯示主辦單位（協辦多半是藥廠，列出來會
    洗版），所以協辦的場次若不標一句，使用者會看不懂它為什麼被歸在這個協會底下。
    """
    return KEYWORD + ("主辦" if KEYWORD in (organizer or "") else "協辦")


def fetch() -> List[Event]:
    cutoff = cutoff_iso(KIND_MEETING)
    events: List[Event] = []
    for year, month in eschool.month_range(MONTHS_BACK, MONTHS_AHEAD):
        rows = eschool.parse_month(
            eschool.month_soup(year, month),
            year,
            month,
            accept=_accept,
            source_name=NAME,
            kind=KIND_MEETING,
        )
        for event in rows:
            # 這裡要自己過濾，不能等 build.py —— 往前掃 12 個月一定會撈到
            # 比保留下界更舊的場次（見 base.MEETING_KEEP_PAST_DAYS 的註解）。
            if (event.end_date or event.date) < cutoff:
                continue
            event.badges = event.badges + [role_badge(event.organizer)]
            events.append(event)
    return events
