"""台灣泌尿腫瘤醫學會 TUOA —— 開會時間（kind=meeting）。

官網 https://tuoa.org.tw/ （2026-08-25 查證可達，純靜態 HTML，不需瀏覽器）。
資料取自「活動訊息」頁 info.php，每一筆是一張卡片：

    <div class="item"><a href="info_detail.php?p=14">
      <div class="ta-info-data">
        <strong class="year">2026</strong>
        <p class="text">台灣泌尿腫瘤醫學會半年會暨學術研討會</p>
        <span>2026/08/01(Sat)</span>
      </div></a></div>

🔴 **日期欄有四種寫法**，實際抓到的全部列在下面，改 _parse_dates() 前先看懂：

    2026/08/01(Sat)                   單日
    2026/01/31-2026/02/01(Sat.Sun)    跨月，兩個完整日期
    2025/02/22.23(SAT.SUN)            同月兩天，第二天只寫「日」
    2023-10-14                        破折號、沒有星期

處理方式是「先把整串裡的**完整日期**全部找出來」：找到兩個就是起訖，找到一個
就再看它後面緊接著是不是 `.DD`（同月的第二天）。不要用「切分隔符」的寫法 ——
`2023-10-14` 的破折號跟跨月寫法的破折號長得一模一樣，切下去會得到 2023 與 10-14。

地點與報名連結只在內頁（info_detail.php），而且內頁頁尾有秘書的姓名、信箱與電話，
所以只抓「Venue:」那一個帶標籤的欄位，抓出來的字串再過一次 scrub_contacts()。
每一筆都會去抓內頁（只有五筆，成本可以忽略）。
"""
from __future__ import annotations

import re
from datetime import date
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import (
    KIND_MEETING,
    Event,
    SourceError,
    clean_text,
    cutoff_iso,
    detect_categories,
    detect_online,
    detect_region,
    get,
    scrub_contacts,
    warn,
)

NAME = "台灣泌尿腫瘤醫學會"
KIND = KIND_MEETING
BASE = "https://tuoa.org.tw/"
LIST_URL = BASE + "info.php"

_FULL_DATE = re.compile(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})")
# 第一個完整日期後面緊接的「.DD」＝同月的第二天（2025/02/22.23）。
# 一定要用 \A 綁在剩餘字串的開頭，否則 (SAT.SUN) 裡的點也會被當成日期。
_SAME_MONTH_SECOND_DAY = re.compile(r"\A\s*[.·]\s*(\d{1,2})")

# 內頁的地點欄。官網混用中英標籤（Venue: / 地點：），兩種都認。
_VENUE = re.compile(r"(?:Venue|地點)\s*[：:]\s*(.+)")


def _to_iso(year: int, month: int, day: int) -> Optional[str]:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _parse_dates(text: str) -> Optional[Tuple[str, str]]:
    """把日期欄原文拆成 (開始日, 結束日)；結束日沒寫就是空字串。"""
    cleaned = clean_text(text)
    matches = list(_FULL_DATE.finditer(cleaned))
    if not matches:
        return None

    first = matches[0]
    start = _to_iso(*(int(g) for g in first.groups()))
    if start is None:
        return None

    end = ""
    if len(matches) > 1:
        candidate = _to_iso(*(int(g) for g in matches[1].groups()))
        if candidate and candidate > start:
            end = candidate
    else:
        tail = _SAME_MONTH_SECOND_DAY.match(cleaned[first.end():])
        if tail:
            candidate = _to_iso(int(first.group(1)), int(first.group(2)), int(tail.group(1)))
            if candidate and candidate > start:
                end = candidate
    return start, end


def _venue(url: str) -> str:
    """從活動內頁抓地點。抓不到就留空，不編一個出來。"""
    try:
        resp = get(url)
    except SourceError:
        return ""
    resp.encoding = resp.apparent_encoding or "utf-8"
    text = BeautifulSoup(resp.text, "html.parser").get_text("\n")
    match = _VENUE.search(text)
    if not match:
        return ""
    return scrub_contacts(clean_text(match.group(1)))


def fetch() -> List[Event]:
    resp = get(LIST_URL)
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    items = soup.select("div.ta-info-content div.item a[href]")
    if not items:
        # 容器還在但沒有卡片，或整個容器被改名 —— 兩種都是改版，必須浮出來
        warn("{}：活動訊息頁找不到任何活動卡片，來源可能已改版".format(NAME))
        return []

    cutoff = cutoff_iso(KIND_MEETING)
    events: List[Event] = []
    parsed_any = False

    for link in items:
        data = link.select_one("div.ta-info-data") or link
        title_node = data.select_one("p.text")
        date_node = data.select_one("span")
        if title_node is None or date_node is None:
            continue

        parsed = _parse_dates(date_node.get_text(" "))
        title = clean_text(title_node.get_text(" "))
        if parsed is None or not title:
            continue
        parsed_any = True
        start, end = parsed
        if (end or start) < cutoff:
            continue

        url = urljoin(BASE, str(link.get("href", "")).replace("\\", "/"))
        location = _venue(url)

        events.append(
            Event(
                date=start,
                end_date=end,
                title=title,
                organizer=NAME,
                location=location,
                # credits 留預設的 None —— 官網不寫積分（見 README）
                region=detect_region(location, NAME),
                kind=KIND_MEETING,
                source=NAME,
                url=url,
                categories=detect_categories(title),
                online=detect_online(title, location),
            )
        )

    if not parsed_any:
        warn("{}：活動卡片解析不出日期或標題，來源可能已改版".format(NAME))
    return events
