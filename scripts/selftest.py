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
    norm_title,
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
# 🔴 這一條是「擋 258 筆年會議程」的**全部防線**（積分欄空白 → 不收）。
#    它看起來只是個空字串檢查，但拿掉它，2027-01 半年會約 35 筆、
#    2027-08 年會約 88 筆議程會在同一天灌進清單。見 base.has_urology_credits 的註解。
check("門檻-年會議程", has_urology_credits(""), False)
check("門檻-他科課程", has_urology_credits("外科積分(2點)"), False)
check("門檻-申請中要收", has_urology_credits("泌尿科(申請中)"), True)
# 2026-08-25 放寬：積分欄寫「泌尿(3點)」沒寫「泌尿科」的場次原本被整列濾掉
# （實抓 1 筆：高雄榮總 35 周年院慶暨台灣新創醫療學會半年會議）
check("門檻-泌尿不含科要收", has_urology_credits("泌尿(3點)、外科學分、護理師學分"), True)
check("門檻-泌尿冒號點數要收", has_urology_credits("泌尿：0.5點"), True)
# 🔴 放寬的界線：不能寫成 `"泌尿" in text`，否則正文詞會被當成積分欄
check("門檻-泌尿道感染不是積分", has_urology_credits("泌尿道感染衛教課程"), False)
# 放寬前就會收的要繼續收（確認沒改壞）
check(
    "門檻-放寬後原本收的仍要收",
    has_urology_credits("泌尿科(1.5點) ,婦產科,內科,家醫科3點,藥師 (學分申請中)"),
    True,
)
# 這一列是靠比對到「台灣泌尿科醫學會」這個**學會名**而不是積分名才通過的。
# 結論碰巧正確（它確實申請了泌尿科積分），但機制是誤打誤撞 —— 釘住它，
# 免得日後有人「修正」比對邏輯時把這一列弄丟。
check(
    "門檻-靠學會名通過的那列不要弄丟",
    has_urology_credits("(申請中):台灣外科醫學會、台灣消化系外科醫學會、台灣泌尿科醫學會、癌症醫學會。"),
    True,
)

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

# --------------------------------------------------------------------------
# 年度國際會議（sources/tua_international.py）
#
# 這一頁補的是「國外辦、不申請台灣積分 → 永遠不會進 E-School」的國際年會。
# 版面是規整的「月/日 ｜ 議程」表，測資取自 2026 那一頁的實際結構。
# --------------------------------------------------------------------------
from sources import tua_international as _intl  # noqa: E402

_INTL_FIXTURE = """
<table><tbody>
<tr><th>月/日</th><th>議程</th></tr>
<tr><td>2/28-3/3</td><td>USANZ 2026／澳洲墨爾本</td></tr>
<tr><td>3/13-3/16</td><td><a href="https://eauncongress.uroweb.org/">EAU 2026／ 英國倫敦</a></td></tr>
<tr><td>12/28-1/3</td><td>跨年測試會議／某地</td></tr>
<tr><td>2/30</td><td>來源打錯的日期／某地</td></tr>
<tr><td>敬請期待</td><td>還沒公布的場次</td></tr>
</tbody></table>
"""

_intl_rows = _intl.parse_page(_INTL_FIXTURE, 2026, "https://www.tua.org.tw/announce")

# 表頭、非日期列、來源打錯的日期都要自動略過，不能變成一筆爛資料
check("國際-只收得出日期的列", len(_intl_rows), 3)
check("國際-起日", _intl_rows[0].date, "2026-02-28")
check("國際-迄日", _intl_rows[0].end_date, "2026-03-03")
# 標題與地點用全形／分隔，斜線後常多一個空白
check("國際-標題切開", _intl_rows[1].title, "EAU 2026")
check("國際-地點去掉前導空白", _intl_rows[1].location, "英國倫敦")
# 有外部連結就連過去，沒有就連回學會公告頁（不留空連結）
check("國際-有連結用連結", _intl_rows[1].url, "https://eauncongress.uroweb.org/")
check("國際-沒連結退回公告頁", _intl_rows[0].url, "https://www.tua.org.tw/announce")
# 🔴 年份來自公告 slug 不在頁面文字裡，跨年要把結束年 +1（12/28-1/3）
check("國際-跨年起日", _intl_rows[2].date, "2026-12-28")
check("國際-跨年迄日進到隔年", _intl_rows[2].end_date, "2027-01-03")
check("國際-都是會議線", {e.kind for e in _intl_rows}, {KIND_MEETING})

