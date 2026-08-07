import { useState, useRef, useCallback, useEffect } from 'react'
import { parseSseStream, type SseFrame } from '../lib/sse'

export interface TimelineEvent {
  id: string
  type: string
  section: SectionKey
  title: string
  status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled' | 'blocked' | 'skipped' | 'timed_out'
  timestamp: number
  runId?: string
  parentId?: string
  attempt?: number
  tool?: string
  command?: string
  path?: string
  cwd?: string
  summary?: string
  lines?: string[]
  output?: string
  error?: string
  exitCode?: number
  durationMs?: number
  query?: string
  sources?: string[]
  target?: string
  server?: string
  mcpTool?: string
  lineStart?: number
  lineEnd?: number
  kind?: string
  action?: string
  skill?: string
  subagent?: string
  stage?: string
  visibility?: string
  startTime?: number
  items?: string[]
  planType?: 'simple' | 'advanced'
  phases?: Array<{ title: string; subgoals: string[] }>
  sequence?: number
  checkpointId?: string
  startedAt?: number
  finishedAt?: number
  updatedAt?: number
  attemptStartedAt?: number
}

export type SectionKey =
  | 'thinking'
  | 'planning'
  | 'searching'
  | 'files'
  | 'editing'
  | 'terminal'
  | 'tests'
  | 'git'
  | 'review'

interface StreamState {
  events: TimelineEvent[]
  content: string
  thinkingText: string
  isThinking: boolean
  thinkingDone: boolean
  isProcessing: boolean
  error: string | null
  pendingApproval: PendingApproval | null
  recoveredActivity: boolean
  replayGap: { afterSequence: number; oldestSequence: number; nextSequence: number } | null
}

export type ConversationHistoryMessage = { role: 'user' | 'assistant'; content: string }

function emptyStreamState(): StreamState {
  return {
    events: [], content: '', thinkingText: '',
    isThinking: false, thinkingDone: false, isProcessing: false,
    error: null, pendingApproval: null, recoveredActivity: false, replayGap: null,
  }
}

export interface PendingApproval {
  requestId: string
  tool: string
  action: string
  sessionId: string | null
}

function eventTypeToSection(type: string): SectionKey {
  if (type.startsWith('plan')) return 'planning'
  if (type.startsWith('search') || type.startsWith('web.')) return 'searching'
  if (type.startsWith('file.read') || type.startsWith('file.created') || type.startsWith('file.diff')) return 'files'
  if (type.startsWith('file.edited')) return 'editing'
  if (type.startsWith('command')) return 'terminal'
  if (type.startsWith('test')) return 'tests'
  if (type.startsWith('git')) return 'git'
  if (type === 'run.completed' || type === 'run.failed' || type === 'run.cancelled' || type === 'run.timed_out') return 'review'
  if (type.startsWith('tool')) return 'planning'
  return 'planning'
}

function completedTypeForStatus(type: string, status: TimelineEvent['status']): string {
  // Some legacy producers used *.result with a terminal status. Treat that as
  // the lifecycle completion for the same stable event, never as a new row.
  if (!type.endsWith('.result') || !['success', 'failed', 'cancelled', 'timed_out'].includes(status)) return type
  const base = type.slice(0, -'.result'.length)
  return `${base}.${status === 'success' ? 'completed' : status}`
}

// ── Live-state safety caps ────────────────────────────────────────────────
// A long autonomous run emits an unbounded number of lifecycle records and a
// command such as a full test suite can stream megabytes of stdout. Both are
// held in React state, so without a hard bound the browser tab grows until it
// stalls. Keep the newest window only — the tail is what the user is reading.
export const MAX_LIVE_WORK_EVENTS = 500
export const MAX_LIVE_OUTPUT_CHARS = 256 * 1024
export const MAX_LIVE_OUTPUT_LINES = 500
export const LIVE_OUTPUT_TRUNCATION_NOTICE = '… earlier output omitted …\n'
export const MAX_REPLAY_EVENTS = 500
export const MAX_REPLAY_ATTEMPTS = 3

export function boundLiveEvents(events: TimelineEvent[]): TimelineEvent[] {
  const limit = MAX_LIVE_WORK_EVENTS
  return events.length <= limit ? events : events.slice(-limit)
}

export function boundedLiveOutput(value: string | undefined): string | undefined {
  if (!value || value.length <= MAX_LIVE_OUTPUT_CHARS) return value
  return `${LIVE_OUTPUT_TRUNCATION_NOTICE}${value.slice(-MAX_LIVE_OUTPUT_CHARS)}`
}

