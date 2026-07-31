import { useState, useRef, useCallback } from 'react'
import { parseSseStream, type SseFrame } from '../lib/sse'

export interface TimelineEvent {
  id: string
  type: string
  section: SectionKey
  title: string
  status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled'
  timestamp: number
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
  if (type === 'run.completed' || type === 'run.failed' || type === 'run.cancelled') return 'review'
  if (type.startsWith('tool')) return 'planning'
  return 'planning'
}

function completedTypeForStatus(type: string, status: TimelineEvent['status']): string {
  // Some legacy producers used *.result with a terminal status. Treat that as
  // the lifecycle completion for the same stable event, never as a new row.
  if (!type.endsWith('.result') || !['success', 'failed', 'cancelled'].includes(status)) return type
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

function appendActivityOutput(current: string | undefined, chunk: string): string | undefined {
  if (!chunk) return current
  if (current?.endsWith(chunk)) return current
  return boundedLiveOutput(`${current || ''}${chunk}`)
}

function completedActivityOutput(current: string | undefined, finalValue: string | undefined): string | undefined {
  if (!finalValue) return current
  return boundedLiveOutput(!current || finalValue.length >= current.length ? finalValue : current)
}

export function useStreamChat() {
  const [state, setState] = useState<StreamState>({
    events: [], content: '', thinkingText: '',
    isThinking: false, thinkingDone: false,
    isProcessing: false, error: null,
    pendingApproval: null,
  })
  const ctrlRef = useRef<AbortController | null>(null)
  const sessionIdRef = useRef<string | null>(null)
  const messagesRef = useRef<Array<{ role: string; content: string }>>([])

  const send = useCallback(async (sessionId: string, prompt: string, options?: { showThinking?: boolean; reasoningEffort?: string }) => {
    const ctrl = new AbortController()
    ctrlRef.current = ctrl
    sessionIdRef.current = sessionId

    setState({
      events: [], content: '', thinkingText: '',
      isThinking: false, thinkingDone: false,
      isProcessing: true, error: null,
      pendingApproval: null,
    })

    try {
      const ctrl = ctrlRef.current
      // Client-side timeout: if the backend stalls (no SSE data for minutes),
      // abort instead of hanging the GUI forever on "isProcessing".
      const timeoutMs = 90000
      const timer = setTimeout(() => ctrl.abort(), timeoutMs)
      // Carry conversation history to the backend so the agent keeps context
      // across turns instead of starting blank every time.
      const history = messagesRef.current.slice(-12)
      const res = await fetch('/api/chat', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          prompt,
          messages: history,
          stream: true,
          canonical_events: true,
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
                    : ''
              const sourceType = canonicalType.startsWith('plan.step.') && toolKind
                ? `${toolKind}.${canonicalType.endsWith('.completed') ? 'completed' : canonicalType.endsWith('.failed') ? 'failed' : 'started'}`
                : canonicalType
              const status = raw.status === 'success' || raw.status === 'done' || raw.status === 'completed' ? 'success'
                : raw.status === 'failed' ? 'failed'
                : raw.status === 'cancelled' ? 'cancelled'
                : 'running'
              const type = completedTypeForStatus(sourceType, status)
              const sourcePayload = Array.isArray(raw.sources) ? raw.sources : details.sources
              const sources = Array.isArray(sourcePayload)
                ? sourcePayload.filter((source: unknown): source is string => typeof source === 'string' && source.length > 0)
                : []
              const rawExitCode = raw.exit_code ?? payload.exit_code
              const event: TimelineEvent = {
                id: raw.event_id || `evt_${Date.now()}`,
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
                durationMs: raw.duration_ms,
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
                startTime: raw.start_time ? raw.start_time * 1000 : undefined,
                sequence: typeof raw.sequence === 'number' ? raw.sequence : undefined,
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
                          output,
                          lines: boundedLiveLines(chunk ? [...(e.lines || []), chunk] : e.lines),
                        }
                      : e),
                  }
                })
                return
              }

              if (status === 'success' || status === 'failed' || status === 'cancelled') {
                const baseType = type.replace('.completed', '').replace('.failed', '').replace('.cancelled', '')
                setState(s => {
                  const completionTarget = event.command || event.path || event.query || event.tool || event.skill || event.subagent
                  const matched = s.events.find(e => e.id === event.id) || s.events.find(e =>
                    e.type.replace('.started', '') === baseType &&
                    e.status === 'running' &&
                    (!completionTarget || [e.command, e.path, e.query, e.tool, e.skill, e.subagent].includes(completionTarget))
                  )
                  if (matched) {
                    // Stale replay frames never clobber newer live state.
                    if (!acceptsSequencedUpdate(matched, event)) return s
                    const startedAt = matched.startTime || matched.timestamp
                    const durationMs = event.durationMs ?? matched.durationMs ?? Math.max(0, event.timestamp - startedAt)
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
                  return { ...s, events: s.events.map(e => e.id === event.id ? { ...e, ...event } : e) }
                }
                return { ...s, events: boundLiveEvents([...s.events, event]) }
              })
            } catch {}
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
          setState(s => ({ ...s, isProcessing: false, isThinking: false }))
        },
        (err) => {
          if (err !== 'The user aborted a request.') {
            setState(s => ({ ...s, isProcessing: false, isThinking: false, error: err }))
          }
        }
      )
    } catch (err: any) {
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

  const cancel = useCallback(() => {
    ctrlRef.current?.abort()
    const sessionId = sessionIdRef.current
    if (sessionId) {
      // Aborting the browser stream alone leaves the agent running on the
      // server. Notify the server as well so Stop means stop everywhere.
      void fetch(`/api/chat/${encodeURIComponent(sessionId)}/cancel`, {
        method: 'POST',
        credentials: 'include',
      })
    }
    setState(s => ({ ...s, isProcessing: false, isThinking: false }))
  }, [])

  const reset = useCallback(() => {
    ctrlRef.current = null
    sessionIdRef.current = null
    setState({ events: [], content: '', thinkingText: '', isThinking: false, thinkingDone: false, isProcessing: false, error: null, pendingApproval: null })
  }, [])

  return { ...state, send, cancel, reset, respondApproval }
}
