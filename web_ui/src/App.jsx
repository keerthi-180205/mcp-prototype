import { useState, useEffect, useRef } from 'react'
import {
  SquarePen,
  PanelLeft,
  Trash2,
  Sparkles,
  ChevronDown,
  Share2,
  Compass,
  SlidersHorizontal,
  MessageSquare,
  Search,
  Check,
  Zap,
  Globe,
  Settings as SettingsIcon
} from 'lucide-react'
import ChatInterface from './components/ChatInterface'
import DiscoveryStudio from './components/DiscoveryStudio'
import PlatformBadges from './components/PlatformBadges'
import { SocialRadarLogo } from './components/SocialRadarLogo'
import './index.css'

const STORAGE_SESSIONS_LIST = 'mcp_sessions_list'
const STORAGE_ACTIVE_SESSION = 'mcp_active_session'

function generateSessionId() {
  return 'sess_' + Math.random().toString(36).substring(2, 10)
}

function createSessionObject(id, title) {
  return { id, title, updatedAt: Date.now() }
}

function loadStoredSessions() {
  try {
    const raw = localStorage.getItem(STORAGE_SESSIONS_LIST)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed) && parsed.length > 0) return parsed
    }
  } catch (e) {
    console.warn('Failed to load sessions:', e)
  }
  const defaultId = generateSessionId()
  const initial = [createSessionObject(defaultId, 'New chat')]
  try {
    localStorage.setItem(STORAGE_SESSIONS_LIST, JSON.stringify(initial))
    localStorage.setItem(STORAGE_ACTIVE_SESSION, defaultId)
  } catch (e) {
    console.warn('Failed to initialize sessions in localStorage:', e)
  }
  return initial
}

function getInitialActiveSession(sessions) {
  try {
    const saved = localStorage.getItem(STORAGE_ACTIVE_SESSION)
    if (saved && sessions.some(s => s.id === saved)) {
      return saved
    }
  } catch (e) {
    console.warn('Failed to get active session:', e)
  }
  return sessions[0]?.id || generateSessionId()
}

