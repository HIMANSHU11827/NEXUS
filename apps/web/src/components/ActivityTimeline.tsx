import { useState, useEffect, useRef } from 'react'
import { Loader2, CheckCircle, ChevronDown, ChevronRight, Brain, Terminal, Globe, FileEdit, Search, Code } from 'lucide-react'
import type { TimelineEvent } from '../hooks/useStreamChat'

function AnimatedThinking({ text }: { text: string }) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [text.length])

  if (!text) {
    return (
      <div className="flex items-center gap-2 py-1">
        <div className="flex gap-1">
          <span className="size-1.5 rounded-full bg-foreground/30 animate-bounce" style={{ animationDelay: '0ms' }} />
          <span className="size-1.5 rounded-full bg-foreground/30 animate-bounce" style={{ animationDelay: '150ms' }} />
          <span className="size-1.5 rounded-full bg-foreground/30 animate-bounce" style={{ animationDelay: '300ms' }} />
        </div>
        <span className="text-xs text-muted-foreground/50 italic">Thinking...</span>
      </div>
    )
  }

  return (
    <div className="relative">
      <div className="text-xs text-foreground/60 leading-relaxed whitespace-pre-wrap max-h-[200px] overflow-y-auto">
        {text}
        <span className="inline-block w-[2px] h-[14px] bg-foreground/40 ml-0.5 animate-pulse align-text-bottom" />
      </div>
      <div ref={endRef} />
    </div>
  )
}

function ThoughtsCollapsible({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border border-border/50 rounded-lg overflow-hidden bg-secondary/20">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-secondary/40 transition text-left"
      >
        {open ? <ChevronDown size={12} className="text-muted-foreground/50 shrink-0" /> : <ChevronRight size={12} className="text-muted-foreground/50 shrink-0" />}
        <Brain size={13} className="text-muted-foreground/50 shrink-0" />
        <span className="text-xs font-medium text-muted-foreground/70">Show thoughts</span>
      </button>
      {open && (
        <div className="px-3 pb-3 pt-1 text-xs text-muted-foreground/60 leading-relaxed whitespace-pre-wrap border-t border-border/30">
          {text}
        </div>
      )}
    </div>
  )
}

function toolIcon(type: string) {
  if (type.startsWith('command')) return Terminal
  if (type.startsWith('file')) return FileEdit
  if (type.startsWith('search') || type.startsWith('web')) return Search
  if (type.startsWith('test')) return Code
  if (type.startsWith('tool')) return Globe
  return Code
}

export default function ActivityTimeline({
  events,
  thinkingText,
  isThinking,
  thinkingDone,
  isWorking,
}: {
  events: TimelineEvent[]
  thinkingText: string
  isThinking: boolean
  thinkingDone: boolean
  isWorking?: boolean
}) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [events.length, thinkingText.length])

  if (!isThinking && !thinkingDone && !isWorking && events.length === 0) return null

  return (
    <div className="mx-auto px-1" style={{ maxWidth: 'var(--composer-width)' }}>
      <div className="border border-border rounded-xl bg-secondary/30">
        <div className="px-4 py-3 border-b border-border flex items-center gap-2">
          {(isThinking || isWorking || events.some(e => e.status === 'running')) ? (
            <Loader2 size={12} className="animate-spin text-foreground/50" />
          ) : (
            <CheckCircle size={12} className="text-foreground/40" />
          )}
          <span className="text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">
            {isThinking ? 'Thinking' : isWorking ? 'Working' : 'Complete'}
          </span>
        </div>

        <div className="px-4 py-3 space-y-2">
          {isThinking && (
            <div>
              <div className="flex items-center gap-2 py-0.5">
                <Brain size={12} className="text-foreground/60 animate-pulse" />
                <span className="text-xs font-medium text-foreground/70">Thinking</span>
              </div>
              <div className="ml-4 pl-3 border-l border-border/50 py-1">
                <AnimatedThinking text={thinkingText} />
              </div>
            </div>
          )}

          {thinkingDone && thinkingText && (
            <div>
              <div className="flex items-center gap-2 py-0.5">
                <Brain size={12} className="text-foreground/50" />
                <span className="text-xs font-medium text-foreground/70">Thoughts</span>
                <CheckCircle size={10} className="text-foreground/40" />
              </div>
              <div className="ml-4 pl-3 py-1">
                <ThoughtsCollapsible text={thinkingText} />
              </div>
            </div>
          )}

          {isWorking && !isThinking && !thinkingDone && events.length === 0 && (
            <div className="flex items-center gap-2 py-1">
              <Loader2 size={12} className="animate-spin text-foreground/50" />
              <span className="text-xs text-muted-foreground/60">Working...</span>
            </div>
          )}

          {events.map(ev => {
            const Icon = toolIcon(ev.type)
            const isRunning = ev.status === 'running'
            const isError = ev.status === 'failed'
            const isDone = ev.status === 'success'

            if (ev.type === 'command.stdout' || ev.type === 'command.stderr') {
              return (
                <div key={ev.id} className="flex items-start gap-2 py-0.5">
                  <div className="shrink-0 mt-0.5">
                    <Terminal size={11} className="text-foreground/40" />
                  </div>
                  <div className="flex-1 min-w-0">
                    {ev.lines?.slice(-3).map((line, i) => (
                      <div key={i} className={`text-[11px] font-mono leading-relaxed whitespace-pre-wrap ${ev.type === 'command.stderr' ? 'text-destructive/60' : 'text-foreground/60'}`}>
                        {line}
                      </div>
                    ))}
                    {isRunning && (
                      <div className="flex items-center gap-1.5 text-[11px] font-mono text-muted-foreground/40">
                        <Loader2 size={9} className="animate-spin" />
                        Running...
                      </div>
                    )}
                  </div>
                </div>
              )
            }

            return (
              <div key={ev.id} className="flex items-start gap-2 py-0.5">
                <div className="shrink-0 mt-0.5">
                  {isRunning ? (
                    <Loader2 size={11} className="animate-spin text-foreground/40" />
                  ) : isError ? (
                    <span className="text-destructive/60 text-xs">✕</span>
                  ) : (
                    <Icon size={11} className="text-foreground/40" />
                  )}
                </div>
                <div className="flex-1 min-w-0 flex items-baseline gap-1.5">
                  <span className={`text-xs ${isRunning ? 'text-foreground/70' : isDone ? 'text-foreground/60' : 'text-muted-foreground/50'}`}>
                    {ev.title}
                  </span>
                  {ev.path && <span className="text-[10px] text-muted-foreground/40 font-mono truncate">{ev.path}</span>}
                  {ev.summary && isDone && <span className="text-[10px] text-muted-foreground/40 ml-auto shrink-0">{ev.summary}</span>}
                  {isError && ev.error && <span className="text-[10px] text-destructive/60 ml-auto shrink-0">{ev.error}</span>}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
