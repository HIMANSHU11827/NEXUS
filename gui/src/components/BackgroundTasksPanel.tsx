import { useEffect, useMemo, useState } from 'react'
import Editor from '@monaco-editor/react'
import {
  ChevronDown, ChevronRight, Clock, Loader2, PauseCircle, RotateCw, StopCircle,
  Terminal, FileText, GitBranch, Users, Cpu,
} from 'lucide-react'
import type { TimelineEvent } from '../hooks/useStreamChat'
import { formatTaskDuration, taskDurationMs } from '../lib/taskDuration'

type TaskState = 'running' | 'waiting' | 'retrying' | 'paused'

interface PanelTask {
  id: string
  event: TimelineEvent
  label: string
  detail: string
  state: TaskState
  retryCount: number
  startedAt: number
  attemptStartedAt: number
}

interface BackgroundTasksPanelProps {
  events: TimelineEvent[]
  onCancel: () => void
}

const ACTIVE_STATUSES: ReadonlySet<TimelineEvent['status']> = new Set(['running', 'pending', 'blocked', 'success', 'failed', 'cancelled'])
const MAX_OUTPUT_CHARS = 12000

// A background task is a real command or agent execution the user can inspect.
// Plan steps, web results, file diffs and private diagnostics never enter here.
// Sub-agent events are handled by HivePanel, not here.
function isBackgroundExecution(event: TimelineEvent): boolean {
  if (event.visibility === 'internal') return false
  // Exclude system/meta events that shouldn't be shown
  if (event.type === 'TASK_COMPLETE' || event.type === 'task_complete') return false
  // Exclude sub-agent and hive events - they belong in HivePanel
  if (event.type.startsWith('hive.') || event.type.startsWith('subagent.') || event.subagent) return false
  // Match command events with various prefixes
  return ['command.', 'terminal.', 'test.', 'git.', 'bash.', 'run_command.'].some(prefix => event.type.startsWith(prefix))
    || (event.type.startsWith('tool.') && Boolean(event.command))
    || (event.tool && Boolean(event.command))
    || Boolean(event.command && (event.type.includes('command') || event.type.includes('terminal') || event.type.includes('bash')))
    // Match events with tool name that indicates command execution
    || ['bash', 'run_command', 'terminal', 'shell'].includes(event.tool || '')
    // Match events with section indicating terminal/command work
    || event.section === 'terminal'
}

// Stable per-run identity. Canonical events carry `run_id`; fall back to the
// event id shape `{kind}_{run}_{...}` for records produced before run_id.
function runIdOf(event: TimelineEvent): string {
  if (event.runId) return event.runId
  const parts = event.id.split('_')
  return parts.length > 1 ? parts.slice(1, -1).join('_') || event.id : event.id
}

function fileName(value: string): string {
  const normalized = value.replace(/\\/g, '/')
  return normalized.split('/').filter(Boolean).pop() || value
}

function taskLabel(event: TimelineEvent): string {
  if (event.type.startsWith('command') || event.type.startsWith('terminal')) return 'Run command'
  if (event.type.startsWith('test')) return 'Test'
  if (event.type.startsWith('git')) return 'Git'
  if (event.type.startsWith('hive') || event.type.startsWith('subagent')) return 'Sub-agent'
  if (event.type.startsWith('tool')) return event.tool || 'Tool'
  return event.title || 'Task'
}

function taskDetail(event: TimelineEvent): string {
  if (event.command) return event.command
  if (event.type.startsWith('command') || event.type.startsWith('terminal')) return event.command || ''
  if (event.path) return fileName(event.path)
  if (event.query) return event.query
  if (event.target) return event.target
  if (event.tool) return event.tool
  if (event.subagent) return event.subagent
  return event.title || ''
}

// 8s, 1m 24s, 2h 10m
function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

const STATE_LABEL: Record<TaskState, string> = {
  running: 'Running', waiting: 'Waiting', retrying: 'Retrying', paused: 'Paused',
}

