"""台灣泌尿科醫學會 E-School 會議列表（eschool.tua.org.tw）。

這是全站唯一也是最完整的來源：任何單位（他科學會、醫院、藥廠）只要替課程
申請泌尿科繼續教育積分，就會登記在這張表上，所以「能拿泌尿科積分的課」
幾乎都在這裡，不必逐一去爬各個子學會的網站。

列表是**一頁一個月**，月份用 query string 指定：

    /conference/list?display_date=2026-08

表格每一列長這樣（欄位已經是結構化的，不用從標題猜）：

    日期/時間 | 主題(連到 /conference/4027) | 圖示 | 主辦/主持人 | 地點 | 會議積分 | 聯絡人

兩件事要特別注意，改這支程式前先看懂：

1. **日期欄只有 MM-DD，沒有年份** —— 年份來自 display_date 這個查詢參數，
   不能從頁面文字裡找。跨年月份用 _resolve_date() 補正。
2. **列表也包含年會的個別議程**（Podium／Symposium／Poster，一天可以有 50 筆），
   那些不能單獨報名、也不單獨給積分，積分欄是空的，而「主辦/主持人」欄放的是
   議程主持人的姓名。所以收錄門檻是 has_urology_credits()：積分欄有提到泌尿科才收。
   這一關同時擋掉了「把個人姓名當主辦單位列在公開網站上」的問題。
"""
from __future__ import annotations

import re
from datetime import date
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup

from .base import (
    Event,
    clean_text,
    credits_pending,
    detect_categories,
    detect_online,
    detect_region,
    get,
    has_urology_credits,
    is_tbd,
    parse_credits,
    primary_organizer,
    today_taipei,
    warn,
)

NAME = "台灣泌尿科醫學會"
BASE = "https://eschool.tua.org.tw"
LIST_URL = BASE + "/conference/list"

# 往後看幾個月（含當月）。學會的區域月會半年前就會掛上來，超過半年幾乎都是空的
# （實測 2026-12 有 6 筆、2027-01 起 0 筆），抓太遠只是多打空請求。
MONTHS_AHEAD = 8

_MD = re.compile(r"^(\d{1,2})-(\d{1,2})$")
_TIME = re.compile(r"(\d{1,2}:\d{2}\s*[~～-]\s*\d{1,2}:\d{2})")


def _month_list(count: int) -> List[Tuple[int, int]]:
    """從台灣的當月起，往後 count 個月的 (年, 月)。"""
    today = today_taipei()
    months = []
    year, month = today.year, today.month
    for _ in range(count):
        months.append((year, month))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return months


def _resolve_date(md: str, year: int, month: int) -> Optional[str]:
    """把「08-22」配上正確的年份。

    絕大多數情況直接用查詢的年份就好，但多日活動可能跨年
    （12 月的頁面出現 01-02），所以要看列出來的月份跟查詢的月份差多遠。
    """
    match = _MD.match(md.strip())
    if not match:
        return None
    row_month, day = int(match.group(1)), int(match.group(2))
    resolved = year
    if month == 12 and row_month == 1:
        resolved += 1
    elif month == 1 and row_month == 12:
        resolved -= 1
    try:
        return date(resolved, row_month, day).isoformat()
    except ValueError:
        return None


def _date_blocks(cell) -> List[Tuple[str, str]]:
    """(MM-DD, 時間) 清單。多日活動在同一格裡有多個區塊。"""
    blocks = []
    for span in cell.select("span.fs-em"):
        md = clean_text(span.get_text())
        holder = span.parent if span.parent is not None else cell
        text = clean_text(holder.get_text(" "))
        matched = _TIME.search(text)
        blocks.append((md, clean_text(matched.group(1)) if matched else ""))
    return blocks


def _title_of(link) -> str:
    """取標題文字。

    標題那顆 span 裡還塞了一顆只在小螢幕顯示的 span（裡面是「有錄影」小圖示），
    直接 get_text() 會把圖示的替代文字混進標題，所以先把巢狀 span 拆掉。
    """
    holder = link.select_one("span.text") or link
    for nested in holder.select("span"):
        nested.decompose()
    return clean_text(holder.get_text())


def _cell_text(row, selector: str) -> str:
    cell = row.select_one(selector)
    return clean_text(cell.get_text(" ")) if cell else ""


