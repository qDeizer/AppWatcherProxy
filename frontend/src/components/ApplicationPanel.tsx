import { ChevronDown, ChevronRight, Layers3, Monitor, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { ApplicationSummary } from '../types'

interface ApplicationPanelProps {
  applications: ApplicationSummary[]
  selected: Set<string>
  onToggle: (name: string) => void
  totalSessions: number
}

export function ApplicationPanel({ applications, selected, onToggle, totalSessions }: ApplicationPanelProps) {
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const visible = useMemo(() => applications.filter((app) => app.name.toLowerCase().includes(query.toLowerCase())), [applications, query])
  const toggleExpanded = (name: string) => setExpanded((current) => {
    const next = new Set(current)
    if (next.has(name)) {
      next.delete(name)
    } else {
      next.add(name)
    }
    return next
  })
  return (
    <aside className="applications-panel panel">
      <div className="panel-heading"><div><Layers3 size={16} /><h2>Applications</h2></div><span>{applications.length}</span></div>
      <label className="panel-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Uygulama ara" /></label>
      <div className="application-list">
        <button className={`application-row ${selected.size === 0 ? 'selected' : ''}`} onClick={() => selected.forEach(onToggle)}>
          <span className="disclosure-spacer" /><Monitor size={15} /><span className="app-name">All</span><span className="count">{totalSessions}</span>
        </button>
        {visible.map((app) => {
          const isExpanded = expanded.has(app.name)
          return <div key={`${app.name}-${app.executable_path}`}>
            <div className={`application-row ${selected.has(app.name) ? 'selected' : ''}`}>
              <button className="disclosure" onClick={() => toggleExpanded(app.name)} aria-label={`${app.name} süreçlerini ${isExpanded ? 'daralt' : 'genişlet'}`}>
                {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>
              <button className="app-select" onClick={() => onToggle(app.name)}><span className="app-dot">{app.name.slice(0, 1).toUpperCase()}</span><span className="app-name">{app.name}</span><span className="count">{app.session_count}</span></button>
            </div>
            {isExpanded ? <div className="process-list">{app.processes.map((process) => <button key={process.pid} onClick={() => onToggle(app.name)}><span>PID</span> {process.pid}<small>{process.name}</small></button>)}</div> : null}
          </div>
        })}
        {!visible.length && applications.length ? <p className="small-empty">Eşleşen uygulama yok.</p> : null}
      </div>
    </aside>
  )
}
