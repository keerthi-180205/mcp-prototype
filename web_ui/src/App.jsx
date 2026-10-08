import { useState } from 'react'
import {
  MessageSquare,
  SlidersHorizontal,
  Layers
} from 'lucide-react'
import ChatInterface from './components/ChatInterface'
import DiscoveryStudio from './components/DiscoveryStudio'
import './index.css'

export default function App() {
  const [activeTab, setActiveTab] = useState('chat')

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-indigo-500 selection:text-white">
      {/* Top Navbar */}
      <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 via-indigo-500 to-sky-400 flex items-center justify-center text-white shadow-lg shadow-indigo-500/25">
              <Layers className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-base font-bold text-white tracking-tight flex items-center gap-2">
                Social Pulse MCP
                <span className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                  Assistant
                </span>
              </h1>
              <p className="text-[11px] text-slate-400 hidden sm:block">
                Multi-Platform Comment Intelligence & Collection
              </p>
            </div>
          </div>

          {/* Tab Selector */}
          <nav className="flex items-center gap-1.5 p-1 rounded-xl bg-slate-950/80 border border-slate-800">
            <button
              onClick={() => setActiveTab('chat')}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                activeTab === 'chat'
                  ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
              }`}
            >
              <MessageSquare className="w-3.5 h-3.5" />
              <span>Chat Assistant</span>
            </button>

            <button
              onClick={() => setActiveTab('discovery')}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                activeTab === 'discovery'
                  ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
              }`}
            >
              <SlidersHorizontal className="w-3.5 h-3.5" />
              <span>Discovery Studio</span>
            </button>
          </nav>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-6xl mx-auto w-full p-4 sm:p-6 flex flex-col justify-center">
        {activeTab === 'chat' ? (
          <ChatInterface />
        ) : (
          <DiscoveryStudio />
        )}
      </main>
    </div>
  )
}
