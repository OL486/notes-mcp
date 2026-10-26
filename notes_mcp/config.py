"""运行期配置。

为什么单独抽一层：MCP Server 的"返回体积"是设计参数，不是硬编码常量。
把预算集中在这里，S4 做上下文预算复核时只需要看一个文件就能算出最坏情况。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_ROOT = "NOTES_MCP_ROOT"
ENV_MAX_NOTE_CHARS = "NOTES_MCP_MAX_NOTE_CHARS"
ENV_SEARCH_BUDGET = "NOTES_MCP_SEARCH_BUDGET"


@dataclass(frozen=True, slots=True)
class Settings:
    """一次进程生命周期内不变的配置。"""

    root: Path
    """笔记根目录，**已经 resolve 过**。安全校验依赖这一点，见 safety.py。"""

    # ---- 上下文预算（字符数，不是字节数；中文场景下字符数更贴近 token 数）----
    max_note_chars: int = 20_000
    """read_note 单次返回上限。超过就截断并明确告知。"""

    search_budget: int = 8_000
    """search_notes 单次返回总预算，所有片段加起来不得超过它。"""

    index_budget: int = 8_000
    """notes://index 的返回预算。"""

    recent_budget: int = 4_000
    """list_recent 的返回预算。"""

    stats_budget: int = 3_000
    """notes_stats 的返回预算。"""

    # ---- 检索行为 ----
    fragments_per_note: int = 3
    """每篇笔记最多返回几个片段。"""

    context_lines: int = 2
    """每个命中行前后各带几行上下文。"""

    max_fragment_lines: int = 15
    """单个片段最多多少行。防止"连续命中"把片段合并成整篇。"""

    max_limit: int = 20
    """search_notes / list_recent 的参数上限，防止模型传 limit=100000 打爆预算。"""


def load_settings(
    root: str | os.PathLike[str] | None = None,
    *,
    max_note_chars: int | None = None,
    search_budget: int | None = None,
) -> Settings:
    """从参数 / 环境变量组装 Settings。

    优先级：函数参数 > 环境变量 > 默认值。
    root 在这里就 resolve：后面 safety.resolve_note_path 的越界判断直接依赖它，
    如果 root 本身带符号链接而没展开，is_relative_to 会误判。
    """
    raw_root = root or os.environ.get(ENV_ROOT) or "notes"
    resolved_root = Path(raw_root).expanduser().resolve()

    return Settings(
        root=resolved_root,
        max_note_chars=_env_int(ENV_MAX_NOTE_CHARS, max_note_chars, 20_000),
        search_budget=_env_int(ENV_SEARCH_BUDGET, search_budget, 8_000),
    )


def _env_int(env_name: str, explicit: int | None, default: int) -> int:
    """环境变量解析失败时退回默认值，而不是让 server 起不来。"""
    if explicit is not None:
        return explicit
    raw = os.environ.get(env_name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default
