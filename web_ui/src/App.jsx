import { useState, useEffect } from 'react'
import {
  MessageSquare,
  SlidersHorizontal,
  Plus,
  PanelLeft,
  Trash2,
  Sparkles
} from 'lucide-react'
import ChatInterface from './components/ChatInterface'
import DiscoveryStudio from './components/DiscoveryStudio'
import PlatformBadges from './components/PlatformBadges'
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
    if (raw) return JSON.parse(raw)
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

  const handleCreateNewChat = () => {
    const newId = generateSessionId()
    const newSession = createSessionObject(newId, 'New chat')
    setSessions(prev => [newSession, ...prev])
    setActiveSessionId(newId)
    setActiveTab('chat')
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
    // Clean up stored messages for this session
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

  return (
    <div className="llm-layout">
      {/* Sidebar (ChatGPT & Claude Style) */}
      <aside className={`llm-sidebar ${sidebarOpen ? '' : 'collapsed'}`}>
        <div className="llm-sidebar-header">
          <button
            onClick={handleCreateNewChat}
            className="new-chat-btn"
            title="Start a new collection conversation"
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Plus className="w-4 h-4" />
              <span>New chat</span>
            </div>
            <Sparkles className="w-3.5 h-3.5" style={{ color: '#10a37f' }} />
          </button>

          {/* Navigation Switcher */}
          <div className="sidebar-nav-tabs">
            <button
              onClick={() => setActiveTab('chat')}
              className={`sidebar-tab-btn ${activeTab === 'chat' ? 'active' : ''}`}
            >
              <MessageSquare className="w-3.5 h-3.5" />
              <span>Chat</span>
            </button>
            <button
              onClick={() => setActiveTab('discovery')}
              className={`sidebar-tab-btn ${activeTab === 'discovery' ? 'active' : ''}`}
            >
              <SlidersHorizontal className="w-3.5 h-3.5" />
              <span>Discovery</span>
            </button>
          </div>
        </div>

        {/* Chat History List */}
        <div className="llm-sidebar-history">
          <div className="history-section-title">Recent Chats</div>
          {sessions.map(s => (
            <div
              key={s.id}
              onClick={() => handleSelectSession(s.id)}
              className={`history-item ${activeSessionId === s.id && activeTab === 'chat' ? 'active' : ''}`}
            >
              <span title={s.title}>{s.title}</span>
              {sessions.length > 1 && (
                <button
                  onClick={(e) => handleDeleteSession(e, s.id)}
                  className="icon-btn"
                  title="Delete chat"
                  style={{ padding: '2px', opacity: 0.6 }}
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              )}
            </div>
          ))}
        </div>

        {/* Sidebar Footer: Platform Statuses */}
        <div className="llm-sidebar-footer">
          <div className="platform-status-title">
            <span>Platforms</span>
            <span style={{ fontSize: '10px', color: '#10a37f', fontWeight: 600 }}>MCP Live</span>
          </div>
          <PlatformBadges mode="sidebar" />
        </div>
      </aside>

      {/* Main Content Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
        {/* Top Header Bar */}
        <header className="llm-topbar">
          <div className="topbar-left">
            <button
              onClick={() => setSidebarOpen(prev => !prev)}
              className="icon-btn"
              title={sidebarOpen ? 'Close sidebar' : 'Open sidebar'}
            >
              <PanelLeft className="w-4 h-4" />
            </button>
            <div className="topbar-title">
              <span>Social Pulse MCP</span>
              <span className="model-badge">Social Pulse v2</span>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <PlatformBadges mode="compact" />
          </div>
        </header>

        {/* View Body */}
        {activeTab === 'chat' ? (
          <ChatInterface
            key={activeSessionId}
            sessionId={activeSessionId}
            onSessionTitleUpdate={handleSessionTitleUpdate}
          />
        ) : (
          <DiscoveryStudio />
        )}
      </div>
    </div>
  )
}