function boundedLiveLines(lines: string[] | undefined): string[] | undefined {
  if (!lines || lines.length <= MAX_LIVE_OUTPUT_LINES) return lines
  return lines.slice(-MAX_LIVE_OUTPUT_LINES)
}

/**
 * Replay guard. Cursor replays and live SSE can deliver the same stable event
 * twice, and a slow replay frame must never overwrite newer live state. When
 * both records carry a canonical `sequence`, only accept the update when
 * `incomingSequence >= existingSequence`; ties still apply so a re-delivered
 * terminal record can enrich the row it already produced.
 */
export function acceptsSequencedUpdate(existing: TimelineEvent | undefined, incoming: TimelineEvent): boolean {
  const existingSequence = existing?.sequence
  const incomingSequence = incoming.sequence
  if (typeof existingSequence !== 'number' || typeof incomingSequence !== 'number') return true
  return incomingSequence >= existingSequence
}

function sequenceFromRecord(raw: Record<string, any>): number | undefined {
  const sequence = Number(raw.sequence)
  return Number.isFinite(sequence) && sequence > 0 ? sequence : undefined
}

function sequenceFromFrame(frame: SseFrame): number | undefined {
  const sequence = Number(frame.id)
  return Number.isFinite(sequence) && sequence > 0 ? sequence : undefined
}

function persistedEventStatus(raw: Record<string, any>): TimelineEvent['status'] {
  const eventType = String(raw.event_type || raw.type || '').toLowerCase()
  if (eventType === 'run.timed_out' || eventType.endsWith('.timed_out')) return 'timed_out'
  const value = String(raw.status || raw.payload?.status || '').toLowerCase()
  if (value === 'success' || value === 'done' || value === 'completed' || value === 'ok') return 'success'
  if (value === 'failed' || value === 'error') return 'failed'
  if (value === 'cancelled' || value === 'canceled') return 'cancelled'
  if (value === 'blocked') return 'blocked'
  if (value === 'skipped') return 'skipped'
  if (value === 'pending') return 'pending'
  return 'running'
}

/** Convert one durable public event into the same card model used by live SSE. */
export function timelineEventFromPersisted(raw: Record<string, any>): TimelineEvent {
  const payload = raw.payload && typeof raw.payload === 'object' ? raw.payload : {}
  const details = payload.payload && typeof payload.payload === 'object' ? { ...payload.payload, ...payload } : payload
  const type = String(raw.event_type || raw.type || 'unknown')
  const status = persistedEventStatus(raw)
  const timestampValue = Number(raw.timestamp || raw.created_at || Date.now() / 1000)
  const timestamp = timestampValue > 10_000_000_000 ? timestampValue : timestampValue * 1000
  const terminal = status === 'success' || status === 'failed' || status === 'cancelled' || status === 'timed_out' || status === 'skipped'
  const id = String(raw.event_id || raw.id || `replay_${raw.sequence || timestamp}`)
  return {
    id,
    type: completedTypeForStatus(type, status),
    section: eventTypeToSection(type),
    title: String(raw.title || raw.related_tool || raw.action || details.tool || 'Work event'),
    status,
    timestamp,
    runId: raw.run_id || raw.turn_id || undefined,
    parentId: raw.parent_id || raw.parent_run_id || undefined,
    tool: raw.related_tool || raw.tool || details.tool || undefined,
    command: raw.related_command || raw.command || details.command || undefined,
    path: raw.related_files?.[0] || raw.path || details.path || undefined,
    cwd: raw.cwd || details.cwd || undefined,
    summary: raw.summary || raw.display?.summary || details.text || undefined,
    output: raw.output || raw.result || details.output || details.result || details.preview || undefined,
    error: typeof raw.error === 'string' ? raw.error : raw.error?.message,
    exitCode: typeof (raw.exit_code ?? details.exit_code) === 'number' ? (raw.exit_code ?? details.exit_code) : undefined,
    durationMs: raw.duration_ms ?? details.duration_ms,
    query: details.query || raw.query || undefined,
    sources: Array.isArray(raw.sources || details.sources) ? (raw.sources || details.sources).filter((value: unknown): value is string => typeof value === 'string' && value.length > 0) : [],
    target: raw.target || details.target || undefined,
    server: raw.server || details.server || undefined,
    mcpTool: raw.mcp_tool || details.mcp_tool || undefined,
    kind: raw.kind || details.kind || undefined,
    action: raw.action || details.action || undefined,
    skill: raw.related_skill || raw.skill || details.skill || undefined,
    subagent: raw.related_subagent || raw.subagent || details.subagent || undefined,
    stage: raw.stage || details.stage || undefined,
    visibility: raw.visibility || details.visibility || undefined,
    sequence: sequenceFromRecord(raw),
    startedAt: raw.start_time ? Number(raw.start_time) * 1000 : undefined,
    finishedAt: raw.end_time ? Number(raw.end_time) * 1000 : terminal ? timestamp : undefined,
    updatedAt: timestamp,
    attempt: typeof raw.attempt === 'number' ? raw.attempt : undefined,
    checkpointId: raw.checkpoint_id || raw.checkpointId || undefined,
  }
}

