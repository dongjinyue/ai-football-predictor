import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { MarketHistoryGroup } from './types'
import MarketHistorySection from './MarketHistorySection'
import OddsTimelineTable from './OddsTimelineTable'

afterEach(cleanup)

function market(overrides: Partial<MarketHistoryGroup> = {}): MarketHistoryGroup {
  return {
    marketType: 'match_result',
    line: null,
    source: 'sporttery',
    provider: 'china_sports_lottery',
    stage: 'closing',
    timePrecision: 'exact',
    outcomeCodes: ['home', 'draw', 'away'],
    snapshots: [
      {
        capturedAt: '2015-01-01T00:00:00Z',
        availableAt: '2015-01-01T00:00:00Z',
        outcomes: [
          { outcomeCode: 'home', odds: 2.1 },
          { outcomeCode: 'draw', odds: 3.1 },
          { outcomeCode: 'away', odds: 3.4 },
        ],
      },
      {
        capturedAt: '2015-01-01T02:00:00Z',
        availableAt: '2015-01-01T02:00:00Z',
        outcomes: [
          { outcomeCode: 'home', odds: 2 },
          { outcomeCode: 'draw', odds: 3.2 },
          { outcomeCode: 'away', odds: 3.4 },
        ],
      },
    ],
    ...overrides,
  }
}

describe('赔率时间线表格', () => {
  it('按固定列顺序显示赔率并标记相邻快照涨跌', () => {
    render(<OddsTimelineTable market={market()} />)

    expect(screen.getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
      '发布时间', '胜', '平', '负',
    ])
    expect(screen.getByLabelText('胜赔率从 2.10 降至 2.00')).toBeInTheDocument()
    expect(screen.getByLabelText('平赔率从 3.10 升至 3.20')).toBeInTheDocument()
    expect(screen.queryByLabelText(/负赔率从/)).not.toBeInTheDocument()
  })

  it('缺失结果显示破折号且不跨缺失快照制造涨跌', () => {
    const fixture = market({
      snapshots: [
        { capturedAt: '2015-01-01T00:00:00Z', availableAt: '2015-01-01T00:00:00Z', outcomes: [] },
        { capturedAt: '2015-01-01T02:00:00Z', availableAt: '2015-01-01T02:00:00Z', outcomes: [{ outcomeCode: 'home', odds: 2 }] },
      ],
    })

    render(<OddsTimelineTable market={fixture} />)

    expect(screen.getAllByText('—')).toHaveLength(5)
    expect(screen.queryByLabelText(/赔率从/)).not.toBeInTheDocument()
  })

  it('按后端业务顺序显示总进球和半全场中文列名', () => {
    const { rerender } = render(<OddsTimelineTable market={market({
      marketType: 'total_goals',
      outcomeCodes: ['0', '1', '2', '3', '4', '5', '6', '7_plus'],
      snapshots: [],
    })} />)
    expect(screen.getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
      '发布时间', '0', '1', '2', '3', '4', '5', '6', '7+',
    ])

    rerender(<OddsTimelineTable market={market({
      marketType: 'half_full',
      outcomeCodes: ['home_home', 'home_draw', 'home_away', 'draw_home', 'draw_draw', 'draw_away', 'away_home', 'away_draw', 'away_away'],
      snapshots: [],
    })} />)
    expect(screen.getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
      '发布时间', '胜胜', '胜平', '胜负', '平胜', '平平', '平负', '负胜', '负平', '负负',
    ])
  })

  it('只有让球市场时仍显示盘口和来源信息', () => {
    render(<MarketHistorySection market={market({ marketType: 'handicap_result', line: -1 })} />)

    expect(screen.getByRole('heading', { name: '让球胜平负固定奖金' })).toBeInTheDocument()
    expect(screen.getByText('让球 -1')).toBeInTheDocument()
    const region = screen.getByRole('region', { name: '让球胜平负固定奖金赔率时间线' })
    expect(within(region).getByRole('table')).toBeInTheDocument()
    expect(screen.getAllByText('中国体育彩票')).toHaveLength(2)
  })
})
