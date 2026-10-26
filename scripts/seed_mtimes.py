"""把示例笔记的修改时间错开，让 list_recent 有可演示的数据。

为什么需要这个脚本：git 不保存 mtime，克隆下来的示例笔记全是"刚检出"的时间，
list_recent(days=7) 会把它们全部命中，看不出筛选效果。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "sample_notes"

# 相对"现在"往前推多少小时
OFFSETS_HOURS = {
    "daily/2026-10-26.md": 2,
    "daily/2026-10-25.md": 26,
    "inbox/2026-10-24-mcp-day1.md": 50,
    "projects/notes-mcp-design.md": 72,
    "reading/ddia-ch3.md": 40 * 24,
    "inbox/old-idea-kb-cli.md": 100 * 24,
}


def main() -> int:
    now = time.time()
    for rel, hours in OFFSETS_HOURS.items():
        path = ROOT / rel
        if not path.exists():
            print(f"跳过（不存在）：{rel}")
            continue
        stamp = now - hours * 3600
        os.utime(path, (stamp, stamp))
        print(f"{rel} -> {time.strftime('%Y-%m-%d %H:%M', time.localtime(stamp))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
