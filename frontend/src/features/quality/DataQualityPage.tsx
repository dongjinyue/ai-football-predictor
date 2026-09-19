import { Fragment, useEffect, useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight, DatabaseZap, RefreshCw } from 'lucide-react'

import { fetchDataAudit } from '../history/api'
import { competitionLabel } from '../history/display'
import type { DataAuditMarketCoverage, DataAuditReport, DataAuditScope } from '../history/types'

const AUDIT_START_YEAR = 2000
const AUDIT_END_YEAR = 2020

const marketNames: Record<string, string> = {
  match_result: '胜平负',
  asian_handicap: '亚洲让球',
  over_under_2_5: '大小球（2.5）',
}

function numberText(value: number): string {
  return value.toLocaleString('zh-CN')
}

function marketName(value: string): string {
  return marketNames[value] ?? value
}

function scopeStatus(scope: DataAuditScope): string {
  return scope.matchCount > 0 ? `已导入 ${numberText(scope.matchCount)} 场` : '未导入'
}

function marketCoverageText(market: DataAuditMarketCoverage): string {
  return `${numberText(market.matchCount)} 场比赛 · 赛前 ${numberText(market.preMatchMatchCount)} 场`
}

function ScopeDetails({ scope }: { scope: DataAuditScope }) {
  return <div className="quality-scope-details" role="region" aria-label={`${scope.competitionCode} ${scope.season} 数据明细`}>
    <dl className="quality-detail-facts">
      <div><dt>全场比分完整</dt><dd>{numberText(scope.completeFullTimeMatches)} / {numberText(scope.matchCount)}</dd></div>
      <div><dt>半场比分完整</dt><dd>{numberText(scope.completeHalfTimeMatches)} / {numberText(scope.matchCount)}</dd></div>
      <div><dt>半全场可派生</dt><dd>{numberText(scope.halfTimeResultMatches)} 场</dd></div>
      <div><dt>总进球可派生</dt><dd>{numberText(scope.totalGoalsMatches)} 场</dd></div>
      <div><dt>赛前可用盘口</dt><dd>{numberText(scope.preMatchMarketMatches)} 场</dd></div>
      <div><dt>开球时边界盘口</dt><dd>{numberText(scope.kickoffBoundMarketMatches)} 场</dd></div>
    </dl>
    <div className="quality-market-list">
      <div className="quality-detail-heading">
        <h3>市场覆盖</h3>
        <p>只有“赛前可用”才会进入赛前盘口特征；开球时边界数据仅用于展示和赛后分析。</p>
      </div>
      {scope.markets.length === 0 ? <p className="quality-muted">暂无盘口明细。</p> : <ul>
        {scope.markets.map((market) => <li key={market.marketType}>
          <span>{marketName(market.marketType)}</span>
          <span>{marketCoverageText(market)}</span>
        </li>)}
      </ul>}
    </div>
  </div>
}

function SummaryMetric({ label, value, tone = 'normal' }: { label: string; value: number; tone?: 'normal' | 'warning' }) {
  return <div className={`quality-metric quality-metric-${tone}`}>
    <dt>{label}</dt>
    <dd>{numberText(value)}</dd>
  </div>
}

