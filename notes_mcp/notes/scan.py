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

    符号链接：只跟随解析后仍落在根目录内的目标。指向根目录外的链接
    会被跳过——否则 search / list_recent 会把根外文件的内容泄漏进结果，
    read_note 的 resolve 校验拦得住单篇读取，却拦不住扫描。

    目录链接也一样跟随：`rglob` 不跟随目录链接，所以这里改用手动递归
    （`iterdir` + 栈）。每进入一个目录前先 resolve，并用"已访问的
    已解析目录集合"去重——既防循环链接（A→B→A）无限递归，也防两个
    链接指向同一目录时同一篇笔记被扫两次。每层条目按名字排序后深度
    优先遍历，两个链接指向同一目录时按字典序先到的路径为准。

    只有符号链接才需要 resolve()：普通文件不可能解析到根外；
    每文件一次 resolve 是 1000 篇规模下约 0.4 s 的系统调用开销，
    is_symlink() 一次 lstat 就够了。目录只 resolve 一次，目录数量
    远少于文件数，开销可忽略。
    """
    resolved_root = root.resolve()
    found: list[Path] = []
    visited: set[Path] = {resolved_root}
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        # 按名字升序处理：同一层内先处理的目录先占 visited，
        # 两个链接指向同一目录时，字典序先到的路径为准，结果确定。
        for entry in entries:
            if entry.is_dir():
                # 隐藏目录与 SKIP_DIRS 直接不进：与旧的 rglob + 父级过滤等价。
                if entry.name.startswith(".") or entry.name in SKIP_DIRS:
                    continue
                try:
                    resolved = entry.resolve(strict=False)
                except (OSError, RuntimeError):
                    # 目标不存在或符号链接成环：跳过，不让扫描失败。
                    continue
                if not resolved.is_relative_to(resolved_root):
                    continue
                if resolved in visited:
                    continue
                visited.add(resolved)
                stack.append(entry)
                continue
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            if entry.name.startswith("."):
                continue
            if entry.is_symlink():
                try:
                    resolved = entry.resolve(strict=False)
                except OSError:
                    continue
                if not resolved.is_relative_to(resolved_root):
                    continue
            found.append(entry)
    found.sort(key=lambda p: p.relative_to(root).as_posix())
    return found
