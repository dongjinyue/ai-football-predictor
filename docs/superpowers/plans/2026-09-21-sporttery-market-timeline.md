# Sporttery Market Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每场中国竞彩彩票比赛提供独立的市场详情页，完整展示已入库的胜平负、让球胜平负、比分、总进球和半全场赔率时间线及相邻快照涨跌。

**Architecture:** 历史比赛列表继续只读取轻量的最新赔率；新的后端详情查询通过核心比赛的 `source_match_id` 关联 `sporttery_matches`，并直接按比赛读取 `sporttery_bonus_snapshots` 与 `sporttery_bonus_outcomes`。前端使用 `#history/match/<match-id>` 子路由按需请求详情，把每种玩法及每个让球盘口渲染为独立时间线表格，并通过 `return` 参数恢复原列表筛选与分页。

**Tech Stack:** Python 3.13、FastAPI（Web API 框架）、DuckDB（嵌入式分析数据库）、Pydantic（数据校验）、pytest（后端测试）；React 19、TypeScript、Vite、Vitest、Testing Library、Lucide React。

**Spec:** `docs/superpowers/specs/2026-09-21-sporttery-market-timeline-design.md`

## Global Constraints

- 完整时间线只能读取 `sporttery_bonus_snapshots` 和 `sporttery_bonus_outcomes`，不得从仅保留最新快照的通用 `market_snapshots` 重建。
- 历史列表接口保持轻量；完整赔率只在打开单场详情时查询。
- 固定玩法顺序为胜平负、让球胜平负、比分、总进球、半全场；结果列按业务含义排序，不按字符串排序。
- 赔率显示两位小数，时间按 `Asia/Shanghai` 显示到秒，缺失值显示 `—`，不得用 `0` 冒充缺失数据。
- 涨跌必须同时提供箭头和可访问文本，颜色只能作为辅助信息。
- 仅有让球胜平负的比赛必须正常显示，并按不同盘口拆成独立表格。
- 页面沿用现有浅色研究工作台设计，不仿制竞彩网品牌页，不使用卡片嵌套。
- 本阶段不重新抓取数据、不改变训练数据定义、不实现模型训练。

## Review Focus

- `match_id` 含特殊字符或不存在时，SQL 使用参数绑定且 API 返回 404，不泄露数据库异常；Task 1 与 Task 2 覆盖。
- 同一比赛同一发布时间存在多个玩法或盘口时，不得互相覆盖或串行；Task 1 覆盖。
- 某次快照缺少一个结果选项时，该单元格显示 `—`，后续涨跌只与该列上一个实际快照比较；Task 4 覆盖。
- 详情页刷新、直接访问和返回列表时，比赛 ID 与原筛选 URL 都能可靠解码；Task 3 与 Task 5 覆盖。
- 比分玩法列很多且窄屏显示时，表格允许横向滚动，列头与赔率不重叠；Task 5 与 Task 6 覆盖。

---

### Task 1: 完整赔率时间线仓储查询

**Files:**
- Modify: `backend/app/imports/models.py`
- Modify: `backend/app/imports/repository.py`
- Test: `backend/tests/test_import_repository.py`

**Interfaces:**
- Consumes: `ImportRepository.database_path`、核心 `matches.source_match_id`、`sporttery_matches.match_id`、`sporttery_bonus_snapshots`、`sporttery_bonus_outcomes`。
- Produces: `ImportRepository.get_match_market_history(match_id: str) -> MatchMarketHistoryView | None`，以及不可变类型 `MarketHistorySnapshotView`、`MarketHistoryGroupView`、`MatchMarketHistoryView`。

- [ ] **Step 1: 写出多玩法、多快照、盘口分组和跨比赛隔离的失败测试**

