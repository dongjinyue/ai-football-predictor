import { ArrowDown, ArrowUp } from 'lucide-react'
import type { CSSProperties } from 'react'

import { historyOutcomeLabel, marketHistoryLabels } from './display'
import type { MarketHistoryGroup, MarketHistorySnapshot } from './types'

const shanghaiTime = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

function outcomeValue(snapshot: MarketHistorySnapshot | undefined, code: string) {
  return snapshot?.outcomes.find((outcome) => outcome.outcomeCode === code)?.odds
}

interface OddsCellProps {
  code: string
  current: number | undefined
  previous: number | undefined
}

function OddsCell({ code, current, previous }: OddsCellProps) {
  if (current === undefined) return <td>—</td>
  const direction = previous === undefined || current === previous
    ? null
    : current > previous ? 'up' : 'down'
  const label = direction
    ? `${historyOutcomeLabel(code)}赔率从 ${previous!.toFixed(2)} ${direction === 'up' ? '升至' : '降至'} ${current.toFixed(2)}`
    : undefined

  return <td className={direction ? `odds-${direction}` : undefined}>
    <span>{current.toFixed(2)}</span>
    {direction && <span aria-label={label} className="odds-direction">
      {direction === 'up'
        ? <ArrowUp aria-hidden="true" size={14} strokeWidth={2.25} />
        : <ArrowDown aria-hidden="true" size={14} strokeWidth={2.25} />}
    </span>}
  </td>
}

export default function OddsTimelineTable({ market }: { market: MarketHistoryGroup }) {
  const title = marketHistoryLabels[market.marketType] ?? market.marketType
  return <div
    className="odds-timeline-scroll"
    role="region"
    aria-label={`${title}赔率时间线`}
    tabIndex={0}
  >
    <table
      className="odds-timeline-table"
      style={{ '--outcome-count': market.outcomeCodes.length } as CSSProperties}
    >
      <caption className="sr-only">{title}赔率发布时间变化</caption>
      <thead><tr>
        <th scope="col">发布时间</th>
        {market.outcomeCodes.map((code) => <th scope="col" key={code}>
          {historyOutcomeLabel(code)}
        </th>)}
      </tr></thead>
      <tbody>{market.snapshots.map((snapshot, index) => {
        const previous = market.snapshots[index - 1]
        return <tr key={`${snapshot.capturedAt}-${index}`}>
          <th scope="row">
            <time dateTime={snapshot.capturedAt}>{shanghaiTime.format(new Date(snapshot.capturedAt))}</time>
          </th>
          {market.outcomeCodes.map((code) => <OddsCell
            code={code}
            current={outcomeValue(snapshot, code)}
            previous={outcomeValue(previous, code)}
            key={code}
          />)}
        </tr>
      })}</tbody>
    </table>
  </div>
}
