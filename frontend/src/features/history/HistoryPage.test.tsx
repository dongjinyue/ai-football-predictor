import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchDataSummary, fetchImportCatalog, fetchImportJob, fetchMatchPage, submitImportJob } from './api'
import HistoryPage from './HistoryPage'
import type { DataSummary, HistoricalMatch, MatchPage } from './types'

vi.mock('./api', () => ({
  fetchDataSummary: vi.fn(),
  fetchImportCatalog: vi.fn(),
  fetchImportJob: vi.fn(),
  fetchMatchPage: vi.fn(),
  submitImportJob: vi.fn(),
}))

const summary: DataSummary = {
  competitions: 1, teams: 20, matches: 380, marketSnapshots: 1140,
  marketOutcomes: 2660, latestKickoffAt: '2024-05-19T15:00:00Z',
  latestSuccessfulImportAt: '2026-09-12T10:00:00Z',
}
const match: HistoricalMatch = {
  id: 'arsenal-everton', competitionCode: 'E0', competitionName: '英超', season: '2324',
  kickoffAt: '2024-05-19T15:00:00Z', kickoffTimePrecision: 'exact', homeTeam: 'Arsenal', awayTeam: 'Everton',
  homeScore: 2, awayScore: 1, fullTimeResult: 'home', totalGoals: 3,
  halfTimeHomeScore: 1, halfTimeAwayScore: 0, halfTimeResult: 'home',
  markets: [
    { marketType: 'match_result', stage: 'closing', timePrecision: 'kickoff_bound',
      source: 'football_data', provider: 'average', capturedAt: '2024-05-19T15:00:00Z',
      availableAt: '2024-05-19T15:00:00Z', line: null,
      outcomes: [{ outcomeCode: 'home', odds: 1.22 }, { outcomeCode: 'draw', odds: 6.80 }, { outcomeCode: 'away', odds: 12.50 }] },
    { marketType: 'asian_handicap', stage: 'closing', timePrecision: 'kickoff_bound',
      source: 'football_data', provider: 'average', capturedAt: '2024-05-19T15:00:00Z',
      availableAt: '2024-05-19T15:00:00Z', line: -1.5,
      outcomes: [{ outcomeCode: 'home', odds: 1.50 }, { outcomeCode: 'away', odds: 2.60 }] },
    { marketType: 'over_under_2_5', stage: 'closing', timePrecision: 'kickoff_bound',
      source: 'football_data', provider: 'average', capturedAt: '2024-05-19T15:00:00Z',
      availableAt: '2024-05-19T15:00:00Z', line: 2.5,
      outcomes: [{ outcomeCode: 'over_2_5', odds: 1.40 }, { outcomeCode: 'under_2_5', odds: 2.90 }] },
  ],
}
const page: MatchPage = {
  page: 1, pageSize: 20, totalItems: 380, totalPages: 19,
  filters: {
    competitions: [
      { code: 'E0', name: '英格兰超级联赛' },
      { code: 'D1', name: '德国甲级联赛' },
    ],
    seasons: ['2324', '2425'],
  },
  items: Array.from({ length: 20 }, (_, index) => index === 0 ? match : {
    ...match, id: `match-${index}`, homeTeam: `主队 ${index}`, awayTeam: `客队 ${index}`,
  }),
}

beforeEach(() => {
  vi.resetAllMocks()
  window.history.replaceState(null, '', '/')
  vi.mocked(fetchDataSummary).mockResolvedValue(summary)
  vi.mocked(fetchMatchPage).mockResolvedValue(page)
  vi.mocked(fetchImportCatalog).mockResolvedValue({
    competitions: [{ code: 'E0', name: '英超', countryCode: 'ENG', seasonStyle: 'split_year' }],
    startYear: 2000,
    endYear: 2020,
  })
  vi.mocked(submitImportJob).mockResolvedValue({
    jobId: 'job-1', runId: null, status: 'queued', requestedFiles: 20,
    completedFiles: 0, failedFiles: 0, importedMatches: 0, skippedRows: 0,
    errors: [], currentCompetitionCode: null, currentSeason: null,
  })
  vi.mocked(fetchImportJob).mockResolvedValue({
    jobId: 'job-1', runId: 'run-1', status: 'completed', requestedFiles: 20,
    completedFiles: 20, failedFiles: 0, importedMatches: 380, skippedRows: 0,
    errors: [], currentCompetitionCode: 'E0', currentSeason: '1920',
  })
})
afterEach(() => { cleanup(); vi.useRealTimers() })

