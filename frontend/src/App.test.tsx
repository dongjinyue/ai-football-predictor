import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { fetchMatchMarketHistory } from './features/history/api'

vi.mock('./features/history/api', () => ({
  fetchDataSummary: vi.fn(() => new Promise(() => {})),
  fetchMatchPage: vi.fn(() => new Promise(() => {})),
  fetchDataAudit: vi.fn(() => new Promise(() => {})),
  fetchMatchMarketHistory: vi.fn(() => new Promise(() => {})),
}))

afterEach(() => {
  cleanup()
  window.history.replaceState(null, '', '/')
})

describe('Dashboard shell', () => {
  it('renders the standalone match detail route and keeps history navigation active', async () => {
    vi.mocked(fetchMatchMarketHistory).mockResolvedValue({
      id: 'sporttery:70001', competitionCode: 'JC25', competitionName: '英超', season: '2015',
      kickoffAt: '2015-01-02T12:00:00Z', kickoffTimePrecision: 'date_only',
      homeTeam: '主队', awayTeam: '客队', halfTimeHomeScore: 0, halfTimeAwayScore: 0,
      homeScore: 1, awayScore: 0, markets: [],
    })
    window.history.replaceState(null, '', '/#history/match/sporttery%3A70001?return=%23history%3Fseason%3D2015')

    render(<App />)

    expect(await screen.findByRole('heading', { name: '主队 1–0 客队' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '历史比赛' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: '返回历史比赛' })).toHaveAttribute('href', '#history?season=2015')
  })
  it('opens the historical match route and returns to today', async () => {
    render(<App />)
    const historyLink = screen.getByRole('link', { name: '历史比赛' })
    expect(historyLink).toHaveAttribute('href', '#history')
    fireEvent.click(historyLink)
    expect(await screen.findByRole('heading', { name: '历史比赛' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '历史比赛' })).toHaveAttribute('aria-current', 'page')
    act(() => {
      window.location.hash = '#today'
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(screen.getByRole('heading', { name: '今日赛事分析' })).toBeInTheDocument()
  })

  it('normalizes the legacy Chinese history hash without dropping query parameters', async () => {
    window.history.replaceState(null, '', '/?page=500#%E5%8E%86%E5%8F%B2%E6%AF%94%E8%B5%9B')

    render(<App />)

    expect(await screen.findByRole('heading', { name: '历史比赛' })).toBeInTheDocument()
    expect(window.location.hash).toBe('#history?page=500')
    expect(window.location.search).toBe('')
  })

  it('opens the data quality route and marks it as the active page', async () => {
    window.history.replaceState(null, '', '/#quality')

    render(<App />)

    expect(await screen.findByRole('heading', { name: '正在审计历史数据' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '数据质量' })).toHaveAttribute('aria-current', 'page')
    expect(document.title).toBe('数据质量 · 赛前分析台')
  })

  it('shows the core analysis areas and makes unavailable predictions explicit', () => {
    render(<App />)

    expect(
      screen.getByRole('heading', { name: '今日赛事分析' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('navigation')).toHaveTextContent('今日赛事')
    expect(screen.getByRole('navigation')).toHaveTextContent('历史回测')
    expect(screen.getByRole('navigation')).toHaveTextContent('数据质量')
    expect(screen.getByRole('navigation')).toHaveTextContent('模型管理')
    expect(screen.getByText('预测模型尚未接入')).toBeInTheDocument()
    expect(screen.getByText(/仅供分析与研究/)).toBeInTheDocument()
    expect(screen.queryByText('AI Football Predictor')).not.toBeInTheDocument()
    expect(screen.queryByText('Foundation status')).not.toBeInTheDocument()
    expect(screen.queryByText('Next module')).not.toBeInTheDocument()
  })

  it('keeps the initial HTML title in Chinese before the app mounts', () => {
    const shell = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8')

    expect(shell).toContain('<title>今日赛事分析 — 赛前分析台</title>')
  })
})
