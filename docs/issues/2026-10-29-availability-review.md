# 可用性审查：4 处修复

对 notes-mcp 做了一轮可用性检查，范围是安装、运行、边界输入、预算约束。

结论是可用。分层没有循环依赖，路径安全、上下文预算、结构化错误这三件事都落在了代码里。
发现 4 个问题，已修复，改动在 `fix/code-issues` 分支。

## 1. 未闭合代码块会让标签统计归零

`notes_mcp/store.py` 的 `_strip_fenced_code` 遇到 ` ``` ` 就进入 fence 状态，把后续每行替换成空行。
文件结尾没有闭合标记时 `fence` 一直不为 None，于是代码块之后的正文全部被抹掉。

```python
from notes_mcp.store import extract_tags

text = "# 标题\n\n```python\n# 这不是标签\n\n正文 #real-tag\n"
extract_tags(text)   # 修复前：()
```

笔记里漏写结尾的 ` ``` ` 很常见，代价是整篇的标签消失，`notes_stats` 的标签分布跟着失真。

改法是记下最后一次进入 fence 的行号，循环结束后若仍未闭合，把该行到文件末尾的内容恢复成原文。
已闭合代码块的过滤行为不变。

`tests/test_store.py` 加了 3 个用例，覆盖未闭合、已闭合、多 fence 且最后一个未闭合。

## 2. build_index 的 O(n²) 序列化

`notes_mcp/resources.py` 里每追加一条笔记就把整个 entries 列表 `json.dumps` 一遍来量体积。
第 k 次序列化代价是 O(k)，总计 O(n²)。200 篇还看不出问题，上千篇之后 `notes://index` 会明显变慢。

改成先一次性构建全部条目：全部放得下就直接返回（一次序列化）；放不下就用二分查找定位能装进预算的最大条目数，
序列化次数从 O(n) 降到 O(log n)。

二分的下界取 0 而不是 1。预算被压到很低时可能连单条都装不下，这时要允许返回 0 条，否则预算上限守不住。

`tests/test_resources.py` 加了 3 个用例。其中 `test_index_uses_budget_instead_of_returning_one_entry`
断言 50 篇 / 3000 预算下至少返回 10 条（实测 15 条），用来防"二分写保守了只返回 1 条"。

## 3. 结果块全部放不下时，提示写成「只返回了前 0 个」

`notes_mcp/budget.py` 的 `fit_blocks` 在 `count == 0` 时仍然复用「前 {count} 个」的句式：

```python
from notes_mcp.budget import fit_blocks
text, count, truncated = fit_blocks(["x" * 5000], 300, header="")
# 修复前：……只返回了前 0 个。请缩小范围后重试。
# 修复后：……未返回任何内容。请缩小范围后重试。
```

「前 0 个」对模型没有信息量，它区分不了「没命中」和「命中了但没塞进预算」，容易原样重试。

新增 `tests/test_budget.py`，8 个用例覆盖 clip、clip_with_notice、fit_blocks 三条路径。

## 4. Windows runner 上脚本打印中文直接崩

CI 矩阵里 ubuntu 三个 job 全绿，windows 三个 job 全红，失败步骤都是「端到端自检」。

```text
File "scripts/verify.py", line 68, in part_a
    print("\n=== A. 功能（SDK Client, mode=2026-07-28）===")
UnicodeEncodeError: 'charmap' codec can't encode characters in position 9-11
```

GitHub Actions 的 windows-latest runner 默认代码页是 cp1252，不是中文 Windows 的 GBK。
Python 的 stdout 跟随代码页，print 中文直接抛 UnicodeEncodeError，脚本第一句就退出，
后面 22 项检查一项都没跑到。

同一个 job 里 `pytest` 是 74 passed，所以这和被测代码无关。

之前没暴露的原因：`notes_mcp/__main__.py` 早就给 stderr 做过 `reconfigure(encoding="utf-8")`
（为了 stdout 纯净度），但 `scripts/` 下的独立脚本没做，而它们正是 CI 唯一会跑的端到端入口。
本地中文 Windows 是 GBK，能编出中文，本地跑不出来。

修了两处：三个脚本各自在入口 reconfigure stdout/stderr 为 UTF-8（`errors="replace"`，避免个别字符再次中断）；
`ci.yml` 加 `PYTHONIOENCODING: utf-8` 和 `PYTHONUTF8: "1"` 兜底，覆盖 pytest 采集阶段的输出。

本地复现不需要等 CI：

```bash
PYTHONIOENCODING=cp1252 python -c "print('=== A. 功能 ===')"
# UnicodeEncodeError: 'charmap' codec can't encode characters
```

## 验证

```bash
uv sync
uv run pytest                      # 60 原有 + 14 新增
uv run python scripts/verify.py    # 22 项端到端
uv run python scripts/budget_report.py

# 没有 uv 时
python -m pip install -e . pytest anyio
python -m pytest
```

CI 六个 job（ubuntu / windows × py3.11 / 3.12 / 3.13）全部通过，`pytest` 74 passed，
`verify.py` 22 项全过。

修复点另外用独立脚本逐条确认过：未闭合 fence 提取出 `('real-tag',)`；
`fit_blocks(…, 300)` 返回 `count=0` 且文案含「未返回任何内容」；
`build_index(100 篇)` 约 75 ms，200 篇 / 2000 预算下长度 1734。

## 后续可做

- `build_index` 现在只断言不超预算，没断言耗时。加一条 1000 篇的阈值用例，防止二分被改回线性累加——这种退化不会让功能测试变红。
- `load_all` 每次调用都全量 rglob 加读盘，`search_notes` / `list_recent` / `notes_stats` / `build_index` 各扫一遍。可以加进程内缓存，键用 `(root, 文件数, 最大 mtime)`。mtime 变化要能让缓存失效，读到旧内容比慢更麻烦。
- `PathRejected` 是「错在哪 + 怎么改」两段式，`QueryRejected` 只有一句。补个 `hint` 字段对齐。
- `config.py` 只暴露了 `NOTES_MCP_MAX_NOTE_CHARS` 和 `NOTES_MCP_SEARCH_BUDGET`，`index_budget` / `recent_budget` / `stats_budget` 只能改代码，建议一并做成环境变量。
- 10 万篇以上再考虑增量索引，顺序是 SQLite FTS5 → cursor 分页 → mtime 增量。

## 变更文件

| 文件 | 变更 |
|---|---|
| `notes_mcp/store.py` | 未闭合 fence 恢复原文 |
| `notes_mcp/resources.py` | 二分查找裁剪，下界 0 |
| `notes_mcp/budget.py` | 空结果文案 |
| `scripts/verify.py`、`budget_report.py`、`demo_weekly_review.py` | 入口 reconfigure stdout/stderr |
| `.github/workflows/ci.yml` | `PYTHONIOENCODING` / `PYTHONUTF8` |
| `tests/test_store.py` | +3 |
| `tests/test_resources.py` | +3 |
| `tests/test_budget.py` | 新增 8 |

公开函数签名、返回值形态、错误类型都没有变。
