import { API_BASE_URL } from '../../config'

import type {
  DataAuditReport,
  DataSummary,
  HistoricalMatch,
  ImportCatalog,
  ImportJob,
  MatchFilters,
  MatchMarketHistory,
  MarketHistoryGroup,
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
    competitions: Array<{ code: string; name: string }>
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
  kickoff_time_precision?: 'exact' | 'date_only'
  home_team: string
  away_team: string
  half_time_home_score: number | null
  half_time_away_score: number | null
  half_time_result?: 'home' | 'draw' | 'away' | null
  home_score: number | null
  away_score: number | null
  full_time_result?: 'home' | 'draw' | 'away' | null
  total_goals?: number | null
  markets: MarketResponse[]
}

interface ImportCatalogResponse {
  competitions: Array<{
    code: string
    name: string
    country_code: string
    season_style: 'split_year' | 'calendar_year'
  }>
  start_year: number
  end_year: number
}

interface ImportJobResponse {
  job_id: string
  run_id: string | null
  status: ImportJob['status']
  requested_files: number
  completed_files: number
  failed_files: number
  imported_matches: number
  skipped_rows: number
  errors: string[]
  current_competition_code: string | null
  current_season: string | null
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

interface MarketHistorySnapshotResponse {
  captured_at: string
  available_at: string
  outcomes: OutcomeResponse[]
}

interface MarketHistoryGroupResponse {
  market_type: string
  line: number | null
  source: string
  provider: string
  stage: string
  time_precision: string
  outcome_codes: string[]
  snapshots: MarketHistorySnapshotResponse[]
}

interface MatchMarketHistoryResponse {
  id: string
  competition_code: string
  competition_name: string
  season: string
  kickoff_at: string
  kickoff_time_precision: 'exact' | 'date_only'
  home_team: string
  away_team: string
  half_time_home_score: number | null
  half_time_away_score: number | null
  home_score: number | null
  away_score: number | null
  markets: MarketHistoryGroupResponse[]
}

interface DataAuditResponse {
  start_year: number
  end_year: number
  requested_files: number
  summary: {
    catalog_competitions: number
    imported_competitions: number
    requested_files: number
    files_with_matches: number
    missing_files: number
    total_matches: number
    complete_full_time_matches: number
    complete_half_time_matches: number
    missing_half_time_matches: number
    half_time_result_matches: number
    total_goals_matches: number
    label_ready_matches: number
    pre_match_market_matches: number
    kickoff_bound_market_matches: number
    post_kickoff_market_matches: number
  }
  scopes: Array<{
    competition_code: string
    competition_name: string
    country_code: string
    season: string
    match_count: number
    complete_full_time_matches: number
    complete_half_time_matches: number
    missing_half_time_matches: number
    half_time_result_matches: number
    total_goals_matches: number
    label_ready_matches: number
    pre_match_market_matches: number
    kickoff_bound_market_matches: number
    post_kickoff_market_matches: number
    markets: Array<{
      market_type: string
      snapshot_count: number
      match_count: number
      pre_match_snapshot_count: number
      pre_match_match_count: number
      kickoff_bound_snapshot_count: number
      kickoff_bound_match_count: number
      post_kickoff_snapshot_count: number
    }>
  }>
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
  params.set('source', 'sporttery')

  if (filters.page !== undefined) {
    params.set('page', String(filters.page))
  }
  if (filters.pageSize !== undefined) {
    params.set('page_size', String(filters.pageSize))
  }
  appendTextFilter(params, 'competition', filters.competition)
  appendTextFilter(params, 'season', filters.season)
  appendTextFilter(params, 'team', filters.team)
  appendTextFilter(params, 'start_date', filters.startDate)
  appendTextFilter(params, 'end_date', filters.endDate)

