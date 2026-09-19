import { useEffect, useRef, useState } from 'react'
import type { MatchFilterOptions } from './types'
import { competitionLabel } from './display'

interface HistoryFiltersProps {
  competition: string
  season: string
  team: string
  options: MatchFilterOptions
  onCompetitionChange: (value: string) => void
  onSeasonChange: (value: string) => void
  onTeamChange: (value: string) => void
  onClear: () => void
}

export default function HistoryFilters({ competition, season, team, options, onCompetitionChange, onSeasonChange, onTeamChange, onClear }: HistoryFiltersProps) {
  const [draft, setDraft] = useState(team)
  const [composing, setComposing] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => setDraft(team), [team])
  useEffect(() => {
    // 输入法候选词尚未确认时，不提交临时拼音或半成品文本。
    if (composing || draft === team) return
    const timer = window.setTimeout(() => onTeamChange(draft.trim()), 300)
    return () => window.clearTimeout(timer)
  }, [draft, team, composing, onTeamChange])

  function clearTeam() {
    setDraft('')
    setComposing(false)
    onTeamChange('')
    inputRef.current?.focus()
  }

  return <div className="history-filters" role="search" aria-label="筛选历史比赛">
    <label htmlFor="history-competition">联赛
      <select id="history-competition" value={competition} onChange={(event) => onCompetitionChange(event.target.value)}>
        <option value="">全部联赛</option>
        {[...new Set([...options.competitions, ...(competition ? [competition] : [])])].map((value) => <option key={value} value={value}>
          {competitionLabel(value)}（{value}）
        </option>)}
      </select>
    </label>
    <label htmlFor="history-season">赛季
      <select id="history-season" value={season} onChange={(event) => onSeasonChange(event.target.value)}>
        <option value="">全部赛季</option>
        {[...new Set([...options.seasons, ...(season ? [season] : [])])].map((value) => <option key={value} value={value}>{value}</option>)}
      </select>
    </label>
    <div className="history-team-field">
      <label htmlFor="history-team">球队</label>
      <div className="history-search-input">
        <input id="history-team" type="search" ref={inputRef} value={draft} placeholder="搜索主队或客队" autoComplete="off"
          onChange={(event) => {
            setDraft(event.target.value)
            if (!event.target.value && !composing && !(event.nativeEvent as InputEvent).isComposing) onTeamChange('')
          }}
          onCompositionStart={() => setComposing(true)}
          onCompositionEnd={(event) => { setComposing(false); setDraft(event.currentTarget.value) }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.nativeEvent.isComposing && !composing) {
              event.preventDefault()
              onTeamChange(draft.trim())
            }
          }} />
        {draft && <button type="button" className="history-clear-search" aria-label="清除球队搜索" onClick={clearTeam}>×</button>}
      </div>
    </div>
    <button type="button" className="history-button" disabled={!competition && !season && !draft && !team}
      onClick={() => { setDraft(''); setComposing(false); onClear(); inputRef.current?.focus() }}>清除筛选</button>
  </div>
}
