#!/usr/bin/env bash
# 上架前的個資閘門：這個 repo 是公開的，任何個人身分資訊都不該出現。
#
# 為什麼要有這支：一旦 push 到公開 repo 就算已外流（git history 會留痕），
# 事後刪檔不算補救。所以檢查要在 commit / push 之前跑，而且要跑在 CI 上，
# 不能只靠「記得檢查」。
#
# 🔴 這支腳本自己會被公開，所以**它裡面不能寫任何人的真名或信箱** ——
# 「掃描規則」本身就是個資外洩管道，這是很容易忽略的一層。
# 因此這裡只掃「形狀」（信箱樣式、token 樣式、絕對路徑、電話），
# 針對特定人名的規則放在不進版控的 .pii-local（見 .gitignore），
# 本機跑的時候會自動帶上，CI 上沒有那個檔就只跑形狀規則。
#
#   bash scripts/pii-scan.sh          掃工作區
#   bash scripts/pii-scan.sh --all    連 git 歷史與 commit 訊息一起掃（上架前跑一次）
#
# 退出碼：0 乾淨 / 2 有命中
set -euo pipefail

cd "$(dirname "$0")/.."

# 形狀規則（不含任何真實姓名／信箱值）
# 註：資料來源網站上的公開機構名（醫院、學會、飯店會場）不是個資，不在掃描範圍。
PII_PATTERNS='[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
PII_PATTERNS="$PII_PATTERNS"'|/Users/[a-z]|/home/[a-z]'
PII_PATTERNS="$PII_PATTERNS"'|sk-ant-|ghp_|gho_|github_pat_|AKIA[0-9A-Z]{16}'
PII_PATTERNS="$PII_PATTERNS"'|Bearer [A-Za-z0-9._-]{20,}'
# 台灣身分證字號樣式
PII_PATTERNS="$PII_PATTERNS"'|[A-Z][12][0-9]{8}'

# 本機補充規則（人名等）。這個檔不進版控，一行一個 regex，# 開頭是註解。
LOCAL_RULES=".pii-local"
if [ -f "$LOCAL_RULES" ]; then
  extra=$(grep -vE '^\s*(#|$)' "$LOCAL_RULES" | paste -sd'|' -)
  if [ -n "$extra" ]; then
    PII_PATTERNS="$PII_PATTERNS|$extra"
    echo "（已載入 $LOCAL_RULES 的本機補充規則）"
  fi
fi

# 白名單：專案自己的匿名署名信箱，不是個資。
# 用「命中行是否只含白名單值」來判，不是整檔排除。
ALLOW='platypusbot@users\.noreply\.github\.com|41898282\+github-actions\[bot\]@users\.noreply\.github\.com'

# 這支腳本自己的規則宣告行一定會匹配到自己的樣式（例如 token 前綴那行）。
# 只濾掉「內容就是那幾行宣告」的命中，不是整檔排除 ——
# 後者會讓日後有人把真個資寫進這支腳本的註解時，閘門完全抓不到。
# 兩種前綴都要認：工作區是 `檔名:行號:內容`，git 歷史那段是 `行號:+內容`。
SELF_DECL="^([^:]*:)?[0-9]+:[+ -]?(PII_PATTERNS|ALLOW|SELF_DECL|LOCAL_RULES)="

drop_allowed() {
  grep -vE "$ALLOW" | grep -vE "$SELF_DECL" || true
}

fail=0

echo "==> 掃描工作區（含註解、README、data/*.json）"
hits=$(grep -rInE "$PII_PATTERNS" . \
      --exclude-dir=.git --exclude-dir=__pycache__ --exclude-dir=.venv \
      --exclude="$LOCAL_RULES" 2>/dev/null | drop_allowed || true)
if [ -n "$hits" ]; then
  echo "$hits"
  echo "🛑 工作區偵測到個資樣式"
  fail=1
else
  echo "   ✅ 工作區乾淨"
fi

# 來源的「聯絡人」欄位是承辦人員的姓氏加分機，解析時就沒有收進來。
# 這裡再確認一次輸出裡真的沒有電話號碼。
echo "==> 檢查活動資料沒有夾帶聯絡人電話"
if [ -f data/events.json ]; then
  # 涵蓋實際看到的三種寫法：[PHONE-REDACTED]#262135 / [PHONE-REDACTED] #2270 / [PHONE-REDACTED]
  # （只寫「區碼-連續數字」會漏掉中間有分隔的那兩種，等於閘門形同虛設）
  phones=$(grep -nE '0[0-9]{1,2}[- ][0-9]{3,4}[- ]?[0-9]{3,4}' data/events.json 2>/dev/null || true)
  if [ -n "$phones" ]; then
    echo "$phones"
    echo "🛑 events.json 出現電話號碼，請檢查解析規則是否誤收聯絡人欄"
    fail=1
  else
    echo "   ✅ 無電話號碼"
  fi
else
  echo "   （尚未產出 data/events.json，略過）"
fi

if [ "${1:-}" = "--all" ]; then
  echo "==> 掃描 git 歷史與 commit 訊息"
  if [ -d .git ]; then
    # 每一段都要 || true：set -o pipefail 之下，grep 找不到東西（回 1）
    # 或 git log 在還沒有任何 commit 時失敗，都會讓整支腳本直接中止，
    # 看起來像「掃描沒跑完」而不是「乾淨」。
    hist=$( { git log -p --all 2>/dev/null || true; } \
            | grep -nE "$PII_PATTERNS" | drop_allowed || true)
    msgs=$( { git log --format='%an|%ae|%s%n%b' --all 2>/dev/null || true; } \
            | grep -nE "$PII_PATTERNS" | drop_allowed || true)
    if [ -n "$hist$msgs" ]; then
      { [ -n "$hist" ] && echo "$hist"; [ -n "$msgs" ] && echo "$msgs"; } | head -20
      echo "🛑 git 歷史或 commit 訊息含個資樣式（需清史後才能公開）"
      fail=1
    else
      echo "   ✅ 歷史與 commit 訊息乾淨"
    fi
  else
    echo "   （尚未 git init，略過）"
  fi
fi

if [ "$fail" -ne 0 ]; then
  exit 2
fi
echo "全部通過"
