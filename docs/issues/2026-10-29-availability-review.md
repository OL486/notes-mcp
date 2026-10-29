# [可用性审查] 未闭合代码块导致标签归零 / 索引构建 O(n²) / 空结果截断提示含糊

> 本文就是 issue 正文，可整段粘贴到 GitHub。
> 对应分支：`fix/code-issues`。全部改动已附回归测试。

## 背景

对 `OL486/notes-mcp` 做了一次全局运行可用性审查，覆盖四件事：能不能装、能不能跑、
边界输入会不会崩、预算承诺是否守得住。

结论：**可用**。分层清晰（`config → safety → store → budget → tools/resources → server`，
无循环依赖），三条工程约束（路径安全、上下文预算、结构化错误）都真正落实了，
不是写在 README 里好看的。

审查中发现 4 处可修复问题（3 处代码 + 1 处 CI 缺陷），均已修复并补上回归测试。

---

## 问题 1：未闭合代码块会让整篇笔记的标签统计归零

**文件**：`notes_mcp/store.py` → `_strip_fenced_code`

**复现**：

```python
from notes_mcp.store import extract_tags

text = "# 标题\n\n```python\n# 这不是标签\n\n正文 #real-tag\n"
print(extract_tags(text))   # 修复前：()   ← 标签全丢
```

**原因**：一旦遇到 ` ``` ` 就进入 fence 状态，把后续每一行替换成空行。如果文件直到结尾
都没有闭合标记，`fence` 永远不为 `None`，于是**代码块之后的所有正文都被当成代码块抹掉**。

笔记里少写一个结尾 ` ``` ` 是很常见的编辑疏漏，代价却是整篇标签消失、
`notes_stats` 的标签分布失真——而标签分布恰恰是模型判断"该不该检索这篇"的依据。

**修复**：记录最后一次进入 fence 的行号；循环结束后若 `fence` 仍未闭合，
把从该行到文件末尾的内容**恢复为普通文本**。已闭合代码块的过滤能力保持不变。

**回归测试**（`tests/test_store.py`，+3）：

| 用例 | 断言 |
|---|---|
| `test_unclosed_fence_does_not_swallow_rest_of_file` | 未闭合后仍能提取 `#real-tag` |
| `test_closed_fence_still_hides_code_tags` | 已闭合代码块内的 `# 注释` 仍被过滤 |
| `test_multiple_fences_last_unclosed` | 前面闭合、最后一个未闭合时互不干扰 |

---

## 问题 2：`build_index` 的 O(n²) 序列化

**文件**：`notes_mcp/resources.py` → `build_index`

**原因**：每追加一条笔记就 `json.dumps` 整个 entries 列表来量体积。第 k 次序列化的代价是
O(k)，总计 O(n²)。200 篇还能忍，笔记库上千篇后 `notes://index` 会明显变慢。

**修复**：

1. 先一次性构建全部条目；
2. 全部放得下 → 直接返回（快速路径，1 次序列化）；
3. 放不下 → **二分查找**能放入预算的最大条目数，序列化次数从 O(n) 降到 O(log n)。

二分下界取 `0` 而不是 `1`：预算被压到极低时连单条都放不下，必须允许返回 0 条，
否则"预算上限"这个承诺会被打破。

**回归测试**（`tests/test_resources.py`，+3）：

| 用例 | 断言 |
|---|---|
| `test_index_serialized_size_never_exceeds_budget` | 200 篇 / 2000 预算下序列化长度 ≤ 预算 |
| `test_index_uses_budget_instead_of_returning_one_entry` | 50 篇 / 3000 预算下返回 ≥ 10 条（实测 15 条），不是保守的 1 条 |
| `test_index_empty_root_is_valid` | 空目录返回 `count=0, truncated=false` 的合法 JSON |

---

## 问题 3：所有结果块都放不下时，提示写成"只返回了前 0 个"

**文件**：`notes_mcp/budget.py` → `fit_blocks`

**复现**：

```python
from notes_mcp.budget import fit_blocks
text, count, truncated = fit_blocks(["x" * 5000], 300, header="")
# 修复前：……只返回了前 0 个。请缩小范围后重试。
# 修复后：……未返回任何内容。请缩小范围后重试。
```

**原因**：`count == 0` 时仍复用"前 {count} 个"的句式。对模型来说"前 0 个"是无效信息，
它无法区分"没命中"和"命中了但没塞进预算"，于是会原样重试。

**修复**：`count == 0` 时改用独立文案。

**回归测试**（新增 `tests/test_budget.py`，8 个用例）：

- `test_fit_blocks_returns_zero_when_remainder_is_useless`
- `test_fit_blocks_first_block_is_clipped_not_dropped`
- `test_fit_blocks_notice_counts_against_budget`
- `test_clip_text_prefers_line_boundary` / `test_clip_text_hard_cuts_when_no_newline`
- `test_clip_with_notice_stays_within_budget` / `test_fit_blocks_all_fit`
- `test_clip_text_no_truncation_when_short_enough`

---

## 问题 4（CI 缺陷）：Windows runner 上脚本打印中文直接崩

**文件**：`scripts/verify.py`、`scripts/budget_report.py`、`scripts/demo_weekly_review.py`、`.github/workflows/ci.yml`

