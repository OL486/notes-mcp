# notes-mcp 实施记录（MCP 2026-07-28）

这份文档按阶段记录"做了什么、协议层面发生了什么、怎么验证"。
所有报文都是本机实际抓取的，不是示意；所有版本号都是 2026-10-26 实测的。

---

## 0 · 环境与事实核对

开工前先把几个关键 API 落实到具体版本，避免照着记忆写出跑不起来的代码。

| 项目 | 实测值 | 怎么核对的 |
|---|---|---|
| 规范版本 | `2026-07-28` | `mcp_types.version.KNOWN_PROTOCOL_VERSIONS` 里最后一项；官网 spec 页标题也是这个日期 |
| Python SDK | `mcp 2.3.0`（PyPI 最新） | `pip install "mcp[cli]"` 后 `importlib.metadata.version("mcp")` |
| 导入方式 | `from mcp.server import MCPServer` | `dir(mcp.server)` 里有 `MCPServer`，且**没有** `FastMCP` |
| 协议时代 | `MODERN_PROTOCOL_VERSIONS = ("2026-07-28",)` | 该版本走"无状态逐请求信封"，2025 系列仍走 `initialize` 握手 |
| 探测方法 | `server/discover` | `mcp_types.methods.CLIENT_REQUESTS` 中 `("server/discover", "2026-07-28")` |
| Inspector | `2.12.0`，CLI 支持 `--protocol-era {legacy,auto,modern}` | `npx @modelcontextprotocol/inspector --cli --help` |
| Python | 3.12（uv 自动下载），要求 `>=3.10` | `mcp` 的 `Requires-Python` |

两个容易踩的点，先写在这里：

**`_meta` 的键是 camelCase。** 逐请求信封里的键名是
`io.modelcontextprotocol/protocolVersion`、`io.modelcontextprotocol/clientCapabilities`。
我第一版写成 `protocol-version` / `client-capabilities`，服务端回的是
`-32602 Invalid request parameters`，而不是"缺少字段"——很容易误判成业务代码有 bug。

**响应可以乱序。** 同一个连接里连发 6 个请求，回来的顺序可能是 5、6、3、4。
JSON-RPC 靠 `id` 配对，不要假设顺序。

---

## S0 · 骨架跑通

**目标**：`uv` 建项目、只挂一个 `notes_stats` 工具、日志全部走 stderr。

### 代码

`pyproject.toml` 的关键部分：

```toml
[project]
name = "notes-mcp"
requires-python = ">=3.11"
dependencies = ["mcp[cli]>=2.0.0,<3"]

[project.scripts]
notes-mcp = "notes_mcp.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["notes_mcp"]
```

`notes_mcp/__main__.py` 里把日志钉死在 stderr：

```python
def _configure_stderr_logging(level: str) -> None:
    reconfigure = getattr(sys.stderr, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    logging.basicConfig(level=..., handlers=[handler], force=True)
```

`force=True` 是必须的。SDK 自己会调 `logging.basicConfig(handlers=[RichHandler(...)])`，
而 `basicConfig` 在没有 `force` 时对已配置的 root logger 是 **no-op**——谁先配置谁说了算。
我们显式占位，才能保证：

1. 所有日志都去 stderr（stdio 下 stdout 只能有协议报文）；
2. 编码固定 UTF-8（中文 Windows 控制台默认 GBK，rich 打中文日志会变成 `·��Խ`）；
3. 不被 SDK 的 rich handler 抢走格式。

### 协议层面发生了什么

客户端连上来第一件事**不是** `initialize`，而是探测：

```json
{"jsonrpc":"2.0","id":1,"method":"server/discover",
 "params":{"_meta":{
   "io.modelcontextprotocol/protocolVersion":"2026-07-28",
   "io.modelcontextprotocol/clientCapabilities":{},
   "io.modelcontextprotocol/clientInfo":{"name":"capture","version":"0.1.0"}}}}
```

服务端的真实响应（已删减 `instructions` 字段内容）：

```json
{"jsonrpc":"2.0","id":1,"result":{
  "cacheScope":"private",
  "capabilities":{
    "prompts":{"listChanged":true},
    "resources":{"listChanged":true,"subscribe":true},
    "tools":{"listChanged":true}},
  "resultType":"complete",
  "supportedVersions":["2026-07-28"],
  "ttlMs":0,
  "_meta":{"io.modelcontextprotocol/serverInfo":{
    "name":"notes-mcp","title":"本地笔记（只读）","version":"0.1.0"}}}}
```

