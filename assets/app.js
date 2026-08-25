/* 讀 data/events.json，做多軸篩選（時間／地區／積分／主題／主辦／來源）與排序。
   全部在瀏覽器端跑，沒有後端。資料量幾百筆等級，直接全量過濾就夠快。

   資料有兩種 kind，在站上以 tag 呈現並用「分類」篩選器切換：
   cme→「上課」（可拿泌尿科積分的課），meeting→「開會」（各次專科學會的開會時間）。
   tag 由 sources/base.py 的 KIND_TAGS 從 kind 投影出來，不是另一份資料。 */
(function () {
  "use strict";

  var DATA_URL = "data/events.json";
  var GUIDELINES_URL = "data/guidelines.json";

  /* 分類標籤。**一個頁面服務兩種受眾**（站主 2026-08-25：「這樣住院醫師還有主治醫師
     都可以用同一個頁面」）—— 住院醫師篩「上課」，主治醫師篩「開會」，各看各的。
     刻意不做成兩個分頁：分頁一定有一個是預設，另一種受眾第一眼就看到不是自己要的東西。
     篩選器的預設是「全部」，兩邊都看得到。 */
  var TAG_CME = "上課";
  var TAG_MEETING = "開會";
  var TAG_HINTS = {};
  TAG_HINTS[TAG_CME] = "台灣泌尿科醫學會公告、掛有泌尿科積分的課程（住院醫師的積分來源）。";
  TAG_HINTS[TAG_MEETING] =
    "泌尿內視鏡醫學會（TEA）、泌尿腫瘤醫學會（TUOA）、高杏泌尿照護協會的開會時間。用途是提前排行程，跟積分無關。";
  var REGION_ORDER = ["北部", "中部", "南部", "東部", "離島", "線上", "其他"];
  var DOW = ["日", "一", "二", "三", "四", "五", "六"];

  var ORG_TUA = "泌尿科醫學會";
  var ORG_HOSPITAL = "醫院／院所";
  var ORG_PHARMA = "藥廠／廠商";
  var ORG_OTHER = "其他主辦";
  var ORG_NONE = "未標示";

  var state = {
    events: [],
    data: {},
    tag: null, // null = 全部（預設，見 TAG_HINTS 上面的註解）
    q: "",
    // 預設「全部」而不是「即將舉行」：積分課程的資料源頭就不收過期的，兩者對它完全等價；
    // 但學會會議刻意留著兩年份歷史，用「即將舉行」當預設會讓主治醫師第一眼看到空清單。
    time: "all",
    region: null,
    credit: 0,
    category: null,
    source: null,
    organizer: null,
    sort: "date-asc"
  };

  var el = {
    list: document.getElementById("list"),
    empty: document.getElementById("empty"),
    q: document.getElementById("q"),
    reset: document.getElementById("reset"),
    resultCount: document.getElementById("result-count"),
    notice: document.getElementById("notice"),
    filters: document.querySelector(".filters"),
    toggle: document.getElementById("toggle"),
    tagHint: document.getElementById("tag-hint"),
    creditRow: document.getElementById("row-credit"),
    guidelines: document.getElementById("guidelines"),
    guidelineNote: document.getElementById("guideline-note"),
    statCount: document.getElementById("stat-count"),
    statCountLabel: document.getElementById("stat-count-label"),
    statRange: document.getElementById("stat-range"),
    statSources: document.getElementById("stat-sources")
  };

  // ---------- 工具 ----------
  /** 這個站的「今天」一律是台灣的今天，不看使用者裝置的時區。
   *  人在國外或手機時區設錯時，「即將舉行」不該跟著跑掉。
   *  台灣沒有日光節約，固定 +08:00 即可。 */
  function todayISO() {
    var now = new Date();
    var taipei = new Date(now.getTime() + (now.getTimezoneOffset() + 480) * 60000);
    return [
      taipei.getFullYear(),
      String(taipei.getMonth() + 1).padStart(2, "0"),
      String(taipei.getDate()).padStart(2, "0")
    ].join("-");
  }

  function addDays(iso, n) {
    var d = new Date(iso + "T00:00:00");
    d.setDate(d.getDate() + n);
    return [
      d.getFullYear(),
      String(d.getMonth() + 1).padStart(2, "0"),
      String(d.getDate()).padStart(2, "0")
    ].join("-");
  }

  /** 活動的最後一天（單日活動就是當天）。多日活動跨過今天時還在進行中，
   *  「即將舉行」不能把它濾掉。 */
  function lastDay(e) {
    return e.end_date || e.date;
  }

  // updated_at 帶時區偏移（本機跑是 +08:00，GitHub Actions 跑是 +00:00）。
  // 直接切字串會讓 CI 產出的時間看起來早 8 小時、像是資料很舊，所以一律換算成台北時間。
  function formatUpdatedAt(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso).slice(0, 16).replace("T", " ");
    try {
      // 用 formatToParts 逐欄取值自己拼，不對 format() 的字串做正則替換 ——
      // 各瀏覽器 ICU 對 zh-TW 的輸出格式不一致（可能是 2026/08/17，也可能是 2026年08月17日），
      // 依賴字串長相會在某些裝置上顯示成沒被轉換的樣子。
      var parts = new Intl.DateTimeFormat("zh-TW", {
        timeZone: "Asia/Taipei",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23"
      }).formatToParts(d);
      var v = {};
      for (var i = 0; i < parts.length; i++) v[parts[i].type] = parts[i].value;
      if (!v.year || !v.month || !v.day || !v.hour || !v.minute) throw new Error("parts");
      var pad = function (s) {
        return String(s).padStart(2, "0");
      };
      // hourCycle h23 在少數舊 ICU 仍可能吐 24，正規化回 00
      var hour = pad(v.hour === "24" ? "0" : v.hour);
      return v.year + "-" + pad(v.month) + "-" + pad(v.day) + " " + hour + ":" + pad(v.minute);
    } catch (err) {
      return String(iso).slice(0, 16).replace("T", " ");
    }
  }

  /** 主辦單位正規化成可篩選的鍵。
   *
   *  原始 organizer 有幾十種寫法，直接列成篩選器沒人看得完，而且同一個學會
   *  會因為「社團法人」「中華民國」「臺／台」這些前綴變成好幾個不同項目。
   *  所以收斂成五類：學會（含 TUA 的各委員會）／醫院院所／藥廠廠商／其他／未標示。
   *  一筆活動可能有多個主辦單位（用、分隔），任一命中就算，所以回傳陣列。 */
  var PHARMA_HINTS = [
    "az", "ipsen", "astellas", "裕利", "阿斯特捷利康", "安斯泰來", "拜耳",
    "嬌生", "輝凌", "友華", "健喬信元", "吉立亞", "諾華", "默沙東", "羅氏"
  ];

  function normalizeOrg(name) {
    return String(name == null ? "" : name)
      // 來源網站打字時會夾雜空白，不清掉同一個學會會被拆成兩個篩選項目
      .replace(/\s+/g, "")
      .replace(/臺/g, "台")
      // 用 + 量詞讓字首可疊加剝除：「財團法人中華民國OO學會」要一路剝到 OO學會，
      // 只剝一次會讓同一個學會因為原始字串有沒有疊字首而落到兩個不同篩選鍵
      .replace(/^(?:社團法人|財團法人|醫療財團法人|中華民國|中華|台灣)+/, "");
  }

  function orgKey(part) {
    var name = normalizeOrg(part);
    if (!name) return "";

    // 學會的區域月會掛在各醫院名下，主辦欄寫成「萬芳醫院、TUA」；
    // TUA 的各委員會（TUA 泌腫委員會…）也是學會自己辦的，一律歸學會。
    if (/^tua/i.test(name) || /^泌尿科醫學會/.test(name)) return ORG_TUA;

    // 「醫會」也算：台灣男性重建外科醫會就是這樣命名的，漏掉它會被丟進「其他主辦」
    var society = name.match(/^.*?(學會|醫會|公會|協會)/);
    if (society) return society[0];

    // 基金會只認「整串就是一個基金會」的情況。不能用 /基金會/ 隨便比對：
    // 「醫療財團法人OO基金會XX紀念醫院」的基金會在字串中間，它實際上是醫院。
    if (/基金會$/.test(name)) return name;

    var lower = name.toLowerCase();
    for (var i = 0; i < PHARMA_HINTS.length; i++) {
      if (lower.indexOf(PHARMA_HINTS[i]) !== -1) return ORG_PHARMA;
    }
    if (/(公司|股份|製藥|生技|藥廠|醫藥)/.test(name)) return ORG_PHARMA;
    // 主辦欄常用口語簡稱（「台北榮總」「花蓮慈濟」「高醫大同」都沒有「醫院」兩個字），
    // 不列進來的話這些場次會全部掉進「其他主辦」，那顆 chip 就變成看不懂的雜物桶
    if (/(醫院|診所|醫療|大學|醫學院|醫學中心|榮總|慈濟|長庚|馬偕|奇美|高醫|台大|北醫|亞東|振興|國泰|新光|門諾|彰基)/.test(name)) {
      return ORG_HOSPITAL;
    }
    return ORG_OTHER;
  }

  function organizerKeys(e) {
    var raw = String(e.organizer == null ? "" : e.organizer).trim();
    if (!raw) return [ORG_NONE];

    var keys = [];
    // 只切實際觀察到的分隔符。斜線刻意不切 —— 機構名本身可能含「/」，
    // 切下去會生出兩個不存在的篩選鍵。
    raw.split(/[、,，]+/).forEach(function (part) {
      var key = orgKey(part);
      if (key && keys.indexOf(key) === -1) keys.push(key);
    });
    return keys.length ? keys : [ORG_NONE];
  }

  function escapeHTML(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ---------- 篩選 ----------
  /* 時間軸。兩種資料共用同一組選項（一個頁面、一套篩選器）。
     「已結束」只可能撈到學會會議 —— 積分課程的資料源頭就不收過期的課
     （KEEP_PAST_DAYS=0），而會議刻意留兩年份歷史
     （見 sources/base.py 的 MEETING_KEEP_PAST_DAYS 說明）：這些學會一年開一兩次會、
     官網多半開會前一兩個月才更新，上一場的日期就是排下一年的依據。 */
  var TIME_FILTERS = [
    { key: "all", label: "全部", test: function () { return true; } },
    { key: "upcoming", label: "即將舉行", test: function (e, t) { return lastDay(e) >= t; } },
    { key: "7", label: "近 7 天", test: function (e, t) { return lastDay(e) >= t && e.date <= addDays(t, 7); } },
    { key: "30", label: "近 30 天", test: function (e, t) { return lastDay(e) >= t && e.date <= addDays(t, 30); } },
    { key: "90", label: "近 3 個月", test: function (e, t) { return lastDay(e) >= t && e.date <= addDays(t, 90); } },
    { key: "past", label: "已結束", test: function (e, t) { return lastDay(e) < t; } }
  ];

  function tagsOf(e) {
    return e.tags && e.tags.length ? e.tags : [];
  }

  var CREDIT_FILTERS = [
    { key: 0, label: "不限" },
    { key: 1, label: "1 點以上" },
    { key: 2, label: "2 點以上" },
    { key: 3, label: "3 點以上" }
  ];

  var SORTS = [
    { key: "date-asc", label: "日期近→遠" },
    { key: "date-desc", label: "日期遠→近" },
    { key: "credit-desc", label: "積分高→低" }
  ];

  /** exceptAxis：計算篩選器上的數字時，要略過該軸自己的條件
   *  （否則點了「北部」之後，北部以外的地區數字全部變成 0）。
   *  渲染清單時不傳，就是全部條件都套。 */
  function applyFilters(exceptAxis) {
    var today = todayISO();
    var timeFilter = TIME_FILTERS.filter(function (f) { return f.key === state.time; })[0];
    var q = state.q.trim().toLowerCase();

    var rows = state.events.filter(function (e) {
      if (exceptAxis !== "tag" && state.tag && tagsOf(e).indexOf(state.tag) === -1) return false;
      if (exceptAxis !== "time" && timeFilter && !timeFilter.test(e, today)) return false;
      if (exceptAxis !== "region" && state.region && e.region !== state.region) return false;
      if (exceptAxis !== "source" && state.source && e.source !== state.source) return false;
      if (exceptAxis !== "organizer" && state.organizer &&
          organizerKeys(e).indexOf(state.organizer) === -1) return false;
      // 積分申請中的場次 credits 是 null，設了點數門檻就不該出現 ——
      // 它現在確實還沒有點數，硬算成 0 或硬留著都會讓「3 點以上」名不副實
      if (exceptAxis !== "credit" && state.credit > 0 && !(e.credits >= state.credit)) return false;
      if (exceptAxis !== "category" && state.category &&
          (e.categories || []).indexOf(state.category) === -1) return false;
      if (q) {
        var blob = [e.title, e.organizer, e.location, e.source].join(" ").toLowerCase();
        if (blob.indexOf(q) === -1) return false;
      }
      return true;
    });

    /* 已結束的一律沉到最底。
       兩種資料放在同一份清單之後這條就變成必要的：學會會議帶著兩年份歷史，
       純按日期升冪排的話第一屏會是 2024 年的舊會議，把使用者真正要看的
       「接下來有什麼」擠到看不見的地方。已結束的彼此之間用日期**降冪**
       （最近剛結束的排前面）—— 往回看的時候，越近的越有參考價值。 */
    var ended = {};
    rows.forEach(function (e) { ended[e.date + "|" + e.title] = lastDay(e) < today; });
    var isEnded = function (e) { return ended[e.date + "|" + e.title]; };

    rows.sort(function (a, b) {
      var ea = isEnded(a), eb = isEnded(b);
      if (ea !== eb) return ea ? 1 : -1;
      // 🔴 已結束的那一段要**排在所有排序模式之前**處理。放在 credit-desc 分支後面的話，
      // 使用者選「積分高→低」時已結束的會改以積分排序，跟上面那段註解承諾的
      // 「最近剛結束的排前面」對不起來（codex review 2026-08-25 抓到）。
      if (ea) return a.date < b.date ? 1 : a.date > b.date ? -1 : 0;
      if (state.sort === "credit-desc") {
        var ca = a.credits == null ? -1 : a.credits;
        var cb = b.credits == null ? -1 : b.credits;
        if (cb !== ca) return cb - ca;
        return a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
      }
      if (state.sort === "date-desc") return a.date < b.date ? 1 : a.date > b.date ? -1 : 0;
      return a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
    });

    return rows;
  }

  /** 「09:00 ~ 17:50」拆成 ["0900", "1750"]；格式不符回 null。 */
  function parseTimeRange(text) {
    var m = /(\d{1,2}):(\d{2})\s*[~～-]\s*(\d{1,2}):(\d{2})/.exec(String(text || ""));
    if (!m) return null;
    var pad = function (s) { return String(s).padStart(2, "0"); };
    return [pad(m[1]) + m[2] + "00", pad(m[3]) + m[4] + "00"];
  }

  /** 產生 Google 日曆的「新增活動」連結。
   *  單日且來源有寫起訖時間 → 建成有時間的行程（帶 ctz=Asia/Taipei，
   *  這樣人在國外開連結也不會被裝置時區平移）。
   *  多日或沒寫時間 → 整天事件（Google 全天事件的結束日要 +1 天）。 */
  function calendarURL(e) {
    var range = e.end_date ? null : parseTimeRange(e.time);
    var dates;
    if (range) {
      dates = e.date.replace(/-/g, "") + "T" + range[0] + "/" +
              e.date.replace(/-/g, "") + "T" + range[1];
    } else {
      dates = e.date.replace(/-/g, "") + "/" +
              addDays(e.end_date || e.date, 1).replace(/-/g, "");
    }

    var details = [
      e.organizer ? "主辦：" + e.organizer : "",
      e.credits_raw ? "積分：" + e.credits_raw : "",
      e.url ? "簡章與報名：" + e.url : "",
      "",
      range ? "" : "（時間為整天，實際起訖請看主辦單位公告）"
    ].filter(Boolean).join("\n");

    return "https://calendar.google.com/calendar/render?action=TEMPLATE" +
      "&text=" + encodeURIComponent(e.title) +
      "&dates=" + dates +
      "&ctz=Asia%2FTaipei" +
      "&location=" + encodeURIComponent(e.location || "") +
      "&details=" + encodeURIComponent(details);
  }

  /** 空清單時要說的話。
   *
   *  「學會會議 + 即將舉行 + 沒有其他篩選」這一格特別重要，而且是**常態不是例外**：
   *  三個學會加起來一年開不到十場，官網又多半在會前一兩個月才更新，
   *  所以大半年時間這一頁就是 0 筆。給一句「試著放寬篩選條件」等於什麼都沒說，
   *  使用者只會以為這個功能壞了。直接告訴他該按哪裡、以及為什麼值得按。 */
  function renderEmpty() {
    var pristine =
      !state.q.trim() && !state.region && !state.category &&
      !state.source && !state.organizer && !state.credit;
    if (state.tag === TAG_MEETING && state.time === "upcoming" && pristine) {
      // 🔴 這裡放一顆真的按鈕，不是寫「請按上面的已結束」——
      // 手機版（≤560px）的篩選器預設是收合的，時間那排 chip 根本看不到，
      // 指路的說明會指向一個使用者找不到的東西。按鈕在哪個版型都按得到。
      var past = applyFilters("time").filter(function (e) {
        return lastDay(e) < todayISO();
      }).length;
      el.empty.textContent =
        "這幾個學會的官網目前都還沒公布下一場。年會與半年會通常固定在同一個月份，" +
        "所以最近幾場的日期就是排行程的依據。";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "empty-action";
      btn.textContent = "看最近 " + past + " 場的日期";
      btn.addEventListener("click", function () {
        state.time = "past";
        render();
      });
      el.empty.appendChild(btn);
      return;
    }
    el.empty.textContent = "沒有符合條件的活動，試著放寬篩選條件。";
  }

  // ---------- 渲染 ----------
  function renderList(rows) {
    var today = todayISO();
    var soonLimit = addDays(today, 7);

    el.list.innerHTML = rows.map(function (e) {
      var parts = e.date.split("-");
      var dow = DOW[new Date(e.date + "T00:00:00").getDay()];
      var soon = e.date >= today && e.date <= soonLimit ? " soon" : "";
      var span = e.end_date
        ? '<div class="span">→ ' + escapeHTML(e.end_date.slice(5).replace("-", "/")) + "</div>"
        : "";

      var meta = [];
      if (e.time) meta.push("<span>時間：" + escapeHTML(e.time) + "</span>");
      if (e.organizer) meta.push("<span>主辦：" + escapeHTML(e.organizer) + "</span>");
      if (e.location) meta.push("<span>地點：" + escapeHTML(e.location) + "</span>");

      var tags = [];
      // 已結束的場次只會出現在「學會會議」分頁（積分課程過期就從資料裡消失了）。
      // 標出來是必要的：這一頁刻意留著歷史場次，不標的話跟即將舉行的混在一起會誤導。
      if (lastDay(e) < today) tags.push('<span class="tag past">已結束</span>');
      if (e.credits != null) tags.push('<span class="tag credit">' + e.credits + " 點</span>");
      else if (e.credits_pending) tags.push('<span class="tag pending">積分申請中</span>');
      // 「積分未標示」只對積分課程有意義。學會會議的來源根本不公告點數，
      // 每張卡都掛一個「未標示」等於在講一句廢話，還會讓人以為資料抓漏了。
      else if (tagsOf(e).indexOf(TAG_MEETING) === -1) tags.push('<span class="tag">積分未標示</span>');
      // 一場課常常同時給外科、機器手臂等其他科別的積分（「泌尿科(1點)、外科積分(2點)」）。
      // 把泌尿科那段從原文剪掉，剩下的就是「另外還能拿什麼」—— 這對之後要考外科的人
      // 不是裝飾，是實際會少拿的分。剪完是空的就不多長一顆重複的標籤。
      var otherCredits = String(e.credits_raw || "")
        .replace(/泌尿科\s*[（(：:]?\s*[^)）、,，]*[)）]?/, "")
        .replace(/^[、,，\s]+/, "")
        .trim();
      if (otherCredits) {
        tags.push('<span class="tag">另有 ' + escapeHTML(otherCredits) + "</span>");
      }
      tags.push('<span class="tag region">' + escapeHTML(e.region) + "</span>");
      if (e.online) tags.push('<span class="tag online">可線上參加</span>');
      (e.categories || []).forEach(function (c) {
        tags.push('<span class="tag">' + escapeHTML(c) + "</span>");
      });
      (e.badges || []).forEach(function (b) {
        tags.push('<span class="tag media">' + escapeHTML(b) + "</span>");
      });
      tags.push('<span class="tag source">' + escapeHTML(e.source) + "</span>");

      var title = e.url
        ? '<a href="' + escapeHTML(e.url) + '" target="_blank" rel="noopener">' + escapeHTML(e.title) + "</a>"
        : escapeHTML(e.title);

      return (
        '<article class="event">' +
          '<div class="date-badge' + soon + '">' +
            '<div class="md">' + parts[1] + "/" + parts[2] + "</div>" +
            '<div class="dow">週' + dow + "</div>" +
            '<div class="yr">' + parts[0] + "</div>" +
            span +
          "</div>" +
          '<div class="event-body">' +
            '<h2 class="event-title">' + title + "</h2>" +
            (meta.length ? '<div class="event-meta">' + meta.join("") + "</div>" : "") +
            '<div class="tags">' + tags.join("") + "</div>" +
            '<div class="actions">' +
              '<a class="cal" href="' + escapeHTML(calendarURL(e)) + '" target="_blank" rel="noopener">' +
                "加入 Google 日曆</a>" +
            "</div>" +
          "</div>" +
        "</article>"
      );
    }).join("");

    el.empty.hidden = rows.length > 0;
    if (!rows.length) renderEmpty();
    el.resultCount.textContent = "顯示 " + rows.length + " 場";
  }

  function chipButton(label, active, count) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip";
    btn.setAttribute("aria-pressed", active ? "true" : "false");
    btn.innerHTML = escapeHTML(label) + (count == null ? "" : ' <span class="n">' + count + "</span>");
    return btn;
  }

  function renderChips(containerId, items, isActive, onPick) {
    var box = document.getElementById(containerId);
    box.innerHTML = "";
    items.forEach(function (item) {
      var btn = chipButton(item.label, isActive(item), item.count);
      btn.addEventListener("click", function () {
        onPick(item);
        render();
      });
      box.appendChild(btn);
    });
  }

  /** 篩選器上的數字＝「按下去會看到幾筆」。
   *  所以要拿套過其他軸條件的結果來數，不能數全部資料 ——
   *  否則預設的「即將舉行」會讓數字比實際點下去多（含已結束的場次）。 */
  function countBy(pick, axis) {
    var counts = {};
    applyFilters(axis).forEach(function (e) {
      var values = pick(e);
      (Array.isArray(values) ? values : [values]).forEach(function (v) {
        if (v == null || v === "") return;
        counts[v] = (counts[v] || 0) + 1;
      });
    });
    return counts;
  }

  /** 目前選中的項目就算在其他條件下歸零也要留著，否則 chip 消失就沒得取消，
   *  使用者會卡在一個看不到出口的空清單（例：選了東部又選只在北部辦的學會）。 */
  function keepSelected(counts, selected) {
    if (selected != null && counts[selected] == null) counts[selected] = 0;
    return counts;
  }

  function renderFilters() {
    // 分類（上課／開會）。這是站主指定的那一軸：住院醫師篩「上課」、主治醫師篩「開會」。
    // 「全部」放第一個且是預設 —— 不預設濾掉其中一種，否則另一種受眾第一眼看到空頁。
    var tagCounts = keepSelected(countBy(tagsOf, "tag"), state.tag);
    var tagItems = [{ key: null, label: "全部" }].concat(
      [TAG_CME, TAG_MEETING]
        .filter(function (t) { return tagCounts[t] != null; })
        .map(function (t) { return { key: t, label: t, count: tagCounts[t] }; })
    );
    renderChips("f-tag", tagItems,
      function (i) { return state.tag === i.key; },
      function (i) {
        state.tag = i.key;
        // 換受眾等於換一份清單：主題／主辦／來源的可選值完全不同，
        // 留著上一種的選擇只會得到一頁空清單
        state.region = null;
        state.category = null;
        state.source = null;
        state.organizer = null;
        state.credit = 0;
      });

    // 時間軸的數字要算：「即將舉行 0」正是學會會議最需要一眼看到的事實
    var timeCounts = {};
    var today = todayISO();
    // applyFilters("time") 在迴圈外算一次就好 —— 每個選項各叫一次等於全量掃描六遍
    var timeBase = applyFilters("time");
    TIME_FILTERS.forEach(function (f) {
      timeCounts[f.key] = timeBase.filter(function (e) {
        return f.test(e, today);
      }).length;
    });
    renderChips("f-time",
      TIME_FILTERS.map(function (f) {
        return { key: f.key, label: f.label, count: timeCounts[f.key] };
      }),
      function (i) { return state.time === i.key; },
      function (i) { state.time = i.key; });

    var regionCounts = keepSelected(countBy(function (e) { return e.region; }, "region"), state.region);
    var regions = REGION_ORDER.filter(function (r) { return regionCounts[r] != null; })
      .map(function (r) { return { key: r, label: r, count: regionCounts[r] }; });
    renderChips("f-region", [{ key: null, label: "全部" }].concat(regions),
      function (i) { return state.region === i.key; },
      function (i) { state.region = i.key; });

    renderChips("f-credit", CREDIT_FILTERS, function (i) { return state.credit === i.key; },
      function (i) { state.credit = i.key; });

    var catCounts = keepSelected(countBy(function (e) { return e.categories || []; }, "category"), state.category);
    var cats = Object.keys(catCounts).sort(function (a, b) { return catCounts[b] - catCounts[a]; })
      .map(function (c) { return { key: c, label: c, count: catCounts[c] }; });
    renderChips("f-category", [{ key: null, label: "全部" }].concat(cats),
      function (i) { return state.category === i.key; },
      function (i) { state.category = i.key; });

    var srcCounts = keepSelected(countBy(function (e) { return e.source; }, "source"), state.source);
    var srcs = Object.keys(srcCounts).sort()
      .map(function (s) { return { key: s, label: s, count: srcCounts[s] }; });
    renderChips("f-source", [{ key: null, label: "全部" }].concat(srcs),
      function (i) { return state.source === i.key; },
      function (i) { state.source = i.key; });

    var orgCounts = keepSelected(countBy(organizerKeys, "organizer"), state.organizer);
    var buckets = [ORG_HOSPITAL, ORG_PHARMA, ORG_OTHER, ORG_NONE];
    var orgs = Object.keys(orgCounts)
      .sort(function (a, b) {
        // 收納桶（醫院／藥廠／其他／未標示）不是學會，固定壓在最後
        var ra = buckets.indexOf(a) === -1 ? 0 : 1;
        var rb = buckets.indexOf(b) === -1 ? 0 : 1;
        if (ra !== rb) return ra - rb;
        if (orgCounts[b] !== orgCounts[a]) return orgCounts[b] - orgCounts[a];
        return a < b ? -1 : a > b ? 1 : 0;
      })
      .map(function (o) { return { key: o, label: o, count: orgCounts[o] }; });
    renderChips("f-organizer", [{ key: null, label: "全部" }].concat(orgs),
      function (i) { return state.organizer === i.key; },
      function (i) { state.organizer = i.key; });

    // 「積分高→低」單獨篩「開會」時排不出東西（那些來源的 credits 一律是 null），
    // 留著只是一顆按了沒反應的按鈕
    var sorts = SORTS.filter(function (s) {
      return !(state.tag === TAG_MEETING && s.key === "credit-desc");
    });
    // 🔴 選項被拿掉時，**目前選中的值也要跟著回到預設**。少了這一步，
    // 使用者在「上課」選了積分排序再切到「開會」，state.sort 會停在一個
    // 畫面上根本看不到的選項：排序照著它跑、「篩選」按鈕的數字也照算，
    // 但沒有任何 chip 是選中的，使用者看不出發生什麼事也無從取消
    // （codex review 2026-08-25 抓到）。用「不在可見清單裡就重設」寫，
    // 而不是在切換分類時特判 —— 這樣日後再拿掉別的選項也自動成立。
    if (!sorts.some(function (s) { return s.key === state.sort; })) {
      state.sort = SORTS[0].key;
    }
    renderChips("f-sort", sorts, function (i) { return state.sort === i.key; },
      function (i) { state.sort = i.key; });
  }

  /** 收合狀態下也要看得出有沒有在篩 —— 按鈕上掛一個數字。 */
  function activeFilterCount() {
    var n = 0;
    if (state.time !== "upcoming") n++;
    if (state.region) n++;
    if (state.credit > 0) n++;
    if (state.category) n++;
    if (state.source) n++;
    if (state.organizer) n++;
    if (state.sort !== "date-asc") n++;
    return n;
  }

  function renderToggle() {
    var n = activeFilterCount();
    el.toggle.innerHTML = "篩選" + (n ? '<span class="badge">' + n + "</span>" : "");
  }

  /** 選了某個分類時，在篩選器下方說明那一類是什麼。沒選就不佔位置。 */
  function renderTagHint() {
    el.tagHint.textContent = state.tag ? TAG_HINTS[state.tag] || "" : "";
    el.tagHint.hidden = !el.tagHint.textContent;
    // 積分軸對學會會議沒有意義（那些來源根本不公告點數，欄位一律是空的）。
    // 只在**單獨篩開會**時整列收起來 —— 「全部」時清單裡仍有積分課程，軸要留著。
    el.creditRow.hidden = state.tag === TAG_MEETING;
  }

  /** 頁首數字。跟著目前的分類選擇走，不是永遠的全站合計。 */
  function renderStats() {
    var today = todayISO();
    var mine = state.events.filter(function (e) {
      return !state.tag || tagsOf(e).indexOf(state.tag) !== -1;
    });
    var upcoming = mine.filter(function (e) { return lastDay(e) >= today; });

    el.statCount.textContent = upcoming.length;
    el.statCountLabel.textContent = "場即將舉行";
    if (upcoming.length) {
      el.statRange.textContent =
        upcoming[0].date.slice(5).replace("-", "/") + " – " +
        upcoming[upcoming.length - 1].date.slice(5).replace("-", "/");
    } else {
      // 一場都還沒公布時，把「最近一場是什麼時候」講出來比印一條破折號有用
      var past = mine.filter(function (e) { return lastDay(e) < today; });
      el.statRange.textContent = past.length
        ? "最近一場 " + past[past.length - 1].date
        : "—";
    }

    // 來源數也跟著分類走。用 events.json 的 sources 表而不是從 events 反推 ——
    // 來源掛掉或當期沒活動時它就消失了，那正是最該讓人看到它還在的時候。
    var sources = state.data.sources || {};
    var wantKind = state.tag === TAG_MEETING ? "meeting" : state.tag === TAG_CME ? "cme" : null;
    el.statSources.textContent = Object.keys(sources).filter(function (name) {
      if (!wantKind) return true;
      var entry = sources[name];
      // 舊版 events.json 的 sources 是 name→筆數，沒有 kind；那時只有積分課程
      var kind = entry && typeof entry === "object" ? entry.kind : "cme";
      return (kind || "cme") === wantKind;
    }).length;
  }

  /** 置頂的 Guideline 區。
   *
   *  🔴 **這一區不吃下面那套 tag 篩選**（站主 2026-08-25 指定：「置頂在篩選器上面常駐
   *  並且分開 就是一個guideline 區域」）—— 它跟活動清單是不同性質的東西，
   *  不管篩選器選什麼都要看得到。
   *
   *  按鍵是**用資料 render 出來的，不是寫死在 HTML 裡**：他今天給三顆，日後再丟一條
   *  網址進 data/guidelines.json 就多一顆，不用改版面。 */
  function renderGuidelines(data) {
    var items = (data && data.guidelines) || [];
    if (!items.length) {
      el.guidelines.hidden = true;
      return;
    }
    el.guidelines.hidden = false;

    var box = el.guidelines.querySelector(".guideline-links");
    box.innerHTML = "";
    items.forEach(function (g) {
      if (!g.url) return;
      var a = document.createElement("a");
      a.className = "guideline-link";
      a.href = g.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      if (g.full_name) a.title = g.full_name;
      a.textContent = g.label + (g.version ? " " + g.version : "");
      box.appendChild(a);
    });

    // 有任何一顆退回 fallback 就講出來。這是「連結悄悄過期」的可見化 ——
    // 只寫進 log 的話沒有人會發現按鍵指到的是舊版。
    var stale = items.filter(function (g) { return g.resolved === false; });
    if (stale.length) {
      el.guidelineNote.hidden = false;
      el.guidelineNote.textContent =
        "以下連結這次沒能自動確認最新版，顯示的是上次驗證過的網址：" +
        stale.map(function (g) { return g.label; }).join("、");
    } else {
      el.guidelineNote.hidden = true;
    }
  }

  function render() {
    renderTagHint();
    renderStats();
    renderFilters();
    renderToggle();
    renderList(applyFilters());
  }

  /** 只做「跟分頁無關」的部分；會跟著分頁變的數字在 renderStats()。 */
  function renderHeader(data) {
    if (data.updated_at) {
      document.getElementById("stat-updated").textContent =
        "更新於 " + formatUpdatedAt(data.updated_at);
    }

    if (data.errors && data.errors.length) {
      el.notice.hidden = false;
      // 兩種情況共用這條：部分來源失敗，或整批沒抓到而顯示舊資料。
      // 訊息本身已經寫清楚是哪一種，前綴保持中性就好。
      el.notice.textContent = "資料更新有狀況：" + data.errors.join("；");
    }
  }

  // ---------- 啟動 ----------
  el.q.addEventListener("input", function () {
    state.q = el.q.value;
    renderList(applyFilters());
  });

  el.toggle.addEventListener("click", function () {
    var collapsed = el.filters.classList.toggle("collapsed");
    el.toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
  });

  // 手機預設收合，讓活動清單出現在第一屏；桌面維持全部攤開
  if (window.matchMedia("(max-width: 560px)").matches) {
    el.filters.classList.add("collapsed");
  }

  el.reset.addEventListener("click", function () {
    // 「清除」也把分類清成「全部」—— 它就是一個篩選條件，沒有理由留著
    state.q = "";
    el.q.value = "";
    state.tag = null;
    state.time = "all";
    state.region = null;
    state.credit = 0;
    state.category = null;
    state.source = null;
    state.organizer = null;
    state.sort = "date-asc";
    render();
  });

  /* Guideline 區獨立載入，**刻意不跟活動資料綁在一起**：
     兩份 JSON 由不同的排程產生（活動每天、guideline 每年），任一份掛掉
     不該讓另一份跟著消失。guidelines.json 讀不到就是不顯示那一區，
     活動清單照常運作，不會讓整頁變成錯誤畫面。 */
  fetch(GUIDELINES_URL, { cache: "no-cache" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) { if (data) renderGuidelines(data); })
    .catch(function () { /* 沒有 guideline 區也不影響活動清單 */ });

  fetch(DATA_URL, { cache: "no-cache" })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (data) {
      state.data = data;
      state.events = data.events || [];
      renderHeader(data);
      render();
    })
    .catch(function (err) {
      el.list.innerHTML = "";
      el.empty.hidden = false;
      el.empty.textContent = "資料載入失敗（" + err.message + "）。請稍後重新整理。";
    });
})();
