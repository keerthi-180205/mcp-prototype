import { useState, useEffect, useRef } from 'react'
import {
  ArrowUp,
  Loader2,
  Sparkles,
  Bot,
  AlertCircle
} from 'lucide-react'
import PlanCard from './PlanCard'
import JobCard from './JobCard'
import ResultsCard from './ResultsCard'
import QuickReplies from './QuickReplies'

let msgCounter = 0
function nextMsgId() {
  msgCounter += 1
  return `msg_${msgCounter}_${Math.random().toString(36).substring(2, 7)}`
}

function getStoredMessagesForSession(sid) {
  if (!sid) return []
  try {
    const data = localStorage.getItem(`mcp_msgs_${sid}`)
    if (data) return JSON.parse(data)
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
 * Format simple markdown elements (bold, bullet lines) into React elements
 */
function FormattedMessageText({ text }) {
  if (!text) return null
  const lines = text.split('\n')

  return (
    <div className="assistant-text">
      {lines.map((line, lIdx) => {
        // Bullet point line
        const isBullet = line.trim().startsWith('•') || line.trim().startsWith('* ') || line.trim().startsWith('- ')
        const cleanLine = isBullet ? line.trim().replace(/^[•*-]\s*/, '') : line

        // Parse **bold** parts
        const parts = cleanLine.split(/(\*\*[^*]+\*\*)/g)
        const renderedLine = parts.map((part, pIdx) => {
          if (part.startsWith('**') && part.endsWith('**')) {
            return (
              <strong key={pIdx} style={{ color: '#ffffff', fontWeight: 600 }}>
                {part.slice(2, -2)}
              </strong>
            )
          }
          return part
        })

        if (isBullet) {
          return (
            <div key={lIdx} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', margin: '3px 0' }}>
              <span style={{ color: '#10a37f', fontSize: '13px' }}>•</span>
              <div>{renderedLine}</div>
            </div>
          )
        }

        return (
          <p key={lIdx} style={{ margin: line.trim() ? '4px 0' : '8px 0' }}>
            {renderedLine}
          </p>
        )
      })}
    </div>
  )
}

export default function ChatInterface({ sessionId, onSessionTitleUpdate }) {
  const [messages, setMessages] = useState(() => getStoredMessagesForSession(sessionId))
  const [inputText, setInputText] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState(null)

  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)

  // Persist messages whenever updated
  useEffect(() => {
    saveStoredMessagesForSession(sessionId, messages)
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sessionId, isLoading])

  // Auto-resize textarea
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

    // Add user bubble if it's text query
    if (query && !action) {
      const userMsg = { role: 'user', text: query, id: nextMsgId() }
      setMessages(prev => {
        const next = [...prev, userMsg]
        // If this is the first message in this conversation, notify parent to set history title
        if (prev.length === 0 && onSessionTitleUpdate) {
          const title = query.length > 36 ? query.substring(0, 36) + '...' : query
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
      setErrorMessage(`Backend connection error: ${err.message}. Please verify the web server is running on port 8080.`)
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

  const examplePrompts = [
    'Get 500 comments about Asian Games 2026 from YouTube and Reddit',
    'Collect 200 comments about Artificial Intelligence from YouTube',
    'Find 300 comments about Electric Vehicles from Reddit and X',
    'What platforms are currently available?'
  ]

  return (
    <div className="llm-main">
      {/* Messages Scroll Area */}
      <div className="llm-chat-stream" aria-live="polite">
        <div className="llm-stream-inner">
          {messages.length === 0 ? (
            <div className="llm-empty-state">
              <div className="empty-icon-halo">
                <Sparkles className="w-7 h-7" />
              </div>
              <h2 className="empty-heading">Where social intelligence begins</h2>
              <p className="empty-subheading">
                Enter your query naturally like ChatGPT or Claude. I'll search public comments, build a collection plan, track background harvesting, and deliver structured CSV/JSON results.
              </p>

              <div className="empty-prompt-grid">
                {examplePrompts.map((prompt, idx) => (
                  <button
                    key={idx}
                    onClick={() => sendMessage(prompt)}
                    className="prompt-card-chip"
                  >
                    <span>"{prompt}"</span>
                    <ArrowUp className="w-4 h-4" style={{ transform: 'rotate(45deg)', color: '#10a37f', flexShrink: 0 }} />
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map(msg => (
              <div key={msg.id} className={`message-turn ${msg.role}`}>
                {msg.role === 'user' ? (
                  <div className="user-bubble">
                    {msg.text}
                  </div>
                ) : (
                  <>
                    <div className="assistant-avatar">
                      <Bot className="w-4 h-4" />
                    </div>
                    <div className="assistant-body">
                      {/* Text bubbles */}
                      {msg.messages?.map((m, mIdx) => (
                        <FormattedMessageText key={mIdx} text={m.text} />
                      ))}

                      {/* Rich Cards (Artifacts) */}
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

                      {/* Quick Replies */}
                      <QuickReplies
                        replies={msg.quick_replies}
                        onSelect={(reply) => sendMessage(reply)}
                        disabled={isLoading}
                      />
                    </div>
                  </>
                )}
              </div>
            ))
          )}

          {/* Typing Indicator */}
          {isLoading && (
            <div className="message-turn assistant">
              <div className="assistant-avatar">
                <Bot className="w-4 h-4" />
              </div>
              <div className="assistant-body">
                <div className="typing-bubble">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span style={{ marginLeft: '6px' }}>Thinking & checking platforms...</span>
                </div>
              </div>
            </div>
          )}

          {/* Error Message */}
          {errorMessage && (
            <div className="card-notice-box" style={{ background: 'rgba(239, 68, 68, 0.1)', borderColor: 'rgba(239, 68, 68, 0.3)', color: '#fca5a5' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
                <AlertCircle className="w-4 h-4" />
                <span>Backend Error</span>
              </div>
              <p>{errorMessage}</p>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Floating Bottom Input Dock (ChatGPT & Claude Style) */}
      <div className="llm-input-dock">
        <div className="input-capsule">
          <textarea
            ref={textareaRef}
            rows={1}
            value={inputText}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            placeholder="Message Social Pulse Assistant (e.g. 'Get 500 comments about Asian Games 2026 from YouTube and Reddit')..."
            className="llm-textarea"
          />
          <button
            onClick={() => sendMessage(inputText)}
            disabled={isLoading || !inputText.trim()}
            className="btn-send-capsule"
            title="Send query (Enter)"
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <ArrowUp className="w-4 h-4" />
            )}
          </button>
        </div>
        <div className="input-footer-note">
          Social Pulse MCP Assistant uses live multi-platform scrapers. Enter to send, Shift + Enter for newline.
        </div>
      </div>
    </div>
  )
}
