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
    <div className="llm-card results-card">
      {/* Header */}
      <div className="card-header-row">
        <div>
          <div className="card-title-group">
            <Sparkles className="w-4 h-4" style={{ color: '#10a37f' }} />
            <h4 className="card-title">Collection Results</h4>
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
            '{topic}' — {total_comments.toLocaleString()} comments collected ({status})
          </div>
        </div>
        <DownloadButtons jobId={job_id} />
      </div>

      {/* Counts per Platform */}
      <div className="results-counts-row">
        <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Counts:</span>
        {Object.entries(counts_per_platform).map(([plat, cnt]) => (
          <span key={plat} className="count-pill">
            <span style={{ textTransform: 'uppercase', marginRight: '4px' }}>{plat}:</span>
            <strong>{cnt.toLocaleString()}</strong>
          </span>
        ))}
      </div>

      {/* Below-Target Notices */}
      {hasBelowTarget && (
        <div className="card-notice-box">
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
            <AlertTriangle className="w-4 h-4" style={{ color: '#fbbf24' }} />
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
              <p key={plat}>
                • <strong style={{ textTransform: 'uppercase' }}>{plat}</strong>: collected {info.collected} / {info.target} ({reasonText})
              </p>
            )
          })}
        </div>
      )}

      {/* Top Comments Highlights */}
      {Object.keys(top_comments).length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <TrendingUp className="w-3.5 h-3.5" style={{ color: '#10a37f' }} /> Top Engaging Comments
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {Object.entries(top_comments).map(([plat, comments]) => (
              <div key={plat} style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {comments.slice(0, 2).map((c, i) => (
                  <div
                    key={i}
                    style={{
                      background: 'var(--bg-card-subtle)',
                      border: '1px solid var(--border-subtle)',
                      borderRadius: '6px',
                      padding: '8px 12px',
                      fontSize: '12px'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-muted)', marginBottom: '4px' }}>
                      <span style={{ fontWeight: 600, color: '#ececec', textTransform: 'uppercase' }}>
                        {c.platform || plat} • {c.username ? `@${c.username.replace(/^@/, '')}` : (c.user_id ? `user_${c.user_id}` : 'Anonymous')}
                      </span>
                      <span style={{ color: '#ef4444', display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <Heart className="w-3 h-3" /> {c.likes || 0}
                      </span>
                    </div>
                    <p style={{ color: '#d1d5db' }}>{c.comment}</p>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Platform Filter Tabs */}
      <div className="results-filter-nav">
        <div className="filter-btn-group">
          <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px', color: 'var(--text-muted)', marginRight: '6px' }}>
            <Filter className="w-3.5 h-3.5" /> Filter:
          </span>
          <button
            onClick={() => handleFilterChange('all')}
            className={`filter-pill ${activeFilter === 'all' ? 'active' : ''}`}
          >
            All Platforms
          </button>
          {platformKeys.map(plat => (
            <button
              key={plat}
              onClick={() => handleFilterChange(plat)}
              className={`filter-pill ${activeFilter === plat ? 'active' : ''}`}
              style={{ textTransform: 'uppercase' }}
            >
              {plat}
            </button>
          ))}
        </div>

        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
          Page {currentPage} of {totalPages}
        </div>
      </div>

      {/* Paginated Comments Table */}
      <div className="llm-table-wrap">
        <table className="llm-data-table">
          <thead>
            <tr>
              <th>Platform</th>
              <th>User</th>
              <th>Comment</th>
              <th>Likes</th>
              <th style={{ textAlign: 'right' }}>Link</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan="5" style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>
                  Loading comments...
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan="5" style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>
                  No comments found for this view.
                </td>
              </tr>
            ) : (
              rows.map((row, idx) => (
                <tr key={idx}>
                  <td style={{ fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                    {row.platform}
                  </td>
                  <td className="td-user">
                    {row.username ? `@${row.username.replace(/^@/, '')}` : (row.user_id ? `user_${row.user_id}` : 'Anonymous')}
                  </td>
                  <td className="td-comment">
                    {row.comment}
                  </td>
                  <td className="td-likes">
                    {row.likes ?? 0}
                  </td>
                  <td className="td-link" style={{ textAlign: 'right' }}>
                    {row.post_url ? (
                      <a href={row.post_url} target="_blank" rel="noreferrer">
                        <span>Post</span>
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    ) : (
                      <span style={{ color: '#555' }}>-</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      <div className="pagination-footer">
        <span>Showing {rows.length} comments</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            onClick={handlePrevPage}
            disabled={currentPage <= 1 || isLoading}
            className="page-btn"
          >
            <ChevronLeft className="w-3.5 h-3.5" style={{ display: 'inline', verticalAlign: 'middle' }} /> Prev
          </button>
          <span>
            {currentPage} / {totalPages}
          </span>
          <button
            onClick={handleNextPage}
            disabled={currentPage >= totalPages || isLoading}
            className="page-btn"
          >
            Next <ChevronRight className="w-3.5 h-3.5" style={{ display: 'inline', verticalAlign: 'middle' }} />
          </button>
        </div>
      </div>
    </div>
  )
}
