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
}

export interface MarketOutcome {
  outcomeCode: string
  odds: number
}

export interface MatchMarket {
  marketType: string
  stage: string
  timePrecision: string
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
  homeTeam: string
  awayTeam: string
  halfTimeHomeScore: number | null
  halfTimeAwayScore: number | null
  homeScore: number | null
  awayScore: number | null
  markets: MatchMarket[]
}

export interface MatchFilterOptions {
  competitions: string[]
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
