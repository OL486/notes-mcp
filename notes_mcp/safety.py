"""路径安全：把不可信的 path 参数收敛到笔记根目录内。

这是整个项目最容易出事的地方。`read_note` 的 path 直接来自模型输出，
而模型可能被笔记内容注入，也可能只是幻觉出一个路径。任何"看起来还行"的
字符串拼接都可能让 server 变成任意文件读取器。
"""

from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath
from urllib.parse import quote

ALLOWED_SUFFIXES = frozenset({".md", ".markdown"})
"""只允许 Markdown。少一类文件就少一类被读取的理由。"""

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class PathRejected(Exception):
    """路径被拒绝。

    message 会原样出现在工具的 isError 内容里，所以必须是**给模型看的**说明：
    说清哪里错了 + 怎么改，模型才能自我纠正后重试。
    """

    def __init__(self, reason: str, hint: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.reason}。{self.hint}" if self.hint else self.reason


def _looks_absolute(raw: str) -> bool:
    """判断是否绝对路径。要同时覆盖 POSIX 和 Windows 两套写法。

    Windows 上只调 Path.is_absolute() 是不够的：`\\foo`、`C:foo` 这类
    "带盘符/根但不算绝对"的写法会让拼接结果跑出预期目录，所以逐个显式判断。
    """
    if raw.startswith(("/", "\\")):
        return True
    if _DRIVE_RE.match(raw):
        return True
    if PureWindowsPath(raw).is_absolute():
        return True
    return Path(raw).is_absolute()


def resolve_note_path(
    root: Path,
    raw: str,
    *,
    allowed_suffixes: frozenset[str] = ALLOWED_SUFFIXES,
    must_exist: bool = True,
) -> Path:
    """把模型给的相对路径解析成根目录内的真实文件路径，否则抛 PathRejected。

    校验顺序是有讲究的：先做便宜的字符串层拒绝（空、NUL、绝对路径、`..`），
    再做 resolve + is_relative_to。**只做字符串检查是不够的**——符号链接
    可以让一个看起来完全正常的 `evil.md` 指向 `C:\\Windows\\System32\\drivers\\etc\\hosts`，
    只有 resolve() 展开链接之后再比较，才拦得住。
    """
    if not isinstance(raw, str) or not raw.strip():
        raise PathRejected("path 不能为空", "请传入相对笔记根目录的 Markdown 路径，例如 daily/2026-10-01.md")

    if "\x00" in raw:
        raise PathRejected("path 含 NUL 字节", "这是非法输入，请重新给出正常的相对路径")

    # 模型经常直接抄 Windows 风格的反斜杠路径，统一成正斜杠再处理，
    # 否则 `a\..\..\b` 这种会因为 Path 在 POSIX 语义下不认 `\` 而绕过检查。
    normalized = raw.strip().replace("\\", "/")

    if _looks_absolute(normalized):
        raise PathRejected(
            f"拒绝绝对路径：{raw}",
            "只接受相对笔记根目录的路径，例如 daily/2026-10-01.md",
        )

    parts = Path(normalized).parts
    if ".." in parts:
        # 即使 `a/../b` 最终仍在根目录内也一律拒绝：规则简单可预测，
        # 模型也更容易学会"不要用 .."。
        raise PathRejected(
            f"拒绝路径穿越：{raw}",
            "路径中不允许出现 ..，请使用根目录内的相对路径",
        )

    if "." in parts:
        # 单点段会被 resolve 消掉，本身无害，但出现它通常说明路径拼错了。
        normalized = "/".join(p for p in parts if p != ".")

    # resolve(strict=False)：文件不存在时也返回一个确定的绝对路径，
    # 这样"越界"和"不存在"能给出两种不同的错误，模型才知道该改什么。
    target = (root / normalized).resolve(strict=False)

    if not target.is_relative_to(root):
        raise PathRejected(
            f"路径越界：{raw} 解析后落在笔记根目录之外",
            "只允许笔记根目录内的相对路径（符号链接指向外部同样会被拒绝）",
        )

    if target.suffix.lower() not in allowed_suffixes:
        allowed = "、".join(sorted(allowed_suffixes))
        raise PathRejected(
            f"不支持的文件类型：{target.suffix or '无扩展名'}",
            f"只允许读取 {allowed} 文件",
        )

    if must_exist and not target.is_file():
        raise PathRejected(
            f"笔记不存在：{normalized}",
            "先用 list_recent 或读取 notes://index 确认准确路径，再调用 read_note",
        )

    return target


def to_note_uri(rel_path: str) -> str:
    """相对路径 -> notes:// URI。

    用 `{+path}` 风格的模板意味着斜杠必须保留，所以这里只做最小转义：
    空格和 `#`/`?` 会破坏 URI 语义，其余原样保留（中文直接出现在 URI 里是合法的）。
    """
    return "notes://note/" + quote(rel_path.replace("\\", "/"), safe="/")