```python
def test_get_match_market_history_returns_all_snapshots_in_business_order(tmp_path):
    repository = ImportRepository(tmp_path / "football_predictor.duckdb")
    seed_sporttery_match(repository, core_id="sporttery:70001", source_match_id="70001")
    seed_bonus_snapshot(repository, 70001, "had", None, "2015-01-01 08:00:00", {"h": 2.10, "d": 3.10, "a": 3.40})
    seed_bonus_snapshot(repository, 70001, "had", None, "2015-01-01 10:00:00", {"h": 2.00, "d": 3.20, "a": 3.50})
    seed_bonus_snapshot(repository, 70001, "hhad", -1.0, "2015-01-01 09:00:00", {"h": 3.80, "d": 3.55, "a": 1.72})
    seed_bonus_snapshot(repository, 79999, "had", None, "2015-01-01 07:00:00", {"h": 1.01})

    result = repository.get_match_market_history("sporttery:70001")

    assert result is not None
    assert [(group.market_type, group.line) for group in result.markets] == [
        ("match_result", None),
        ("handicap_result", -1.0),
    ]
    assert [snapshot.captured_at.hour for snapshot in result.markets[0].snapshots] == [8, 10]
    assert result.markets[0].outcome_codes == ("home", "draw", "away")
    assert all(1.01 not in dict(snapshot.outcomes).values() for group in result.markets for snapshot in group.snapshots)
```

同时增加：存在比赛但没有赔率时 `markets == ()`；未知 ID 返回 `None`；比分、总进球、半全场的 `outcome_codes` 符合规范中的业务顺序；同一 `captured_at` 下不同盘口不会合并。

- [ ] **Step 2: 运行仓储测试并确认失败原因是方法和模型尚不存在**

Run: `C:\Users\24315\miniconda3\python.exe -m pytest backend/tests/test_import_repository.py -k market_history -v`

Expected: FAIL，提示 `ImportRepository` 没有 `get_match_market_history` 或无法导入新视图类型。

- [ ] **Step 3: 增加不可变领域视图与明确的市场排序常量**

```python
@dataclass(frozen=True)
class MarketHistorySnapshotView:
    captured_at: datetime
    available_at: datetime
    outcomes: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class MarketHistoryGroupView:
    market_type: str
    line: float | None
    source: str
    provider: str
    stage: str
    time_precision: str
    outcome_codes: tuple[str, ...]
    snapshots: tuple[MarketHistorySnapshotView, ...]


@dataclass(frozen=True)
class MatchMarketHistoryView:
    id: str
    competition_code: str
    competition_name: str
    season: str
    kickoff_at: datetime
    kickoff_time_precision: str
    home_team: str
    away_team: str
    half_time_home_score: int | None
    half_time_away_score: int | None
    home_score: int | None
    away_score: int | None
    markets: tuple[MarketHistoryGroupView, ...]
```

在仓储中定义接口原始玩法到页面玩法的映射 `had -> match_result`、`hhad -> handicap_result`、`crs -> correct_score`、`ttg -> total_goals`、`hafu -> half_full`，并为每种玩法定义完整结果顺序。

- [ ] **Step 4: 使用一次参数化明细查询实现聚合，不做逐快照 N+1 查询**

```python
def get_match_market_history(self, match_id: str) -> MatchMarketHistoryView | None:
    with duckdb.connect(str(self.database_path), read_only=True) as connection:
        match_row = connection.execute(
            """
            SELECT m.id, m.competition_code, m.competition_name, m.season,
                   m.kickoff_at, m.kickoff_time_precision, m.home_team, m.away_team,
                   m.half_time_home_score, m.half_time_away_score,
                   m.home_score, m.away_score, sm.match_id
            FROM matches AS m
            JOIN sporttery_matches AS sm
              ON CAST(sm.match_id AS VARCHAR) = m.source_match_id
            WHERE m.id = ? AND m.source = 'sporttery'
            """,
            [match_id],
        ).fetchone()
        if match_row is None:
            return None

        rows = connection.execute(
            """
            SELECT s.id, s.market_type, s.handicap, s.handicap_key, s.captured_at,
                   o.outcome_code, o.odds_value
            FROM sporttery_bonus_snapshots AS s
            LEFT JOIN sporttery_bonus_outcomes AS o ON o.snapshot_id = s.id
            WHERE s.match_id = ?
            ORDER BY s.captured_at, s.id
            """,
            [match_row[-1]],
        ).fetchall()
        return self._build_match_market_history(match_row, rows)
```

