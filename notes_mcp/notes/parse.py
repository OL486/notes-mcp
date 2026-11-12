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

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


def decode_bytes(data: bytes) -> str:
    """按 utf-8 → gb18030 → 有损 utf-8 的顺序解码。

    中文 Windows 上老笔记常是 GBK/GB18030；直接用 Path.read_text() 会抛
    UnicodeDecodeError 让整个工具调用失败，为了一篇乱码笔记赔上整次检索不值得。
    """
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_title(text: str, fallback: str) -> str:
    """取首行标题：第一个 `#` 标题行；没有标题就用第一行非空内容。"""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            return title or fallback
        return stripped[:80]
    return fallback


def extract_tags(text: str) -> tuple[str, ...]:
    """解析正文里的 #tag，剔除代码块与标题行后再匹配。

    不去掉代码块的话，笔记里贴一段 `# 注释` 或 shell 的 `# TODO` 都会被算成标签。
    """
    cleaned = _strip_fenced_code(text)
    tags: set[str] = set()
    for line in cleaned.splitlines():
        if _HEADING_RE.match(line):
            continue
        for match in TAG_RE.finditer(line):
            tag = match.group(1).rstrip("/-")
            if tag:
                tags.add(tag)
    return tuple(sorted(tags))


def _strip_fenced_code(text: str) -> str:
    """把 ``` / ~~~ 围起来的代码块替换成空行，保留行数以便行号仍然对得上。"""
    out: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        stripped = line.lstrip()
        if fence is None:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                fence = stripped[:3]
                out.append("")
                continue
            out.append(line)
        else:
            if stripped.startswith(fence):
                fence = None
            out.append("")
    return "\n".join(out)


def count_units(text: str) -> int:
    """CJK 字符按字算，拉丁文本按词算。中英混排笔记用 len() 会严重失真。"""
    return len(_CJK_RE.findall(text)) + len(_WORD_RE.findall(text))