# 🔴 公告網址每年換，slug 比對要窄：同一個分類底下混著徵選／遴選公告，
#    用「網址含 international」會指錯（TUA guideline 那邊踩過的同型坑）
check("國際-slug比對-正版命中", bool(_intl._SLUG.search("/2627-2026-international-meeting")), True)
check("國際-slug比對-EUREP不命中", bool(_intl._SLUG.search("/2683-2026-eurep")), False)
check("國際-slug比對-AURC不命中", bool(_intl._SLUG.search("/2662-result-aurc-2026")), False)
check(
    "國際-slug比對-分類資料夾本身不命中",
    bool(_intl._SLUG.search("/tua/tw/latest-news/events/86-international-meeting")),
    False,
)

# --------------------------------------------------------------------------
# 年度行事曆頁：只抽理監事會議（sources/tua_calendar.py）
#
# 🔴 這一頁的日期會漂移（實測 ±7～14 天），所以**只准拿來抽理監事會議** ——
#    區域月會／季會 E-School 有更準的版本。測資取自 2026 行事曆的真實列。
# --------------------------------------------------------------------------
from sources import tua_calendar as _cal  # noqa: E402

_CAL_FIXTURE = """
<table><tbody>
<tr><th>月/日</th><th>議程</th></tr>
<tr><td>1/17</td><td>中區季會／中榮</td></tr>
<tr><td>1/24</td><td>TUA半年會／光田</td></tr>
<tr><td>4/11</td><td>第24屆第6次理監事會議／IEAT會議中心</td></tr>
<tr><td>8/23</td><td>第25屆第1次理監事會議／南港展覽館二館</td></tr>
<tr><td>2/28-3/3</td><td>USANZ 2026／澳洲墨爾本</td></tr>
</tbody></table>
"""

_cal_rows = _intl.parse_table(
    _CAL_FIXTURE, 2026, "https://www.tua.org.tw/cal", keep=_cal._keep, source_name=_cal.NAME
)

# 🔴 只收理監事：區域季會／半年會／國際年會都必須被擋掉
#    （它們在別的來源有更準的版本，從這頁收會拿到漂移 ±7～14 天的日期）
check("行事曆-只收理監事", len(_cal_rows), 2)
check("行事曆-標題都含理監事", all("理監事" in e.title for e in _cal_rows), True)
check("行事曆-區域季會被擋", any("季會" in e.title for e in _cal_rows), False)
check("行事曆-半年會被擋", any("半年會" in e.title for e in _cal_rows), False)
check("行事曆-國際年會被擋", any("USANZ" in e.title for e in _cal_rows), False)
check("行事曆-日期", _cal_rows[0].date, "2026-04-11")
check("行事曆-來源名", _cal_rows[0].source, "台灣泌尿科醫學會 理監事會議")
check("行事曆-是會議線", {e.kind for e in _cal_rows}, {KIND_MEETING})
# 屆次數字會變，所以認「理監事」三個字而不是整串
check("行事曆-keep認關鍵字不認屆次", _cal._keep("第99屆第9次理監事會議", ""), True)
check("行事曆-keep擋掉月會", _cal._keep("南區月會", ""), False)
# slug 比對：公告區上千則，用「網址含 calendar」會掃到別的東西
check("行事曆-slug命中", bool(_cal._SLUG.search("/2599-2026-calendar")), True)
check("行事曆-slug不命中別的公告", bool(_cal._SLUG.search("/2198-tua-guideline-2024")), False)

