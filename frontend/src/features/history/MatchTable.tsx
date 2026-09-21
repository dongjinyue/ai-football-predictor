import type { ReactNode } from 'react'

import { buildMatchDetailHash } from '../../routing'
import { competitionLabel, teamLabel } from './display'
import type { HistoricalMatch, MatchMarket } from './types'

function score(home: number | null, away: number | null) {
  return `${home ?? '—'}–${away ?? '—'}`
}

const resultLabels = { home: '胜', draw: '平', away: '负' } as const

function halfFullResult(
  halfTimeResult: keyof typeof resultLabels | null,
  fullTimeResult: keyof typeof resultLabels | null,
) {
  if (!halfTimeResult || !fullTimeResult) return '—'
  return `${resultLabels[halfTimeResult]} / ${resultLabels[fullTimeResult]}`
}

function kickoffText(match: HistoricalMatch) {
  const kickoff = new Date(match.kickoffAt)
  if (match.kickoffTimePrecision === 'date_only') {
    const date = new Intl.DateTimeFormat('zh-CN', {
      timeZone: 'Asia/Shanghai', year: 'numeric', month: 'numeric', day: 'numeric',
    }).format(kickoff)
    return `${date}（时间未知）`
  }
  return kickoff.toLocaleString('zh-CN')
}

function primaryResultMarket(markets: MatchMarket[]) {
  return markets.find((market) => market.marketType === 'match_result')
    ?? markets.find((market) => market.marketType === 'handicap_result')
}

function marketLineLabel(market: MatchMarket | undefined) {
  if (!market || market.marketType !== 'handicap_result') return null
  if (market.line === null) return '让球'
  const line = Number.isInteger(market.line) ? market.line.toFixed(0) : market.line.toFixed(2)
  return `让球 ${market.line > 0 ? '+' : ''}${line}`
}

export default function MatchTable({ items, children }: { items: HistoricalMatch[]; children?: ReactNode }) {
  const returnHash = window.location.hash || '#history'
  return <div className="history-table-scroll" role="region" aria-label="比赛表格，可横向滚动" tabIndex={0}>
    <table className="history-table">
      <caption className="sr-only">历史比赛列表</caption>
      <thead><tr>
        <th scope="col">开球时间</th><th scope="col">联赛 / 赛季</th>
        <th scope="col">主队 · 全场 · 客队</th><th scope="col">半场</th>
        <th scope="col">半全场</th><th scope="col">总进球</th>
        <th scope="col">1（主胜）</th><th scope="col">X（平局）</th><th scope="col">2（客胜）</th>
        <th scope="col">市场记录</th>
      </tr></thead>
      <tbody>{children ? <tr><td colSpan={10} className="history-table-state">{children}</td></tr> : items.map((match) => {
        const result = primaryResultMarket(match.markets)
        const resultMarketLabel = marketLineLabel(result)
        const homeTeam = teamLabel(match.homeTeam)
        const awayTeam = teamLabel(match.awayTeam)
        return <tr key={match.id}>
          <td><time dateTime={match.kickoffAt}>{kickoffText(match)}</time></td>
          <td>{competitionLabel(match.competitionCode, match.competitionName)}（{match.competitionCode}）<small>{match.season}</small></td>
          <th scope="row">{`${homeTeam} ${score(match.homeScore, match.awayScore)} ${awayTeam}`}</th>
          <td>{score(match.halfTimeHomeScore, match.halfTimeAwayScore)}</td>
          <td>{halfFullResult(match.halfTimeResult, match.fullTimeResult)}</td>
          <td>{match.totalGoals ?? '—'}</td>
          {(['home', 'draw', 'away'] as const).map((code, index) => <td key={code} className="history-primary-odd">
            {index === 0 && resultMarketLabel && <small className="history-odds-kind">{resultMarketLabel}</small>}
            {result?.outcomes.find((outcome) => outcome.outcomeCode === code)?.odds.toFixed(2) ?? '—'}
          </td>)}
          <td><a
            className="history-button"
            href={buildMatchDetailHash(match.id, returnHash)}
            aria-label={`查看${homeTeam}对${awayTeam}的市场详情`}
          >市场详情</a></td>
        </tr>
      })}</tbody>
    </table>
  </div>
}