it('从列表进入详情时保留筛选和分页', async () => {
  window.history.replaceState(null, '', '/#history?season=2324&page=12&pageSize=20')
  render(<HistoryPage />)

  const link = (await screen.findAllByRole('link', { name: /市场详情/ }))[0]
  expect(link).toHaveAttribute(
    'href',
    expect.stringContaining('return=%23history%3Fseason%3D2324%26page%3D12%26pageSize%3D20'),
  )
})

describe('历史比赛页面', () => {
  it('体彩比赛只有日期时明确显示时间未知', async () => {
    vi.mocked(fetchMatchPage).mockResolvedValue({
      ...page,
      items: [{
        ...match,
        id: 'sporttery-date-only',
        kickoffAt: '2015-01-03T04:00:00Z',
        kickoffTimePrecision: 'date_only',
      }],
    })

    render(<HistoryPage />)

    expect(await screen.findByText('2015/1/3（时间未知）')).toBeInTheDocument()
    expect(screen.queryByText(/12:00:00/)).not.toBeInTheDocument()
  })

  it('does not clear a committed query until the draft is searched', async () => {
    window.history.replaceState(null, '', '/#history?team=Arsenal')
    render(<HistoryPage />)
    await screen.findByText('阿森纳 2–1 埃弗顿')
    const input = screen.getByLabelText('球队')
    fireEvent.change(input, { target: { value: '' } })
    expect(fetchMatchPage).toHaveBeenCalledTimes(1)
    expect(fetchMatchPage).toHaveBeenLastCalledWith(expect.objectContaining({ team: 'Arsenal' }), expect.any(AbortSignal))
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    await waitFor(() => expect(fetchMatchPage).toHaveBeenCalledTimes(2))
    expect(fetchMatchPage).toHaveBeenLastCalledWith(expect.objectContaining({ team: '' }), expect.any(AbortSignal))
  })

  it('turns a request that exceeds 30 seconds into a retryable error and aborts it', async () => {
    vi.useFakeTimers()
    vi.mocked(fetchMatchPage).mockReturnValue(new Promise(() => {}))
    vi.mocked(fetchDataSummary).mockReturnValue(new Promise(() => {}))
    render(<HistoryPage />)
    const matchSignal = vi.mocked(fetchMatchPage).mock.calls[0][1]
    const summarySignal = vi.mocked(fetchDataSummary).mock.calls[0][0]
    await act(async () => { vi.advanceTimersByTime(30000) })
    expect(screen.getByRole('button', { name: '重新加载比赛' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '重新加载摘要' })).toBeEnabled()
    expect(matchSignal.aborted).toBe(true)
    expect(summarySignal.aborted).toBe(true)
  })

  it('filters, resets page, clears all filters, and enforces pagination boundaries', async () => {
    vi.mocked(fetchMatchPage).mockImplementation(async (filters) => ({ ...page, page: filters.page ?? 1 }))
    render(<HistoryPage />)
    await screen.findByText('阿森纳 2–1 埃弗顿')
    expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    await screen.findByText('共 380 条')
    fireEvent.change(screen.getByLabelText('联赛'), { target: { value: 'E0' } })
    fireEvent.change(screen.getByLabelText('赛季'), { target: { value: '2324' } })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    await waitFor(() => expect(fetchMatchPage).toHaveBeenLastCalledWith(expect.objectContaining({ competition: 'E0', season: '2324', page: 1 }), expect.any(AbortSignal)))
    fireEvent.click(screen.getByRole('button', { name: '清除筛选' }))
    await waitFor(() => expect(fetchMatchPage).toHaveBeenLastCalledWith(expect.objectContaining({ competition: '', season: '', team: '', page: 1 }), expect.any(AbortSignal)))
    vi.mocked(fetchMatchPage).mockResolvedValue({ ...page, page: 19, items: [match] })
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled())
  })

  it('shows Chinese competition names and submits draft filters only after search', async () => {
    render(<HistoryPage />)
    await screen.findByText('阿森纳 2–1 埃弗顿')
    expect(screen.getByRole('option', { name: '英超（E0）' })).toBeInTheDocument()
    expect(fetchMatchPage).toHaveBeenCalledTimes(1)

    fireEvent.change(screen.getByLabelText('联赛'), { target: { value: 'E0' } })
    fireEvent.change(screen.getByLabelText('开始日期'), { target: { value: '2024-05-01' } })
    fireEvent.change(screen.getByLabelText('结束日期'), { target: { value: '2024-05-31' } })
    fireEvent.change(screen.getByLabelText('球队'), { target: { value: 'Arsenal' } })
    expect(fetchMatchPage).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    await waitFor(() => expect(fetchMatchPage).toHaveBeenLastCalledWith(
      expect.objectContaining({
        competition: 'E0', team: 'Arsenal', startDate: '2024-05-01', endDate: '2024-05-31', page: 1,
      }),
      expect.any(AbortSignal),
    ))
    expect(window.location.hash).toContain('start_date=2024-05-01')
  })

  it('renders compact pagination controls and applies page size changes', async () => {
    vi.mocked(fetchMatchPage).mockImplementation(async (filters) => ({
      ...page,
      page: filters.page ?? 1,
      pageSize: filters.pageSize ?? 10,
      totalItems: 405,
      totalPages: Math.ceil(405 / (filters.pageSize ?? 10)),
    }))
    render(<HistoryPage />)
    await screen.findByText('阿森纳 2–1 埃弗顿')

    expect(screen.getByText('共 405 条')).toBeInTheDocument()
    expect(screen.getByLabelText('每页条数')).toHaveValue('10')
    expect(screen.getByRole('button', { name: '第 1 页' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: '第 41 页' })).toBeInTheDocument()
    expect(document.querySelector('.history-page-ellipsis')).toBeInTheDocument()
    expect(screen.getByLabelText('前往页码')).toHaveValue(1)

    fireEvent.click(screen.getByRole('button', { name: '第 2 页' }))
    await waitFor(() => expect(fetchMatchPage).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2, pageSize: 10 }),
      expect.any(AbortSignal),
    ))
    expect(window.location.search).toBe('')
    expect(window.location.hash).toContain('#history?page=2')

    fireEvent.change(screen.getByLabelText('前往页码'), { target: { value: '41' } })
    fireEvent.keyDown(screen.getByLabelText('前往页码'), { key: 'Enter' })
    await waitFor(() => expect(fetchMatchPage).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 41, pageSize: 10 }),
      expect.any(AbortSignal),
    ))

    fireEvent.change(screen.getByLabelText('每页条数'), { target: { value: '20' } })
    await waitFor(() => expect(fetchMatchPage).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, pageSize: 20 }),
      expect.any(AbortSignal),
    ))
  })

  it('keeps team input as a draft and clears it without issuing a request', async () => {
    render(<HistoryPage />)
    await screen.findByText('阿森纳 2–1 埃弗顿')
    const input = screen.getByLabelText('球队')
    fireEvent.change(input, { target: { value: 'Arsenal' } })
    expect(fetchMatchPage).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: '清除球队搜索' }))
    expect(fetchMatchPage).toHaveBeenCalledTimes(1)
    expect(input).toHaveValue('')
    expect(input).toHaveFocus()
  })

  it('submits search and cancels older requests even if they later resolve', async () => {
    let resolveOld!: (value: MatchPage) => void
    vi.mocked(fetchMatchPage).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
    const { unmount } = render(<HistoryPage />)
    const oldSignal = vi.mocked(fetchMatchPage).mock.calls[0][1]
    const input = screen.getByLabelText('球队')
    fireEvent.change(input, { target: { value: 'Arsenal' } })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    await screen.findByText('阿森纳 2–1 埃弗顿')
    expect(oldSignal.aborted).toBe(true)
    await act(async () => { resolveOld({ ...page, items: [{ ...match, homeTeam: '过期队名' }] }) })
    expect(screen.queryByText(/过期队名/)).not.toBeInTheDocument()
    const latestSignal = vi.mocked(fetchMatchPage).mock.calls.at(-1)![1]
    unmount()
    expect(latestSignal.aborted).toBe(true)
  })

  it('uses an independent market detail link instead of expanding dense odds inline', async () => {
    render(<HistoryPage />)
    await screen.findByText('阿森纳 2–1 埃弗顿')
    const links = screen.getAllByRole('link', { name: /市场详情/ })
    expect(links[0]).toHaveAttribute('href', expect.stringContaining('#history/match/arsenal-everton'))
    expect(screen.queryByRole('region', { name: /市场详情/ })).not.toBeInTheDocument()
  })

  it('shows pending state without invented scores', () => {
    vi.mocked(fetchMatchPage).mockReturnValue(new Promise(() => {}))
    vi.mocked(fetchDataSummary).mockReturnValue(new Promise(() => {}))
    render(<HistoryPage />)
    expect(screen.getByRole('status', { name: '比赛加载状态' })).toHaveTextContent('正在加载比赛')
    expect(screen.queryByText(/Arsenal/)).not.toBeInTheDocument()
  })

  it('distinguishes an empty database from filtered no-results', async () => {
    vi.mocked(fetchDataSummary).mockResolvedValue({ ...summary, matches: 0 })
    vi.mocked(fetchMatchPage).mockResolvedValue({ ...page, totalItems: 0, totalPages: 0, items: [] })
    render(<HistoryPage />)
    expect(await screen.findByText('尚未导入历史比赛')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('联赛'), { target: { value: 'E0' } })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    expect(await screen.findByText('没有符合条件的比赛')).toBeInTheDocument()
    expect(screen.queryByText(/Arsenal/)).not.toBeInTheDocument()
  })

  it('recovers from a list error while preserving the summary and filters', async () => {
    vi.mocked(fetchMatchPage).mockRejectedValueOnce(new Error('private server path'))
    render(<HistoryPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('比赛加载失败')
    expect(screen.queryByText(/private server path/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重新加载比赛' }))
    expect(await screen.findByText('阿森纳 2–1 埃弗顿')).toBeInTheDocument()
  })

  it('keeps matches usable when the summary fails and retries only the summary', async () => {
    vi.mocked(fetchDataSummary).mockRejectedValueOnce(new Error('offline'))
    render(<HistoryPage />)
    expect(await screen.findByText('阿森纳 2–1 埃弗顿')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('摘要加载失败')
    fireEvent.click(screen.getByRole('button', { name: '重新加载摘要' }))
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(fetchMatchPage).toHaveBeenCalledTimes(1)
  })

  it('restores URL filters on load and browser history navigation', async () => {
    window.history.replaceState(null, '', '/#history?competition=E0&season=2324&team=Arsenal&page=3')
    vi.mocked(fetchMatchPage).mockImplementation(async (filters) => ({ ...page, page: filters.page ?? 1 }))
    render(<HistoryPage />)
    await screen.findByText('共 380 条')
    expect(screen.getByLabelText('球队')).toHaveValue('Arsenal')
    expect(window.location.search).toBe('')
    expect(window.location.hash).toContain('competition=E0')
    act(() => {
      window.history.replaceState(null, '', '/#history?competition=D1&page=2')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    await screen.findByText('共 380 条')
    expect(screen.getByLabelText('联赛')).toHaveValue('D1')
    expect(screen.getByLabelText('球队')).toHaveValue('')
  })

  it('renders real match scores, half-time scores, odds and the server page range', async () => {
    render(<HistoryPage />)
    const table = await screen.findByRole('table', { name: '历史比赛列表' })
    expect(within(table).getByText('阿森纳 2–1 埃弗顿')).toBeInTheDocument()
    expect(within(table).getAllByText('英超（E0）').length).toBeGreaterThan(0)
    expect(screen.getByRole('option', { name: '英超（E0）' })).toBeInTheDocument()
    expect(within(table).getAllByText('1–0')[0]).toBeInTheDocument()
    expect(within(table).getAllByText('胜 / 胜')[0]).toBeInTheDocument()
    expect(within(table).getAllByText('3')[0]).toBeInTheDocument()
    expect(within(table).getAllByText('1.22')[0]).toBeInTheDocument()
    expect(within(table).getAllByText('6.80')[0]).toBeInTheDocument()
    expect(within(table).getAllByText('12.50')[0]).toBeInTheDocument()
    expect(screen.getByText('共 380 条')).toBeInTheDocument()
  })

  it('uses handicap result odds as the row fallback without expanding dense outcomes inline', async () => {
    vi.mocked(fetchMatchPage).mockResolvedValue({
      ...page,
      totalItems: 1,
      totalPages: 1,
      items: [{
        ...match,
        id: 'handicap-only',
        markets: [
          { marketType: 'handicap_result', stage: 'closing', timePrecision: 'exact',
            source: 'sporttery', provider: 'china_sports_lottery', capturedAt: '2015-12-30T12:00:00Z',
            availableAt: '2015-12-30T12:00:00Z', line: -3,
            outcomes: [{ outcomeCode: 'home', odds: 2.62 }, { outcomeCode: 'draw', odds: 4.45 }, { outcomeCode: 'away', odds: 1.92 }] },
          { marketType: 'correct_score', stage: 'closing', timePrecision: 'exact',
            source: 'sporttery', provider: 'china_sports_lottery', capturedAt: '2015-12-28T12:00:00Z',
            availableAt: '2015-12-28T12:00:00Z', line: null,
            outcomes: [{ outcomeCode: '0_0', odds: 50 }, { outcomeCode: '0_1', odds: 80 }, { outcomeCode: 'other_home', odds: 120 }] },
          { marketType: 'half_full', stage: 'closing', timePrecision: 'exact',
            source: 'sporttery', provider: 'china_sports_lottery', capturedAt: '2015-12-28T12:00:00Z',
            availableAt: '2015-12-28T12:00:00Z', line: null,
            outcomes: [{ outcomeCode: 'away_away', odds: 14 }, { outcomeCode: 'draw_home', odds: 8 }] },
        ],
      }],
    })

    render(<HistoryPage />)
    const table = await screen.findByRole('table', { name: '历史比赛列表' })
    expect(within(table).getByText('让球 -3')).toBeInTheDocument()
    for (const odds of ['2.62', '4.45', '1.92']) expect(within(table).getByText(odds)).toBeInTheDocument()

    expect(screen.getByRole('link', { name: /市场详情/ })).toHaveAttribute(
      'href',
      expect.stringContaining('#history/match/handicap-only'),
    )
    expect(screen.queryByText('away_away')).not.toBeInTheDocument()
  })

  it('refreshes Sporttery data without offering the old source import', async () => {
    render(<HistoryPage />)
    await screen.findByText('阿森纳 2–1 埃弗顿')
    expect(screen.queryByRole('button', { name: '导入历史数据' })).not.toBeInTheDocument()
    expect(screen.getByText('中国竞彩 · Sporttery')).toBeInTheDocument()
    const before = vi.mocked(fetchMatchPage).mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: '刷新竞彩数据' }))
    await waitFor(() => expect(fetchMatchPage).toHaveBeenCalledTimes(before + 1))
  })

})
