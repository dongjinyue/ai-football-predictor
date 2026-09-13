import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchDataSummary, fetchMatchPage } from './api'
import HistoryPage from './HistoryPage'
import type { DataSummary, HistoricalMatch, MatchPage } from './types'

vi.mock('./api', () => ({ fetchDataSummary: vi.fn(), fetchMatchPage: vi.fn() }))

const summary: DataSummary = {
  competitions: 1, teams: 20, matches: 380, marketSnapshots: 1140,
  marketOutcomes: 2660, latestKickoffAt: '2024-05-19T15:00:00Z',
  latestSuccessfulImportAt: '2026-09-12T10:00:00Z',
}
const match: HistoricalMatch = {
  id: 'arsenal-everton', competitionCode: 'E0', competitionName: '英超', season: '2324',
  kickoffAt: '2024-05-19T15:00:00Z', homeTeam: 'Arsenal', awayTeam: 'Everton',
  homeScore: 2, awayScore: 1, halfTimeHomeScore: 1, halfTimeAwayScore: 0,
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
  filters: { competitions: ['E0', 'D1'], seasons: ['2324', '2425'] },
  items: Array.from({ length: 20 }, (_, index) => index === 0 ? match : {
    ...match, id: `match-${index}`, homeTeam: `主队 ${index}`, awayTeam: `客队 ${index}`,
  }),
}

beforeEach(() => {
  vi.resetAllMocks()
  window.history.replaceState(null, '', '/')
  vi.mocked(fetchDataSummary).mockResolvedValue(summary)
  vi.mocked(fetchMatchPage).mockResolvedValue(page)
})
afterEach(() => { cleanup(); vi.useRealTimers() })

