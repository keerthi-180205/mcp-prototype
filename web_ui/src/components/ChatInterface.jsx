import { useState, useEffect, useRef } from 'react'
import {
  ArrowUp,
  Loader2,
  Sparkles,
  AlertCircle,
  Copy,
  Check,
  ThumbsUp,
  ThumbsDown,
  RotateCcw,
  Paperclip,
  Globe,
  Mic,
  TrendingUp,
  Video,
  Camera,
  MessageSquare
} from 'lucide-react'
import PlanCard from './PlanCard'
import JobCard from './JobCard'
import ResultsCard from './ResultsCard'
import { SocialRadarLogo } from './SocialRadarLogo'

let msgCounter = 0
function nextMsgId() {
  msgCounter += 1
  return `msg_${msgCounter}_${Math.random().toString(36).substring(2, 7)}`
}

function getStoredMessagesForSession(sid) {
  if (!sid) return []
  try {
    const data = localStorage.getItem(`mcp_msgs_${sid}`)
    if (data) {
      const parsed = JSON.parse(data)
      if (Array.isArray(parsed)) return parsed
    }
  } catch (e) {
    console.warn('localStorage read error:', e)
  }
  return []
}

function saveStoredMessagesForSession(sid, msgs) {
  if (!sid) return
  try {
    localStorage.setItem(`mcp_msgs_${sid}`, JSON.stringify(msgs))
  } catch (e) {
    console.warn('localStorage write error:', e)
  }
}

/**
 * Render structured markdown formatting with bolding and bullet lists
 */
function FormattedMessageText({ text }) {
  if (!text) return null
  const lines = text.split('\n')

  return (
    <div className="chatgpt-markdown-body">
      {lines.map((line, lIdx) => {
        const isBullet = line.trim().startsWith('•') || line.trim().startsWith('* ') || line.trim().startsWith('- ')
        const cleanLine = isBullet ? line.trim().replace(/^[•*-]\s*/, '') : line

        const parts = cleanLine.split(/(\*\*[^*]+\*\*)/g)
        const renderedLine = parts.map((part, pIdx) => {
          if (part.startsWith('**') && part.endsWith('**')) {
            return (
              <strong key={pIdx} className="markdown-bold">
                {part.slice(2, -2)}
              </strong>
            )
          }
          return part
        })

        if (isBullet) {
          return (
            <div key={lIdx} className="markdown-bullet-row">
              <span className="bullet-dot">•</span>
              <div className="bullet-content">{renderedLine}</div>
            </div>
          )
        }

        if (!line.trim()) {
          return <div key={lIdx} className="markdown-paragraph-spacer" />
        }

        return (
          <p key={lIdx} className="markdown-paragraph">
            {renderedLine}
          </p>
        )
      })}
    </div>
  )
}

