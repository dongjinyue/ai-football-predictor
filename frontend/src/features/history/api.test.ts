import { afterEach, describe, expect, it, vi } from 'vitest'

import { DataRequestError, fetchDataSummary, fetchMatchPage } from './api'

describe('历史数据 API 客户端', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('按筛选条件构造 URL 并传递取消信号', async () => {
    const response = {
      ok: true,
      json: vi.fn().mockResolvedValue({
        page: 2,
        page_size: 20,
        total_items: 0,
        total_pages: 0,
        filters: { competitions: [], seasons: [] },
        items: [],
      }),
    }
    const fetchMock = vi.fn().mockResolvedValue(response)
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await fetchMatchPage(
      { page: 2, pageSize: 20, competition: 'E0', season: '2324', team: 'Man Utd' },
      controller.signal,
    )

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(
        'page=2&page_size=20&competition=E0&season=2324&team=Man+Utd',
      ),
      { signal: controller.signal },
    )
  })

  it('跳过空筛选条件并将后端比赛字段格式化为前端字段', async () => {
    const response = {
      ok: true,
      json: vi.fn().mockResolvedValue({
        page: 1,
        page_size: 20,
        total_items: 1,
        total_pages: 1,
        filters: { competitions: ['E0'], seasons: ['2324'] },
        items: [
          {
            id: 'match-1',
            competition_code: 'E0',
            competition_name: 'Premier League',
            season: '2324',
            kickoff_at: '2023-08-11T20:00:00Z',
            home_team: 'Arsenal',
            away_team: 'Everton',
            half_time_home_score: 1,
            half_time_away_score: 0,
            home_score: 2,
            away_score: 1,
            markets: [
              {
                market_type: '1X2',
                stage: 'closing',
                time_precision: 'kickoff_bound',
                source: 'football_data',
                provider: 'bet365',
                captured_at: '2023-08-11T20:00:00Z',
                available_at: '2023-08-11T20:00:00Z',
                line: null,
                outcomes: [{ outcome_code: 'H', odds: 1.5 }],
              },
            ],
          },
        ],
      }),
    }
    const fetchMock = vi.fn().mockResolvedValue(response)
    vi.stubGlobal('fetch', fetchMock)

    const page = await fetchMatchPage(
      { page: 1, pageSize: 20, competition: '', season: '  ', team: undefined },
      new AbortController().signal,
    )

    expect(fetchMock.mock.calls[0][0]).toBe(
      'http://127.0.0.1:8000/api/data/matches?page=1&page_size=20',
    )
    expect(page.items[0]).toMatchObject({
      competitionCode: 'E0',
      kickoffAt: '2023-08-11T20:00:00Z',
      homeTeam: 'Arsenal',
      halfTimeHomeScore: 1,
    })
    expect(page.items[0].markets[0]).toEqual({
      marketType: '1X2',
      stage: 'closing',
      timePrecision: 'kickoff_bound',
      source: 'football_data',
      provider: 'bet365',
      capturedAt: '2023-08-11T20:00:00Z',
      availableAt: '2023-08-11T20:00:00Z',
      line: null,
      outcomes: [{ outcomeCode: 'H', odds: 1.5 }],
    })
  })

  it('对非 2xx 响应抛出统一的 DataRequestError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 503, json: vi.fn() }),
    )

    await expect(fetchDataSummary(new AbortController().signal)).rejects.toBeInstanceOf(
      DataRequestError,
    )
  })

  it('格式化数据摘要中的计数和时间字段', async () => {
    const response = {
      ok: true,
      json: vi.fn().mockResolvedValue({
        competitions: 5,
        teams: 100,
        matches: 380,
        market_snapshots: 760,
        market_outcomes: 2280,
        latest_kickoff_at: '2024-05-19T15:00:00Z',
        latest_successful_import_at: null,
      }),
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))

    await expect(fetchDataSummary(new AbortController().signal)).resolves.toEqual({
      competitions: 5,
      teams: 100,
      matches: 380,
      marketSnapshots: 760,
      marketOutcomes: 2280,
      latestKickoffAt: '2024-05-19T15:00:00Z',
      latestSuccessfulImportAt: null,
    })
  })
})
