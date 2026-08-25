"""台灣泌尿科醫學會自己的年會／半年會（kind=meeting）。

站主 2026-08-25：「可以幫我把泌尿科醫學會的開會也額外加到開會那一邊嗎」。
它是這個站的主場學會，會議清單裡缺它很怪。

🔴 **為什麼不能從 E-School 的會議列表撈（那是最直覺但錯的作法）**：
年會在 `conference/list` 上是**攤成 88 筆個別議程**的（2026 年會 8/22 有 53 筆、
8/23 有 35 筆），每一筆是 Podium／Symposium／Workshop 這種**議程層級**的東西 ——
不能單獨報名、積分欄是空的，而且「主辦／主持人」欄放的是**座長的姓名**。
現行的積分門檻 `has_urology_credits()` 正是靠積分欄空白把這 88 筆擋掉的，
那一關同時擋著「把個人姓名登在公開網站上」。**放寬它等於同時拆掉 PII 防線。**

✅ **正確的會議層級來源是 E-School 首頁列出的「議程總表」頁**：

    https://eschool.tua.org.tw/p/2026_conference      2026 TUA Annual Meeting
    https://eschool.tua.org.tw/p/2026mid_conference   2026 TUA Mid-year Meeting
    https://eschool.tua.org.tw/p/2025_conference      2025 TUA x UAA Annual Meeting
    …

這些頁面本身就是「一場會議」：有名稱、有起訖日、有地點。而且**首頁直接把它們全部列出來**
（`<a href=".../p/…_conference">`），所以不需要去猜網址、也不需要一頁頁翻議程 ——
一個請求就知道有哪些會議層級的頁面存在。

頁面結構（2026-08-25 實測五個年度都一致）：
  ・標題列  `2026 TUA Annual Meeting Scientific Programs`（2025 那年寫 `Program` 單數）
  ・多日活動每天一段 `時間: 2026/08/22 (星期六) 09:00 - 17:30 地點: 台北南港展覽館2館 7F`
    → 取最早的日期當開始、最晚的當結束
  ・⚠️ 少數頁面沒有「時間:」那一段（實測 `2025mid_conference` 就沒有）→ 那頁跳過，
    不硬湊一個日期出來。

🔴 **只抓「時間」「地點」這兩個帶標籤的欄位，不碰議程表格** —— 表格裡全是講者與座長的姓名。
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
    clean_text,
    cutoff_iso,
    detect_categories,
    detect_online,
    detect_region,
    get,
    scrub_contacts,
    today_taipei,
    warn,
)

# 🔴 這裡的 NAME 必須跟 sources/eschool.py 的不一樣。
# build.py 的 per_source 是用 NAME 當 key，兩支來源同名會互相覆蓋 ——
# 帳面上只剩一個來源，而且 kind 會是後跑的那支的，前端「幾個來源」就跟著算錯。
NAME = "台灣泌尿科醫學會 年會／半年會"
KIND = KIND_MEETING
ORGANIZER = "台灣泌尿科醫學會"

BASE = "https://eschool.tua.org.tw/"
HOME_URL = BASE

# 首頁上的議程總表連結。slug 形如 `2026_conference` / `2026mid_conference`。
_PAGE_HREF = re.compile(r"/p/((\d{4})[a-z]*)_conference/?$")

# 「2026 TUA Annual Meeting Scientific Programs」／「… Scientific Program」（2025 是單數）
_HEADING = re.compile(r"^(\d{4}\s+TUA\s+.{2,60}?)\s+Scientific\s+Programs?$")

# 「時間: 2026/08/22 (星期六) 09:00 - 17:30」。星期的寫法中英文都有（星期六／Sat）。
_DAY = re.compile(
    r"時間\s*[:：]\s*(\d{4})/(\d{1,2})/(\d{1,2})\s*(?:\([^)]{0,12}\))?\s*"
    r"(\d{1,2}:\d{2}\s*[-~～]\s*\d{1,2}:\d{2})?"
)
# 「地點: 台北南港展覽館2館 7F last update: 07.19 TIME 701 A …」
#
# 🔴 **這條一定要「有界」而且抓不到就放棄**，不能寫成 `(.+?)` 到處找結束標記。
# 地點後面緊接著就是整張議程表格，而**表格裡全是講者與座長的姓名** ——
# 邊界沒命中的話會把整張表（連同幾百個人名、頁尾的電話傳真）當成「地點」寫進 events.json。
# 這不是假想：2026-08-25 第一版就是這樣，2025 那年的頁面用的是「時間 & 會場」而不是
# 「last update」，邊界沒中，一筆活動的地點欄長達數千字並夾帶人名。
#
# 所以改成：非貪婪 + **長度上限** + 邊界 lookahead。三者同時成立才算數 ——
# 超過上限還沒遇到邊界就是「我不認得這頁的版型」，回傳空字串留白，不吐半截句子。
_VENUE_MAX = 80
_VENUE = re.compile(
    r"地點\s*[:：]\s*(.{1,%d}?)(?=\s+last\s+update|\s+TIME\s|\s*時間\s*[&:：]|$)" % _VENUE_MAX
)

# 往回看幾年。會議保留兩年份（見 base.MEETING_KEEP_PAST_DAYS），
# 用 slug 的年份先粗篩，省下抓那些一定會被日期下界濾掉的舊頁面。
YEARS_BACK = 2


def _page_links(soup: BeautifulSoup) -> List[Tuple[str, int]]:
    """首頁上的議程總表頁 (網址, slug 年份)，去重後保持出現順序。"""
    found: List[Tuple[str, int]] = []
    seen = set()
    for link in soup.select("a[href]"):
        href = str(link.get("href", ""))
        matched = _PAGE_HREF.search(href)
        if not matched:
            continue
        url = urljoin(BASE, href)
        if url in seen:
            continue
        seen.add(url)
        found.append((url, int(matched.group(2))))
    return found


def _parse_page(url: str) -> Optional[Event]:
    """把一個議程總表頁解析成一筆會議；沒有日期就回 None（不硬湊）。"""
    resp = get(url)
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    text = clean_text(soup.get_text(" "))

    days = []
    first_time = ""
    for matched in _DAY.finditer(text):
        try:
            days.append(date(*(int(g) for g in matched.groups()[:3])))
        except ValueError:
            continue
        if not first_time and matched.group(4):
            first_time = clean_text(matched.group(4))
    if not days:
        return None

    title = ""
    for node in soup.select("h1, h2, h3, h4, strong, b, p, div, span"):
        candidate = _HEADING.match(clean_text(node.get_text(" ")))
        if candidate:
            title = candidate.group(1)
            break
    if not title:
        return None

    venue = _VENUE.search(text)
    location = scrub_contacts(clean_text(venue.group(1))) if venue else ""

    start, end = min(days), max(days)
    return Event(
        date=start.isoformat(),
        end_date=end.isoformat() if end > start else "",
        time=first_time,
        title=title,
        organizer=ORGANIZER,
        location=location,
        # credits 留預設的 None：年會的積分是逐場議程各自認定的，
        # 掛一個數字在整場會議上會是錯的。
        region=detect_region(location, ORGANIZER),
        kind=KIND_MEETING,
        source=NAME,
        url=url,
        categories=detect_categories(title),
        online=detect_online(title, location),
    )


def fetch() -> List[Event]:
    resp = get(HOME_URL)
    resp.encoding = resp.apparent_encoding or "utf-8"
    pages = _page_links(BeautifulSoup(resp.text, "html.parser"))
    if not pages:
        # 首頁拿得到卻一個總表連結都沒有＝改版。這是這支唯一的入口，
        # 不喊的話整條來源會安靜地變成 0 筆。
        warn("{}：E-School 首頁找不到任何議程總表連結，來源可能已改版".format(NAME))
        return []

    cutoff = cutoff_iso(KIND_MEETING)
    oldest_year = today_taipei().year - YEARS_BACK
    events: List[Event] = []
    for url, year in pages:
        if year < oldest_year:
            continue  # 一定會被日期下界濾掉，不值得為它多打一個請求
        event = _parse_page(url)
        if event is None:
            continue  # 那頁沒寫日期（實測 2025mid 就沒有），跳過不硬湊
        if (event.end_date or event.date) < cutoff:
            continue
        events.append(event)

    if pages and not events:
        # 有總表頁、卻一場都解不出來 = 版型被改掉了。
        # 「全部超出保留期間」不會走到這裡：粗篩已經把太舊的排除，
        # 剩下的年度理當至少有一場落在兩年內。
        warn("{}：找到 {} 個議程總表頁但一場都解析不出來，版型可能已改".format(NAME, len(pages)))
    return events