  return url.toString()
}

async function requestJson<T>(url: string, signal?: AbortSignal, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, { ...init, signal })

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

function formatMarketHistoryGroup(market: MarketHistoryGroupResponse): MarketHistoryGroup {
  return {
    marketType: market.market_type,
    line: market.line,
    source: market.source,
    provider: market.provider,
    stage: market.stage,
    timePrecision: market.time_precision,
    outcomeCodes: market.outcome_codes,
    snapshots: market.snapshots.map((snapshot) => ({
      capturedAt: snapshot.captured_at,
      availableAt: snapshot.available_at,
      outcomes: snapshot.outcomes.map(formatOutcome),
    })),
  }
}

function formatMatchMarketHistory(match: MatchMarketHistoryResponse): MatchMarketHistory {
  return {
    id: match.id,
    competitionCode: match.competition_code,
    competitionName: match.competition_name,
    season: match.season,
    kickoffAt: match.kickoff_at,
    kickoffTimePrecision: match.kickoff_time_precision,
    homeTeam: match.home_team,
    awayTeam: match.away_team,
    halfTimeHomeScore: match.half_time_home_score,
    halfTimeAwayScore: match.half_time_away_score,
    homeScore: match.home_score,
    awayScore: match.away_score,
    markets: match.markets.map(formatMarketHistoryGroup),
  }
}

function resultCode(home: number | null, away: number | null): 'home' | 'draw' | 'away' | null {
  if (home === null || away === null) return null
  if (home > away) return 'home'
  if (home < away) return 'away'
  return 'draw'
}

function formatMatch(match: MatchResponse): HistoricalMatch {
  return {
    id: match.id,
    competitionCode: match.competition_code,
    competitionName: match.competition_name,
    season: match.season,
    kickoffAt: match.kickoff_at,
    kickoffTimePrecision: match.kickoff_time_precision ?? 'exact',
    homeTeam: match.home_team,
    awayTeam: match.away_team,
    halfTimeHomeScore: match.half_time_home_score,
    halfTimeAwayScore: match.half_time_away_score,
    halfTimeResult: match.half_time_result ?? resultCode(match.half_time_home_score, match.half_time_away_score),
    homeScore: match.home_score,
    awayScore: match.away_score,
    fullTimeResult: match.full_time_result ?? resultCode(match.home_score, match.away_score),
    totalGoals: match.total_goals ?? (
      match.home_score !== null && match.away_score !== null
        ? match.home_score + match.away_score
        : null
    ),
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

function formatDataAudit(report: DataAuditResponse): DataAuditReport {
  return {
    startYear: report.start_year,
    endYear: report.end_year,
    requestedFiles: report.requested_files,
    summary: {
      catalogCompetitions: report.summary.catalog_competitions,
      importedCompetitions: report.summary.imported_competitions,
      requestedFiles: report.summary.requested_files,
      filesWithMatches: report.summary.files_with_matches,
      missingFiles: report.summary.missing_files,
      totalMatches: report.summary.total_matches,
      completeFullTimeMatches: report.summary.complete_full_time_matches,
      completeHalfTimeMatches: report.summary.complete_half_time_matches,
      missingHalfTimeMatches: report.summary.missing_half_time_matches,
      halfTimeResultMatches: report.summary.half_time_result_matches,
      totalGoalsMatches: report.summary.total_goals_matches,
      labelReadyMatches: report.summary.label_ready_matches,
      preMatchMarketMatches: report.summary.pre_match_market_matches,
      kickoffBoundMarketMatches: report.summary.kickoff_bound_market_matches,
      postKickoffMarketMatches: report.summary.post_kickoff_market_matches,
    },
    scopes: report.scopes.map((scope) => ({
      competitionCode: scope.competition_code,
      competitionName: scope.competition_name,
      countryCode: scope.country_code,
      season: scope.season,
      matchCount: scope.match_count,
      completeFullTimeMatches: scope.complete_full_time_matches,
      completeHalfTimeMatches: scope.complete_half_time_matches,
      missingHalfTimeMatches: scope.missing_half_time_matches,
      halfTimeResultMatches: scope.half_time_result_matches,
      totalGoalsMatches: scope.total_goals_matches,
      labelReadyMatches: scope.label_ready_matches,
      preMatchMarketMatches: scope.pre_match_market_matches,
      kickoffBoundMarketMatches: scope.kickoff_bound_market_matches,
      postKickoffMarketMatches: scope.post_kickoff_market_matches,
      markets: scope.markets.map((market) => ({
        marketType: market.market_type,
        snapshotCount: market.snapshot_count,
        matchCount: market.match_count,
        preMatchSnapshotCount: market.pre_match_snapshot_count,
        preMatchMatchCount: market.pre_match_match_count,
        kickoffBoundSnapshotCount: market.kickoff_bound_snapshot_count,
        kickoffBoundMatchCount: market.kickoff_bound_match_count,
        postKickoffSnapshotCount: market.post_kickoff_snapshot_count,
      })),
    })),
  }
}

function formatImportCatalog(catalog: ImportCatalogResponse): ImportCatalog {
  return {
    competitions: catalog.competitions.map((competition) => ({
      code: competition.code,
      name: competition.name,
      countryCode: competition.country_code,
      seasonStyle: competition.season_style,
    })),
    startYear: catalog.start_year,
    endYear: catalog.end_year,
  }
}

function formatImportJob(job: ImportJobResponse): ImportJob {
  return {
    jobId: job.job_id,
    runId: job.run_id,
    status: job.status,
    requestedFiles: job.requested_files,
    completedFiles: job.completed_files,
    failedFiles: job.failed_files,
    importedMatches: job.imported_matches,
    skippedRows: job.skipped_rows,
    errors: job.errors,
    currentCompetitionCode: job.current_competition_code,
    currentSeason: job.current_season,
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
  const url = new URL('/api/data/summary?source=sporttery', API_BASE_URL).toString()
  const response = await requestJson<DataSummaryResponse>(url, signal)
  return formatDataSummary(response)
}

/** 按需读取一场竞彩彩票比赛的全部官方赔率快照。 */
export async function fetchMatchMarketHistory(
  matchId: string,
  signal?: AbortSignal,
): Promise<MatchMarketHistory> {
  const url = new URL(
    `/api/data/matches/${encodeURIComponent(matchId)}/market-history`,
    API_BASE_URL,
  ).toString()
  const response = await requestJson<MatchMarketHistoryResponse>(url, signal)
  return formatMatchMarketHistory(response)
}

/** 请求训练前数据审计；默认范围覆盖项目约定的 2000–2020 历史数据。 */
export async function fetchDataAudit(
  query: { startYear: number; endYear: number; competitionCodes?: string[] },
  signal: AbortSignal,
): Promise<DataAuditReport> {
  const url = new URL('/api/data/audit', API_BASE_URL)
  url.searchParams.set('start_year', String(query.startYear))
  url.searchParams.set('end_year', String(query.endYear))
  for (const code of query.competitionCodes ?? []) {
    url.searchParams.append('competition_codes', code)
  }
  const response = await requestJson<DataAuditResponse>(url.toString(), signal)
  return formatDataAudit(response)
}

/** 读取可导入联赛目录与历史年份边界。 */
export async function fetchImportCatalog(signal: AbortSignal): Promise<ImportCatalog> {
  const url = new URL('/api/data/import/catalog', API_BASE_URL).toString()
  const response = await requestJson<ImportCatalogResponse>(url, signal)
  return formatImportCatalog(response)
}

/** 提交后台导入任务，页面随后通过 job_id 轮询进度。 */
export async function submitImportJob(
  payload: { competitionCodes: string[]; startYear: number; endYear: number },
  signal: AbortSignal,
): Promise<ImportJob> {
  const url = new URL('/api/data/import/jobs', API_BASE_URL).toString()
  const response = await requestJson<ImportJobResponse>(url, signal, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      start_year: payload.startYear,
      end_year: payload.endYear,
      competition_codes: payload.competitionCodes,
    }),
  })
  return formatImportJob(response)
}

/** 查询后台导入任务的最新安全进度。 */
export async function fetchImportJob(jobId: string, signal: AbortSignal): Promise<ImportJob> {
  const url = new URL(`/api/data/import/jobs/${encodeURIComponent(jobId)}`, API_BASE_URL).toString()
  const response = await requestJson<ImportJobResponse>(url, signal)
  return formatImportJob(response)
}
