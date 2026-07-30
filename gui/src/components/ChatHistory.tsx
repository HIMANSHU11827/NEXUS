import { Plus, Search, MessageSquare, Trash2, Clock, Check, X, Pencil, Settings } from 'lucide-react'
import { useState, useEffect, useMemo, useRef } from 'react'
import { useStore } from '../lib/store'
import mascot from '../assets/nexus-mascot-brand.png'

export default function ChatHistory({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { sessions, activeSessionId, createSession, setActiveSession, deleteSession, renameSession } = useStore()
  const [searchQuery, setSearchQuery] = useState('')
  const [searchRef, setSearchRef] = useState<HTMLInputElement | null>(null)
  const [renaming, setRenaming] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const renameRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        searchRef?.focus()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [searchRef])

  useEffect(() => {
    if (renaming && renameRef.current) {
      renameRef.current.focus()
      renameRef.current.select()
    }
  }, [renaming])

  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return sessions
    const q = searchQuery.toLowerCase()
    return sessions.filter(s => s.title.toLowerCase().includes(q) || s.messages.some(m => m.content.toLowerCase().includes(q)))
  }, [sessions, searchQuery])

  const formatDate = (ts: number) => {
    const d = new Date(ts)
    const now = new Date()
    const diff = now.getTime() - d.getTime()
    if (diff < 86400000) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    if (diff < 604800000) return d.toLocaleDateString([], { weekday: 'short' })
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
  }

  const startRename = (e: React.MouseEvent, id: string, title: string) => {
    e.stopPropagation()
    setRenaming(id)
    setRenameValue(title)
  }

  const commitRename = () => {
    if (renaming && renameValue.trim()) {
      renameSession(renaming, renameValue.trim())
    }
    setRenaming(null)
  }

  const cancelRename = () => setRenaming(null)

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-border px-3 pb-2.5 pt-3">
        <div className="mb-3 flex items-center gap-2 px-1">
          <img src={mascot} alt="Nexus AI mascot" className="size-9 shrink-0 object-contain" />
          <div className="min-w-0 leading-tight">
            <p className="text-xs font-bold tracking-[0.14em] text-foreground/85">NEXUS AI</p>
            <p className="mt-0.5 text-[10px] text-muted-foreground/60">Autonomous workspace</p>
          </div>
        </div>
        <button
          onClick={createSession}
          className="w-full flex items-center justify-center gap-1.5 px-3 py-2 bg-foreground text-background rounded-lg hover:opacity-80 transition text-xs font-medium mb-2.5"
        >
          <Plus size={14} />
          <span>New Chat</span>
        </button>
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground/40 pointer-events-none" />
          <input
            ref={setSearchRef}
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search...  ⌘K"
            className="w-full pl-8 pr-3 py-1.5 bg-secondary border-0 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-ring/20 transition placeholder:text-muted-foreground/40"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full px-6 text-center">
            <MessageSquare size={20} className="text-muted-foreground/20 mb-3" />
            <p className="text-xs text-muted-foreground/50 leading-relaxed max-w-[160px]">
              No sessions yet. Start a new chat to begin.
            </p>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full px-6 text-center">
            <Search size={18} className="text-muted-foreground/20 mb-2" />
            <p className="text-xs text-muted-foreground/50">No results found.</p>
          </div>
        ) : (
          <div className="py-1">
            {filtered.map(s => (
              <div
                key={s.id}
                role="button"
                tabIndex={0}
                aria-label={`Open chat: ${s.title}`}
                aria-current={s.id === activeSessionId ? 'true' : undefined}
                data-testid={`session-${s.id}`}
                className={`group flex items-center gap-2 mx-2 px-2.5 py-2 rounded-lg cursor-pointer transition ${
                  s.id === activeSessionId ? 'bg-secondary/80' : 'hover:bg-secondary/50'
                }`}
                onClick={() => setActiveSession(s.id)}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setActiveSession(s.id) } }}
              >
                <MessageSquare size={13} className="text-muted-foreground/40 shrink-0" />
                <div className="flex-1 min-w-0">
                  {renaming === s.id ? (
                    <div className="flex items-center gap-1">
                      <input
                        ref={renameRef}
                        value={renameValue}
                        onChange={e => setRenameValue(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') commitRename(); if (e.key === 'Escape') cancelRename() }}
                        className="flex-1 bg-background border border-border rounded px-1.5 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring/30"
                        onClick={e => e.stopPropagation()}
                      />
                      <button onClick={e => { e.stopPropagation(); commitRename() }} className="size-5 flex items-center justify-center rounded hover:bg-secondary text-muted-foreground/60"><Check size={11} /></button>
                      <button onClick={e => { e.stopPropagation(); cancelRename() }} className="size-5 flex items-center justify-center rounded hover:bg-secondary text-muted-foreground/60"><X size={11} /></button>
                    </div>
                  ) : (
                    <p className="text-xs text-foreground/80 truncate font-medium">{s.title}</p>
                  )}
                  <p className="flex items-center gap-1 text-[10px] text-muted-foreground/40 mt-0.5">
                    <Clock size={9} />
                    <span>{formatDate(s.updatedAt)}</span>
                    <span className="mx-1">·</span>
                    <span>{s.messages.length} message{s.messages.length !== 1 ? 's' : ''}</span>
                  </p>
                </div>
                <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition">
                  <button
                    onClick={e => startRename(e, s.id, s.title)}
                    aria-label={`Rename chat: ${s.title}`}
                    title="Rename"
                    className="size-6 flex items-center justify-center rounded hover:bg-secondary text-muted-foreground/40 hover:text-muted-foreground transition"
                  >
                    <Pencil size={11} />
                  </button>
                  <button
                    onClick={e => { e.stopPropagation(); deleteSession(s.id) }}
                    aria-label={`Delete chat: ${s.title}`}
                    title="Delete"
                    className="size-6 flex items-center justify-center rounded hover:bg-destructive/10 text-muted-foreground/40 hover:text-destructive transition"
                  >
                    <Trash2 size={11} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="border-t border-border px-3 py-2 shrink-0">
        <button onClick={onOpenSettings} className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-secondary transition text-left text-muted-foreground/60 hover:text-muted-foreground">
          <Settings size={14} />
          <span className="text-xs">Settings</span>
        </button>
      </div>
    </div>
  )
}