**现象**：CI 矩阵里 `ubuntu-latest` 三个 job 全绿，`windows-latest` 三个 job 全红，
失败步骤都是"端到端自检（真实 stdio 传输）"。

**日志**：

```text
File "scripts/verify.py", line 68, in part_a
    print("\n=== A. 功能（SDK Client, mode=2026-07-28）===")
UnicodeEncodeError: 'charmap' codec can't encode characters in position 9-11
```

**原因**：GitHub Actions 的 `windows-latest` runner 默认代码页是 **cp1252**（不是中文 Windows 的 GBK）。
Python 的 stdout 跟着代码页走，`print` 中文直接抛 `UnicodeEncodeError`。
脚本第一句就崩，后面 22 项检查一项都没跑到。

注意这与被测代码无关——`pytest` 在同一个 job 里是 `74 passed`。纯粹是脚本自己的输出问题。

**为什么之前没暴露**：`notes_mcp/__main__.py` 早就对 **stderr** 做了 `reconfigure(encoding="utf-8")`
（那是为了 MCP 的 stdout 纯净度），但 `scripts/` 下的独立脚本没有做，而它们恰恰是 CI 唯一会跑的
端到端入口。本地中文 Windows 是 GBK，能编出中文，所以本地跑不出问题。

**修复**：

1. 三个脚本各自在入口处 `reconfigure` stdout/stderr 为 UTF-8
   （与 `__main__.py` 处理 stderr 的做法保持一致，`errors="replace"` 保证不因个别字符再次崩）；
2. `ci.yml` 增加 `PYTHONIOENCODING: utf-8` 与 `PYTHONUTF8: "1"` 兜底，
   覆盖 pytest 采集阶段的输出以及将来新增的脚本。

**本地复现方式**（不用等 CI）：

```bash
PYTHONIOENCODING=cp1252 python -c "print('=== A. 功能 ===')"
# 修复前：UnicodeEncodeError: 'charmap' codec can't encode characters
```

---

## 验证方式（可直接执行）

```bash
# 推荐：uv
uv sync
uv run pytest                      # 原有 60 个 + 新增 14 个
uv run python scripts/verify.py    # 22 项端到端（含 stdout 纯净度）
uv run python scripts/budget_report.py

# 没有 uv 时
python -m pip install -e . pytest anyio
python -m pytest
```

**CI 实测结果（ubuntu / windows × py3.11 / 3.12 / 3.13，六个 job）**：

- 六个 job 全部 success
- `pytest` **74 passed**（原有 60 + 新增 14）
- `scripts/verify.py` 22 项端到端全部通过（含 stdout 每行必须是合法 JSON）

修复点另有等价独立脚本逐条验证：未闭合 fence 提取出 `('real-tag',)`、
`fit_blocks(…, 300)` 返回 `count=0` 且含"未返回任何内容"、
`build_index(100 篇)` 耗时约 75 ms、200 篇 / 2000 预算下长度 1734 ≤ 2000。

---

## 拓展建议（按性价比排序）

### 1. 给 `build_index` 加性能回归测试（低成本，高收益）

现在只断言"不超预算"，没断言"够快"。建议加一条 1000 篇的耗时阈值用例，
防止将来有人把二分改回线性累加——这种退化不会让任何功能测试变红。

### 2. 索引缓存（中成本）

`load_all` 每次调用都全量 rglob + 读盘。`search_notes` / `list_recent` / `notes_stats` /
`build_index` 四个原语各自扫一遍，一次对话里经常重复扫同一批文件。
建议加一个以 `(root, 文件数, 最大 mtime)` 为键的进程内缓存，命中时省掉大部分 IO。
**注意 mtime 变化必须能让缓存失效**，否则会读到旧内容——这比慢更糟。

### 3. 错误结构统一为两段式（低成本）

`PathRejected` 已经是"错在哪 + 怎么改"的两段式，但 `QueryRejected` 只有一句话。
建议给 `QueryRejected` 也补 `hint` 字段，让模型收到的每个错误都同构。

### 4. 补齐预算类环境变量（低成本）

`config.py` 目前只暴露 `NOTES_MCP_MAX_NOTE_CHARS` 和 `NOTES_MCP_SEARCH_BUDGET`，
`index_budget` / `recent_budget` / `stats_budget` 只能改代码。
对想进一步压缩上下文的用户不友好，建议一并暴露。

### 5. 增量索引（高成本，10 万篇再考虑）

改造顺序建议：SQLite FTS5 → cursor 分页 → mtime 增量。ISSUE.md 已给方向，可作为独立任务。

---

## 变更范围

| 文件 | 变更 |
|---|---|
| `notes_mcp/store.py` | 未闭合 fence 恢复逻辑 |
| `notes_mcp/resources.py` | 二分查找裁剪，下界 0 |
| `notes_mcp/budget.py` | 空结果截断文案 |
| `scripts/verify.py` / `budget_report.py` / `demo_weekly_review.py` | 入口处 reconfigure stdout/stderr 为 UTF-8 |
| `.github/workflows/ci.yml` | 增加 `PYTHONIOENCODING` / `PYTHONUTF8` |
| `tests/test_store.py` | +3 用例 |
| `tests/test_resources.py` | +3 用例 |
| `tests/test_budget.py` | 新增，8 用例 |

无破坏性变更：公开函数签名、返回值形态、错误类型全部保持不变。
