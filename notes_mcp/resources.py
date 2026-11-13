"""两个 Resource 的实现。

Resource 和 Tool 的区别不是"谁能读文件"，而是**谁来触发**：
Tool 由模型决定调用，Resource 由客户端/用户决定读取（挂到上下文、@ 引用、手动打开）。
所以 index 做成 Resource 是对的——它是"目录"，属于用户侧的可浏览资产。
"""

from __future__ import annotations

import json

from .budget import clip_text
from .config import Settings
from .notes.store import make_store
from .safety import to_note_uri
from .services.read_note import read_note
from .tools.common import _fmt_iso_time

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
    预算表直接失真。第二版每加一条就真实序列化一次来量，长度准了，
    但那是 O(n²)：index_budget 调到 10_000_000 时 1000 篇要 ~4.6 s，
    其中约 4 s 是重复序列化。现在是增量记账：每加一条只算该条的渲染增量，
    最后仍以一次真实 `_dump_index` 收口（防估算漂移）。
    """
    notes = make_store(settings).load_all()
    notes.sort(key=lambda n: n.mtime, reverse=True)

    # 给 truncated 时的 hint 字段预留空间，避免"刚好卡线再加一句就超"。
    # 注意这里没有下限：index_budget 很小（例如 100）时，max(1_000, …) 会
    # 让输出反超预算近 10 倍——预算承诺必须按实际值算。
    budget = settings.index_budget
    work_budget = max(0, budget - 200)
    entries: list[dict[str, object]] = []
    truncated = False

    # 增量记账的算式（与真实 dumps 逐字符一致，见 test_resources 的属性测试）：
    # - 空壳：0 条、truncated=True（含 hint）的 dumps 长度；
    # - 加第 1 条：条目在数组内的渲染长度 + 4
    #  （`"notes": [],` 变成 `"notes": [ … ]` 的结构差）；
    # - 再加一条：条目渲染长度 + 2（条目间的 ",\n"）；
    # - returned 位数变化时再补位数差（9 → 10 加 1）。
    # 其余部分（count、truncated、hint 文本）在循环里是不变量。
    estimated = len(_dump_index(settings, len(notes), [], truncated=True))
    for note in notes:
        entry = {
            "uri": to_note_uri(note.rel),
            "path": note.rel,
            "title": note.title,
            "mtime": _fmt_iso_time(note.mtime),
            "units": note.units,
            "tags": list(note.tags),
        }
        increment = _index_entry_len(entry) + (2 if entries else 4)
        increment += len(str(len(entries) + 1)) - len(str(len(entries)))
        if estimated + increment > work_budget:
            truncated = True
            break
        entries.append(entry)
        estimated += increment

    result = _dump_index(settings, len(notes), entries, truncated=truncated)
    if len(result) > budget:
        # 条目已空仍超预算：先去掉 hint 再量；极端小预算下最后硬截，
        # 预算上限是硬承诺，JSON 完整性只能让路。
        result = _dump_index(settings, len(notes), entries, truncated=truncated, hint=False)
    if len(result) > budget:
        result = clip_text(result, budget)[0]
    return result


def _index_entry_len(entry: dict[str, object]) -> int:
    """一条目在 indent=2 的 notes 数组内的渲染长度。

    `json.dumps(entry, indent=2)` 是条目自身的渲染；在数组里每行再缩进 4 格，
    与 `_dump_index` 里该条目实际占的长度逐字符一致（见 test_resources
    的属性测试）。每条只渲染一次，build_index 的记账因此是 O(n) 而不是 O(n²)。
    """
    rendered = json.dumps(entry, ensure_ascii=False, indent=2)
    return len("\n".join("    " + line for line in rendered.split("\n")))


def _dump_index(
    settings: Settings,
    total: int,
    entries: list[dict[str, object]],
    *,
    truncated: bool,
    hint: bool = True,
) -> str:
    payload: dict[str, object] = {
        "count": total,
        "returned": len(entries),
        "truncated": truncated or len(entries) < total,
        "notes": entries,
    }
    if hint and payload["truncated"]:
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
    # 唯一实现在 notes_mcp.services.read_note；这里只传 Resource 侧的截断提示文案。
    return read_note(
        settings,
        path,
        advice=(
            "请用 search_notes 定位关键段落；超出 20,000 字符上限的部分"
            "目前没有分段读取的办法，read_note 工具同样只有这个上限。"
        ),
    ).text


__all__ = [
    "INDEX_URI",
    "NOTE_URI_TEMPLATE",
    "build_index",
    "read_note_resource",
]
