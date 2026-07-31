import { useState, useEffect } from 'react'
import { X, MessageSquare, FileText, Plus, Search, Settings } from 'lucide-react'
import ChatHistory from './components/ChatHistory'
import MainChat from './components/MainChat'
import FileExplorer from './components/FileExplorer'
import MonacoEditor from './components/MonacoEditor'
import SettingsPanel from './components/SettingsPanel'
import { PanelLeft, PanelRight, PanelBottom, Server, Circle } from 'lucide-react'
import { useStore } from './lib/store'
import { api } from './lib/api'
import TerminalPanel from './components/TerminalPanel'
import mascot from './assets/nexus-mascot-brand.png'

interface OpenFile {
  name: string
  path: string
  content: string
}

function App() {
  const [showFileExplorer, setShowFileExplorer] = useState(false)
  const [showChatHistory, setShowChatHistory] = useState(false)
  const [openFiles, setOpenFiles] = useState<OpenFile[]>([])
  const [activeFile, setActiveFile] = useState<string | null>(null)
  const [showFileEditor, setShowFileEditor] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showTerminal, setShowTerminal] = useState(false)
  const { sessions, activeSessionId, backendAvailable, checkBackend, loadSessionsFromServer, createSession, setActiveSession } = useStore()
  const session = sessions.find(s => s.id === activeSessionId)

  useEffect(() => {
    const theme = localStorage.getItem('nexus-theme') || 'light'
    document.documentElement.classList.remove('dark', 'theme-grey', 'theme-glass', 'theme-green', 'theme-blue', 'theme-purple')
    if (theme === 'dark') {
      document.documentElement.classList.add('dark')
    } else if (theme !== 'light') {
      document.documentElement.classList.add(`theme-${theme}`)
    }
    checkBackend()
    loadSessionsFromServer()
    // The GUI can finish loading before the freshly restarted API is ready.
    // Keep checking so a brief startup race cannot leave the composer disabled.
    const healthTimer = window.setInterval(checkBackend, 3000)
    return () => window.clearInterval(healthTimer)
  }, [])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
        e.preventDefault()
        setShowChatHistory(v => !v)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const handleFileOpen = (path: string) => {
    const name = path.split('/').pop() || path
    if (!openFiles.find(f => f.path === path)) {
      // Load file content
      api.readFile(path).then(res => {
        setOpenFiles([...openFiles, { name, path, content: res.content }])
      }).catch(() => {})
    }
    setActiveFile(path)
    setShowFileEditor(true)
  }

  const closeFile = (path: string) => {
    const newFiles = openFiles.filter(f => f.path !== path)
    setOpenFiles(newFiles)
    if (activeFile === path) {
      if (newFiles.length > 0) {
        setActiveFile(newFiles[0].path)
      } else {
        setActiveFile(null)
        setShowFileEditor(false)
      }
    }
  }

  const closeAllFiles = () => {
    setOpenFiles([])
    setActiveFile(null)
    setShowFileEditor(false)
  }

  return (
    <div className="flex flex-col h-screen bg-background text-foreground overflow-hidden">
      <div className="flex flex-1 min-h-0">
        {showChatHistory ? (
          <div className="flex-shrink-0 flex flex-col border-r border-border bg-card/50" style={{ width: 'var(--sidebar-width)' }}>
            <ChatHistory onOpenSettings={() => setShowSettings(true)} />
          </div>
        ) : (
          <aside aria-label="Collapsed chat sidebar" className="flex w-[52px] shrink-0 flex-col items-center border-r border-border bg-card/50 py-2">
            <button
              onClick={() => setShowChatHistory(true)}
              title="Open chat history"
              aria-label="Open chat history"
              className="mb-3 flex size-9 items-center justify-center rounded-lg hover:bg-secondary transition"
            >
              <img src={mascot} alt="Nexus AI" className="size-8 object-contain" />
            </button>
            <button
              onClick={async () => { await createSession(); setShowChatHistory(true) }}
              title="New chat"
              aria-label="New chat"
              className="mb-1 flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-secondary hover:text-foreground transition"
            >
              <Plus size={17} />
            </button>
            <button
              onClick={() => setShowChatHistory(true)}
              title="Search chats"
              aria-label="Search chats"
              className="flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-secondary hover:text-foreground transition"
            >
              <Search size={16} />
            </button>
            <div className="my-2 h-px w-6 bg-border" />
            <nav aria-label="Recent chats" className="flex w-full flex-col items-center gap-1 overflow-y-auto px-1">
              {sessions.slice(0, 9).map((chat) => {
                const label = (chat.title.trim().slice(0, 2) || '•').toUpperCase()
                const active = chat.id === activeSessionId
                return (
                  <button
                    key={chat.id}
                    onClick={() => setActiveSession(chat.id)}
                    title={chat.title || 'Untitled chat'}
                    aria-label={`Open chat: ${chat.title || 'Untitled chat'}`}
                    aria-current={active ? 'true' : undefined}
                    className={`flex size-8 shrink-0 items-center justify-center rounded-lg text-[9px] font-bold tracking-tight transition ${
                      active ? 'bg-foreground text-background' : 'bg-secondary/70 text-muted-foreground hover:bg-secondary hover:text-foreground'
                    }`}
                  >
                    <span className="max-w-6 truncate">{label}</span>
                  </button>
                )
              })}
            </nav>
            <div className="mt-auto">
              <button
                onClick={() => setShowSettings(true)}
                title="Settings"
                aria-label="Settings"
                className="flex size-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-secondary hover:text-foreground transition"
              >
                <Settings size={16} />
              </button>
            </div>
          </aside>
        )}

        <div className="flex-1 flex flex-col min-w-0 bg-background" style={{ minWidth: '400px' }}>
          <header className="flex items-center justify-between px-3 border-b border-border shrink-0" style={{ height: 'var(--titlebar-height)' }}>
            <div className="flex items-center gap-1 min-w-0 flex-1">
              <button
                onClick={() => setShowChatHistory(!showChatHistory)}
                className="flex items-center justify-center size-7 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition"
                title="Toggle sidebar (⌘B)"
              >
                <PanelLeft size={15} />
              </button>
              <div className="ml-1 flex min-w-0 items-center gap-2">
                <img src={mascot} alt="" className="size-7 shrink-0 object-contain" />
                <span className="truncate text-xs font-semibold tracking-tight text-foreground/85">NEXUS AI</span>
              </div>
            </div>
            <div className="flex items-center gap-0.5">
              <button
                onClick={() => setShowTerminal(value => !value)}
                className={`flex size-7 items-center justify-center rounded-md transition ${showTerminal ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-secondary'}`}
                title="Toggle terminal"
                aria-label="Toggle terminal"
                aria-pressed={showTerminal}
                data-testid="terminal-toggle"
              >
                <PanelBottom size={14} />
              </button>
              <button
                onClick={() => setShowFileExplorer(!showFileExplorer)}
                className="flex items-center justify-center size-7 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition"
                title="Toggle file explorer"
              >
                <PanelRight size={15} />
              </button>
            </div>
          </header>
          
          {/* File Tabs */}
          {openFiles.length > 0 && (
            <div className="flex items-center border-b border-border bg-card/50 px-2 gap-1">
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setShowFileEditor(true)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition cursor-pointer ${
                    showFileEditor ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:bg-secondary/50 hover:text-foreground'
                  }`}
                >
                  <FileText size={12} />
                  Editor
                </button>
                <button
                  onClick={() => setShowFileEditor(false)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition cursor-pointer ${
                    !showFileEditor ? 'bg-secondary text-foreground' : 'text-muted-foreground hover:bg-secondary/50 hover:text-foreground'
                  }`}
                >
                  <MessageSquare size={12} />
                  Chat
                </button>
              </div>
              <div className="w-px h-4 bg-border mx-2" />
              {openFiles.map((file) => (
                <button
                  key={file.path}
                  onClick={() => { setActiveFile(file.path); setShowFileEditor(true) }}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs transition ${
                    activeFile === file.path && showFileEditor
                      ? 'bg-secondary text-foreground'
                      : 'text-muted-foreground hover:bg-secondary/50 hover:text-foreground'
                  }`}
                >
                  <span className="truncate max-w-24">{file.name}</span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      closeFile(file.path)
                    }}
                    className="hover:text-foreground transition"
                  >
                    <X size={12} />
                  </button>
                </button>
              ))}
              <button
                onClick={closeAllFiles}
                className="ml-auto flex items-center gap-1 px-2 py-1.5 rounded-md text-xs text-muted-foreground hover:bg-secondary/50 hover:text-foreground transition"
              >
                <X size={12} />
                Close All
              </button>
            </div>
          )}
          
          {/* File Editor or Chat */}
          <div className="flex-1 flex flex-col min-h-0">
            {activeFile && showFileEditor ? (
              <div className="flex-1 overflow-hidden">
                <MonacoEditor
                  value={openFiles.find(f => f.path === activeFile)?.content || ''}
                  onChange={(value) => {
                    setOpenFiles(openFiles.map(f => 
                      f.path === activeFile ? { ...f, content: value } : f
                    ))
                  }}
                  language=""
                  path={activeFile}
                />
              </div>
            ) : (
              <MainChat onOpenTerminal={() => setShowTerminal(true)} />
            )}
          </div>
          {showTerminal && <TerminalPanel onClose={() => setShowTerminal(false)} onOpenSettings={() => setShowSettings(true)} />}
        </div>

        {showFileExplorer && (
          <div className="flex-shrink-0 flex flex-col border-l border-border bg-card/50" style={{ width: 'var(--sidebar-width)' }}>
            <FileExplorer onFileOpen={handleFileOpen} />
          </div>
        )}
      </div>

      <footer className="flex items-center justify-between px-3 border-t border-border shrink-0" style={{ height: '22px' }}>
        <div className="flex items-center gap-3 text-[10px] text-muted-foreground/50">
          <span className="flex items-center gap-1.5">
            <Circle size={6} className={backendAvailable ? 'text-green-500/70' : 'text-destructive/50'} fill="currentColor" />
            <Server size={10} />
            Nexus AI v1.0.0
          </span>
        </div>
        <div className="flex items-center gap-3 text-[10px] text-muted-foreground/50">
          {session && <span>{session.messages.length} messages</span>}
          {session && <span>·</span>}
          <span>{sessions.length} session{sessions.length !== 1 ? 's' : ''}</span>
        </div>
      </footer>
      {showSettings && <SettingsPanel onClose={() => setShowSettings(false)} />}
    </div>
  )
}

export default App
