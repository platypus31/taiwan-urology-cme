"""台灣泌尿科醫學會公告的「年度國際會議」—— 開會時間（kind=meeting）。

站主 2026-08-25：「幫我把台灣泌尿科醫學會 所有的會議全部都抓下來包括其他學術活動
但是不是積分的 **寧願多也不要漏掉開會**」。

這一條補的是盤點報告裡最大的缺口：**國際泌尿科年會**（EAU／AUA／JUA／SIU／ICS／
KUA／WCET／USANZ 這些）。它們在國外辦、不申請台灣積分，所以**永遠不會出現在
E-School 的積分登記表上**（實測 0 命中），兩條既有的線都收不到。

🔴 **公告網址每年換一個**（`…/events/86-international-meeting/<id>-<年份>-international-meeting`），
所以不能寫死，必須從「活動資訊」列表頁解析出來 —— 型態跟 `guidelines.py` 的 TUA
治療指引完全一樣，那邊踩過的坑這裡直接沿用。

🔴 **比對規則刻意很窄**：`86-international-meeting/` 這個分類底下還躺著一堆**不是**
年度國際會議清單的公告（EUREP 徵選、YLF 遴選、AURC 甄選結果、生技大會早鳥…）。
用「網址含 international」這種寬鬆規則會直接指錯，所以規則是
**slug 必須長成 `<數字>-<四位年份>-international-meeting`**，再從命中的取最新年份。

⚠️ 這一頁只有**當年度**的場次。往年的（例如 2025 那四場）只存在於學會的公開
Google 日曆，不在這支的守備範圍 —— 見盤點報告 §4.3。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup

from .base import (
    KIND_MEETING,
    Event,
    SourceError,
    clean_text,
    cutoff_iso,
    detect_online,
    detect_region,
    get,
    scrub_contacts,
    warn,
)

NAME = "台灣泌尿科醫學會 國際會議"
KIND = KIND_MEETING

BASE = "https://www.tua.org.tw"
# limit=0 是學會自己的「顯示全部」參數（guidelines.py 也用同一招），
# 一次拿完整份列表，不用翻頁。
LIST_URL = BASE + "/tua/tw/latest-news/events?limit=0"

# 只認「<數字>-<四位年份>-international-meeting」這個 slug 形狀。
# 分類資料夾同名但底下混著徵選／遴選公告，光看資料夾會抓錯（見模組 docstring）。
_SLUG = re.compile(r"/(\d+)-(\d{4})-international-meeting/?$")

# 「2/28-3/3」「10/14-10/17」「11/9-11/13」；也接受單日「5/20」。
_RANGE = re.compile(
    r"^\s*(\d{1,2})\s*/\s*(\d{1,2})\s*(?:[-–~－]\s*(\d{1,2})\s*/\s*(\d{1,2})\s*)?$"
)


def _find_page() -> Tuple[str, int]:
    """從活動資訊列表找出最新年度的國際會議公告頁，回 (網址, 年份)。"""
    soup = BeautifulSoup(get(LIST_URL).text, "html.parser")
    best: Optional[Tuple[int, str]] = None
    for anchor in soup.find_all("a", href=True):
        match = _SLUG.search(anchor["href"].split("?")[0])
        if not match:
            continue
        year = int(match.group(2))
        if best is None or year > best[0]:
            best = (year, anchor["href"])
    if best is None:
        raise SourceError("活動資訊列表找不到年度國際會議公告頁（來源可能改版）")
    url = best[1]
    if url.startswith("/"):
        url = BASE + url
    return url, best[0]


def _resolve_dates(text: str, year: int) -> Optional[Tuple[str, str]]:
    """「2/28-3/3」+ 年份 → ("2026-02-28", "2026-03-03")；解析不出來回 None。

    🔴 年份不在頁面文字裡，是從公告 slug 來的（跟 eschool 的 display_date 同理）。
    跨年的情形（12/28-1/3）用「結束月份比開始月份小 → 結束年 +1」補正。
    """
    match = _RANGE.match(text or "")
    if not match:
        return None
    start_month, start_day = int(match.group(1)), int(match.group(2))
    if match.group(3):
        end_month, end_day = int(match.group(3)), int(match.group(4))
    else:
        end_month, end_day = start_month, start_day

    end_year = year + 1 if end_month < start_month else year
    try:
        start = "{:04d}-{:02d}-{:02d}".format(year, start_month, start_day)
        end = "{:04d}-{:02d}-{:02d}".format(end_year, end_month, end_day)
        # 用 date 建構一次確認不是 2/30 這種來源打錯的日期
        from datetime import date

        date(year, start_month, start_day)
        date(end_year, end_month, end_day)
    except ValueError:
        return None
    return start, end


def _split_title(text: str) -> Tuple[str, str]:
    """「USANZ 2026／澳洲墨爾本」→ ("USANZ 2026", "澳洲墨爾本")。

    來源用全形／分隔，且斜線後常多一個空白（「EAU 2026／ 英國倫敦」）。
    分不出來就整串當標題、地點留白 —— 寧可少一個欄位，不要猜。
    """
    parts = re.split(r"[／/]", text, maxsplit=1)
    title = clean_text(parts[0])
    location = clean_text(parts[1]) if len(parts) > 1 else ""
    return title, location


def parse_table(
    html: str,
    year: int,
    page_url: str,
    keep=None,
    source_name: str = NAME,
) -> List[Event]:
    """把 TUA 公告頁的「月/日 ｜ 議程」表格解析成 Event 清單（不連網，供 selftest 用）。

    學會的年度國際會議頁與年度行事曆頁**用的是同一種表格**，所以解析共用這一支，
    差別只在 `keep`：傳一個 `(標題, 地點) -> bool` 決定哪幾列要收
    （`sources/tua_calendar.py` 用它只挑理監事會議）。
    這是本 repo 既有的做法 —— `kaohsing.py` 也是這樣重用 `eschool.parse_month(accept=…)`。
    """
    soup = BeautifulSoup(html, "html.parser")
    events: List[Event] = []
    seen = set()

    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        date_text = cells[0].get_text(" ", strip=True)
        resolved = _resolve_dates(date_text, year)
        if not resolved:
            continue  # 表頭「月/日」與任何非日期列自動被略過
        start, end = resolved

        raw_title = cells[1].get_text(" ", strip=True)
        title, location = _split_title(raw_title)
        if not title:
            continue
        if keep is not None and not keep(title, location):
            continue

        # 有外部連結就連過去（報名頁），沒有就連回學會公告頁 —— 不留空連結。
        anchor = row.find("a", href=True)
        url = anchor["href"] if anchor else page_url
        if url.startswith("/"):
            url = BASE + url

        key = (start, title)
        if key in seen:
            continue
        seen.add(key)

        # 這一頁的內容是會議名稱與城市，沒有承辦人資訊；scrub 是防禦性的，
        # 來源哪天多加一欄聯絡方式時不會直接把它登上公開網站。
        location = scrub_contacts(location)
        events.append(
            Event(
                date=start,
                end_date=end if end != start else "",
                title=title,
                location=location,
                organizer="台灣泌尿科醫學會",
                region=detect_region(location),
                online=detect_online(title, location),
                kind=KIND_MEETING,
                source=source_name,
                url=url,
            )
        )

    return events


# 舊名保留：selftest 與既有呼叫端用 parse_page
parse_page = parse_table


def fetch() -> List[Event]:
    page_url, year = _find_page()
    events = parse_table(get(page_url).text, year, page_url)
    if not events:
        raise SourceError("國際會議公告頁 {} 解析不到任何場次（版面可能改了）".format(page_url))

    cutoff = cutoff_iso(KIND_MEETING)
    kept = [e for e in events if (e.end_date or e.date) >= cutoff]
    if not kept:
        warn("{}：{} 場全部早於保留下界".format(NAME, len(events)))
    return kept
