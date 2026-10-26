# [项目] notes-mcp：从零实现一个只读本地笔记 MCP Server（MCP 2026-07-28）

> 这份文件就是 issue 正文，可以整段粘贴到 GitHub。
> 代码已在本地完成并通过 `pytest`（60 个用例）+ `scripts/verify.py`（22 项端到端检查），
> 下方「交付清单」即当前实际状态。逐阶段的协议报文与讲解见 `docs/WALKTHROUGH.md`。

---

## 背景

目标不是"接一个现成的 MCP server"，而是**通过自己写一个来理解 MCP 协议**，
最终让本地 AI 助手能读我的 Markdown 笔记、完成真实任务。

选"只读笔记"作为题材，因为它是 MCP 里最典型的**上下文供给**场景，而且天然带三个真问题：

- `path` 参数来自模型，是不可信输入 → **路径安全**；
- 笔记可能很长，一次全吐回去会吃掉客户端上下文 → **上下文预算**；
- 模型调错参数时必须能自我纠正 → **结构化错误**。

这三个问题都不是"能跑就行"能覆盖的，而它们恰好是 MCP server 里最容易做错、
也最影响实际体验的部分。

## 目标

1. 一个真实可用的 MCP server：四个 Tool、两个 Resource、一个 Prompt
2. 严格跑在 `2026-07-28` 规范上（无状态、逐请求信封、`server/discover` 探测），
   同时兼容 2025 时代的 `initialize` 握手客户端
3. 每个返回值都有**明确的字符上限**，超限必须自报"已截断"
4. 所有失败都是**模型能读懂并据此纠正**的文本，而不是堆栈
5. 每个阶段都有可复现的验收命令

## 范围

**包含**：`search_notes` / `read_note` / `list_recent` / `notes_stats`；
`notes://index` 与 `notes://note/{+path}`；`weekly-review` prompt；stdio + Streamable HTTP 两种传输。

**不包含**（刻意排除）：写入/删除、向量检索、笔记间的引用图、Obsidian 双链解析、认证。

---

## 交付清单

- [x] **S0** 骨架跑通：`uv` 建项目、`mcp[cli]`、stderr 日志铁律、Inspector modern 验收
- [x] **S1** `search_notes`：片段化检索 + 8000 字符预算 + 窗口合并与限长
- [x] **S2** `read_note`：路径安全（绝对路径 / `..` / 符号链接逃逸三种用例）
- [x] **S3** Resources：`notes://index`（JSON）+ `notes://note/{+path}`（模板）
- [x] **S4** `weekly-review` prompt + 上下文预算实测表
- [x] **S5** 客户端接入配置（Claude Desktop / Cursor）+ 真实任务调用序列
- [x] **S6** Streamable HTTP 传输（含有状态 / 无状态两种模式实测）
- [x] 60 个 pytest 用例（含 8 个端到端：真起子进程走 stdio）
- [x] `scripts/verify.py`：22 项检查，含 **stdout 纯净度**（每行必须是合法 JSON-RPC）
- [x] 6 篇示例笔记 + 可复现的 mtime 脚本

---

## 阶段计划与验收

| 阶段 | 验收命令 | 通过标准 |
|---|---|---|
| S0 | `npx @modelcontextprotocol/inspector@2.12.0 --cli --protocol-era modern uv run notes-mcp --root ./sample_notes --method tools/list` | 列出 4 个工具；stdout 无任何非协议输出 |
| S1 | `uv run pytest tests/test_search.py -v` | 返回片段（带行号）而非全文；每篇 ≤3 段；总长 ≤8000 |
| S2 | `uv run pytest tests/test_safety.py -v` | `../../etc/passwd`、`/etc/passwd`、软链接逃逸全部拒绝，且返回可读说明 |
| S3 | `uv run pytest tests/test_resources.py -v` | index 是合法 JSON 且 `count` 正确；单篇 URI 可读；越界 URI 被拒 |
| S4 | `uv run python scripts/budget_report.py` | 6 个原语的实测最大返回全部落在各自上限内 |
| S5 | `uv run python scripts/demo_weekly_review.py MCP` | 依次出现 `list_recent(days=7)` → `search_notes` → `read_note` |
| S6 | `uv run notes-mcp --transport streamable-http --stateless-http --port 8932` | 无 session 直接 `tools/list` 也能返回（SSE 格式） |

---

## 关键结果

### 上下文预算（实测，不是估算）