export default function App() {
  const [activeTab, setActiveTab] = useState('chat')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [sessions, setSessions] = useState(loadStoredSessions)
  const [activeSessionId, setActiveSessionId] = useState(() => getInitialActiveSession(sessions))
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false)
  const [selectedModel, setSelectedModel] = useState('socialradar-ai')
  const [searchFilter, setSearchFilter] = useState('')
  const [showSearchInput, setShowSearchInput] = useState(false)
  const [shareCopied, setShareCopied] = useState(false)

  const dropdownRef = useRef(null)

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_SESSIONS_LIST, JSON.stringify(sessions))
    } catch (e) {
      console.warn('Failed to save sessions:', e)
    }
  }, [sessions])

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_ACTIVE_SESSION, activeSessionId)
    } catch (e) {
      console.warn('Failed to save active session:', e)
    }
  }, [activeSessionId])

  useEffect(() => {
    function handleClickOutside(event) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setModelDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleCreateNewChat = () => {
    const newId = generateSessionId()
    const newSession = createSessionObject(newId, 'New chat')
    setSessions(prev => [newSession, ...prev])
    setActiveSessionId(newId)
    setActiveTab('chat')
    setSearchFilter('')
  }

  const handleSelectSession = (sid) => {
    setActiveSessionId(sid)
    setActiveTab('chat')
  }

  const handleDeleteSession = (e, sid) => {
    e.stopPropagation()
    const remaining = sessions.filter(s => s.id !== sid)
    if (remaining.length === 0) {
      const newId = generateSessionId()
      const newSession = createSessionObject(newId, 'New chat')
      setSessions([newSession])
      setActiveSessionId(newId)
    } else {
      setSessions(remaining)
      if (activeSessionId === sid) {
        setActiveSessionId(remaining[0].id)
      }
    }
    try {
      localStorage.removeItem(`mcp_msgs_${sid}`)
    } catch (err) {
      console.warn('Failed to remove session messages:', err)
    }
  }

  const handleSessionTitleUpdate = (sid, title) => {
    setSessions(prev =>
      prev.map(s => (s.id === sid ? { ...s, title } : s))
    )
  }

  const handleShare = () => {
    navigator.clipboard?.writeText(window.location.href)
    setShareCopied(true)
    setTimeout(() => setShareCopied(false), 2000)
  }

  const models = [
    {
      id: 'socialradar-ai',
      name: 'SocialRadar AI',
      desc: 'Intelligent multi-platform audience intelligence powered by Gemini LLM & TrueScrape',
      icon: <SocialRadarLogo size={18} />
    },
    {
      id: 'truescrape',
      name: 'TrueScrape Instagram',
      desc: 'High-speed REST engine for Reels, posts & public comment acquisition',
      icon: <Zap className="w-4 h-4 text-pink-400" />
    },
    {
      id: 'agent-reach',
      name: 'Agent Reach (yt-dlp)',
      desc: 'Zero-API-key local scraper for YouTube videos & comments',
      icon: <Globe className="w-4 h-4 text-red-400" />
    }
  ]

  const currentModelObj = models.find(m => m.id === selectedModel) || models[0]

  const filteredSessions = sessions.filter(s =>
    !searchFilter ? true : s.title.toLowerCase().includes(searchFilter.toLowerCase())
  )

  return (
    <div className="chatgpt-layout">
      {/* ChatGPT Left Sidebar */}
      <aside className={`chatgpt-sidebar ${sidebarOpen ? '' : 'collapsed'}`}>
        <div className="sidebar-top">
          {/* Top Bar with Logo & Collapse & New Chat */}
          <div className="sidebar-header-row">
            <button
              onClick={() => setSidebarOpen(false)}
              className="chatgpt-icon-btn"
              title="Close sidebar"
            >
              <PanelLeft className="w-4 h-4" />
            </button>

            <button
              onClick={handleCreateNewChat}
              className="chatgpt-new-chat-btn"
              title="New chat"
            >
              <SquarePen className="w-4 h-4" />
            </button>
          </div>

          {/* Quick Actions / Navigation */}
          <div className="sidebar-nav-list">
            <button
              onClick={handleCreateNewChat}
              className={`sidebar-nav-item ${activeTab === 'chat' && sessions.find(s => s.id === activeSessionId)?.title === 'New chat' ? 'active' : ''}`}
            >
              <div className="nav-item-icon" style={{ display: 'flex', alignItems: 'center' }}>
                <SocialRadarLogo size={18} />
              </div>
              <span className="nav-item-label" style={{ fontWeight: 600 }}>SocialRadar AI</span>
            </button>

            <button
              onClick={() => setActiveTab('discovery')}
              className={`sidebar-nav-item ${activeTab === 'discovery' ? 'active' : ''}`}
            >
              <div className="nav-item-icon">
                <Compass className="w-4 h-4 text-[#10a37f]" />
              </div>
              <span className="nav-item-label">Explore Studio</span>
            </button>
          </div>

          {/* Search Chats Bar (if toggled or active) */}
          {showSearchInput && (
            <div className="sidebar-search-box">
              <Search className="w-3.5 h-3.5 text-[#8e8e8e]" />
              <input
                type="text"
                value={searchFilter}
                onChange={e => setSearchFilter(e.target.value)}
                placeholder="Search chats..."
                className="sidebar-search-input"
                autoFocus
              />
            </div>
          )}
        </div>

        {/* Chat History List */}
        <div className="chatgpt-history-container">
          <div className="history-group-header">
            <span>Recent</span>
            <button
              onClick={() => setShowSearchInput(prev => !prev)}
              className="chatgpt-icon-btn small"
              title="Search chats"
            >
              <Search className="w-3 h-3" />
            </button>
          </div>

          <div className="history-items-list">
            {filteredSessions.map(s => {
              const isActive = activeSessionId === s.id && activeTab === 'chat'
              return (
                <div
                  key={s.id}
                  onClick={() => handleSelectSession(s.id)}
                  className={`chatgpt-history-row ${isActive ? 'active' : ''}`}
                >
                  <span className="history-title" title={s.title}>
                    {s.title}
                  </span>
                  {sessions.length > 1 && (
                    <button
                      onClick={(e) => handleDeleteSession(e, s.id)}
                      className="history-action-btn"
                      title="Delete chat"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* Sidebar Footer: Profile & Connected Scrapers */}
        <div className="chatgpt-sidebar-footer">
          <div className="sidebar-platform-status">
            <PlatformBadges mode="sidebar" />
          </div>

          <div className="chatgpt-user-row">
            <div className="chatgpt-user-avatar">
              <span>K</span>
            </div>
            <div className="chatgpt-user-info">
              <span className="user-name">User Workspace</span>
              <span className="user-plan">MCP TrueScrape Live</span>
            </div>
          </div>
        </div>
      </aside>

      {/* Main ChatGPT Body */}
      <div className="chatgpt-main-view">
        {/* Top Header Bar */}
        <header className="chatgpt-topbar">
          <div className="topbar-left-group">
            {!sidebarOpen && (
              <button
                onClick={() => setSidebarOpen(true)}
                className="chatgpt-icon-btn"
                title="Open sidebar"
              >
                <PanelLeft className="w-4 h-4" />
              </button>
            )}

            {!sidebarOpen && (
              <button
                onClick={handleCreateNewChat}
                className="chatgpt-icon-btn"
                title="New chat"
              >
                <SquarePen className="w-4 h-4" />
              </button>
            )}

            {/* Model Selector Dropdown */}
            <div className="model-selector-wrapper" ref={dropdownRef}>
              <button
                onClick={() => setModelDropdownOpen(prev => !prev)}
                className="chatgpt-model-btn"
              >
                <span className="model-name">{currentModelObj.name}</span>
                <ChevronDown className="w-3.5 h-3.5 text-[#8e8e8e]" />
              </button>

              {modelDropdownOpen && (
                <div className="model-dropdown-menu">
                  <div className="dropdown-title">Model Options</div>
                  {models.map(m => (
                    <div
                      key={m.id}
                      onClick={() => {
                        setSelectedModel(m.id)
                        setModelDropdownOpen(false)
                      }}
                      className={`dropdown-model-item ${selectedModel === m.id ? 'selected' : ''}`}
                    >
                      <div className="dropdown-item-header">
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          {m.icon}
                          <span className="dropdown-item-title">{m.name}</span>
                        </div>
                        {selectedModel === m.id && (
                          <Check className="w-4 h-4 text-[#10a37f]" />
                        )}
                      </div>
                      <p className="dropdown-item-desc">{m.desc}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="topbar-right-group">
            <PlatformBadges mode="compact" />

            <button
              onClick={handleShare}
              className="chatgpt-share-btn"
              title="Share chat"
            >
              {shareCopied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-[#10a37f]" />
                  <span>Copied</span>
                </>
              ) : (
                <>
                  <Share2 className="w-3.5 h-3.5" />
                  <span>Share</span>
                </>
              )}
            </button>

            <div className="chatgpt-top-avatar" title="User Account">
              <span>K</span>
            </div>
          </div>
        </header>

        {/* View Switcher: Chat Interface or Studio */}
        <div className="chatgpt-content-stage">
          {activeTab === 'chat' ? (
            <ChatInterface
              key={activeSessionId}
              sessionId={activeSessionId}
              onSessionTitleUpdate={handleSessionTitleUpdate}
              selectedModelName={currentModelObj.name}
            />
          ) : (
            <DiscoveryStudio />
          )}
        </div>
      </div>
    </div>
  )
}
