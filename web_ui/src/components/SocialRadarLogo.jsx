import React, { useState } from 'react'
import logoSrc from '../assets/logo.png'

export function SocialRadarLogo({ size = 24, className = '', rounded = true, style = {} }) {
  const [loadError, setLoadError] = useState(false)
  const borderRadius = rounded ? `${Math.max(4, Math.round(size * 0.22))}px` : '0px'

  if (loadError) {
    // Beautiful vector radar fallback if image fails to render
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 100 100"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={className}
        style={{
          width: `${size}px`,
          height: `${size}px`,
          borderRadius,
          verticalAlign: 'middle',
          display: 'inline-block',
          ...style
        }}
      >
        <defs>
          <linearGradient id="radarFallbackGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#4f46e5" />
            <stop offset="50%" stopColor="#2563eb" />
            <stop offset="100%" stopColor="#06b6d4" />
          </linearGradient>
        </defs>
        <rect width="100" height="100" rx="22" fill="url(#radarFallbackGrad)" />
        <circle cx="50" cy="50" r="32" stroke="#ffffff" strokeWidth="6" strokeDasharray="160 40" fill="none" />
        <circle cx="50" cy="50" r="20" stroke="#ffffff" strokeWidth="6" strokeDasharray="95 30" fill="none" />
        <circle cx="50" cy="50" r="7" fill="#ffffff" />
        <path d="M50 50 L78 22" stroke="#ffffff" strokeWidth="6" strokeLinecap="round" />
        <circle cx="78" cy="22" r="5" fill="#ffffff" opacity="0.9" />
      </svg>
    )
  }

  return (
    <img
      src={logoSrc}
      alt="SocialRadar AI"
      width={size}
      height={size}
      className={className}
      onError={() => setLoadError(true)}
      style={{
        width: `${size}px`,
        height: `${size}px`,
        objectFit: 'contain',
        borderRadius,
        display: 'inline-block',
        verticalAlign: 'middle',
        boxShadow: size > 32 ? '0 10px 25px -5px rgba(59, 130, 246, 0.4), 0 8px 10px -6px rgba(139, 92, 246, 0.3)' : 'none',
        ...style
      }}
    />
  )
}

export default SocialRadarLogo
