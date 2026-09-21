import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DataRequestError, fetchMatchMarketHistory } from './api'
import MatchMarketHistoryPage from './MatchMarketHistoryPage'
import type { MatchMarketHistory } from './types'

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return { ...actual, fetchMatchMarketHistory: vi.fn() }
})

const detail: MatchMarketHistory = {
  id: 'sporttery:70001',
  competitionCode: 'JC25',
  competitionName: '英超',
  season: '2015',
  kickoffAt: '2015-01-02T12:00:00Z',
  kickoffTimePrecision: 'date_only',
  homeTeam: '主队',
  awayTeam: '客队',
  halfTimeHomeScore: 0,
  halfTimeAwayScore: 0,
  homeScore: 1,
  awayScore: 0,
  markets: [{
    marketType: 'handicap_result',
    line: -1,
    source: 'sporttery',
    provider: 'china_sports_lottery',
    stage: 'closing',
    timePrecision: 'exact',
    outcomeCodes: ['home', 'draw', 'away'],
    snapshots: [{
      capturedAt: '2015-01-01T00:00:00Z',
      availableAt: '2015-01-01T00:00:00Z',
      outcomes: [{ outcomeCode: 'home', odds: 3.8 }],
    }],
  }],
}

beforeEach(() => vi.resetAllMocks())
afterEach(cleanup)

describe('比赛市场详情页', () => {
  it('成功显示比赛摘要、仅有的让球市场和精确返回地址', async () => {
    vi.mocked(fetchMatchMarketHistory).mockResolvedValue(detail)
    render(<MatchMarketHistoryPage matchId={detail.id} returnHash="#history?season=2015&page=12" />)

    expect(await screen.findByRole('heading', { name: '主队 1–0 客队' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '让球胜平负固定奖金' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回历史比赛' })).toHaveAttribute(
      'href', '#history?season=2015&page=12',
    )
  })

  it('加载期间显示稳定状态区', () => {
    vi.mocked(fetchMatchMarketHistory).mockReturnValue(new Promise(() => {}))
    render(<MatchMarketHistoryPage matchId={detail.id} returnHash="#history" />)
    expect(screen.getByRole('status')).toHaveTextContent('正在加载市场记录')
  })

  it('没有赔率时仍显示比赛信息与明确说明', async () => {
    vi.mocked(fetchMatchMarketHistory).mockResolvedValue({ ...detail, markets: [] })
    render(<MatchMarketHistoryPage matchId={detail.id} returnHash="#history" />)
    expect(await screen.findByText('该场比赛没有已采集的赔率记录')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '主队 1–0 客队' })).toBeInTheDocument()
  })

  it('把 404 区分为比赛不存在', async () => {
    vi.mocked(fetchMatchMarketHistory).mockRejectedValue(new DataRequestError(404))
    render(<MatchMarketHistoryPage matchId="missing" returnHash="#history" />)
    expect(await screen.findByText('比赛不存在或已被移除')).toBeInTheDocument()
  })

  it('普通失败后可以重新加载', async () => {
    vi.mocked(fetchMatchMarketHistory)
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce(detail)
    render(<MatchMarketHistoryPage matchId={detail.id} returnHash="#history" />)
    fireEvent.click(await screen.findByRole('button', { name: '重新加载' }))
    expect(await screen.findByRole('heading', { name: '让球胜平负固定奖金' })).toBeInTheDocument()
  })

  it('卸载页面时取消仍在进行的请求', () => {
    vi.mocked(fetchMatchMarketHistory).mockReturnValue(new Promise(() => {}))
    const { unmount } = render(<MatchMarketHistoryPage matchId={detail.id} returnHash="#history" />)
    const signal = vi.mocked(fetchMatchMarketHistory).mock.calls[0][1]
    unmount()
    expect(signal?.aborted).toBe(true)
  })
})
