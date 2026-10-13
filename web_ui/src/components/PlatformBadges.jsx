import { useState, useEffect } from 'react'

export default function PlatformBadges({ mode = 'sidebar' }) {
  const [platforms, setPlatforms] = useState({
    youtube: { available: true, reason: 'Ready' },
    reddit: { available: true, reason: 'Ready' },
    x: { available: true, reason: 'Ready' },
    instagram: { available: false, reason: 'Apify Token Required' }
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
    instagram: { name: 'Instagram', color: '#ec4899' },
    linkedin: { name: 'LinkedIn', color: '#0a66c2' }
  }

  if (mode === 'compact') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        {Object.entries(platforms).map(([key, info]) => {
          const meta = platformMeta[key] || { name: key, color: '#94a3b8' }
          const isAvail = !!info.available
          return (
            <span
              key={key}
              title={`${meta.name}: ${info.reason || (isAvail ? 'Connected' : 'Unavailable')}`}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '2px 7px',
                borderRadius: '12px',
                background: '#262626',
                border: '1px solid #383838',
                fontSize: '11px',
                color: isAvail ? '#ececec' : '#777'
              }}
            >
              <span className={`status-dot ${isAvail ? 'green' : 'gray'}`} />
              <span>{meta.name}</span>
            </span>
          )
        })}
      </div>
    )
  }

  return (
    <div className="platform-pills-list">
      {Object.entries(platforms).map(([key, info]) => {
        const meta = platformMeta[key] || { name: key, color: '#94a3b8' }
        const isAvail = !!info.available
        return (
          <div
            key={key}
            className="platform-pill-row"
            title={info.reason || (isAvail ? 'Ready to collect' : 'Unavailable')}
          >
            <div className="platform-pill-label">
              <span
                style={{
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  backgroundColor: meta.color,
                  display: 'inline-block'
                }}
              />
              <span>{meta.name}</span>
            </div>
            <span
              className={`status-dot ${isAvail ? 'green' : 'gray'}`}
              title={isAvail ? 'Connected & Ready' : info.reason || 'Offline'}
            />
          </div>
        )
      })}
    </div>
  )
}
