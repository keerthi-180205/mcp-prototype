import { FileSpreadsheet, FileCode } from 'lucide-react'

export default function DownloadButtons({ jobId }) {
  if (!jobId) return null

  const handleDownload = (format) => {
    // Direct browser navigation triggers the attachment download
    const url = `/api/collect/${encodeURIComponent(jobId)}/export?format=${format}`
    const a = document.createElement('a')
    a.href = url
    a.download = `${jobId}.${format}`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => handleDownload('csv')}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 border border-emerald-500/30 text-xs font-semibold transition-all shadow-sm"
        title="Download comments as CSV with UTF-8 BOM"
      >
        <FileSpreadsheet className="w-3.5 h-3.5" />
        <span>Export CSV</span>
      </button>

      <button
        onClick={() => handleDownload('json')}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-600/20 hover:bg-sky-600/30 text-sky-300 border border-sky-500/30 text-xs font-semibold transition-all shadow-sm"
        title="Download comments as JSON"
      >
        <FileCode className="w-3.5 h-3.5" />
        <span>Export JSON</span>
      </button>
    </div>
  )
}
