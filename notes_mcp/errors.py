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