`_build_match_market_history` 先按 `(market_type, handicap_key)` 分组，再按 `snapshot_id` 聚合结果；空结果列保留在 `outcome_codes` 中，快照按 `captured_at` 升序，市场按固定业务顺序和盘口数值排序。`available_at` 与 `captured_at` 使用同一官方发布时间，`source="sporttery"`、`provider="china_sports_lottery"`、`stage="closing"`、`time_precision="exact"`。

- [ ] **Step 5: 运行仓储测试并提交**

Run: `C:\Users\24315\miniconda3\python.exe -m pytest backend/tests/test_import_repository.py -k market_history -v`

Expected: PASS，且多快照、空赔率、未知 ID、业务顺序和数据隔离断言全部通过。

```powershell
git add backend/app/imports/models.py backend/app/imports/repository.py backend/tests/test_import_repository.py
git commit -m "feat: query sporttery market timelines"
```

### Task 2: 单场市场历史 API（接口）

**Files:**
- Modify: `backend/app/imports/router.py`
- Modify: `backend/tests/test_import_api.py`

**Interfaces:**
- Consumes: `get_match_market_history(match_id: str) -> MatchMarketHistoryView | None`。
- Produces: `GET /api/data/matches/{match_id}/market-history`，返回 camel_case（驼峰命名）JSON 中的比赛信息与 `markets[].snapshots[]`。

- [ ] **Step 1: 写出成功、空市场、未知比赛和仓储异常的失败 API 测试**

```python
def test_get_match_market_history_returns_full_timeline(client, fake_repository):
    fake_repository.market_history = match_market_history_fixture()

    response = client.get("/api/data/matches/sporttery%3A70001/market-history")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "sporttery:70001"
    assert payload["markets"][0]["market_type"] == "match_result"
    assert [row["captured_at"] for row in payload["markets"][0]["snapshots"]] == [
        "2015-01-01T08:00:00",
        "2015-01-01T10:00:00",
    ]


def test_get_match_market_history_returns_404_for_unknown_match(client, fake_repository):
    fake_repository.market_history = None
    response = client.get("/api/data/matches/missing/market-history")
    assert response.status_code == 404
    assert response.json() == {"detail": "match_not_found"}
```

另加两个测试：已知比赛且 `markets=()` 返回 200；仓储抛异常返回 `500 {"detail":"internal_error"}` 且不包含异常路径。

- [ ] **Step 2: 运行 API 测试并确认新路由为 404**

Run: `C:\Users\24315\miniconda3\python.exe -m pytest backend/tests/test_import_api.py -k market_history -v`

Expected: FAIL，新 URL 尚未注册。

- [ ] **Step 3: 扩展仓储 Protocol（协议）并定义显式响应模型**

```python
class MarketHistorySnapshotResponse(BaseModel):
    captured_at: datetime
    available_at: datetime
    outcomes: tuple[MarketOutcomeResponse, ...]


class MarketHistoryGroupResponse(BaseModel):
    market_type: str
    line: float | None
    source: str
    provider: str
    stage: str
    time_precision: str
    outcome_codes: tuple[str, ...]
    snapshots: tuple[MarketHistorySnapshotResponse, ...]


class MatchMarketHistoryResponse(BaseModel):
    id: str
    competition_code: str
    competition_name: str
    season: str
    kickoff_at: datetime
    kickoff_time_precision: Literal["exact", "date_only"]
    home_team: str
    away_team: str
    half_time_home_score: int | None
    half_time_away_score: int | None
    home_score: int | None
    away_score: int | None
    markets: tuple[MarketHistoryGroupResponse, ...]
```

