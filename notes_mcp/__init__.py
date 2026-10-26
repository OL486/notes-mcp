"""notes-mcp：把本地 Markdown 笔记目录以只读方式暴露给 MCP 客户端。

分层：
    config.py     运行期配置（根目录、各类预算）
    safety.py     不可信路径的校验（工具和资源共用）
    store.py      扫描、解析、检索笔记
    budget.py     截断与预算工具
    tools.py      四个 Tool 的纯逻辑
    resources.py  两个 Resource 的纯逻辑
    prompts.py    Prompt 模板
    server.py     把上面这些注册到 MCPServer 上
    __main__.py   进程入口：解析参数、配置 stderr 日志、启动传输
"""

__version__ = "0.1.0"
