"""读单篇笔记的唯一实现。

原来 `tools.run_read_note` 与 `resources.read_note_resource` 各写了一份
`resolve_note_path → load_note → clip_with_notice`，只差截断提示文案，
改一处很容易漏另一处。现在两边都调这里，只传不同的提示文案。

路径校验放在这里而不是 server 层：资源和工具都要用同一套规则，
放在纯逻辑层才能保证两边不会漂移。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..budget import clip_with_notice
from ..config import Settings
from ..notes.store import make_store
from ..safety import PathRejected, resolve_note_path


@dataclass(frozen=True, slots=True)
class ReadOutcome:
    text: str
    total_chars: int
    truncated: bool


def read_note(settings: Settings, path: str, *, advice: str) -> ReadOutcome:
    """读单篇全文，超过 max_note_chars 截断并标注。

    越界/不存在/类型不符都会抛 PathRejected（调用方负责翻译成协议错误）。
    """
    target = resolve_note_path(settings.root, path)  # 越界/不存在/类型不符都会抛 PathRejected
    try:
        note = make_store(settings).load_note(target)
    except PathRejected:
        raise
    except OSError as exc:
        # 校验通过后、读盘之前文件被删/被移走的竞态：不要让裸 OSError
        # 漏到协议层，统一转成模型能读懂的 PathRejected。
        raise PathRejected(
            f"笔记读取失败：{path}",
            "文件可能在读取时被删除或移动，请先读 notes://index 确认路径再重试。",
        ) from exc

    text, truncated = clip_with_notice(
        note.text,
        settings.max_note_chars,
        advice,
    )
    return ReadOutcome(text=text, total_chars=len(note.text), truncated=truncated)
