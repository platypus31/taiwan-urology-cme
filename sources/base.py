"""共用資料結構與解析工具。

每個來源（sources/*.py）只負責「把該學會的網頁變成 Event 清單」，
其餘工作（地區判定、積分解析、去重、輸出 JSON）全部集中在這裡，
所以之後要加新來源，只要寫一支新的 fetch() 就好。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT = 30


# --------------------------------------------------------------------------
# 資料結構
# --------------------------------------------------------------------------
@dataclass
class Event:
    """一筆繼續教育活動。所有來源都必須產出這個形狀。"""

    date: str  # 開始日，ISO 格式 YYYY-MM-DD
    title: str
    end_date: str = ""  # 多日活動的結束日；單日留空
    time: str = ""  # 「09:00 ~ 17:50」原文，來源沒寫就留空
    organizer: str = ""
    location: str = ""
    credits: Optional[float] = None  # 泌尿科積分（點）。抓不到或申請中都是 None
    credits_raw: str = ""  # 積分欄位原文，含外科／機泌等其他科別
    credits_pending: bool = False  # 泌尿科積分「申請中」
    region: str = "其他"  # 由 location 推導
    source: str = ""  # 學會名稱
    url: str = ""
    categories: List[str] = field(default_factory=list)
    online: bool = False  # 可線上參加（含「實體＋線上」的混合場）
    badges: List[str] = field(default_factory=list)  # 來源標的小圖示，例如「有錄影」

    def to_dict(self) -> dict:
        return asdict(self)


# 這個站的「今天」一律是台灣的今天。
#
# 不能用機器的本地時間：GitHub Actions 的 runner 跑在 UTC，排程是台灣 06:00
# （UTC 前一天 22:00），用 runner 的日期會整整差一天，把當天的活動誤判成過期。
# 台灣沒有日光節約時間，固定 +08:00 就夠，不需要 tzdata。
TAIPEI = timezone(timedelta(hours=8))

# 保留過去幾天的活動。過期的課程不要出現在站上，所以是 0。
# 定義在這裡而不是 build.py，是為了讓「來源層自己過濾」與「彙整層過濾」用同一個下界。
KEEP_PAST_DAYS = 0


class SourceError(Exception):
    """單一來源抓取失敗。build.py 會記錄並繼續跑其他來源。"""


# 「有抓到東西，但不完整」的情況（例如頁數超過安全上限被截斷）。
# 這種事最怕默默發生 —— 資料看起來正常、只是變少，沒人會發現。
# 所以一律收集起來交給 build.py 寫進 events.json，讓網站頂端顯示出來。
_WARNINGS: List[str] = []


def warn(message: str) -> None:
    _WARNINGS.append(message)


def drain_warnings() -> List[str]:
    """取出並清空目前累積的警告（build.py 每跑完一個來源呼叫一次）。"""
    global _WARNINGS
    collected, _WARNINGS = _WARNINGS, []
    return collected


def get(url: str, **kwargs) -> requests.Response:
    """帶 UA 與 timeout 的 GET，失敗轉成 SourceError。"""
    try:
        resp = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, **kwargs
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise SourceError("GET {} 失敗: {}".format(url, exc)) from exc
    return resp


# --------------------------------------------------------------------------
# 積分解析
# --------------------------------------------------------------------------
# 泌尿科的積分不是從標題猜的，是學會在「會議積分」欄位裡明寫的，例如：
#
#     泌尿科(3.5點)
#     泌尿科(1點)、外科積分(1點)
#     泌尿科：0.5點、、衛福部－品質感染：2分
#     泌尿科(1.5點) ,婦產科,內科,家醫科3點,藥師 (學分申請中)
#     泌尿科(申請中)、外科積分(申請中)
#
# 所以一律鎖定「泌尿科」這三個字後面緊接的數字，**不要**在整串裡找數字 ——
# 最後兩個例子裡的「家醫科3點」「外科積分(2點)」都不是泌尿科的點數，
# 用寬鬆的規則會把它們當成泌尿科積分（已用實際資料驗證會誤抓）。
_CREDIT_UROLOGY = re.compile(r"泌尿科\s*[（(：:]?\s*(\d+(?:\.\d+)?)\s*點")
# 「泌尿科(申請中)」「泌尿科(積分申請中)」—— 課是真的，只是點數還沒核下來。
# 這種要照實顯示「申請中」，不能當成沒積分丟掉：學會的區域月會半年份都長這樣，
# 而那正是要提前排時間的課。
_CREDIT_PENDING = re.compile(r"泌尿科\s*[（(：:]?\s*[^)）、,，]{0,6}?申請中")


def parse_credits(text: str) -> Optional[float]:
    """從「會議積分」欄位抽出泌尿科點數；抽不到回 None（前端顯示為未標示／申請中）。"""
    if not text:
        return None
    match = _CREDIT_UROLOGY.search(text)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    # 單場繼續教育積分極少超過 20 點（年會 16 點是上限級距），超出視為誤抓
    if 0 < value <= 20:
        return value
    return None


def credits_pending(text: str) -> bool:
    """泌尿科積分是否為「申請中」。"""
    if not text:
        return False
    return bool(_CREDIT_PENDING.search(text))


def has_urology_credits(text: str) -> bool:
    """這筆有沒有掛泌尿科積分（含申請中）。

    這是本站的收錄門檻：來源列表裡也放年會的個別議程（Podium／Symposium／海報），
    那些是大會議程的一部分、不能單獨報名也不單獨給積分，積分欄位是空的。
    用「積分欄位有沒有提到泌尿科」當閘門，可以一次擋掉它們，
    順帶避免把議程主持人的姓名當成主辦單位列出來。
    """
    return bool(text) and "泌尿科" in text


# --------------------------------------------------------------------------
# 地區判定
# --------------------------------------------------------------------------
_ONLINE_KEYWORDS = [
    "線上",
    "視訊",
    "遠距",
    "webex",
    "zoom",
    "google meet",
    "meet.google",
    "teams",
    "youtube",
    "直播",
    "雲端",
]

_REGION_MAP = [
    ("北部", ["台北", "臺北", "新北", "基隆", "桃園", "新竹", "宜蘭", "羅東"]),
    ("中部", ["台中", "臺中", "苗栗", "彰化", "南投", "雲林", "竹山", "斗六", "員林"]),
    ("南部", ["高雄", "台南", "臺南", "嘉義", "屏東", "澎湖"]),
    ("東部", ["花蓮", "台東", "臺東"]),
    ("離島", ["金門", "馬祖", "連江", "綠島", "蘭嶼"]),
]

# 地點只寫「某某醫院會議室」沒寫縣市時的補救對應。
# 刻意只收「單一院區、不會認錯」的機構 —— 長庚／榮總／馬偕這種多院區的一律不放，
# 寧可落在「其他」也不要標錯地區（標錯比沒標更糟，使用者會白跑一趟）。
_INSTITUTION_MAP = [
    ("北部", ["台大醫院", "臺大醫院", "三軍總醫院", "萬芳醫", "新光吳火獅", "亞東醫", "國泰綜合醫"]),
    ("中部", ["中國醫藥大學", "中山醫學", "若瑟醫"]),
    ("南部", ["成大醫", "成功大學醫學", "奇美醫", "安泰醫", "高雄醫學大學"]),
]

# 地點還沒定案時來源會直接寫 TBD（區域月會提前半年就掛上來，場地當然還沒訂）。
_TBD_MARKERS = ["tbd", "待定", "未定", "另行公告"]


def is_tbd(location: str) -> bool:
    place = (location or "").strip().lower()
    if not place:
        return False
    return any(marker in place for marker in _TBD_MARKERS)


def detect_region(location: str, organizer: str = "") -> str:
    """由地點判斷地區。線上優先（線上課程沒有地理限制，是獨立篩選軸）。

    刻意不看標題：標題裡的關鍵字多半是課程**主題**而非上課地點
    （實例：「2026台東家庭醫學週末研討會」辦在台東沒問題，
    但「泌尿道結石與男性性腺功能低下」這種標題完全推不出地點）。
    地點沒寫縣市時（例如只寫「B1 第一會議室」）才退而用主辦單位推斷。
    """
    place = (location or "").lower()
    if is_tbd(place):
        return "其他"
    for keyword in _ONLINE_KEYWORDS:
        if keyword in place:
            return "線上"
    for blob in (place, (organizer or "").lower()):
        for region, keywords in _REGION_MAP:
            for keyword in keywords:
                if keyword in blob:
                    return region
    for blob in (place, (organizer or "").lower()):
        for region, keywords in _INSTITUTION_MAP:
            for keyword in keywords:
                if keyword.lower() in blob:
                    return region
    return "其他"


def detect_online(title: str, location: str) -> bool:
    """能不能線上參加。

    跟 detect_region 的分工：region 回答「人要去哪裡」，這個回答「不到現場行不行」。
    兩者要分開，因為來源有一整類「實體＋【線上】」的混合場 ——
    地點是實體會場（region 該是北部），但同時開線上，值班走不開的人也能參加。

    這裡**看標題**是刻意的，跟 detect_region 的規則相反：來源在標題前面用
    【線上】【🎬線上】「實體+【🎬線上】」當結構化標記，不是在講課程主題。
    """
    marker = re.search(r"[【\[]([^】\]]*)[】\]]", title or "")
    if marker and any(k in marker.group(1).lower() for k in ("線上", "直播", "視訊")):
        return True
    return any(k in (location or "").lower() for k in _ONLINE_KEYWORDS)


# --------------------------------------------------------------------------
# 分類判定
# --------------------------------------------------------------------------
# 泌尿科次專科軸。關鍵字取自實際抓到的活動標題（中英夾雜是這個科的常態，
# 藥廠場次幾乎全英文），所以每一類中英文都要放。
#
# blob 會先轉小寫再比對，**英文關鍵字一律寫小寫**，寫成大寫永遠比不到。
_CATEGORY_MAP = [
    (
        "泌尿腫瘤",
        [
            "腫瘤", "癌", "oncolog", "tumor", "cancer", "carcinoma", "prostate",
            "攝護腺", "前列腺", "psma", "mcrpc", "mhspc", "mcspc", "nmibc", "mibc",
            "urothelial", "膀胱癌", "腎細胞", "renal cell", "rcc", "睪丸癌",
            "adt", "arpi", "bcg", "theranostic",
        ],
    ),
    (
        "排尿功能與婦女泌尿",
        [
            "bph", "攝護腺肥大", "良性攝護腺", "luts", "下泌尿道症狀", "排尿",
            "尿失禁", "incontinence", "膀胱過動", "oab", "overactive",
            "尿路動力學", "urodynamic", "骨盆", "pelvic", "神經性膀胱",
            "neurogenic bladder", "mist", "urolift", "rezum", "aquablation",
            "gsm", "menopause", "更年期",
        ],
    ),
    (
        "結石與內視鏡",
        [
            "結石", "stone", "urolithiasis", "碎石", "eswl", "pcnl", "rirs",
            "ureteroscop", "輸尿管鏡", "endourology", "內視鏡", "flexible uretero",
        ],
    ),
    (
        "男性學與性功能",
        [
            "男性學", "andrology", "男性健康", "male health", "male infertility",
            "性功能", "勃起", "erectile", "早洩", "睪固酮", "testosterone",
            "性腺功能低下", "hypogonadism", "不孕", "infertility", "生育力",
            "荷爾蒙", "hormone", "男性重建",
        ],
    ),
    (
        "機器手臂與微創",
        [
            "機器手臂", "機械手臂", "達文西", "davinci", "da vinci", "robotic",
            "腹腔鏡", "laparoscop", "single-port", "single port", "微創",
            "minimal-invasive", "minimal invasive", "minimally invasive", "機泌",
        ],
    ),
    ("腎臟移植", ["移植", "transplant", "供腎", "donor", "免疫抑制"]),
    (
        "感染與性傳染病",
        [
            "感染", "infection", "uti", "泌尿道感染", "性傳染", "std", "sti",
            "hiv", "愛滋", "梅毒", "syphilis", "淋病", "gonorrhea", "prep",
            "肝炎", "hepatitis", "友善門診",
        ],
    ),
    (
        "小兒泌尿",
        [
            "小兒", "兒童", "pediatric", "paediatric", "尿道下裂", "hypospadias",
            "upj", "腎水腫", "hydronephrosis", "夜尿", "vur",
        ],
    ),
    (
        "教育訓練與研究",
        [
            "住院醫師", "resident", "核心訓練", "workshop", "工作坊", "研習",
            "大體", "cadaver", "實作", "hands-on", "guideline", "指引",
            "sci", "論文", "research", "共識", "consensus",
        ],
    ),
]


def detect_categories(title: str, extra: str = "") -> List[str]:
    """依關鍵字標記分類，可多標。全都不中就不標（前端顯示為「其他」）。"""
    blob = "{} {}".format(title or "", extra or "").lower()
    hits = []
    for category, keywords in _CATEGORY_MAP:
        for keyword in keywords:
            if keyword.lower() in blob:
                hits.append(category)
                break
    return hits


# --------------------------------------------------------------------------
# 日期解析
# --------------------------------------------------------------------------
# (?<!\d) 是必要的數字邊界：沒有它，民國年那條會從「2026.08.22」的後三碼
# 抓出「026」再 +1911 變成 1937 年。
_DATE_PATTERNS = [
    re.compile(r"(?<!\d)(\d{4})[/\-.年](\d{1,2})[/\-.月](\d{1,2})"),
    # 民國年。分隔符含「年/月」，因為學會網站常寫成「115年08月22日」或「115.08.22」
    re.compile(r"(?<!\d)(\d{3})[/\-.年](\d{1,2})[/\-.月](\d{1,2})"),
]


def parse_date(text: str) -> Optional[str]:
    """解析日期成 ISO 字串。支援西元與民國年（3 位數自動 +1911）。"""
    if not text:
        return None
    cleaned = unicodedata.normalize("NFKC", text)
    for pattern in _DATE_PATTERNS:
        match = pattern.search(cleaned)
        if not match:
            continue
        year, month, day = (int(g) for g in match.groups())
        if year < 1911:  # 民國年
            year += 1911
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            continue
    return None


def clean_text(text: str) -> str:
    """壓掉多餘空白與全形空格。"""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.replace("　", " ")).strip()


def strip_prefix(text: str, *prefixes: str) -> str:
    """去掉「主辦：」「地點：」這類前綴。"""
    result = clean_text(text)
    for prefix in prefixes:
        for sep in ("：", ":"):
            token = prefix + sep
            if result.startswith(token):
                result = result[len(token) :].strip()
    return result


def primary_organizer(text: str) -> str:
    """把「主辦單位：A、B 協辦單位：C」收斂成「A、B」。

    來源的主辦欄有兩種寫法（有沒有「主辦單位：」前綴都有），而且常把協辦單位
    接在同一格裡 —— 協辦多半是藥廠，掛在主辦欄會讓篩選器長出一堆廠商名字，
    也讓卡片上的主辦欄變成三行。這裡只留主辦。
    """
    result = clean_text(text)
    if not result:
        return ""
    result = re.sub(r"^主辦(?:單位)?\s*[：:]\s*", "", result)
    result = re.split(r"協辦(?:單位)?\s*[：:]", result)[0]
    return clean_text(result)


def today_taipei() -> date:
    """台灣的今天。所有日期比較都從這裡出發，不看機器時區。"""
    return datetime.now(TAIPEI).date()


def today_iso() -> str:
    return today_taipei().isoformat()


def cutoff_iso() -> str:
    """資料保留下界：早於這天的活動一律不收。

    來源層若要自己過濾過期活動，必須用這個函式而不是 today_iso()，
    否則 build.py 的 KEEP_PAST_DAYS 對該來源會失效 ——
    資料看起來正常，只是跟彙整層對不上。
    """
    return (today_taipei() - timedelta(days=KEEP_PAST_DAYS)).isoformat()
