import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  DataRequestError,
  fetchDataAudit,
  fetchDataSummary,
  fetchImportCatalog,
  fetchImportJob,
  fetchMatchPage,
  submitImportJob,
} from './api'

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
            kickoff_time_precision: 'date_only',
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
      kickoffTimePrecision: 'date_only',
      homeTeam: 'Arsenal',
      halfTimeHomeScore: 1,
      halfTimeResult: 'home',
      fullTimeResult: 'home',
      totalGoals: 3,
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

  it('读取训练前数据审计并保留联赛赛季与盘口时间统计', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        start_year: 2000,
        end_year: 2020,
        requested_files: 1,
        summary: {
          catalog_competitions: 1,
          imported_competitions: 1,
          requested_files: 1,
          files_with_matches: 1,
          missing_files: 0,
          total_matches: 380,
          complete_full_time_matches: 380,
          complete_half_time_matches: 379,
          missing_half_time_matches: 1,
          half_time_result_matches: 379,
          total_goals_matches: 380,
          label_ready_matches: 380,
          pre_match_market_matches: 120,
          kickoff_bound_market_matches: 260,
          post_kickoff_market_matches: 380,
        },
        scopes: [{
          competition_code: 'E0',
          competition_name: 'English Premier League',
          country_code: 'ENG',
          season: '1920',
          match_count: 380,
          complete_full_time_matches: 380,
          complete_half_time_matches: 379,
          missing_half_time_matches: 1,
          half_time_result_matches: 379,
          total_goals_matches: 380,
          label_ready_matches: 380,
          pre_match_market_matches: 120,
          kickoff_bound_market_matches: 260,
          post_kickoff_market_matches: 380,
          markets: [{
            market_type: 'match_result',
            snapshot_count: 380,
            match_count: 380,
            pre_match_snapshot_count: 120,
            pre_match_match_count: 120,
            kickoff_bound_snapshot_count: 260,
            kickoff_bound_match_count: 260,
            post_kickoff_snapshot_count: 380,
          }],
        }],
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchDataAudit(
      { startYear: 2000, endYear: 2020, competitionCodes: ['E0'] },
      new AbortController().signal,
    )).resolves.toMatchObject({
      startYear: 2000,
      endYear: 2020,
      summary: expect.objectContaining({ labelReadyMatches: 380, preMatchMarketMatches: 120 }),
      scopes: [expect.objectContaining({ competitionCode: 'E0', season: '1920' })],
    })
    expect(fetchMock.mock.calls[0][0]).toBe(
      'http://127.0.0.1:8000/api/data/audit?start_year=2000&end_year=2020&competition_codes=E0',
    )
  })

  it('读取导入目录并提交后台导入任务', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({
          competitions: [{ code: 'E0', name: 'English Premier League', country_code: 'ENG', season_style: 'split_year' }],
          start_year: 2000,
          end_year: 2020,
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({
          job_id: 'job-1', run_id: null, status: 'queued', requested_files: 456,
          completed_files: 0, failed_files: 0, imported_matches: 0, skipped_rows: 0,
          errors: [], current_competition_code: null, current_season: null,
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn().mockResolvedValue({
          job_id: 'job-1', run_id: 'run-1', status: 'completed', requested_files: 456,
          completed_files: 456, failed_files: 0, imported_matches: 1000, skipped_rows: 0,
          errors: [], current_competition_code: 'E0', current_season: '1920',
        }),
      })
    vi.stubGlobal('fetch', fetchMock)
    const signal = new AbortController().signal

    await expect(fetchImportCatalog(signal)).resolves.toEqual({
      competitions: [{ code: 'E0', name: 'English Premier League', countryCode: 'ENG', seasonStyle: 'split_year' }],
      startYear: 2000,
      endYear: 2020,
    })
    await expect(submitImportJob({ competitionCodes: [], startYear: 2000, endYear: 2020 }, signal)).resolves.toMatchObject({
      jobId: 'job-1', requestedFiles: 456, status: 'queued',
    })
    await expect(fetchImportJob('job-1', signal)).resolves.toMatchObject({
      jobId: 'job-1', runId: 'run-1', status: 'completed', completedFiles: 456,
    })
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ start_year: 2000, end_year: 2020, competition_codes: [] }),
    })
  })
})
