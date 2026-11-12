"""扫描：列出根目录下所有候选笔记文件。

后缀白名单原来放在 safety.py（"扫描该读哪些后缀"本应属于 store 的职责），
现已迁到这里；safety.py 从这里 re-export，保持旧导入可用。
"""

from __future__ import annotations

from pathlib import Path

ALLOWED_SUFFIXES = frozenset({".md", ".markdown"})
"""只允许 Markdown。少一类文件就少一类被读取的理由。"""

SKIP_DIRS = frozenset({".git", ".obsidian", ".trash", "node_modules", "__pycache__", ".venv"})
"""这些目录里的文件不是"笔记"，扫进来只会污染统计和检索结果。"""


def iter_note_files(root: Path) -> list[Path]:
    """列出根目录下所有候选笔记文件，按路径排序保证输出稳定。

    排序很重要：不稳定顺序会让同一查询两次返回不同结果，模型会以为数据变了。
    """
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        rel_parts = path.relative_to(root).parts
        # 只看父级目录：文件名以 . 开头也算隐藏文件，一并跳过。
        if any(part.startswith(".") or part in SKIP_DIRS for part in rel_parts[:-1]):
            continue
        if rel_parts[-1].startswith("."):
            continue
        found.append(path)
    found.sort(key=lambda p: p.relative_to(root).as_posix())
    return found
