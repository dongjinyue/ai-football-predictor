import { API_BASE_URL } from '../../config'

import type {
  DataSummary,
  HistoricalMatch,
  MatchFilters,
  MatchMarket,
  MatchPage,
  MarketOutcome,
} from './types'

/** 对外统一表示 HTTP（超文本传输协议）请求失败，便于页面统一反馈。 */
export class DataRequestError extends Error {
  readonly status: number

  constructor(status: number) {
    super(`数据请求失败（HTTP ${status}）`)
    this.name = 'DataRequestError'
    this.status = status
  }
}

interface MatchPageResponse {
  page: number
  page_size: number
  total_items: number
  total_pages: number
  filters: {
    competitions: string[]
    seasons: string[]
  }
  items: MatchResponse[]
}

interface MatchResponse {
  id: string
  competition_code: string
  competition_name: string
  season: string
  kickoff_at: string
  home_team: string
  away_team: string
  half_time_home_score: number | null
  half_time_away_score: number | null
  home_score: number | null
  away_score: number | null
  markets: MarketResponse[]
}

interface MarketResponse {
  market_type: string
  stage: string
  time_precision: string
  source: string
  provider: string
  captured_at: string
  available_at: string
  line: number | null
  outcomes: OutcomeResponse[]
}

interface OutcomeResponse {
  outcome_code: string
  odds: number
}

interface DataSummaryResponse {
  competitions: number
  teams: number
  matches: number
  market_snapshots: number
  market_outcomes: number
  latest_kickoff_at: string | null
  latest_successful_import_at: string | null
}

function appendTextFilter(
  params: URLSearchParams,
  key: string,
  value: string | undefined,
): void {
  // 空白筛选没有语义；非空值保留原文，让服务端负责规范化匹配。
  if (value?.trim()) {
    params.set(key, value)
  }
}

function buildMatchUrl(filters: MatchFilters): string {
  const url = new URL('/api/data/matches', API_BASE_URL)
  const params = url.searchParams

  if (filters.page !== undefined) {
    params.set('page', String(filters.page))
  }
  if (filters.pageSize !== undefined) {
    params.set('page_size', String(filters.pageSize))
  }
  appendTextFilter(params, 'competition', filters.competition)
  appendTextFilter(params, 'season', filters.season)
  appendTextFilter(params, 'team', filters.team)

  return url.toString()
}

async function requestJson<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal })

  if (!response.ok) {
    throw new DataRequestError(response.status)
  }

  return (await response.json()) as T
}

function formatOutcome(outcome: OutcomeResponse): MarketOutcome {
  return {
    outcomeCode: outcome.outcome_code,
    odds: outcome.odds,
  }
}

function formatMarket(market: MarketResponse): MatchMarket {
  return {
    marketType: market.market_type,
    stage: market.stage,
    timePrecision: market.time_precision,
    source: market.source,
    provider: market.provider,
    capturedAt: market.captured_at,
    availableAt: market.available_at,
    line: market.line,
    outcomes: market.outcomes.map(formatOutcome),
  }
}

function formatMatch(match: MatchResponse): HistoricalMatch {
  return {
    id: match.id,
    competitionCode: match.competition_code,
    competitionName: match.competition_name,
    season: match.season,
    kickoffAt: match.kickoff_at,
    homeTeam: match.home_team,
    awayTeam: match.away_team,
    halfTimeHomeScore: match.half_time_home_score,
    halfTimeAwayScore: match.half_time_away_score,
    homeScore: match.home_score,
    awayScore: match.away_score,
    markets: match.markets.map(formatMarket),
  }
}

function formatMatchPage(page: MatchPageResponse): MatchPage {
  return {
    page: page.page,
    pageSize: page.page_size,
    totalItems: page.total_items,
    totalPages: page.total_pages,
    filters: {
      competitions: page.filters.competitions,
      seasons: page.filters.seasons,
    },
    items: page.items.map(formatMatch),
  }
}

function formatDataSummary(summary: DataSummaryResponse): DataSummary {
  return {
    competitions: summary.competitions,
    teams: summary.teams,
    matches: summary.matches,
    marketSnapshots: summary.market_snapshots,
    marketOutcomes: summary.market_outcomes,
    latestKickoffAt: summary.latest_kickoff_at,
    latestSuccessfulImportAt: summary.latest_successful_import_at,
  }
}

/** 请求一页历史比赛，并将后端响应格式化为前端命名。 */
export async function fetchMatchPage(
  filters: MatchFilters,
  signal: AbortSignal,
): Promise<MatchPage> {
  const response = await requestJson<MatchPageResponse>(buildMatchUrl(filters), signal)
  return formatMatchPage(response)
}

/** 请求当前数据库摘要，并将后端响应格式化为前端命名。 */
export async function fetchDataSummary(signal: AbortSignal): Promise<DataSummary> {
  const url = new URL('/api/data/summary', API_BASE_URL).toString()
  const response = await requestJson<DataSummaryResponse>(url, signal)
  return formatDataSummary(response)
}
