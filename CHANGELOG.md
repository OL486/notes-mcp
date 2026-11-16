# Changelog

<!-- 约定：PR 合并后请同步更新本文件（Unreleased 节），上次漂移就是合并后没人同步。 -->

本文件记录 notes-mcp 每个版本值得注意的改动，格式遵循
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- 发布流程：新增本文件（CHANGELOG.md）。
- `pyproject.toml` 补许可证、作者与仓库链接元数据（`license = "MIT"`、`authors`、
  `[project.urls]`）。
- `list_notes` 工具（PR #14，Closes #13，已合、未发布）：按 mtime 倒序、offset/limit
  翻页列出全部笔记，支持按目录过滤；`notes://index` 无翻页的问题由此解决。

### 在途（尚未合进 main，待合并/落地后再记入上面）

- 发布流程的 release.yml（未落地）：`.github/workflows/release.yml` 从未进过 git
  历史，workflow 全文目前只在 PR #16 正文的折叠块里；待在网页端手动新建该文件、
  打 tag `v0.1.0` 并确认 Release 挂上 wheel 与 sdist 后，再记入 Added。

### Fixed

- 修复 frontmatter 笔记标题变 `---`、frontmatter 里的标签被漏数（PR #12，Closes #11）。

### Changed

- `build_index` 改为增量记账，1000 篇笔记、大预算下由 4,604 ms 降至 716 ms；
  `extract_tags` 跳过无反引号的行、`load_note` 缓存根目录解析，1000 篇笔记下
  search 约 311 ms → 279 ms、list_recent 约 285 ms → 259 ms；根目录不存在时明确报错
  （PR #10，Closes #9）。

### 计划在 0.2.0 做

- 删除 `notes_mcp/store.py` 兼容层：它头上写着“一个版本后删除”，0.1.0 发布后该条件
  即满足，在 0.2.0 里兑现。

## [0.1.0]

首个版本。版本号自 2026-10-26 首个提交起一直是 0.1.0，本文件补记至今已合的全部内容；
此前没有任何 tag 或 GitHub Release，wheel 只由 CI 构建后保留 14 天。
首个 tag `v0.1.0` 待创建（步骤见 PR 正文），日期以 tag 为准。

### Added

- 只读 MCP Server：4 个工具（`search_notes` / `read_note` / `list_recent` / `notes_stats`）、
  2 个资源（`notes://index`、`notes://note/{path}`）、1 个提示（`weekly-review`）。
- 预算机制：搜索 8000 字符、单篇 20000 字符等上限均含截断提示在内，
  `scripts/budget_report.py` 可复核整张预算表。
- `scripts/verify.py` 端到端自检（真实 stdio 传输，22 项）与 `sample_notes` 示例笔记。
- 结构重构（PR #4）：`store.py` 拆为 `notes/` 包、`tools.py` 拆为 `tools/` 包、读单篇
  统一走 `services/read_note.py`、补预算与配置测试。
- 安全与配置收口（PR #6）：根外符号链接拒绝读取、异常翻译统一、`test_server.py` /
  `test_main.py`、ruff + mypy 落地、全部 `Settings` 字段暴露并校验、版本单一来源
  （`__init__.__version__`）。

### Fixed

- 标题 / 标签 / 预算 bug 修复（PR #8）：纯标签行不再被当标题、围栏开头的笔记标题不再
  是 ```` ``` ````、`build_index` 小预算不再超支、行内代码里的 `#tag` 不再计数、UTF-16
  笔记不再解码成乱码。
- 轻量加载提速（PR #8）：`search` / `list_recent` 不再计算用不到的 `units` / `tags`，
  1000 篇笔记下 search 约 1149 ms → 343 ms、list_recent 约 1026 ms → 225 ms；
  mypy `--strict` 全过。

### 已知限制

- `read_note` 超过 20000 字符截断后，剩余部分暂无办法读取（分页是新功能，待定）。
