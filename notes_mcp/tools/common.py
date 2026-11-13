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


def _clamp(value: object, low: int, high: int, *, default: int) -> int:
    """参数夹取而不是报错：模型传了超范围的 limit 时，给最接近的合法值比拒绝更有用。

    签名是 object 而不是 int：模型参数经 JSON-RPC 进来时类型不可信，
    bool / 浮点 / 字符串都可能出现，夹取前必须先分流——
    bool 与非整数浮点直接回默认值（`int(True)` 是 1、`int(2.9)` 是 2，
    静默取整会把传错的参数"翻译"成另一个合法值，全程无提示）；
    整数值浮点（如 2.0）与数字字符串（如 "5"）仍按原有逻辑夹取。
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, float):
        if not value.is_integer():
            return default
        return max(low, min(high, int(value)))
    if isinstance(value, int):
        return max(low, min(high, value))
    if isinstance(value, str):
        try:
            return max(low, min(high, int(value)))
        except ValueError:
            return default
    return default


def _fmt_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d %H:%M %z")


def _fmt_iso_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="minutes")
