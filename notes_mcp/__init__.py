"""notes-mcp：把本地 Markdown 笔记目录以只读方式暴露给 MCP 客户端。

分层：
    config.py     运行期配置（根目录、各类预算）
    safety.py     不可信路径的校验（工具和资源共用）
    notes/        扫描、解析、检索、存储（原 store.py 的拆分）
      models.py   Note / Fragment / NoteHit 数据模型
      scan.py     扫描候选笔记文件 + 后缀白名单
      parse.py    标题 / 标签 / 字数等纯文本解析
      search.py   子串检索 + 片段合并 + 渲染
      store.py    NoteStore 协议 + 朴素文件系统实现
    store.py      兼容层（已废弃）：re-export notes/，一个版本后删除
    budget.py     截断与预算工具
    tools/        四个 Tool 的纯逻辑（原 tools.py 的拆分）
      search.py / read.py / recent.py / stats.py / common.py
    services/     跨 Tool / Resource 共用的服务
      read_note.py  读单篇的唯一实现
    resources.py  两个 Resource 的纯逻辑
    prompts.py    Prompt 模板
    server.py     把上面这些注册到 MCPServer 上
    __main__.py   进程入口：解析参数、配置 stderr 日志、启动传输
"""

__version__ = "0.1.0"
