import { useEffect, useMemo, useRef, useState } from 'react'
import { Search } from 'lucide-react'

import { competitionLabel } from './display'
import type { MatchFilterOptions } from './types'

export interface HistoryFilterValues {
  competition: string
  season: string
  team: string
  startDate: string
  endDate: string
}

interface HistoryFiltersProps extends HistoryFilterValues {
  options: MatchFilterOptions
  onSearch: (values: HistoryFilterValues) => void
  onClear: () => void
}

export default function HistoryFilters(props: HistoryFiltersProps) {
  const { options, onSearch, onClear } = props
  const [draft, setDraft] = useState<HistoryFilterValues>(() => ({
    competition: props.competition, season: props.season, team: props.team,
    startDate: props.startDate, endDate: props.endDate,
  }))
  const [dateError, setDateError] = useState(false)
  const teamInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setDraft({
      competition: props.competition, season: props.season, team: props.team,
      startDate: props.startDate, endDate: props.endDate,
    })
    setDateError(false)
  }, [props.competition, props.season, props.team, props.startDate, props.endDate])

  const competitions = useMemo(() => {
    const byCode = new Map(options.competitions.map((item) => [item.code, item]))
    if (draft.competition && !byCode.has(draft.competition)) {
      byCode.set(draft.competition, { code: draft.competition, name: competitionLabel(draft.competition) })
    }
    return [...byCode.values()]
  }, [draft.competition, options.competitions])

  function update(key: keyof HistoryFilterValues, value: string) {
    setDraft((current) => ({ ...current, [key]: value }))
    if (key === 'startDate' || key === 'endDate') setDateError(false)
  }

  function submit() {
    if (draft.startDate && draft.endDate && draft.startDate > draft.endDate) {
      setDateError(true)
      return
    }
    setDateError(false)
    onSearch({ ...draft, team: draft.team.trim() })
  }

  function clearAll() {
    setDraft({ competition: '', season: '', team: '', startDate: '', endDate: '' })
    setDateError(false)
    onClear()
  }

  return <form className="history-filters" role="search" aria-label="筛选历史比赛"
    onSubmit={(event) => { event.preventDefault(); submit() }}>
    <label htmlFor="history-competition">联赛
      <select id="history-competition" value={draft.competition} onChange={(event) => update('competition', event.target.value)}>
        <option value="">全部联赛</option>
        {competitions.map((item) => <option key={item.code} value={item.code}>
          {competitionLabel(item.code, item.name)}（{item.code}）
        </option>)}
      </select>
    </label>
    <label htmlFor="history-season">赛季
      <select id="history-season" value={draft.season} onChange={(event) => update('season', event.target.value)}>
        <option value="">全部赛季</option>
        {[...new Set([...options.seasons, ...(draft.season ? [draft.season] : [])])].map((value) => <option key={value} value={value}>{value}</option>)}
      </select>
    </label>
    <label htmlFor="history-start-date">开始日期
      <input id="history-start-date" type="date" value={draft.startDate} max={draft.endDate || undefined}
        onChange={(event) => update('startDate', event.target.value)} />
    </label>
    <label htmlFor="history-end-date">结束日期
      <input id="history-end-date" type="date" value={draft.endDate} min={draft.startDate || undefined}
        onChange={(event) => update('endDate', event.target.value)} />
    </label>
    <div className="history-team-field">
      <label htmlFor="history-team">球队</label>
      <div className="history-search-input">
        <input id="history-team" type="search" ref={teamInputRef} value={draft.team}
          placeholder="搜索主队或客队" autoComplete="off" onChange={(event) => update('team', event.target.value)} />
        {draft.team && <button type="button" className="history-clear-search" aria-label="清除球队搜索"
          onClick={() => { update('team', ''); teamInputRef.current?.focus() }}>×</button>}
      </div>
    </div>
    <div className="history-filter-actions">
      <button type="submit" className="history-button history-search-button"><Search aria-hidden="true" size={17} />搜索</button>
      <button type="button" className="history-button" onClick={clearAll}>清除筛选</button>
    </div>
    {dateError && <p className="history-filter-error" role="alert">开始日期不能晚于结束日期</p>}
  </form>
}