# --------------------------------------------------------------------------
# .ics 訂閱檔（sources/icsfeed.py）
#
# 🔴 這一組最重要的是 **UID 穩定性**：同一場活動每次 build 都要算出相同的 UID，
#    否則訂閱端會把它當成新事件重複跳出來 —— 這是 ics 最常見也最惱人的坑，
#    而且它**不會有任何錯誤訊息**，只有訂閱的人被洗版。
# --------------------------------------------------------------------------
from sources import icsfeed as _ics  # noqa: E402


def _ev_ics(**kwargs):
    base_kwargs = dict(date="2026-09-06", title="測試研討會", kind=KIND_CME)
    base_kwargs.update(kwargs)
    return Event(**base_kwargs)


# 同樣的識別欄位 → 同樣的 UID（跑兩次也一樣）
check("ics-UID-同一場兩次相同", _ics.event_uid(_ev_ics()), _ics.event_uid(_ev_ics()))

# 🔴 會被來源網站改來改去的欄位**不可以**影響 UID，否則官網補個地點就等於新事件
check(
    "ics-UID-不受地點時間網址積分影響",
    _ics.event_uid(_ev_ics()),
    _ics.event_uid(
        _ev_ics(
            location="台北國際會議中心",
            time="09:00 ~ 17:00",
            url="https://example.invalid/x",
            credits=3.0,
            credits_raw="泌尿科(3點)",
        )
    ),
)
# 標題裡的括號註記與空白標點被正規化掉，仍算同一場（跟 dedupe 的判準一致）
check(
    "ics-UID-標題註記不影響",
    _ics.event_uid(_ev_ics()),
    _ics.event_uid(_ev_ics(title="【線上】測試 研討會（3點）")),
)
# 但日期、kind、實質標題不同就必須是不同事件
check("ics-UID-日期不同要不同", _ics.event_uid(_ev_ics()) != _ics.event_uid(_ev_ics(date="2026-09-07")), True)
check("ics-UID-kind不同要不同", _ics.event_uid(_ev_ics()) != _ics.event_uid(_ev_ics(kind=KIND_MEETING)), True)
check("ics-UID-標題不同要不同", _ics.event_uid(_ev_ics()) != _ics.event_uid(_ev_ics(title="另一場會")), True)

# UID 與 dedupe 用的是同一支正規化函式（兩邊若各留一份，改了一邊就會無聲失準）
check("ics-UID-與dedupe共用正規化", norm_title("【線上】測試 研討會（3點）"), norm_title("測試研討會"))

# 🔴 UID 不可以長得像 email。ics 的慣例寫法是 <識別碼>@<網域>，但那個形狀跟信箱
#    一模一樣，scripts/pii-scan.sh 的信箱規則會把整份 .ics 判成個資外洩
#    （2026-08-25 首次產出時真的被擋下 49 筆）。閘門分辨不出 UID 與信箱，
#    所以要改的是我們的格式，不是把 data/*.ics 加進白名單。
check("ics-UID-不含@不像信箱", "@" in _ics.event_uid(_ev_ics()), False)
check("ics-UID-有專案命名空間前綴", _ics.event_uid(_ev_ics()).startswith("taiwan-urology-cme-"), True)

_rendered = _ics.render([_ev_ics(time="09:00 ~ 17:30", location="台北")], "測試日曆", dtstamp="20260825T000000Z")
_ics_lines = _rendered.split("\r\n")

