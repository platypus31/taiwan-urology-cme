#!/usr/bin/env python3
"""不連網的解析自我測試。

存在的理由：這個站唯一會壞的地方就是「解析規則」—— 來源改版、或有人改了
正則表達式卻沒發現舊寫法被打壞。整包資料每天自動更新，壞掉的樣子是
「資料看起來正常，只是少了幾筆或積分抓錯」，沒有測試根本看不出來。

所以這裡把踩過的坑都固定成案例（每一條後面都寫了它在防什麼）。
CI 會跑它，本機改完程式也請跑一次：

    python3 scripts/selftest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup

from sources import eschool, kaohsing, tea, tua_meetings, tuoa
from sources.base import (
    KIND_CME,
    KIND_MEETING,
    Event,
    credits_pending,
    drain_warnings,
    detect_categories,
    detect_online,
    detect_region,
    has_urology_credits,
    parse_credits,
    parse_date,
    primary_organizer,
    scrub_contacts,
)

FAILURES = []


def check(name: str, got, want) -> None:
    if got != want:
        FAILURES.append("{}：得到 {!r}，預期 {!r}".format(name, got, want))


# --------------------------------------------------------------------------
# 積分：全部取自來源「會議積分」欄的真實寫法
# --------------------------------------------------------------------------
check("積分-括號", parse_credits("泌尿科(3.5點)"), 3.5)
check("積分-全形括號", parse_credits("泌尿科（2點）"), 2.0)
# 冒號寫法沒有右括號，只吃 (\d+點) 的規則會漏掉整筆
check("積分-冒號", parse_credits("泌尿科：0.5點、、衛福部－品質感染：2分"), 0.5)
# 這條是重點：不能在整串裡找數字，否則會抓到別科的點數
check(
    "積分-他科不能誤抓",
    parse_credits("泌尿科(1.5點) ,婦產科,內科,家醫科3點,藥師 (學分申請中)"),
    1.5,
)
check("積分-外科在後面", parse_credits("泌尿科(1點)、外科積分(2點)"), 1.0)
check("積分-只有外科有數字", parse_credits("泌尿科(申請中)、外科積分(2點)"), None)
check("積分-申請中", parse_credits("泌尿科(申請中)"), None)
check("積分-空", parse_credits(""), None)
check("申請中-是", credits_pending("泌尿科(申請中)、外科積分(申請中)"), True)
check("申請中-否", credits_pending("泌尿科(3點)、機泌(1點)"), False)
# 收錄門檻：年會的個別議程積分欄是空的，必須被擋掉
check("門檻-年會議程", has_urology_credits(""), False)
check("門檻-他科課程", has_urology_credits("外科積分(2點)"), False)
check("門檻-申請中要收", has_urology_credits("泌尿科(申請中)"), True)

# --------------------------------------------------------------------------
# 地區與線上
# --------------------------------------------------------------------------
check("地區-地址括號", detect_region("君品酒店 5F (台北市大同區承德路一段 3 號)"), "北部")
check("地區-線上", detect_region("線上會議"), "線上")
check("地區-待定", detect_region("TBD"), "其他")
# 多院區的機構刻意不對應地區，標錯比沒標更糟
check("地區-馬偕不猜", detect_region("", "馬偕醫院、TUA"), "其他")
check("地區-台東", detect_region("台東桂田喜來登酒店"), "東部")
# 混合場：地點是實體會場，但仍然可以線上參加 —— 兩個欄位各自回答不同問題
check("線上-混合場地區", detect_region("高雄萬豪酒店"), "南部")
check(
    "線上-混合場旗標",
    detect_online("實體+【🎬線上】The Evolving Role of 5-ARIs in BPH", "高雄萬豪酒店"),
    True,
)
check("線上-純線上", detect_online("【🎬線上】泌尿癌實戰現場三部曲", "線上會議"), True)
check("線上-實體", detect_online("2026當代泌尿學論壇", "臺北榮民總醫院"), False)
# 標記要在【】裡才算，避免把課程主題誤判成上課形式
check("線上-主題不算", detect_online("遠距醫療於泌尿科的應用", "臺大醫院"), False)

# --------------------------------------------------------------------------
# 分類（中英夾雜是這個科的常態）
# --------------------------------------------------------------------------
check("分類-英文縮寫", detect_categories("Maximizing Treatment Outcomes in mCRPC"), ["泌尿腫瘤"])
check("分類-中文", detect_categories("泌尿道結石與男性性腺功能低下的臨床新知"), ["結石與內視鏡", "男性學與性功能"])
check("分類-無命中", detect_categories("TUA 9月北區月會"), [])

# --------------------------------------------------------------------------
# 主辦單位：協辦多半是藥廠，不該混進主辦欄
# --------------------------------------------------------------------------
check(
    "主辦-剝前綴與協辦",
    primary_organizer("主辦單位：新光醫院 協辦單位：台灣安斯泰來製藥股份有限公司"),
    "新光醫院",
)
check("主辦-無前綴", primary_organizer("台灣尿失禁防治協會、馬偕醫院泌尿部"), "台灣尿失禁防治協會、馬偕醫院泌尿部")
check("主辦-半形冒號", primary_organizer("主辦:台灣泌尿科醫學會 協辦單位:友華生技醫藥公司"), "台灣泌尿科醫學會")
# 學會官網寫的是「協辦廠商：」，只認「協辦單位」的話主辦欄會拖著一串藥廠名字
check(
    "主辦-協辦廠商",
    primary_organizer("台灣泌尿內視鏡醫學會 協辦廠商：某某公司、另一家公司"),
    "台灣泌尿內視鏡醫學會",
)

# --------------------------------------------------------------------------
# 日期
# --------------------------------------------------------------------------
check("日期-西元", parse_date("2026/08/22"), "2026-08-22")
check("日期-民國", parse_date("115年08月22日"), "2026-08-22")
check("年份補正-同月", eschool._resolve_date("08-22", 2026, 8), "2026-08-22")
# 12 月的頁面出現 01-02 = 跨年的多日活動
check("年份補正-跨年", eschool._resolve_date("01-02", 2026, 12), "2027-01-02")
check("年份補正-非法日期", eschool._resolve_date("02-30", 2026, 2), None)

# --------------------------------------------------------------------------
# 整列解析（用真實 HTML 的縮小版，含多日、錄影圖示、巢狀 span）
# --------------------------------------------------------------------------
FIXTURE = """
<table id='conferenceTable'><tbody>
<tr class=' '>
  <td class='  text-center  col-datetime'><div class='text-overflow'>
    <div style='margin-bottom:20px;'><span class='fs-em'>10-17</span> (六)<br>08:00 ~ 17:00</div>
    <div style='margin-bottom:20px;'><span class='fs-em'>10-18</span> (日)<br>08:30 ~ 12:30</div>
  </div></td>
  <td colspan="2"><div class='sm-text-overflow fs-em'><a href='/conference/4099'>
    <span class='text '>實體+【&#127916;線上】2026 Combined Meeting<span class='hidden-lg hidden-md'>
    <img title='有錄影' src='/sys/res/icon/film.png'></span></span></a></div></td>
  <td class='hidden-xs hidden-sm text-center  col-char3'><a href='/conference/4099'>
    <span class='text '><img title='有錄影' src='/sys/res/icon/film.png'></span></a></td>
  <td class='hidden-xs hidden-sm text-left  col-division'>主辦單位：馬偕醫院泌尿部 協辦單位：某某藥廠</td>
  <td class='hidden-xs hidden-sm text-left  col-site'>Day 1|茹曦酒店 (台北市中山區)<br /> Day 2|馬偕醫院 (台北市中山區)</td>
  <td class='hidden-xs hidden-sm text-left  col-char7'>泌尿科(6點)、外科積分(2點)</td>
  <td class='hidden-xs hidden-sm text-left  col-char7'>陳小姐 02-1234-5678#123</td>