- [ ] **Step 4: 新增只读路由并显式映射领域对象**

```python
@router.get("/matches/{match_id}/market-history", response_model=MatchMarketHistoryResponse)
def get_match_market_history(match_id: str, request: Request) -> MatchMarketHistoryResponse:
    try:
        resolved_repository = repository or request.app.state.import_repository
        result = resolved_repository.get_match_market_history(match_id)
    except Exception:
        logger.exception("读取单场竞彩彩票赔率时间线失败")
        raise HTTPException(status_code=500, detail="internal_error") from None
    if result is None:
        raise HTTPException(status_code=404, detail="match_not_found")
    return _match_market_history_response(result)
```

`_match_market_history_response` 逐层构造响应模型，不能直接把 DuckDB 行或内部对象透传给客户端。

- [ ] **Step 5: 运行 API 测试并提交**

Run: `C:\Users\24315\miniconda3\python.exe -m pytest backend/tests/test_import_api.py -k market_history -v`

Expected: PASS，四种状态都返回稳定的 HTTP 状态码和响应结构。

```powershell
git add backend/app/imports/router.py backend/tests/test_import_api.py
git commit -m "feat: expose sporttery market history api"
```

### Task 3: 前端详情类型、API 客户端与子路由工具

**Files:**
- Modify: `frontend/src/features/history/types.ts`
- Modify: `frontend/src/features/history/api.ts`
- Modify: `frontend/src/features/history/api.test.ts`
- Modify: `frontend/src/routing.ts`
- Create: `frontend/src/routing.test.ts`

**Interfaces:**
- Consumes: Task 2 的 JSON 响应。
- Produces: `fetchMatchMarketHistory(matchId: string, signal?: AbortSignal): Promise<MatchMarketHistory>`、`matchDetailRoute(hash: string): { matchId: string; returnHash: string } | null`、`buildMatchDetailHash(matchId: string, returnHash: string): string`。

- [ ] **Step 1: 写出 URL 编码、响应映射、404 分类和返回地址往返的失败测试**

```typescript
it('读取并映射单场竞彩彩票赔率时间线', async () => {
  vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(apiFixture), { status: 200 }))
  const result = await fetchMatchMarketHistory('sporttery:70001')
  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining('/matches/sporttery%3A70001/market-history'),
    expect.objectContaining({ signal: undefined }),
  )
  expect(result.markets[0].snapshots).toHaveLength(2)
})

it('详情哈希保留原历史筛选地址', () => {
  const returnHash = '#history?season=2015&page=12&pageSize=20'
  const hash = buildMatchDetailHash('sporttery:70001', returnHash)
  expect(matchDetailRoute(hash)).toEqual({ matchId: 'sporttery:70001', returnHash })
})
```

另加测试：后端 404 抛出带 `status=404` 的 `ApiError`；畸形百分号编码返回 `null` 而不是让应用崩溃；缺少 `return` 时回退到 `#history`。

- [ ] **Step 2: 运行前端单元测试并确认导出尚不存在**

Run: `npm test -- --run src/features/history/api.test.ts src/routing.test.ts`

Working directory: `frontend`

Expected: FAIL，提示新类型或函数未导出。

- [ ] **Step 3: 定义与 API 一一对应的 TypeScript 类型**

```typescript
export interface MarketHistorySnapshot {
  capturedAt: string
  availableAt: string
  outcomes: MarketOutcome[]
}

export interface MarketHistoryGroup {
  marketType: string
  line: number | null
  source: string
  provider: string
  stage: string
  timePrecision: string
  outcomeCodes: string[]
  snapshots: MarketHistorySnapshot[]
}

export interface MatchMarketHistory {
  id: string
  competitionCode: string
  competitionName: string
  season: string
  kickoffAt: string
  kickoffTimePrecision: 'exact' | 'date_only'
  homeTeam: string
  awayTeam: string
  halfTimeHomeScore: number | null
  halfTimeAwayScore: number | null
  homeScore: number | null
  awayScore: number | null
  markets: MarketHistoryGroup[]
}
```

