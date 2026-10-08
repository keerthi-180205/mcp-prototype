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
        const res = await fetch(`/api/collect/${job_id}/status`)
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
          // Retry polling even if temporary glitch
          timerId = setTimeout(fetchStatus, 3000)
        }
      }
    }

    // If initial card is not already terminal, start polling
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

  // Calculate overall target and collected
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
        return <span className="px-2 py-0.5 rounded text-xs bg-emerald-500/20 text-emerald-300 font-medium">Done</span>
      case 'harvesting':
        return (
          <span className="flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-sky-500/20 text-sky-300 font-medium animate-pulse">
            <Radio className="w-3 h-3 text-sky-400" /> Harvesting
          </span>
        )
      case 'discovering':
        return (
          <span className="flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-indigo-500/20 text-indigo-300 font-medium">
            <Loader2 className="w-3 h-3 animate-spin text-indigo-400" /> Discovering
          </span>
        )
      case 'failed':
        return <span className="px-2 py-0.5 rounded text-xs bg-rose-500/20 text-rose-300 font-medium">Failed</span>
      case 'skipped':
        return <span className="px-2 py-0.5 rounded text-xs bg-slate-700/50 text-slate-400 font-medium">Skipped</span>
      default:
        return <span className="px-2 py-0.5 rounded text-xs bg-slate-800 text-slate-400 font-medium">Pending</span>
    }
  }

  return (
    <div className="mt-3 p-4 rounded-xl bg-slate-900/90 border border-slate-800 shadow-xl max-w-xl text-slate-100">
      <div className="flex items-center justify-between pb-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          {isFinished ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-400" />
          ) : (
            <Loader2 className="w-5 h-5 text-sky-400 animate-spin" />
          )}
          <div>
            <h4 className="font-semibold text-sm text-white">
              Job {job_id} {isFinished ? `(${status})` : 'in progress'}
            </h4>
            <p className="text-xs text-slate-400">{jobState.topic}</p>
          </div>
        </div>
        <span
          className={`px-2.5 py-0.5 rounded-full text-xs font-semibold capitalize ${
            status === 'completed'
              ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
              : status === 'partial'
              ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
              : status === 'failed'
              ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
              : 'bg-sky-500/20 text-sky-300 border border-sky-500/30'
          }`}
        >
          {status}
        </span>
      </div>

      {/* Overall Progress Bar */}
      <div className="py-3">
        <div className="flex justify-between text-xs font-medium text-slate-300 mb-1.5">
          <span>Total Progress</span>
          <span>{totalCollected.toLocaleString()} / {totalTarget.toLocaleString()} comments ({progressPct}%)</span>
        </div>
        <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
          <div
            className={`h-full transition-all duration-500 ${
              isFinished ? 'bg-emerald-500' : 'bg-gradient-to-r from-sky-500 to-indigo-500'
            }`}
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Per-Platform Breakdown */}
      <div className="space-y-2 py-2">
        {Object.entries(platforms).map(([plat, pr]) => {
          const collected = pr.comments_collected || 0
          const target = pr.target || 0
          const posts = pr.posts_processed || 0
          return (
            <div
              key={plat}
              className="p-2.5 rounded-lg bg-slate-800/60 border border-slate-700/50 flex items-center justify-between text-xs"
            >
              <div className="flex items-center gap-2">
                <span className="font-semibold uppercase text-slate-200">{plat}</span>
                <span className="text-slate-400">({posts} posts searched)</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="font-medium text-slate-200">
                  {collected.toLocaleString()} / {target.toLocaleString()}
                </span>
                {getStatusBadge(pr.status)}
              </div>
            </div>
          )
        })}
      </div>

      {error && (
        <div className="mt-2 text-xs text-rose-400 flex items-center gap-1">
          <AlertCircle className="w-3.5 h-3.5" />
          <span>Polling error: {error}</span>
        </div>
      )}

      {/* Completion CTA */}
      {isFinished && onShowResults && (
        <div className="mt-3 pt-3 border-t border-slate-800 flex justify-end">
          <button
            onClick={() => onShowResults(job_id)}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs transition-all shadow-md"
          >
            <BarChart2 className="w-4 h-4" />
            <span>View Full Results</span>
          </button>
        </div>
      )}
    </div>
  )
}