function stateColor(state: TaskState): string {
  if (state === 'running') return 'text-primary'
  if (state === 'waiting') return 'text-amber-500'
  if (state === 'retrying') return 'text-amber-500'
  if (state === 'paused') return 'text-sky-500'
  return 'text-muted-foreground'
}

function StateIcon({ state }: { state: TaskState }) {
  if (state === 'waiting') return <Clock size={12} className="shrink-0 text-amber-500" aria-hidden="true" />
  if (state === 'retrying') return <RotateCw size={12} className="shrink-0 animate-spin text-amber-500" aria-hidden="true" />
  if (state === 'paused') return <PauseCircle size={12} className="shrink-0 text-sky-500" aria-hidden="true" />
  return <Loader2 size={12} className="shrink-0 animate-spin text-primary" aria-hidden="true" />
}

function TaskTypeIcon({ event }: { event: TimelineEvent }) {
  if (event.type.startsWith('command') || event.type.startsWith('terminal')) return <Terminal size={12} className="shrink-0 text-muted-foreground/70" aria-hidden="true" />
  if (event.type.startsWith('test')) return <Cpu size={12} className="shrink-0 text-muted-foreground/70" aria-hidden="true" />
  if (event.type.startsWith('git')) return <GitBranch size={12} className="shrink-0 text-muted-foreground/70" aria-hidden="true" />
  if (event.type.startsWith('hive') || event.type.startsWith('subagent')) return <Users size={12} className="shrink-0 text-purple-500/70" aria-hidden="true" />
  if (event.type.startsWith('tool')) return <Cpu size={12} className="shrink-0 text-muted-foreground/70" aria-hidden="true" />
  if (event.path) return <FileText size={12} className="shrink-0 text-muted-foreground/70" aria-hidden="true" />
  return <Loader2 size={12} className="shrink-0 text-muted-foreground/70" aria-hidden="true" />
}

function buildTasks(events: TimelineEvent[]): { tasks: PanelTask[]; retryMarkers: TimelineEvent[] } {
  const retryMarkers: TimelineEvent[] = []
  const latestById = new Map<string, TimelineEvent>()
  for (const event of events) {
    if (event.type === 'retry') {
      retryMarkers.push(event)
      continue
    }
    if (!isBackgroundExecution(event) || !ACTIVE_STATUSES.has(event.status)) continue
    const existing = latestById.get(event.id)
    if (!existing || (event.sequence ?? 0) >= (existing.sequence ?? 0)) latestById.set(event.id, event)
  }

  const tasks: PanelTask[] = Array.from(latestById.values()).map(event => {
    const runId = runIdOf(event)
    const runMarkers = retryMarkers.filter(marker => runIdOf(marker) === runId)
    const retryCount = runMarkers.length
    const startedAt = event.startedAt ?? event.startTime ?? event.timestamp
    const lastRetry = runMarkers[runMarkers.length - 1]
    const attemptStartedAt = event.attemptStartedAt ?? (lastRetry ? lastRetry.timestamp : startedAt)
    const state: TaskState = event.status === 'blocked' ? 'paused'
      : event.status === 'pending' ? 'waiting'
      : retryCount > 0 ? 'retrying'
      : 'running'
    return {
      id: event.id,
      event,
      label: taskLabel(event),
      detail: taskDetail(event),
      state,
      retryCount,
      startedAt,
      attemptStartedAt,
    }
  })
  return { tasks, retryMarkers }
}

