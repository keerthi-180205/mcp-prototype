import { useState, useEffect } from 'react'
import { CheckCircle2, AlertCircle } from 'lucide-react'

export default function PlatformBadges() {
  const [platforms, setPlatforms] = useState({
    youtube: { available: false, reason: 'Checking status...' },
    reddit: { available: false, reason: 'Checking status...' },
    x: { available: false, reason: 'Checking status...' },
    instagram: { available: false, reason: 'Checking status...' }
  })

  useEffect(() => {
    let isMounted = true
    const fetchPlatforms = async () => {
      try {
        const res = await fetch('/api/collect/platforms')
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        if (isMounted && data) {
          setPlatforms(data)
        }
      } catch (err) {
        console.warn('Could not fetch platforms availability:', err)
      }
    }
    fetchPlatforms()
    const interval = setInterval(fetchPlatforms, 15000)
    return () => {
      isMounted = false
      clearInterval(interval)
    }
  }, [])

  const platformMeta = {
    youtube: { name: 'YouTube', color: '#ef4444' },
    reddit: { name: 'Reddit', color: '#f97316' },
    x: { name: 'X / Twitter', color: '#38bdf8' },
    instagram: { name: 'Instagram', color: '#ec4899' }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {Object.entries(platforms).map(([key, info]) => {
        const meta = platformMeta[key] || { name: key, color: '#94a3b8' }
        const isAvail = !!info.available
        return (
          <div
            key={key}
            title={info.reason || (isAvail ? 'Ready to collect' : 'Unavailable')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-colors cursor-help ${
              isAvail
                ? 'bg-slate-800/80 border-emerald-500/30 text-emerald-400'
                : 'bg-slate-900/40 border-slate-700/50 text-slate-400 opacity-70'
            }`}
          >
            <span
              className="w-2 h-2 rounded-full inline-block"
              style={{ backgroundColor: isAvail ? meta.color : '#64748b' }}
            />
            <span>{meta.name}</span>
            {isAvail ? (
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <AlertCircle className="w-3.5 h-3.5 text-slate-400" />
            )}
          </div>
        )
      })}
    </div>
  )
}