`capabilities` 是 SDK 根据你**实际注册了哪几类原语**自动推导的：只注册 tools 就没有
`resources`/`prompts` 字段。`supportedVersions` 里只有 `2026-07-28`，说明这是现代服务端；
如果客户端拿到的是 `-32601 Method not found`，它会退回 2025 的 `initialize` 握手——
`serveStdio` / `MCPServer.run("stdio")` 对这两条路径都兼容。

然后是 `tools/list`。**注意 `inputSchema` 不是我手写的**，是 SDK 从 Python 函数签名
经 pydantic 推导出来的：

```json
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{"_meta":{...}}}
```

```json
{"jsonrpc":"2.0","id":2,"result":{
  "cacheScope":"private","resultType":"complete","ttlMs":0,
  "tools":[
    {"name":"search_notes",
     "description":"按关键词全文检索本地笔记，返回命中行前后各若干行的**片段**…",
     "inputSchema":{
       "type":"object",
       "properties":{
         "query":{"title":"Query","type":"string"},
         "limit":{"default":5,"title":"Limit","type":"integer"}},
       "required":["query"],
       "title":"search_notesArguments"}},
    {"name":"read_note","inputSchema":{...}},
    {"name":"list_recent","inputSchema":{...}},
    {"name":"notes_stats","inputSchema":{"type":"object","properties":{},"title":"notes_statsArguments"}}
  ]}}
```

这里能直接看到"Python 函数 → 协议对象"的映射：函数名 → `name`，
docstring/description → `description`，参数类型注解 → `inputSchema.properties`，
默认值 → `default`，无默认值的参数 → `required`。

### 验收命令 + 预期输出

```bash
npx @modelcontextprotocol/inspector@2.12.0 --cli \
  --protocol-era modern \
  uv run notes-mcp --root ./sample_notes \
  --method tools/list
```

实际输出（节选）：

```json
{
  "tools": [
    {"name": "search_notes", "description": "按关键词全文检索本地笔记…",
     "inputSchema": {"type":"object","properties":{...},"required":["query"]}},
    {"name": "read_note", ...},
    {"name": "list_recent", ...},
    {"name": "notes_stats", ...}
  ]
}
```

`--protocol-era modern` 不能省。Inspector CLI 对 ad-hoc 目标（直接给命令而不是
`--config`）默认走 **legacy**，你会看到 2025 的握手流程，从而误判 SDK 版本。

另外单独验一次 stdout 纯净度（`scripts/verify.py` 的 B 段做这件事）：
连发 4 个请求，stdout 必须正好 4 行、每行都是合法 JSON、没有别的输出。

---

## S1 · `search_notes`：片段化与字节预算

**目标**：返回命中行上下文片段而不是整篇，并把总量压在 8000 字符内。

### 朴素实现

`notes_mcp/store.py`，全文读进内存逐行匹配：

```python
def search_notes(notes, query, *, fragments_per_note, context_lines, max_fragment_lines=15):
    needle = query.strip().lower()
    if not needle:
        return []
    hits = []
    for note in notes:
        lines = note.text.splitlines()
        matched = [i for i, line in enumerate(lines) if needle in line.lower()]
        if not matched:
            continue
        windows = _merge_windows(matched, len(lines), context_lines, max_fragment_lines)
        fragments = tuple(
            Fragment(start=s, end=e, lines=tuple(lines[s:e + 1]))
            for s, e in windows[:fragments_per_note])
        hits.append(NoteHit(note=note, fragments=fragments, hit_lines=len(matched)))
    hits.sort(key=lambda h: (-h.hit_lines, -h.note.mtime, h.note.rel))
    return hits
```

窗口合并是这段的核心：

```python
def _merge_windows(matched, total_lines, context, max_lines):
    windows = []
    for index in matched:
        start = max(0, index - context)
        end = min(total_lines - 1, index + context)
        if windows:
            prev_start, prev_end = windows[-1]
            merged_end = max(prev_end, end)
            if start <= prev_end + 1 and merged_end - prev_start + 1 <= max_lines:
                windows[-1] = (prev_start, merged_end)
                continue
        windows.append((start, end))
    return windows
```

两个条件缺一不可：