describe('历史比赛页面', () => {
  it('does not clear a committed query while IME composition is active', async () => {
    window.history.replaceState(null, '', '/?team=Arsenal')
    render(<HistoryPage />)
    await screen.findByText('Arsenal 2–1 Everton')
    vi.useFakeTimers()
    const input = screen.getByLabelText('球队')
    fireEvent.compositionStart(input)
    fireEvent.change(input, { target: { value: '' } })
    await act(async () => { vi.advanceTimersByTime(500) })
    expect(fetchMatchPage).toHaveBeenCalledTimes(1)
    fireEvent.compositionEnd(input)
    await act(async () => { vi.advanceTimersByTime(300) })
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
    await screen.findByText('Arsenal 2–1 Everton')
    expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    await screen.findByText('第 21–40 场，共 380 场')
    fireEvent.change(screen.getByLabelText('联赛'), { target: { value: 'E0' } })
    await waitFor(() => expect(fetchMatchPage).toHaveBeenLastCalledWith(expect.objectContaining({ competition: 'E0', page: 1 }), expect.any(AbortSignal)))
    fireEvent.change(screen.getByLabelText('赛季'), { target: { value: '2324' } })
    await waitFor(() => expect(fetchMatchPage).toHaveBeenLastCalledWith(expect.objectContaining({ competition: 'E0', season: '2324', page: 1 }), expect.any(AbortSignal)))
    fireEvent.click(screen.getByRole('button', { name: '清除筛选' }))
    await waitFor(() => expect(fetchMatchPage).toHaveBeenLastCalledWith(expect.objectContaining({ competition: '', season: '', team: '', page: 1 }), expect.any(AbortSignal)))
    vi.mocked(fetchMatchPage).mockResolvedValue({ ...page, page: 19, items: [match] })
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled())
  })

  it('debounces team search for 300ms, respects IME composition, and clears immediately with focus restored', async () => {
    render(<HistoryPage />)
    await screen.findByText('Arsenal 2–1 Everton')
    vi.useFakeTimers()
    const input = screen.getByLabelText('球队')
    fireEvent.compositionStart(input)
    fireEvent.change(input, { target: { value: 'Arsenal' } })
    await act(async () => { vi.advanceTimersByTime(500) })
    expect(fetchMatchPage).toHaveBeenCalledTimes(1)
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true })
    expect(fetchMatchPage).toHaveBeenCalledTimes(1)
    fireEvent.compositionEnd(input)
    await act(async () => { vi.advanceTimersByTime(299) })
    expect(fetchMatchPage).toHaveBeenCalledTimes(1)
    await act(async () => { vi.advanceTimersByTime(1) })
    expect(fetchMatchPage).toHaveBeenLastCalledWith(expect.objectContaining({ team: 'Arsenal', page: 1 }), expect.any(AbortSignal))
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '清除球队搜索' })) })
    expect(fetchMatchPage).toHaveBeenLastCalledWith(expect.objectContaining({ team: '', page: 1 }), expect.any(AbortSignal))
    expect(input).toHaveValue('')
    expect(input).toHaveFocus()
  })

  it('submits Enter immediately and cancels older requests even if they later resolve', async () => {
    let resolveOld!: (value: MatchPage) => void
    vi.mocked(fetchMatchPage).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve }))
    const { unmount } = render(<HistoryPage />)
    const oldSignal = vi.mocked(fetchMatchPage).mock.calls[0][1]
    const input = screen.getByLabelText('球队')
    fireEvent.change(input, { target: { value: 'Arsenal' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await screen.findByText('Arsenal 2–1 Everton')
    expect(oldSignal.aborted).toBe(true)
    await act(async () => { resolveOld({ ...page, items: [{ ...match, homeTeam: '过期队名' }] }) })
    expect(screen.queryByText(/过期队名/)).not.toBeInTheDocument()
    const latestSignal = vi.mocked(fetchMatchPage).mock.calls.at(-1)![1]
    unmount()
    expect(latestSignal.aborted).toBe(true)
  })

  it('opens only one match and includes provenance and kickoff-bound warnings', async () => {
    render(<HistoryPage />)
    await screen.findByText('Arsenal 2–1 Everton')
    const buttons = screen.getAllByRole('button', { name: /展开市场/ })
    fireEvent.click(buttons[0])
    expect(buttons[0]).toHaveAttribute('aria-expanded', 'true')
    const details = screen.getByRole('region', { name: 'Arsenal 对 Everton 的市场详情' })
    expect(within(details).getByText('亚洲让球')).toBeInTheDocument()
    expect(within(details).getByText('1.50')).toBeInTheDocument()
    expect(within(details).getByText('大小球')).toBeInTheDocument()
    for (const text of ['来源', '提供方', '阶段', '采集时间（记录值）', '可用时间', '时间精度']) {
      expect(within(details).getAllByText(text).length).toBeGreaterThan(0)
    }
    expect(within(details).getAllByText(/仅能确认开球时可用，不能用于开球前回测/).length).toBeGreaterThan(0)
    expect(within(details).getAllByText('football_data').length).toBeGreaterThan(0)
    fireEvent.click(buttons[1])
    expect(buttons[0]).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('region', { name: 'Arsenal 对 Everton 的市场详情' })).not.toBeInTheDocument()
    fireEvent.click(buttons[1])
    expect(buttons[1]).toHaveAttribute('aria-expanded', 'false')
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
    expect(await screen.findByText('没有符合条件的比赛')).toBeInTheDocument()
    expect(screen.queryByText(/Arsenal/)).not.toBeInTheDocument()
  })

  it('recovers from a list error while preserving the summary and filters', async () => {
    vi.mocked(fetchMatchPage).mockRejectedValueOnce(new Error('private server path'))
    render(<HistoryPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('比赛加载失败')
    expect(screen.queryByText(/private server path/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重新加载比赛' }))
    expect(await screen.findByText('Arsenal 2–1 Everton')).toBeInTheDocument()
  })

  it('keeps matches usable when the summary fails and retries only the summary', async () => {
    vi.mocked(fetchDataSummary).mockRejectedValueOnce(new Error('offline'))
    render(<HistoryPage />)
    expect(await screen.findByText('Arsenal 2–1 Everton')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('摘要加载失败')
    fireEvent.click(screen.getByRole('button', { name: '重新加载摘要' }))
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(fetchMatchPage).toHaveBeenCalledTimes(1)
  })

  it('restores URL filters on load and browser history navigation', async () => {
    window.history.replaceState(null, '', '/?competition=E0&season=2324&team=Arsenal&page=3#历史比赛')
    vi.mocked(fetchMatchPage).mockImplementation(async (filters) => ({ ...page, page: filters.page ?? 1 }))
    render(<HistoryPage />)
    await screen.findByText('第 41–60 场，共 380 场')
    expect(screen.getByLabelText('球队')).toHaveValue('Arsenal')
    act(() => {
      window.history.replaceState(null, '', '/?competition=D1&page=2#历史比赛')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    await screen.findByText('第 21–40 场，共 380 场')
    expect(screen.getByLabelText('联赛')).toHaveValue('D1')
    expect(screen.getByLabelText('球队')).toHaveValue('')
  })

  it('renders real match scores, half-time scores, odds and the server page range', async () => {
    render(<HistoryPage />)
    const table = await screen.findByRole('table', { name: '历史比赛列表' })
    expect(within(table).getByText('Arsenal 2–1 Everton')).toBeInTheDocument()
    expect(within(table).getAllByText('1–0')[0]).toBeInTheDocument()
    expect(within(table).getAllByText('1.22')[0]).toBeInTheDocument()
    expect(within(table).getAllByText('6.80')[0]).toBeInTheDocument()
    expect(within(table).getAllByText('12.50')[0]).toBeInTheDocument()
    expect(screen.getByText('第 1–20 场，共 380 场')).toBeInTheDocument()
  })
})
