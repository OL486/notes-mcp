"""Prompt 模板。

Prompt 是"用户侧发起"的预置消息模板：用户在客户端里选一个 prompt，
填参数，客户端拿到一组 message 直接塞进对话。它不是给模型调用的工具，
所以内容应该写成**给模型的指令**，而不是"返回值"。
"""

from __future__ import annotations

WEEKLY_REVIEW = "weekly-review"


def weekly_review(topic: str) -> str:
    """生成"总结本周关于 {topic} 的笔记"的指令模板。

    为什么把工具名写进模板：Prompt 的价值就是把"该怎么做"固化下来。
    用户只说一个 topic，模板负责把检索路径（先 list_recent 再 search_notes）
    和输出格式（3 条要点 + 出处）交代清楚，避免每次都要重新提示。
    """
    clean = (topic or "").strip() or "（未指定主题）"
    return f"""请基于我的本地笔记，总结本周关于「{clean}」的内容。

步骤：
1. 调用 `list_recent`，参数 days=7，确认本周实际改动过哪些笔记。
2. 调用 `search_notes`，参数 query="{clean}"、limit=8，拿到命中片段。
3. 如果片段不足以支撑结论，再用 `read_note` 精确读取相关笔记（不要整目录遍历）。
4. 只用笔记里真实存在的内容作答；笔记没写的，明确说"笔记中没有提到"。

输出格式：
- 恰好 3 条要点，每条一句话说清结论。
- 每条要点后用括号标注来源笔记路径，例如（daily/2026-10-25.md）。
- 如果本周没有任何相关笔记，直接说明，并列出本周实际写过的笔记标题。"""