- **合并**：不合并的话，一段连续 5 行都命中的笔记会返回 5 个几乎一样的片段，三份预算吃一份内容。
- **限长 15 行**：只合并不限长，一篇 200 行全命中的笔记会合成一个 200 行巨型片段。
  这不是理论问题——我第一版没有这个上限，`search_notes` 在压测库里返回
  **"命中 200 篇、返回 0 篇"**：单个片段就超过 8000 字符，一个都塞不进去。

### 预算拼装

`notes_mcp/budget.py` 的 `fit_blocks` 有三条规则，每条都对应一次翻车：

```python
for block in blocks:
    if used + len(block) <= budget:
        kept.append(block); used += len(block); continue
    truncated = True
    remainder = budget - used
    if remainder >= MIN_USEFUL_REMAINDER:      # 规则 2：第一块放不下要裁，不能直接丢
        clipped, _ = clip_text(block, remainder - 60)
        kept.append(clipped + "\n…（本片段已截断）\n")
    break
```

1. 块是语义单位，放不下就整体不塞——半块内容对模型没用；
2. 但**第一块放不下时必须裁**，否则就是上面那个"返回 0 篇"；
3. **截断提示本身也算预算**。否则"8000 预算"实际吐 8200，预算表就是假的。
   实现上是在拼完之后再检查一次总长，超了就从尾部丢块：

```python
while kept and len(text) + len(_notice(len(kept))) > budget:
    kept.pop()
    text = header + "".join(kept)
```

### 协议层面发生了什么

模型决定搜索时，客户端发的是：

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call",
 "params":{"_meta":{...},"name":"search_notes",
           "arguments":{"query":"上下文预算","limit":2}}}
```

真实响应（`result.content[0].text` 就是函数返回值）：

```json
{"jsonrpc":"2.0","id":3,"result":{
  "content":[{"type":"text","text":
    "检索 “上下文预算”：命中 3 篇笔记，返回前 2 篇的片段（每篇最多 3 段，每段前后 2 行）。\n\n### daily/2026-10-26.md  ·  2026-10-26 日志\n[第 15-19 行]\n   15 | \n   16 | - 实现 resources\n   17 | - 做上下文预算表\n   18 | - 接 Claude Desktop 实测一次真实任务\n   19 | \n\n### inbox/2026-10-24-mcp-day1.md  ·  MCP 协议学习笔记（第一天）\n[第 20-24 行]\n   20 | \n   21 | - [ ] 把 notes-mcp 的 search_notes 改成返回片段而不是全文\n…"}],
  "isError":false,
  "resultType":"complete"}}
```

要点：**工具执行成功时 `isError: false`，失败时也是 HTTP/JSON-RPC 层面的"成功"**——
错误装在同一条 `result` 里，只是 `isError` 为 `true`。这是 MCP 的刻意设计：
让模型能看到错误文本并自我纠正，而不是让传输层直接报错。

### 验收

```bash
uv run pytest tests/test_search.py -v
```

覆盖：片段带行号、±2 行上下文、每篇最多 3 段、总长 ≤ 预算 + 提示、无命中给建议、
空 query 报错、`limit` 夹取、大小写不敏感。

实测（`scripts/budget_report.py`，200 篇 × 600 行、每行都命中）：
`search_notes(limit=20)` 返回 **7,631 字符**，命中 200 篇、实际返回 3 篇、`truncated=True`。

### 如果是 10 万篇

现在的实现是"每次调用全量读盘"。10 万篇时这条路走不通（单次调用要读几 GB），
改造顺序建议：

1. **倒排索引 + 落盘**：启动时或按 mtime 增量建 `term -> [(note_id, line_no)]`，
   用 SQLite FTS5（自带中文分词可配 trigram）最省事，不用自己写索引结构。
2. **分页而不是截断**：`search_notes` 加 `cursor` 参数，返回 `nextCursor`，
   让模型自己决定要不要翻下一页——比"截断后让模型改参数重试"更省一轮往返。
3. **增量更新**：以 mtime + size 做指纹，只重扫变化的文件；
   大目录用 `watchdog` 监听文件事件，避免每次全量 stat。
4. **别过早做**：索引带来的缓存一致性问题（写入后忘记失效、软链接重复计入）
   比它省下的那点 CPU 值钱得多。几千篇以内，朴素实现就是最优解。

---

## S2 · `read_note` + 路径安全

**目标**：把模型给的 `path` 收敛到根目录内，三种逃逸方式全部拒绝。

### 代码

`notes_mcp/safety.py` 的核心：

```python
def resolve_note_path(root: Path, raw: str, *, allowed_suffixes=ALLOWED_SUFFIXES,
                      must_exist: bool = True) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise PathRejected("path 不能为空", "请传入相对笔记根目录的 Markdown 路径…")
    if "\x00" in raw:
        raise PathRejected("path 含 NUL 字节", "这是非法输入…")

    normalized = raw.strip().replace("\\", "/")

    if _looks_absolute(normalized):
        raise PathRejected(f"拒绝绝对路径：{raw}", "只接受相对笔记根目录的路径…")

    parts = Path(normalized).parts
    if ".." in parts:
        raise PathRejected(f"拒绝路径穿越：{raw}", "路径中不允许出现 ..…")

    target = (root / normalized).resolve(strict=False)

    if not target.is_relative_to(root):
        raise PathRejected(f"路径越界：{raw} 解析后落在笔记根目录之外",
                           "只允许笔记根目录内的相对路径（符号链接指向外部同样会被拒绝）")
    ...
