import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchDataAudit } from '../history/api'
import type { DataAuditReport } from '../history/types'
import DataQualityPage from './DataQualityPage'

vi.mock('../history/api', () => ({
  fetchDataAudit: vi.fn(),
}))

const report: DataAuditReport = {
  startYear: 2000,
  endYear: 2020,
  requestedFiles: 3,
  summary: {
    catalogCompetitions: 2,
    importedCompetitions: 1,
    requestedFiles: 3,
    filesWithMatches: 2,
    missingFiles: 1,
    totalMatches: 760,
    completeFullTimeMatches: 760,
    completeHalfTimeMatches: 740,
    missingHalfTimeMatches: 20,
    halfTimeResultMatches: 740,
    totalGoalsMatches: 760,
    labelReadyMatches: 760,
    preMatchMarketMatches: 0,
    kickoffBoundMarketMatches: 500,
    postKickoffMarketMatches: 760,
  },
  scopes: [
    {
      competitionCode: 'E0',
      competitionName: 'English Premier League',
      countryCode: 'ENG',
      season: '1920',
      matchCount: 380,
      completeFullTimeMatches: 380,
      completeHalfTimeMatches: 370,
      missingHalfTimeMatches: 10,
      halfTimeResultMatches: 370,
      totalGoalsMatches: 380,
      labelReadyMatches: 380,
      preMatchMarketMatches: 0,
      kickoffBoundMarketMatches: 250,
      postKickoffMarketMatches: 380,
      markets: [],
    },
    {
      competitionCode: 'D1',
      competitionName: 'German Bundesliga',
      countryCode: 'DEU',
      season: '1920',
      matchCount: 0,
      completeFullTimeMatches: 0,
      completeHalfTimeMatches: 0,
      missingHalfTimeMatches: 0,
      halfTimeResultMatches: 0,
      totalGoalsMatches: 0,
      labelReadyMatches: 0,
      preMatchMarketMatches: 0,
      kickoffBoundMarketMatches: 0,
      postKickoffMarketMatches: 0,
      markets: [],
    },
  ],
}

describe('数据质量页面', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(fetchDataAudit).mockResolvedValue(report)
  })
  afterEach(() => cleanup())

  it('显示审计结论、缺失文件和盘口时间边界', async () => {
    render(<DataQualityPage />)

    expect(await screen.findByText('训练前数据审计')).toBeInTheDocument()
    expect(screen.getByText('缺失源文件')).toBeInTheDocument()
    expect(screen.getByText('赛前可用盘口')).toBeInTheDocument()
    expect(screen.getByText(/开球时边界的数据不能用于赛前回测/)).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /英超.*E0.*1920/ })).toHaveTextContent(/英超\s*（E0）/)
    expect(screen.getByRole('row', { name: /德甲.*1920/ })).toHaveTextContent('未导入')
  })

  it('支持展开联赛赛季明细并在请求失败时提供重试', async () => {
    vi.mocked(fetchDataAudit).mockRejectedValueOnce(new Error('offline'))
    render(<DataQualityPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('审计加载失败')
    fireEvent.click(screen.getByRole('button', { name: '重新加载审计' }))
    await screen.findByText('训练前数据审计')
    fireEvent.click(screen.getByRole('button', { name: '查看 E0 1920 明细' }))
    const details = screen.getByRole('region', { name: 'E0 1920 数据明细' })
    expect(within(details).getByText('370 / 380')).toBeInTheDocument()
  })
})