export default function DataQualityPage() {
  const [report, setReport] = useState<DataAuditReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [retry, setRetry] = useState(0)
  const [expandedKey, setExpandedKey] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(false)
    const timeout = window.setTimeout(() => {
      controller.abort()
      setError(true)
      setLoading(false)
    }, 30000)

    void fetchDataAudit({ startYear: AUDIT_START_YEAR, endYear: AUDIT_END_YEAR }, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setReport(data)
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(true)
      })
      .finally(() => {
        window.clearTimeout(timeout)
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => {
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [retry])

  if (loading) {
    return <section className="quality-state" aria-label="数据质量加载状态" role="status">
      <DatabaseZap aria-hidden="true" size={22} />
      <div><h2>正在审计历史数据</h2><p>正在按联赛和赛季检查覆盖与时间口径。</p></div>
    </section>
  }

  if (error || !report) {
    return <section className="quality-state quality-state-error" role="alert">
      <AlertTriangle aria-hidden="true" size={22} />
      <div><h2>审计加载失败</h2><p>数据质量接口暂不可用，历史比赛页面不受影响。</p>
        <button type="button" className="history-button" onClick={() => setRetry((value) => value + 1)}>
          <RefreshCw aria-hidden="true" size={16} />重新加载审计
        </button>
      </div>
    </section>
  }

  const { summary } = report
  return <>
    <header className="page-header">
      <div><p className="eyebrow page-index">工作台 / 数据质量</p><h1>训练前数据审计</h1>
        <p className="page-summary">核对 2000–2020 年历史数据是否完整，并把可用于赛前训练的字段与开球后信息分开。</p>
      </div>
      <div className="system-state"><span className="state-dot" aria-hidden="true" />审计完成</div>
    </header>

    <section className="quality-summary" aria-label="审计结论">
      <div className="quality-summary-heading">
        <div><p className="eyebrow">覆盖结论</p><h2>{numberText(summary.labelReadyMatches)} 场可作为赛果训练样本</h2></div>
        <p>请求 {numberText(summary.requestedFiles)} 个联赛赛季文件，已找到 {numberText(summary.filesWithMatches)} 个有比赛记录的文件。</p>
      </div>
      <dl className="quality-metrics">
        <SummaryMetric label="历史比赛" value={summary.totalMatches} />
        <SummaryMetric label="半全场可派生" value={summary.halfTimeResultMatches} />
        <SummaryMetric label="总进球可派生" value={summary.totalGoalsMatches} />
        <SummaryMetric label="缺失源文件" value={summary.missingFiles} tone="warning" />
        <SummaryMetric label="赛前可用盘口" value={summary.preMatchMarketMatches} tone="warning" />
      </dl>
      <p className="quality-warning"><AlertTriangle aria-hidden="true" size={16} />开球时边界的数据不能用于赛前回测；当前审计会把它单独统计，不会混入“赛前可用盘口”。</p>
    </section>

    <section className="status-board quality-board" aria-label="联赛赛季覆盖明细">
      <div className="board-heading">
        <div><p className="eyebrow">逐项核对</p><h2>联赛与赛季覆盖</h2></div>
        <p className="quality-board-count">目录 {numberText(summary.catalogCompetitions)} 个联赛 · 数据库已有 {numberText(summary.importedCompetitions)} 个</p>
      </div>
      <div className="quality-table-scroll" role="region" aria-label="联赛赛季审计表" tabIndex={0}>
        <table className="quality-table">
          <caption className="sr-only">2000 到 2020 年联赛赛季数据覆盖明细</caption>
          <thead><tr><th scope="col">联赛</th><th scope="col">赛季</th><th scope="col">比赛数</th><th scope="col">半场比分</th><th scope="col">赛前盘口</th><th scope="col">状态</th><th scope="col">明细</th></tr></thead>
          <tbody>{report.scopes.map((scope) => {
            const key = `${scope.competitionCode}-${scope.season}`
            const expanded = expandedKey === key
            return <Fragment key={key}>
              <tr key={key}>
                <th scope="row">{competitionLabel(scope.competitionCode, scope.competitionName)} <small>（{scope.competitionCode}）</small></th>
                <td>{scope.season}</td>
                <td>{numberText(scope.matchCount)}</td>
                <td>{numberText(scope.completeHalfTimeMatches)} / {numberText(scope.matchCount)}</td>
                <td>{numberText(scope.preMatchMarketMatches)}</td>
                <td><span className={`quality-status ${scope.matchCount > 0 ? 'quality-status-ready' : 'quality-status-missing'}`}>{scopeStatus(scope)}</span></td>
                <td><button type="button" className="quality-detail-button" aria-expanded={expanded} onClick={() => setExpandedKey(expanded ? null : key)}>
                  {expanded ? <ChevronDown aria-hidden="true" size={16} /> : <ChevronRight aria-hidden="true" size={16} />}查看 {scope.competitionCode} {scope.season} 明细
                </button></td>
              </tr>
              {expanded && <tr key={`${key}-details`} className="quality-details-row"><td colSpan={7}><ScopeDetails scope={scope} /></td></tr>}
            </Fragment>
          })}</tbody>
        </table>
      </div>
    </section>
  </>
}
