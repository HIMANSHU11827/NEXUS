import { create } from 'zustand'
import { api } from './api'
import type { TimelineEvent } from '../hooks/useStreamChat'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  activity?: TimelineEvent[]
  checkpointId?: string
  checkpointRestored?: boolean
}

export interface Session {
  id: string
  title: string
  messages: Message[]
  createdAt: number
  updatedAt: number
}

function stripLeakedToolProtocol(content: string): string {
  // Older saved messages can contain provider DSML after a parser miss. Keep
  // the user-facing sentence, but never replay raw tool markup into chat.
  return content
    .replace(/\n?\s*<\s*\/?\s*[|｜]{2}\s*DSML[\s\S]*$/i, '')
    .replace(/<param\s+[^>]*>[\s\S]*?<\/param>/gi, '')
    .replace(/<\/?(?:bash|tool_calls?|invoke|function|parameter)>\s*/gi, '')
    .trim()
}

function restoreActivity(events: Record<string, unknown>[] | undefined): TimelineEvent[] | undefined {
  if (!Array.isArray(events) || events.length === 0) return undefined
  const restored: TimelineEvent[] = []
  const positions = new Map<string, number>()
  const appendOutput = (current: string | undefined, chunk: string) =>
    !chunk ? current : current?.endsWith(chunk) ? current : `${current || ''}${chunk}`

  for (const [index, raw] of events.entries()) {
    const payload = raw.payload && typeof raw.payload === 'object' ? raw.payload as Record<string, unknown> : {}
    // Persisted canonical events nest the producer data one level deeper than
    // live SSE events. Normalize both shapes before deciding what card to show.
    const details = payload.payload && typeof payload.payload === 'object'
      ? { ...(payload.payload as Record<string, unknown>), ...payload }
      : payload
    const rawStatus = String(raw.status || 'running')
    const status: TimelineEvent['status'] = rawStatus === 'success' || rawStatus === 'done' || rawStatus === 'completed' || rawStatus === 'ok' ? 'success' : rawStatus === 'failed' || rawStatus === 'error' ? 'failed' : rawStatus === 'cancelled' || rawStatus === 'canceled' ? 'cancelled' : rawStatus === 'blocked' ? 'blocked' : rawStatus === 'skipped' ? 'skipped' : rawStatus === 'pending' ? 'pending' : 'running'
    const rawCanonicalType = String(raw.event_type || raw.type || 'unknown')
    const canonicalType = rawCanonicalType === 'progress' ? 'assistant.progress' : rawCanonicalType
    const toolName = raw.related_tool || raw.tool || raw.name || details.tool || details.name
    // `plan.step.*` is lifecycle bookkeeping. Restore the real operation
    // instead, exactly as the live stream does, so a web result never becomes
    // a misleading Plan card after a refresh.
    const toolKind = /search|web_search/i.test(String(toolName || '')) ? 'search'
      : /^(bash|run_command|terminal|shell)$/i.test(String(toolName || '')) ? 'command'
        : /read|write|file|creating|modifying|deleting/i.test(String(toolName || '')) ? 'file'
          : ''
    const type = canonicalType.startsWith('plan.step.') && toolKind
      ? `${toolKind}.${canonicalType.endsWith('.completed') ? 'completed' : canonicalType.endsWith('.failed') ? 'failed' : 'started'}`
      : canonicalType
    const files = Array.isArray(raw.related_files) ? raw.related_files : []
    const rawExitCode = raw.exit_code ?? details.exit_code
    const sourceValues = Array.isArray(raw.sources) ? raw.sources : Array.isArray(details.sources) ? details.sources : []
    const id = String(raw.event_id || raw.id || `restored-${index}`)
    const isAppend = Boolean(raw.append || payload.append)
      || typeof raw.chunk === 'string' || typeof payload.chunk === 'string'
    const chunk = String(
      raw.delta || raw.chunk || details.chunk || raw.output || raw.result
      || details.output || details.result || raw.summary || ''
    )
    const event: TimelineEvent = {
      id,
      type,
      section: type.startsWith('command') || type.startsWith('terminal') ? 'terminal' : type.startsWith('web') || type.startsWith('search') ? 'searching' : type.startsWith('file') ? 'files' : type.startsWith('plan') ? 'planning' : 'review',
      title: String(raw.title || raw.related_tool || raw.action || 'Work event'),
      status,
      timestamp: typeof raw.timestamp === 'number' ? raw.timestamp * 1000 : Date.now(),
      startedAt: typeof raw.start_time === 'number' ? raw.start_time * 1000 : typeof details.start_time === 'number' ? details.start_time * 1000 : undefined,
      finishedAt: typeof raw.end_time === 'number' ? raw.end_time * 1000 : typeof details.end_time === 'number' ? details.end_time * 1000 : undefined,
      updatedAt: typeof raw.timestamp === 'number' ? raw.timestamp * 1000 : Date.now(),
      attemptStartedAt: typeof raw.attempt_started_at === 'number' ? raw.attempt_started_at * 1000 : typeof details.attempt_started_at === 'number' ? details.attempt_started_at * 1000 : undefined,
      tool: typeof toolName === 'string' ? toolName : undefined,
      command: typeof raw.related_command === 'string' ? raw.related_command : typeof details.command === 'string' ? details.command : undefined,
      path: typeof files[0] === 'string' ? files[0] : typeof raw.path === 'string' ? raw.path : undefined,
      cwd: typeof details.cwd === 'string' ? details.cwd : undefined,
      summary: typeof raw.summary === 'string' ? raw.summary
        : typeof details.note === 'string' ? details.note
          : typeof details.text === 'string' ? details.text
            : typeof details.message === 'string' ? details.message : undefined,
      output: typeof raw.output === 'string' ? raw.output : typeof raw.result === 'string' ? raw.result : typeof details.output === 'string' ? details.output : typeof details.result === 'string' ? details.result : undefined,
      error: raw.error && typeof raw.error === 'object' && typeof (raw.error as Record<string, unknown>).message === 'string' ? String((raw.error as Record<string, unknown>).message) : undefined,
      exitCode: typeof rawExitCode === 'number' ? rawExitCode : undefined,
      durationMs: typeof raw.duration_ms === 'number' ? raw.duration_ms : undefined,
      query: typeof details.query === 'string' ? details.query : typeof raw.query === 'string' ? raw.query : undefined,
      sources: sourceValues.filter((source): source is string => typeof source === 'string'),
      target: typeof details.target === 'string' ? details.target : typeof raw.target === 'string' ? raw.target : undefined,
      action: typeof details.action === 'string' ? details.action : typeof raw.action === 'string' ? raw.action : undefined,
      stage: typeof details.stage === 'string' ? details.stage : typeof raw.stage === 'string' ? raw.stage : undefined,
      visibility: typeof details.visibility === 'string' ? details.visibility : typeof raw.visibility === 'string' ? raw.visibility : undefined,
      items: Array.isArray(details.items) ? details.items.filter((item): item is string => typeof item === 'string') : undefined,
      planType: details.plan_type === 'advanced' ? 'advanced' : details.plan_type === 'simple' ? 'simple' : undefined,
      phases: Array.isArray(details.phases) ? details.phases.filter((phase): phase is { title: string; subgoals: string[] } => Boolean(phase) && typeof phase === 'object') : undefined,
      runId: typeof raw.run_id === 'string' ? raw.run_id : typeof raw.turn_id === 'string' ? raw.turn_id : typeof details.run_id === 'string' ? details.run_id : undefined,
      parentId: typeof raw.parent_id === 'string' ? raw.parent_id : typeof details.parent_id === 'string' ? details.parent_id : undefined,
      sequence: typeof raw.sequence === 'number' ? raw.sequence : typeof details.sequence === 'number' ? details.sequence : undefined,
      kind: typeof raw.kind === 'string' ? raw.kind : typeof details.kind === 'string' ? details.kind : undefined,
      server: typeof raw.server === 'string' ? raw.server : typeof details.server === 'string' ? details.server : undefined,
      mcpTool: typeof raw.mcp_tool === 'string' ? raw.mcp_tool : typeof details.mcp_tool === 'string' ? details.mcp_tool : undefined,
      skill: typeof raw.skill === 'string' ? raw.skill : typeof details.skill === 'string' ? details.skill : undefined,
      subagent: typeof raw.subagent === 'string' ? raw.subagent : typeof details.subagent === 'string' ? details.subagent : undefined,
    }
    const existingIndex = positions.get(id)
    if (existingIndex === undefined) {
      restored.push({
        ...event,
        status: isAppend ? 'running' : event.status,
        output: isAppend ? chunk || event.output : event.output,
        lines: isAppend && chunk ? [chunk] : undefined,
      })
      positions.set(id, restored.length - 1)
      continue
    }

    const existing = restored[existingIndex]
    const existingOutput = existing.output || existing.lines?.join('')
    restored[existingIndex] = {
      ...existing,
      ...event,
      timestamp: event.timestamp || existing.timestamp,
      startedAt: existing.startedAt || event.startedAt || existing.startTime || existing.timestamp,
      finishedAt: event.finishedAt || existing.finishedAt,
      updatedAt: event.updatedAt || existing.updatedAt || event.timestamp || existing.timestamp,
      attemptStartedAt: existing.attemptStartedAt || event.attemptStartedAt,
      status: isAppend ? (existing.status === 'pending' ? 'running' : existing.status) : event.status,
      output: isAppend
        ? appendOutput(existingOutput, chunk)
        : (!event.output || existingOutput && event.output.length < existingOutput.length ? existingOutput : event.output),
      lines: isAppend && chunk ? [...(existing.lines || []), chunk] : existing.lines,
      // Lifecycle events reuse one stable ID. Keep the timestamp from the
      // original started event so restored history can show the true elapsed
      // time when the final completed event did not include duration_ms.
      startTime: existing.startTime || event.startTime || existing.timestamp,
    }
  }
  return restored
}

