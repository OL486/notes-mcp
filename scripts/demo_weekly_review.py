"""演示 S5 的真实任务链路："找出上周提到 X 的笔记并总结成 3 条要点"。

这个脚本不调用任何大模型，它只是把 weekly-review 模板里规定的调用序列
**按顺序执行一遍**，把每一步的工具名、参数、返回摘要打印出来。

为什么值得单独跑一遍：
1. 它证明了 prompt 里写的调用路径真的能走通（工具存在、参数正确、结果够用）；
2. 接上 Claude Desktop / Cursor 之后，模型发起的是同一串 tools/call，
   你可以拿这个输出对照客户端日志，确认"模型确实调了 list_recent 和 search_notes"。
"""

from __future__ import annotations

import sys
from pathlib import Path

import anyio
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters


def _force_utf8_console() -> None:
    """Windows 控制台默认 GBK、GitHub Actions 的 Windows runner 是 cp1252，
    都不保证能编码中文。脚本自己把输出钉成 UTF-8，别让 print 成为唯一的失败点。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


_force_utf8_console()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NOTES_ROOT = PROJECT_ROOT / "sample_notes"
TOPIC = sys.argv[1] if len(sys.argv) > 1 else "MCP"


def _brief(text: str, limit: int = 260) -> str:
    flat = text.replace("\n", " ⏎ ")
    return flat if len(flat) <= limit else flat[:limit] + " …"


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "notes_mcp", "--root", str(NOTES_ROOT)],
        cwd=str(PROJECT_ROOT),
    )

    async with Client(params, mode="2026-07-28") as client:
        print(f"协议版本：{client.protocol_version}")
        print(f"任务：找出上周提到「{TOPIC}」的笔记，总结成 3 条要点\n")

        # 第 0 步：客户端取 prompt 模板（这一步是用户侧触发的 prompts/get）
        prompt = await client.get_prompt("weekly-review", {"topic": TOPIC})
        print("[prompts/get] weekly-review")
        print(f"  模板前 80 字：{_brief(prompt.messages[0].content.text, 80)}\n")

        # 第 1 步：确认本周动过哪些笔记
        step1 = await client.call_tool("list_recent", {"days": 7})
        print("[tools/call] list_recent  arguments={'days': 7}")
        print(f"  -> {_brief(step1.content[0].text, 420)}\n")

        # 第 2 步：按主题检索片段
        step2 = await client.call_tool("search_notes", {"query": TOPIC, "limit": 8})
        search_text = step2.content[0].text
        print(f"[tools/call] search_notes  arguments={{'query': '{TOPIC}', 'limit': 8}}")
        print(f"  -> 返回 {len(search_text)} 字符，is_error={step2.is_error}")
        print(f"  -> {_brief(search_text, 500)}\n")

        # 第 3 步：片段不够时精读一篇（这里固定读第一篇，真实场景由模型决定）
        first_note = "daily/2026-10-26.md"
        step3 = await client.call_tool("read_note", {"path": first_note})
        print(f"[tools/call] read_note  arguments={{'path': '{first_note}'}}")
        print(f"  -> 返回 {len(step3.content[0].text)} 字符\n")

        print("调用序列完成。接上真实客户端后，模型应当发起同样这三步，")
        print("然后基于返回的片段写 3 条要点，并在每条后面标注来源笔记路径。")


if __name__ == "__main__":
    anyio.run(main)
