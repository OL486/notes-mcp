"""共享的异常类型。

单独成模块、不依赖任何项目内模块：safety.py 与 notes/store.py 都要抛
PathRejected，而 safety 又要从 notes.scan 导入后缀白名单——
PathRejected 若留在 safety 里，store 导入它就会形成循环导入。
"""

from __future__ import annotations


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


class NoteTooLargeError(OSError):
    """单篇笔记超过大小上限（`notes.store.MAX_NOTE_BYTES`）。

    OSError 子类：load_all 与 read_note 服务本来就接 OSError，超大文件
    因此默认走"跳过 / 友好报错"的已有路径，不会漏成裸堆栈；
    需要计数时（load_all）或需要专属文案时（read_note 服务）再单独捕获。
    """

    def __init__(self, rel: str, size: int, limit: int) -> None:
        super().__init__(f"笔记过大（{size:,} 字节，超过 {limit:,} 字节上限）：{rel}")
        self.rel = rel
        self.size = size
        self.limit = limit
