# notes-mcp

把本地 Markdown 笔记目录以**只读**方式暴露给 AI 助手的 MCP Server。
基于 MCP 规范 `2026-07-28`，Python SDK `mcp[cli] >= 2.0`。

> 不写文件、不删文件、不执行任何外部命令。所有返回值都有字符预算上限。

---

## 它提供什么

**Tools（模型调用）**

| 名称 | 参数 | 行为 |
|---|---|---|
| `search_notes` | `query: str`, `limit: int = 5` | 全文检索，返回命中行 ±2 行的**片段**（每篇最多 3 段），总预算 8000 字符 |
| `read_note` | `path: str` | 读取单篇全文，超过 20000 字符截断并标注 |
| `list_recent` | `days: int = 7` | 最近 N 天修改过的笔记（路径 + 时间 + 首行标题） |
| `notes_stats` | — | 笔记总数、总字数、标签分布（解析 `#tag`） |

**Resources（客户端/用户读取）**

| URI | 说明 |
|---|---|
| `notes://index` | 全部笔记清单（JSON：uri / path / title / mtime / units / tags） |
| `notes://note/{+path}` | 单篇笔记正文，例如 `notes://note/daily/2026-10-25.md` |

**Prompts（用户触发的模板）**

| 名称 | 参数 | 说明 |
|---|---|---|
| `weekly-review` | `topic: str` | 生成"总结本周关于 {topic} 的笔记"的指令，要求 3 条要点 + 出处 |

---

## 快速开始

```bash
# 方式一：uv（推荐，与文档命令一致）
uv sync
uv run notes-mcp --root ./sample_notes

# 方式二：pip 可编辑安装
python -m venv .venv
.venv/Scripts/python -m pip install -e .      # Windows
# .venv/bin/python -m pip install -e .        # macOS / Linux
.venv/Scripts/python -m notes_mcp --root ./sample_notes
```

`--root` 也可以省略，此时按 `NOTES_MCP_ROOT` 环境变量 → `./notes` 的顺序取值。

### 构建可分发的产物

```bash
uv build      # -> dist/notes_mcp-0.1.0-py3-none-any.whl 与 dist/notes_mcp-0.1.0.tar.gz
```

把 wheel 拷到目标机器（不需要源码、不需要 uv）：

```bash
python -m venv .venv
.venv/Scripts/python -m pip install notes_mcp-0.1.0-py3-none-any.whl
.venv/Scripts/notes-mcp --root D:\Notes --version
```

装完就多了一个 `notes-mcp` 命令，客户端配置里直接指向它，不用再记 `python -m notes_mcp`。

CI（`.github/workflows/ci.yml`）在每次推送时都会走一遍"构建 → 装进干净 venv → 跑 `--version`"，
所以"构建成功"和"装得上"这两件事不会脱节。

### 验收（Inspector CLI，强制 modern 协议）

```bash
npx @modelcontextprotocol/inspector@2.12.0 --cli \
  --protocol-era modern \
  uv run notes-mcp --root ./sample_notes \
  --method tools/list
```

看到四个工具名即通过。`--protocol-era modern` 不能省——Inspector 的 CLI 在
ad-hoc 目标下默认走 **legacy**（2025 握手），不加这个参数你测的是旧时代的行为。

### 本地完整自检

```bash
uv run python scripts/verify.py      # 走真实 stdio 客户端，跑全部工具/资源/提示
uv run pytest                        # 单元测试 + 端到端测试
```

---

## 三条工程约束

### 1. 路径安全

`read_note` 的 `path` 来自模型，是不可信输入。校验流程（`notes_mcp/safety.py`）：

1. 拒绝空、NUL 字节；
2. 拒绝绝对路径（同时覆盖 POSIX `/x`、Windows `C:\x`、`\\server\share`）；
3. 拒绝任何含 `..` 的路径；
4. `Path.resolve()` **展开符号链接之后**，用 `is_relative_to(root)` 判断是否越界；
5. 只允许 `.md` / `.markdown`。

第 4 步是唯一真正有效的一步。字符串里看不出问题的 `escape.md` 完全可能是个
指向 `C:\Windows\System32\drivers\etc\hosts` 的软链接——只有 resolve 之后再比较才拦得住。

### 2. 上下文预算

`search_notes` 绝不返回整篇。每个片段前后各 2 行、每篇最多 3 段、总预算 8000 字符。
超限时返回文本里会带 `[已截断：…]`，明确告诉模型"你还没看完"。