- [ ] **Step 4: 实现请求映射与安全的详情哈希解析**

```typescript
export async function fetchMatchMarketHistory(matchId: string, signal?: AbortSignal) {
  const response = await fetch(
    apiUrl(`/api/data/matches/${encodeURIComponent(matchId)}/market-history`),
    { signal },
  )
  if (!response.ok) throw new ApiError(response.status, '读取市场详情失败')
  return mapMatchMarketHistory(await response.json())
}

export function buildMatchDetailHash(matchId: string, returnHash: string): string {
  const params = new URLSearchParams({ return: returnHash || '#history' })
  return buildHash(`history/match/${encodeURIComponent(matchId)}`, params)
}

export function matchDetailRoute(value: string) {
  const match = hashRoute(value).match(/^history\/match\/([^/]+)$/)
  if (!match) return null
  try {
    return {
      matchId: decodeURIComponent(match[1]),
      returnHash: hashParams(value).get('return') || '#history',
    }
  } catch {
    return null
  }
}
```

- [ ] **Step 5: 运行测试并提交**

Run: `npm test -- --run src/features/history/api.test.ts src/routing.test.ts`

Working directory: `frontend`

Expected: PASS，包括冒号 ID、原列表参数、404 和畸形编码。

```powershell
git add frontend/src/features/history/types.ts frontend/src/features/history/api.ts frontend/src/features/history/api.test.ts frontend/src/routing.ts frontend/src/routing.test.ts
git commit -m "feat: add market history client and route"
```

### Task 4: 可访问的赔率时间线表格

**Files:**
- Create: `frontend/src/features/history/OddsTimelineTable.tsx`
- Create: `frontend/src/features/history/MarketHistorySection.tsx`
- Create: `frontend/src/features/history/OddsTimelineTable.test.tsx`
- Modify: `frontend/src/features/history/display.ts`

**Interfaces:**
- Consumes: `MarketHistoryGroup`、现有来源/提供方/阶段/时间精度显示函数。
- Produces: `OddsTimelineTable({ market }: { market: MarketHistoryGroup })` 和 `MarketHistorySection({ market }: { market: MarketHistoryGroup })`。

- [ ] **Step 1: 写出列顺序、缺失值、涨跌和盘口标题的失败组件测试**

```tsx
it('按固定列顺序显示赔率并标记相邻快照涨跌', () => {
  render(<OddsTimelineTable market={matchResultFixture} />)
  expect(screen.getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
    '发布时间', '胜', '平', '负',
  ])
  expect(screen.getByLabelText('胜赔率从 2.10 降至 2.00')).toBeInTheDocument()
  expect(screen.getByLabelText('平赔率从 3.10 升至 3.20')).toBeInTheDocument()
})

it('缺失结果显示破折号且不跨缺失值制造涨跌', () => {
  render(<OddsTimelineTable market={missingOutcomeFixture} />)
  expect(screen.getAllByText('—')).not.toHaveLength(0)
  expect(screen.queryByLabelText(/从 .* 升至|从 .* 降至/)).not.toBeInTheDocument()
})
```

再加测试：总进球为 `0..7+`；半全场为九个中文列；比分为业务顺序；让球 `-1` 出现在分区标题；只有让球市场也能独立渲染。

- [ ] **Step 2: 运行组件测试并确认组件尚不存在**

Run: `npm test -- --run src/features/history/OddsTimelineTable.test.tsx`

Working directory: `frontend`

Expected: FAIL，无法导入新组件。

- [ ] **Step 3: 增加玩法与结果中文标签映射**