check("ics-換行是CRLF", "\r\n" in _rendered, True)
check("ics-沒有裸LF", _rendered.replace("\r\n", "").count("\n"), 0)
check("ics-開頭", _ics_lines[0], "BEGIN:VCALENDAR")
check("ics-結尾", [l for l in _ics_lines if l][-1], "END:VCALENDAR")
check("ics-有台北時區宣告", "TZID:Asia/Taipei" in _rendered, True)
# 有起訖時間的單日活動 → 帶 TZID 的實際時段，不是整天事件
check("ics-有時間用TZID", "DTSTART;TZID=Asia/Taipei:20260906T090000" in _rendered, True)
check("ics-結束時間正確", "DTEND;TZID=Asia/Taipei:20260906T173000" in _rendered, True)

# 沒寫時間 → 整天事件，DTEND 是**不含**的所以要 +1 天
_allday = _ics.render([_ev_ics()], "x", dtstamp="20260825T000000Z")
check("ics-整天DTSTART", "DTSTART;VALUE=DATE:20260906" in _allday, True)
check("ics-整天DTEND隔天", "DTEND;VALUE=DATE:20260907" in _allday, True)
# 多日活動以結束日為準，一樣要 +1
_multi = _ics.render([_ev_ics(end_date="2026-09-08")], "x", dtstamp="20260825T000000Z")
check("ics-多日DTEND用結束日+1", "DTEND;VALUE=DATE:20260909" in _multi, True)

# 跳脫：逗號／分號／反斜線要跳脫，換行寫成 \n（否則整份檔會被訂閱端判為壞掉）
_esc = _ics.render(
    [_ev_ics(title="A,B;C\\D", location="地點,一")], "x", dtstamp="20260825T000000Z"
)
check("ics-跳脫逗號分號反斜線", "SUMMARY:A\\,B\\;C\\\\D" in _esc, True)
check("ics-跳脫地點逗號", "LOCATION:地點\\,一" in _esc, True)

# 🔴 折行必須以 octet 計算：中文一個字 3 bytes，用字元數折會超長被嚴格的訂閱端整份拒收
_long = _ics.render(
    [_ev_ics(title="泌尿科繼續教育學術研討會" * 8)], "x", dtstamp="20260825T000000Z"
)
check(
    "ics-折行不超過75octet",
    max(len(l.encode("utf-8")) for l in _long.split("\r\n")) <= 75,
    True,
)
# 這條防的是「測試自己失效」：標題長到一定會折行，若某次改動讓它不再折行，
# 上面那條照樣通過但其實什麼都沒驗到。
check("ics-這個案例真的有折到行", any(l.startswith(" ") for l in _long.split("\r\n")), True)
_unfolded = []
for _l in _long.split("\r\n"):
    if _l.startswith(" ") and _unfolded:
        _unfolded[-1] += _l[1:]
    else:
        _unfolded.append(_l)
check(
    "ics-折行可還原成原標題",
    any("泌尿科繼續教育學術研討會" * 8 in l for l in _unfolded),
    True,
)


# ⚠️ 三種換行都要統一成跳脫符再寫進去。單獨的 CR（舊式 Mac 換行）如果直接砍掉，
#    兩行會被黏成一行、斷行語意整個消失，而且不會有任何提示。
_crlf = _ics.render([_ev_ics(title="上排\r\n下排")], "x", dtstamp="20260825T000000Z")
check("ics-CRLF換行轉跳脫", "SUMMARY:上排\\n下排" in _crlf, True)
_barecr = _ics.render([_ev_ics(title="上排\r下排")], "x", dtstamp="20260825T000000Z")
check("ics-單獨CR不被砍掉", "SUMMARY:上排\\n下排" in _barecr, True)

# --------------------------------------------------------------------------
# 訂閱檔的切法：分頁 × 地區（scripts/build.py 的 _write_feeds）
#
# 🔴 這一組守的是三件會**沉默失效**的事：
#    ① 前端拿到的檔名對應不到磁碟上的檔 → 訂閱網址 404，零錯誤訊息
#    ② 兩個分頁被混進同一份地區檔 → 訂了積分課程卻收到一堆理監事會議
#    ③ 空的範圍留下上一輪的舊檔 → 訂閱者永遠收到不再更新的資料，毫無徵兆
# --------------------------------------------------------------------------
import importlib.util  # noqa: E402
import tempfile  # noqa: E402