完整预算表见 [`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md) 的 S4 一节。

### 3. 结构化错误

工具失败时不抛裸异常，而是 `raise ToolError("路径越界：…。只允许笔记根目录内的相对路径")`。
客户端收到 `isError: true` + 可读文本，模型能据此改写参数重试。
抛未捕获异常的话，模型只会看到 `Error executing tool read_note`，学不到任何东西。

---

## 接入客户端

### Claude Desktop

编辑 `%APPDATA%\Claude\claude_desktop_config.json`（macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`）：

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

三个必须注意的点：

- Windows 路径在 JSON 里要用**双反斜杠**，否则 `\U`、`\n` 会被当转义序列；
- 用 `.venv` 里 python 的**绝对路径**，不要写 `uv run`——Claude Desktop 不继承你的 shell 环境，
  找不到 `uv` 就静默失败；
- 改完必须**完全退出** Claude Desktop（托盘图标也要退），它只在启动时读配置。

### Cursor

`~/.cursor/mcp.json`（项目级用 `.cursor/mcp.json`），结构同上：

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

在 Cursor 的 Settings → MCP 里确认 `notes` 显示为已连接、工具数为 4。

### 用 wheel 装好的命令

如果是 `pip install notes_mcp-*.whl` 装的，直接指向虚拟环境里的可执行文件更省事：

```json
{
  "mcpServers": {
    "notes": {
      "command": "C:\\Users\\<你>\\notes-venv\\Scripts\\notes-mcp.exe",
      "args": ["--root", "D:\\Notes"]
    }
  }
}
```

macOS / Linux 上 `command` 换成 `/Users/<你>/notes-venv/bin/notes-mcp`。

---

## 配置项

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `NOTES_MCP_ROOT` | `./notes` | 笔记根目录 |
| `NOTES_MCP_MAX_NOTE_CHARS` | `20000` | `read_note` / 单篇 Resource 的返回上限 |
| `NOTES_MCP_SEARCH_BUDGET` | `8000` | `search_notes` 总预算 |

命令行参数：`--root`、`--transport {stdio,streamable-http}`、`--host`、`--port`、
`--stateless-http`、`--log-level`。

完整的实施过程（每个阶段的协议报文、验收输出、踩过的坑）见
[`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md)。

---

## 项目结构

```
notes_mcp/
├── config.py     运行期配置（根目录 + 各类预算）
├── safety.py     不可信路径校验（工具与资源共用同一套规则）
├── store.py      扫描 / 解析 / 片段化检索（朴素实现）
├── budget.py     截断与预算拼装
├── tools.py      四个 Tool 的纯逻辑（不认识 MCP，可单测）
├── resources.py  两个 Resource 的纯逻辑
├── prompts.py    Prompt 模板
├── server.py     注册到 MCPServer
└── __main__.py   进程入口：参数、stderr 日志、传输
```

分层的关键是 `tools.py` / `resources.py` 不 import 任何 MCP 的东西。
它们只接收 `Settings` 和字符串，抛 `PathRejected` / `QueryRejected`；
`server.py` 才把这些异常翻译成 `ToolError` / `ResourceNotFoundError`。
这样单测不需要起 server，也不用解析 JSON-RPC。

---

## 故障排查

| 现象 | 判断依据 | 处理 |
|---|---|---|
| 客户端显示 "Server disconnected" | stderr 里有 traceback | 直接跑 `python -m notes_mcp --root ...` 看真实报错 |
| 工具列表是空的 | Inspector 没加 `--protocol-era modern` | 加上参数重测 |
| 客户端读到一半乱码 | stdout 混入了非协议输出 | 检查是否有 `print()`；日志必须走 stderr |
| `read_note` 报"笔记不存在" | 路径相对的是根目录，不是当前目录 | 先读 `notes://index` 拿准确路径 |

---

## 已知限制

- **朴素检索**：每次调用都全量扫描并读盘。几千篇以内无感，10 万篇需要倒排索引
  （改造方向见 `docs/WALKTHROUGH.md` S1 后半段）。
- **只读**：没有任何写路径。需要写入请另开一个 server，并显式做权限与备份。
- **单进程单根目录**：一个进程只服务一个 `--root`。多个目录就配多个 server 条目。

---

## 开发

```bash
uv sync                                  # 含 dev 依赖（pytest / anyio）
uv run pytest                            # 60 个用例
uv run python scripts/verify.py          # 22 项端到端检查（真实 stdio + 报文纯净度）
uv run python scripts/budget_report.py   # 打印各类返回的实测体积，确认没越预算
uv run python scripts/demo_weekly_review.py   # 按 prompt 模板走一遍完整调用链
```

实施过程与逐阶段协议报文见 [`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md)，
可复现的验收结论见 [`ISSUE.md`](ISSUE.md)。

## 许可证

[MIT](LICENSE)