```typescript
export const marketHistoryLabels: Record<string, string> = {
  match_result: '胜平负固定奖金',
  handicap_result: '让球胜平负固定奖金',
  correct_score: '比分固定奖金',
  total_goals: '总进球固定奖金',
  half_full: '半全场胜平负固定奖金',
}

export function historyOutcomeLabel(code: string): string {
  return {
    home: '胜', draw: '平', away: '负',
    '7_plus': '7+',
    home_home: '胜胜', home_draw: '胜平', home_away: '胜负',
    draw_home: '平胜', draw_draw: '平平', draw_away: '平负',
    away_home: '负胜', away_draw: '负平', away_away: '负负',
  }[code] ?? code.replaceAll('_', ':')
}
```

- [ ] **Step 4: 实现稳定列宽、秒级时间、两位小数及非颜色涨跌提示**

```tsx
function OddsCell({ code, current, previous }: OddsCellProps) {
  if (current === undefined) return <td>—</td>
  const direction = previous === undefined || current === previous
    ? null
    : current > previous ? 'up' : 'down'
  const label = direction
    ? `${historyOutcomeLabel(code)}赔率从 ${previous!.toFixed(2)}${direction === 'up' ? '升至' : '降至'} ${current.toFixed(2)}`
    : undefined
  return <td className={direction ? `odds-${direction}` : undefined}>
    <span>{current.toFixed(2)}</span>
    {direction && <span aria-label={label} className="odds-direction">
      {direction === 'up' ? <ArrowUp aria-hidden="true" /> : <ArrowDown aria-hidden="true" />}
    </span>}
  </td>
}
```

每一行只从紧邻的上一快照读取同列值；上一快照缺列时 `previous` 为 `undefined`，不显示方向。时间使用 `Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', ...秒级字段 })`。表格外层使用可聚焦、带中文 `aria-label` 的横向滚动容器。

- [ ] **Step 5: 运行测试并提交**

Run: `npm test -- --run src/features/history/OddsTimelineTable.test.tsx`

Working directory: `frontend`

Expected: PASS，列顺序、缺失值、格式、盘口及涨跌语义均正确。

```powershell
git add frontend/src/features/history/OddsTimelineTable.tsx frontend/src/features/history/MarketHistorySection.tsx frontend/src/features/history/OddsTimelineTable.test.tsx frontend/src/features/history/display.ts
git commit -m "feat: render accessible odds timelines"
```

### Task 5: 独立详情页、列表导航与所有页面状态

**Files:**
- Create: `frontend/src/features/history/MatchMarketHistoryPage.tsx`
- Create: `frontend/src/features/history/MatchMarketHistoryPage.test.tsx`
- Modify: `frontend/src/features/history/MatchTable.tsx`
- Modify: `frontend/src/features/history/HistoryPage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `matchDetailRoute`、`buildMatchDetailHash`、`fetchMatchMarketHistory`、`MarketHistorySection`。
- Produces: 可直接刷新的 `#history/match/<match-id>?return=...` 页面；列表中的“市场详情”链接；加载、404、空市场、请求失败重试和成功视图。

- [ ] **Step 1: 写出列表跳转与详情路由的失败测试**

```tsx
it('从列表进入详情时保留筛选和分页', async () => {
  window.location.hash = '#history?season=2015&page=12&pageSize=20'
  render(<HistoryPage />)
  const link = await screen.findByRole('link', { name: /市场详情/ })
  expect(link).toHaveAttribute(
    'href',
    expect.stringContaining('return=%23history%3Fseason%3D2015%26page%3D12%26pageSize%3D20'),
  )
})

it('详情子路由渲染独立页面而不是历史列表', async () => {
  window.location.hash = '#history/match/sporttery%3A70001?return=%23history%3Fseason%3D2015'
  render(<App />)
  expect(await screen.findByRole('heading', { name: /主队.*客队/ })).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: '历史比赛' })).not.toBeInTheDocument()
})
```

- [ ] **Step 2: 写出详情页加载、成功、空市场、404 和重试失败测试**

