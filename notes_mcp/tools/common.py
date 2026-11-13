"""Tool 层共用的小工具：参数夹取与时间格式化。

时间格式集中在这里，而不是各模块手写：
- `_fmt_time`：给人读的显示格式（list_recent / notes_stats），`%Y-%m-%d %H:%M +0800`；
- `_fmt_iso_time`：notes://index 里机器读的 ISO 格式，`2026-10-25T09:15+08:00`。
两处格式本身不同（一个是展示、一个是结构化数据），刻意不强行统一成一种，
统一的是"格式只在这里定义"这一处来源。
时间都带本地时区偏移：不带时区的"09:15"在跨时区客户端看来是歧义的，
模型也无法判断"最近修改"到底是几点。
"""

from __future__ import annotations

from datetime import datetime


def _clamp(value: int, low: int, high: int, *, default: int) -> int:
    """参数夹取而不是报错：模型传了超范围的 limit 时，给最接近的合法值比拒绝更有用。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _fmt_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d %H:%M %z")


def _fmt_iso_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="minutes")
