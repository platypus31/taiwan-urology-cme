"""台灣泌尿內視鏡醫學會 TEA —— 開會時間（kind=meeting）。

官網 https://www.tea2024.org.tw/ （2026-08-25 查證可達，純靜態 HTML，不需瀏覽器）。

資料取自「學術活動」頁，那是一份純粹的 `<p><a href=…>日期 標題</a></p>` 清單：

    2026.07.25~26 泌尿腫瘤夏季研討會          → news/0725-26.pdf
    2026.06.27 台灣泌尿內視鏡醫學會年會        → news/20260627.jpg
    2026.04.18 台灣泌尿內視鏡醫學會            → news/20260418.html

三件事改程式前先看懂：

1. **不靠版面結構定位，靠「連結文字開頭是不是日期」**。這頁的清單沒有 id 也沒有
   專屬 class，用 `div.col-lg-7 p a` 之類的選擇器一改版就死。改用日期樣式當錨點：
   全頁掃 `<a>`，文字開頭符合 `YYYY.MM.DD` 才算一筆。導覽列與頁尾的連結不會誤中。
2. **`~` 只給「日」**（`2026.07.25~26`），不是完整的第二個日期。結束日小於開始日
   （理論上的跨月寫法）就當它沒寫，不自己推月份 —— 猜錯一個月比留白糟。
3. **地點與時間只在內頁**，而且內頁還混著講者與主持人的姓名。所以只抓
   「時間：」「地點：」「主辦單位：」這三個帶標籤的欄位，其餘一律不碰，
   抓出來的字串再過一次 scrub_contacts()（官網會把承辦人電話寫在同一段裡）。
   內頁只對 .html 抓 —— 清單裡有一半的連結直接指向簡章的 PDF 或 JPG，
   把那些下載回來丟給 HTML 解析器只會得到亂碼，還白費一次傳輸。

⚠️ 官網自己的資料有打錯的地方（例如某筆標題就寫成「2025年健康台灣 Health Taiw」，
   後面真的沒了）。那是來源的原文，不是解析壞掉，照實呈現不要「修正」。
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
    primary_organizer,
    scrub_contacts,
    warn,
)

NAME = "台灣泌尿內視鏡醫學會"
KIND = KIND_MEETING
BASE = "https://www.tea2024.org.tw/"
LIST_URL = BASE + "Academic%20activities.html"

# 「2026.07.25~26 標題」或「2026.04.18 標題」。日期與標題之間至少一個空白。
_ITEM = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})(?:\s*[~～-]\s*(\d{1,2}))?\s+(.+)$")

# 內頁的三個帶標籤欄位。全形半形冒號都要認，「地點：」後面常多一個空白。
_DETAIL_FIELDS = {
    "time": re.compile(r"時間\s*[：:]\s*(.+)"),
    "location": re.compile(r"地點\s*[：:]\s*(.+)"),
    "organizer": re.compile(r"主辦單位\s*[：:]\s*(.+)"),
}

# 內頁「時間：2026/04/18(W六) 13:00~18:00」裡的時段部分。
_TIME_RANGE = re.compile(r"(\d{1,2}:\d{2}\s*[~～-]\s*\d{1,2}:\d{2})")


def _parse_item(text: str) -> Optional[Tuple[str, str, str]]:
    """把一行「日期 標題」拆成 (開始日, 結束日, 標題)；不是活動就回 None。"""
    match = _ITEM.match(clean_text(text))
    if not match:
        return None
    year, month, day, end_day, title = match.groups()
    try:
        # 用 date 建一次確認不是 02-30 這種假日期
        start = date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None

    end = ""
    if end_day:
        try:
            candidate = date(int(year), int(month), int(end_day))
        except ValueError:
            candidate = None
        # 結束日必須真的在開始日之後；否則就是跨月寫法或打錯，一律留白不猜
        if candidate is not None and candidate.isoformat() > start:
            end = candidate.isoformat()
    return start, end, clean_text(title)


def _is_html_page(url: str) -> bool:
    """值不值得當成 HTML 內頁去抓。清單裡一半的連結是簡章 PDF／JPG。"""
    if not url or url == LIST_URL:
        return False
    path = url.split("?", 1)[0].split("#", 1)[0].lower()
    return path.endswith(".html") or path.endswith(".htm")


def _detail_fields(url: str) -> dict:
    """從活動內頁抓時間／地點／主辦單位。抓不到就回空的，不讓整筆掛掉。"""
    fields = {}
    try:
        resp = get(url)
    except SourceError:
        # 內頁掛掉只是少了地點，清單本身還是對的 —— 不值得讓整個來源失敗
        return fields
    resp.encoding = resp.apparent_encoding or "utf-8"
    text = BeautifulSoup(resp.text, "html.parser").get_text("\n")
    for key, pattern in _DETAIL_FIELDS.items():
        match = pattern.search(text)
        if not match:
            continue
        value = scrub_contacts(clean_text(match.group(1)))
        # 主辦欄常把協辦廠商接在同一行（「主辦單位：X 協辦廠商：某某公司、…」），
        # 跟 E-School 那邊同一個問題，所以用同一支函式收斂
        if key == "organizer":
            value = primary_organizer(value)
        if value:
            fields[key] = value
    if "time" in fields:
        # 「2026/04/18(W六) 13:00~18:00」→ 只留時段，日期已經有了
        matched = _TIME_RANGE.search(fields["time"])
        fields["time"] = clean_text(matched.group(1)) if matched else ""
    return fields


def fetch() -> List[Event]:
    resp = get(LIST_URL)
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    cutoff = cutoff_iso(KIND_MEETING)
    events: List[Event] = []
    parsed_any = False

    for link in soup.select("a[href]"):
        item = _parse_item(link.get_text(" "))
        if item is None:
            continue
        parsed_any = True
        start, end, title = item
        if (end or start) < cutoff:
            continue

        # 官網的相對連結混用了反斜線（news\0725-26.pdf），照著接會變成壞網址
        href = str(link.get("href", "")).replace("\\", "/")
        url = urljoin(BASE, href) if href else LIST_URL

        detail = _detail_fields(url) if _is_html_page(url) else {}
        location = detail.get("location", "")
        organizer = detail.get("organizer", "") or NAME

        events.append(
            Event(
                date=start,
                end_date=end,
                time=detail.get("time", ""),
                title=title,
                organizer=organizer,
                location=location,
                # credits 留預設的 None：官網的活動列表不寫積分，猜一個數字比留白糟。
                # 同一場若有申請泌尿科積分，會以 kind=cme 的身分從 E-School 那條線進來。
                region=detect_region(location, organizer),
                kind=KIND_MEETING,
                source=NAME,
                url=url,
                categories=detect_categories(title),
                online=detect_online(title, location),
            )
        )

    # 頁面拿得到、卻一個日期開頭的連結都認不出來 = 版型被改掉了。
    # 這種壞法最陰險：HTTP 200、解析不報錯、只是安靜地少了一個來源。
    if not parsed_any:
        warn("{}：學術活動頁找不到任何日期開頭的連結，來源可能已改版".format(NAME))
    return events