def _parse_rows(soup: BeautifulSoup, year: int, month: int) -> List[Event]:
    table = soup.select_one("table#conferenceTable")
    if table is None:
        # 表格不見了＝來源改版，這種事一定要浮出來，不能靜靜地回傳 0 筆
        warn("{}：{}-{:02d} 找不到會議表格，來源可能已改版".format(NAME, year, month))
        return []

    events: List[Event] = []
    # 空月份的頁面不是沒有 tbody，而是放一列
    # `<tr id='noData'><td colspan=8>沒有資料</td></tr>`。
    # 這是正常狀態（明年的課還沒排），不能讓它觸發下面的改版偵測。
    body_rows = [
        row
        for row in table.select("tbody tr")
        if row.get("id") != "noData" and len(row.select("td")) > 1
    ]
    for row in body_rows:
        link = row.select_one("a[href*='/conference/']")
        date_cell = row.select_one("td.col-datetime")
        if not link or not date_cell:
            continue

        blocks = _date_blocks(date_cell)
        if not blocks:
            continue
        start = _resolve_date(blocks[0][0], year, month)
        if not start:
            continue
        end = _resolve_date(blocks[-1][0], year, month) if len(blocks) > 1 else ""
        if end == start:
            end = ""

        title = _title_of(link)
        if not title:
            continue

        # 積分與聯絡人共用同一個 class，順序固定是「積分、聯絡人」。
        # 只取第一格 —— 聯絡人欄是承辦人員的姓氏與分機，公開站沒有理由轉載。
        credit_cells = row.select("td.col-char7")
        credits_raw = clean_text(credit_cells[0].get_text(" ")) if credit_cells else ""
        if not has_urology_credits(credits_raw):
            continue  # 年會議程／他科課程，不是能拿泌尿科積分的獨立場次

        organizer = primary_organizer(_cell_text(row, "td.col-division"))
        location = _cell_text(row, "td.col-site").replace("|", "：")
        if is_tbd(location):
            location = "地點待公布"

        href = link.get("href", "")
        url = href if href.startswith("http") else BASE + "/" + href.lstrip("/")

        badges = []
        for img in row.select("td.col-char3 img[title]"):
            label = clean_text(img.get("title", ""))
            if label and label not in badges:
                badges.append(label)

        events.append(
            Event(
                date=start,
                end_date=end,
                time=blocks[0][1],
                title=title,
                organizer=organizer,
                location=location,
                credits=parse_credits(credits_raw),
                credits_raw=credits_raw,
                credits_pending=credits_pending(credits_raw),
                region=detect_region(location, organizer),
                source=NAME,
                url=url,
                categories=detect_categories(title, organizer),
                online=detect_online(title, location),
                badges=badges,
            )
        )

    # 表格還在、也有列，卻一筆都解不出來 = 欄位選擇器被改版打壞了。
    # 這條比「表格整個不見」更難發現：頁面看起來正常、程式也不會出錯，
    # 只是安靜地回傳 0 筆（codex review 2026-08-25 抓到的洞）。
    #
    # 「有列但全部被門檻濾掉」是合法情況（例如某個月只有年會議程），
    # 所以門檻要用「連一列都沒通過最基本的連結／日期欄檢查」來判，不是用最終筆數。
    if body_rows and not any(
        row.select_one("a[href*='/conference/']") and row.select_one("td.col-datetime")
        for row in body_rows
    ):
        warn(
            "{}：{}-{:02d} 有 {} 列但一筆都解析不出來，欄位結構可能已改版".format(
                NAME, year, month, len(body_rows)
            )
        )
    return events


def fetch() -> List[Event]:
    events: List[Event] = []
    for year, month in _month_list(MONTHS_AHEAD):
        resp = get(LIST_URL, params={"display_date": "{}-{:02d}".format(year, month)})
        resp.encoding = resp.apparent_encoding or "utf-8"
        events.extend(
            _parse_rows(BeautifulSoup(resp.text, "html.parser"), year, month)
        )
    # 空月份是正常的（明年的課還沒排），所以**不因為某個月 0 筆就停止往後翻** ——
    # 實測 2026-12 有課、2027-01 空、之後又會陸續補上，提早收手會漏掉遠期的課。
    return events
