"""上下文预算工具。

MCP server 最典型的翻车方式不是崩，而是"太实在"：模型说 read_note，它就把
300KB 的笔记原样吐回去，一次调用吃掉客户端半个上下文窗口，之后所有推理都降智。
所以每个工具的返回值都要有上限，而且**超限时必须明说**，否则模型以为自己看到了全部。
"""

from __future__ import annotations

MIN_USEFUL_REMAINDER = 400
"""剩余预算低于这个数就干脆不再塞内容：几十个字符的残片对模型没有价值，
只会让它以为自己读到了东西。"""


def clip_text(text: str, limit: int) -> tuple[str, bool]:
    """把文本截到 limit 字符以内，返回 (截断后文本, 是否真的截断了)。

    优先在行边界切，避免把一行 Markdown 从中间劈开导致语法看起来是坏的。
    如果最近的行边界离 limit 太远（比如整篇没有换行），就硬切。
    """
    if limit <= 0:
        return "", bool(text)
    if len(text) <= limit:
        return text, False

    cut = text.rfind("\n", 0, limit)
    if cut < limit // 2:
        cut = limit
    elif cut > 0 and text[cut - 1] == "\r":
        # CRLF 文件里 "\n" 前面还有个 "\r"，切在两者之间会留下一个孤立的回车，
        # 客户端渲染时可能出现诡异的空行。
        cut -= 1
    return text[:cut], True


def truncation_notice(returned: int, total: int, budget: int, advice: str) -> str:
    """统一的截断提示。

    必须同时给出三件事：返回了多少、总量多少、模型下一步该怎么做。
    只说"已截断"的提示等于没说——模型会继续用同样参数重试。
    """
    return (
        f"\n\n[已截断：返回 {returned} 字符 / 全文 {total} 字符，达到 {budget} 字符预算上限。"
        f"{advice}]"
    )


NOTICE_RESERVE = 240
"""给截断提示预留的字符数。提示本身必须算进预算，否则"20000 上限"会吐出 20100。"""


def clip_with_notice(text: str, budget: int, advice: str) -> tuple[str, bool]:
    """截断并在末尾附上提示，保证**含提示在内**不超过 budget。

    这是 read_note / 单篇 Resource / notes_stats 共用的收口函数：
    分散在各处手写"先截断再拼提示"必然有一处忘了算提示的长度。
    """
    if len(text) <= budget:
        return text, False
    body, _ = clip_text(text, max(1, budget - NOTICE_RESERVE))
    return body + truncation_notice(len(body), len(text), budget, advice), True


def fit_blocks(
    blocks: list[str],
    budget: int,
    *,
    header: str = "",
    overflow_advice: str = "请缩小范围后重试。",
) -> tuple[str, int, bool]:
    """按顺序把若干文本块塞进预算，返回 (拼好的文本, 实际返回块数, 是否截断)。

    三条规则，都是踩过坑才定下来的：

    1. 块（片段/条目）是语义单位，放不下就整体不塞——半块内容对模型没用。
    2. **但第一块放不下时必须裁而不是丢**。否则一篇命中 200 行的笔记会让
       search_notes 返回 0 个片段，模型看到"命中 200 篇、返回 0 篇"完全没法行动。
    3. 截断提示本身也算预算。否则"8000 预算"实际会吐出 8200，
       预算表就成了假的。
    """
    kept: list[str] = []
    used = len(header)
    truncated = False

    for block in blocks:
        if used + len(block) <= budget:
            kept.append(block)
            used += len(block)
            continue

        truncated = True
        remainder = budget - used
        if remainder >= MIN_USEFUL_REMAINDER:
            clipped, _ = clip_text(block, remainder - 60)
            kept.append(clipped + "\n…（本片段已截断）\n")
        break

    def _notice(count: int) -> str:
        return (
            f"\n\n[已截断：共 {len(blocks)} 个结果块，受 {budget} 字符预算限制只返回了前 {count} 个。"
            f"{overflow_advice}]"
        )

    text = header + "".join(kept)
    if truncated:
        # 把提示也算进预算：必要时从尾部丢块，直到总量落在上限内。
        while kept and len(text) + len(_notice(len(kept))) > budget:
            kept.pop()
            text = header + "".join(kept)
        text += _notice(len(kept))

    return text, len(kept), truncated