构造最坏情况：200 篇笔记 × 600 行、每行都命中、每行 40 字符。

| 原语 | 实测最大返回 | 约束 | 行为 |
|---|---:|---|---|
| `search_notes(query, limit=20)` | **7,631** | 预算 8000 | 命中 200 篇 → 实际返回 3 篇，`truncated=true` |
| `read_note(超长笔记)` | **19,836** | 上限 20000 | 含截断提示 |
| `list_recent(days=3650)` | **3,994** | 预算 4000 | 200 篇全在窗口内 |
| `notes_stats` | **442** | 预算 3000 | 50 个标签 |
| `notes://index` | **7,642** | 预算 8000 | 200 篇 → 返回 37 条 |
| `notes://note/{path}` | **19,828** | 上限 20000 | 含截断提示 |

单次调用最坏约 **20,000 字符**（≈ 10K-14K 中文 token），占 200K 窗口的 5-7%。
一次"检索 + 读两篇"的任务最多吃 60K，仍在安全区。

### 环境事实核对（开工前做的，避免照记忆写代码）

| 项目 | 实测值 | 核对方式 |
|---|---|---|
| 规范版本 | `2026-07-28` | `mcp_types.version.KNOWN_PROTOCOL_VERSIONS[-1]`；官网 spec 页标题一致 |
| Python SDK | `mcp 2.3.0` | `importlib.metadata.version("mcp")` |
| 导入方式 | `from mcp.server import MCPServer` | `dir(mcp.server)` 有 `MCPServer`，**无** `FastMCP` |
| 现代时代判定 | `MODERN_PROTOCOL_VERSIONS == ("2026-07-28",)` | 同文件常量 |
| 探测方法 | `server/discover` | `mcp_types.methods.CLIENT_REQUESTS` 的 key |
| Inspector | `2.12.0`，`--protocol-era {legacy,auto,modern}` | `npx @modelcontextprotocol/inspector --cli --help` |
| Resources 注册 | `@server.resource(uri, *, name, title, description, mime_type, ...)` | `inspect.signature(MCPServer.resource)` |
| 工具错误 | `raise ToolError("...")` → `isError:true` + 可读文本 | 实跑抓包 |

### 规模

- 服务端 `notes_mcp/` 1257 行（10 个文件，零额外依赖）
- 测试 694 行 / 60 个用例；脚本 412 行

---

## 三条工程约束的落实

### 1. 路径安全

```python
target = (root / normalized).resolve(strict=False)
if not target.is_relative_to(root):
    raise PathRejected(f"路径越界：{raw} 解析后落在笔记根目录之外",
                       "只允许笔记根目录内的相对路径（符号链接指向外部同样会被拒绝）")
```

**`is_relative_to` 必须在 `resolve()` 之后。** 这是唯一有效的一步：
一个名叫 `escape.md` 的符号链接在字符串层面毫无破绽，只有展开后才暴露它指向根目录外。

另外三个细节：`root` 在配置加载时就 resolve（否则根目录自身带软链接会误判）；
`strict=False` 让"越界"和"不存在"能给出两种不同错误；反斜杠先归一化成正斜杠
（`..\..\x` 在 POSIX 语义的 `Path` 里是一整个文件名，`..` 检查会漏）。

### 2. 上下文预算

`search_notes` 绝不返回整篇。三条规则，每条都对应一次真实翻车：

1. 片段是语义单位，放不下就整体不塞；
2. **但第一块放不下必须裁，不能直接丢**——否则一篇命中 200 行的笔记会导致
   "命中 200 篇、返回 0 篇"，模型完全无法行动；
3. **截断提示本身也算预算**，否则"8000 预算"实际吐 8200，预算表就是假的。

### 3. 结构化错误

`PathRejected` / `QueryRejected` 在 `server.py` 被显式翻译成 `ToolError`：

```json
{"jsonrpc":"2.0","id":4,"result":{
  "content":[{"type":"text","text":"Error executing tool read_note: 拒绝路径穿越：../../etc/passwd。路径中不允许出现 ..，请使用根目录内的相对路径"}],
  "isError":true,"resultType":"complete"}}
```

关键认知：**工具失败时 JSON-RPC 层面是"成功"的**，错误装在同一条 `result` 里，
只是 `isError` 为 `true`。这是刻意设计——让模型能读到错误文本并自我纠正。
如果抛未捕获异常，模型只会看到 `Error executing tool read_note`，学不到任何东西。

