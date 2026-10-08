import { FileSpreadsheet, FileCode } from 'lucide-react'

export default function DownloadButtons({ jobId }) {
  if (!jobId) return null

  const handleDownload = (format) => {
    const url = `/api/collect/${encodeURIComponent(jobId)}/export?format=${format}`
    const a = document.createElement('a')
    a.href = url
    a.download = `${jobId}.${format}`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  return (
    <div className="download-btn-group">
      <button
        onClick={() => handleDownload('csv')}
        className="download-btn"
        title="Download comments as CSV with UTF-8 BOM"
      >
        <FileSpreadsheet className="w-3.5 h-3.5" style={{ color: '#10a37f' }} />
        <span>Export CSV</span>
      </button>

      <button
        onClick={() => handleDownload('json')}
        className="download-btn"
        title="Download comments as JSON"
      >
        <FileCode className="w-3.5 h-3.5" style={{ color: '#3b82f6' }} />
        <span>Export JSON</span>
      </button>
    </div>
  )
}