// Persisted work events are raw backend records. A `checkpoint.created` event
// is matched to its message by the turn id the backend stamps on both.
function checkpointIdFromRawEvents(events: Record<string, unknown>[] | undefined, turnId?: string): string | undefined {
  if (!Array.isArray(events)) return undefined
  for (const raw of events) {
    if (String(raw.event_type || raw.type || '') !== 'checkpoint.created') continue
    const checkpointId = String(raw.checkpoint_id || raw.checkpointId || '')
    if (!checkpointId) continue
    const eventTurnId = String(raw.turn_id || raw.turnId || '')
    if (turnId && eventTurnId && eventTurnId !== turnId) continue
    return checkpointId
  }
  return undefined
}

// Live stream events are normalized TimelineEvents carrying the checkpoint id
// the SSE record preserved.
function checkpointIdFromActivity(activity: TimelineEvent[] | undefined): string | undefined {
  if (!activity) return undefined
  for (const event of activity) {
    if (event.type === 'checkpoint.created' && event.checkpointId) return event.checkpointId
  }
  return undefined
}

interface AppState {
  sessions: Session[]
  activeSessionId: string | null
  isProcessing: boolean
  backendAvailable: boolean

  checkBackend: () => Promise<void>
  createSession: () => Promise<string>
  deleteSession: (id: string) => void
  renameSession: (id: string, title: string) => void
  setActiveSession: (id: string) => void
  addMessage: (sessionId: string, role: 'user' | 'assistant', content: string, activity?: TimelineEvent[]) => void
  setProcessing: (v: boolean) => void
  setMessageCheckpointRestored: (sessionId: string, messageId: string) => void
  getActiveSession: () => Session | undefined
  loadSessionsFromServer: () => Promise<void>
  loadSessionMessages: (id: string) => Promise<void>
}