```

几个决定的理由：

- **`root` 必须已经 resolve 过**（在 `config.load_settings` 里做）。如果根目录本身带符号链接
  而没展开，`is_relative_to` 会拿"未展开的 root"和"展开后的 target"比，正常文件也会被判越界。
- **`resolve(strict=False)`**：文件不存在时也给出确定的绝对路径，
  这样"越界"和"不存在"能返回两种不同的错误。模型需要区分这两件事：
  前者要改路径写法，后者要先去查路径。
- **`is_relative_to` 必须放在 `resolve()` 之后**。这是唯一有效的一步。
  一个名叫 `escape.md` 的符号链接在字符串层面毫无破绽，只有展开后才暴露它指向根目录外。
- **任何 `..` 一律拒绝**，包括 `a/../b` 这种其实还在根内的写法。
  规则简单可预测，模型也更容易学会"不要用 `..`"。
- **反斜杠先归一化**。不归一化的话，`..\..\secret.md` 在 POSIX 语义的 `Path` 里
  是一整个文件名，`..` 检查会漏掉（在 Windows 上则取决于 `Path` 的实现细节，不该赌）。

### 协议层面发生了什么

失败时不是 JSON-RPC error，而是 `result.isError = true`：

```json
{"jsonrpc":"2.0","id":4,"result":{
  "content":[{"type":"text","text":
    "Error executing tool read_note: 拒绝路径穿越：../../etc/passwd。路径中不允许出现 ..，请使用根目录内的相对路径"}],
  "isError":true,
  "resultType":"complete"}}
```

注意 `Error executing tool read_note: ` 这个前缀是 **SDK 自动加的**，来自
`ToolError` 的包装。所以 `ToolError` 的消息只需要写"错在哪 + 怎么改"，
不要自己再重复工具名。

对应关系：

| 你写的代码 | 线上的报文 |
|---|---|
| `return "..."` | `result.content[0].text`，`isError:false` |
| `raise ToolError("...")` | `result.content[0].text = "Error executing tool X: ..."`，`isError:true` |
| 未捕获异常 | `result.content[0].text = "Error executing tool X"`（原文被吞掉），stderr 里打 traceback |
| 未知工具名 / 参数不合 schema | SDK 自己抛 `ToolError`，同样是 `isError:true` |

第三行是重点：**裸异常会让模型失去所有信息**。这也是为什么 `PathRejected` / `QueryRejected`
在 `server.py` 里被显式翻译成 `ToolError`。

### 验收：三个恶意用例

```bash
uv run pytest tests/test_safety.py -v
```

`scripts/verify.py` 里对真实 server 跑的结果：

```
'../../etc/passwd'      -> is_error=True  拒绝路径穿越：../../etc/passwd。路径中不允许出现 ..，请使用根目录内的相对路径
'/etc/passwd'           -> is_error=True  拒绝绝对路径：/etc/passwd。只接受相对笔记根目录的路径，例如 daily/2026-10-01.md
'C:\Windows\win.ini'    -> is_error=True  拒绝绝对路径：C:\Windows\win.ini。只接受相对笔记根目录的路径…
```

第三个用例（软链接目录）需要真正创建符号链接，Windows 上要求开发者模式或管理员权限，
所以测试里是"能建就测，不能建就 skip"：

```python
try:
    os.symlink(tmp_path / "secret.md", notes_root / "escape.md")
