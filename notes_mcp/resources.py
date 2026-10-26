"""两个 Resource 的实现。

Resource 和 Tool 的区别不是"谁能读文件"，而是**谁来触发**：
Tool 由模型决定调用，Resource 由客户端/用户决定读取（挂到上下文、@ 引用、手动打开）。
所以 index 做成 Resource 是对的——它是"目录"，属于用户侧的可浏览资产。
"""

from __future__ import annotations

import json
from datetime import datetime

from .budget import clip_with_notice
from .config import Settings
from .safety import resolve_note_path, to_note_uri
from .store import load_all, load_note

INDEX_URI = "notes://index"
NOTE_URI_TEMPLATE = "notes://note/{+path}"


def build_index(settings: Settings) -> str:
    """notes://index：全部笔记的清单，JSON 格式。

    用 JSON 而不是 Markdown 表格：这是给客户端/模型做结构化索引用的，
    JSON 的字段名本身就是语义，模型不用去猜列顺序。

    条目按预算裁剪，并在 JSON 里显式写 `truncated` / `returned` / `count`，
    这样模型读到的不是"看起来完整其实缺了一半"的假清单。

    体积必须按**序列化后的真实长度**算。第一版按单条目 json.dumps 的长度累加，
    结果 `indent=2` 的缩进和换行完全没算进去，200 篇笔记实测吐出 11K 字符——
    预算表直接失真。现在每加一条就真实序列化一次来量。
    """
    notes = load_all(settings.root)
    notes.sort(key=lambda n: n.mtime, reverse=True)

    # 给 truncated 时的 hint 字段预留空间，避免"刚好卡线再加一句就超"。
    budget = max(1_000, settings.index_budget - 200)
    entries: list[dict[str, object]] = []
    truncated = False

    for note in notes:
        entries.append(
            {
                "uri": to_note_uri(note.rel),
                "path": note.rel,
                "title": note.title,
                "mtime": datetime.fromtimestamp(note.mtime).isoformat(timespec="minutes"),
                "units": note.units,
                "tags": list(note.tags),
            }
        )
        if len(_dump_index(settings, len(notes), entries, truncated=True)) > budget:
            entries.pop()
            truncated = True
            break

    return _dump_index(settings, len(notes), entries, truncated=truncated)


def _dump_index(
    settings: Settings,
    total: int,
    entries: list[dict[str, object]],
    *,
    truncated: bool,
) -> str:
    payload: dict[str, object] = {
        "root": str(settings.root),
        "count": total,
        "returned": len(entries),
        "truncated": truncated or len(entries) < total,
        "notes": entries,
    }
    if payload["truncated"]:
        payload["hint"] = "清单被预算截断，请用 list_recent 或 search_notes 定位剩余笔记。"
    return json.dumps(payload, ensure_ascii=False, indent=2)


def read_note_resource(settings: Settings, path: str) -> str:
    """notes://note/{path}：单篇笔记正文。

    注意这里**再校验一次**路径。SDK 的 ResourceSecurity 已经在模板参数层
    拦掉了 `..`、绝对路径和 NUL 字节，但那是"模板参数"级别的防线；
    换成 `notes://index` 之外的静态资源、或者以后改了 URI 结构，这道防线就没了。
    真正的安全边界必须由 server 自己守住，不能依赖调用方的检查。

    返回体积同样封顶：Resource 虽然名义上由客户端决定何时读取，但不少客户端
    会把资源内容直接塞进上下文，一篇 200KB 的笔记足以毁掉整轮对话。
    """
    target = resolve_note_path(settings.root, path)
    note = load_note(settings.root, target)

    text, _ = clip_with_notice(
        note.text,
        settings.max_note_chars,
        "请改用 read_note 工具分段读取，或用 search_notes 定位关键段落。",
    )
    return text


__all__ = [
    "INDEX_URI",
    "NOTE_URI_TEMPLATE",
    "build_index",
    "read_note_resource",
]