from sources import base as _base  # noqa: E402
from sources.base import REGION_SLUGS  # noqa: E402

# 每個 detect_region() 產得出來的地區都要有檔名代號，否則那個地區永遠沒有專屬
# 訂閱檔（會靜靜地被收進「全部」那份，使用者只會覺得「怎麼沒有我這區」）。
# 直接讀 _REGION_MAP 而不是再抄一份地區清單 —— 抄一份的話，日後有人加了新地區
# 卻沒補代號，這條測試會跟著漏掉，等於白守。
_producible_regions = {detect_region(""), detect_region("線上會議")}
_producible_regions.update(region for region, _ in _base._REGION_MAP)
check("地區代號-涵蓋所有產得出的地區", sorted(_producible_regions - set(REGION_SLUGS)), [])
check("地區代號-全是ASCII", all(s.isascii() and s.isalpha() for s in REGION_SLUGS.values()), True)
check("地區代號-沒有重複", len(set(REGION_SLUGS.values())), len(REGION_SLUGS))

# scripts/ 沒有 __init__.py（icsfeed 放在 sources/ 就是為了這個），
# 所以這裡用檔案路徑載入 build.py。載入只會跑到 import 與常數，main() 有 __main__ 守著。
_build_path = Path(__file__).resolve().parent / "build.py"
_spec = importlib.util.spec_from_file_location("_build_under_test", _build_path)
_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_build)


def _feed_uids(path: Path):
    """一份 .ics 裡的所有 UID。

    ⚠️ 一定要 newline="" 讀。`read_text()` 走 universal newlines 會把 \\r\\n 翻成 \\n，
    再用 "\\r\\n" 切就切不出任何行 —— 集合永遠是空的，而**空集合之間的比較全部成立**，
    下面「兩個分頁不重疊」「地區檔聯集等於全部」那幾條會安靜地變成沒在測。
    （這不是假想：第一版就是這樣寫的，靠一條數量比對才露出來。）
    """
    if not path.exists():
        # 對照表指到不存在的檔（＝訂閱網址 404）。記成失敗而不是讓例外炸掉整支測試 ——
        # 炸掉的話結尾那份失敗清單根本印不出來，其他真正的失敗會跟著被藏住。
        FAILURES.append("{}：對照表指到這個檔，但它不在磁碟上".format(path.name))
        return set()
    with open(path, encoding="utf-8", newline="") as handle:
        text = handle.read()
    uids = {l[4:] for l in text.split("\r\n") if l.startswith("UID:")}
    if not uids:
        FAILURES.append("{}：讀不到任何 UID（測試本身失效了）".format(path.name))
    return uids


_rows = [
    Event(date="2026-09-06", title="北部課", kind=KIND_CME, region="北部").to_dict(),
    Event(date="2026-09-07", title="南部課", kind=KIND_CME, region="南部").to_dict(),
    Event(date="2026-09-08", title="北部會", kind=KIND_MEETING, region="北部").to_dict(),
]