except (OSError, NotImplementedError):
    pytest.skip("当前环境不允许创建符号链接（Windows 需要开发者模式或管理员）")

with pytest.raises(PathRejected) as excinfo:
    resolve_note_path(notes_root, "escape.md")
assert "越界" in str(excinfo.value)
```

同时还有一个反向用例 `test_allows_symlink_inside_root`：
指向**根目录内部**的软链接必须放行，否则 Obsidian 那类会建别名链接的笔记工具会被误杀。

---

## S3 · Resources

**目标**：`notes://index`（清单）+ `notes://note/{+path}`（单篇）。

### 注册方式（先核实，不猜）

2.x 的 `MCPServer` 上，Resources 的注册和 Tools 一样是装饰器，签名是：

```python
MCPServer.resource(
    uri: str, *, name=None, title=None, description=None, mime_type=None,
    icons=None, annotations=None, meta=None, security: ResourceSecurity | None = None,
) -> Callable
```

带 `{...}` 的 URI 会被自动识别成**资源模板**（注册到 `resources/templates/list`），
否则是静态资源。所以两个原语只需要一个装饰器：

```python
@server.resource("notes://index", name="notes-index", title="笔记索引",
                 description="全部笔记的清单…", mime_type="application/json")
def notes_index() -> str:
    return build_index(settings)

@server.resource("notes://note/{+path}", name="note", title="单篇笔记",
                 description="按相对路径读取单篇笔记正文…", mime_type="text/markdown")
def note_by_path(path: str) -> str:
    ...
```

`{+path}` 里的 `+` 是 RFC 6570 的"保留展开"：斜杠不做百分号编码。
用 `{path}` 的话，`daily/2026-10-25.md` 的 `/` 会被当成 URI 分隔符而不是参数内容，
匹配不上（或者只能匹配到 `daily`）。

### 协议层面发生了什么

`resources/read` 请求：

```json
{"jsonrpc":"2.0","id":5,"method":"resources/read",
 "params":{"_meta":{...},"uri":"notes://note/daily/2026-10-25.md"}}
```

真实响应：

```json
{"jsonrpc":"2.0","id":5,"result":{
  "cacheScope":"private",
  "contents":[{"mimeType":"text/markdown",
               "text":"# 2026-10-25 日志\n\n## 上午\n\n把 notes-mcp 的骨架跑起来了…",
               "uri":"notes://note/daily/2026-10-25.md"}],
  "resultType":"complete","ttlMs":0}}
```

`contents` 是**数组**，一次可以返回多个表示（比如同一资源的 text 和 blob）。
`cacheScope` / `ttlMs` 是 2026-07-28 的缓存语义：`private` 表示只给单个客户端缓存。

模板列表：

```json
{"jsonrpc":"2.0","id":7,"result":{"resourceTemplates":[
  {"name":"note","description":"…","mimeType":"text/markdown",
   "uriTemplate":"notes://note/{+path}"}]}}
```

### 一个值得记下来的发现：SDK 在路由层就拦了穿越

请求 `notes://note/../../../etc/passwd` 时，返回的不是我写的 `PathRejected` 文案，而是：

```json
{"jsonrpc":"2.0","id":1,"error":{
  "code":-32602,
  "message":"Unknown resource: notes://note/../../../etc/passwd",
  "data":{"uri":"notes://note/../../../etc/passwd"}}}
```

原因：`MCPServer` 的 `resource_security` 默认是
`ResourceSecurity(reject_path_traversal=True, reject_absolute_paths=True, reject_null_bytes=True)`，
它在**模板参数提取之后、handler 之前**就拒绝了，于是这个 URI 根本没匹配上任何模板，
被当成"未知资源"。

这带来两个结论：

1. 别把安全寄托在这一层。`ResourceSecurity` 只保护"资源模板参数"，
   而 Tool 的参数（`read_note` 的 `path`）完全不在它的保护范围内——
   所以 `safety.resolve_note_path` 必须被工具和资源**共用**。
2. 反过来，我的 `read_note_resource` 里仍然保留了 `resolve_note_path` 调用。
   这是有意的冗余：一旦以后改了 URI 结构、或给某个参数加了 `exempt_params`，
   唯一的防线就只剩这一层了。

而"文件不存在"这种**能进到 handler** 的失败，返回的是可读文案（`ResourceNotFoundError` → `-32602`）：

