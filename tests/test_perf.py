"""性能回归冒烟：1000 篇笔记下关键原语的耗时上限。

round-3/4 的性能数字只存在于分析报告里；一次"顺手"重构（例如去掉
light 加载、改回全量解析）就能让 search 悄悄慢 3 倍，而 CI 全绿。
这个文件是自动化护栏，不是 benchmark：

- 阈值只抓"量级退化"，不抓毫秒级波动。本轮实测（main 6020f00，
  共享 VM，5 遍中位，两轮）：search ~0.5–1.1s、list_recent
  ~0.4–1.6s、build_index 大预算 ~3.4–4.2s（负载较低时；共享 VM
  高负载下 build_index 可达 ~7–10s，list_recent 单次曾到 ~4s——
  数字随负载波动很大，只看量级）。2s 对 search / list_recent 留
  约 2–4 倍余量。
- build_index 大预算的阈值是 5s：本轮实测 ~3.4–4.2s（负载较低
  时），3s 已无余量（global-check round 2 实测 2.91–3.59s；本轮
  高负载下 pytest 里甚至跑到 7.29s，直接超标）。5s 留约 1.4 倍
  余量，同时仍能抓住旧 O(n²) 行为（同 VM 上约 9s 会超标）。3s
  是上一轮 PR #22 定的值，当时实测 ~1.6s（6 次 1.51–1.81s）；
  8s 是 #10 合并前的过渡值，已作废。
- 不要断言精确毫秒数，不要引入 pytest-benchmark，也不要在 CI 里做
  精确计时对比——波动太大，收益不成正比。
- 标记 @pytest.mark.slow 只是为了能用 `-m "not slow"` 跳过，
  默认照常跑。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from notes_mcp.config import Settings
from notes_mcp.resources import build_index
from notes_mcp.tools import run_list_recent, run_search

# 冒烟阈值（秒）：只防量级退化。见模块 docstring 的余量说明。
PERF_BUDGET_SECONDS = 2.0
# build_index 大预算的阈值：见模块 docstring（从 3s 放宽到 5s——共享 VM
# 变慢，3s 已无余量；5s 仍能抓住旧 O(n²) 行为）。
BIG_INDEX_BUDGET_SECONDS = 5.0

# 合成库规模：与 round-3/4 分析口径一致（1000 篇、每篇约 4.5KB）。
NOTES = 1000
LINES_PER_NOTE = 120
QUERY = "命中关键词"


def _build_library(root: Path) -> None:
    """造 1000 篇笔记：每篇都命中 query，每篇都有标签。

    每行都含 query 是最坏情况——search 要扫全部命中行、拼片段；
    标签行让 build_index 的全量加载（light=False）走完整解析路径。
    mtime 保持"刚刚写入"，让 list_recent(days=7) 看到全部 1000 篇。
    """
    (root / "d").mkdir(parents=True)
    body = "\n".join("命中关键词 " + "填充" * 15 for _ in range(LINES_PER_NOTE))
    for index in range(NOTES):
        (root / "d" / f"n{index:03d}.md").write_text(
            f"# 笔记 {index}\n{body}\n#tag{index % 50}\n", encoding="utf-8"
        )


@pytest.fixture(scope="module")
def perf_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("notes") / "library"
    _build_library(root)
    return Settings(root=root.resolve())


@pytest.mark.slow
def test_search_notes_under_budget(perf_settings: Settings) -> None:
    """search_notes 在 1000 篇笔记下单次调用 < 2s（本轮实测中位 ~0.5–1.1s）。"""
    start = time.perf_counter()
    outcome = run_search(perf_settings, QUERY)
    elapsed = time.perf_counter() - start

    assert outcome.notes_matched == NOTES
    assert elapsed < PERF_BUDGET_SECONDS, (
        f"search_notes 耗时 {elapsed:.2f}s，超过 {PERF_BUDGET_SECONDS}s"
    )


@pytest.mark.slow
def test_list_recent_under_budget(perf_settings: Settings) -> None:
    """list_recent 在 1000 篇笔记下单次调用 < 2s（本轮实测中位 ~0.4–1.6s）。

    注意 outcome.count 是预算截断后返回的条数（4000 字符预算下约 81 条），
    不是命中的总数；总数在 header 文本里，这里断言 header。
    """
    start = time.perf_counter()
    outcome = run_list_recent(perf_settings, days=7)
    elapsed = time.perf_counter() - start

    assert f"最近 7 天内修改的笔记：{NOTES} 篇（全部 {NOTES} 篇）" in outcome.text
    assert elapsed < PERF_BUDGET_SECONDS, (
        f"list_recent 耗时 {elapsed:.2f}s，超过 {PERF_BUDGET_SECONDS}s"
    )


@pytest.mark.slow
def test_build_index_big_budget_under_budget(perf_settings: Settings) -> None:
    """build_index 在大预算下单次调用 < 5s（本轮实测 ~3.4–4.2s，负载较低时，见模块 docstring）。

    默认预算会把 1000 篇截断到几十条，测不出全量渲染的成本，
    所以这里用 10_000_000 预算让全部条目都进入输出——
    这正是 round-4 修掉 O(n²) 的那个场景（PR #10 未合前 4,604ms，
    合后本机实测 ~1.6s；共享 VM 变慢后本轮实测 ~3.4–4.2s）。阈值 5s
    仍能抓住旧行为（同 VM 上约 9s 会超标）。
    """
    big_budget = Settings(root=perf_settings.root, index_budget=10_000_000)

    start = time.perf_counter()
    index = build_index(big_budget)
    elapsed = time.perf_counter() - start

    payload = json.loads(index)
    assert payload["count"] == NOTES
    assert payload["returned"] == NOTES
    assert payload["truncated"] is False
    assert elapsed < BIG_INDEX_BUDGET_SECONDS, (
        f"build_index 耗时 {elapsed:.2f}s，超过 {BIG_INDEX_BUDGET_SECONDS}s"
    )
