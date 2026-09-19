# Historical Match Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在前端提供可筛选、可分页、可展开查看赔率时间信息的真实历史比赛列表。

**Architecture:** DuckDB 仓储执行参数化筛选、服务端分页以及当前页市场批量查询，FastAPI 用明确的 Pydantic 响应模型公开结果。React 通过独立 API 客户端加载摘要和比赛页，在 hash 页面导航中渲染响应式表格，不引入路由或表格依赖。

**Tech Stack:** Python、FastAPI、Pydantic、DuckDB、pytest、React、TypeScript、Vite、Vitest、Testing Library、Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-09-13-historical-match-browser-design.md`

## Global Constraints

- 所有业务数据必须来自 DuckDB，不得写示例或虚构比赛。
- 默认按 `kickoff_at` 倒序，每页 20 场，`page_size` 最大 100。
- 只展示 `stage = closing` 的市场；`kickoff_bound` 必须解释为不能用于开球前回测。
- 只读浏览页面不得触发历史数据导入。
- 不新增 React Router 或通用数据表格依赖。
- 不实现预测模型、回测逻辑、CSV 导出或自动购票。
- 严格执行 TDD：每个行为先看到测试失败，再写最小实现。

---

### Task 1: 历史比赛查询领域模型与仓储分页

**Files:**
- Modify: `backend/app/imports/models.py`
- Modify: `backend/app/imports/repository.py`
- Test: `backend/tests/test_import_repository.py`

**Interfaces:**
- Consumes: 现有 `ImportRepository._connect()` 和 v4 数据库表。
- Produces: `MatchQuery`, `MatchMarketView`, `HistoricalMatchView`, `MatchFilterOptions`, `MatchPage`；`ImportRepository.list_matches(query: MatchQuery) -> MatchPage`。

- [ ] **Step 1: 写默认分页、排序和市场组合失败测试**

在真实 DuckDB 测试中导入至少两场 fixture（固定样例）比赛，然后断言：

```python
page = repository.list_matches(MatchQuery(page=1, page_size=1))
assert page.total_items == 2
assert page.total_pages == 2
assert len(page.items) == 1
assert page.items[0].kickoff_at > second_page.items[0].kickoff_at
assert {market.market_type for market in page.items[0].markets} == {
    "match_result", "over_under_2_5", "asian_handicap"
}
assert all(market.stage == "closing" for market in page.items[0].markets)
```

- [ ] **Step 2: 运行单测并确认因接口不存在而失败**

Run: `python -m pytest tests/test_import_repository.py -k list_matches -v`

Expected: FAIL，提示 `MatchQuery` 或 `list_matches` 尚未定义。

- [ ] **Step 3: 添加不可变查询和响应 dataclass（数据类）**

在 `models.py` 定义带明确类型的冻结数据类；`MatchQuery` 包含 `page`、`page_size`、`competition`、`season`、`team`，`MatchPage` 包含当前页、总数、总页数、筛选项和比赛元组。赔率选项使用 `tuple[tuple[str, float], ...]`，避免仓储向路由泄露 DuckDB 行对象。

- [ ] **Step 4: 实现两阶段批量查询**

在 `repository.py` 中用预定义条件片段和参数列表构造 WHERE；先 count（计数）和当前页比赛，再以当前页 ID 批量读取 closing 快照与 outcomes（赔率选项）。总页数使用：

```python
total_pages = (total_items + query.page_size - 1) // query.page_size
offset = (query.page - 1) * query.page_size
```

筛选项从 competitions、matches 中读取并稳定排序。球队条件使用 `lower(home.name_zh) LIKE ? OR lower(away.name_zh) LIKE ?`，转义用户输入中的 `%` 与 `_`，SQL 始终参数化。

- [ ] **Step 5: 运行默认查询测试并确认通过**

Run: `python -m pytest tests/test_import_repository.py -k list_matches -v`

Expected: PASS。

- [ ] **Step 6: 写筛选、空数据库和无边界失败测试**

分别断言联赛、赛季、球队大小写包含筛选；未知筛选返回空页；第二页；无赔率比赛；空数据库筛选项为空。添加包含 `%` 的球队查询，确认其按普通字符处理而不是通配符。

- [ ] **Step 7: 实现最小筛选与空状态支持并运行完整仓储测试**

Run: `python -m pytest tests/test_import_repository.py -v`

Expected: 全部 PASS。

- [ ] **Step 8: 提交仓储功能**

```bash
git add backend/app/imports/models.py backend/app/imports/repository.py backend/tests/test_import_repository.py
git commit -m "feat: query paginated historical matches"
```

### Task 2: 历史比赛 HTTP API（接口）

**Files:**
- Modify: `backend/app/imports/router.py`
- Modify: `backend/tests/test_import_api.py`

**Interfaces:**
- Consumes: `ImportRepository.list_matches(MatchQuery) -> MatchPage`。
- Produces: `GET /api/data/matches?page=1&page_size=20&competition=&season=&team=` 的稳定 JSON 响应。

- [ ] **Step 1: 扩展 FakeRepository 并写 API 响应失败测试**

测试固定响应应包含：

```python
assert response.json()["items"][0] == {
    "id": "match-1",
    "competition_code": "E0",
    "competition_name": "English Premier League",
    "season": "2324",
    "kickoff_at": "2024-05-19T15:00:00Z",
    "home_team": "Arsenal",
    "away_team": "Everton",
    "half_time_home_score": 1,
    "half_time_away_score": 0,
    "home_score": 2,
    "away_score": 1,
    "markets": response.json()["items"][0]["markets"],
}
```

并断言 fake 收到经过 trim（去首尾空格）的查询值。

- [ ] **Step 2: 运行 API 测试并确认 404 失败**

Run: `python -m pytest tests/test_import_api.py -k matches -v`

Expected: FAIL，`GET /api/data/matches` 返回 404。

- [ ] **Step 3: 添加 Pydantic 响应模型和路由**

定义 `MarketOutcomeResponse`、`MatchMarketResponse`、`HistoricalMatchResponse`、`FilterOptionResponse`、`MatchPageResponse`。使用 FastAPI `Query(ge=1)` 校验 `page`，使用 `Query(ge=1, le=100)` 校验 `page_size`；路由把可选字符串规范为空或去空格后的值，再调用仓储。

- [ ] **Step 4: 运行 API 正常路径测试**

Run: `python -m pytest tests/test_import_api.py -k matches -v`

Expected: PASS。

- [ ] **Step 5: 写并通过非法分页及安全错误测试**

断言 `page=0`、`page_size=101` 返回 422；仓储抛出包含本机路径的异常时返回 `{"detail":"internal_error"}` 且响应不含路径。

Run: `python -m pytest tests/test_import_api.py -v`

Expected: 全部 PASS。

- [ ] **Step 6: 提交 API 功能**

```bash
git add backend/app/imports/router.py backend/tests/test_import_api.py
git commit -m "feat: expose historical match browser API"
```

### Task 3: 前端 API 客户端与数据格式化

**Files:**
- Create: `frontend/src/features/history/types.ts`
- Create: `frontend/src/features/history/api.ts`
- Create: `frontend/src/features/history/api.test.ts`

**Interfaces:**
- Consumes: `API_BASE_URL` 和 Task 2 的 `/api/data/matches`、现有 `/api/data/summary`。
- Produces: `fetchMatchPage(filters, signal)`、`fetchDataSummary(signal)`、前端 `MatchPage` 与 `DataSummary` 类型。

- [ ] **Step 1: 写 URL 编码和响应失败测试**

Mock `fetch`，调用：

```typescript
await fetchMatchPage(
  { page: 2, pageSize: 20, competition: 'E0', season: '2324', team: 'Man Utd' },
  controller.signal,
)
expect(fetch).toHaveBeenCalledWith(
  expect.stringContaining('page=2&page_size=20&competition=E0&season=2324&team=Man+Utd'),
  { signal: controller.signal },
)
```

另测非 2xx 响应抛出统一 `DataRequestError`。

- [ ] **Step 2: 运行测试并确认模块不存在**

Run: `npm test -- --run src/features/history/api.test.ts`

Expected: FAIL，无法解析 `./api`。

- [ ] **Step 3: 定义类型并实现最小客户端**

使用 `URLSearchParams` 只追加非空筛选；请求选项只传 `signal`；对响应执行 `response.ok` 检查。不要在客户端生成比赛或赔率默认值。

- [ ] **Step 4: 运行客户端测试并提交**

Run: `npm test -- --run src/features/history/api.test.ts`

Expected: PASS。

```bash
git add frontend/src/features/history
git commit -m "feat: add historical match API client"
```

### Task 4: 历史比赛页面与导航

**Files:**
- Create: `frontend/src/features/history/HistoryPage.tsx`
- Create: `frontend/src/features/history/HistoryFilters.tsx`
- Create: `frontend/src/features/history/MatchTable.tsx`
- Create: `frontend/src/features/history/HistoryPage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: Task 3 客户端和类型。
- Produces: `#history` 可访问页面；摘要、筛选、表格、展开市场、分页及完整状态反馈。