```json
{"jsonrpc":"2.0","id":2,"error":{
  "code":-32602,
  "message":"笔记不存在：nope.md。先用 list_recent 或读取 notes://index 确认准确路径，再调用 read_note",
  "data":{"uri":"notes://note/nope.md"}}}
```

注意 Resource 的错误**没有** `isError` 通道，只能走 JSON-RPC error。
这就是为什么选 `ResourceNotFoundError`（映射成 `-32602` invalid params）而不是笼统的
`-32603`：客户端能据此判断"是路径错了"而不是"服务器炸了"。

### 验收

```bash
uv run pytest tests/test_resources.py -v
```

`notes://index` 的返回（节选）：

```json
{
  "root": ".../sample_notes",
  "count": 6,
  "returned": 6,
  "truncated": false,
  "notes": [
    {"uri":"notes://note/daily/2026-10-26.md","path":"daily/2026-10-26.md",
     "title":"2026-10-26 日志","mtime":"2026-10-26T16:18","units":142,"tags":["daily","mcp","security"]}
  ]
}
```

索引的体积必须按**序列化后的真实长度**算。第一版按"单条目 `json.dumps` 长度累加"，
`indent=2` 的缩进和换行完全没算进去，200 篇笔记实测吐出 **11,195 字符**，
超了 8000 预算 40%。现在的做法是每加一条就真实序列化一次来量。

---

## S4 · Prompt 模板 + 上下文预算复核

**目标**：`weekly-review` 模板，并给出每个原语在最坏情况下的返回上限。

### 代码

```python
@server.prompt(name="weekly-review", title="本周回顾",
               description="总结本周关于某个主题的所有笔记，输出 3 条带出处的要点。")
def weekly_review(topic: str) -> str:
    return prompt_impl.weekly_review(topic)
```

模板内容（`notes_mcp/prompts.py`）把调用路径和输出格式都固化下来：

```
请基于我的本地笔记，总结本周关于「{topic}」的内容。

步骤：
1. 调用 `list_recent`，参数 days=7，确认本周实际改动过哪些笔记。
2. 调用 `search_notes`，参数 query="{topic}"、limit=8，拿到命中片段。
3. 如果片段不足以支撑结论，再用 `read_note` 精确读取相关笔记（不要整目录遍历）。
4. 只用笔记里真实存在的内容作答；笔记没写的，明确说"笔记中没有提到"。

输出格式：
- 恰好 3 条要点，每条一句话说清结论。
- 每条要点后用括号标注来源笔记路径，例如（daily/2026-10-25.md）。
```

Prompt 的价值就在这几行：用户只说一个 `topic`，模板负责把"先 list_recent 再 search_notes"、
"3 条要点"、"必须标注出处"、"不许编" 全部交代清楚。

### 协议层面发生了什么

`prompts/list` 返回的参数表是从函数签名推出来的：

```json
{"jsonrpc":"2.0","id":9,"result":{"prompts":[
  {"name":"weekly-review","description":"总结本周关于某个主题的所有笔记，输出 3 条带出处的要点。",
   "arguments":[{"name":"topic","required":true}]}]}}
```

`prompts/get` 的响应是**一组 message**，不是一个字符串：

```json
{"jsonrpc":"2.0","id":6,"result":{
  "description":"总结本周关于某个主题的所有笔记，输出 3 条带出处的要点。",
  "messages":[{"role":"user","content":{"type":"text","text":"请基于我的本地笔记，总结本周关于「MCP」的内容。…"}}],
  "resultType":"complete"}}
```

函数返回 `str` 时 SDK 会自动包成一条 `role: "user"` 的消息；返回 `list[Message]`
就能自己控制多条消息和角色。

### 预算表（实测，不是估算）

用 `scripts/budget_report.py` 构造最坏情况：200 篇笔记 × 600 行、每行都命中、每行 40 字符。

| 原语 | 实测最大返回 | 约束 | 说明 |
|---|---:|---|---|
| `search_notes(query, limit=20)` | **7,631** | 预算 8000 | 命中 200 篇，实际只返回 3 篇，`truncated=true` |
| `read_note(超长笔记)` | **19,836** | 上限 20000 | 含截断提示 |
| `list_recent(days=3650)` | **3,994** | 预算 4000 | 200 篇全部在窗口内 |
| `notes_stats` | **442** | 预算 3000 | 50 个标签 |
| `notes://index` | **7,642** | 预算 8000 | 200 篇，实际返回 37 条 |
| `notes://note/{path}` | **19,828** | 上限 20000 | 含截断提示 |

