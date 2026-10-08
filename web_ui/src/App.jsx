import { useState, useEffect } from 'react'
import {
  Activity,
  Search,
  Loader2,
  ExternalLink,
  Globe,
  Sparkles,
  CheckCircle2,
  XCircle,
  Share2,
  MessageSquare,
  Video,
  FileText,
  SlidersHorizontal,
  ChevronRight,
  TrendingUp,
  Award,
  Layers,
  ArrowRight,
  RefreshCw,
  Eye,
  Heart,
  ShieldCheck,
  Radio
} from 'lucide-react'
import './index.css'

export default function App() {
  // Navigation: 'connect' or 'chat'
  const [activeTab, setActiveTab] = useState('chat')
  
  // Platform connections state
  const [platforms, setPlatforms] = useState({
    youtube: { connected: true, name: 'YouTube', account: '@agent_reach_runner', features: ['Live Trending Videos', 'Shorts', 'Real Commenters', 'Public Comments'], color: '#ef4444' },
    instagram: { connected: true, name: 'Instagram', account: '@discovery_studio', features: ['Live Trending Reels', 'Explore Posts', 'Commenters'], color: '#ec4899' },
    reddit: { connected: true, name: 'Reddit', account: 'u/social_intelligence', features: ['Live Subreddit Posts', 'Community Discussions', 'Authors'], color: '#f97316' },
    linkedin: { connected: true, name: 'LinkedIn', account: 'in/growth-intelligence-lead', features: ['Professional Posts', 'Articles', 'Commenters'], color: '#0a66c2' },
    twitter: { connected: true, name: 'Twitter / X', account: '@social_scout', features: ['Tweets', 'Replies', 'Commenters'], color: '#38bdf8' }
  })
  
  // Unified dynamic search query
  const [query, setQuery] = useState('King Kohli')
  const [isLoading, setIsLoading] = useState(false)
  const [chatHistory, setChatHistory] = useState([])
  const [activeViewMode, setActiveViewMode] = useState('table') // 'table' or 'cards'
  const [platformFilter, setPlatformFilter] = useState('all') // 'all' or specific platform

  // Fetch initial platform status from server
  useEffect(() => {
    fetch('http://localhost:8080/api/platforms/status')
      .then(res => res.json())
      .then(data => {
        if (data.status === 'success' && data.platforms) {
          setPlatforms(data.platforms)
        }
      })
      .catch(err => console.debug("Using local platform defaults:", err))
  }, [])

  const handleTogglePlatform = async (key) => {
    const current = platforms[key]?.connected ?? false
    const nextState = !current
    
    setPlatforms(prev => ({
      ...prev,
      [key]: {
        ...prev[key],
        connected: nextState
      }
    }))

    try {
      await fetch('http://localhost:8080/api/platforms/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: key, connected: nextState })
      })
    } catch (err) {
      console.warn("Could not sync platform state to backend:", err)
    }
  }

  const handleConnectAll = () => {
    const updated = {}
    Object.keys(platforms).forEach(k => {
      updated[k] = { ...platforms[k], connected: true }
    })
    setPlatforms(updated)
  }

  const connectedCount = Object.values(platforms).filter(p => p.connected).length
  const connectedKeys = Object.keys(platforms).filter(k => platforms[k].connected)

  const handleSubmitDiscovery = async (e, customQuery) => {
    if (e) e.preventDefault()
    const targetQuery = (customQuery !== undefined ? customQuery : query).trim()

    if (!targetQuery) return

    if (customQuery) setQuery(customQuery)

    setIsLoading(true)
    setActiveTab('chat')

    const newQueryItem = {
      type: 'user',
      query: targetQuery,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }

    setChatHistory(prev => [...prev, newQueryItem])

    try {
      const res = await fetch('http://localhost:8080/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: targetQuery,
          description: targetQuery,
          field: targetQuery,
          connected_platforms: connectedKeys
        })
      })

      if (res.ok) {
        const data = await res.json()
        if (data.status === 'success') {
          const commentsList = data.matched_comments || data.matched_profiles || data.comments || []
          const aiResponseItem = {
            type: 'ai',
            message: data.chatbot_message,
            topic: data.field || data.topic || targetQuery,
            matched_comments: commentsList,
            total_scraped: data.total_scraped || commentsList.length,
            total_matched: data.total_matched || commentsList.length,
            platforms_searched: data.platforms_reached || connectedKeys,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          }
          setChatHistory(prev => [...prev, aiResponseItem])
        } else {
          setChatHistory(prev => [...prev, {
            type: 'ai_error',
            message: data.message || "Failed to process discovery request.",
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          }])
        }
      } else {
        setChatHistory(prev => [...prev, {
          type: 'ai_error',
          message: "Failed to connect to backend server on port 8080.",
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }])
      }
    } catch (err) {
      console.error(err)
      setChatHistory(prev => [...prev, {
        type: 'ai_error',
        message: "Network error connecting to discovery server.",
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      }])
    } finally {
      setIsLoading(false)
    }
  }

  const trendingTopics = [
    { label: "👑 King Kohli (Cricket)", q: "King Kohli" },
    { label: "⚽ Cristiano Ronaldo", q: "Cristiano Ronaldo" },
    { label: "🏏 Cricket World Cup", q: "Cricket World Cup" },
    { label: "🤖 AI Agents & Tools", q: "AI Agents and automation" },
    { label: "🏋️ Fitness & Bodybuilding", q: "Fitness workouts and bodybuilding" },
    { label: "🎬 Viral Video Editing", q: "Video editing for reels" }
  ]

  const getPlatformStyle = (platform) => {
    const p = (platform || '').toLowerCase()
    if (p.includes('instagram')) return { background: 'linear-gradient(135deg, #833ab4, #fd1d1d, #fcb045)', color: '#fff' }
    if (p.includes('linkedin')) return { background: '#0a66c2', color: '#fff' }
    if (p.includes('youtube')) return { background: '#ef4444', color: '#fff' }
    if (p.includes('twitter') || p.includes('x')) return { background: '#1d9bf0', color: '#fff' }
    if (p.includes('reddit')) return { background: '#ff4500', color: '#fff' }
    return { background: '#3b82f6', color: '#fff' }
  }

  return (
    <div className="dashboard-container" style={{ maxWidth: '1280px', margin: '0 auto', padding: '1.5rem' }}>
      {/* Top Header */}
      <header className="header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div style={{
            width: '46px',
            height: '46px',
            borderRadius: '12px',
            background: 'linear-gradient(135deg, #ef4444, #f59e0b)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 4px 15px rgba(239, 68, 68, 0.4)'
          }}>
            <Radio size={24} color="#ffffff" />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <h1 style={{ fontSize: '1.8rem', fontWeight: 800, margin: 0, letterSpacing: '-0.5px' }}>
                Live Trending Social Comments
              </h1>
              <span style={{
                fontSize: '0.7rem',
                fontWeight: 700,
                padding: '0.15rem 0.5rem',
                borderRadius: '12px',
                background: 'rgba(239, 68, 68, 0.2)',
                color: '#f87171',
                border: '1px solid rgba(239, 68, 68, 0.4)',
                display: 'flex',
                alignItems: 'center',
                gap: '4px'
              }}>
                <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#ef4444' }}></span>
                REAL-TIME
              </span>
            </div>
            <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              Fetches most trending posts & reels in any social media • Extracts comment sections & usernames • Agent Reach filter
            </p>
          </div>
        </div>

        {/* Tab Toggle Navigation */}
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button
            onClick={() => setActiveTab('connect')}
            style={{
              padding: '0.55rem 1.1rem',
              borderRadius: '10px',
              border: activeTab === 'connect' ? '1px solid #3b82f6' : '1px solid rgba(255,255,255,0.1)',
              background: activeTab === 'connect' ? 'rgba(59, 130, 246, 0.2)' : 'rgba(255,255,255,0.03)',
              color: activeTab === 'connect' ? '#93c5fd' : '#cbd5e1',
              fontWeight: 600,
              fontSize: '0.85rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            <Share2 size={16} />
            <span>Connected Channels ({connectedCount})</span>
          </button>

          <button
            onClick={() => setActiveTab('chat')}
            style={{
              padding: '0.55rem 1.1rem',
              borderRadius: '10px',
              border: activeTab === 'chat' ? '1px solid #ef4444' : '1px solid rgba(255,255,255,0.1)',
              background: activeTab === 'chat' ? 'rgba(239, 68, 68, 0.25)' : 'rgba(255,255,255,0.03)',
              color: activeTab === 'chat' ? '#fca5a5' : '#cbd5e1',
              fontWeight: 600,
              fontSize: '0.85rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            <TrendingUp size={16} />
            <span>Trending Stream</span>
          </button>
        </div>
      </header>

      {/* VIEW 1: PLATFORM CONNECTION HUB */}
      {activeTab === 'connect' && (
        <div className="connection-hub-view" style={{ animation: 'fadeIn 0.3s ease' }}>
          <div style={{
            background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.9))',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '16px',
            padding: '1.75rem',
            marginBottom: '1.5rem',
            backdropFilter: 'blur(10px)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem', marginBottom: '1.25rem' }}>
              <div>
                <h2 style={{ fontSize: '1.4rem', fontWeight: 700, margin: '0 0 0.3rem 0', color: '#f8fafc' }}>
                  Live Social Media Channels
                </h2>
                <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.9rem' }}>
                  Enable platforms to scrape real-time trending posts, reels, and comment sections.
                </p>
              </div>

              <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                <button
                  onClick={handleConnectAll}
                  style={{
                    padding: '0.5rem 1rem',
                    borderRadius: '8px',
                    border: '1px solid rgba(255,255,255,0.15)',
                    background: 'rgba(255,255,255,0.05)',
                    color: '#e2e8f0',
                    fontSize: '0.85rem',
                    cursor: 'pointer'
                  }}
                >
                  Connect All
                </button>
                <button
                  onClick={() => setActiveTab('chat')}
                  style={{
                    padding: '0.55rem 1.25rem',
                    borderRadius: '8px',
                    background: 'linear-gradient(135deg, #ef4444, #f59e0b)',
                    color: '#ffffff',
                    border: 'none',
                    fontWeight: 600,
                    fontSize: '0.9rem',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}
                >
                  <span>Launch Live Stream</span>
                  <ArrowRight size={16} />
                </button>
              </div>
            </div>

            {/* Platform Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem' }}>
              {Object.entries(platforms).map(([key, p]) => (
                <div
                  key={key}
                  style={{
                    background: p.connected ? 'rgba(30, 41, 59, 0.85)' : 'rgba(15, 23, 42, 0.6)',
                    border: p.connected ? `1px solid ${p.color}55` : '1px solid rgba(255,255,255,0.08)',
                    borderRadius: '14px',
                    padding: '1.25rem'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.85rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      <div style={{
                        width: '42px',
                        height: '42px',
                        borderRadius: '10px',
                        ...getPlatformStyle(key),
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontWeight: 700,
                        fontSize: '1.1rem'
                      }}>
                        {p.name[0]}
                      </div>
                      <div>
                        <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 700, color: '#f8fafc' }}>{p.name}</h3>
                        <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>{p.account}</span>
                      </div>
                    </div>

                    <span style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      padding: '0.2rem 0.6rem',
                      borderRadius: '20px',
                      background: p.connected ? 'rgba(16, 185, 129, 0.15)' : 'rgba(148, 163, 184, 0.1)',
                      color: p.connected ? '#34d399' : '#94a3b8',
                      border: p.connected ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(148, 163, 184, 0.2)'
                    }}>
                      {p.connected ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
                      {p.connected ? 'Active' : 'Disabled'}
                    </span>
                  </div>

                  <div style={{ marginBottom: '1rem' }}>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                      {p.features.map((feat, fIdx) => (
                        <span
                          key={fIdx}
                          style={{
                            fontSize: '0.72rem',
                            padding: '0.15rem 0.5rem',
                            borderRadius: '4px',
                            background: 'rgba(255,255,255,0.06)',
                            color: '#cbd5e1'
                          }}
                        >
                          {feat}
                        </span>
                      ))}
                    </div>
                  </div>

                  <button
                    onClick={() => handleTogglePlatform(key)}
                    style={{
                      width: '100%',
                      padding: '0.55rem',
                      borderRadius: '8px',
                      border: p.connected ? '1px solid rgba(239, 68, 68, 0.3)' : `1px solid ${p.color}`,
                      background: p.connected ? 'rgba(239, 68, 68, 0.1)' : `${p.color}22`,
                      color: p.connected ? '#f87171' : '#ffffff',
                      fontWeight: 600,
                      fontSize: '0.85rem',
                      cursor: 'pointer'
                    }}
                  >
                    {p.connected ? 'Disable Channel' : `Enable ${p.name}`}
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* VIEW 2: LIVE TRENDING STREAM & COMMENTS CHAT */}
      {activeTab === 'chat' && (
        <div className="chat-interface-view" style={{ animation: 'fadeIn 0.3s ease' }}>
          {/* Active Platforms Status Bar */}
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: 'rgba(30, 41, 59, 0.6)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: '12px',
            padding: '0.65rem 1rem',
            marginBottom: '1rem',
            fontSize: '0.85rem'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
              <span style={{ color: '#94a3b8', fontWeight: 500 }}>Live Crawling Across:</span>
              {connectedKeys.map(k => (
                <span
                  key={k}
                  style={{
                    fontSize: '0.75rem',
                    padding: '0.15rem 0.6rem',
                    borderRadius: '20px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '5px',
                    background: 'rgba(16, 185, 129, 0.15)',
                    color: '#34d399',
                    border: '1px solid rgba(16, 185, 129, 0.3)'
                  }}
                >
                  <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981' }}></span>
                  {platforms[k].name}
                </span>
              ))}
            </div>

            <button
              onClick={() => setActiveTab('connect')}
              style={{
                background: 'none',
                border: 'none',
                color: '#60a5fa',
                fontSize: '0.8rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px'
              }}
            >
              <span>Manage Channels</span>
              <ChevronRight size={14} />
            </button>
          </div>

          {/* Quick Trending Topic Pills */}
          <div style={{ marginBottom: '1.25rem' }}>
            <span style={{ fontSize: '0.78rem', color: '#94a3b8', fontWeight: 600, display: 'block', marginBottom: '0.4rem' }}>
              TRENDING NOW (ONE-CLICK DISCOVERY):
            </span>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
              {trendingTopics.map((t, idx) => (
                <button
                  key={idx}
                  onClick={() => handleSubmitDiscovery(null, t.q)}
                  disabled={isLoading}
                  style={{
                    padding: '0.4rem 0.85rem',
                    borderRadius: '8px',
                    background: query.toLowerCase() === t.q.toLowerCase() ? 'rgba(239, 68, 68, 0.2)' : 'rgba(255,255,255,0.04)',
                    border: query.toLowerCase() === t.q.toLowerCase() ? '1px solid rgba(239, 68, 68, 0.4)' : '1px solid rgba(255,255,255,0.1)',
                    color: query.toLowerCase() === t.q.toLowerCase() ? '#fca5a5' : '#cbd5e1',
                    fontSize: '0.8rem',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease'
                  }}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          {/* Chat Feed */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', marginBottom: '2rem' }}>
            {/* Welcome Bot Message */}
            <div style={{
              background: 'rgba(30, 41, 59, 0.5)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '16px',
              padding: '1.25rem',
              display: 'flex',
              gap: '1rem',
              alignItems: 'flex-start'
            }}>
              <div style={{
                width: '36px',
                height: '36px',
                borderRadius: '10px',
                background: 'linear-gradient(135deg, #ef4444, #f59e0b)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0
              }}>
                <Radio size={20} color="#fff" />
              </div>
              <div>
                <h4 style={{ margin: '0 0 0.3rem 0', fontSize: '1rem', color: '#f8fafc' }}>
                  Live Trending Social Discovery Engine
                </h4>
                <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.9rem', lineHeight: '1.5' }}>
                  Enter <strong>any topic</strong> (e.g. <em>"King Kohli"</em>, <em>"Ronaldo"</em>, <em>"AI agents"</em>). The system crawls live trending posts, reels, and videos in real time, extracts the <strong>exact user_name</strong> who commented and <strong>what they said</strong>, and filters for highest relevance.
                </p>
              </div>
            </div>

            {/* Conversation History */}
            {chatHistory.map((item, idx) => (
              <div key={idx} style={{ animation: 'fadeIn 0.3s ease' }}>
                {item.type === 'user' && (
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '1rem' }}>
                    <div style={{
                      maxWidth: '80%',
                      background: 'linear-gradient(135deg, #ef4444, #ea580c)',
                      borderRadius: '16px 16px 4px 16px',
                      padding: '0.85rem 1.25rem',
                      color: '#ffffff',
                      boxShadow: '0 4px 15px rgba(239, 68, 68, 0.3)'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.2rem' }}>
                        <span style={{ fontSize: '0.72rem', background: 'rgba(0,0,0,0.2)', padding: '0.1rem 0.5rem', borderRadius: '4px', fontWeight: 700 }}>
                          LIVE QUERY
                        </span>
                        <span style={{ fontSize: '0.72rem', opacity: 0.8 }}>{item.timestamp}</span>
                      </div>
                      <p style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600 }}>
                        {item.query}
                      </p>
                    </div>
                  </div>
                )}

                {item.type === 'ai' && (
                  <div style={{
                    background: 'rgba(15, 23, 42, 0.85)',
                    border: '1px solid rgba(255, 255, 255, 0.1)',
                    borderRadius: '16px',
                    padding: '1.5rem',
                    boxShadow: '0 8px 30px rgba(0,0,0,0.25)'
                  }}>
                    {/* Header Summary */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem', marginBottom: '1rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        <div style={{
                          width: '42px',
                          height: '42px',
                          borderRadius: '12px',
                          background: 'linear-gradient(135deg, #10b981, #059669)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          boxShadow: '0 4px 15px rgba(16, 185, 129, 0.3)'
                        }}>
                          <MessageSquare size={22} color="#fff" />
                        </div>
                        <div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                            <h4 style={{ margin: 0, fontSize: '1.2rem', color: '#f8fafc', fontWeight: 800 }}>
                              Live Universal Social Results for: <span style={{ color: '#f59e0b' }}>{item.topic}</span>
                            </h4>
                            <span style={{ fontSize: '0.72rem', padding: '0.15rem 0.55rem', borderRadius: '12px', background: 'rgba(239, 68, 68, 0.2)', color: '#f87171', fontWeight: 700, border: '1px solid rgba(239, 68, 68, 0.4)' }}>
                              ⚡ UNIVERSAL STREAM
                            </span>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px', flexWrap: 'wrap' }}>
                            <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                              Found <strong style={{ color: '#f8fafc' }}>{item.matched_comments?.length || item.total_matched}</strong> real commenter reactions across YouTube, Reddit, Instagram & X
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* View Switcher: Table vs Cards */}
                      <div style={{ display: 'flex', gap: '0.5rem', background: 'rgba(255,255,255,0.05)', padding: '0.2rem', borderRadius: '8px' }}>
                        <button
                          onClick={() => setActiveViewMode('table')}
                          style={{
                            padding: '0.4rem 0.95rem',
                            borderRadius: '6px',
                            border: 'none',
                            background: activeViewMode === 'table' ? '#ef4444' : 'transparent',
                            color: activeViewMode === 'table' ? '#ffffff' : '#94a3b8',
                            fontSize: '0.82rem',
                            fontWeight: 700,
                            cursor: 'pointer'
                          }}
                        >
                          Tabular View (4-Col)
                        </button>
                        <button
                          onClick={() => setActiveViewMode('cards')}
                          style={{
                            padding: '0.4rem 0.95rem',
                            borderRadius: '6px',
                            border: 'none',
                            background: activeViewMode === 'cards' ? '#ef4444' : 'transparent',
                            color: activeViewMode === 'cards' ? '#ffffff' : '#94a3b8',
                            fontSize: '0.82rem',
                            fontWeight: 700,
                            cursor: 'pointer'
                          }}
                        >
                          Comment Cards
                        </button>
                      </div>
                    </div>

                    {/* Strict 3-4 Months Trending Window Banner */}
                    <div style={{
                      background: 'rgba(15, 23, 42, 0.75)',
                      border: '1px solid rgba(16, 185, 129, 0.3)',
                      borderRadius: '10px',
                      padding: '0.65rem 1rem',
                      marginBottom: '1rem',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      flexWrap: 'wrap',
                      gap: '0.5rem',
                      fontSize: '0.82rem'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#34d399' }}>
                        <CheckCircle2 size={16} />
                        <span>
                          <strong>Strict 3 to 4 Months Trending Filter Active:</strong> Verified content published from <strong>June 2026 onwards</strong> (no older data).
                        </span>
                      </div>
                      <span style={{
                        fontSize: '0.72rem',
                        fontWeight: 700,
                        padding: '0.15rem 0.5rem',
                        borderRadius: '6px',
                        background: 'rgba(16, 185, 129, 0.2)',
                        color: '#6ee7b7'
                      }}>
                        Max Age: 120 Days
                      </span>
                    </div>

                    {/* Platform Filter Tabs */}
                    <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.78rem', color: '#94a3b8', fontWeight: 600 }}>Filter Platform:</span>
                      {['all', 'youtube', 'reddit', 'instagram', 'twitter'].map((pKey) => {
                        const count = pKey === 'all'
                          ? (item.matched_comments?.length || 0)
                          : (item.matched_comments?.filter(c => (c.platform || '').toLowerCase().includes(pKey === 'twitter' ? 'twit' : pKey)).length || 0)
                        
                        const label = pKey === 'all' ? 'All Universal' : pKey === 'twitter' ? 'Twitter / X' : pKey.charAt(0).toUpperCase() + pKey.slice(1)
                        const isSel = platformFilter === pKey
                        return (
                          <button
                            key={pKey}
                            onClick={() => setPlatformFilter(pKey)}
                            style={{
                              padding: '0.25rem 0.65rem',
                              borderRadius: '20px',
                              border: isSel ? '1px solid #3b82f6' : '1px solid rgba(255,255,255,0.1)',
                              background: isSel ? 'rgba(59, 130, 246, 0.25)' : 'rgba(255,255,255,0.03)',
                              color: isSel ? '#93c5fd' : '#94a3b8',
                              fontSize: '0.78rem',
                              fontWeight: isSel ? 700 : 500,
                              cursor: 'pointer',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '5px'
                            }}
                          >
                            <span>{label}</span>
                            <span style={{
                              fontSize: '0.7rem',
                              padding: '0.05rem 0.35rem',
                              borderRadius: '10px',
                              background: isSel ? '#3b82f6' : 'rgba(255,255,255,0.1)',
                              color: '#fff'
                            }}>
                              {count}
                            </span>
                          </button>
                        )
                      })}
                    </div>

                    {/* VIEW A: 4-COLUMN TABULAR FORMAT (EXACT USER SPEC) */}
                    {activeViewMode === 'table' && (
                      <div className="table-responsive" style={{ overflowX: 'auto', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.1)' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.88rem' }}>
                          <thead>
                            <tr style={{ background: 'rgba(30, 41, 59, 0.95)', borderBottom: '1px solid rgba(255,255,255,0.12)' }}>
                              <th style={{ padding: '0.85rem 1rem', color: '#94a3b8', width: '22%' }}>1. User ID (Commenter)</th>
                              <th style={{ padding: '0.85rem 1rem', color: '#94a3b8', width: '44%' }}>2. What They Commented</th>
                              <th style={{ padding: '0.85rem 1rem', color: '#94a3b8', width: '16%' }}>3. Platform Name</th>
                              <th style={{ padding: '0.85rem 1rem', color: '#94a3b8', width: '18%' }}>4. Link of Reel / Post</th>
                            </tr>
                          </thead>
                          <tbody>
                            {item.matched_comments
                              ?.filter(c => platformFilter === 'all' || (c.platform || '').toLowerCase().includes(platformFilter === 'twitter' ? 'twit' : platformFilter))
                              .map((c, cIdx) => (
                              <tr key={cIdx} style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', background: cIdx % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)' }}>
                                {/* Col 1: user_name */}
                                <td style={{ padding: '0.85rem 1rem', verticalAlign: 'top' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <div style={{
                                      width: '32px',
                                      height: '32px',
                                      borderRadius: '50%',
                                      background: 'rgba(255,255,255,0.1)',
                                      display: 'flex',
                                      alignItems: 'center',
                                      justifyContent: 'center',
                                      fontSize: '0.85rem',
                                      fontWeight: 700,
                                      color: '#f8fafc'
                                    }}>
                                      {c.user_name.replace(/[@u\/]/g, '')[0]?.toUpperCase() || 'U'}
                                    </div>
                                    <div>
                                      <strong style={{ display: 'block', color: '#f8fafc', fontSize: '0.9rem' }}>
                                        {c.user_name}
                                      </strong>
                                      <span style={{
                                        fontSize: '0.72rem',
                                        fontWeight: 600,
                                        color: c.match_score >= 90 ? '#34d399' : '#93c5fd'
                                      }}>
                                        {c.match_score}% Match
                                      </span>
                                    </div>
                                  </div>
                                </td>

                                {/* Col 2: what they commented */}
                                <td style={{ padding: '0.85rem 1rem', verticalAlign: 'top' }}>
                                  <p style={{ margin: '0 0 0.4rem 0', color: '#e2e8f0', lineHeight: '1.45', fontSize: '0.88rem' }}>
                                    "{c.comment}"
                                  </p>
                                  <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', alignItems: 'center' }}>
                                    <span style={{
                                      fontSize: '0.68rem',
                                      padding: '0.12rem 0.45rem',
                                      borderRadius: '4px',
                                      background: 'rgba(16, 185, 129, 0.15)',
                                      color: '#34d399',
                                      border: '1px solid rgba(16, 185, 129, 0.3)',
                                      display: 'inline-flex',
                                      alignItems: 'center',
                                      gap: '3px'
                                    }}>
                                      ⏱️ {c.published_date || 'Recent'} ({c.recency_text || '< 4 months'})
                                    </span>
                                    <span style={{ fontSize: '0.68rem', padding: '0.12rem 0.4rem', borderRadius: '4px', background: 'rgba(59, 130, 246, 0.15)', color: '#93c5fd' }}>
                                      {c.intent_category || c.category}
                                    </span>
                                    {c.likes > 0 && (
                                      <span style={{ fontSize: '0.7rem', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '3px' }}>
                                        <Heart size={11} color="#f472b6" /> {c.likes} likes
                                      </span>
                                    )}
                                  </div>
                                </td>

                                {/* Col 3: platform name */}
                                <td style={{ padding: '0.85rem 1rem', verticalAlign: 'top' }}>
                                  <span style={{ fontSize: '0.78rem', padding: '0.2rem 0.6rem', borderRadius: '4px', fontWeight: 600, ...getPlatformStyle(c.platform) }}>
                                    {c.platform}
                                  </span>
                                  <span style={{ display: 'block', fontSize: '0.72rem', color: '#94a3b8', marginTop: '4px' }}>
                                    {c.media_type}
                                  </span>
                                </td>

                                {/* Col 4: link of the reel or video */}
                                <td style={{ padding: '0.85rem 1rem', verticalAlign: 'top' }}>
                                  <div style={{ marginBottom: '0.3rem' }}>
                                    <span style={{ fontSize: '0.75rem', color: '#94a3b8', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '200px' }}>
                                      {c.media_title}
                                    </span>
                                  </div>
                                  <a
                                    href={c.link || c.media_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    style={{
                                      display: 'inline-flex',
                                      alignItems: 'center',
                                      gap: '4px',
                                      color: '#60a5fa',
                                      textDecoration: 'none',
                                      fontSize: '0.8rem',
                                      fontWeight: 600,
                                      background: 'rgba(59, 130, 246, 0.1)',
                                      padding: '0.25rem 0.6rem',
                                      borderRadius: '6px',
                                      border: '1px solid rgba(59, 130, 246, 0.3)'
                                    }}
                                  >
                                    <span>Watch {c.media_type?.split(' ')[0] || 'Post'}</span>
                                    <ExternalLink size={12} />
                                  </a>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* VIEW B: INTERACTIVE COMMENT CARDS */}
                    {activeViewMode === 'cards' && (
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '1rem' }}>
                        {item.matched_comments?.map((c, cIdx) => (
                          <div
                            key={cIdx}
                            style={{
                              background: 'rgba(30, 41, 59, 0.7)',
                              border: c.match_score >= 90 ? '1px solid rgba(16, 185, 129, 0.4)' : '1px solid rgba(255, 255, 255, 0.1)',
                              borderRadius: '12px',
                              padding: '1.25rem',
                              display: 'flex',
                              flexDirection: 'column',
                              justifyContent: 'space-between'
                            }}
                          >
                            <div>
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                                <div>
                                  <span style={{ fontSize: '0.92rem', fontWeight: 700, color: '#f8fafc', display: 'block' }}>
                                    {c.user_name}
                                  </span>
                                  <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}>Live Commenter</span>
                                </div>

                                <div style={{ textAlign: 'right' }}>
                                  <span style={{ fontSize: '0.75rem', padding: '0.15rem 0.5rem', borderRadius: '4px', fontWeight: 600, ...getPlatformStyle(c.platform) }}>
                                    {c.platform}
                                  </span>
                                  <span style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, color: c.match_score >= 90 ? '#34d399' : '#93c5fd', marginTop: '2px' }}>
                                    {c.match_score}% Match
                                  </span>
                                </div>
                              </div>

                              {/* What They Commented */}
                              <div style={{
                                background: 'rgba(0,0,0,0.3)',
                                borderLeft: '3px solid #ef4444',
                                borderRadius: '6px',
                                padding: '0.75rem',
                                marginBottom: '0.85rem'
                              }}>
                                <span style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase', display: 'block', marginBottom: '0.2rem' }}>
                                  What they commented:
                                </span>
                                <p style={{ margin: 0, color: '#f1f5f9', fontSize: '0.88rem', lineHeight: '1.45', fontStyle: 'italic' }}>
                                  "{c.comment}"
                                </p>
                              </div>

                              <div style={{ fontSize: '0.78rem', color: '#94a3b8', marginBottom: '0.75rem' }}>
                                <span>Trending on: </span>
                                <strong style={{ color: '#cbd5e1' }}>{c.media_title}</strong>
                              </div>

                              <div style={{ background: 'rgba(239, 68, 68, 0.08)', padding: '0.55rem', borderRadius: '6px', marginBottom: '0.75rem' }}>
                                <span style={{ fontSize: '0.72rem', color: '#fca5a5', fontWeight: 600, display: 'block', marginBottom: '0.15rem' }}>
                                  ✨ Semantic Assessment:
                                </span>
                                <p style={{ margin: 0, fontSize: '0.76rem', color: '#e2e8f0', lineHeight: '1.35' }}>
                                  {c.llm_reasoning}
                                </p>
                              </div>
                            </div>

                            <a
                              href={c.link || c.media_url}
                              target="_blank"
                              rel="noreferrer"
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: '6px',
                                background: 'linear-gradient(135deg, #ef4444, #ea580c)',
                                color: '#ffffff',
                                textDecoration: 'none',
                                padding: '0.55rem',
                                borderRadius: '8px',
                                fontSize: '0.8rem',
                                fontWeight: 600
                              }}
                            >
                              <span>Open Live {c.media_type}</span>
                              <ExternalLink size={13} />
                            </a>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}

            {/* Loading Indicator */}
            {isLoading && (
              <div style={{
                background: 'rgba(30, 41, 59, 0.6)',
                border: '1px solid rgba(239, 68, 68, 0.4)',
                borderRadius: '16px',
                padding: '1.5rem',
                display: 'flex',
                alignItems: 'center',
                gap: '1rem',
                animation: 'pulse 2s infinite'
              }}>
                <Loader2 size={26} color="#f87171" className="spin" />
                <div>
                  <h4 style={{ margin: '0 0 0.2rem 0', fontSize: '0.98rem', color: '#f8fafc' }}>
                    Crawling Live Trending Posts & Comment Sections...
                  </h4>
                  <span style={{ fontSize: '0.82rem', color: '#94a3b8' }}>
                    Searching live YouTube, Reddit, Instagram for '{query}' • Extracting comment sections • Filtering comments...
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Search Console Input Section */}
          <form
            onSubmit={(e) => handleSubmitDiscovery(e)}
            style={{
              position: 'sticky',
              bottom: '1rem',
              background: 'rgba(15, 23, 42, 0.95)',
              border: '1px solid rgba(255, 255, 255, 0.12)',
              borderRadius: '16px',
              padding: '1rem 1.25rem',
              boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
              backdropFilter: 'blur(12px)',
              zIndex: 50
            }}
          >
            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Enter any topic to fetch live trending reels, posts & comments (e.g. 'King Kohli', 'Ronaldo', 'Cricket', 'AI Agents')..."
                disabled={isLoading}
                style={{
                  flex: 1,
                  padding: '0.85rem 1.25rem',
                  borderRadius: '10px',
                  background: 'rgba(255,255,255,0.07)',
                  border: '1px solid rgba(255,255,255,0.15)',
                  color: '#ffffff',
                  fontSize: '0.95rem'
                }}
              />

              <button
                type="submit"
                disabled={isLoading || !query.trim()}
                style={{
                  padding: '0.85rem 1.75rem',
                  borderRadius: '10px',
                  background: 'linear-gradient(135deg, #ef4444, #ea580c)',
                  color: '#ffffff',
                  border: 'none',
                  fontWeight: 700,
                  fontSize: '0.95rem',
                  cursor: isLoading ? 'not-allowed' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  boxShadow: '0 4px 15px rgba(239, 68, 68, 0.4)',
                  whiteSpace: 'nowrap'
                }}
              >
                {isLoading ? <Loader2 size={18} className="spin" /> : <TrendingUp size={18} />}
                <span>{isLoading ? 'Crawling...' : 'Fetch Live Trending'}</span>
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
