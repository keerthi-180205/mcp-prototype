import { useState, useEffect, useRef } from 'react'
import {
  Send,
  Loader2,
  RefreshCw,
  Sparkles,
  Bot,
  User,
  AlertCircle
} from 'lucide-react'
import PlatformBadges from './PlatformBadges'
import PlanCard from './PlanCard'
import JobCard from './JobCard'
import ResultsCard from './ResultsCard'
import QuickReplies from './QuickReplies'

const STORAGE_SESSION_KEY = 'mcp_assistant_session_id'
const STORAGE_MESSAGES_KEY = 'mcp_assistant_messages'

let msgCounter = 0
function nextMsgId() {
  msgCounter += 1
  return `msg_${msgCounter}_${Math.random().toString(36).substring(2, 7)}`
}

function generateSessionId() {
  return 'sess_' + Math.random().toString(36).substring(2, 10)
}

function getStoredSession() {
  try {
    const s = localStorage.getItem(STORAGE_SESSION_KEY)
    if (s) return s
  } catch (e) {
    console.warn('localStorage read error:', e)
  }
  const newId = generateSessionId()
  try {
    localStorage.setItem(STORAGE_SESSION_KEY, newId)
  } catch (e) {
    console.warn('localStorage write error:', e)
  }
  return newId
}

function getStoredMessages() {
  try {
    const data = localStorage.getItem(STORAGE_MESSAGES_KEY)
    if (data) return JSON.parse(data)
  } catch (e) {
    console.warn('localStorage read error for messages:', e)
  }
  return []
}

function saveStoredMessages(messages) {
  try {
    localStorage.setItem(STORAGE_MESSAGES_KEY, JSON.stringify(messages))
  } catch (e) {
    console.warn('localStorage write error for messages:', e)
  }
}

