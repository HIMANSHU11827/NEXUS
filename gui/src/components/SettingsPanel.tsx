import { useEffect, useMemo, useRef, useState } from 'react'
import {
  X, Palette, Cpu, Brain, Sparkles, SlidersHorizontal, Info,
  Wrench, Puzzle, Network, UsersRound, ReceiptText, Settings2, Radio, Clock3, Monitor, ShieldCheck, Bell, Keyboard, Mic,
} from 'lucide-react'
import { api, type HiveItem, type InventoryItem, type RuntimeProviderStatus } from '../lib/api'
import { useStore } from '../lib/store'
import WorkspaceSettingsPanel from './WorkspaceSettings'
import SafetySettings from './SafetySettings'
import { McpManager } from './settings/McpManager'
import { HiveManager } from './settings/HiveManager'
import { SkillsManager } from './settings/SkillsManager'
import { ToolsManager } from './settings/ToolsManager'
import { PluginManager } from './settings/PluginManager'
import { ScheduledJobsManager } from './settings/ScheduledJobsManager'
import { GatewayManager } from './settings/GatewayManager'
import { ConfigurationPanel } from './settings/ConfigurationPanel'
import { ProviderList } from './settings/Providers'
import { EvolutionPanel } from './settings/Evolution'
import { Appearance } from './settings/Appearance'
import { MemorySettings } from './settings/Memory'
import { VoiceSettings } from './settings/Voice'
import { NotificationSettings } from './settings/Notifications'
import { BillingSettings } from './settings/Billing'
import { AboutSettings } from './settings/About'
import { KeyboardShortcuts } from './settings/KeyboardShortcuts'
import { LiveData } from './settings/LiveData'

type Section = 'appearance' | 'workspace' | 'safety' | 'notifications' | 'shortcuts' | 'voice' | 'providers' | 'memory' | 'evolution' | 'config' | 'skills' | 'tools' | 'plugins' | 'mcp' | 'hive' | 'gateway' | 'cron' | 'billing' | 'about'
type Loaded = Record<string, unknown>

const sections: Array<{ id: Section; label: string; icon: typeof Palette }> = [
  { id: 'appearance', label: 'Theme & appearance', icon: Palette },
  { id: 'workspace', label: 'Workspace', icon: Monitor },
  { id: 'safety', label: 'Safety', icon: ShieldCheck },
  { id: 'memory', label: 'Memory & context', icon: Brain },
  { id: 'voice', label: 'Voice', icon: Mic },
  { id: 'notifications', label: 'Notifications', icon: Bell },
  { id: 'shortcuts', label: 'Keyboard shortcuts', icon: Keyboard },
  { id: 'providers', label: 'Providers', icon: Cpu },
  { id: 'evolution', label: 'Evolution', icon: Sparkles },
  { id: 'config', label: 'Configuration', icon: Settings2 },
  { id: 'skills', label: 'Skills', icon: Wrench },
  { id: 'tools', label: 'Tools', icon: SlidersHorizontal },
  { id: 'plugins', label: 'Plugins', icon: Puzzle },
  { id: 'mcp', label: 'MCP', icon: Network },
  { id: 'hive', label: 'Hive', icon: UsersRound },
  { id: 'gateway', label: 'Gateway', icon: Radio },
  { id: 'cron', label: 'Scheduled jobs', icon: Clock3 },
  { id: 'billing', label: 'Billing', icon: ReceiptText },
  { id: 'about', label: 'About', icon: Info },
]