export default function ChatInterface({ sessionId, onSessionTitleUpdate, selectedModelName }) {
  const [messages, setMessages] = useState(() => getStoredMessagesForSession(sessionId))
  const [inputText, setInputText] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState(null)
  const [copiedMsgId, setCopiedMsgId] = useState(null)
  const [feedback, setFeedback] = useState({})
  const [webSearchActive, setWebSearchActive] = useState(true)

  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    saveStoredMessagesForSession(sessionId, messages)
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sessionId, isLoading])

  const adjustTextareaHeight = () => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`
    }
  }

  const handleInputChange = (e) => {
    setInputText(e.target.value)
    adjustTextareaHeight()
  }

  const sendMessage = async (textToSend, action = null) => {
    const query = (textToSend || '').trim()
    if (!query && !action) return

    setErrorMessage(null)

    if (query && !action) {
      const userMsg = { role: 'user', text: query, id: nextMsgId() }
      setMessages(prev => {
        const next = [...prev, userMsg]
        if (prev.length === 0 && onSessionTitleUpdate) {
          const title = query.length > 32 ? query.substring(0, 32) + '...' : query
          onSessionTitleUpdate(sessionId, title)
        }
        return next
      })
      setInputText('')
      if (textareaRef.current) {
        textareaRef.current.style.height = '24px'
      }
    }

    setIsLoading(true)

    try {
      const payload = {
        session_id: sessionId,
        text: query,
        action: action
      }

      const res = await fetch('/api/assistant/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })

      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status}`)
      }

      const data = await res.json()

      const botEntry = {
        role: 'assistant',
        id: nextMsgId(),
        messages: data.messages || [],
        cards: data.cards || [],
        quick_replies: data.quick_replies || []
      }

      setMessages(prev => [...prev, botEntry])
    } catch (err) {
      console.error('Assistant error:', err)
      setErrorMessage(`Connection error: ${err.message}. Ensure the backend server is running.`)
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!isLoading && inputText.trim()) {
        sendMessage(inputText)
      }
    }
  }

  const handleCopyMessage = (msgId, text) => {
    navigator.clipboard?.writeText(text)
    setCopiedMsgId(msgId)
    setTimeout(() => setCopiedMsgId(null), 2000)
  }

  const handleFeedback = (msgId, type) => {
    setFeedback(prev => ({
      ...prev,
      [msgId]: prev[msgId] === type ? null : type
    }))
  }

  const handleRegenerate = () => {
    const lastUserMsg = [...messages].reverse().find(m => m.role === 'user')
    if (lastUserMsg && !isLoading) {
      sendMessage(lastUserMsg.text)
    }
  }

  const suggestionCards = [
    {
      title: 'Trending Instagram Reels',
      subtitle: 'Analyze viral AI & tech reels via TrueScrape',
      icon: <Camera className="w-4 h-4 text-pink-400" />,
      prompt: 'Search trending Instagram Reels about AI tools and fetch top comments'
    },
    {
      title: 'YouTube Sentiment Analysis',
      subtitle: 'Extract public video comments with yt-dlp',
      icon: <Video className="w-4 h-4 text-red-400" />,
      prompt: 'Get 200 public comments about Artificial Intelligence from YouTube'
    },
    {
      title: 'Cross-Platform Discovery',
      subtitle: 'Harvest discussions across YouTube, Reddit & X',
      icon: <Globe className="w-4 h-4 text-blue-400" />,
      prompt: 'Find 300 comments about Electric Vehicles from Reddit, YouTube, and X'
    },
    {
      title: 'Platform Capabilities',
      subtitle: 'Check TrueScrape, yt-dlp, and MCP health',
      icon: <Sparkles className="w-4 h-4 text-[#10a37f]" />,
      prompt: 'What platforms and tools are currently available and connected?'
    }
  ]

  return (
    <div className="chatgpt-stream-wrapper">
      {/* Scrollable Conversation Container */}
      <div className="chatgpt-conversation-scroll">
        <div className="chatgpt-conversation-container">
          {messages.length === 0 ? (
            /* SocialRadar AI Empty State */
            <div className="chatgpt-empty-stage">
              <div className="chatgpt-hero-logo" style={{ background: 'transparent' }}>
                <SocialRadarLogo size={76} />
              </div>
              <h1 className="chatgpt-hero-title">SocialRadar AI</h1>
              <p style={{ color: '#8e8e8e', fontSize: '15px', marginTop: '4px', marginBottom: '28px', textAlign: 'center' }}>
                Multi-platform audience intelligence & live comment discovery
              </p>

              {/* Suggestion Cards */}
              <div className="chatgpt-suggestions-grid">
                {suggestionCards.map((card, idx) => (
                  <button
                    key={idx}
                    onClick={() => sendMessage(card.prompt)}
                    className="chatgpt-suggestion-card"
                  >
                    <div className="suggestion-icon-wrap">
                      {card.icon}
                    </div>
                    <div className="suggestion-text-wrap">
                      <span className="suggestion-title">{card.title}</span>
                      <span className="suggestion-subtitle">{card.subtitle}</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            /* Message turns */
            messages.map(msg => (
              <div key={msg.id} className={`chatgpt-turn ${msg.role}`}>
                {msg.role === 'user' ? (
                  <div className="chatgpt-user-bubble">
                    {msg.text}
                  </div>
                ) : (
                  <div className="chatgpt-assistant-turn">
                    <div className="assistant-avatar-circle" style={{ background: 'transparent', overflow: 'hidden' }}>
                      <SocialRadarLogo size={24} />
                    </div>

                    <div className="assistant-content-column">
                      {/* Text bubbles */}
                      {msg.messages?.map((m, mIdx) => (
                        <FormattedMessageText key={mIdx} text={m.text} />
                      ))}

                      {/* Interactive Artifact Cards */}
                      {msg.cards?.map((card, cIdx) => {
                        if (card.type === 'plan') {
                          return (
                            <PlanCard
                              key={cIdx}
                              card={card}
                              onAction={(act) => sendMessage(null, act)}
                              disabled={isLoading}
                            />
                          )
                        } else if (card.type === 'job' || card.type === 'job_status') {
                          return (
                            <JobCard
                              key={cIdx}
                              card={card}
                              onShowResults={() => sendMessage('show results')}
                            />
                          )
                        } else if (card.type === 'results') {
                          return (
                            <ResultsCard
                              key={cIdx}
                              card={card}
                            />
                          )
                        }
                        return null
                      })}

                      {/* Quick Replies removed for clean conversational experience */}

                      {/* ChatGPT Action Bar */}
                      <div className="chatgpt-action-bar">
                        <button
                          onClick={() => handleCopyMessage(msg.id, msg.messages?.map(m => m.text).join('\n') || '')}
                          className="action-icon-btn"
                          title="Copy"
                        >
                          {copiedMsgId === msg.id ? (
                            <Check className="w-3.5 h-3.5 text-[#10a37f]" />
                          ) : (
                            <Copy className="w-3.5 h-3.5" />
                          )}
                        </button>

                        <button
                          onClick={() => handleFeedback(msg.id, 'like')}
                          className={`action-icon-btn ${feedback[msg.id] === 'like' ? 'active' : ''}`}
                          title="Good response"
                        >
                          <ThumbsUp className="w-3.5 h-3.5" />
                        </button>

                        <button
                          onClick={() => handleFeedback(msg.id, 'dislike')}
                          className={`action-icon-btn ${feedback[msg.id] === 'dislike' ? 'active' : ''}`}
                          title="Bad response"
                        >
                          <ThumbsDown className="w-3.5 h-3.5" />
                        </button>

                        <button
                          onClick={handleRegenerate}
                          className="action-icon-btn"
                          title="Regenerate response"
                          disabled={isLoading}
                        >
                          <RotateCcw className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))
          )}

          {/* Typing Indicator */}
          {isLoading && (
            <div className="chatgpt-turn assistant">
              <div className="chatgpt-assistant-turn">
                <div className="assistant-avatar-circle" style={{ background: 'transparent', overflow: 'hidden' }}>
                  <SocialRadarLogo size={24} />
                </div>
                <div className="assistant-content-column">
                  <div className="chatgpt-thinking-state">
                    <span className="thinking-pulse-dot" />
                    <span className="thinking-pulse-dot" />
                    <span className="thinking-pulse-dot" />
                    <span className="thinking-text">Thinking with TrueScrape & yt-dlp...</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Error Message */}
          {errorMessage && (
            <div className="chatgpt-error-box">
              <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
              <span>{errorMessage}</span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Signature Floating ChatGPT Bottom Input Dock */}
      <div className="chatgpt-dock-wrapper">
        <div className="chatgpt-input-dock">
          {/* Inner multi-line capsule */}
          <div className="dock-capsule-container">
            <textarea
              ref={textareaRef}
              rows={1}
              value={inputText}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
              placeholder="Message SocialRadar AI..."
              className="dock-textarea"
            />

            {/* Bottom action controls inside the capsule */}
            <div className="dock-actions-row">
              <div className="dock-tools-left">
                <button
                  type="button"
                  className="dock-tool-btn"
                  title="Attach file or data"
                >
                  <Paperclip className="w-4 h-4" />
                </button>

                <button
                  type="button"
                  onClick={() => setWebSearchActive(prev => !prev)}
                  className={`dock-tool-btn ${webSearchActive ? 'active-pill' : ''}`}
                  title="Search with TrueScrape & Web"
                >
                  <Globe className="w-4 h-4" />
                  <span className="tool-btn-label">Search</span>
                </button>
              </div>

              <div className="dock-controls-right">
                <button
                  type="button"
                  className="dock-tool-btn"
                  title="Voice input"
                >
                  <Mic className="w-4 h-4" />
                </button>

                {/* Signature circular Send Button */}
                <button
                  onClick={() => sendMessage(inputText)}
                  disabled={isLoading || !inputText.trim()}
                  className={`dock-send-button ${inputText.trim() ? 'has-input' : ''}`}
                  title="Send message (Enter)"
                >
                  {isLoading ? (
                    <Loader2 className="w-4 h-4 animate-spin text-[#171717]" />
                  ) : (
                    <ArrowUp className="w-4 h-4" />
                  )}
                </button>
              </div>
            </div>
          </div>

          <div className="dock-disclaimer">
            SocialRadar AI can make mistakes. Verify important information.
          </div>
        </div>
      </div>
    </div>
  )
}
