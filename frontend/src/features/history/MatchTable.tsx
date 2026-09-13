import { Fragment, useState, type ReactNode } from 'react'
import type { HistoricalMatch, MatchMarket } from './types'

/** 缺失比分保留为破折号，不能用 0 冒充已知赛果。 */
function score(home: number | null, away: number | null) {
  return `${home ?? '—'}–${away ?? '—'}`
}

const marketLabels: Record<string, string> = {
  match_result: '胜平负', asian_handicap: '亚洲让球', over_under_2_5: '大小球',
}
const outcomeLabels: Record<string, string> = {
  home: '主队', draw: '平局', away: '客队', over_2_5: '大于 2.5 球', under_2_5: '小于 2.5 球',
}

function MarketDetails({ market }: { market: MatchMarket }) {
  return <article className="history-market">
    <h3>{marketLabels[market.marketType] ?? market.marketType}</h3>
    {market.line !== null && <p>盘口：{market.line.toFixed(2)}{market.marketType === 'asian_handicap' ? '（主队让球）' : ' 球'}</p>}
    <dl className="history-market-outcomes">{market.outcomes.map((outcome) => <div key={outcome.outcomeCode}>
      <dt>{outcomeLabels[outcome.outcomeCode] ?? outcome.outcomeCode}</dt><dd>{outcome.odds.toFixed(2)}</dd>
    </div>)}</dl>
    <dl className="history-provenance">
      <div><dt>来源</dt><dd>{market.source}</dd></div>
      <div><dt>提供方</dt><dd>{market.provider === 'average' ? 'average（市场平均）' : market.provider}</dd></div>
      <div><dt>阶段</dt><dd>{market.stage === 'closing' ? 'closing（收盘）' : market.stage}</dd></div>
      <div><dt>采集时间（记录值）</dt><dd><time dateTime={market.capturedAt}>{new Date(market.capturedAt).toLocaleString('zh-CN')}</time></dd></div>
      <div><dt>可用时间</dt><dd><time dateTime={market.availableAt}>{new Date(market.availableAt).toLocaleString('zh-CN')}</time></dd></div>
      <div><dt>时间精度</dt><dd>{market.timePrecision === 'kickoff_bound' ? 'kickoff_bound（开球时间边界）' : market.timePrecision}</dd></div>
    </dl>
    {market.timePrecision === 'kickoff_bound' && <p className="history-warning">仅能确认开球时可用，不能用于开球前回测。记录时间不代表真实采集时刻。</p>}
  </article>
}

export default function MatchTable({ items, children }: { items: HistoricalMatch[]; children?: ReactNode }) {
  const [expandedMatchId, setExpandedMatchId] = useState<string | null>(null)
  return (
    <div className="history-table-scroll" role="region" aria-label="比赛表格，可横向滚动" tabIndex={0}>
      <table className="history-table">
        <caption className="sr-only">历史比赛列表</caption>
        <thead><tr>
          <th scope="col">开球时间</th><th scope="col">联赛 / 赛季</th>
          <th scope="col">主队 · 全场 · 客队</th><th scope="col">半场</th>
          <th scope="col">1（主胜）</th><th scope="col">X（平局）</th><th scope="col">2（客胜）</th>
          <th scope="col">市场记录</th>
        </tr></thead>
        <tbody>{children ? <tr><td colSpan={8} className="history-table-state">{children}</td></tr> : items.map((match) => {
          const result = match.markets.find((market) => market.marketType === 'match_result')
          const expanded = expandedMatchId === match.id
          return <Fragment key={match.id}><tr>
            <td><time dateTime={match.kickoffAt}>{new Date(match.kickoffAt).toLocaleString('zh-CN')}</time></td>
            <td>{match.competitionName}（{match.competitionCode}）<small>{match.season}</small></td>
            <th scope="row">{`${match.homeTeam} ${score(match.homeScore, match.awayScore)} ${match.awayTeam}`}</th>
            <td>{score(match.halfTimeHomeScore, match.halfTimeAwayScore)}</td>
            {['home', 'draw', 'away'].map((code) => <td key={code}>{result?.outcomes.find((outcome) => outcome.outcomeCode === code)?.odds.toFixed(2) ?? '—'}</td>)}
            <td><button type="button" className="history-button" aria-expanded={expanded} aria-controls={`markets-${match.id}`}
              aria-label={`${expanded ? '收起' : '展开'}市场：${match.homeTeam} 对 ${match.awayTeam}`}
              onClick={() => setExpandedMatchId(expanded ? null : match.id)}>{expanded ? '收起市场' : '展开市场'}</button></td>
          </tr>
            {expanded && <tr><td colSpan={8} className="history-details-cell">
              <section id={`markets-${match.id}`} aria-label={`${match.homeTeam} 对 ${match.awayTeam} 的市场详情`}>
                <h2 className="history-details-title">{match.homeTeam} 对 {match.awayTeam} · 市场记录</h2>
                {match.markets.length === 0 ? <p>这场比赛暂无市场记录。</p> : <div className="history-markets">{match.markets.map((market, index) => <MarketDetails key={index} market={market} />)}</div>}
              </section>
            </td></tr>}
          </Fragment>
        })}</tbody>
      </table>
    </div>
  )
}