</tr>
<tr class=' '>
  <td class='  text-center  col-datetime'><div class='text-overflow'>
    <div style='margin-bottom:20px;'><span class='fs-em'>10-18</span> (日)<br>09:00 ~ 12:00</div>
  </div></td>
  <td colspan="2"><div class='sm-text-overflow fs-em'><a href='/conference/4100'>
    <span class='text '>Podium 01</span></a></div></td>
  <td class='hidden-xs hidden-sm text-center  col-char3'></td>
  <td class='hidden-xs hidden-sm text-left  col-division'>王小明, 李小華</td>
  <td class='hidden-xs hidden-sm text-left  col-site'>g.701 G</td>
  <td class='hidden-xs hidden-sm text-left  col-char7'></td>
  <td class='hidden-xs hidden-sm text-left  col-char7'></td>
</tr>
</tbody></table>
"""

rows = eschool._parse_rows(BeautifulSoup(FIXTURE, "html.parser"), 2026, 10)
# 第二列是年會議程（積分欄空白＋主持人姓名），必須被門檻擋掉
check("整列-筆數", len(rows), 1)
if rows:
    event = rows[0]
    check("整列-開始日", event.date, "2026-10-17")
    check("整列-結束日", event.end_date, "2026-10-18")
    check("整列-時間", event.time, "08:00 ~ 17:00")
    # 巢狀 span 裡的圖示不能混進標題
    check("整列-標題", event.title, "實體+【🎬線上】2026 Combined Meeting")
    check("整列-主辦", event.organizer, "馬偕醫院泌尿部")
    check("整列-積分", event.credits, 6.0)
    check("整列-積分原文", event.credits_raw, "泌尿科(6點)、外科積分(2點)")
    check("整列-線上", event.online, True)
    check("整列-錄影標記", event.badges, ["有錄影"])
    check("整列-連結", event.url, "https://eschool.tua.org.tw/conference/4099")
    # 聯絡人（姓氏＋電話）不得進入輸出
    check("整列-不收聯絡人", "陳小姐" in str(event.to_dict()), False)

# 表格還在、也有列，卻一筆都解不出來 → 必須發警告，不能安靜地回 0 筆
BROKEN = """
<table id='conferenceTable'><tbody>
<tr class=' '><td class='new-layout'>2026-10-17</td><td>某某研討會</td></tr>
<tr class=' '><td class='new-layout'>2026-10-18</td><td>另一場研討會</td></tr>
</tbody></table>
"""
drain_warnings()  # 先清掉前面測試留下的
broken_rows = eschool._parse_rows(BeautifulSoup(BROKEN, "html.parser"), 2026, 10)
check("改版偵測-零筆", len(broken_rows), 0)
check("改版偵測-有發警告", len(drain_warnings()), 1)

# 空月份（明年的課還沒排）長這樣，是正常狀態不是改版
EMPTY_MONTH = """
<table id='conferenceTable'><tbody>
<tr id='noData' role='noData'><td class='td text-center' colspan=8>沒有資料</td></tr>
</tbody></table>
"""
drain_warnings()
check("空月份-零筆", len(eschool._parse_rows(BeautifulSoup(EMPTY_MONTH, "html.parser"), 2027, 1)), 0)
check("空月份-不誤報", len(drain_warnings()), 0)

# 表格整個不見也要發警告
drain_warnings()
eschool._parse_rows(BeautifulSoup("<div>維護中</div>", "html.parser"), 2026, 10)
check("表格消失-有發警告", len(drain_warnings()), 1)

# 「有列、解得出來，但全部被積分門檻擋掉」是合法情況，不該誤報改版
drain_warnings()
eschool._parse_rows(BeautifulSoup(FIXTURE, "html.parser"), 2026, 10)
check("門檻濾掉-不誤報", len(drain_warnings()), 0)

# --------------------------------------------------------------------------
# TUA 自己的年會／半年會：會議層級，不是議程層級
#
# 🔴 為什麼不從 conference/list 撈：年會在那張表上是攤成 88 筆個別議程，
# 每一筆的「主辦」欄放的是**座長姓名**、積分欄是空的。現行的積分門檻正是靠這點
# 把它們擋掉，同時擋著「把個人姓名登在公開網站上」。改用 E-School 首頁列出的
# 「議程總表」頁（一場會議一頁，有名稱／起訖日／地點）。
# --------------------------------------------------------------------------
check(
    "TUA會議-首頁連結認得出年份",
    tua_meetings._PAGE_HREF.search("https://eschool.tua.org.tw/p/2026_conference").group(2),
    "2026",
)
check(
    "TUA會議-半年會也認得",
    tua_meetings._PAGE_HREF.search("/p/2026mid_conference").group(2),
    "2026",
)
# 議程頁（/conference/3896）不是總表頁，不能誤收
check("TUA會議-議程頁不算", tua_meetings._PAGE_HREF.search("/conference/3896"), None)

check(
    "TUA會議-標題",
    tua_meetings._HEADING.match("2026 TUA Annual Meeting Scientific Programs").group(1),
    "2026 TUA Annual Meeting",
)
# 2025 那年官網寫的是單數 Program，少認一種寫法那年就整場抓不到
check(
    "TUA會議-標題單數也認",
    tua_meetings._HEADING.match("2025 TUA x UAA Annual Meeting Scientific Program").group(1),
    "2025 TUA x UAA Annual Meeting",
)

_d = list(tua_meetings._DAY.finditer(
    "時間: 2026/08/22 (星期六) 09:00 - 17:30 地點: 台北南港展覽館2館 7F "
    "時間: 2026/08/23 (星期日) 09:30 - 15:00 地點: 台北南港展覽館2館 7F"
))
check("TUA會議-多日抓到兩天", len(_d), 2)
check("TUA會議-第一天", "-".join(g.zfill(2) for g in _d[0].groups()[:3]), "2026-08-22")
check("TUA會議-時段", _d[0].group(4), "09:00 - 17:30")
# 英文星期（實測 2026 半年會頁面用 (Sat)）也要認
check(
    "TUA會議-英文星期",
    tua_meetings._DAY.search("時間: 2026/01/24 (Sat) 09:00-17:30").group(2),
    "01",
)

# 🔴 地點必須有界。這一條是真的踩過：2025 那頁的邊界字樣是「時間 & 會場」而不是
# 「last update」，第一版的寫法把整張議程表（含幾百個講者座長姓名）當成地點寫進輸出。
check(
    "TUA會議-地點-last update 邊界",
    tua_meetings._VENUE.search("地點: 台北南港展覽館2館 7F last update: 07.19 TIME 701 A").group(1),
    "台北南港展覽館2館 7F",
)
check(
    "TUA會議-地點-時間&會場 邊界",
    tua_meetings._VENUE.search("地點: 台北國際會議中心 (TICC) 時間 & 會場 3F 大會堂 某某醫師").group(1),
    "台北國際會議中心 (TICC)",
)
# 邊界完全沒命中時**寧可留白也不要吐半截**：超過上限就整條不匹配
check(
    "TUA會議-地點-無邊界就放棄",
    tua_meetings._VENUE.search("地點: " + "某" * 200),
    None,
)

# --------------------------------------------------------------------------
# Guideline 連結解析（三個學會，三種網頁結構）
# --------------------------------------------------------------------------
from sources import guidelines as _gl  # noqa: E402

# 每顆都要有一個實際驗證過的 fallback，否則解析失敗時按鍵會變空連結
for _key in ("tua", "aua", "eau"):
    check("guideline-fallback-{}".format(_key), _gl.FALLBACKS[_key].startswith("https://"), True)
check("guideline-三顆", len(_gl.SPECS), 3)

# 🔴 TUA 的年度規則必須**很窄**。這張公告列表裡有一堆「看起來像但不是」的項目，
# 下面每一條都是 2026-08-25 全表掃描時真的撞到的干擾項。
check("TUA年度-正版", bool(_gl._TUA_ALIAS.match("tua-guideline-2024")), True)
check("TUA年度-複數形也認", bool(_gl._TUA_ALIAS.match("tua-guidelines-2030")), True)
# 擂台賽的 alias 帶著更新的年份（2025 > 2024），寬鬆規則會直接指錯
check("TUA年度-擂台賽不算", bool(_gl._TUA_ALIAS.match("tua-2025-guideline-contest")), False)
check(
    "TUA年度-共識不算",
    bool(_gl._TUA_ALIAS.match("consensus-guideline-for-the-rechallenge-of-bcc")),
    False,
)
check(
    "TUA年度-審核辦法不算",
    bool(_gl._TUA_ALIAS.match("guidelines-for-reviewing-robotic-urological-surgery-mentorship")),
    False,
)
check("TUA標題-正版", _gl._TUA_TITLE.search("TUA治療指引 2024 電子版上線囉").group(1), "2024")
check("TUA標題-擂台賽不算", _gl._TUA_TITLE.search("TUA2025泌尿科治療指引住院醫師擂台賽活動辦法"), None)

# AUA 索引頁的寫法有兩種：單學會與合訂
check("AUA年度-單學會", _gl._AUA_YEAR.findall("Vasectomy: AUA Guideline (2026)"), ["2026"])
check(
    "AUA年度-合訂",
    _gl._AUA_YEAR.findall("Advanced Prostate Cancer: AUA/SUO Guideline (2026)"),
    ["2026"],
)
# 頁尾的版權年份不是指引年度，不能誤抓
check("AUA年度-版權年不算", _gl._AUA_YEAR.findall("©2026 American Urological Association"), [])

# EAU 的年度寫在內頁正文，同一句還會提到上一版年份，必須錨在 This 後面第一個
check(
    "EAU年度-取新不取舊",
    _gl._EAU_EDITION.search(
        "This 2026 PCa Guidelines present a limited update of the 2025 publication."
    ).group(1),
    "2026",
)
check("EAU年度-無版本標示", _gl._EAU_EDITION.search("EAU Guidelines on Prostate Cancer"), None)

# --------------------------------------------------------------------------
# 會議來源（kind=meeting）：TEA 官網的「日期 標題」清單
# --------------------------------------------------------------------------
check("TEA-單日", tea._parse_item("2026.04.18 台灣泌尿內視鏡醫學會"), ("2026-04-18", "", "台灣泌尿內視鏡醫學會"))
# 「~26」只給日，不是完整的第二個日期
check(
    "TEA-跨日",
    tea._parse_item("2026.07.25~26 泌尿腫瘤夏季研討會"),
    ("2026-07-25", "2026-07-26", "泌尿腫瘤夏季研討會"),
)
# 結束日不在開始日之後（跨月寫法／打錯）就留白，不自己推月份
check("TEA-結束日不合理", tea._parse_item("2026.07.25~03 某研討會"), ("2026-07-25", "", "某研討會"))
check("TEA-假日期", tea._parse_item("2026.02.30 某研討會"), None)
# 導覽列與頁尾的連結不是活動，必須認不出來
check("TEA-非活動連結", tea._parse_item("學術活動"), None)
check("TEA-標題開頭是年份不算跨日", tea._parse_item("2025.09.06 2025年健康台灣"), ("2025-09-06", "", "2025年健康台灣"))
# 簡章 PDF／JPG 不當內頁抓（丟給 HTML 解析器只會得到亂碼）
check("TEA-內頁只抓html", tea._is_html_page("https://x/news/20260418.html"), True)
check("TEA-不抓pdf", tea._is_html_page("https://x/news/0725-26.pdf"), False)
check("TEA-不抓jpg", tea._is_html_page("https://x/news/20260627.jpg"), False)

# --------------------------------------------------------------------------
# 會議來源：TUOA 官網日期欄的四種寫法（全部取自實際頁面）
# --------------------------------------------------------------------------
check("TUOA-單日", tuoa._parse_dates("2026/08/01(Sat)"), ("2026-08-01", ""))
check("TUOA-跨月", tuoa._parse_dates("2026/01/31-2026/02/01(Sat.Sun)"), ("2026-01-31", "2026-02-01"))
# 「.23」是同月的第二天；(SAT.SUN) 裡也有一個點，錨在第一個日期正後方才不會誤抓
check("TUOA-同月兩天", tuoa._parse_dates("2025/02/22.23(SAT.SUN)"), ("2025-02-22", "2025-02-23"))
check("TUOA-破折號單日", tuoa._parse_dates("2023-10-14"), ("2023-10-14", ""))
check("TUOA-沒有日期", tuoa._parse_dates("敬請期待"), None)

# --------------------------------------------------------------------------
# 會議來源：高杏。走的是 E-School 同一張表，但門檻換成「主辦／協辦欄提到高杏」
# --------------------------------------------------------------------------
KAOHSING_FIXTURE = """
<table id='conferenceTable'><tbody>
<tr class=' '>
  <td class='  text-center  col-datetime'><div class='text-overflow'>
    <div><span class='fs-em'>11-22</span> (六)<br>08:30 ~ 18:00</div>
  </div></td>
  <td colspan="2"><div class='sm-text-overflow fs-em'><a href='/conference/3494'>
    <span class='text '>2025 TUA南區月會暨高杏泌尿論壇</span></a></div></td>
  <td class='hidden-xs hidden-sm text-center  col-char3'></td>
  <td class='hidden-xs hidden-sm text-left  col-division'>主辦單位：高醫岡山醫院泌尿科、高杏泌尿照護協會</td>
  <td class='hidden-xs hidden-sm text-left  col-site'>高醫岡山醫院</td>
  <td class='hidden-xs hidden-sm text-left  col-char7'>泌尿科(3點)、外科積分(申請中)</td>
  <td class='hidden-xs hidden-sm text-left  col-char7'>郭小姐 07-123-4567</td>
