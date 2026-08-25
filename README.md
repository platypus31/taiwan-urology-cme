# 泌尿科 繼續教育活動彙整

[![更新活動資料](https://github.com/platypus31/taiwan-urology-cme/actions/workflows/update.yml/badge.svg)](https://github.com/platypus31/taiwan-urology-cme/actions/workflows/update.yml)
[![CI](https://github.com/platypus31/taiwan-urology-cme/actions/workflows/ci.yml/badge.svg)](https://github.com/platypus31/taiwan-urology-cme/actions/workflows/ci.yml)

把台灣泌尿科醫學會公告的積分課程抓下來，變成一頁可以用**時間／地區／積分／主題／主辦／來源**篩選的清單。
純靜態網站，資料存成一份 JSON，靠 GitHub Actions 每天自動更新，沒有伺服器也沒有資料庫。

> 資料只是彙整索引，**報名與積分認定一律以主辦單位公告為準**。

## 網站長怎樣

- 上方是統計（幾場活動、日期範圍、這些課加起來有幾點、最後更新時間）
- 中間是六組篩選器（時間／地區／積分／主題／主辦／來源）+ 關鍵字搜尋 + 三種排序
- 下面是活動卡片，點標題直接連到學會的原始公告頁，一鍵加進 Google 日曆
- 手機上篩選器預設收起來，第一屏就看得到活動

卡片上會標的東西：泌尿科點數（還沒核定的標「積分申請中」）、**另外還能拿的其他科積分**、
地區、可不可以線上參加、次專科主題、有沒有錄影。

## 積分是什麼

專科醫師證書更新（展延）要在**六年內累積繼續教育積分 108 點以上**，
出處是學會的[繼續教育積分授予辦法](https://www.tua.org.tw/tua/tw/specialist-of-urology/points)。
同一份辦法也寫了各種取得方式的點數（年會 16 點、半年會 10 點、區域月／季會每次 2 點、
網路繼續教育依影片長度 0.5～2 點且上限 30 點……）。

這個站只做一件事：把「哪一天、在哪裡、有幾點」攤開來讓人挑，**不做點數試算**。
點數的最終認定在學會，站上顯示的是公告當下的值。

## 資料從哪來

| 來源 | 狀態 | 說明 |
|------|------|------|
| [台灣泌尿科醫學會 E-School 會議列表](https://eschool.tua.org.tw/conference/list) | ✅ 已接 | 唯一也是最完整的來源。**任何單位**（他科學會、醫院、藥廠）只要替課程申請泌尿科積分就會登記在這張表，所以不必逐一去爬各子學會的網站 |
| [學會官網「活動資訊」](https://www.tua.org.tw/tua/tw/latest-news/events) | 🟡 已知缺口 | 少數課程只發在這裡。實例：2026 進階課程「攝護腺肥大 MIST 治療大體實作課程」（8/21）在 E-School 的 8 月列表查不到。但這一頁多半是徵稿通知／週報／合格名單，而且列的是**發佈日期不是上課日期**，上課日埋在內文各種寫法裡 —— 為了少數幾筆讓整條管線變脆不划算，先記著 |
| 年會／半年會專屬網站 | ⛔ 決定不接 | 年會有自己的網站與議程系統。E-School 會把年會的**每一個議程**（Podium／Symposium／海報）都列成一列，兩天就有 88 筆，那些不能單獨報名也不單獨給積分 —— 收進來只會把清單洗掉 |

### 為什麼「積分欄有沒有寫泌尿科」是收錄門檻

E-School 的列表同時裝了兩種東西：**可以單獨報名的課程**，和**年會的議程項目**。
兩者長得很像，但議程項目的積分欄是空的，而「主辦／主持人」欄放的是主持人的姓名。

所以 `sources/base.py` 的 `has_urology_credits()` 就是那道門：積分欄有提到「泌尿科」才收。
一條規則同時解決三件事 —— 擋掉 88 筆議程、擋掉他科課程、也避免把個人姓名當主辦單位登在公開網站上。

「泌尿科(申請中)」**要收**：學會的區域月會半年前就掛上來、點數還沒核，
而那正是需要提前排時間的課。這種場次會標成「積分申請中」，不會被當成 0 點。

## 怎麼加新來源

**一個來源 = 一支獨立檔案**，加來源不用動前端也不用動排程。

1. 在 `sources/` 底下新增一支 `xxx.py`，裡面要有：
   - `NAME`：學會名稱（會顯示在網站的來源篩選器上）
   - `fetch()`：回傳 `list[Event]`
2. 把它加進 `scripts/build.py` 最上面的 `SOURCES` 清單
3. 跑 `python3 scripts/build.py --dry-run` 確認抓得到

`Event` 的欄位、地區判定、積分解析、分類判定全部在 `sources/base.py`，新來源直接拿來用：

```python
from .base import Event, get, parse_date, parse_credits, detect_region, detect_categories
```

## 動手改之前要知道的三件事

1. **時間基準一律台灣（+08:00），不看機器時區**。`sources/base.py` 的 `TAIPEI` / `today_taipei()`
   是唯一權威。這不是潔癖：Actions runner 跑在 UTC，排程台灣 06:00 ＝ UTC 前一天 22:00，
   用 runner 日期判斷「過期」會整整差一天、把當天的課砍掉。前端 `todayISO()` 同理。
2. **積分只從「會議積分」欄的「泌尿科」那一段抓，不從標題猜**。同一格裡常常有別科的點數
   （`泌尿科(1.5點) ,婦產科,內科,家醫科3點`），在整串裡找數字會抓到 3 點。
3. **日期欄只有 MM-DD，年份來自 `display_date` 這個查詢參數**，不在頁面文字裡。
   跨年的多日活動由 `eschool._resolve_date()` 補正。

改完請跑 `python3 scripts/selftest.py` —— 上面三件事都在裡面有測試案例。

## 本機怎麼跑

```bash
pip install -r requirements.txt
python3 scripts/selftest.py       # 解析規則自我測試（不連網）
python3 scripts/build.py          # 抓資料 → data/events.json
python3 -m http.server 8899       # 開 http://127.0.0.1:8899
```

只想看抓到什麼、不想寫檔：`python3 scripts/build.py --dry-run`
上架前的個資檢查：`bash scripts/pii-scan.sh --all`（連 git 歷史與 commit 訊息一起掃）

### 個資閘門的設計（`scripts/pii-scan.sh`）

這支腳本自己也會被公開，所以**裡面不寫任何人的真名或信箱** ——
「掃描規則」本身就是一條外洩管道，而且它會通過自己的檢查。
因此它只掃**形狀**：信箱樣式、家目錄絕對路徑、常見 API 金鑰與 token 前綴、授權標頭、身分證字號樣式、電話。
實際的樣式清單直接看 `scripts/pii-scan.sh` 開頭的 `PII_PATTERNS`（**文件裡刻意不抄那些字面值** ——
寫進 README 會讓 README 自己被閘門判成命中）。

針對特定人名的規則放在 `.pii-local`（已列進 `.gitignore`，一行一個 regex）。
本機跑會自動載入並提示；CI 上沒有那個檔，就只跑形狀規則。
⚠️ 代價是**人名類個資 CI 擋不住**，上架或大改動前請務必本機跑一次 `--all`。

## 自動更新

`.github/workflows/update.yml` 每天台灣時間 06:00 跑一次，有變動才 commit
（也可以到 Actions 頁面按 **Run workflow** 手動觸發）。
`ci.yml` 則在每次 push／PR 跑自我測試與個資掃描，**刻意不連外網** ——
PR 的成敗不該取決於學會網站當下通不通。

## 部署到 GitHub Pages

Settings → Pages → Source 選 **Deploy from a branch**，branch 選 `main`、資料夾選 `/ (root)`，存檔即可。

## 來源掛掉會怎樣

不會整包壞掉，也不會把網站洗成 0 筆。三層防線，針對的是同一種失敗：**資料默默停止更新，畫面上卻看不出來**。

1. **抓到 0 筆一律當失敗**（不管來源有沒有丟例外）。來源改版時最常見的樣子是
   HTTP 200、HTML 解析成功、只是選擇器對不上 —— 沒有任何例外可抓。
2. **失敗時保留既有活動資料，但把錯誤訊息換成這次的**，並在網站頂部跳一條
   「顯示的是 ⋯⋯ 的舊資料」。`updated_at` 刻意不更新 —— 那個欄位的意思是「資料有多新」。
3. **解析層自己會喊**：表格不見、或「有列卻一筆都解不出來」都會發 warning 寫進
   `errors` 欄位。部分來源失敗時其他來源照常更新。

## 檔案結構

```
sources/base.py      共用資料結構與判定邏輯（積分、地區、線上、分類、日期）
sources/eschool.py   台灣泌尿科醫學會 E-School 會議列表
scripts/build.py     跑所有來源 → 合併去重 → 寫出 data/events.json
scripts/selftest.py  解析規則自我測試（不連網，CI 會跑）
scripts/pii-scan.sh  個資閘門（工作區＋可選 git 歷史）
data/events.json     網站唯一的資料來源（自動產生，不要手改）
index.html           頁面結構
assets/style.css     樣式
assets/app.js        篩選與排序（原生 JS，沒有框架）
```

## 授權

MIT，見 `LICENSE`。
