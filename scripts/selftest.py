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

from sources import eschool
from sources.base import (
    credits_pending,
    drain_warnings,
    detect_categories,
    detect_online,
    detect_region,
    has_urology_credits,
    parse_credits,
    parse_date,
    primary_organizer,
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

if FAILURES:
    print("自我測試失敗 {} 項：".format(len(FAILURES)), file=sys.stderr)
    for line in FAILURES:
        print("  ✗ " + line, file=sys.stderr)
    raise SystemExit(1)

print("自我測試全部通過")