结论：**单次调用的最坏情况约 20,000 字符**（≈ 10,000-14,000 中文 token），
占 200K 上下文窗口的 5-7%。一次"检索 → 读 2 篇"的任务最多吃 60K，仍在安全区。

复核时改掉的两个真问题：

1. **`notes://index` 超预算 40%**（11,195 > 8000）——体积估算漏了缩进。
2. **`read_note` 超 76 字符**（20,076 > 20000）——截断提示没算进预算。
   现在统一走 `clip_with_notice()`，先按 `budget - 240` 裁正文再拼提示。

还有一个设计层面的问题：**`notes://note/{path}` 原本完全没有上限**。
Resource 名义上"由客户端决定何时读取"，但不少客户端会把资源内容直接塞进上下文，
一篇 200KB 的笔记足以毁掉整轮对话。现在它和 `read_note` 用同一个 `max_note_chars`。

---

## S5 · 接入真实客户端

### Claude Desktop（Windows）

编辑 `%APPDATA%\Claude\claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "notes": {
      "command": "C:\\Users\\<你>\\projects\\notes-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "notes_mcp", "--root", "D:\\Notes"]
    }
  }
}
```

三个坑：

1. **双反斜杠**。JSON 里 `\U`、`\n`、`\t` 都是转义序列，单写 `C:\Users` 会直接解析失败。
2. **用 `.venv` 里 python 的绝对路径**，不要写 `uv run`。Claude Desktop 不继承你的 shell
   PATH，找不到 `uv` 时它不会报错，只是这个 server 静默消失。
3. **改完必须完全退出**（托盘图标也要退）。它只在启动时读配置，关窗口不算。

### Cursor

`~/.cursor/mcp.json`（项目级放 `.cursor/mcp.json`），结构相同：

```json
{
  "mcpServers": {
    "notes": {
      "command": "C:\\Users\\<你>\\projects\\notes-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "notes_mcp", "--root", "D:\\Notes"]
    }
  }
}
```

在 Settings → MCP 里应看到 `notes` 已连接、4 个工具。

### 真实任务的调用序列

任务：**"找出上周所有提到 MCP 的笔记并总结成 3 条要点"**。

模型应该发起三步（`scripts/demo_weekly_review.py` 会按顺序跑一遍并把每步打印出来，
方便你拿它对照客户端日志）：

```
[prompts/get] weekly-review
[1] tools/call list_recent  {"days": 7}
    -> 最近 7 天内修改的笔记：4 篇（全部 6 篇）
       - daily/2026-10-26.md   2026-10-26 16:18  ·  2026-10-26 日志
       - daily/2026-10-25.md   2026-10-25 16:18  ·  2026-10-25 日志
       - inbox/2026-10-24-mcp-day1.md  2026-10-24 16:18  ·  MCP 协议学习笔记（第一天）
       - projects/notes-mcp-design.md  2026-10-23 18:18  ·  notes-mcp 设计草案
[2] tools/call search_notes  {"query": "MCP", "limit": 8}
    -> 命中 6 篇，返回 1623 字符的片段（不是全文）
[3] tools/call read_note  {"path": "daily/2026-10-26.md"}
    -> 381 字符
```

判断"模型确实调对了"的依据：客户端日志里出现 `list_recent` 且 `days=7`，
紧接着出现 `search_notes`；如果模型跳过 `list_recent` 直接 `search_notes`，
说明 prompt 的步骤没被采纳——检查模板里工具名是否写成了反引号包裹的形式（更容易被遵循）。

> 说明：上面这段是脚本按 prompt 规定的序列执行的结果，不是 Claude Desktop 的截图。
> 我无法在这个环境里启动图形客户端，所以客户端侧的最终确认需要你本地做一次。

---

## S6 · 选做：Streamable HTTP

**目标**：同一份 server 换传输。

### 代码

`notes_mcp/__main__.py` 已经支持：

```python
if args.transport == "stdio":
    server.run("stdio")
else:
    server.run("streamable-http", host=args.host, port=args.port,
               stateless_http=args.stateless_http)
```

```bash
uv run notes-mcp --root ./sample_notes --transport streamable-http --port 8000
```