```tsx
it('没有赔率时仍显示比赛信息与明确说明', async () => {
  mockFetchMatchMarketHistory.mockResolvedValue({ ...detailFixture, markets: [] })
  render(<MatchMarketHistoryPage matchId="sporttery:70001" returnHash="#history" />)
  expect(await screen.findByText('该场比赛没有已采集的赔率记录')).toBeInTheDocument()
  expect(screen.getByText(/主队/)).toBeInTheDocument()
})

it('请求失败后可以重试', async () => {
  mockFetchMatchMarketHistory
    .mockRejectedValueOnce(new Error('network'))
    .mockResolvedValueOnce(detailFixture)
  render(<MatchMarketHistoryPage matchId="sporttery:70001" returnHash="#history" />)
  await userEvent.click(await screen.findByRole('button', { name: '重新加载' }))
  expect(await screen.findByText('胜平负固定奖金')).toBeInTheDocument()
})
```

另加测试：加载中显示稳定状态区；`ApiError(404)` 显示“比赛不存在或已被移除”；卸载时取消旧请求；返回链接精确等于传入的 `returnHash`。

- [ ] **Step 3: 运行页面测试并确认失败**

Run: `npm test -- --run src/features/history/HistoryPage.test.tsx src/features/history/MatchMarketHistoryPage.test.tsx src/App.test.tsx`

Working directory: `frontend`

Expected: FAIL，详情组件和子路由尚未接入。

- [ ] **Step 4: 把表格行内展开替换成独立详情链接**

```tsx
const returnHash = window.location.hash || '#history'

<a
  className="history-button"
  href={buildMatchDetailHash(match.id, returnHash)}
  aria-label={`查看${homeTeam}对${awayTeam}的市场详情`}
>
  市场详情
</a>
```

删除 `expandedMatchId`、`MarketDetails` 和行内详情 `<tr>`，保持列表的 10 列宽度与分页行为不变。

- [ ] **Step 5: 实现详情页请求生命周期和页面语义结构**

```tsx
export default function MatchMarketHistoryPage({ matchId, returnHash }: Props) {
  const [requestVersion, setRequestVersion] = useState(0)
  const [state, setState] = useState<LoadState>({ status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    setState({ status: 'loading' })
    fetchMatchMarketHistory(matchId, controller.signal)
      .then((data) => setState({ status: 'ready', data }))
      .catch((error) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setState({ status: error instanceof ApiError && error.status === 404 ? 'not-found' : 'error' })
      })
    return () => controller.abort()
  }, [matchId, requestVersion])

  return <section className="market-history-page">
    <a className="back-link" href={returnHash}><ArrowLeft aria-hidden="true" />返回历史比赛</a>
    {/* 根据 state 渲染稳定标题区、比赛摘要、空状态、重试按钮或市场分区。 */}
  </section>
}
```

将注释处实现为明确的条件分支：`loading` 显示“正在加载市场记录”；`not-found` 显示不存在说明；`error` 显示失败说明和调用 `setRequestVersion(value => value + 1)` 的“重新加载”按钮；`ready` 显示比赛摘要并映射 `MarketHistorySection`，市场为空时显示指定空数据文案。

- [ ] **Step 6: 在 App 中识别详情子路由并保持侧栏历史项激活**

```tsx
const detailRoute = matchDetailRoute(hash)
const isHistory = activeRoute === 'history' || detailRoute !== null

{detailRoute ? (
  <MatchMarketHistoryPage
    matchId={detailRoute.matchId}
    returnHash={detailRoute.returnHash}
  />
) : isHistory ? (
  <HistoryPage />
) : isQuality ? (
  <DataQualityPage />
) : (
  <TodayPage />
)}
```

页面标题对详情路由使用“市场详情 · 赛前分析台”，侧栏“历史比赛”继续带 `aria-current="page"`。

- [ ] **Step 7: 运行页面测试并提交**

Run: `npm test -- --run src/features/history/HistoryPage.test.tsx src/features/history/MatchMarketHistoryPage.test.tsx src/App.test.tsx`

Working directory: `frontend`

