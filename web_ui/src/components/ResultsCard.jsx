import { useState } from 'react'
import {
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  Filter,
  AlertTriangle,
  Heart,
  TrendingUp,
  Sparkles
} from 'lucide-react'
import DownloadButtons from './DownloadButtons'

export default function ResultsCard({ card }) {
  const {
    job_id,
    topic,
    status,
    counts_per_platform = {},
    total_comments = 0,
    below_target = {},
    top_comments = {},
    rows: initialRows = [],
    page: initialPage = 1,
    page_size = 25,
    total_pages: initialTotalPages = 1,
    filter_platform = null
  } = card

  const [activeFilter, setActiveFilter] = useState(filter_platform || 'all')
  const [currentPage, setCurrentPage] = useState(initialPage)
  const [totalPages, setTotalPages] = useState(initialTotalPages)
  const [rows, setRows] = useState(initialRows)
  const [isLoading, setIsLoading] = useState(false)

  const fetchPage = async (pageNumber, platform) => {
    setIsLoading(true)
    try {
      const platParam = platform && platform !== 'all' ? `&platform=${encodeURIComponent(platform)}` : ''
      const res = await fetch(`/api/collect/${encodeURIComponent(job_id)}/results?page=${pageNumber}&page_size=${page_size}${platParam}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setRows(data.rows || [])
      setCurrentPage(data.page || pageNumber)
      setTotalPages(data.total_pages || 1)
    } catch (err) {
      console.error('Failed to paginate results:', err)
    } finally {
      setIsLoading(false)
    }
  }

  const handleFilterChange = (platform) => {
    setActiveFilter(platform)
    setCurrentPage(1)
    fetchPage(1, platform)
  }

  const handleNextPage = () => {
    if (currentPage < totalPages) {
      const nextPage = currentPage + 1
      setCurrentPage(nextPage)
      fetchPage(nextPage, activeFilter)
    }
  }

  const handlePrevPage = () => {
    if (currentPage > 1) {
      const prevPage = currentPage - 1
      setCurrentPage(prevPage)
      fetchPage(prevPage, activeFilter)
    }
  }

  const platformKeys = Object.keys(counts_per_platform)
  const hasBelowTarget = Object.keys(below_target).length > 0

  return (
    <div className="mt-3 p-4 rounded-xl bg-slate-900/90 border border-slate-800 shadow-xl max-w-2xl text-slate-100">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-slate-800">
        <div>
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-emerald-400" />
            <h4 className="font-semibold text-base text-white">Collection Results</h4>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            '{topic}' — {total_comments.toLocaleString()} comments collected ({status})
          </p>
        </div>
        <DownloadButtons jobId={job_id} />
      </div>

      {/* Counts per Platform Badges */}
      <div className="flex flex-wrap items-center gap-2 py-3 border-b border-slate-800/60">
        <span className="text-xs font-medium text-slate-400">Collected:</span>
        {Object.entries(counts_per_platform).map(([plat, cnt]) => (
          <span
            key={plat}
            className="px-2.5 py-1 rounded-md text-xs font-semibold uppercase bg-slate-800 border border-slate-700 text-slate-200"
          >
            {plat}: <span className="text-emerald-400">{cnt.toLocaleString()}</span>
          </span>
        ))}
      </div>

      {/* Below-Target Notices */}
      {hasBelowTarget && (
        <div className="my-3 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs text-amber-300 space-y-1.5">
          <div className="flex items-center gap-1.5 font-semibold text-amber-200">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>Below-Target Explanation</span>
          </div>
          {Object.entries(below_target).map(([plat, info]) => {
            let reasonText = info.reason || 'ran out of matching posts before reaching target'
            if (info.reason === 'no_more_candidates') {
              reasonText = 'ran out of matching posts before reaching the target'
            } else if (info.reason === 'budget_cap_reached') {
              reasonText = 'reached cost budget cap'
            } else if (info.reason === 'error' && info.error) {
              reasonText = `stopped due to error: ${info.error}`
            }
            return (
              <p key={plat} className="leading-relaxed">
                • <strong className="uppercase">{plat}</strong>: collected {info.collected} / {info.target} ({reasonText})
              </p>
            )
          })}
        </div>
      )}

      {/* Top Comments Highlights */}
      {Object.keys(top_comments).length > 0 && (
        <div className="my-3 space-y-2">
          <h5 className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
            <TrendingUp className="w-3.5 h-3.5 text-indigo-400" /> Top Engaging Comments
          </h5>
          <div className="space-y-2">
            {Object.entries(top_comments).map(([plat, comments]) => (
              <div key={plat} className="space-y-1.5">
                {comments.slice(0, 2).map((c, i) => (
                  <div
                    key={i}
                    className="p-2.5 rounded-lg bg-slate-800/50 border border-slate-700/40 text-xs flex flex-col gap-1"
                  >
                    <div className="flex items-center justify-between text-slate-400">
                      <div className="flex items-center gap-1.5 font-medium">
                        <span className="uppercase text-slate-300 font-semibold">{c.platform || plat}</span>
                        <span>•</span>
                        <span className="text-slate-300">{c.username || c.user_id}</span>
                      </div>
                      <div className="flex items-center gap-1 text-rose-400">
                        <Heart className="w-3 h-3" />
                        <span>{c.likes || 0}</span>
                      </div>
                    </div>
                    <p className="text-slate-200 leading-snug">{c.comment}</p>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Platform Filter Tabs */}
      <div className="mt-4 mb-2 flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-1 text-xs">
          <Filter className="w-3.5 h-3.5 text-slate-400 mr-1" />
          <button
            onClick={() => handleFilterChange('all')}
            className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
              activeFilter === 'all'
                ? 'bg-indigo-600 text-white shadow-sm'
                : 'bg-slate-800 hover:bg-slate-700 text-slate-300'
            }`}
          >
            All
          </button>
          {platformKeys.map(plat => (
            <button
              key={plat}
              onClick={() => handleFilterChange(plat)}
              className={`px-2.5 py-1 rounded-md font-medium uppercase transition-colors ${
                activeFilter === plat
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'bg-slate-800 hover:bg-slate-700 text-slate-300'
              }`}
            >
              {plat}
            </button>
          ))}
        </div>

        <div className="text-xs text-slate-400">
          Page {currentPage} of {totalPages}
        </div>
      </div>

      {/* Paginated Comments Table */}
      <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/40">
        <table className="w-full text-left text-xs text-slate-300">
          <thead className="bg-slate-800/80 uppercase font-semibold text-slate-400 border-b border-slate-700">
            <tr>
              <th className="py-2.5 px-3">Platform</th>
              <th className="py-2.5 px-3">User</th>
              <th className="py-2.5 px-3">Comment</th>
              <th className="py-2.5 px-3">Likes</th>
              <th className="py-2.5 px-3 text-right">Link</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/50">
            {isLoading ? (
              <tr>
                <td colSpan="5" className="py-8 text-center text-slate-400">
                  Loading comments...
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan="5" className="py-8 text-center text-slate-500">
                  No comments found for this view.
                </td>
              </tr>
            ) : (
              rows.map((row, idx) => (
                <tr key={idx} className="hover:bg-slate-800/30 transition-colors">
                  <td className="py-2.5 px-3 font-semibold uppercase text-slate-400">
                    {row.platform}
                  </td>
                  <td className="py-2.5 px-3">
                    <span className="font-medium text-slate-200">{row.username || row.user_id}</span>
                  </td>
                  <td className="py-2.5 px-3 text-slate-200 max-w-xs break-words">
                    {row.comment}
                  </td>
                  <td className="py-2.5 px-3 text-rose-400 font-medium whitespace-nowrap">
                    {row.likes ?? 0}
                  </td>
                  <td className="py-2.5 px-3 text-right whitespace-nowrap">
                    {row.post_url ? (
                      <a
                        href={row.post_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-sky-400 hover:text-sky-300 hover:underline"
                      >
                        <span>Post</span>
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    ) : (
                      <span className="text-slate-600">-</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Controls */}
      <div className="mt-3 flex items-center justify-between text-xs text-slate-400">
        <span>Showing {rows.length} comments</span>
        <div className="flex items-center gap-2">
          <button
            onClick={handlePrevPage}
            disabled={currentPage <= 1 || isLoading}
            className="flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed text-slate-300"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
            <span>Prev</span>
          </button>
          <span>
            {currentPage} / {totalPages}
          </span>
          <button
            onClick={handleNextPage}
            disabled={currentPage >= totalPages || isLoading}
            className="flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed text-slate-300"
          >
            <span>Next</span>
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
}
