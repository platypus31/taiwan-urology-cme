"""台灣泌尿科醫學會年度行事曆頁 —— **只抽理監事會議**（kind=meeting）。

站主 2026-08-25：「所有的會議全部都抓下來」。理監事會議是不折不扣的會議，
而且**只存在於這一頁** —— 盤點報告實測：E-School 搜「理監事」0 命中、
學會官方 Google 日曆搜「理監事」也 0 命中。不接這一頁就永遠收不到。

🔴🔴 **這一頁不可以當一般事件來源，只准拿來抽理監事會議。**
它是每年一月發布的**計畫表**，日期會漂移。盤點報告實測 8 筆對照：

    行事曆 2025-09-20 中區季會  → E-School 實際 2025-09-27   (+7)
    行事曆 2025-10-18 北區月會  → E-School 實際 2025-10-25   (+7)
    行事曆 2025-12-27 南區月會  → E-School 實際 2025-12-13   (−14)
    行事曆 2026-06-11 蘭陽區季會 → E-School 實際 2026-06-25   (+14)

所以區域月會／季會一律**不從這裡收**（E-School 有更準的版本，而且帶連結與完整地點）。
理監事會議是唯一沒有替代來源的類別，它的日期同樣可能漂移，但「有個大概時間」
遠好過「完全不知道有這場會」—— 卡片會連回行事曆公告頁讓人自行確認。

⚠️ 附帶發現（刻意不收）：秘書處公告區有「第 24 屆第 5／第 6 次理監事會**會議紀錄**」，
那是**事後紀錄**不是行程預告，拿來當事件來源會產生日期錯亂的假活動。
"""
from __future__ import annotations

import re
from typing import List, Tuple

from bs4 import BeautifulSoup

from . import tua_international
from .base import KIND_MEETING, Event, SourceError, cutoff_iso, get, warn

NAME = "台灣泌尿科醫學會 理監事會議"
KIND = KIND_MEETING

BASE = tua_international.BASE
# limit=0 是學會自己的「顯示全部」參數（guidelines.py／tua_international 同招）。
LIST_URL = BASE + "/tua/tw/latest-news/announcement?limit=0"

# 只認「<數字>-<四位年份>-calendar」這個 slug 形狀。
# 公告區有上千則，用「網址含 calendar」會掃到別的東西。
_SLUG = re.compile(r"/(\d+)-(\d{4})-calendar/?$")

# 收錄關鍵字。理監事會議在這張表上的寫法很固定（「第24屆第6次理監事會議」），
# 但屆次數字會變，所以認「理監事」三個字就好。
KEYWORD = "理監事"


def _keep(title: str, location: str) -> bool:
    """只收理監事會議（見模組 docstring：其餘類別的日期在這一頁不可信）。

    `location` 沒有用到 —— 它是 `tua_international.parse_table(keep=…)` 共用介面
    要求的簽名 `(標題, 地點) -> bool`。這裡刻意只看標題：判準是「是不是理監事會議」，
    跟在哪裡開無關。留著參數是為了介面一致，不是還沒寫完。
    """
    return KEYWORD in (title or "")


def _find_pages(min_year: int) -> List[Tuple[str, int]]:
    """找出**保留窗內**的年度行事曆公告頁，回 [(網址, 年份), …]。

    不是「全部都要」也不是「只取最新一份」：
    ・只取最新一份 → 會漏掉去年下半年那幾場理監事會議（會議線保留 730 天）
    ・全部都要     → 學會每年多一份公告，請求數逐年無界成長，而且每多抓一份
                     舊頁面就多一個「那一頁掛掉」的機會（見 fetch 的例外隔離）
    所以用保留下界反推最小年份：`min_year = 下界那一年`。
    """
    soup = BeautifulSoup(get(LIST_URL).text, "html.parser")
    found = {}
    for anchor in soup.find_all("a", href=True):
        match = _SLUG.search(anchor["href"].split("?")[0])
        if not match:
            continue
        year = int(match.group(2))
        if year < min_year:
            continue  # 整份都早於保留下界，抓了也會被濾掉
        url = anchor["href"]
        if url.startswith("/"):
            url = BASE + url
        found[year] = url
    if not found:
        raise SourceError(
            "公告列表找不到 {} 年以後的年度行事曆頁（來源可能改版）".format(min_year)
        )
    return [(url, year) for year, url in sorted(found.items())]


def fetch() -> List[Event]:
    cutoff = cutoff_iso(KIND_MEETING)
    events: List[Event] = []
    pages = _find_pages(int(cutoff[:4]))
    failed = 0

    for page_url, year in pages:
        # 🔴 **逐頁隔離例外**：這支要抓好幾份年度公告，若讓其中一份掛掉直接往上拋，
        # build.py 的單源 try/except 會把**整個來源**判成 0 筆 ——
        # 連本來抓得到的今年理監事會議也一起沒了。舊年份頁面被下架或改網址
        # 是遲早的事，不該拖垮還好好的那幾份。
        try:
            html = get(page_url).text
        except Exception as exc:  # noqa: BLE001 - 單頁失敗不中斷其餘年份
            failed += 1
            warn("{}：{} 年行事曆頁抓取失敗（{}），其餘年份照常".format(NAME, year, exc))
            continue
        # 表格結構跟年度國際會議頁一模一樣，共用同一支解析器，只換 keep 條件。
        events.extend(
            tua_international.parse_table(
                html, year, page_url, keep=_keep, source_name=NAME
            )
        )

    if not events:
        raise SourceError(
            "{} 份年度行事曆頁裡一場理監事會議都找不到（{} 份抓取失敗；版面或寫法可能改了）".format(
                len(pages), failed
            )
        )

    kept = [e for e in events if (e.end_date or e.date) >= cutoff]
    if not kept:
        warn("{}：{} 場理監事會議全部早於保留下界".format(NAME, len(events)))
    return kept
