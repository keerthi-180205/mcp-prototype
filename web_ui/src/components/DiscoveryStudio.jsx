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
    <div className="max-w-5xl mx-auto w-full space-y-6">
      {/* Search Header */}
      <div className="p-6 rounded-2xl bg-slate-900/80 border border-slate-800 shadow-xl backdrop-blur-xl">
        <div className="flex items-center gap-2 mb-2 text-indigo-400 text-xs font-semibold uppercase tracking-wider">
          <SlidersHorizontal className="w-4 h-4" />
          <span>Discovery Studio</span>
        </div>
        <h3 className="text-xl font-bold text-white mb-1">Live Topic Intelligence</h3>
        <p className="text-xs text-slate-400 mb-4">
          Quickly discover trending media and top comments across social channels.
        </p>

        <form onSubmit={handleSearch} className="flex gap-2">
          <div className="flex-1 relative">
            <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Enter any topic or search phrase..."
              className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-slate-950/80 border border-slate-700/80 text-white placeholder-slate-500 text-sm focus:outline-none focus:border-indigo-500"
            />
          </div>
          <button
            type="submit"
            disabled={isLoading || !query.trim()}
            className="px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold transition-all shadow-md flex items-center gap-2 disabled:opacity-50"
          >
            {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <TrendingUp className="w-4 h-4" />}
            <span>Discover</span>
          </button>
        </form>
      </div>

      {/* Error Bubble */}
      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
          Error: {error}
        </div>
      )}

      {/* Results View */}
      {results && (
        <div className="p-6 rounded-2xl bg-slate-900/80 border border-slate-800 shadow-xl backdrop-blur-xl space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800 flex-wrap gap-2">
            <div>
              <h4 className="text-base font-bold text-white">
                {results.topic || query}
              </h4>
              <p className="text-xs text-slate-400">
                {results.summary_message || `Found ${comments.length} comments`}
              </p>
            </div>

            {/* Filter pills */}
            <div className="flex items-center gap-1.5 text-xs">
              <button
                onClick={() => setFilterPlatform('all')}
                className={`px-3 py-1 rounded-md font-medium transition-colors ${
                  filterPlatform === 'all'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                }`}
              >
                All
              </button>
              {['YouTube', 'Reddit', 'Twitter'].map(p => (
                <button
                  key={p}
                  onClick={() => setFilterPlatform(p)}
                  className={`px-3 py-1 rounded-md font-medium transition-colors ${
                    filterPlatform === p
                      ? 'bg-indigo-600 text-white'
                      : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {/* Table */}
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
                {filteredComments.length === 0 ? (
                  <tr>
                    <td colSpan="5" className="py-8 text-center text-slate-500">
                      No comments found for this selection.
                    </td>
                  </tr>
                ) : (
                  filteredComments.map((c, i) => (
                    <tr key={i} className="hover:bg-slate-800/30 transition-colors">
                      <td className="py-2.5 px-3 font-semibold uppercase text-slate-400">
                        {c.platform || 'General'}
                      </td>
                      <td className="py-2.5 px-3 font-medium text-slate-200">
                        {c.username || c.user_id || 'User'}
                      </td>
                      <td className="py-2.5 px-3 text-slate-200 max-w-sm break-words">
                        {c.comment || c.comment_text}
                      </td>
                      <td className="py-2.5 px-3 text-rose-400 font-medium">
                        {c.likes ?? 0}
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        {c.link || c.post_url ? (
                          <a
                            href={c.link || c.post_url}
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
        </div>
      )}
    </div>
  )
}