function appendActivityOutput(current: string | undefined, chunk: string): string | undefined {
  if (!chunk) return current
  if (current?.endsWith(chunk)) return current
  return boundedLiveOutput(`${current || ''}${chunk}`)
}

function completedActivityOutput(current: string | undefined, finalValue: string | undefined): string | undefined {
  if (!finalValue) return current
  return boundedLiveOutput(!current || finalValue.length >= current.length ? finalValue : current)
}

export function useStreamChat(sessionId?: string | null) {
  const streamStorageKey = sessionId ? `nexus-stream-state:${sessionId}` : ''
  const [state, setState] = useState<StreamState>(() => {
    if (typeof window === 'undefined') {
      return emptyStreamState()
    }
    try {
      // Interrupted activity belongs to one conversation.  A global key made
      // refresh/new-chat restore cards from the previously active session.
      const saved = streamStorageKey ? localStorage.getItem(streamStorageKey) : null
      if (saved) {
        const parsed = JSON.parse(saved)
        // Mark all running events as completed since the stream was broken
        const completedEvents = (parsed.events || []).map((e: TimelineEvent) => ({
          ...e,
          status: e.status === 'running' ? 'cancelled' : e.status,
          finishedAt: e.finishedAt || Date.now(),
        }))
        return {
          ...emptyStreamState(),
          events: completedEvents,
          recoveredActivity: completedEvents.length > 0,
          thinkingText: parsed.thinkingText || '',
          thinkingDone: parsed.thinkingDone || false,
        }
      }
    } catch {}
    return emptyStreamState()
  })
  const ctrlRef = useRef<AbortController | null>(null)
  const sessionIdRef = useRef<string | null>(null)
  const generationRef = useRef(0)
  const messagesRef = useRef<Array<{ role: string; content: string }>>([])
  const lastSequenceRef = useRef(0)
  const mountedSessionRef = useRef<string | null | undefined>(undefined)

  // Changing chats must clear the previous session's live state immediately,
  // before any replayed history finishes loading.
  useEffect(() => {
    const nextSessionId = sessionId || null
    const previousSessionId = mountedSessionRef.current
    mountedSessionRef.current = nextSessionId
    sessionIdRef.current = nextSessionId
    // Preserve the per-session interrupted-run snapshot during first mount;
    // only a real session change should clear the in-memory live state.
    if (previousSessionId === undefined || previousSessionId === nextSessionId) return
    ctrlRef.current?.abort()
    generationRef.current += 1
    messagesRef.current = []
    setState(emptyStreamState())
  }, [sessionId])

  // A browser refresh or a dropped SSE connection must not make the UI invent
  // its state from localStorage.  The server's ordered public event log is the
  // authority for this conversation, so replay it whenever the active session
  // is mounted or changes.  A live send can race this request; the generation
  // guard and sequence comparison prevent older replay data from clobbering it.
  useEffect(() => {
    const sid = sessionId || null
    if (!sid) return
    const generation = generationRef.current
    let cancelled = false
    void fetch(`/api/work-events?session_id=${encodeURIComponent(sid)}&limit=500`, {
      credentials: 'include',
    }).then(async response => {
      if (!response.ok) return null
      const body = await response.json()
      return { records: Array.isArray(body?.events) ? body.events : [], body }
    }).then((result: { records: any[]; body: any } | null) => {
      const records = result?.records || []
      const body = result?.body || {}
      if (cancelled || !records || generation !== generationRef.current) return
      lastSequenceRef.current = Math.max(lastSequenceRef.current, ...records.map(item => sequenceFromRecord(item) || 0))
      const replayed = records.map(timelineEventFromPersisted)
      if (!replayed.length) {
        if (body.replay_truncated) setState(s => ({ ...s, replayGap: {
          afterSequence: Number(body.after_sequence) || 0,
          oldestSequence: Number(body.oldest_sequence) || 0,
          nextSequence: Number(body.next_sequence) || 0,
        } }))
        return
      }
      const deduped = new Map<string, TimelineEvent>()
      for (const event of replayed) {
        const existing = deduped.get(event.id)
        if (!existing || acceptsSequencedUpdate(existing, event)) deduped.set(event.id, event)
      }
      setState(s => ({
        ...s,
        events: boundLiveEvents(Array.from(deduped.values()).sort((a, b) => (a.sequence || 0) - (b.sequence || 0))),
        recoveredActivity: false,
        replayGap: body.replay_truncated ? {
          afterSequence: Number(body.after_sequence) || 0,
          oldestSequence: Number(body.oldest_sequence) || 0,
          nextSequence: Number(body.next_sequence) || 0,
        } : s.replayGap,
      }))
    }).catch(() => {
      // Live chat remains usable when replay is unavailable.
    })
    return () => { cancelled = true }
  }, [sessionId])

  // Persist stream state to localStorage
  useEffect(() => {
    const toSave = {
      events: state.events,
      thinkingText: state.thinkingText,
      isThinking: state.isThinking,
      thinkingDone: state.thinkingDone,
      isProcessing: state.isProcessing,
    }
    if (streamStorageKey) localStorage.setItem(streamStorageKey, JSON.stringify(toSave))
  }, [streamStorageKey, state.events, state.thinkingText, state.isThinking, state.thinkingDone, state.isProcessing])

  // Clear persisted state when processing completes and events are empty
  useEffect(() => {
    if (!state.isProcessing && state.events.length === 0) {
      if (streamStorageKey) localStorage.removeItem(streamStorageKey)
    }
  }, [streamStorageKey, state.isProcessing, state.events.length])

  const send = useCallback(async (sessionId: string, prompt: string, options?: { showThinking?: boolean; reasoningEffort?: string; provider?: string; model?: string; profile?: string; history?: ConversationHistoryMessage[] }) => {
    const generation = ++generationRef.current
    const ctrl = new AbortController()
    ctrlRef.current = ctrl
    sessionIdRef.current = sessionId
    lastSequenceRef.current = 0

    // Clear any persisted state from previous interrupted stream
    localStorage.removeItem(`nexus-stream-state:${sessionId}`)

      setState({
      events: [], content: '', thinkingText: '',
      isThinking: false, thinkingDone: false,
      isProcessing: true, error: null,
      pendingApproval: null,
      recoveredActivity: false, replayGap: null,
    })

    try {
      const ctrl = ctrlRef.current
      const replayAfterCursor = async (cursor: number) => {
        const response = await fetch(`/api/work-events?session_id=${encodeURIComponent(sessionId)}&after_sequence=${Math.max(0, cursor)}&limit=500`, {
          credentials: 'include',
          headers: { 'Last-Event-ID': String(Math.max(0, cursor)) },
        })
        if (!response.ok) return
        const body = await response.json()
        const records = Array.isArray(body?.events) ? body.events : []
        const gap = body?.replay_truncated ? {
          afterSequence: Number(body.after_sequence) || cursor,
          oldestSequence: Number(body.oldest_sequence) || 0,
          nextSequence: Number(body.next_sequence) || 0,
        } : null
        if (typeof body?.next_sequence === 'number') lastSequenceRef.current = Math.max(lastSequenceRef.current, body.next_sequence)
        const completedRecord = [...records].reverse().find(record => ['message.completed', 'message.failed'].includes(String(record?.event_type || record?.type || '')))
        const completedPayload = completedRecord?.payload && typeof completedRecord.payload === 'object' ? completedRecord.payload : {}
        const completedText = typeof completedPayload.content === 'string'
          ? completedPayload.content
          : completedPayload.payload && typeof completedPayload.payload.content === 'string' ? completedPayload.payload.content : ''
        if (completedText) {
          messagesRef.current = [...messagesRef.current.filter(message => message.role !== 'assistant'), { role: 'assistant', content: completedText }].slice(-12)
        }
        const replayed = records.map(timelineEventFromPersisted)
        if (!replayed.length) {
          if (gap) setState(s => ({ ...s, replayGap: gap }))
          return
        }
        setState(s => {
          const merged = new Map(s.events.map(event => [event.id, event]))
          for (const event of replayed) {
            const existing = merged.get(event.id)
            if (!existing || acceptsSequencedUpdate(existing, event)) merged.set(event.id, event)
          }
          return {
            ...s,
            content: completedText && completedText.length >= s.content.length ? completedText : s.content,
            error: completedRecord && String(completedRecord.event_type || completedRecord.type || '') === 'message.failed' && completedText
              ? 'The response was interrupted; the partial answer was recovered.'
              : s.error,
            events: boundLiveEvents(Array.from(merged.values()).sort((a, b) => (a.sequence || 0) - (b.sequence || 0))),
            recoveredActivity: true,
            replayGap: gap || s.replayGap,
          }
        })
      }
      // Client-side timeout: if the backend stalls (no SSE data for minutes),
      // abort instead of hanging the GUI forever on "isProcessing".
      const timeoutMs = 90000
      const timer = setTimeout(() => ctrl.abort(), timeoutMs)
      // Carry conversation history to the backend so the agent keeps context
      // across turns instead of starting blank every time.
      const history = (options?.history || messagesRef.current).slice(-12)
      const turnId = `turn_${Date.now()}_${Math.random().toString(16).slice(2, 10)}`
      const res = await fetch('/api/chat', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          turn_id: turnId,
          prompt,
          messages: history,
          stream: true,
          canonical_events: true,
          timeout_seconds: 120,
          provider: options?.provider,
          model: options?.model,
          profile: options?.profile,
          show_thinking: options?.showThinking ?? false,
          reasoning_effort: options?.reasoningEffort || 'medium',
        }),
        signal: ctrl.signal,
      })
      clearTimeout(timer)

      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }))
        setState(s => ({ ...s, isProcessing: false, error: body.detail || `Request failed: ${res.status}` }))
        return
      }

      const reader = res.body?.getReader()
      if (!reader) {
        setState(s => ({ ...s, isProcessing: false, error: 'No response body' }))
        return
      }

      parseSseStream(
        reader,
        (frame: SseFrame) => {
          if (generation !== generationRef.current) return
          if (frame.event === 'thinking') {
            try {
              const td = JSON.parse(frame.data)
              const delta = td.delta || ''
              setState(s => ({
                ...s,
                isThinking: true,
                thinkingText: s.thinkingText + delta,
              }))
            } catch {}
          } else if (frame.event === 'thinking_done') {
            setState(s => ({ ...s, isThinking: false, thinkingDone: true }))
          } else if (frame.event === 'nexus.event' || frame.event === 'work_event') {
            try {
              const streamed = JSON.parse(frame.data)
              // `/api/chat` wraps live lifecycle records in a `work_event`
              // SSE frame. Older streams send the event directly as
              // `nexus.event`; support both shapes so real Plan/tool cards
              // cannot disappear at the transport boundary.
              const raw = streamed && typeof streamed.event === 'object' ? streamed.event : streamed
              const payload = raw.payload && typeof raw.payload === 'object' ? raw.payload : {}
              // Canonical events retain the producer payload under
              // `payload.payload`; accept both levels for live and replayed
              // activity records.
              const details = payload.payload && typeof payload.payload === 'object'
                ? { ...payload.payload, ...payload }
                : payload
              const toolName = raw.related_tool || raw.tool || raw.name || details.tool || details.name
              const canonicalType = String(raw.event_type || raw.type || 'unknown')
              // A plan step is bookkeeping for a real tool call. Render it as
              // that actual operation (search, terminal, file, etc.) so a
              // web search never appears as a misleading second Plan card.
              const toolKind = /search|web_search/i.test(String(toolName || '')) ? 'search'
                : /^(bash|run_command|terminal|shell)$/i.test(String(toolName || '')) ? 'command'
                  : /read|write|file|creating|modifying|deleting/i.test(String(toolName || '')) ? 'file'
                    : /mcp/i.test(String(toolName || '') + ' ' + String(details.kind || '')) ? 'tool'
                      : /hive|subagent|agent/i.test(String(toolName || '') + ' ' + String(details.kind || '')) ? 'subagent'
                  : ''
              const sourceType = canonicalType.startsWith('plan.step.') && toolKind
                ? `${toolKind}.${canonicalType.endsWith('.completed') ? 'completed' : canonicalType.endsWith('.failed') ? 'failed' : 'started'}`
                : canonicalType
              const eventStatus = String(raw.status || details.status || details.target || '').toLowerCase()
              const status: TimelineEvent['status'] = eventStatus === 'success' || eventStatus === 'done' || eventStatus === 'completed' || eventStatus === 'ok' ? 'success'
                : eventStatus === 'failed' || eventStatus === 'error' ? 'failed'
                : eventStatus === 'cancelled' ? 'cancelled'
                : canonicalType === 'run.timed_out' ? 'timed_out'
                : eventStatus === 'blocked' ? 'blocked'
                : eventStatus === 'skipped' ? 'skipped'
                : raw.status === 'pending' ? 'pending'
                : 'running'
              const type = completedTypeForStatus(sourceType, status)
              const sourcePayload = Array.isArray(raw.sources) ? raw.sources : details.sources
              const sources = Array.isArray(sourcePayload)
                ? sourcePayload.filter((source: unknown): source is string => typeof source === 'string' && source.length > 0)
                : []
              const rawExitCode = raw.exit_code ?? payload.exit_code
              const frameSequence = sequenceFromFrame(frame)
              const event: TimelineEvent = {
                id: raw.event_id || raw.id || `evt_${Date.now()}`,
                type,
                section: eventTypeToSection(type),
                title: raw.title || raw.related_tool || raw.action || 'Work event',
                status,
                timestamp: raw.timestamp ? raw.timestamp * 1000 : Date.now(),
                tool: toolName,
                command: raw.related_command || raw.command || details.command,
                path: raw.related_files?.[0] || raw.path || details.path,
                cwd: raw.cwd || details.cwd,
                summary: raw.summary || raw.display?.summary || details.text,
                output: raw.output || raw.result || details.output || details.result || details.preview,
                error: raw.error?.message,
                exitCode: typeof rawExitCode === 'number' ? rawExitCode : undefined,
                durationMs: raw.duration_ms ?? details.duration_ms,
                query: details.query || raw.query || (toolKind === 'search' ? details.target || raw.target : undefined),
                sources,
                target: raw.target || details.target,
                server: raw.server || details.server,
                mcpTool: raw.mcp_tool || details.mcp_tool,
                lineStart: Number.isFinite(details.line_start) ? details.line_start : Number.isFinite(details.start_line) ? details.start_line : undefined,
                lineEnd: Number.isFinite(details.line_end) ? details.line_end : Number.isFinite(details.end_line) ? details.end_line : undefined,
                kind: raw.kind || details.kind,
                action: raw.action || details.action,
                skill: raw.related_skill || raw.skill || details.skill,
                subagent: raw.related_subagent || raw.subagent || details.subagent,
                stage: raw.stage || details.stage,
                visibility: raw.visibility || details.visibility,
                items: Array.isArray(details.items) ? details.items.filter((item: unknown): item is string => typeof item === 'string' && item.trim().length > 0) : undefined,
                planType: payload.plan_type === 'advanced' ? 'advanced' : payload.plan_type === 'simple' ? 'simple' : undefined,
                phases: Array.isArray(payload.phases) ? payload.phases
                  .filter((phase: unknown): phase is { title?: unknown; subgoals?: unknown } => !!phase && typeof phase === 'object')
                  .map((phase: { title?: unknown; subgoals?: unknown }) => ({ title: typeof phase.title === 'string' ? phase.title : 'Phase', subgoals: Array.isArray(phase.subgoals) ? phase.subgoals.filter((goal: unknown): goal is string => typeof goal === 'string') : [] }))
                  : undefined,
                startTime: (raw.start_time ?? details.start_time) ? (raw.start_time ?? details.start_time) * 1000 : undefined,
                startedAt: (raw.start_time ?? details.start_time) ? (raw.start_time ?? details.start_time) * 1000 : undefined,
                finishedAt: (raw.end_time ?? details.end_time) ? (raw.end_time ?? details.end_time) * 1000
                  : (status === 'success' || status === 'failed' || status === 'cancelled' || status === 'timed_out' || status === 'skipped')
                    ? (raw.timestamp ? raw.timestamp * 1000 : Date.now())
                    : undefined,
                updatedAt: raw.timestamp ? raw.timestamp * 1000 : Date.now(),
                attemptStartedAt: raw.attempt_started_at ? raw.attempt_started_at * 1000 : undefined,
                runId: raw.run_id || raw.turn_id || undefined,
                parentId: raw.parent_id || raw.parent_run_id || undefined,
                attempt: typeof raw.attempt === 'number' ? raw.attempt : typeof details.attempt === 'number' ? details.attempt : undefined,
                sequence: sequenceFromRecord(raw) ?? frameSequence,
                checkpointId: typeof raw.checkpoint_id === 'string' ? raw.checkpoint_id
                  : typeof raw.checkpointId === 'string' ? raw.checkpointId
                    : typeof details.checkpoint_id === 'string' ? details.checkpoint_id
                      : typeof details.checkpointId === 'string' ? details.checkpointId : undefined,
              }
              if (frameSequence !== undefined) lastSequenceRef.current = Math.max(lastSequenceRef.current, frameSequence)
              const completedText = (canonicalType === 'message.completed' || canonicalType === 'message.failed')
                ? (typeof payload.content === 'string' ? payload.content : payload.payload && typeof payload.payload.content === 'string' ? payload.payload.content : '')
                : ''
              if (completedText) {
                messagesRef.current = [...messagesRef.current.filter(message => message.role !== 'assistant'), { role: 'assistant', content: completedText }].slice(-12)
                setState(s => ({
                  ...s,
                  content: completedText.length >= s.content.length ? completedText : s.content,
                  error: canonicalType === 'message.failed' ? 'The response was interrupted; the partial answer was recovered.' : s.error,
                }))
              }

              const isAppend = Boolean(raw.append || payload.append)
                || typeof raw.chunk === 'string' || typeof payload.chunk === 'string'
              const chunk = String(
                raw.delta || raw.chunk || payload.chunk || raw.payload?.data
                || raw.output || raw.result || payload.output || payload.result || raw.summary || ''
              )

              // ── Co-Pilot (ask mode) interactive tool approval ──
              if (raw.event_type === 'tool.approval_request') {
                const ap = payload && typeof payload === 'object' ? payload : {}
                setState(s => ({
                  ...s,
                  pendingApproval: {
                    requestId: String(ap.request_id || raw.event_id || ''),
                    tool: String(ap.tool || raw.related_tool || raw.tool || 'command'),
                    action: String(ap.action || ap.command || ''),
                    sessionId: sessionIdRef.current,
                  },
                }))
                return
              }

              if (isAppend || type === 'command.stdout' || type === 'command.stderr' || type === 'command.started') {
                setState(s => {
                  const existing = s.events.find(e => e.id === event.id)
                  if (!existing) {
                    return {
                      ...s,
                      events: boundLiveEvents([...s.events, {
                        ...event,
                        status: 'running',
                        output: boundedLiveOutput(chunk || event.output),
                        lines: chunk ? [chunk] : [],
                      }]),
                    }
                  }
                  // Stale replay frames never clobber newer live state.
                  if (!acceptsSequencedUpdate(existing, event)) return s
                  const output = appendActivityOutput(existing.output || existing.lines?.join(''), chunk)
                  return {
                    ...s,
                    events: s.events.map(e => e.id === event.id
                      ? {
                          ...e,
                          ...event,
                          status: 'running',
                          startTime: e.startTime || event.startTime || e.timestamp,
                          startedAt: e.startedAt || event.startedAt || e.startTime || e.timestamp,
                          finishedAt: e.finishedAt,
                          updatedAt: event.updatedAt || e.updatedAt || event.timestamp || e.timestamp,
                          attemptStartedAt: e.attemptStartedAt || event.attemptStartedAt,
                          output,
                          lines: boundedLiveLines(chunk ? [...(e.lines || []), chunk] : e.lines),
                        }
                      : e),
                  }
                })
                return
              }

              if (status === 'success' || status === 'failed' || status === 'cancelled' || status === 'timed_out') {
                const baseType = type.replace('.completed', '').replace('.failed', '').replace('.cancelled', '').replace('.timed_out', '')
                setState(s => {
                  const completionTarget = event.command || event.path || event.query || event.tool || event.skill || event.subagent
                  const matched = s.events.find(e => e.id === event.id) || s.events.find(e =>
                    e.type.replace('.started', '') === baseType &&
                    e.status === 'running' &&
                    (!e.runId || !event.runId || e.runId === event.runId) &&
                    (!completionTarget || [e.command, e.path, e.query, e.tool, e.skill, e.subagent].includes(completionTarget))
                  )
                  if (matched) {
                    // Stale replay frames never clobber newer live state.
                    if (!acceptsSequencedUpdate(matched, event)) return s
                    const startedAt = matched.startedAt || matched.startTime || matched.timestamp
                    const finishedAt = event.finishedAt || event.timestamp
                    const durationMs = event.durationMs ?? matched.durationMs ?? Math.max(0, finishedAt - startedAt)
                    return {
                      ...s,
                      events: s.events.map(e =>
                        e.id === matched.id
                          ? {
                              ...e,
                              status,
                              summary: event.summary || e.summary,
                              command: event.command || e.command,
                              path: event.path || e.path,
                              cwd: event.cwd || e.cwd,
                              output: completedActivityOutput(e.output || e.lines?.join(''), event.output),
                              error: event.error || e.error,
                              exitCode: event.exitCode ?? e.exitCode,
                              sources: event.sources?.length ? event.sources : e.sources,
                              target: event.target || e.target,
                              server: event.server || e.server,
                              mcpTool: event.mcpTool || e.mcpTool,
                              lineStart: event.lineStart ?? e.lineStart,
                              lineEnd: event.lineEnd ?? e.lineEnd,
                              durationMs,
                              startTime: startedAt,
                              startedAt,
                              finishedAt: e.finishedAt || finishedAt,
                              updatedAt: event.updatedAt || event.timestamp,
                              attemptStartedAt: e.attemptStartedAt || event.attemptStartedAt,
                              sequence: event.sequence ?? e.sequence,
                            }
                          : e
                      ),
                    }
                  }
                  return { ...s, events: boundLiveEvents([...s.events, { ...event, status }]) }
                })
                return
              }

              setState(s => {
                // Stable-id dedupe: the latest update for a known event wins
                // instead of appending a duplicate row.
                const existing = s.events.find(e => e.id === event.id)
                if (existing) {
                  if (!acceptsSequencedUpdate(existing, event)) return s
                  return {
                    ...s,
                    events: s.events.map(e => e.id === event.id ? {
                      ...e,
                      ...event,
                      startedAt: e.startedAt || event.startedAt || e.startTime || e.timestamp,
                      finishedAt: e.finishedAt || event.finishedAt,
                      updatedAt: event.updatedAt || event.timestamp,
                      attemptStartedAt: e.attemptStartedAt || event.attemptStartedAt,
                    } : e),
                  }
                }
                return { ...s, events: boundLiveEvents([...s.events, event]) }
              })
            } catch {}
          } else if (frame.event === 'nexus.replay_required') {
            try {
              const payload = JSON.parse(frame.data)
              void replayAfterCursor(Number(payload?.after_sequence) || lastSequenceRef.current)
            } catch {
              void replayAfterCursor(lastSequenceRef.current)
            }
          } else if (frame.event === 'error') {
            setState(s => ({ ...s, error: frame.data || 'Stream error' }))
          } else if (frame.event === 'message' || frame.event === 'content' || !frame.event) {
            // The API uses explicit SSE `message` frames. Previously this hook
            // only consumed unlabelled data, so Nexus finished on the server
            // but the visible chat stayed on the user's message forever.
            let text = frame.data
            try {
              const payload = JSON.parse(frame.data)
              if (payload && typeof payload.content === 'string') text = payload.content
            } catch {}
            if (text) {
              setState(s => ({ ...s, content: s.content + text }))
              // Keep a rolling transcript so the next /api/chat call can send
              // real conversation history back to the backend.
              messagesRef.current = [
                ...messagesRef.current.slice(-11),
                { role: 'assistant', content: text },
              ]
            }
          }
        },
        () => {
          if (generation !== generationRef.current) return
          setState(s => ({ ...s, isProcessing: false, isThinking: false }))
        },
        (err) => {
          if (generation !== generationRef.current) return
          if (err !== 'The user aborted a request.') {
            void replayAfterCursor(lastSequenceRef.current).finally(() => {
              if (generation === generationRef.current) {
                setState(s => ({ ...s, isProcessing: false, isThinking: false, recoveredActivity: true, error: `Live stream disconnected; recovered saved activity. ${err}` }))
              }
            })
          }
        }
      )
    } catch (err: any) {
      if (generation !== generationRef.current) return
      if (err.name !== 'AbortError') {
        setState(s => ({ ...s, isProcessing: false, isThinking: false, error: err.message }))
      }
    }
  }, [])

  const respondApproval = useCallback(async (decision: 'yes' | 'no' | 'save') => {
    const approval = state.pendingApproval
    if (!approval) return
    setState(s => ({ ...s, pendingApproval: null }))
    try {
      await fetch('/api/approve', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          request_id: approval.requestId,
          decision,
          session_id: approval.sessionId,
          command: approval.action,
        }),
      })
    } catch {
      // Best-effort; the agent side times out the request if it fails.
    }
  }, [state.pendingApproval])

  const cancel = useCallback((requestedRunId?: string) => {
    const currentRunId = state.events.find(event => event.runId)?.runId
    const runId = requestedRunId || currentRunId
    if (!requestedRunId || requestedRunId === currentRunId) {
      ctrlRef.current?.abort()
      generationRef.current += 1
    }
    const sessionId = sessionIdRef.current
    if (sessionId) {
      // Aborting the browser stream alone leaves the agent running on the
      // server. Notify the server as well so Stop means stop everywhere.
      const suffix = runId ? `?turn_id=${encodeURIComponent(runId)}` : ''
      void fetch(`/api/chat/${encodeURIComponent(sessionId)}/cancel${suffix}`, {
        method: 'POST',
        credentials: 'include',
      })
    }
    if (!requestedRunId || requestedRunId === currentRunId) {
      setState(s => ({ ...s, isProcessing: false, isThinking: false }))
    }
  }, [state.events])

  const reset = useCallback(() => {
    const oldSessionId = sessionIdRef.current
    ctrlRef.current = null
    sessionIdRef.current = null
    generationRef.current += 1
    if (oldSessionId) localStorage.removeItem(`nexus-stream-state:${oldSessionId}`)
    setState({ events: [], content: '', thinkingText: '', isThinking: false, thinkingDone: false, isProcessing: false, error: null, pendingApproval: null, recoveredActivity: false, replayGap: null })
  }, [])

  return { ...state, send, cancel, reset, respondApproval }
}
