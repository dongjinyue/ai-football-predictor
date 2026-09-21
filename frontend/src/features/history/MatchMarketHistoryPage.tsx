import { useEffect, useState } from 'react'
import { ArrowLeft, RefreshCw } from 'lucide-react'

import { DataRequestError, fetchMatchMarketHistory } from './api'
import { competitionLabel, teamLabel } from './display'
import MarketHistorySection from './MarketHistorySection'
import type { MatchMarketHistory } from './types'

interface Props {
  matchId: string
  returnHash: string
}

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; data: MatchMarketHistory }
  | { status: 'not-found' }
  | { status: 'error' }

function score(home: number | null, away: number | null) {
  return `${home ?? '—'}–${away ?? '—'}`
}

function kickoffText(match: MatchMarketHistory) {
  if (match.kickoffTimePrecision === 'date_only') {
    return `${new Intl.DateTimeFormat('zh-CN', {
      timeZone: 'Asia/Shanghai', year: 'numeric', month: 'long', day: 'numeric',
    }).format(new Date(match.kickoffAt))}（时间未知）`
  }
  return new Date(match.kickoffAt).toLocaleString('zh-CN')
}

export default function MatchMarketHistoryPage({ matchId, returnHash }: Props) {
  const [requestVersion, setRequestVersion] = useState(0)
  const [state, setState] = useState<LoadState>({ status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()
    setState({ status: 'loading' })
    fetchMatchMarketHistory(matchId, controller.signal)
      .then((data) => setState({ status: 'ready', data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setState({
          status: error instanceof DataRequestError && error.status === 404
            ? 'not-found'
            : 'error',
        })
      })
    return () => controller.abort()
  }, [matchId, requestVersion])

  return <section className="market-history-page">
    <a className="back-link" href={returnHash || '#history'}>
      <ArrowLeft aria-hidden="true" size={18} />返回历史比赛
    </a>

    {state.status === 'loading' && <div className="market-page-state" role="status">
      <p className="eyebrow">市场详情</p>
      <h1>正在加载市场记录</h1>
    </div>}

    {state.status === 'not-found' && <div className="market-page-state" role="alert">
      <p className="eyebrow">市场详情</p>
      <h1>比赛不存在或已被移除</h1>
      <p>请返回历史比赛列表，重新选择一场比赛。</p>
    </div>}

    {state.status === 'error' && <div className="market-page-state" role="alert">
      <p className="eyebrow">市场详情</p>
      <h1>市场记录加载失败</h1>
      <p>数据服务暂时不可用，请稍后重试。</p>
      <button className="history-button" type="button" onClick={() => setRequestVersion((value) => value + 1)}>
        <RefreshCw aria-hidden="true" size={17} />重新加载
      </button>
    </div>}

    {state.status === 'ready' && <>
      <header className="market-match-header">
        <p className="eyebrow">{competitionLabel(state.data.competitionCode, state.data.competitionName)} · {state.data.season}</p>
        <h1>{teamLabel(state.data.homeTeam)} {score(state.data.homeScore, state.data.awayScore)} {teamLabel(state.data.awayTeam)}</h1>
        <p className="page-summary">{kickoffText(state.data)}</p>
        <dl className="market-match-summary">
          <div><dt>半场比分</dt><dd>{score(state.data.halfTimeHomeScore, state.data.halfTimeAwayScore)}</dd></div>
          <div><dt>全场比分</dt><dd>{score(state.data.homeScore, state.data.awayScore)}</dd></div>
          <div><dt>数据来源</dt><dd>中国体育彩票</dd></div>
          <div><dt>赔率记录</dt><dd>{state.data.markets.reduce((sum, market) => sum + market.snapshots.length, 0)} 次发布</dd></div>
        </dl>
      </header>
      {state.data.markets.length === 0
        ? <div className="market-empty-state" role="status">该场比赛没有已采集的赔率记录</div>
        : <div className="market-history-sections">
          {state.data.markets.map((market) => <MarketHistorySection
            market={market}
            key={`${market.marketType}-${market.line ?? 'none'}`}
          />)}
        </div>}
    </>}
  </section>
}
