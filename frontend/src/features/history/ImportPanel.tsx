import { useEffect, useRef, useState } from 'react'

import { fetchImportCatalog, fetchImportJob, submitImportJob } from './api'
import { competitionLabel, importErrorLabel } from './display'
import type { ImportCatalog, ImportJob } from './types'

interface ImportPanelProps {
  open: boolean
  onClose: () => void
  onCompleted: () => void
}

const terminalStatuses = new Set<ImportJob['status']>(['completed', 'completed_with_errors', 'failed'])

function statusText(status: ImportJob['status']) {
  switch (status) {
    case 'queued': return '等待开始'
    case 'running': return '正在导入'
    case 'completed': return '导入已完成'
    case 'completed_with_errors': return '导入完成，但有文件失败'
    case 'failed': return '导入失败'
  }
}

function progressPercent(job: ImportJob) {
  if (!job.requestedFiles) return 100
  return Math.min(100, Math.round(((job.completedFiles + job.failedFiles) / job.requestedFiles) * 100))
}

export default function ImportPanel({ open, onClose, onCompleted }: ImportPanelProps) {
  const [catalog, setCatalog] = useState<ImportCatalog | null>(null)
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [catalogRetry, setCatalogRetry] = useState(0)
  const [allCompetitions, setAllCompetitions] = useState(true)
  const [selectedCodes, setSelectedCodes] = useState<string[]>([])
  const [startYear, setStartYear] = useState(2000)
  const [endYear, setEndYear] = useState(2020)
  const [job, setJob] = useState<ImportJob | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const refreshedJob = useRef<string | null>(null)

  useEffect(() => {
    if (!open || catalog) return
    const controller = new AbortController()
    setCatalogLoading(true)
    setError(null)
    void fetchImportCatalog(controller.signal).then((value) => {
      if (controller.signal.aborted) return
      setCatalog(value)
      setStartYear(value.startYear)
      setEndYear(value.endYear)
    }).catch(() => {
      if (!controller.signal.aborted) setError('导入目录加载失败，请稍后重试。')
    }).finally(() => {
      if (!controller.signal.aborted) setCatalogLoading(false)
    })
    return () => controller.abort()
  }, [catalog, catalogRetry, open])

  useEffect(() => {
    if (!job || terminalStatuses.has(job.status)) return
    let active = true
    const controller = new AbortController()
    const poll = async () => {
      try {
        const next = await fetchImportJob(job.jobId, controller.signal)
        if (active) setJob(next)
      } catch {
        if (active && !controller.signal.aborted) setError('导入进度暂时无法读取，系统会继续执行任务。')
      }
    }
    void poll()
    const timer = window.setInterval(() => { void poll() }, 1000)
    return () => {
      active = false
      controller.abort()
      window.clearInterval(timer)
    }
  }, [job])

  useEffect(() => {
    if (!job || !terminalStatuses.has(job.status) || refreshedJob.current === job.jobId) return
    refreshedJob.current = job.jobId
    onCompleted()
  }, [job, onCompleted])

  if (!open) return null

  const years = catalog
    ? Array.from({ length: catalog.endYear - catalog.startYear + 1 }, (_, index) => catalog.startYear + index)
    : []
  const jobActive = Boolean(job && !terminalStatuses.has(job.status))

  async function startImport() {
    if (!catalog || submitting || jobActive) return
    const controller = new AbortController()
    setSubmitting(true)
    setError(null)
    refreshedJob.current = null
    try {
      const next = await submitImportJob({
        competitionCodes: allCompetitions ? [] : selectedCodes,
        startYear,
        endYear,
      }, controller.signal)
      setJob(next)
    } catch {
      setError('导入任务提交失败，请检查后端服务是否正在运行。')
    } finally {
      setSubmitting(false)
    }
  }

  return <section className="import-panel" aria-label="历史数据导入" aria-labelledby="import-panel-title">
    <div className="import-panel-heading">
      <div>
        <p className="eyebrow">数据导入</p>
        <h2 id="import-panel-title">导入历史数据</h2>
        <p>数据会在后台处理，页面可继续浏览。重复导入不会重复写入比赛。</p>
      </div>
      <button type="button" className="history-button" onClick={onClose} disabled={jobActive}>关闭</button>
    </div>

    {catalogLoading && <p role="status">正在读取可用联赛…</p>}
    {error && <div className="import-error-block" role="alert">
      <p className="import-error">{error}</p>
      {!catalog && <button type="button" className="history-button" onClick={() => setCatalogRetry((value) => value + 1)} disabled={catalogLoading}>重新读取联赛</button>}
    </div>}
    {catalog && !job && <div className="import-form">
      <fieldset disabled={submitting}>
        <legend>联赛范围</legend>
        <label className="import-checkbox">
          <input type="checkbox" checked={allCompetitions} onChange={(event) => setAllCompetitions(event.target.checked)} />
          <span>全部支持的联赛（{catalog.competitions.length} 个）</span>
        </label>
        {!allCompetitions && <label htmlFor="import-competitions">选择联赛
          <select id="import-competitions" multiple size={6} value={selectedCodes}
            onChange={(event) => setSelectedCodes(Array.from(event.target.selectedOptions, (option) => option.value))}>
            {catalog.competitions.map((competition) => <option key={competition.code} value={competition.code}>
              {competitionLabel(competition.code, competition.name)}（{competition.code}）
            </option>)}
          </select>
        </label>}
      </fieldset>
      <div className="import-year-range">
        <label htmlFor="import-start-year">开始年份
          <select id="import-start-year" value={startYear} onChange={(event) => setStartYear(Number(event.target.value))}>
            {years.map((year) => <option key={year} value={year}>{year}</option>)}
          </select>
        </label>
        <span aria-hidden="true">至</span>
        <label htmlFor="import-end-year">结束年份
          <select id="import-end-year" value={endYear} onChange={(event) => setEndYear(Number(event.target.value))}>
            {years.map((year) => <option key={year} value={year}>{year}</option>)}
          </select>
        </label>
      </div>
      <p className="import-note">欧洲联赛按 2000/01–2019/20 处理，日历年联赛按 2000–2020 处理。源站缺失的年份会单独记录，不会中断整批任务。</p>
      <button type="button" className="history-button import-submit" onClick={() => { void startImport() }} disabled={submitting || startYear > endYear}>
        {submitting ? '提交中…' : '开始导入'}
      </button>
    </div>}

    {job && <div className="import-progress" aria-live="polite">
      <div className="import-progress-heading">
        <strong>{statusText(job.status)}</strong>
        <span>{progressPercent(job)}%</span>
      </div>
      <div className="import-progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progressPercent(job)}>
        <span style={{ width: `${progressPercent(job)}%` }} />
      </div>
      <p>文件：{job.completedFiles + job.failedFiles} / {job.requestedFiles}；比赛：{job.importedMatches} 场；失败文件：{job.failedFiles}</p>
      {job.currentCompetitionCode && <p>当前联赛：{competitionLabel(job.currentCompetitionCode)}（{job.currentCompetitionCode}） · 赛季：{job.currentSeason}</p>}
      {job.errors.length > 0 && <p className="import-error">导入提示：{job.errors.slice(0, 5).map(importErrorLabel).join('、')}</p>}
      {terminalStatuses.has(job.status) && <button type="button" className="history-button" onClick={() => setJob(null)}>新建导入任务</button>}
    </div>}
  </section>
}