function TaskOutput({ value }: { value: string }) {
  const bounded = value.length > MAX_OUTPUT_CHARS ? `… earlier output omitted …\n${value.slice(-MAX_OUTPUT_CHARS)}` : value
  return (
    <div className="mb-1.5">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground/60">Output</p>
      <div className="mt-0.5 max-h-48 overflow-auto rounded bg-background/70">
        <Editor
          height="200px"
          language="plaintext"
          value={bounded}
          theme="vs"
          options={{
            readOnly: true,
            minimap: { enabled: false },
            fontSize: 10,
            lineNumbers: 'off',
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 2,
            wordWrap: 'on',
            folding: false,
            renderWhitespace: 'selection',
            lineHeight: 14,
            padding: { top: 8, bottom: 8 },
          }}
        />
      </div>
    </div>
  )
}

function TaskDetails({ task, now, onCancel }: { task: PanelTask; now: number; onCancel: () => void }) {
  const event = task.event
  const output = event.output || event.lines?.filter(Boolean).join('') || ''
  return (
    <div className="border-t border-border/50 bg-background/40 px-3 py-2 text-[11px] text-foreground/75">
      {event.command && (
        <div className="mb-1.5">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground/60">Command</p>
          <div className="mt-0.5 max-h-32 overflow-auto rounded bg-background/70">
            <Editor
              height="120px"
              language="shell"
              value={event.command}
              theme="vs"
              options={{
                readOnly: true,
                minimap: { enabled: false },
                fontSize: 11,
                lineNumbers: 'off',
                scrollBeyondLastLine: false,
                automaticLayout: true,
                tabSize: 2,
                wordWrap: 'on',
                folding: false,
                renderWhitespace: 'selection',
                lineHeight: 16,
                padding: { top: 8, bottom: 8 },
              }}
            />
          </div>
        </div>
      )}
      {event.query && (
        <div className="mb-1.5">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground/60">Query</p>
          <p className="mt-0.5 break-words font-mono text-[11px]">{event.query}</p>
        </div>
      )}
      {event.path && (
        <div className="mb-1.5">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground/60">File</p>
          <p className="mt-0.5 break-words font-mono text-[11px]">{fileName(event.path)}</p>
        </div>
      )}
      {event.cwd && (
        <div className="mb-1.5">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground/60">Workspace</p>
          <p className="mt-0.5 break-words text-[11px]">{event.cwd}</p>
        </div>
      )}
      <div className="mb-1.5 flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground/80">
        <span>Started <time dateTime={new Date(task.startedAt).toISOString()}>{formatTime(task.startedAt)}</time></span>
        <span>Total <span className="tabular-nums">{formatTaskDuration(taskDurationMs({ startedAt: task.startedAt }, now) ?? 0)}</span></span>
        <span>Attempt <span className="tabular-nums">{formatTaskDuration(taskDurationMs({ startedAt: task.attemptStartedAt }, now) ?? 0)}</span></span>
        {task.retryCount > 0 && <span>Retries <span className="tabular-nums">{task.retryCount}</span></span>}
        {event.exitCode !== undefined && <span>Exit code <span className="tabular-nums">{event.exitCode}</span></span>}
      </div>
      {output && <TaskOutput value={output} />}
      {event.error && (
        <div className="mb-1.5 mt-1">
          <div className="max-h-32 overflow-auto rounded bg-destructive/5">
            <Editor
              height="120px"
              language="plaintext"
              value={event.error}
              theme="vs"
              options={{
                readOnly: true,
                minimap: { enabled: false },
                fontSize: 10,
                lineNumbers: 'off',
                scrollBeyondLastLine: false,
                automaticLayout: true,
                tabSize: 2,
                wordWrap: 'on',
                folding: false,
                renderWhitespace: 'selection',
                lineHeight: 14,
                padding: { top: 8, bottom: 8 },
              }}
            />
          </div>
        </div>
      )}
      <div className="mt-1 flex justify-end">
        <button
          type="button"
          onClick={onCancel}
          className="flex items-center gap-1 rounded border border-destructive/40 bg-destructive/5 px-2 py-1 font-medium text-destructive hover:bg-destructive/10"
        >
          <StopCircle size={12} /> Cancel
        </button>
      </div>
    </div>
  )
}

