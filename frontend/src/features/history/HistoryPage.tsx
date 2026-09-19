import { useCallback, useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, MoreHorizontal } from 'lucide-react'
import { buildHash, hashParams } from '../../routing'
import { fetchDataSummary, fetchMatchPage } from './api'
import HistoryFilters from './HistoryFilters'
import ImportPanel from './ImportPanel'
import MatchTable from './MatchTable'
import type { DataSummary, MatchPage } from './types'

const DEFAULT_PAGE_SIZE = 10
const PAGE_SIZE_OPTIONS = [10, 20, 50] as const
type PageSize = typeof PAGE_SIZE_OPTIONS[number]
type PageItem = number | 'ellipsis'

interface Query { competition: string; season: string; team: string; page: number; pageSize: PageSize }

function parsePageSize(value: string | null): PageSize {
  const parsed = Number(value)
  return PAGE_SIZE_OPTIONS.includes(parsed as PageSize) ? parsed as PageSize : DEFAULT_PAGE_SIZE
}

function pageItems(totalPages: number, currentPage: number): PageItem[] {
  if (totalPages <= 0) return []
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, index) => index + 1)
  if (currentPage <= 4) return [1, 2, 3, 4, 5, 'ellipsis', totalPages]
  if (currentPage >= totalPages - 3) {
    return [1, 'ellipsis', totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1, totalPages]
  }
  return [1, 'ellipsis', currentPage - 1, currentPage, currentPage + 1, 'ellipsis', totalPages]
}

/** 查询参数只保存已提交筛选，让刷新和浏览器返回恢复相同比赛范围。 */
function locationQueryParams(): URLSearchParams {
  const params = new URLSearchParams(window.location.search)
  hashParams(window.location.hash).forEach((value, key) => params.set(key, value))
  return params
}

function readQuery(): Query {
  const params = locationQueryParams()
  const requestedPage = Number(params.get('page') ?? 1)
  return {
    competition: params.get('competition') ?? '', season: params.get('season') ?? '',
    team: params.get('team') ?? '',
    page: Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1,
    pageSize: parsePageSize(params.get('page_size')),
  }
}

function dateText(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '暂无记录'
}

export default function HistoryPage() {
  const [query, setQuery] = useState(readQuery)
  const [jumpPage, setJumpPage] = useState(() => String(readQuery().page))
  const [summary, setSummary] = useState<DataSummary | null>(null)
  const [result, setResult] = useState<MatchPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [summaryError, setSummaryError] = useState(false)
  const [retry, setRetry] = useState(0)
  const [summaryRetry, setSummaryRetry] = useState(0)
  const [importOpen, setImportOpen] = useState(false)

  const commitQuery = useCallback((change: Partial<Query>) => {
    const next = { ...readQuery(), ...change }
    const url = new URL(window.location.href)
    const params = locationQueryParams()
    for (const key of ['competition', 'season', 'team'] as const) {
      if (next[key]) params.set(key, next[key])
      else params.delete(key)
    }
    if (next.page > 1) params.set('page', String(next.page))
    else params.delete('page')
    if (next.pageSize !== DEFAULT_PAGE_SIZE) params.set('page_size', String(next.pageSize))
    else params.delete('page_size')
    url.search = ''
    url.hash = buildHash('history', params).slice(1)
    const nextLocation = `${url.pathname}${url.search}${url.hash}`
    const currentLocation = `${window.location.pathname}${window.location.search}${window.location.hash}`
    if (nextLocation === currentLocation) return
    window.history.pushState(null, '', nextLocation)
    setQuery(next)
  }, [])

  const changeTeam = useCallback((team: string) => commitQuery({ team, page: 1 }), [commitQuery])
  const refreshAfterImport = useCallback(() => {
    setSummaryRetry((value) => value + 1)
    setRetry((value) => value + 1)
  }, [])

  useEffect(() => {
    const restoreQuery = () => setQuery(readQuery())
    window.addEventListener('popstate', restoreQuery)
    return () => window.removeEventListener('popstate', restoreQuery)
  }, [])

  useEffect(() => setJumpPage(String(query.page)), [query.page])

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
    void fetchMatchPage(query, controller.signal).then((data) => {
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
  const totalPages = result?.totalPages ?? 0
  const paginationItems = pageItems(totalPages, currentPage)
  const paginationDisabled = loading || error || !result || totalPages === 0

  function goToPage(page: number) {
    if (paginationDisabled || page === currentPage) return
    commitQuery({ page })
  }

  function submitJumpPage() {
    if (paginationDisabled) return
    const parsed = Number(jumpPage)
    const targetPage = Number.isInteger(parsed)
      ? Math.min(Math.max(parsed, 1), totalPages)
      : currentPage
    setJumpPage(String(targetPage))
    goToPage(targetPage)
  }

  return <>
    <header className="page-header">
      <div><p className="eyebrow page-index">工作台 / 比赛档案</p><h1>历史比赛</h1>
        <p className="page-summary">查看已导入的赛果与赔率，核对每条市场记录的来源和可用时间。</p>
      </div>
      <div className="page-header-actions">
        <div className="system-state"><span className="state-dot" aria-hidden="true" />历史数据</div>
        <button type="button" className="history-button import-trigger" onClick={() => setImportOpen(true)}>导入历史数据</button>
      </div>
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
    <ImportPanel open={importOpen} onClose={() => setImportOpen(false)} onCompleted={refreshAfterImport} />
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
        <p className="history-pagination-total" aria-live="polite">
          {loading ? '正在加载…' : error ? '数据暂不可用' : `共 ${result?.totalItems ?? 0} 条`}
        </p>
        <label className="history-page-size">
          <span className="sr-only">每页条数</span>
          <select aria-label="每页条数" value={query.pageSize} disabled={paginationDisabled}
            onChange={(event) => commitQuery({ page: 1, pageSize: parsePageSize(event.target.value) })}>
            {PAGE_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{size}条/页</option>)}
          </select>
        </label>
        <div className="history-page-controls" aria-label="页码">
          <button type="button" className="history-page-button" aria-label="上一页" title="上一页"
            disabled={paginationDisabled || currentPage <= 1} onClick={() => goToPage(currentPage - 1)}>
            <ChevronLeft aria-hidden="true" size={18} strokeWidth={1.8} />
          </button>
          {paginationItems.map((item, index) => item === 'ellipsis' ? (
            <span className="history-page-ellipsis" aria-hidden="true" key={`ellipsis-${index}`}>
              <MoreHorizontal size={18} strokeWidth={1.8} />
            </span>
          ) : (
            <button type="button" className="history-page-button" key={item}
              aria-label={`第 ${item} 页`} aria-current={item === currentPage ? 'page' : undefined}
              disabled={paginationDisabled} onClick={() => goToPage(item)}>{item}</button>
          ))}
          <button type="button" className="history-page-button" aria-label="下一页" title="下一页"
            disabled={paginationDisabled || currentPage >= totalPages} onClick={() => goToPage(currentPage + 1)}>
            <ChevronRight aria-hidden="true" size={18} strokeWidth={1.8} />
          </button>
        </div>
        <label className="history-page-jump">
          <span>前往</span>
          <input aria-label="前往页码" type="number" min={1} max={Math.max(1, totalPages)} value={jumpPage}
            disabled={paginationDisabled} onChange={(event) => setJumpPage(event.target.value)}
            onBlur={submitJumpPage}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                submitJumpPage()
              }
            }} />
          <span>页</span>
        </label>
      </nav>
    </section>
  </>
}