- [ ] **Step 1: 写导航和成功渲染失败测试**

Mock API，点击“历史比赛”，断言标题、`Arsenal 2–1 Everton`、半场 `1–0`、1/X/2 赔率和“第 1–20 场，共 380 场”出现。

- [ ] **Step 2: 运行测试并确认失败**

Run: `npm test -- --run src/App.test.tsx src/features/history/HistoryPage.test.tsx`

Expected: FAIL，历史页面组件或可用导航不存在。

- [ ] **Step 3: 实现 hash 导航、加载和主表格**

`App` 监听 `hashchange`，只在 hash 为 `#history` 时渲染 `HistoryPage`，并兼容旧的中文哈希链接。页面挂载时并行请求摘要和第一页；effect cleanup（副作用清理）调用 `controller.abort()`。表格使用真实 `<table>`、`<thead>`、`<tbody>`，窄屏容器使用横向滚动。

- [ ] **Step 4: 运行成功路径测试并确认通过**

Run: `npm test -- --run src/App.test.tsx src/features/history/HistoryPage.test.tsx`

Expected: PASS。

- [ ] **Step 5: 写筛选、分页和展开详情失败测试**

使用 `userEvent` 或 Testing Library fireEvent：选择 E0、输入 Arsenal 后断言页码重置为 1 且请求参数正确；点击下一页断言请求 page 2；展开行断言显示亚洲让球 `1.50`、大小球和“仅能确认开球时可用，不能用于开球前回测”。