export default function BackgroundTasksPanel({ events, onCancel }: BackgroundTasksPanelProps) {
  const [panelExpanded, setPanelExpanded] = useState(true)
  const [expandedIds, setExpandedIds] = useState<Record<string, boolean>>({})
  const [now, setNow] = useState(() => Date.now())

  const { tasks } = useMemo(() => buildTasks(events), [events])

  // One shared per-second timer for every row. Stopped as soon as no active
  // task remains; torn down on unmount so nothing leaks.
  useEffect(() => {
    if (tasks.length === 0) return
    setNow(Date.now())
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [tasks.length])

  // Drop expansion state for rows that finished and were auto-removed.
  useEffect(() => {
    setExpandedIds(previous => {
      const activeIds = new Set(tasks.map(task => task.id))
      let changed = false
      const next: Record<string, boolean> = {}
      for (const [id, value] of Object.entries(previous)) {
        if (activeIds.has(id)) next[id] = value
        else changed = true
      }
      return changed ? next : previous
    })
  }, [tasks])

  const toggleTask = (id: string) => setExpandedIds(previous => ({ ...previous, [id]: !previous[id] }))

  const activeCount = tasks.length
  if (activeCount === 0) return null

  return (
    <div className="mb-1 border border-border bg-secondary/25 text-[11px] text-muted-foreground">
      <button
        type="button"
        onClick={() => setPanelExpanded(value => !value)}
        aria-expanded={panelExpanded}
        className="flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-secondary/45"
      >
        {panelExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <span className="flex w-3 shrink-0 items-center justify-center"><Loader2 size={12} className="animate-spin text-primary" aria-hidden="true" /></span>
        <span className="font-medium text-foreground/85">{activeCount} Background task{activeCount !== 1 ? 's' : ''}</span>
      </button>
      {panelExpanded && (
        <div className="border-t border-border">
          <div className="flex items-center gap-2 px-3 py-1.5">
            <span className="min-w-0 truncate text-[10px] text-muted-foreground/70">Commands, tests, git operations, and sub-agents running in background.</span>
          </div>
          <div>
            {tasks.map(task => {
              const isExpanded = Boolean(expandedIds[task.id])
              const totalElapsed = formatTaskDuration(taskDurationMs({ startedAt: task.startedAt }, now) ?? 0)
              const statusText = `${STATE_LABEL[task.state]}${task.retryCount > 0 ? ` · attempt ${task.retryCount + 1}` : ''}`
              return (
                <div key={task.id} className="border-t border-border/60 first:border-t-0">
                  <button
                    type="button"
                    onClick={() => toggleTask(task.id)}
                    onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggleTask(task.id) } }}
                    aria-expanded={isExpanded}
                    aria-label={`${STATE_LABEL[task.state]}: ${task.label}${task.detail ? ` — ${task.detail}` : ''}`}
                    className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left hover:bg-secondary/45 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/40"
                  >
                    <span className="flex w-4 shrink-0 items-center justify-center"><StateIcon state={task.state} /></span>
                    <span className="flex w-4 shrink-0 items-center justify-center"><TaskTypeIcon event={task.event} /></span>
                    <span className="min-w-0 flex-1 truncate text-[11px] font-medium text-foreground" title={`${task.label}${task.detail ? ` · ${task.detail}` : ''}`}>
                      {task.label}{task.detail ? <span className="font-normal text-muted-foreground/70"> · {task.detail}</span> : null}
                    </span>
                    <span className="ml-auto flex shrink-0 items-center gap-2 text-[10px]">
                      <span className={`font-medium ${stateColor(task.state)}`}>{statusText}</span>
                      <span className="tabular-nums text-muted-foreground/80">{totalElapsed}</span>
                      <span className="text-muted-foreground/50">{isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}</span>
                    </span>
                  </button>
                  {isExpanded && <TaskDetails task={task} now={now} onCancel={onCancel} />}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
