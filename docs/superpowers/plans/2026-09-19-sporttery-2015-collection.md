# 中国竞彩 2015 全年采集 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现可恢复、可审计、幂等的中国竞彩历史比赛与固定奖金采集器，并完成 2015-01-01 至 2015-12-31 的全年采集验证。

**Architecture:** `backend/app/sporttery/` 独立负责官方接口访问、JSON 解析、原始响应、检查点和 DuckDB（嵌入式分析数据库）写入。命令行入口先支持小窗口探测，再运行全年任务；每个列表页和每场奖金响应落盘后立即更新检查点，HTTP 567 立即停止并保留进度。

**Tech Stack:** Python 3.11、httpx（HTTP 客户端）、DuckDB、pytest（测试框架）、Typer-free argparse（标准库命令行解析）。

**Spec:** `docs/superpowers/specs/2026-09-19-sporttery-history-model-design.md`

## Global Constraints

- 官方列表接口：`getUniformMatchResultV1.qry`；固定奖金接口：`getFixedBonusV1.qry`。
- 单线程采集；生产默认请求间隔 3 至 5 秒；HTTP 567 不持续重试。
- 原始 JSON、检查点、DuckDB 和运行报告不提交 Git。
- 首次验收范围固定为 `2015-01-01` 至 `2015-12-31`。
- 不绕过验证码、登录、付费墙或交互式安全验证。

## Review Focus

- 接口返回 HTTP 200 但 `success=false`：测试必须分类为业务错误，不能写入成功检查点。
- 列表 `pages` 大于 1：测试必须逐页发现全部 `matchId`，不能只采第一页。
- 任务中断或重复执行：测试必须从检查点继续且不重复请求已校验的原始响应。
- 奖金中存在空玩法或不完整快照：测试必须保留原始响应并只写入完整、正数奖金快照。
- HTTP 567、429、超时与 5xx：测试必须分别验证停止、退避重试和有限重试行为。

---

### Task 1: 官方接口客户端与响应模型

**Files:**
- Create: `backend/app/sporttery/models.py`
- Create: `backend/app/sporttery/client.py`
- Create: `backend/tests/test_sporttery_client.py`

**Interfaces:**
- Produces: `SportteryClient.fetch_match_page(begin, end, page_no, page_size) -> HttpPayload`
- Produces: `SportteryClient.fetch_fixed_bonus(match_id) -> HttpPayload`
- Produces: `BlockedBySourceError`、`RetryableSourceError`、`SourceBusinessError`

- [x] 写入使用 `httpx.MockTransport` 的失败测试，覆盖固定请求头、查询参数、HTTP 567、429、5xx、超时和业务错误码。
- [x] 运行 `pytest tests/test_sporttery_client.py -q`，确认因模块尚不存在而失败。
- [x] 实现同步单线程客户端、最多 3 次指数退避和可注入的等待函数；567 直接抛出阻断错误。
- [x] 再次运行测试并确认通过。

### Task 2: 列表与五类奖金解析

**Files:**
- Create: `backend/app/sporttery/parser.py`
- Create: `backend/tests/fixtures/sporttery_match_page.json`
- Create: `backend/tests/fixtures/sporttery_fixed_bonus.json`
- Create: `backend/tests/test_sporttery_parser.py`

**Interfaces:**
- Consumes: 官方 `value.matchResult` 与 `value.oddsHistory`
- Produces: `parse_match_page(payload) -> MatchPageRecord`
- Produces: `parse_fixed_bonus(payload) -> FixedBonusRecord`

- [x] 从用户提供的响应裁剪脱敏 fixture（固定测试样例），保留真实字段结构。
- [x] 写失败测试，覆盖分页元数据、比赛赛果、`hadList`、`hhadList`、`ttgList`、`crsList`、`hafuList`、空玩法和非法奖金。
- [x] 实现不可变 dataclass（数据类）和 Asia/Shanghai 到 UTC 的精确时间解析。
- [x] 运行 `pytest tests/test_sporttery_parser.py -q` 并确认通过。

### Task 3: 原始响应、检查点与幂等数据库

**Files:**
- Create: `backend/app/sporttery/storage.py`
- Create: `backend/app/sporttery/repository.py`
- Create: `backend/app/migrations/007_sporttery_history.sql`
- Create: `backend/tests/test_sporttery_storage.py`
- Create: `backend/tests/test_sporttery_repository.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `RawResponseStore.write(kind, year, key, payload) -> StoredResponse`
- Produces: `CheckpointStore.load(year)`、`CheckpointStore.save(checkpoint)`
- Produces: `SportteryRepository.import_match_page(...)`、`import_fixed_bonus(...)`、`coverage_report(year)`

- [x] 写失败测试，验证原子写入、SHA-256、损坏文件拒绝、检查点恢复和数据库重复导入计数不增长。
- [x] 新增竞彩请求审计、比赛元数据及与现有核心表兼容的唯一约束迁移。
- [x] 实现原始响应和检查点的临时文件加原子替换，避免中途退出留下半个 JSON。
- [x] 运行新增存储与仓储测试并确认通过。

### Task 4: 可恢复采集服务与命令行

**Files:**
- Create: `backend/app/sporttery/service.py`
- Create: `backend/app/sporttery/cli.py`
- Create: `backend/app/sporttery/__init__.py`
- Create: `backend/tests/test_sporttery_service.py`

**Interfaces:**
- Produces: `collect_range(start_date, end_date, window_days=7) -> CollectionReport`
- Produces: `python -m app.sporttery.cli collect --start 2015-01-01 --end 2015-12-31`
- Produces: `python -m app.sporttery.cli report --year 2015`

- [ ] 写失败测试，模拟两页列表、重复比赛、中断恢复、奖金缺失和 567 停止。
- [ ] 实现 7 天窗口、动态页数、去重队列、每项完成后检查点写入和结构化进度日志。
- [ ] 实现 `--delay-min`、`--delay-max`、`--resume` 和 `--dry-run` 参数，并校验日期与延迟范围。
- [ ] 运行服务测试与全部后端回归测试。

### Task 5: 2015 在线采集与验收报告

**Files:**
- Create (ignored): `data/raw/sporttery/**`
- Create (ignored): `data/reports/sporttery-2015.json`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 4 的 CLI（命令行界面）
- Produces: 2015 覆盖率、错误、幂等性和可恢复性报告

- [ ] 先运行 `collect --start 2015-01-01 --end 2015-01-03 --delay-min 3 --delay-max 5`，核对列表 44 场、2 页及已知比赛 `matchId=62373`。
- [ ] 对小窗口重复执行一次，确认比赛和快照计数不增长且原始文件命中缓存。
- [ ] 运行全年命令，保留实时检查点；若遇到 567，停止并报告实际完成范围，不规避来源限制。
- [ ] 运行 `report --year 2015`，输出唯一比赛、五类玩法覆盖、快照分布、无效记录和原始文件校验结果。
- [ ] 更新 README 的运行命令、预计时长、恢复方式和数据不进入 Git 的说明。