export default function ChatInterface() {
  const [sessionId, setSessionId] = useState(getStoredSession)
  const [messages, setMessages] = useState(getStoredMessages)
  const [inputText, setInputText] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState(null)

  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    saveStoredMessages(messages)
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  const handleNewChat = () => {
    const newSession = generateSessionId()
    try {
      localStorage.setItem(STORAGE_SESSION_KEY, newSession)
      localStorage.removeItem(STORAGE_MESSAGES_KEY)
    } catch (e) {
      console.warn('localStorage reset error:', e)
    }
    setSessionId(newSession)
    setMessages([])
    setErrorMessage(null)
    setInputText('')
  }

  const sendMessage = async (textToSend, action = null) => {
    const query = (textToSend || '').trim()
    if (!query && !action) return

    setErrorMessage(null)

    // Add user bubble if it's text and not an internal action alone
    if (query && !action) {
      const userMsg = { role: 'user', text: query, id: nextMsgId() }
      setMessages(prev => [...prev, userMsg])
      setInputText('')
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
      setErrorMessage(`Could not reach the collection backend: ${err.message}. Please verify the server is running on port 8080.`)
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!isLoading) {
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
    <div className="flex flex-col h-[calc(100vh-8rem)] max-w-5xl mx-auto w-full bg-slate-900/60 rounded-2xl border border-slate-800 shadow-2xl backdrop-blur-xl overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-800 bg-slate-900/90 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-500 to-sky-400 flex items-center justify-center text-white shadow-md shadow-indigo-500/20">
            <Bot className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              Social Comments Assistant
              <span className="text-[10px] uppercase font-semibold px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                v2 live
              </span>
            </h2>
            <p className="text-xs text-slate-400">Natural language comment collection across social platforms</p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <PlatformBadges />
          <button
            onClick={handleNewChat}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white text-xs font-semibold border border-slate-700 transition-colors shadow-sm"
            title="Start a fresh conversation"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>New Chat</span>
          </button>
        </div>
      </div>

      {/* Messages Scroll Area */}
      <div
        className="flex-1 overflow-y-auto px-6 py-6 space-y-6"
        aria-live="polite"
      >
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center max-w-lg mx-auto py-12">
            <div className="w-14 h-14 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 mb-4 shadow-inner">
              <Sparkles className="w-7 h-7" />
            </div>
            <h3 className="text-lg font-bold text-white mb-2">What would you like to collect?</h3>
            <p className="text-sm text-slate-400 mb-6">
              Ask in plain English to gather public comments across YouTube, Reddit, X, and Instagram.
              I will confirm the plan, track live progress, and provide CSV/JSON downloads.
            </p>

            <div className="w-full space-y-2">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-2">
                Example Prompts
              </span>
              {examplePrompts.map((prompt, idx) => (
                <button
                  key={idx}
                  onClick={() => sendMessage(prompt)}
                  className="w-full text-left p-3 rounded-xl bg-slate-800/60 hover:bg-slate-800 border border-slate-700/60 hover:border-indigo-500/50 text-slate-200 hover:text-white text-xs font-medium transition-all shadow-sm flex items-center justify-between group"
                >
                  <span>"{prompt}"</span>
                  <Send className="w-3.5 h-3.5 text-slate-500 group-hover:text-indigo-400 transition-colors" />
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map(msg => (
            <div key={msg.id} className="space-y-3">
              {msg.role === 'user' ? (
                <div className="flex justify-end">
                  <div className="flex items-start gap-2.5 max-w-xl">
                    <div className="p-3.5 rounded-2xl bg-indigo-600 text-white text-sm shadow-md leading-relaxed rounded-tr-sm">
                      {msg.text}
                    </div>
                    <div className="w-7 h-7 rounded-full bg-indigo-500 flex items-center justify-center text-white shrink-0 shadow-sm mt-0.5">
                      <User className="w-4 h-4" />
                    </div>
                  </div>
                </div>
              ) : (
                <div className="flex justify-start">
                  <div className="flex items-start gap-3 max-w-2xl w-full">
                    <div className="w-8 h-8 rounded-xl bg-slate-800 border border-slate-700 flex items-center justify-center text-sky-400 shrink-0 mt-0.5 shadow-sm">
                      <Bot className="w-4 h-4" />
                    </div>
                    <div className="flex-1 space-y-3">
                      {/* Text bubbles */}
                      {msg.messages?.map((m, mIdx) => (
                        <div
                          key={mIdx}
                          className="p-3.5 rounded-2xl bg-slate-800/80 border border-slate-700/60 text-slate-200 text-sm shadow-sm leading-relaxed rounded-tl-sm whitespace-pre-wrap"
                        >
                          {m.text}
                        </div>
                      ))}

                      {/* Rich Cards */}
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
                  </div>
                </div>
              )}
            </div>
          ))
        )}

        {/* In-Flight Typing Indicator */}
        {isLoading && (
          <div className="flex justify-start">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-xl bg-slate-800 border border-slate-700 flex items-center justify-center text-sky-400 shadow-sm">
                <Bot className="w-4 h-4" />
              </div>
              <div className="px-4 py-2.5 rounded-2xl bg-slate-800/80 border border-slate-700/60 text-slate-300 text-xs flex items-center gap-2 shadow-sm">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-sky-400" />
                <span>Assistant is thinking...</span>
              </div>
            </div>
          </div>
        )}

        {/* Error Bubble */}
        {errorMessage && (
          <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2 shadow-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{errorMessage}</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Bar */}
      <div className="p-4 border-t border-slate-800 bg-slate-900/90">
        <div className="flex items-end gap-2 bg-slate-950/80 border border-slate-800 rounded-xl p-2 focus-within:border-indigo-500/60 transition-colors shadow-inner">
          <textarea
            ref={textareaRef}
            rows={1}
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            placeholder="Type a request (e.g. 'get me 500 comments about Asian Games 2026 from YouTube and Reddit')..."
            className="flex-1 bg-transparent border-0 resize-none text-slate-100 placeholder-slate-500 text-sm focus:outline-none focus:ring-0 px-2 py-1 max-h-32 min-h-[2rem]"
          />
          <button
            onClick={() => sendMessage(inputText)}
            disabled={isLoading || !inputText.trim()}
            className="p-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:hover:bg-indigo-600 text-white transition-all shadow-md shrink-0 cursor-pointer disabled:cursor-not-allowed"
            title="Send request (Enter)"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
        <div className="mt-1.5 flex items-center justify-between text-[11px] text-slate-500 px-1">
          <span>Press Enter to send, Shift + Enter for newline</span>
          <span>Confirmation gate required before jobs begin</span>
        </div>
      </div>
    </div>
  )
}