export default function SettingsPanel({ onClose }: { onClose: () => void }) {
  const { backendAvailable, sessions } = useStore()
  const [active, setActive] = useState<Section>('appearance')
  const [data, setData] = useState<Loaded>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [theme, setTheme] = useState(() => localStorage.getItem('nexus-theme') || 'light')
  const [pendingToggle, setPendingToggle] = useState('')
  const safetyDirtyRef = useRef(false)

  const navigateTo = (next: Section) => {
    if (active === 'safety' && next !== 'safety' && safetyDirtyRef.current && !window.confirm('You have unsaved Safety changes. Discard them and leave the Safety page?')) return
    setActive(next)
  }

  const closeSettings = () => {
    if (active === 'safety' && safetyDirtyRef.current && !window.confirm('You have unsaved Safety changes. Discard them and close Settings?')) return
    onClose()
  }

  useEffect(() => {
    const saved = localStorage.getItem('nexus-theme') || 'light'
    const themeClass = saved === 'dark' ? 'dark' : saved === 'light' ? '' : `theme-${saved}`
    document.documentElement.classList.remove('dark', 'theme-grey', 'theme-glass', 'theme-green', 'theme-blue', 'theme-purple')
    if (themeClass) document.documentElement.classList.add(themeClass)
  }, [])

  useEffect(() => {
    const loaders: Partial<Record<Section, () => Promise<unknown>>> = {
      providers: async () => ({ ...(await api.providers()), runtime_status: await api.status().catch(() => undefined) }), skills: api.skills, tools: api.tools, plugins: api.plugins,
      mcp: api.mcp, hive: api.hives, gateway: api.gateways, cron: api.cronJobs,
      evolution: api.evolution, config: api.state, memory: api.state,
      notifications: api.state, voice: api.voiceStatus, billing: api.billing, about: api.version,
    }
    const load = loaders[active]
    if (!load || data[active]) return
    setLoading(true); setError('')
    load().then(result => setData(current => ({ ...current, [active]: result })))
      .catch(err => setError(err instanceof Error ? err.message : 'Could not load this Nexus setting.'))
      .finally(() => setLoading(false))
  }, [active, data])

  const toggle = async (kind: string, name: string, enabled: boolean) => {
    setPendingToggle(`${kind}:${name}`); setError('')
    try {
      await api.manage(kind, name, enabled ? 'enable' : 'disable')
      setData(current => { const next = { ...current }; delete next[active]; return next })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nexus could not save this setting.')
    } finally { setPendingToggle('') }
  }

  const content = useMemo(() => {
    if (active === 'workspace') return <WorkspaceSettingsPanel state={(data.workspace as Record<string, unknown> | undefined) || {}} onSaved={() => setData(current => { const next = { ...current }; delete next.workspace; return next })} />
    if (active === 'appearance') return <Appearance theme={theme} onTheme={value => {
      setTheme(value); localStorage.setItem('nexus-theme', value);
      document.documentElement.classList.remove('dark', 'theme-grey', 'theme-glass', 'theme-green', 'theme-blue', 'theme-purple', 'theme-pink', 'theme-red', 'theme-orange')
      const themeClass = value === 'dark' ? 'dark' : value === 'light' ? '' : `theme-${value}`
      if (themeClass) document.documentElement.classList.add(themeClass)
    }} />
    if (active === 'shortcuts') return <KeyboardShortcuts />
    if (loading) return <p className="py-8 text-sm text-muted-foreground" role="status">Loading live Nexus data…</p>
    if (error) return <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive" role="alert">Could not load this section: {error}</p>
    if (active === 'providers') {
      const response = data.providers as { providers?: InventoryItem[]; runtime?: { provider?: string; model?: string }; runtime_status?: RuntimeProviderStatus } | undefined
      const providers = response?.providers || []
      if (error) {
        return <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive" role="alert">Could not load providers: {error}</p>
      }
      if (loading) {
        return <p className="py-8 text-sm text-muted-foreground" role="status">Loading providers…</p>
      }
      return providers.length ? <ProviderList providers={providers} pending={pendingToggle.replace('provider:', '')} runtimeStatus={response?.runtime_status} onToggle={(name, enabled) => toggle('provider', name, enabled)} onChanged={() => setData(current => { const next = { ...current }; delete next.providers; return next })} /> : <p className="py-8 text-sm text-muted-foreground">No provider implementations were reported.</p>
    }
    if (active === 'safety') return <SafetySettings onOpenWorkspace={() => navigateTo('workspace')} onDirtyChange={dirty => { safetyDirtyRef.current = dirty }} />
    if (active === 'memory') return <MemorySettings state={(data.memory as Record<string, unknown> | undefined) || {}} />
    if (active === 'voice') return <VoiceSettings status={(data.voice as { running?: boolean; mode?: string; phase?: string; transcript_preview?: string; reply_preview?: string } | undefined)} onChanged={() => setData(current => { const next = { ...current }; delete next.voice; return next })} />
    if (active === 'notifications') return <NotificationSettings />
    if (active === 'skills') return <SkillsManager items={(data.skills as { skills?: InventoryItem[] } | undefined)?.skills || []} pending={pendingToggle.replace('skill:', '')} onToggle={(name, enabled) => toggle('skill', name, enabled)} />
    if (active === 'tools') return <ToolsManager items={(data.tools as { tools?: InventoryItem[] } | undefined)?.tools || []} pending={pendingToggle.replace('tool:', '')} onToggle={(name, enabled) => toggle('tool', name, enabled)} />
    if (active === 'plugins') return <PluginManager items={(data.plugins as { plugins?: InventoryItem[] } | undefined)?.plugins || []} pending={pendingToggle.replace('plugin:', '')} onToggle={(name, enabled) => toggle('plugin', name, enabled)} />
    if (active === 'mcp') return <McpManager items={(data.mcp as { mcp?: InventoryItem[] } | undefined)?.mcp || []} pending={pendingToggle.replace('mcp:', '')} onToggle={(name, enabled) => toggle('mcp', name, enabled)} onChanged={() => setData(current => { const next = { ...current }; delete next.mcp; return next })} onError={setError} />
    if (active === 'hive') return <HiveManager response={data.hive as { enabled: boolean; personas: string[]; hives: HiveItem[] } | undefined} pending={pendingToggle === 'hive:hive'} onToggle={enabled => toggle('hive', 'hive', enabled)} onChanged={() => setData(current => { const next = { ...current }; delete next.hive; return next })} onError={setError} />
    if (active === 'evolution') {
      if (loading) return <p className="py-8 text-sm text-muted-foreground" role="status">Loading evolution data…</p>
      if (error) return <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive" role="alert">Could not load evolution: {error}</p>
      const evolution = data.evolution as { enabled?: boolean; version?: string; lifecycle?: InventoryItem[]; forges?: InventoryItem[] } | undefined
      return <EvolutionPanel evolution={evolution} onToggle={toggle} pending={pendingToggle} />
    }
    if (active === 'config') return <ConfigurationPanel state={(data.config as Record<string, unknown> | undefined) || {}} onSaved={() => setData(current => { const next = { ...current }; delete next.config; return next })} />
    if (active === 'gateway') return <GatewayManager items={(data.gateway as { gateways?: InventoryItem[] } | undefined)?.gateways || []} pending={pendingToggle.replace('gateway:', '')} onToggle={(name: string, enabled: boolean) => toggle('gateway', name, enabled)} />
    if (active === 'cron') {
      const cron = data.cron as { jobs?: InventoryItem[]; status?: string; message?: string } | undefined
      return <ScheduledJobsManager jobs={cron?.jobs || []} onChanged={() => setData(current => { const next = { ...current }; delete next.cron; return next })} onError={setError} />
    }
    if (active === 'billing') {
      const billing = data.billing as { tier?: string; message?: string; status?: string } | undefined
      return <BillingSettings billing={billing} />
    }
    if (active === 'about') {
      const version = data.about as { version?: string; service?: string } | undefined
      return <AboutSettings version={version} backendAvailable={backendAvailable} sessions={sessions} />
    }
    return <LiveData data={(data[active] as Record<string, unknown> | undefined) || {}} empty={`Nexus did not report ${active} data.`} />
  }, [active, backendAvailable, data, error, loading, sessions.length, theme])

  const activeLabel = sections.find(section => section.id === active)?.label || 'Settings'
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/20 p-4 backdrop-blur-[1px]" role="dialog" aria-modal="true" aria-label="Nexus settings">
      <div
        className="flex overflow-hidden rounded-xl border border-border bg-background shadow-2xl"
        style={{
          width: "min(1320px, calc(100vw - 48px))",
          maxWidth: "1320px",
          height: "min(760px, 88vh)",
          maxHeight: "88vh",
        }}
      >
      <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-secondary/35 p-3">
        <div className="mb-4 px-2 pt-1"><p className="text-sm font-semibold">Nexus settings</p><p className="mt-0.5 text-xs text-muted-foreground">Workspace configuration</p></div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto" aria-label="Settings sections">
          {sections.map(section => { const Icon = section.icon; return <button key={section.id} onClick={() => navigateTo(section.id)} className={`flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition ${active === section.id ? 'bg-background font-medium text-foreground shadow-sm ring-1 ring-border' : 'text-muted-foreground hover:bg-background/70 hover:text-foreground'}`}><Icon size={16} />{section.label}</button> })}
        </nav>
      </aside>
      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border px-7 py-4"><div><h2 className="text-base font-semibold">{activeLabel}</h2><p className="mt-0.5 text-xs text-muted-foreground">{active === 'appearance' ? 'Preferences saved on this device.' : 'Data reported by your running Nexus server.'}</p></div><button onClick={closeSettings} className="flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground" aria-label="Close settings"><X size={17} /></button></header>
        <div className="flex-1 overflow-y-auto px-7 py-6"><div className="mx-auto max-w-4xl">{content}</div></div>
      </section>
    </div>
  </div>
}