- [ ] **Step 6: 实现筛选、分页与单行展开**

筛选变化重置 page；清除按钮恢复空筛选；边界分页按钮设置 `disabled`；用单个 `expandedMatchId` 保证一次只展开一场。

- [ ] **Step 7: 写加载、空数据、无结果和错误失败测试并实现**

分别测试 pending Promise（等待中的 Promise）、空数据库、带筛选的空结果和 reject（拒绝）请求；错误状态提供“重新加载”，重试后再次调用 API。不得在任何状态显示虚构比分。

- [ ] **Step 8: 完成响应式样式和无障碍状态**

为筛选 label、展开按钮 `aria-expanded`、加载 `role=status`、错误 `role=alert` 添加语义；沿用现有颜色变量和 focus-visible（键盘焦点）样式。

- [ ] **Step 9: 运行前端测试、检查并提交**

Run: `npm test`

Expected: 全部 PASS。

Run: `npm run lint`

Expected: 无 ESLint 错误。

```bash
git add frontend/src
git commit -m "feat: add historical match browser page"
```

### Task 5: 全链路验证与文档

**Files:**
- Modify: `README.md`
- Create: `docs/verification/2026-09-13-historical-match-browser.md`

**Interfaces:**
- Consumes: Tasks 1–4 的完整功能。
- Produces: 可重复启动和核验的说明、最终验证记录。

- [ ] **Step 1: 更新 README 使用说明**

说明先启动后端和前端，再打开 `http://127.0.0.1:4173/#history`；注明页面只展示已导入数据，空页面时需先按现有导入说明导入数据。每条命令解释工作目录、端口和环境变量作用。

- [ ] **Step 2: 运行完整后端验证**

Run: `python -m pytest`

Expected: 全部 PASS。

- [ ] **Step 3: 运行完整前端验证**

Run: `npm test`

Expected: 全部 PASS。

Run: `npm run lint`

Expected: PASS。

Run: `npm run build`

Expected: TypeScript 编译和 Vite 生产构建成功。

- [ ] **Step 4: 使用真实演示数据库验证 API 与页面**

启动服务后请求 `/api/data/matches?page=1&page_size=20`，确认返回真实 E0 2324 比赛；浏览器打开历史比赛页，检查筛选、分页、展开区、窄屏横向滚动，确认控制台无错误。

- [ ] **Step 5: 写验证记录并检查差异**

记录执行命令、通过数量、真实数据规模和人工页面检查结果。

Run: `git diff --check main...HEAD`

Expected: 无空白错误。

- [ ] **Step 6: 提交文档**

```bash
git add README.md docs/verification/2026-09-13-historical-match-browser.md
git commit -m "docs: explain historical match browser"
```

- [ ] **Step 7: 完成前执行独立代码审查**

对照设计的 11 条验收标准逐条核验，修复所有阻断问题后重新运行 Step 2、3、5 的完整验证。随后推送分支并创建 Pull Request，等待用户确认后再合并。
