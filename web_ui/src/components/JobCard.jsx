import { useState, useEffect } from 'react'
import { Loader2, CheckCircle2, AlertCircle, BarChart2, Radio } from 'lucide-react'

const TERMINAL_STATUSES = new Set(['completed', 'partial', 'failed', 'interrupted'])

export default function JobCard({ card, onShowResults }) {
  const { job_id } = card
  const [jobState, setJobState] = useState(card)
  const [error, setError] = useState(null)

  useEffect(() => {
    let isMounted = true
    let timerId = null

    const fetchStatus = async () => {
      try {
        const res = await fetch(`/api/collect/${encodeURIComponent(job_id)}/status`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        if (isMounted) {
          setJobState(data)
          if (!TERMINAL_STATUSES.has(data.status)) {
            timerId = setTimeout(fetchStatus, 2000)
          }
        }
      } catch (err) {
        if (isMounted) {
          setError(err.message)
          timerId = setTimeout(fetchStatus, 3000)
        }
      }
    }

    if (!TERMINAL_STATUSES.has(card.status)) {
      timerId = setTimeout(fetchStatus, 2000)
    }

    return () => {
      isMounted = false
      if (timerId) clearTimeout(timerId)
    }
  }, [job_id, card.status])

  const status = jobState.status || 'running'
  const isFinished = TERMINAL_STATUSES.has(status)
  const platforms = jobState.platforms || {}

  let totalTarget = 0
  let totalCollected = 0
  Object.values(platforms).forEach(pr => {
    totalTarget += (pr.target || 0)
    totalCollected += (pr.comments_collected || 0)
  })
  const progressPct = totalTarget > 0 ? Math.min(100, Math.round((totalCollected / totalTarget) * 100)) : 0

  const getStatusBadge = (s) => {
    switch (s) {
      case 'done':
        return <span className="stage-badge done">Done</span>
      case 'harvesting':
        return (
          <span className="stage-badge harvesting" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Radio className="w-3 h-3" /> Harvesting
          </span>
        )
      case 'discovering':
        return (
          <span className="stage-badge discovering" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Loader2 className="w-3 h-3 animate-spin" /> Discovering
          </span>
        )
      case 'failed':
        return <span className="stage-badge failed">Failed</span>
      default:
        return <span className="stage-badge" style={{ background: '#262626', color: '#999' }}>{s || 'Pending'}</span>
    }
  }

  const getStatusBadgeClass = () => {
    if (status === 'completed') return 'badge-completed'
    if (status === 'running') return 'badge-running'
    if (status === 'partial') return 'badge-partial'
    return 'badge-pending'
  }

  return (
    <div className="llm-card job-card">
      <div className="card-header-row">
        <div className="card-title-group">
          {isFinished ? (
            <CheckCircle2 className="w-5 h-5" style={{ color: '#10a37f' }} />
          ) : (
            <Loader2 className="w-5 h-5 animate-spin" style={{ color: '#3b82f6' }} />
          )}
          <div>
            <h4 className="card-title">
              Job #{job_id} {isFinished ? `(${status})` : '• In Progress'}
            </h4>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              {jobState.topic}
            </div>
          </div>
        </div>
        <span className={`card-status-badge ${getStatusBadgeClass()}`}>
          {status}
        </span>
      </div>

      {/* Overall Progress */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
          <span>Overall Collection Progress</span>
          <span>
            <strong style={{ color: '#fff' }}>{totalCollected.toLocaleString()}</strong> / {totalTarget.toLocaleString()} comments ({progressPct}%)
          </span>
        </div>
        <div className="progress-track-outer">
          <div
            className="progress-track-fill"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Per-Platform Breakdown */}
      <div className="platforms-progress-list">
        {Object.entries(platforms).map(([plat, pr]) => {
          const collected = pr.comments_collected || 0
          const target = pr.target || 0
          const posts = pr.posts_processed || 0
          return (
            <div key={plat} className="platform-progress-item">
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="platform-tag">{plat}</span>
                <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
                  ({posts} posts searched)
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '13px' }}>
                  {collected.toLocaleString()} / {target.toLocaleString()}
                </span>
                {getStatusBadge(pr.status)}
              </div>
            </div>
          )
        })}
      </div>

      {error && (
        <div style={{ color: '#ef4444', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <AlertCircle className="w-4 h-4" />
          <span>Status connection error: {error}</span>
        </div>
      )}

      {/* Completion CTA */}
      {isFinished && onShowResults && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: '6px' }}>
          <button
            onClick={() => onShowResults(job_id)}
            className="btn-confirm-start"
            style={{ flex: 'none', padding: '8px 16px', fontSize: '13px' }}
          >
            <BarChart2 className="w-4 h-4" />
            <span>View Full Results</span>
          </button>
        </div>
      )}
    </div>
  )
}
