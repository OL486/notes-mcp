"""解析：把一篇笔记的原始文本变成标题、标签、字数。

只做纯文本处理，不碰文件系统。
"""

from __future__ import annotations

import re

TAG_RE = re.compile(r"(?<![\w#])#([\w\u4e00-\u9fff][\w\u4e00-\u9fff/-]*)")
r"""匹配正文里的 `#tag` / `#中文标签` / `#a/b`。

`(?<![\w#])` 这个前向断言是关键：Markdown 标题 `# 标题` 里 `#` 后面跟空格，
不会命中；但 `##二级标题` 这类漏写空格的写法会命中，所以解析前先把标题行剔掉。
"""

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
"""判定"这是标题行"的严格规则：`#` 后面必须跟空白。

不能用 `line.startswith("#")`——那会把整行标签 `#mcp #protocol` 当成标题剔掉，
标签统计会直接归零（这个 bug 第一版就踩了）。
"""

_TAG_TOKEN_RE = re.compile(r"^#[\w\u4e00-\u9fff][\w\u4e00-\u9fff/-]*$")
"""判定"这行全是标签"：每个空白分隔的词都形如 `#tag`。

`extract_title` 用它跳过纯标签行：`#mcp #design` 不是标题，标题要继续往下找。
"""

_INLINE_CODE_DOUBLE_RE = re.compile(r"``[^`\n]*``")
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
"""行内代码段：`` `#foo` `` 里的 `#` 不是标签，匹配前先剔掉。

先剔双反引号段再剔单反引号段；嵌套反引号的极端写法剔不干净，
但 `#` 本身一定会被带走——标签统计只关心 `#` 在不在。
"""

_UNIT_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]|[A-Za-z0-9_]+")
"""一次扫描同时数 CJK 字和拉丁词：单个 CJK 字符算 1，连续拉丁字符算 1 个词。

原来是 CJK 与拉丁各一次 findall，全文扫两遍；两类字符集不重叠，
一次扫描的结果与两次相加完全一致。
"""


def decode_bytes(data: bytes) -> str:
    """按 utf-16（BOM）→ utf-8 → gb18030 → 有损 utf-8 的顺序解码。

    中文 Windows 上老笔记常是 GBK/GB18030；直接用 Path.read_text() 会抛
    UnicodeDecodeError 让整个工具调用失败，为了一篇乱码笔记赔上整次检索不值得。

    UTF-16 必须先按 BOM 识别：gb18030 几乎什么字节都解得出，
    不先判 BOM 的话 UTF-16 文件会走 gb18030 兜底，解成一堆乱码还不报错。
    """
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _is_tag_only_line(stripped: str) -> bool:
    """这行是不是纯标签行，例如 `#mcp #design`。"""
    return bool(stripped) and all(
        _TAG_TOKEN_RE.match(token) for token in stripped.split()
    )


def _fence_marker(line: str) -> str | None:
    """围栏起始/结束行返回围栏标记（``` 或 ~~~），否则返回 None。"""
    stripped = line.lstrip()
    if stripped.startswith("```") or stripped.startswith("~~~"):
        return stripped[:3]
    return None


def extract_title(text: str, fallback: str) -> str:
    """取首行标题：第一个 `#` 标题行；没有标题就用第一行非空内容。

    跳过三类"不是标题"的行：围栏行与围栏内的代码、纯标签行（如 `#mcp #design`）。
    标题行必须是 `#` + 空白的严格标题（`_HEADING_RE`）；`#标题` 这种没空格的写法
    在 Markdown 里不是标题，按标签行处理，继续往下找。
    """
    fence: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        marker = _fence_marker(line)
        if fence is None:
            if marker is not None:
                fence = marker
                continue
        else:
            if marker == fence:
                fence = None
            continue
        if _HEADING_RE.match(line):
            title = stripped.lstrip("#").strip()
            return title or fallback
        if _is_tag_only_line(stripped):
            continue
        return stripped[:80]
    return fallback


def extract_tags(text: str) -> tuple[str, ...]:
    """解析正文里的 #tag，剔除代码块、行内代码与标题行后再匹配。

    不去掉代码块的话，笔记里贴一段 `# 注释` 或 shell 的 `# TODO` 都会被算成标签。
    单遍扫描：逐行跟踪围栏状态，不再像以前那样先全文复制一份再逐行扫。
    """
    tags: set[str] = set()
    fence: str | None = None
    for line in text.splitlines():
        marker = _fence_marker(line)
        if fence is None:
            if marker is not None:
                fence = marker
                continue
        else:
            if marker == fence:
                fence = None
            continue
        if _HEADING_RE.match(line):
            continue
        if "`" in line:
            # 无反引号的行两次 sub 本来就是 no-op：1000 篇 × 100 行时
            # 这两行 sub 要跑近 60 万次，其中约 5% 的全量加载时间是白花的。
            line = _INLINE_CODE_DOUBLE_RE.sub("", line)
            line = _INLINE_CODE_RE.sub("", line)
        for match in TAG_RE.finditer(line):
            tag = match.group(1).rstrip("/-")
            if tag:
                tags.add(tag)
    return tuple(sorted(tags))


def count_units(text: str) -> int:
    """CJK 字符按字算，拉丁文本按词算。中英混排笔记用 len() 会严重失真。"""
    return len(_UNIT_RE.findall(text))
