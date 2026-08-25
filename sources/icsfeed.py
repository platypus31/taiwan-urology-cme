"""把 Event 清單算成 iCalendar（.ics）訂閱檔。

站主 2026-08-25：「幫我添加一個訂閱制按鈕好了 … 大家有值班不一定所有的課程
都有機會可以上 如果沒辦法就是單純的雜訊 所以讓他們選擇要不要去訂閱」。

🔴 **為什麼這支放在 sources/ 而不是 scripts/**：`scripts/` 沒有 `__init__.py`，
`scripts/selftest.py` 的 sys.path 技巧 import 不到 `scripts.*`。要讓格式邏輯
有回歸測試守著就得放在這裡（`sources.is_current` 已經踩過同一個坑）。
它是輸出格式不是資料來源，命名用 icsfeed 跟真正的 source adapter 區隔。

🔴 **UID 必須跨 build 穩定**，否則訂閱端會把同一場活動當成新事件重複跳出來 ——
這是 ics 最常見也最惱人的坑。這裡用的識別碼跟 `build.dedupe()` 判斷「兩筆是不是
同一場」用的是**同一組欄位**（kind + date + 正規化標題），所以只要管線認為是同一場，
UID 就一定一樣。刻意不放 location／url／credits 這些會被來源網站修來修去的欄位。

⚠️ 已知限制：來源把活動**日期**改掉、或把標題改到連 `base.norm_title` 都正規化不成同一個字串時，
UID 會變，訂閱端會多一筆。這是可接受的 —— 那種程度的變動本來就該當成新活動。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from .base import TAIPEI, Event, norm_title

# UID 的命名空間前綴。
#
# 🔴 **刻意不用 `<識別碼>@<網域>` 那個慣例寫法**，雖然 RFC 5545 建議 UID 長得像
# addr-spec。理由是那個形狀**跟 email 一模一樣**，`scripts/pii-scan.sh` 的信箱樣式
# 規則會整份掃到 —— 2026-08-25 首次產出 .ics 時閘門就當場擋下 49 筆 UID。
# 那不是誤報而是「形狀真的沒辦法分辨」：閘門看不出 `<sha1>@domain` 是 UID 還是信箱。
# **正確的處理是改我們自己的格式，不是把 data/*.ics 加進閘門白名單** ——
# 白名單會讓真的信箱哪天混進 .ics 也一起放行。
#
# 唯一性仍然成立：固定前綴（專案命名空間）+ sha1（內容雜湊）。
# ⚠️ 改動這個前綴等於讓所有既有訂閱者的事件全部重新產生一次，非必要不要動。
UID_PREFIX = "taiwan-urology-cme"

# 訂閱端多久回來抓一次。資料一天更新一次（Actions 台灣 06:00），
# 所以 12 小時足夠；設更短只是讓別人的日曆 App 空跑。
REFRESH_INTERVAL = "PT12H"


def _fold(line: str) -> str:
    """RFC 5545 的折行：每行最多 75 個 octet，續行開頭補一個空白。

    🔴 必須以 **octet** 計算而不是字元 —— 中文一個字是 3 個 byte，
    用字元數折出來的行會超長，嚴格一點的訂閱端會整份拒收。
    同時不能把一個多位元組字元從中間切開，所以是一個 byte 一個 byte 疊上去。
    """
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line

    chunks: List[bytes] = []
    current = b""
    limit = 75
    for char in line:
        encoded = char.encode("utf-8")
        if len(current) + len(encoded) > limit:
            chunks.append(current)
            current = encoded
            limit = 74  # 續行被佔掉一個 byte 放開頭那個空白
        else:
            current += encoded
    if current:
        chunks.append(current)
    return "\r\n ".join(chunk.decode("utf-8") for chunk in chunks)


def _escape(text: str) -> str:
    """ics 的文字跳脫：反斜線、分號、逗號要跳脫，換行寫成 \\n。

    順序很重要 —— 反斜線一定要**先**換，不然後面補進去的跳脫符號會被二次跳脫。
    """
    out = str(text or "")
    out = out.replace("\\", "\\\\")
    out = out.replace("\n", "\\n").replace("\r", "")
    out = out.replace(";", "\\;").replace(",", "\\,")
    return out


def event_uid(event: Event) -> str:
    """跨 build 穩定的 UID。

    用 `base.norm_title` 而不是自己複製一份 —— `build.dedupe()` 也用它，
    兩邊共用同一支才能保證「管線認為是同一場」與「訂閱端認為是同一場」永遠一致。
    """
    identity = "|".join([event.kind or "", event.date or "", norm_title(event.title)])
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()
    return "{}-{}".format(UID_PREFIX, digest)


def _parse_time_range(text: str) -> Optional[tuple]:
    """「09:00 ~ 17:50」→ ("090000", "175000")；格式不符回 None。

    跟前端 `assets/app.js` 的 parseTimeRange 是同一套規則。
    """
    import re

    match = re.search(r"(\d{1,2}):(\d{2})\s*[~～-]\s*(\d{1,2}):(\d{2})", str(text or ""))
    if not match:
        return None
    start = "{:02d}{}00".format(int(match.group(1)), match.group(2))
    end = "{:02d}{}00".format(int(match.group(3)), match.group(4))
    return start, end


def _compact(iso_date: str) -> str:
    return (iso_date or "").replace("-", "")


def _plus_one_day(iso_date: str) -> str:
    """整天事件的 DTEND 是**不含**的，所以要 +1 天。"""
    parsed = datetime.strptime(iso_date, "%Y-%m-%d") + timedelta(days=1)
    return parsed.strftime("%Y%m%d")


def _event_lines(event: Event, dtstamp: str) -> List[str]:
    lines = ["BEGIN:VEVENT", "UID:" + event_uid(event), "DTSTAMP:" + dtstamp]

    time_range = _parse_time_range(event.time) if not event.end_date else None
    if time_range:
        # 單日且來源有寫起訖時間 → 帶時區的實際時段
        day = _compact(event.date)
        lines.append("DTSTART;TZID=Asia/Taipei:{}T{}".format(day, time_range[0]))
        lines.append("DTEND;TZID=Asia/Taipei:{}T{}".format(day, time_range[1]))
    else:
        # 多日、或來源沒寫時間 → 整天事件（DTEND 不含，所以 +1 天）
        lines.append("DTSTART;VALUE=DATE:" + _compact(event.date))
        lines.append("DTEND;VALUE=DATE:" + _plus_one_day(event.end_date or event.date))

    lines.append("SUMMARY:" + _escape(event.title))
    if event.location:
        lines.append("LOCATION:" + _escape(event.location))
    if event.url:
        lines.append("URL:" + _escape(event.url))

    description = "\n".join(
        part
        for part in [
            "主辦：" + event.organizer if event.organizer else "",
            "積分：" + event.credits_raw if event.credits_raw else "",
            "簡章與報名：" + event.url if event.url else "",
            "" if time_range else "（時間為整天，實際起訖請看主辦單位公告）",
        ]
        if part
    )
    if description:
        lines.append("DESCRIPTION:" + _escape(description))

    lines.append("END:VEVENT")
    return lines


def render(events: Iterable[Event], calendar_name: str, dtstamp: Optional[str] = None) -> str:
    """算出一份完整的 .ics 內容（含 CRLF 結尾，符合 RFC 5545）。

    dtstamp 傳 build 的 updated_at，讓「資料沒更新時檔案內容不變」——
    每次都塞當下時間會讓 git 每天產生無意義的 diff。
    """
    if dtstamp is None:
        dtstamp = utc_stamp()

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//platypusbot//taiwan-urology-cme//ZH-TW",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + _escape(calendar_name),
        "X-WR-TIMEZONE:Asia/Taipei",
        "REFRESH-INTERVAL;VALUE=DURATION:" + REFRESH_INTERVAL,
        "X-PUBLISHED-TTL:" + REFRESH_INTERVAL,
        # 台灣沒有日光節約時間，固定 +0800，所以 VTIMEZONE 只需要一段 STANDARD。
        "BEGIN:VTIMEZONE",
        "TZID:Asia/Taipei",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        "TZOFFSETFROM:+0800",
        "TZOFFSETTO:+0800",
        "TZNAME:CST",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]

    for event in events:
        lines.extend(_event_lines(event, dtstamp))

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def utc_stamp(iso_datetime: Optional[str] = None) -> str:
    """把 build 的 updated_at（帶 +08:00）換成 ics 的 DTSTAMP 形式（UTC，結尾 Z）。

    傳 None 或格式不對就退回「現在」。DTSTAMP 規範上必須是 UTC。
    """
    try:
        parsed = datetime.fromisoformat(iso_datetime) if iso_datetime else None
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        parsed = datetime.now(TAIPEI)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TAIPEI)
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
