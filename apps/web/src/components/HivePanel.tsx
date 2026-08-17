import { useEffect, useState, useMemo } from 'react'
import { ChevronDown, ChevronRight, UsersRound, Square, CheckCircle2, Clock, Loader2 } from 'lucide-react'
import { api, type HiveItem } from '../lib/api'
import type { TimelineEvent } from '../hooks/useStreamChat'

interface HivePanelProps {
  events?: TimelineEvent[]
  onCancel?: (id: string) => void
}

type HiveState = 'running' | 'completed' | 'failed' | 'partial' | 'unknown'

function hiveStateColor(state: HiveState): string {
  if (state === 'running') return 'text-emerald-500'
  if (state === 'completed') return 'text-blue-500'
  if (state === 'partial') return 'text-amber-500'
  if (state === 'failed') return 'text-destructive'
  return 'text-muted-foreground'
}

function HiveStateIcon({ state }: { state: HiveState }) {
  if (state === 'running') return <Loader2 size={12} className="shrink-0 animate-spin text-emerald-500" aria-hidden="true" />
  if (state === 'completed') return <CheckCircle2 size={12} className="shrink-0 text-blue-500" aria-hidden="true" />
  if (state === 'partial') return <Clock size={12} className="shrink-0 text-amber-500" aria-hidden="true" />
  if (state === 'failed') return <Square size={12} className="shrink-0 text-destructive" aria-hidden="true" />
  return <Clock size={12} className="shrink-0 text-muted-foreground" aria-hidden="true" />
}

const STATE_LABEL: Record<HiveState, string> = {
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  partial: 'Partial',
  unknown: 'Unknown',
}

function normalizeHiveState(hive: HiveItem): HiveState {
  const status = String(hive.status || '').toLowerCase()
  if (hive.partial || status === 'partial' || status === 'degraded') return 'partial'
  if (status === 'running' || status === 'paused') return 'running'
  if (status === 'success' || status === 'succeeded' || status === 'completed') return 'completed'
  if (status === 'failed' || status === 'error' || status === 'cancelled' || status === 'canceled') return 'failed'
  return 'unknown'
}

function normalizeAgentStatus(status: string): 'completed' | 'running' | 'failed' | 'other' {
  const value = String(status || '').toLowerCase()
  if (['completed', 'success', 'succeeded'].includes(value)) return 'completed'
  if (['running', 'pending', 'paused'].includes(value)) return 'running'
  if (['failed', 'error', 'cancelled', 'canceled', 'timeout'].includes(value)) return 'failed'
  return 'other'
}

