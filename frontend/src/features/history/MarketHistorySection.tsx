import {
  marketHistoryLabels,
  providerLabel,
  sourceLabel,
  timePrecisionLabel,
} from './display'
import OddsTimelineTable from './OddsTimelineTable'
import type { MarketHistoryGroup } from './types'

function lineLabel(line: number) {
  const formatted = Number.isInteger(line) ? line.toFixed(0) : line.toFixed(2)
  return `让球 ${line > 0 ? '+' : ''}${formatted}`
}

export default function MarketHistorySection({ market }: { market: MarketHistoryGroup }) {
  const title = marketHistoryLabels[market.marketType] ?? market.marketType
  return <section className="market-history-section" aria-labelledby={`market-${market.marketType}-${market.line ?? 'none'}`}>
    <header className="market-history-heading">
      <div>
        <h2 id={`market-${market.marketType}-${market.line ?? 'none'}`}>{title}</h2>
        {market.line !== null && <p className="market-line">{lineLabel(market.line)}</p>}
      </div>
      <dl className="market-provenance">
        <div><dt>来源</dt><dd>{sourceLabel(market.source)}</dd></div>
        <div><dt>提供方</dt><dd>{providerLabel(market.provider)}</dd></div>
        <div><dt>时间精度</dt><dd>{timePrecisionLabel(market.timePrecision)}</dd></div>
      </dl>
    </header>
    <OddsTimelineTable market={market} />
  </section>
}