</tr>
<tr class=' '>
  <td class='  text-center  col-datetime'><div class='text-overflow'>
    <div><span class='fs-em'>11-29</span> (六)<br>13:30 ~ 16:40</div>
  </div></td>
  <td colspan="2"><div class='sm-text-overflow fs-em'><a href='/conference/3779'>
    <span class='text '>某某醫學會冬季研習會</span></a></div></td>
  <td class='hidden-xs hidden-sm text-center  col-char3'></td>
  <td class='hidden-xs hidden-sm text-left  col-division'>主辦單位：某某醫學會 協辦單位：高雄市高杏泌尿照護協會</td>
  <td class='hidden-xs hidden-sm text-left  col-site'>高雄市三民區</td>
  <td class='hidden-xs hidden-sm text-left  col-char7'></td>
  <td class='hidden-xs hidden-sm text-left  col-char7'></td>
</tr>
</tbody></table>
"""

drain_warnings()
kh_rows = eschool.parse_month(
    BeautifulSoup(KAOHSING_FIXTURE, "html.parser"),
    2025,
    11,
    accept=kaohsing._accept,
    source_name=kaohsing.NAME,
    kind=KIND_MEETING,
)
# 第二列積分欄是空的 —— 積分門檻會擋掉它，高杏門檻不該擋
check("高杏-筆數", len(kh_rows), 2)
if len(kh_rows) == 2:
    check("高杏-kind", kh_rows[0].kind, KIND_MEETING)
    check("高杏-來源名", kh_rows[0].source, kaohsing.NAME)
    check("高杏-主辦場標記", kaohsing.role_badge(kh_rows[0].organizer), "高杏主辦")
    # 協辦欄被 primary_organizer 切掉了，所以 organizer 裡沒有「高杏」＝它是協辦
    check("高杏-協辦場標記", kaohsing.role_badge(kh_rows[1].organizer), "高杏協辦")
    check("高杏-沒積分的場次照收", kh_rows[1].credits, None)
    check("高杏-不收聯絡人", "郭小姐" in str(kh_rows[0].to_dict()), False)
# 同一批列用積分門檻跑，第二列必須被擋掉 —— 證明兩個門檻真的是分開的
check(
    "高杏-積分門檻仍擋得住",
    len(eschool.parse_month(BeautifulSoup(KAOHSING_FIXTURE, "html.parser"), 2025, 11)),
    1,
)
check("高杏-兩種門檻都沒誤報改版", len(drain_warnings()), 0)

# --------------------------------------------------------------------------
# 兩種 kind 的保留下界不同：課過期就丟，會議留兩年
# --------------------------------------------------------------------------
from sources.base import cutoff_iso as _cutoff  # noqa: E402
from sources.base import today_iso as _today  # noqa: E402

# KEEP_PAST_DAYS=0：課的下界就是今天（過期就從站上消失）
check("下界-課等於今天", _cutoff(KIND_CME), _today())
check("下界-會議比課早", _cutoff(KIND_MEETING) < _cutoff(KIND_CME), True)

# --------------------------------------------------------------------------
# 台北日期邊界（站主 2026-08-25：「已經結束的會議還有課程就不應該顯示在上面了」）
#
# 🔴 上面兩條只測了「下界這個常數等於什麼」，測不到**真正在過濾活動的那個判準**。
#    下面這幾條測的是 is_current() 本身 —— 少了它，把 >= 改成 > 這種一字之差
#    （當天的課全部提早一天消失）能一路通過整份測試。
# --------------------------------------------------------------------------
from datetime import timedelta as _timedelta  # noqa: E402

from sources.base import is_current as _is_current  # noqa: E402
from sources.base import today_taipei as _today_taipei  # noqa: E402

_CUTOFFS = {KIND_CME: _cutoff(KIND_CME), KIND_MEETING: _cutoff(KIND_MEETING)}


def _offset_day(n: int) -> str:
    """相對台北今天的第 n 天（負數是過去）。"""
    return (_today_taipei() + _timedelta(days=n)).isoformat()


def _dated(start: str, end: str = "", kind: str = KIND_CME) -> Event:
    return Event(date=start, title="邊界測試", end_date=end, kind=kind)


# 站主要的邊界就是這條：活動當天還沒過，不能從站上消失
check("邊界-課-當天仍保留", _is_current(_dated(_offset_day(0)), _CUTOFFS), True)
check("邊界-課-昨天要丟掉", _is_current(_dated(_offset_day(-1)), _CUTOFFS), False)
check("邊界-課-明天保留", _is_current(_dated(_offset_day(1)), _CUTOFFS), True)
# 多日活動看結束日：昨天開始、明天結束的課還在進行中
check(
    "邊界-課-跨過今天的多日活動保留",
    _is_current(_dated(_offset_day(-3), end=_offset_day(1)), _CUTOFFS),
    True,
)
# 多日活動整段都在過去 → 該丟
check(
    "邊界-課-整段在過去的多日活動要丟掉",
    _is_current(_dated(_offset_day(-5), end=_offset_day(-2)), _CUTOFFS),
    False,
)
# 會議留兩年份，所以昨天的會議**仍留在資料裡**（顯不顯示是前端的事）
check(
    "邊界-會議-昨天仍留在資料裡",
    _is_current(_dated(_offset_day(-1), kind=KIND_MEETING), _CUTOFFS),
    True,
)
# 但比保留下界更舊的會議一樣要丟，否則兩年份的界線形同虛設
check(
    "邊界-會議-超過兩年的要丟掉",
    _is_current(_dated(_offset_day(-800), kind=KIND_MEETING), _CUTOFFS),
    False,
)

# --------------------------------------------------------------------------
# 個資防線：官網把承辦人電話／信箱寫在地點同一段，抽欄位時要挖掉
# （scripts/pii-scan.sh 是最後一道閘門，這裡是讓資料一開始就不髒）
# --------------------------------------------------------------------------
# 🔴 這幾條的測資一律用**虛構**的號碼與信箱，不要貼來源網站上真實承辦人的聯絡方式 ——
#    測試檔跟著 repo 公開，把真號碼寫進來就是自己把個資推上去（這正是這支測試在防的事）。
#    信箱那條還得把字串拆開拼，否則 scripts/pii-scan.sh 會在自己的測試檔裡抓到信箱樣式
#    而擋下 CI。拆開拼不會削弱測試：真正被檢驗的是 scrub_contacts() 執行時的行為。
check("個資-挖電話", scrub_contacts("某某會議中心 洽詢 02-1234-5678 #123"), "某某會議中心 洽詢")
check("個資-挖信箱", scrub_contacts("報名請洽 nobody" + "@" + "example.invalid"), "報名請洽")
check("個資-挖手機", scrub_contacts("聯絡 0900-000-000"), "聯絡")
# 挖完只剩標點就當它是空的，不要留一個「（）」在卡片上
check("個資-挖完剩標點", scrub_contacts("( 0912-345-678 )"), "")
# 正常地址不能被誤傷（門牌號碼、樓層、郵遞區號都有數字）
check(
    "個資-地址不誤傷",
    scrub_contacts("臺北文創大樓六樓多功能廳D+E (台北市信義區菸廠路88號)"),
    "臺北文創大樓六樓多功能廳D+E (台北市信義區菸廠路88號)",
)
check("個資-時間不誤傷", scrub_contacts("2026/04/18(W六) 13:00~18:00"), "2026/04/18(W六) 13:00~18:00")

# --------------------------------------------------------------------------
# 彙整層：來源拋例外時，它在例外**之前**發的 warning 不能跟著消失
# （只在成功分支 drain 的話，那些訊息會卡在緩衝區裡沒人看得到）
# --------------------------------------------------------------------------
import contextlib  # noqa: E402
import io  # noqa: E402
import importlib.util  # noqa: E402
import tempfile  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "build", str(Path(__file__).resolve().parent / "build.py")
)
_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_build)


class _FailingSource:
    NAME = "測試用假來源"
    __name__ = "failing_source"

    @staticmethod
    def fetch():
        from sources.base import warn as _warn

        _warn("測試用假來源：有列但一筆都解析不出來")
        raise RuntimeError("連線失敗")


# 同一場活動如果兩條線都收得到（例如學會年會有申請泌尿科積分），去重不可以把它合成
# 一筆 —— 合掉的話有一個分頁會少一場，而且少得無聲無息
from sources.base import Event as _Event  # noqa: E402

_same = [
    _Event(date="2026-01-31", title="某學會年會", kind=KIND_CME, source="A"),
    _Event(date="2026-01-31", title="某學會年會", kind=KIND_MEETING, source="B"),
]
check("去重-不同 kind 各留一份", len(_build.dedupe(_same)), 2)
check(
    "去重-同 kind 同名同日才合併",
    len(_build.dedupe(_same + [_Event(date="2026-01-31", title="某學會年會", kind=KIND_CME, source="A")])),
    2,
)

_orig_sources, _orig_output = _build.SOURCES, _build.OUTPUT
_build.SOURCES = [_FailingSource]
_build.OUTPUT = Path(tempfile.mkdtemp()) / "events.json"
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf), contextlib.redirect_stderr(_buf):
    _rc = _build.main()
_out = _buf.getvalue()
_build.SOURCES, _build.OUTPUT = _orig_sources, _orig_output
drain_warnings()

check("來源全掛-退出碼", _rc, 1)
check("來源全掛-例外訊息有出現", "連線失敗" in _out, True)
check("來源全掛-例外前的警告沒消失", "一筆都解析不出來" in _out, True)

# --------------------------------------------------------------------------
# 降級寫入：兩種 kind 各判各的，一邊掛掉不能牽連另一邊
#
# 這一整段是 codex review 2026-08-25 兩輪抓出來的。錯誤的作法有兩種，
# 兩種的後果一模一樣 ——「那一頁被默默清空 / 默默停止更新，畫面上看不出來」，
# 正是這個站最想避免的失敗形態，只是換一頁重演：
#   ① 積分課程掛掉時整份檔案跳過寫入 → 會議那頁跟著停止更新（第 1 輪）
#   ② 只用積分課程的筆數判成敗       → 會議三個來源全滅時仍判成功、把會議洗成 0 筆（第 2 輪）
# --------------------------------------------------------------------------
import json as _json  # noqa: E402

_PREVIOUS_FILE = {
    "updated_at": "2026-08-01T06:00:00+08:00",
    "count": 2,
    "events": [
        {"date": "2099-12-31", "title": "上一次抓到的課", "kind": KIND_CME},
        {"date": "2099-06-30", "title": "上一次抓到的會議", "kind": KIND_MEETING},
    ],
}


def _fake_source(name, kind, events):
    return type(
        "FakeSource",
        (),
        {
            "NAME": name,
            "KIND": kind,
            "__name__": name,
            "fetch": staticmethod(lambda: list(events)),
        },
    )


def _run_build(sources):
    """拿既有檔案跑一次 build.main()，回傳 (退出碼, 寫出去的內容)。"""
    tmp = Path(tempfile.mkdtemp()) / "events.json"
    tmp.write_text(_json.dumps(_PREVIOUS_FILE, ensure_ascii=False), encoding="utf-8")
    orig_sources, orig_output = _build.SOURCES, _build.OUTPUT
    _build.SOURCES, _build.OUTPUT = sources, tmp
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = _build.main()
    _build.SOURCES, _build.OUTPUT = orig_sources, orig_output
    drain_warnings()
    return rc, _json.loads(tmp.read_text(encoding="utf-8"))


_NEW_MEETING = _Event(
    date="2099-01-01", title="這次剛抓到的會議", kind=KIND_MEETING, source="會議來源"
)
_NEW_CME = _Event(date="2099-02-02", title="這次剛抓到的課", kind=KIND_CME, source="積分來源")

# ① 積分課程掛掉、會議正常
_rc2, _written = _run_build(
    [_FailingSource, _fake_source("會議來源", KIND_MEETING, [_NEW_MEETING])]
)
_titles = [e["title"] for e in _written["events"]]
check("降級①-退出碼是失敗", _rc2, 1)
check("降級①-舊的課要留著", "上一次抓到的課" in _titles, True)
check("降級①-新抓到的會議要寫進去", "這次剛抓到的會議" in _titles, True)
check("降級①-舊會議被新結果取代", "上一次抓到的會議" in _titles, False)
check("降級①-updated_at 不能被改新", _written["updated_at"], _PREVIOUS_FILE["updated_at"])
check("降級①-告警指名是積分課程", "沒有抓到任何積分課程" in _written["errors"][0], True)

# ② 會議三個來源全滅、積分課程正常 —— 反過來也要有一樣的保護
_rc3, _written3 = _run_build(
    [_fake_source("積分來源", KIND_CME, [_NEW_CME]), _FailingSource]
)
_titles3 = [e["title"] for e in _written3["events"]]
check("降級②-會議全滅也算失敗", _rc3, 1)
check("降級②-舊的會議要留著", "上一次抓到的會議" in _titles3, True)
check("降級②-新抓到的課要寫進去", "這次剛抓到的課" in _titles3, True)
check("降級②-舊的課被新結果取代", "上一次抓到的課" in _titles3, False)
check("降級②-告警指名是學會會議", "沒有抓到任何學會會議" in _written3["errors"][0], True)

# ③ 兩邊都正常 = 完全不碰舊資料，退出碼 0
_rc4, _written4 = _run_build(
    [
        _fake_source("積分來源", KIND_CME, [_NEW_CME]),
        _fake_source("會議來源", KIND_MEETING, [_NEW_MEETING]),
    ]
)
check("正常-退出碼 0", _rc4, 0)
check("正常-筆數", _written4["count"], 2)
check("正常-updated_at 有更新", _written4["updated_at"] != _PREVIOUS_FILE["updated_at"], True)
check("正常-沒有降級告警", _written4["errors"], [])

# ④ 兩種同時掛掉：告警順序要照 (積分課程, 學會會議)，不能被逐條 insert(0) 反轉
_rc5, _written5 = _run_build([_FailingSource])
check("兩種全掛-退出碼", _rc5, 1)
# 索引前要先確認長度：check() 只比對值不做防呆，直接寫 errors[1] 的話
# 一旦訊息少於兩條會拋 IndexError 中斷整份測試，而不是記成一筆失敗
_errs5 = _written5["errors"]
check("兩種全掛-告警兩條", len(_errs5) >= 2, True)
check("兩種全掛-第一條是積分課程", "積分課程" in _errs5[0] if _errs5 else False, True)
check("兩種全掛-第二條是學會會議", "學會會議" in _errs5[1] if len(_errs5) > 1 else False, True)
check("兩種全掛-舊資料兩種都留著", len(_written5["events"]), 2)

if FAILURES:
    print("自我測試失敗 {} 項：".format(len(FAILURES)), file=sys.stderr)
    for line in FAILURES:
        print("  ✗ " + line, file=sys.stderr)
    raise SystemExit(1)

print("自我測試全部通過")