---

## 实现中真实踩到的坑

比"理论上的陷阱"更有价值，全部记在 `docs/WALKTHROUGH.md` 附录：

1. **`_meta` 的键是 camelCase**（`io.modelcontextprotocol/protocolVersion`）。
   写成 kebab-case 会得到 `-32602 Invalid request parameters`，不提示缺哪个字段，极易误判成业务 bug。
2. **标签统计全是 0**：用 `line.startswith("#")` 剔标题，把整行 `#mcp #protocol` 也剔了。
   标题判定必须用 `^\s{0,3}#{1,6}\s`（`#` 后必须跟空白）。
3. **`search_notes` 返回"命中 200 篇、返回 0 篇"**：单个片段超过总预算，一个都塞不进去。
   修法 = 片段限长 15 行 + 第一块放不下时裁剪而非丢弃。
4. **预算表说 8000、实测 11,195**：`notes://index` 的体积估算漏了 `indent=2` 的缩进。
   改成每加一条就真实序列化一次来量。
5. **`read_note` 超 76 字符**（20,076 > 20000）：截断提示没算进预算。
   统一收口到 `clip_with_notice()`，先按 `budget - 240` 裁正文再拼提示。
6. **中文日志在 Windows 控制台变成 `·��Խ`**：控制台 GBK + rich 按 UTF-8 写。
   修法：`sys.stderr.reconfigure(encoding="utf-8")` 并自己装 handler（`force=True` 顶掉 SDK 的 rich handler）。
7. **`notes://note/a/b.md` 匹配不上**：用了 `{path}`，斜杠被当 URI 分隔符。必须用 `{+path}`（保留展开）。
8. **Inspector 看不到 modern 行为**：CLI 对 ad-hoc 目标默认走 legacy，必须加 `--protocol-era modern`。

### 一个值得单独说的发现

请求 `notes://note/../../../etc/passwd` 返回的不是我写的错误文案，而是：

```json
{"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"Unknown resource: notes://note/../../../etc/passwd"}}
```

因为 `MCPServer` 的 `resource_security` 默认
`ResourceSecurity(reject_path_traversal=True, reject_absolute_paths=True, reject_null_bytes=True)`，
它在**模板参数提取之后、handler 之前**就拒绝了，于是这个 URI 根本没匹配上任何模板。

两个结论：① 别把安全寄托在这一层——Tool 的参数完全不在它的保护范围内，
所以 `resolve_note_path` 必须被工具和资源**共用**；② 我的 resource handler 里仍然保留了
同一套校验，这是有意冗余，防止以后改了 URI 结构或给参数加 `exempt_params` 时防线消失。

---

## 需要指出的三点偏差

1. **Claude Desktop / Cursor 的实际连接我没有验证。** 这个环境起不了图形客户端，
   所以我只给了配置文件和用脚本按 prompt 规定序列跑出来的调用链路。
   客户端侧"模型确实调了 `list_recent` 和 `search_notes`"需要你本地确认一次。
2. **项目是一次性建完的，不是逐阶段停下来等确认。** 因为交付物是"可运行的项目"，
   逐阶段的讲解、报文和验收输出都写在 `docs/WALKTHROUGH.md` 里，可以按 S0→S6 顺序读。
3. **检索是朴素实现**（每次全量读盘逐行匹配）。几千篇以内是毫秒级，
   10 万篇需要倒排索引——改造顺序（SQLite FTS5、cursor 分页、mtime 增量）写在 S1 末尾，
   但没有实现。

---

## 如何验证

```bash
uv sync

# 1. 协议层：确认跑在 2026-07-28 上
npx @modelcontextprotocol/inspector@2.12.0 --cli --protocol-era modern \
  uv run notes-mcp --root ./sample_notes --method tools/list

# 2. 功能 + stdout 纯净度（22 项）
uv run python scripts/verify.py

# 3. 单元 + 端到端（60 个用例）
uv run pytest

# 4. 预算表
uv run python scripts/budget_report.py

# 5. 真实任务调用序列
uv run python scripts/demo_weekly_review.py MCP

# 6. HTTP 传输
uv run notes-mcp --root ./sample_notes --transport streamable-http --port 8932 --stateless-http
```

当前状态：以上 1-6 全部通过。`pytest` 覆盖 60 个用例，其中 8 个是端到端
（真起子进程、走 stdio、发真实 JSON-RPC），包括"stdout 每行必须是合法 JSON"这一条。
