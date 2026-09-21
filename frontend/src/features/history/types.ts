/**
 * 历史比赛接口（API）在前端使用的筛选参数。
 *
 * page 与 pageSize 可省略，省略时由后端采用默认分页；字符串筛选为空时不发送。
 */
export interface MatchFilters {
  page?: number
  pageSize?: number
  competition?: string
  season?: string
  team?: string
  startDate?: string
  endDate?: string
}

export interface MarketOutcome {
  outcomeCode: string
  odds: number
}

export interface MatchMarket {
  marketType: string
  stage: string
  timePrecision: string
  source: string
  provider: string
  capturedAt: string
  availableAt: string
  line: number | null
  outcomes: MarketOutcome[]
}

export interface HistoricalMatch {
  id: string
  competitionCode: string
  competitionName: string
  season: string
  /** 保留后端 ISO（国际标准化组织）时间字符串，显示时再按本地时区格式化。 */
  kickoffAt: string
  /** 体彩历史列表可能只有比赛日期，不能把排序用的中午时间当成真实开球时间。 */
  kickoffTimePrecision: 'exact' | 'date_only'
  homeTeam: string
  awayTeam: string
  halfTimeHomeScore: number | null
  halfTimeAwayScore: number | null
  halfTimeResult: 'home' | 'draw' | 'away' | null
  homeScore: number | null
  awayScore: number | null
  fullTimeResult: 'home' | 'draw' | 'away' | null
  totalGoals: number | null
  markets: MatchMarket[]
}

export interface MarketHistorySnapshot {
  capturedAt: string
  availableAt: string
  outcomes: MarketOutcome[]
}

export interface MarketHistoryGroup {
  marketType: string
  line: number | null
  source: string
  provider: string
  stage: string
  timePrecision: string
  outcomeCodes: string[]
  snapshots: MarketHistorySnapshot[]
}

export interface MatchMarketHistory {
  id: string
  competitionCode: string
  competitionName: string
  season: string
  kickoffAt: string
  kickoffTimePrecision: 'exact' | 'date_only'
  homeTeam: string
  awayTeam: string
  halfTimeHomeScore: number | null
  halfTimeAwayScore: number | null
  homeScore: number | null
  awayScore: number | null
  markets: MarketHistoryGroup[]
}

export interface ImportCompetition {
  code: string
  name: string
  countryCode: string
  seasonStyle: 'split_year' | 'calendar_year'
}

export interface ImportCatalog {
  competitions: ImportCompetition[]
  startYear: number
  endYear: number
}

export type ImportJobStatus = 'queued' | 'running' | 'completed' | 'completed_with_errors' | 'failed'

export interface ImportJob {
  jobId: string
  runId: string | null
  status: ImportJobStatus
  requestedFiles: number
  completedFiles: number
  failedFiles: number
  importedMatches: number
  skippedRows: number
  errors: string[]
  currentCompetitionCode: string | null
  currentSeason: string | null
}

export interface MatchFilterOptions {
  competitions: Array<{ code: string; name: string }>
  seasons: string[]
}

export interface MatchPage {
  page: number
  pageSize: number
  totalItems: number
  totalPages: number
  filters: MatchFilterOptions
  items: HistoricalMatch[]
}

export interface DataSummary {
  competitions: number
  teams: number
  matches: number
  marketSnapshots: number
  marketOutcomes: number
  latestKickoffAt: string | null
  latestSuccessfulImportAt: string | null
}

export interface DataAuditMarketCoverage {
  marketType: string
  snapshotCount: number
  matchCount: number
  preMatchSnapshotCount: number
  preMatchMatchCount: number
  kickoffBoundSnapshotCount: number
  kickoffBoundMatchCount: number
  postKickoffSnapshotCount: number
}

export interface DataAuditScope {
  competitionCode: string
  competitionName: string
  countryCode: string
  season: string
  matchCount: number
  completeFullTimeMatches: number
  completeHalfTimeMatches: number
  missingHalfTimeMatches: number
  halfTimeResultMatches: number
  totalGoalsMatches: number
  labelReadyMatches: number
  preMatchMarketMatches: number
  kickoffBoundMarketMatches: number
  postKickoffMarketMatches: number
  markets: DataAuditMarketCoverage[]
}

export interface DataAuditSummary {
  catalogCompetitions: number
  importedCompetitions: number
  requestedFiles: number
  filesWithMatches: number
  missingFiles: number
  totalMatches: number
  completeFullTimeMatches: number
  completeHalfTimeMatches: number
  missingHalfTimeMatches: number
  halfTimeResultMatches: number
  totalGoalsMatches: number
  labelReadyMatches: number
  preMatchMarketMatches: number
  kickoffBoundMarketMatches: number
  postKickoffMarketMatches: number
}

export interface DataAuditReport {
  startYear: number
  endYear: number
  requestedFiles: number
  summary: DataAuditSummary
  scopes: DataAuditScope[]
}