客户端连 `http://127.0.0.1:8000/mcp`。

实测两种模式的行为差异：

```bash
# 有状态模式：没有 session 直接请求 → 被拒
curl -s -X POST http://127.0.0.1:8931/mcp -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{
        "io.modelcontextprotocol/protocolVersion":"2026-07-28",
        "io.modelcontextprotocol/clientCapabilities":{}}}}'
# {"jsonrpc":"2.0","id":null,"error":{"code":-32600,"message":"Bad Request: Missing session ID"}}
```

```bash
# 无状态模式（--stateless-http）：同样的请求直接返回结果
uv run notes-mcp --root ./sample_notes --transport streamable-http --port 8932 --stateless-http
# event: message
# data: {"jsonrpc":"2.0","id":1,"result":{"tools":[{"description":"按关键词全文检索…"}]}}
```

有状态模式下 session ID 是 `initialize` 时由服务端在响应头里下发的；
无状态模式没有会话，每个请求自带 `_meta`（protocolVersion + capabilities）就够——
这正是 2026-07-28「请求自包含」的直接收益：**同一个 server 既能做本地 stdio，
又能无粘性负载均衡到多个副本**。另外注意响应是 SSE 格式（`event: message` + `data:` 行），
不是裸 JSON。

### 与 stdio 的差异

| 维度 | stdio | Streamable HTTP |
|---|---|---|
| **日志** | 铁律：stdout 只能有协议报文，日志必须 stderr | 没有这个限制，stdout 随便打 |
| **生命周期** | 一个进程 = 一个客户端，客户端退出进程就结束 | 一个进程服务多个客户端，server 长驻 |
| **多客户端** | 天然隔离（进程隔离） | 需要自己处理并发；`--stateless-http` 下每次请求都独立 |
| **认证** | 由操作系统文件权限保证 | 必须自己加（`auth_server_provider` / `token_verifier`），否则同网段谁都能读你的笔记 |
| **默认绑定** | — | `127.0.0.1`，**不要改成 `0.0.0.0`** 除非你清楚后果 |
| **调试** | 报文不好抓 | 可以直接 curl / 用浏览器开发者工具看 |

对这个项目来说，HTTP 传输的唯一正当理由是"多设备访问同一份笔记"。
一旦开在公网上，`read_note` 的路径校验就从"防御模型幻觉"升级成"防御真实攻击者"，
那时至少要加：认证、速率限制、根目录只读挂载、以及把 `notes://index` 关掉
（它会把整个目录结构泄露出去）。

---

## 附 · 踩过的坑

| 现象 | 根因 | 修法 |
|---|---|---|
| `-32602 Invalid request parameters`，看不出缺什么 | `_meta` 的键写成了 kebab-case | 用 `io.modelcontextprotocol/protocolVersion`（camelCase） |
| Inspector 里看不到 modern 行为 | CLI 对 ad-hoc 目标默认走 legacy | 加 `--protocol-era modern` |
| 标签统计全是 0 | 用 `line.startswith("#")` 剔标题，把整行 `#mcp #protocol` 也剔了 | 标题判定改成 `^\s{0,3}#{1,6}\s`（`#` 后必须跟空白） |
| `search_notes` 返回"命中 200 篇、返回 0 篇" | 单个片段超过总预算，一个都塞不进去 | 片段限长 15 行 + 第一块放不下时裁剪而不是丢弃 |
| 预算表说 8000，实测 11,195 | 体积估算漏了 `indent=2` 的缩进 | 每加一条就真实序列化一次来量 |
| 中文日志在 Windows 控制台变成 `·��Խ` | 控制台 GBK，rich 按 UTF-8 写 | `sys.stderr.reconfigure(encoding="utf-8")` + 自己装 handler |
| 客户端里 server 静默消失 | 配置里用了 `uv run`，Claude Desktop 没有那个 PATH | 写 `.venv` 里 python 的绝对路径 |
| `notes://note/a/b.md` 匹配不上 | 用了 `{path}`，斜杠被当成分隔符 | 用 `{+path}`（保留展开） |

---

## 测试与自检

```bash
uv run pytest                       # 60 个用例：单测 + 端到端
uv run python scripts/verify.py     # 22 项检查，含 stdout 纯净度
uv run python scripts/budget_report.py   # 预算表
uv run python scripts/demo_weekly_review.py MCP   # S5 调用序列
```
