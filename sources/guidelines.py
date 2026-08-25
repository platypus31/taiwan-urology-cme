"""三個泌尿科學會的治療指引（guideline）連結解析。

站上「Guideline」區的三顆按鍵就是這裡產出的。站主 2026-08-25 的要求有兩層：
① 按鍵要直接落在 guideline 本體／索引頁，不是協會首頁；
② 「他們三個如果有更新你會幫我每年更新」→ 網址**不寫死**，每次跑都去解析最新的。

🔴 **三個站的結構完全不同，所以是三支 adapter 共用一個骨架，不是一套通用爬蟲**
（站主原話：「依照他們網頁搜尋邏輯來設計爬蟲」）。差異是真的，不是潔癖：

    TUA  年度公告型 —— 每出一版就是**一個新網址**（`…/2198-tua-guideline-2024`）。
                      不解析的話，按鍵會永遠停在 2024 版。
    AUA  索引頁型   —— 網址固定，內容自己更新；索引頁上會列出各份 guideline 的年度
                      （`… : AUA Guideline (2026)`），所以年度解析得到。
    EAU  索引頁型   —— 網址固定，但索引頁**沒有**任何版本標示（只有 21 個疾病主題連結），
                      年度寫在各疾病內頁的正文裡。

**每一顆都有 fallback**：解析失敗就退回下面 FALLBACKS 裡那個「已實際打開驗證過」的網址，
絕不讓按鍵變成空連結或 404。解析失敗會被記進輸出的 `errors`，站上會顯示，CI 會變紅。

🔴 **反幻覺紅線**：FALLBACKS 裡的每一個網址都是 2026-08-25 用 curl 實測回 200 的。
日後要改這裡的網址，**必須先實際打開驗證**，不准用網址規律推導一個看起來合理的出來。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Callable, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import SourceError, clean_text, get


@dataclass
class Guideline:
    """一顆 guideline 按鍵。"""

    key: str  # tua / aua / eau
    label: str  # 按鍵上的英文短名
    full_name: str  # 中文全名，放在 title 屬性讓滑鼠停留時看得到
    url: str
    version: str = ""  # 年度／版本，**只能來自解析結果，不准手寫**
    resolved: bool = False  # True=這次動態解析成功；False=退回 fallback
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# 🔴 全部 2026-08-25 實測回 200。TUA 這個網址是站主親自給的，逐字照抄。
FALLBACKS = {
    "tua": "https://www.tua.org.tw/tua/tw/latest-news/announcement/2198-tua-guideline-2024",
    "aua": "https://www.auanet.org/guidelines-and-quality/guidelines",
    "eau": "https://uroweb.org/guidelines",
}


# --------------------------------------------------------------------------
# TUA —— 台灣泌尿科醫學會（年度公告型）
# --------------------------------------------------------------------------
TUA_BASE = "https://www.tua.org.tw"
# 用學會自己的「顯示全部」參數，不要自己一頁一頁翻。
# 這張列表預設一頁 15 筆、共 52 頁（`?start=15` 這樣翻），但它吃 `?limit=0`
# ——一次回傳全部 768 筆（2026-08-25 實測）。一個請求換 52 個請求，而且不會因為
# 新公告插進來導致翻頁時漏抓。
TUA_LIST_URL = TUA_BASE + "/tua/tw/latest-news/announcement?limit=0"

# 兩條規則取聯集，命中任一條就算候選，再取年份最大的那筆。
#
# ⚠️ 規則必須**很窄**，因為這張列表裡有一堆「看起來很像」但不是治療指引的公告，
#    實測 2026-08-25 全表掃描抓到的干擾項：
#      ・`tua-2025-guideline-contest`「TUA2025泌尿科治療指引住院醫師擂台賽」← 擂台賽不是指引
#      ・`consensus-guideline-for-the-rechallenge-of-bcc`「攝護腺癌生化復發治療共識」← 共識不是指引
#      ・`guidelines-for-reviewing-robotic-urological-surgery-mentorship`「審核辦法」← 辦法不是指引
#    用寬鬆的「含 guideline 就算」會抓到擂台賽那筆，年份 2025 還比正版新，直接指錯。
_TUA_ALIAS = re.compile(r"^tua-guidelines?-(\d{4})$")
_TUA_TITLE = re.compile(r"TUA\s*治療指引\s*(\d{4})")
_TUA_HREF = re.compile(r"/announcement/(\d+)-([^/?#]+)")


def _resolve_tua() -> Guideline:
    resp = get(TUA_LIST_URL)
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    best_year = 0
    best_href = ""
    seen = 0
    for link in soup.select("a[href*='/announcement/']"):
        href = str(link.get("href", ""))
        matched = _TUA_HREF.search(href)
        if not matched:
            continue
        seen += 1
        alias = matched.group(2)
        title = clean_text(link.get_text(" "))
        year = _TUA_ALIAS.match(alias) or _TUA_TITLE.search(title)
        if not year:
            continue
        value = int(year.group(1))
        if value > best_year:
            best_year, best_href = value, href

    if seen < 50:
        # 一次抓全部應該有好幾百筆；只剩個位數代表 limit=0 失效或版型改了
        raise SourceError("公告列表只解析到 {} 筆，`limit=0` 可能已失效".format(seen))
    if not best_href:
        raise SourceError("公告列表裡找不到「TUA治療指引 <年份>」這樣的項目")

    return Guideline(
        key="tua",
        label="TUA guideline",
        full_name="台灣泌尿科醫學會 治療指引",
        url=urljoin(TUA_BASE, best_href),
        version=str(best_year),
        resolved=True,
    )


# --------------------------------------------------------------------------
# AUA —— 美國泌尿科醫學會（索引頁型，索引頁上有各份指引的年度）
# --------------------------------------------------------------------------
AUA_URL = FALLBACKS["aua"]
# 索引頁會列出最近發布的指引，寫法固定是「<疾病>: AUA Guideline (2026)」，
# 也有 AUA 與其他學會合訂的「AUA/SUO Guideline (2026)」。取所有出現年份的最大值
# ＝目前最新一份指引的年度。
_AUA_YEAR = re.compile(r"AUA(?:/[A-Z]{2,6})?\s+Guideline\s*\((\d{4})\)")
# 索引頁本身的分類連結（Oncology / Non-Oncology / …）。這些不見了就是改版。
_AUA_SECTION = "a[href*='/guidelines-and-quality/guidelines/']"


def _resolve_aua() -> Guideline:
    resp = get(AUA_URL)
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    sections = {
        str(a.get("href", "")) for a in soup.select(_AUA_SECTION) if a.get("href")
    }
    if len(sections) < 3:
        raise SourceError("索引頁上找不到 guideline 分類連結，版型可能已改")

    text = soup.get_text(" ")
    years = [int(y) for y in _AUA_YEAR.findall(text)]
    return Guideline(
        key="aua",
        label="AUA guideline",
        full_name="American Urological Association 美國泌尿科醫學會 指引",
        url=AUA_URL,
        # 抓不到年份不算失敗：按鍵照樣指向索引頁，只是不顯示年度。
        # 索引頁型的網址本來就不會換，年度純粹是給人看的資訊。
        version=str(max(years)) if years else "",
        resolved=True,
    )


# --------------------------------------------------------------------------
# EAU —— 歐洲泌尿科醫學會（索引頁型，索引頁沒有版本標示）
# --------------------------------------------------------------------------
EAU_URL = FALLBACKS["eau"]
# 索引頁是 21 個疾病主題的清單（Prostate Cancer / Urolithiasis / …），
# 頁面上**沒有任何年度或版本字樣**（2026-08-25 實測）。所以：
#   ・結構檢查 = 主題連結還在不在
#   ・年度 = 隨便挑一個主題內頁去讀，正文開頭寫著「This 2026 PCa Guidelines …」
_EAU_TOPIC = "a[href*='/guidelines/']"
# 挑攝護腺癌當版本探針：它是 EAU 最大的一份、每年必更新，不太可能被下架。
EAU_VERSION_PROBE = "https://uroweb.org/guidelines/prostate-cancer"
# 只認「This <年份> … Guidelines」這種句型。內文同一句還會提到上一版的年份
#（「This 2026 PCa Guidelines present a limited update of the 2025 …」），
# 所以不能在整段裡撈最大／最小值，要錨在 This 後面第一個年份。
_EAU_EDITION = re.compile(r"\bThis\s+(20\d{2})\s+[^.]{0,60}?Guidelines\b")


def _eau_version() -> str:
    """從一個主題內頁讀年度。**失敗一律回空字串，不拋例外** ——

    這是純加值資訊（按鍵上多顯示一個年度），不該有能力讓整顆按鍵判定為解析失敗。
    索引頁的網址本來就不會換，年度抓不到並不影響按鍵能不能用。
    """
    try:
        resp = get(EAU_VERSION_PROBE)
    except SourceError:
        return ""
    resp.encoding = resp.apparent_encoding or "utf-8"
    matched = _EAU_EDITION.search(resp.text)
    return matched.group(1) if matched else ""


def _resolve_eau() -> Guideline:
    resp = get(EAU_URL)
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    topics = {str(a.get("href", "")) for a in soup.select(_EAU_TOPIC) if a.get("href")}
    if len(topics) < 10:
        raise SourceError(
            "索引頁只找到 {} 個主題連結（實測應有 21 個），版型可能已改".format(len(topics))
        )

    return Guideline(
        key="eau",
        label="EAU guideline",
        full_name="European Association of Urology 歐洲泌尿科醫學會 指引",
        url=EAU_URL,
        version=_eau_version(),
        resolved=True,
    )


# --------------------------------------------------------------------------
# 骨架：三支 adapter 共用同一套「解析→失敗退回 fallback」流程
# --------------------------------------------------------------------------
@dataclass
class _Spec:
    key: str
    label: str
    full_name: str
    resolve: Callable[[], Guideline]
    order: int = 0
    notes: List[str] = field(default_factory=list)


SPECS = [
    _Spec("tua", "TUA guideline", "台灣泌尿科醫學會 治療指引", _resolve_tua),
    _Spec(
        "aua",
        "AUA guideline",
        "American Urological Association 美國泌尿科醫學會 指引",
        _resolve_aua,
    ),
    _Spec(
        "eau",
        "EAU guideline",
        "European Association of Urology 歐洲泌尿科醫學會 指引",
        _resolve_eau,
    ),
]


def resolve_all() -> (List[Guideline], List[str]):
    """解析三顆按鍵。回傳 (guidelines, 錯誤訊息)。

    任一顆解析失敗都只影響那一顆 —— 它退回 fallback 網址並記一條錯誤，
    其他兩顆照常。整份 guidelines.json 永遠是三顆齊全的，站上不會少一顆按鍵。
    """
    results: List[Guideline] = []
    errors: List[str] = []
    for spec in SPECS:
        try:
            results.append(spec.resolve())
        except Exception as exc:  # noqa: BLE001 - 單顆失敗不影響其他顆
            results.append(
                Guideline(
                    key=spec.key,
                    label=spec.label,
                    full_name=spec.full_name,
                    url=FALLBACKS[spec.key],
                    resolved=False,
                    note="自動解析失敗，顯示的是上次驗證過的連結",
                )
            )
            errors.append("{}：{}".format(spec.label, exc))
    return results, errors