Expected: PASS，列表状态保留、详情直达和五种页面状态全部通过。

```powershell
git add frontend/src/features/history/MatchMarketHistoryPage.tsx frontend/src/features/history/MatchMarketHistoryPage.test.tsx frontend/src/features/history/MatchTable.tsx frontend/src/features/history/HistoryPage.test.tsx frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat: add standalone market history page"
```

### Task 6: 响应式视觉收尾与端到端回归

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/features/history/MatchMarketHistoryPage.test.tsx`

**Interfaces:**
- Consumes: Task 4 和 Task 5 生成的语义类名与组件结构。
- Produces: 桌面和窄屏均不重叠、比分表格可横向滚动、列宽稳定的最终页面。

- [ ] **Step 1: 增加滚动区域与表格稳定性断言**

```tsx
it('时间线使用可访问的横向滚动区域和稳定表格类名', async () => {
  render(<MatchMarketHistoryPage matchId="sporttery:70001" returnHash="#history" />)
  const region = await screen.findByRole('region', { name: '比分固定奖金赔率时间线' })
  expect(region).toHaveClass('odds-timeline-scroll')
  expect(within(region).getByRole('table')).toHaveClass('odds-timeline-table')
})
```

- [ ] **Step 2: 运行测试并确认样式契约尚未满足**

Run: `npm test -- --run src/features/history/MatchMarketHistoryPage.test.tsx`

Working directory: `frontend`

Expected: FAIL，滚动区域或稳定类名缺失。

- [ ] **Step 3: 增加全宽分区、固定列宽和窄屏滚动样式**

```css
.market-history-page {
  width: min(1120px, 100%);
  margin: 0 auto;
}

.market-history-section {
  padding: 28px 0;
  border-top: 1px solid var(--line);
}

.odds-timeline-scroll {
  width: 100%;
  overflow-x: auto;
  overscroll-behavior-inline: contain;
}

.odds-timeline-table {
  width: 100%;
  min-width: max-content;
  table-layout: fixed;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}

.odds-timeline-table th:first-child,
.odds-timeline-table td:first-child {
  width: 176px;
  min-width: 176px;
}

.odds-timeline-table th:not(:first-child),
.odds-timeline-table td:not(:first-child) {
  width: 84px;
  min-width: 84px;
  text-align: center;
}

@media (max-width: 720px) {
  .market-match-summary {
    grid-template-columns: 1fr;
  }
}
```

复用现有 CSS 变量；上涨与下跌使用现有状态色，同时保留箭头，不新增渐变、装饰性圆球或嵌套卡片。

- [ ] **Step 4: 运行完整后端与前端验证**

Run: `C:\Users\24315\miniconda3\python.exe -m pytest backend/tests -q`

Expected: 全部后端测试 PASS。

Run: `npm test -- --run`

Working directory: `frontend`

Expected: 全部前端测试 PASS。

Run: `npm run lint`

Working directory: `frontend`

Expected: 无 ESLint（代码质量检查）错误。

Run: `npm run build`

Working directory: `frontend`

Expected: TypeScript 编译和 Vite 生产构建成功。

- [ ] **Step 5: 启动应用并做浏览器视觉验证**

Run: `C:\Users\24315\miniconda3\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`

Working directory: `backend`

Expected: 后端监听 `http://127.0.0.1:8000`。

Run: `npm run dev -- --host 127.0.0.1`

Working directory: `frontend`

Expected: Vite 输出一个可访问的本地 URL。使用已入库且包含多快照的 Sporttery 比赛验证桌面宽度和约 390px 手机宽度：返回链接恢复筛选、五类玩法顺序正确、让球盘口清晰、比分表只在自身区域横向滚动、文字与赔率不重叠、控制台无错误。

- [ ] **Step 6: 提交样式与测试收尾**

```powershell
git add frontend/src/index.css frontend/src/features/history/MatchMarketHistoryPage.test.tsx
git commit -m "style: finish responsive market timelines"
```