with tempfile.TemporaryDirectory() as _tmp:
    _dir = Path(_tmp)
    _build.OUTPUT = _dir / "events.json"

    # 上一輪留下來的檔：這一輪沒有中部活動，它必須被刪掉而不是繼續留著騙訂閱者。
    _stale = _dir / "cme-central.ics"
    # 用 open 不用 write_text：後者在 3.9 沒有 newline 參數（build.py 同一個理由）
    with open(_stale, "w", encoding="utf-8", newline="") as _h:
        _h.write("BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")

    _feeds = _build._write_feeds(_rows, "2026-09-01T06:00:00+08:00")

    check("訂閱檔-兩個分頁各有一份全部", [_feeds[KIND_CME][""], _feeds[KIND_MEETING][""]],
          ["cme.ics", "meeting.ics"])
    check("訂閱檔-地區檔跟著分頁走", _feeds[KIND_CME].get("北部"), "cme-north.ics")
    check("訂閱檔-另一個分頁的地區檔是另一個檔名", _feeds[KIND_MEETING].get("北部"), "meeting-north.ics")
    # 🔴 沒有活動的組合不可以有檔名（前端就不會顯示那個選項）
    check("訂閱檔-沒活動的地區不進對照表", "南部" in _feeds[KIND_MEETING], False)
    check("訂閱檔-沒活動的地區不產檔", (_dir / "meeting-south.ics").exists(), False)
    # 🔴 上一輪的舊檔要刪掉，留著＝訂閱者永遠收到不再更新的資料
    check("訂閱檔-上一輪的舊檔被刪掉", _stale.exists(), False)

    # 🔴 對照表裡的每個檔名都必須真的在磁碟上，否則就是 404 訂閱網址
    _missing = sorted(
        name for per_kind in _feeds.values() for name in per_kind.values()
        if not (_dir / name).exists()
    )
    check("訂閱檔-對照表的檔案都真的存在", _missing, [])

    # 🔴 分頁不可以互相混進來 —— 訂了積分課程卻收到理監事會議正是站主不要的
    _cme_all = _feed_uids(_dir / "cme.ics")
    _meeting_all = _feed_uids(_dir / "meeting.ics")
    check("訂閱檔-兩個分頁的事件完全不重疊", sorted(_cme_all & _meeting_all), [])
    check("訂閱檔-地區檔不含另一個分頁的事件",
          _feed_uids(_dir / "cme-north.ics") & _meeting_all, set())

    # 地區檔的聯集要等於該分頁「全部」那份：少了＝有活動訂不到，多了＝重複
    _union = set()
    for _r, _name in _feeds[KIND_CME].items():
        if _r:
            _union |= _feed_uids(_dir / _name)
    check("訂閱檔-地區檔聯集等於該分頁全部", _union, _cme_all)

    # 寫檔用 newline=""，否則 CRLF 會被再翻譯成 \r\r\n（嚴格的訂閱端會拒收）
    _raw = (_dir / "cme.ics").read_bytes()
    check("訂閱檔-寫出來沒有變成CRCRLF", b"\r\r\n" in _raw, False)
    check("訂閱檔-寫出來是CRLF", b"\r\n" in _raw, True)

    # 地區沒收進 REGION_SLUGS 時：不產專屬檔，但仍然收在「全部」那份裡（不可以整筆消失）
    _odd = _rows + [
        Event(date="2026-09-09", title="外太空課", kind=KIND_CME, region="外太空").to_dict()
    ]
    _feeds2 = _build._write_feeds(_odd, "2026-09-01T06:00:00+08:00")
    check("訂閱檔-未收錄地區不進對照表", "外太空" in _feeds2[KIND_CME], False)
    check("訂閱檔-未收錄地區仍收在全部那份", len(_feed_uids(_dir / "cme.ics")), 3)

    # 某個分頁整個沒資料：不產空日曆，並刪掉上一輪的檔；前端靠 feeds 缺 "" 藏整區
    _feeds3 = _build._write_feeds(
        [r for r in _rows if r["kind"] == KIND_CME], "2026-09-01T06:00:00+08:00"
    )
    check("訂閱檔-空分頁沒有全部那份", "" in _feeds3[KIND_MEETING], False)
    check("訂閱檔-空分頁的檔被刪掉", (_dir / "meeting.ics").exists(), False)
    check("訂閱檔-空分頁的地區檔也被刪掉", (_dir / "meeting-north.ics").exists(), False)

if FAILURES:
    print("自我測試失敗 {} 項：".format(len(FAILURES)), file=sys.stderr)
    for line in FAILURES:
        print("  ✗ " + line, file=sys.stderr)
    raise SystemExit(1)

print("自我測試全部通過")