export const useStore = create<AppState>((set, get) => ({
  sessions: [],
  activeSessionId: typeof window !== 'undefined' ? localStorage.getItem('nexus-active-session-id') || null : null,
  isProcessing: false,
  // Start optimistic: the API can still be booting while Vite first renders.
  // The health probe immediately corrects this if it is genuinely unavailable.
  backendAvailable: true,

  checkBackend: async () => {
    try {
      // Use a bare same-origin health request. It avoids an unnecessary JSON
      // request header on startup and works through Vite's /api proxy.
      const res = await fetch('/api/health', { credentials: 'include', cache: 'no-store' })
      if (!res.ok) throw new Error(`Health request failed: ${res.status}`)
      set({ backendAvailable: true })
    } catch {
      set({ backendAvailable: false })
    }
  },

  createSession: async () => {
    let id: string
    let title = 'New Chat'

    try {
      const res = await api.createSession()
      id = res.id
      title = res.title
    } catch {
      id = crypto.randomUUID()
    }

    const session: Session = {
      id,
      title,
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
    }
    // Keep refresh/reopen tied to the chat the user just created. Without
    // this write, reload restores the previously selected session from stale
    // localStorage even though the UI showed the new chat before refresh.
    localStorage.setItem('nexus-active-session-id', id)
    set(s => ({ sessions: [session, ...s.sessions], activeSessionId: id }))
    return id
  },

  deleteSession: (id) => {
    api.deleteSession(id).catch(() => {})
    set(s => ({
      sessions: s.sessions.filter(x => x.id !== id),
      activeSessionId: s.activeSessionId === id ? null : s.activeSessionId,
    }))
  },

  renameSession: (id, title) => {
    api.renameSession(id, title).catch(() => {})
    set(s => ({
      sessions: s.sessions.map(sess =>
        sess.id === id ? { ...sess, title, updatedAt: Date.now() } : sess
      ),
    }))
  },

  setActiveSession: (id) => {
    localStorage.setItem('nexus-active-session-id', id)
    set({ activeSessionId: id })
    get().loadSessionMessages(id)
  },

  addMessage: (sessionId, role, content, activity) => {
    set(s => ({
      sessions: s.sessions.map(sess =>
        sess.id === sessionId
          ? (() => {
              const last = sess.messages[sess.messages.length - 1]
              // The backend may have already restored the assistant text while
              // the live stream is finishing. Keep that message, but merge in
              // the completed activity rather than silently dropping it.
              if (last && content && last.role === role && last.content === content) {
                if (!activity?.length) return sess
                return {
                  ...sess,
                  messages: sess.messages.map((message, index) => index === sess.messages.length - 1
                    ? { ...message, activity, checkpointId: checkpointIdFromActivity(activity) || message.checkpointId }
                    : message),
                }
              }
              return {
                ...sess,
                messages: [...sess.messages, { id: crypto.randomUUID(), role, content, timestamp: Date.now(), activity, checkpointId: checkpointIdFromActivity(activity) }],
                updatedAt: Date.now(),
                title: sess.messages.length === 0 && role === 'user'
                  ? content.slice(0, 50)
                  : sess.title,
              }
            })()
          : sess
      ),
    }))
  },

  setProcessing: (v) => set({ isProcessing: v }),

  setMessageCheckpointRestored: (sessionId, messageId) => {
    set(s => ({
      sessions: s.sessions.map(sess =>
        sess.id === sessionId
          ? {
              ...sess,
              messages: sess.messages.map(message =>
                message.id === messageId ? { ...message, checkpointRestored: true } : message
              ),
            }
          : sess
      ),
    }))
  },

  getActiveSession: () => {
    const { sessions, activeSessionId } = get()
    return sessions.find(s => s.id === activeSessionId)
  },

  loadSessionsFromServer: async () => {
    try {
      const list = await api.listSessions()
      const sessions: Session[] = list.map(dto => ({
        id: dto.id,
        title: dto.title,
        messages: [],
        createdAt: dto.updated_at * 1000,
        updatedAt: dto.updated_at * 1000,
      }))
      const storedActiveId = get().activeSessionId
      const activeSessionId = storedActiveId && sessions.find(s => s.id === storedActiveId)
        ? storedActiveId
        : sessions[0]?.id || null
      if (activeSessionId) localStorage.setItem('nexus-active-session-id', activeSessionId)
      else localStorage.removeItem('nexus-active-session-id')
      set(s => ({
        sessions: [...sessions, ...s.sessions.filter(ss => !sessions.find(s2 => s2.id === ss.id))],
        activeSessionId,
      }))
      // Selecting the newest server session without loading it left the chat
      // looking empty after refresh. Load its history just as a sidebar click does.
      if (activeSessionId) void get().loadSessionMessages(activeSessionId)
    } catch {}
  },

  loadSessionMessages: async (id) => {
    const { sessions } = get()
    const existing = sessions.find(s => s.id === id)
    if (existing && existing.messages.length > 0) return

    try {
      const res = await api.loadSession(id)
      set(s => ({
        sessions: s.sessions.map(sess =>
          sess.id === id
            ? {
                ...sess,
                messages: res.history.map(msg => ({
                  id: crypto.randomUUID(),
                  role: msg.role,
                  content: msg.role === 'assistant' ? stripLeakedToolProtocol(msg.content) : msg.content,
                  timestamp: Date.now(),
                  activity: msg.role === 'assistant' ? restoreActivity(msg.work_events) : undefined,
                  checkpointId: msg.role === 'assistant' ? checkpointIdFromRawEvents(msg.work_events, msg.turn_id) : undefined,
                })),
              }
            : sess
        ),
      }))
    } catch {}
  },
}))
