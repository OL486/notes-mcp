"""进程入口。

stdio 传输下这个文件承担一个额外责任：**保证 stdout 只有协议报文**。
这里的做法是——所有日志显式绑定到 stderr，并且在启动前把 stderr 的编码
固定成 UTF-8（中文 Windows 控制台默认 GBK，日志里的中文会变成乱码）。
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .config import ENV_ROOT, load_settings
from .server import create_server

LOG = logging.getLogger("notes_mcp")


def _configure_stderr_logging(level: str) -> None:
    """把日志钉死在 stderr。

    force=True 会顶掉之前任何 handler（包括 SDK 自己装的 rich handler）。
    这不是洁癖：rich handler 在 GBK 控制台下会把中文日志打成乱码，
    而且一旦有人不小心让日志落到 stdout，整个 JSON-RPC 流就废了。
    """
    reconfigure = getattr(sys.stderr, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # 被重定向到不支持重配置的对象时忽略
            pass

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    logging.basicConfig(level=getattr(logging, level.upper(), logging.WARNING), handlers=[handler], force=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notes-mcp",
        description="把本地 Markdown 笔记目录以只读方式暴露给 MCP 客户端。",
    )
    parser.add_argument(
        "--root",
        default=None,
        help=f"笔记根目录。默认读环境变量 {ENV_ROOT}，再退回 ./notes。",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="传输方式。stdio 给本地客户端用；streamable-http 给远程/多客户端用。",
    )
    parser.add_argument("--host", default="127.0.0.1", help="streamable-http 监听地址（默认仅本机）。")
    parser.add_argument("--port", type=int, default=8000, help="streamable-http 监听端口。")
    parser.add_argument(
        "--stateless-http",
        action="store_true",
        help="streamable-http 下不维护会话状态。多副本部署/无粘性负载均衡时需要。",
    )
    parser.add_argument("--log-level", default="WARNING", help="stderr 日志级别，默认 WARNING。")
    parser.add_argument("--version", action="version", version=f"notes-mcp {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _configure_stderr_logging(args.log_level)

    settings = load_settings(args.root)
    if not settings.root.is_dir():
        # 用 stderr + 退出码，而不是抛异常：客户端只会看到"服务器启动失败"，
        # 但用户在日志面板里能直接读到原因。
        print(f"[notes-mcp] 笔记根目录不存在或不是目录：{settings.root}", file=sys.stderr)
        print(f"[notes-mcp] 用 --root 指定，或设置环境变量 {ENV_ROOT}。", file=sys.stderr)
        return 2

    # 用 INFO 而不是 WARNING：默认级别是 WARNING，启动日志不该在每次连接时
    # 都往客户端的日志面板里刷一行。想看就用 --log-level INFO。
    LOG.info("notes-mcp 启动：root=%s transport=%s", settings.root, args.transport)

    server = create_server(settings)
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run(
            "streamable-http",
            host=args.host,
            port=args.port,
            stateless_http=args.stateless_http,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
