import { useCallback, useEffect, useState } from 'react'
import { fetchDataSummary, fetchMatchPage } from './api'
import HistoryFilters from './HistoryFilters'
import MatchTable from './MatchTable'
import type { DataSummary, MatchPage } from './types'

interface Query { competition: string; season: string; team: string; page: number }

/** 查询参数只保存已提交筛选，让刷新和浏览器返回恢复相同比赛范围。 */
function readQuery(): Query {
  const params = new URLSearchParams(window.location.search)
  const requestedPage = Number(params.get('page') ?? 1)
  return {
    competition: params.get('competition') ?? '', season: params.get('season') ?? '',
    team: params.get('team') ?? '',
    page: Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1,
  }
}

function dateText(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '暂无记录'
}

export default function HistoryPage() {
  const [query, setQuery] = useState(readQuery)
  const [summary, setSummary] = useState<DataSummary | null>(null)
  const [result, setResult] = useState<MatchPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [summaryError, setSummaryError] = useState(false)
  const [retry, setRetry] = useState(0)
  const [summaryRetry, setSummaryRetry] = useState(0)

  const commitQuery = useCallback((change: Partial<Query>) => {
    const next = { ...readQuery(), ...change }
    const url = new URL(window.location.href)
    for (const key of ['competition', 'season', 'team'] as const) {
      if (next[key]) url.searchParams.set(key, next[key])
      else url.searchParams.delete(key)
    }
    if (next.page > 1) url.searchParams.set('page', String(next.page))
    else url.searchParams.delete('page')
    if (url.href === window.location.href) return
    window.history.pushState(null, '', url)
    setQuery(next)
  }, [])

  const changeTeam = useCallback((team: string) => commitQuery({ team, page: 1 }), [commitQuery])

  useEffect(() => {
    const restoreQuery = () => setQuery(readQuery())
    window.addEventListener('popstate', restoreQuery)
    return () => window.removeEventListener('popstate', restoreQuery)
  }, [])

  // 摘要和比赛独立请求：摘要故障时，仍可查询已成功返回的比赛。
  useEffect(() => {
    const controller = new AbortController()
    setSummaryLoading(true)
    setSummaryError(false)
    // 超时转为可重试状态，避免网络无响应时一直显示加载。
    const timeout = window.setTimeout(() => {
      controller.abort()
      setSummaryError(true)
      setSummaryLoading(false)
    }, 30000)
    void fetchDataSummary(controller.signal).then((data) => {
      if (!controller.signal.aborted) setSummary(data)
    }).catch(() => {
      if (!controller.signal.aborted) setSummaryError(true)
    }).finally(() => {
      window.clearTimeout(timeout)
      if (!controller.signal.aborted) setSummaryLoading(false)
    })
    return () => { window.clearTimeout(timeout); controller.abort() }
  }, [summaryRetry])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(false)
    const timeout = window.setTimeout(() => {
      controller.abort()
      setError(true)
      setLoading(false)
    }, 30000)
    void fetchMatchPage({ ...query, pageSize: 20 }, controller.signal).then((data) => {
      // 信号检查同时阻止已返回的旧响应覆盖新筛选。
      if (controller.signal.aborted) return
      setResult(data)
      if (data.totalPages > 0 && query.page > data.totalPages) commitQuery({ page: data.totalPages })
    }).catch(() => {
      if (!controller.signal.aborted) setError(true)
    }).finally(() => {
      window.clearTimeout(timeout)
      if (!controller.signal.aborted) setLoading(false)
    })
    return () => { window.clearTimeout(timeout); controller.abort() }
  }, [query, retry, commitQuery])

  const hasFilters = Boolean(query.competition || query.season || query.team)
  const currentPage = result?.page ?? query.page
  const range = result && result.totalItems > 0
    ? `第 ${(currentPage - 1) * result.pageSize + 1}–${Math.min(currentPage * result.pageSize, result.totalItems)} 场，共 ${result.totalItems} 场`
    : '共 0 场'

  return <>
    <header className="page-header">
      <div><p className="eyebrow page-index">工作台 / 比赛档案</p><h1>历史比赛</h1>
        <p className="page-summary">查看已导入的赛果与赔率，核对每条市场记录的来源和可用时间。</p>
      </div>
      <div className="system-state"><span className="state-dot" aria-hidden="true" />历史数据</div>
    </header>
    <section aria-label="数据摘要" className="history-summary">
      {summaryLoading ? <p role="status">正在加载摘要…</p> : summaryError ? <div role="alert">
        <p>摘要加载失败，比赛查询仍可使用。</p>
        <button type="button" className="history-button" onClick={() => setSummaryRetry((value) => value + 1)}>重新加载摘要</button>
      </div> : summary && <>
        <dl className="history-summary-counts">
          <div><dt>比赛</dt><dd>{summary.matches}</dd></div>
          <div><dt>联赛</dt><dd>{summary.competitions}</dd></div>
          <div><dt>球队</dt><dd>{summary.teams}</dd></div>
          <div><dt>市场快照</dt><dd>{summary.marketSnapshots}</dd></div>
          <div><dt>赔率结果</dt><dd>{summary.marketOutcomes}</dd></div>
        </dl>
        <p className="history-update">最近比赛：{dateText(summary.latestKickoffAt)}<br />最近成功导入：{dateText(summary.latestSuccessfulImportAt)}</p>
      </>}
    </section>
    <section className="status-board history-board" aria-label="历史比赛查询">
      <HistoryFilters {...query} options={result?.filters ?? { competitions: [], seasons: [] }}
        onCompetitionChange={(competition) => commitQuery({ competition, page: 1 })}
        onSeasonChange={(season) => commitQuery({ season, page: 1 })}
        onTeamChange={changeTeam} onClear={() => commitQuery({ competition: '', season: '', team: '', page: 1 })} />
      <p className="history-help">时间按当前设备时区显示。1 / X / 2 为主胜 / 平局 / 客胜赔率；— 表示缺少记录。窄屏可横向滚动表格。</p>
      <MatchTable key={`${query.competition}/${query.season}/${query.team}/${query.page}/${retry}`}
        items={loading || error ? [] : result?.items ?? []}>
        {loading ? <div role="status" aria-label="比赛加载状态">正在加载比赛…</div> : error ? <div role="alert">
          <p>比赛加载失败，请检查数据服务后重试。</p>
          <button type="button" className="history-button" onClick={() => setRetry((value) => value + 1)}>重新加载比赛</button>
        </div> : result?.items.length === 0 ? <div role="status">
          <h2>{hasFilters ? '没有符合条件的比赛' : '尚未导入历史比赛'}</h2>
          <p>{hasFilters ? '试试其他球队、联赛或赛季，也可以清除筛选。' : '完成历史数据导入后，赛果和市场记录会出现在这里。'}</p>
        </div> : null}
      </MatchTable>
      <nav className="history-pagination" aria-label="比赛分页">
        <p aria-live="polite">{loading ? '正在更新比赛范围…' : error ? '比赛范围暂不可用' : range}</p>
        <div>
          <button type="button" className="history-button" disabled={loading || error || currentPage <= 1}
            onClick={() => commitQuery({ page: Math.max(1, currentPage - 1) })}>上一页</button>
          <span>{result && !loading && !error ? `${currentPage} / ${Math.max(1, result.totalPages)}` : '— / —'}</span>
          <button type="button" className="history-button" disabled={loading || error || !result || currentPage >= result.totalPages}
            onClick={() => commitQuery({ page: currentPage + 1 })}>下一页</button>
        </div>
      </nav>
    </section>
  </>
}