export default function HivePanel({ events = [], onCancel }: HivePanelProps) {
  const [panelExpanded, setPanelExpanded] = useState(true)
  const [hives, setHives] = useState<HiveItem[]>([])

  // Filter sub-agent events from the stream
  const subAgentEvents = useMemo(() => {
    return events.filter(event =>
      event.type.startsWith('subagent.') ||
      event.type.startsWith('hive.') ||
      event.subagent ||
      event.tool === 'subagent'
    ).filter(event => event.type !== 'TASK_COMPLETE' && event.type !== 'task_complete')
  }, [events])

  const runningHives = useMemo(() => hives.filter(h => normalizeHiveState(h) === 'running'), [hives])
  const runningSubAgents = useMemo(() => subAgentEvents.filter(e => e.status === 'running' || e.status === 'pending'), [subAgentEvents])

  useEffect(() => {
    const loadHives = async () => {
      try {
        const response = await api.hives()
        setHives(response.hives || [])
      } catch {}
    }
    loadHives()
    const interval = setInterval(loadHives, 3000)
    return () => clearInterval(interval)
  }, [])

  const handleCancel = async (id: string) => {
    try {
      await api.cancelHive(id)
      onCancel?.(id)
      const response = await api.hives()
      setHives(response.hives || [])
    } catch {}
  }

  const totalCount = runningHives.length + runningSubAgents.length

  if (hives.length === 0 && subAgentEvents.length === 0) return null

  return (
    <div className="mb-1 border border-border bg-secondary/25 text-[11px] text-muted-foreground">
      <button
        type="button"
        onClick={() => setPanelExpanded(value => !value)}
        aria-expanded={panelExpanded}
        className="flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-secondary/45"
      >
        {panelExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <span className="flex w-3 shrink-0 items-center justify-center"><UsersRound size={12} className="text-purple-500" aria-hidden="true" /></span>
        <span className="font-medium text-foreground/85">Hive{totalCount > 0 ? ` (${totalCount} active)` : ''}</span>
      </button>
      {panelExpanded && (
        <div className="border-t border-border">
          <div className="flex items-center gap-2 px-3 py-1.5">
            <span className="min-w-0 truncate text-[10px] text-muted-foreground/70">Live and recent sub-agent execution status.</span>
          </div>
          <div>
            {hives.map(hive => {
              const state = normalizeHiveState(hive)
              const isRunning = state === 'running'
              const completedAgents = hive.agents.filter(a => ['completed', 'success', 'succeeded'].includes(String(a.status || '').toLowerCase())).length
              const totalAgents = hive.agents.length
              return (
                <div key={hive.id} className="border-t border-border/60 first:border-t-0">
                  <div className="flex w-full items-center gap-1.5 px-3 py-1.5">
                    <span className="flex w-4 shrink-0 items-center justify-center"><HiveStateIcon state={state} /></span>
                    <span className="min-w-0 flex-1 truncate text-[11px] font-medium text-foreground">
                      Hive {hive.id.slice(0, 8)}
                    </span>
                    <span className="ml-auto flex shrink-0 items-center gap-2 text-[10px]">
                      <span className={`font-medium ${hiveStateColor(state)}`}>{STATE_LABEL[state]}</span>
                      <span className="text-muted-foreground/80">{completedAgents}/{totalAgents} agents</span>
                      {isRunning && (
                        <button
                          type="button"
                          onClick={() => handleCancel(hive.id)}
                          className="text-destructive hover:text-destructive/80"
                          aria-label="Cancel hive"
                        >
                          <Square size={10} />
                        </button>
                      )}
                    </span>
                  </div>
                  {hive.agents.length > 0 && (
                    <div className="border-t border-border/50 bg-background/40 px-3 py-1.5 text-[10px] text-muted-foreground/70">
                      {hive.agents.map((agent, idx) => (
                        <div key={idx} className="flex items-center gap-2 py-0.5">
                          <span className={`w-5 h-5 flex items-center justify-center rounded-full text-[9px] font-bold ${
                            normalizeAgentStatus(agent.status) === 'completed' ? 'bg-emerald-100 text-emerald-600' :
                            normalizeAgentStatus(agent.status) === 'running' ? 'bg-blue-100 text-blue-600' :
                            normalizeAgentStatus(agent.status) === 'failed' ? 'bg-red-100 text-red-600' :
                            'bg-gray-100 text-gray-600'
                          }`}>
                            {agent.persona[0]}
                          </span>
                          <span className="flex-1 truncate">{agent.persona}</span>
                          <span className={`capitalize ${normalizeAgentStatus(agent.status) === 'completed' ? 'text-emerald-600' : normalizeAgentStatus(agent.status) === 'running' ? 'text-blue-600' : normalizeAgentStatus(agent.status) === 'failed' ? 'text-destructive' : 'text-muted-foreground'}`}>
                            {agent.status}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
            {runningSubAgents.map(event => (
              <div key={event.id} className="border-t border-border/60 first:border-t-0">
                <div className="flex w-full items-center gap-1.5 px-3 py-1.5">
                  <span className="flex w-4 shrink-0 items-center justify-center"><Loader2 size={12} className="animate-spin text-purple-500" aria-hidden="true" /></span>
                  <span className="min-w-0 flex-1 truncate text-[11px] font-medium text-foreground">
                    {event.subagent || event.title || event.tool || 'Sub-agent'}
                  </span>
                  <span className="ml-auto flex shrink-0 items-center gap-2 text-[10px]">
                    <span className="font-medium text-purple-500">Running</span>
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
