"""解析：把一篇笔记的原始文本变成标题、标签、字数。

只做纯文本处理，不碰文件系统。
"""

from __future__ import annotations

import re
from typing import NamedTuple

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
    """按 utf-32（BOM）→ utf-16（BOM）→ utf-8 → gb18030 → 有损 utf-8 的顺序解码。

    中文 Windows 上老笔记常是 GBK/GB18030；直接用 Path.read_text() 会抛
    UnicodeDecodeError 让整个工具调用失败，为了一篇乱码笔记赔上整次检索不值得。

    UTF-16 必须先按 BOM 识别：gb18030 几乎什么字节都解得出，
    不先判 BOM 的话 UTF-16 文件会走 gb18030 兜底，解成一堆乱码还不报错。

    UTF-32 更要先判：它的 LE BOM（FF FE 00 00）前两个字节与 UTF-16 LE 的
    BOM 完全相同，不先判 4 字节就会按 UTF-16 解出带 NUL 的乱码还不报错。
    """
    if data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        try:
            return data.decode("utf-32")
        except UnicodeDecodeError:
            pass
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


_TAG_VALUE_RE = re.compile(r"^[\w\u4e00-\u9fff][\w\u4e00-\u9fff/-]*$")
"""frontmatter 里 `tags:` 值的合法字符集，与 TAG_RE 的标签字符集一致。

含空格等非法字符的值直接丢掉，不参与标签统计。
"""


class _Frontmatter(NamedTuple):
    """剥离结果：正文 + frontmatter 里的标题与标签。"""

    body: str
    title: str | None
    tags: tuple[str, ...]


def _clean_fm_scalar(raw: str) -> str:
    """frontmatter 标量值去引号与 YAML 注释。

    `title: "我的笔记"` → `我的笔记`；`title: 我的笔记 # 这是注释` → `我的笔记`。
    YAML 里 `#` 前有空格即注释，只剥「空格 + #」——`C#` 这类无空格的不动；
    引号里的 `#` 不是注释，`"a # b"` 照单全收。引号后的注释也剥掉，
    所以 `title: "我的笔记" # 注释` 同样只剩 `我的笔记`。
    """
    value = raw.strip()
    if value[:1] in ('"', "'"):
        quote = value[0]
        closing = value.find(quote, 1)
        if closing > 0:
            return value[1:closing].strip()
        return value[1:].strip()
    hash_pos = value.find(" #")
    if hash_pos >= 0:
        value = value[:hash_pos].rstrip()
    return value


def _fm_tag(raw: str) -> str | None:
    """一个 frontmatter 标签值 → 合法标签或 None。

    去掉引号与开头的 `#`（`tags: [#mcp]` 这种写法），再按 TAG_RE 的
    合法字符集校验；末尾多余的 `/`、`-` 与正文标签一样剔掉。
    """
    value = _clean_fm_scalar(raw).lstrip("#").rstrip("/-")
    if value and _TAG_VALUE_RE.match(value):
        return value
    return None


def _split_frontmatter(text: str) -> _Frontmatter:
    """剥离文件开头的 YAML frontmatter（`--- ... ---` 或 `--- ... ...`）。

    只认文件起始处的第一个块：第一行必须是 `---`，且后面必须出现
    结束行（`---` 或 `...`）；没有结束行就不是 frontmatter，整篇按正文处理。
    块里只做行级键值提取：`title:` 与 `tags:`（`[a, b]` 列表与 `- a` 块列表
    两种写法），不做完整 YAML 解析，保持零依赖。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return _Frontmatter(text, None, ())
    end: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return _Frontmatter(text, None, ())
    title: str | None = None
    tags: set[str] = set()
    i = 1
    while i < end:
        stripped = lines[i].strip()
        if stripped.startswith("title:"):
            if title is None:
                value = _clean_fm_scalar(stripped.removeprefix("title:"))
                if value:
                    title = value
            i += 1
        elif stripped.startswith("tags:"):
            rest = stripped.removeprefix("tags:").strip()
            if rest.startswith("[") and rest.endswith("]"):
                for item in rest[1:-1].split(","):
                    tag = _fm_tag(item)
                    if tag is not None:
                        tags.add(tag)
                i += 1
            elif rest:
                tag = _fm_tag(rest)
                if tag is not None:
                    tags.add(tag)
                i += 1
            else:
                # `- a` 块列表：连续的 `- item` 行，空行跳过，别的行结束。
                i += 1
                while i < end:
                    item_line = lines[i].strip()
                    if not item_line:
                        i += 1
                        continue
                    if item_line.startswith("- "):
                        tag = _fm_tag(item_line[2:])
                        if tag is not None:
                            tags.add(tag)
                        i += 1
                        continue
                    break
        else:
            i += 1
    body_start = end + 1
    body = "\n".join(lines[body_start:])
    return _Frontmatter(body, title, tuple(sorted(tags)))


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

    首行非空内容若是 `---` / `...` 也跳过：无结束行的 `---` 不是 frontmatter，
    但它只是分隔线，不能当标题（P2-1；仅跳过第一行即可）。

    frontmatter 先剥离：`---` 块本身不是标题，块里的 `#` 也不参与判定。
    没有 `#` 标题时，frontmatter 的 `title:` 优先于第一行非空内容。
    """
    fm = _split_frontmatter(text)
    fence: str | None = None
    first = True  # 首行非空内容：`---` / `...` 只是分隔线，不是标题。
    for line in fm.body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if first:
            first = False
            if stripped in ("---", "..."):
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
        if fm.title:
            return fm.title[:80]
        return stripped[:80]
    if fm.title:
        return fm.title[:80]
    return fallback


def extract_tags(text: str) -> tuple[str, ...]:
    """解析正文里的 #tag，剔除代码块、行内代码与标题行后再匹配。

    不去掉代码块的话，笔记里贴一段 `# 注释` 或 shell 的 `# TODO` 都会被算成标签。
    单遍扫描：逐行跟踪围栏状态，不再像以前那样先全文复制一份再逐行扫。

    frontmatter 先剥离：块里的 `#` 不算标签；块里 `tags:` 声明的标签
    与正文标签合并返回。
    """
    fm = _split_frontmatter(text)
    tags: set[str] = set(fm.tags)
    fence: str | None = None
    for line in fm.body.splitlines():
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
