import { useState } from 'react'
import {
  Search,
  Loader2,
  ExternalLink,
  TrendingUp,
  SlidersHorizontal
} from 'lucide-react'

export default function DiscoveryStudio() {
  const [query, setQuery] = useState('Asian Games 2026')
  const [isLoading, setIsLoading] = useState(false)
  const [results, setResults] = useState(null)
  const [error, setError] = useState(null)
  const [filterPlatform, setFilterPlatform] = useState('all')

  const handleSearch = async (e, customQuery) => {
    if (e) e.preventDefault()
    const q = (customQuery !== undefined ? customQuery : query).trim()
    if (!q) return

    if (customQuery) setQuery(customQuery)
    setIsLoading(true)
    setError(null)

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: q,
          description: q,
          field: q,
          connected_platforms: ['youtube', 'reddit', 'twitter']
        })
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setResults(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setIsLoading(false)
    }
  }

  const comments = results?.matched_comments || results?.comments || []
  const filteredComments = filterPlatform === 'all'
    ? comments
    : comments.filter(c => (c.platform || '').toLowerCase().includes(filterPlatform.toLowerCase()))

  return (
    <div className="discovery-view">
      <div className="discovery-inner">
        {/* Search Header */}
        <div className="discovery-search-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#10a37f', fontSize: '12px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            <SlidersHorizontal className="w-4 h-4" />
            <span>Discovery Studio</span>
          </div>

          <div>
            <h3 style={{ fontSize: '20px', fontWeight: 700, color: '#fff', marginBottom: '4px' }}>
              Direct Topic Discovery
            </h3>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              Search and filter trending social comments directly using the multi-platform MCP engine.
            </p>
          </div>

          <form onSubmit={handleSearch} className="discovery-input-row">
            <div style={{ position: 'relative', flex: 1, display: 'flex', alignItems: 'center' }}>
              <Search className="w-4 h-4" style={{ position: 'absolute', left: '12px', color: 'var(--text-muted)' }} />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Enter any topic or search phrase..."
                className="discovery-input"
                style={{ paddingLeft: '38px' }}
              />
            </div>
            <button
              type="submit"
              disabled={isLoading || !query.trim()}
              className="discovery-btn-search"
            >
              {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <TrendingUp className="w-4 h-4" />}
              <span>Discover</span>
            </button>
          </form>
        </div>

        {/* Error Bubble */}
        {error && (
          <div className="card-notice-box" style={{ background: 'rgba(239, 68, 68, 0.1)', borderColor: 'rgba(239, 68, 68, 0.3)', color: '#fca5a5' }}>
            Error: {error}
          </div>
        )}

        {/* Results View */}
        {results && (
          <div className="llm-card">
            <div className="card-header-row">
              <div>
                <h4 className="card-title">
                  {results.topic || query}
                </h4>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  {results.summary_message || `Found ${comments.length} comments`}
                </div>
              </div>

              {/* Filter pills */}
              <div className="filter-btn-group">
                <button
                  onClick={() => setFilterPlatform('all')}
                  className={`filter-pill ${filterPlatform === 'all' ? 'active' : ''}`}
                >
                  All
                </button>
                {['YouTube', 'Reddit', 'Twitter'].map(p => (
                  <button
                    key={p}
                    onClick={() => setFilterPlatform(p)}
                    className={`filter-pill ${filterPlatform === p ? 'active' : ''}`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>

            {/* Table */}
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
                  {filteredComments.length === 0 ? (
                    <tr>
                      <td colSpan="5" style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>
                        No comments found for this selection.
                      </td>
                    </tr>
                  ) : (
                    filteredComments.map((c, i) => (
                      <tr key={i}>
                        <td style={{ fontWeight: 600, textTransform: 'uppercase', color: 'var(--text-muted)' }}>
                          {c.platform || 'General'}
                        </td>
                        <td className="td-user">
                          {c.username || c.user_id || 'User'}
                        </td>
                        <td className="td-comment">
                          {c.comment || c.comment_text}
                        </td>
                        <td className="td-likes">
                          {c.likes ?? 0}
                        </td>
                        <td className="td-link" style={{ textAlign: 'right' }}>
                          {c.link || c.post_url ? (
                            <a
                              href={c.link || c.post_url}
                              target="_blank"
                              rel="noreferrer"
                            >
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
          </div>
        )}
      </div>
    </div>
  )
}
