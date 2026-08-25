#!/usr/bin/env python3
"""解析三個學會的 guideline 連結 → 寫出 data/guidelines.json。

**跟 build.py 是完全分開的兩條線**，刻意的：
  ・活動資料每天更新，guideline 一年才換一次版
  ・活動來源掛掉不該讓 guideline 按鍵跟著消失，反過來也是
  ・分開之後，這支的排程可以跑得比每日抓取稀疏很多，不去騷擾人家的網站

排程見 `.github/workflows/guidelines.yml`。

退出碼：0＝三顆都動態解析成功；1＝至少一顆退回 fallback（工作流程會變紅）。
**退回 fallback 不會讓檔案寫不出來** —— 按鍵永遠是三顆齊全、永遠點得開，
只是站上會顯示一條「某顆連結自動解析失敗」的提示。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sources.base import TAIPEI  # noqa: E402
from sources.guidelines import resolve_all  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "guidelines.json"


def _write(payload: dict) -> None:
    """原子寫入：中途失敗不會留下半截 JSON。"""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(OUTPUT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只印結果，不寫檔")
    args = parser.parse_args()

    guidelines, errors = resolve_all()

    for item in guidelines:
        print(
            "[{}] {} {} — {}".format(
                "ok" if item.resolved else "fallback",
                item.label,
                item.version or "(無版本標示)",
                item.url,
            )
        )
    for message in errors:
        print("[FAIL] {}".format(message), file=sys.stderr)

    exit_code = 1 if errors else 0

    if args.dry_run:
        return exit_code

    _write(
        {
            "updated_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
            "errors": errors,
            "guidelines": [g.to_dict() for g in guidelines],
        }
    )
    print("已寫入 {}".format(OUTPUT))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
