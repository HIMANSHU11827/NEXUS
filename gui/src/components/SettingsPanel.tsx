import { useEffect, useMemo, useRef, useState } from 'react'
import {
  X, Palette, Sparkles,
  Search, RefreshCw, AlertTriangle, ChevronRight,
} from 'lucide-react'
import { api, type HiveItem, type InventoryItem, type ProviderDiagnostics, type RuntimeProviderStatus } from '../lib/api'
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
import { settingsSections, type SettingsSectionId as Section } from './settings/settingsRegistry'
import './settings/settings.css'

type Loaded = Record<string, unknown>
const sections = settingsSections


export default function SettingsPanel({ onClose }: { onClose: () => void }) {
  const { backendAvailable, sessions } = useStore()
  const [active, setActive] = useState<Section>('appearance')
  const [data, setData] = useState<Loaded>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [theme, setTheme] = useState(() => localStorage.getItem('nexus-theme') || 'light')
  const [pendingToggle, setPendingToggle] = useState('')
  const [query, setQuery] = useState('')
  const [refreshNonce, setRefreshNonce] = useState(0)
  const safetyDirtyRef = useRef(false)
  const dialogRef = useRef<HTMLDivElement>(null)
  const loadRequestRef = useRef(0)

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
    document.documentElement.classList.remove('dark', 'theme-grey', 'theme-glass', 'theme-green', 'theme-blue', 'theme-purple', 'theme-pink', 'theme-red', 'theme-orange')
    if (themeClass) document.documentElement.classList.add(themeClass)
  }, [])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeSettings()
        return
      }
      if (event.key !== 'Tab' || !dialogRef.current) return
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  })

  useEffect(() => {
    const first = dialogRef.current?.querySelector<HTMLElement>('input:not([disabled]), button:not([disabled]), select:not([disabled])')
    first?.focus()
  }, [active])

  useEffect(() => {
    const loaders: Partial<Record<Section, () => Promise<unknown>>> = {
      providers: async () => ({ ...(await api.providers()), runtime_status: await api.status().catch(() => undefined) }), skills: api.skills, tools: api.tools, plugins: api.plugins,
      mcp: api.mcp, hive: api.hives, gateway: api.gateways, cron: api.cronJobs,
      evolution: api.evolution, config: api.state, memory: api.state,
      notifications: api.state, voice: api.voiceStatus, billing: api.billing, about: api.version,
    }
    const load = loaders[active]
    if (!load) return
    const requestId = ++loadRequestRef.current
    let cancelled = false
    const isCurrent = () => !cancelled && requestId === loadRequestRef.current
    setLoading(true); setError('')
    load().then(result => { if (isCurrent()) setData(current => ({ ...current, [active]: result })) })
      .catch(err => { if (isCurrent()) setError(err instanceof Error ? err.message : 'Could not load this Nexus setting.') })
      .finally(() => { if (isCurrent()) setLoading(false) })
    return () => { cancelled = true }
  }, [active, refreshNonce])

  const toggle = async (kind: string, name: string, enabled: boolean) => {
    setPendingToggle(`${kind}:${name}`); setError('')
    try {
      await api.manage(kind, name, enabled ? 'enable' : 'disable')
      setData(current => { const next = { ...current }; delete next[active]; return next })
      setRefreshNonce(value => value + 1)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nexus could not save this setting.')
    } finally { setPendingToggle('') }
  }

  const refreshActive = () => {
    setError('')
    setData(current => {
      const next = { ...current }
      delete next[active]
      return next
    })
    setRefreshNonce(value => value + 1)
  }

  const filteredSections = sections.filter(section => {
    const needle = query.trim().toLowerCase()
    return !needle || `${section.label} ${section.description} ${section.purpose} ${section.group} ${section.searchTerms.join(' ')}`.toLowerCase().includes(needle)
  })

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
    if (error) return <div className="rounded-xl border border-destructive/25 bg-destructive/5 p-5" role="alert"><div className="flex items-start gap-3"><AlertTriangle className="mt-0.5 shrink-0 text-destructive" size={18} /><div><p className="text-sm font-semibold text-destructive">Couldn’t load this section</p><p className="mt-1 text-sm text-destructive/80">{error}</p><button type="button" onClick={refreshActive} className="mt-3 inline-flex items-center gap-2 rounded-md border border-destructive/30 bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-secondary"><RefreshCw size={13} /> Try again</button></div></div></div>
    if (active === 'providers') {
      const response = data.providers as { providers?: InventoryItem[]; runtime?: { provider?: string; model?: string }; diagnostics?: ProviderDiagnostics; runtime_status?: RuntimeProviderStatus } | undefined
      const providers = response?.providers || []
      if (error) {
        return <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive" role="alert">Could not load providers: {error}</p>
      }
      if (loading) {
        return <p className="py-8 text-sm text-muted-foreground" role="status">Loading providers…</p>
      }
      return providers.length ? <ProviderList providers={providers} pending={pendingToggle.replace('provider:', '')} runtimeStatus={response?.runtime_status} diagnostics={response?.diagnostics} onToggle={(name, enabled) => toggle('provider', name, enabled)} onChanged={() => { setData(current => { const next = { ...current }; delete next.providers; return next }); setRefreshNonce(value => value + 1) }} /> : <p className="py-8 text-sm text-muted-foreground">No provider implementations were reported.</p>
    }
    if (active === 'safety') return <SafetySettings onOpenWorkspace={() => navigateTo('workspace')} onDirtyChange={dirty => { safetyDirtyRef.current = dirty }} />
    if (active === 'memory') return <MemorySettings state={(data.memory as Record<string, unknown> | undefined) || {}} />
    if (active === 'voice') return <VoiceSettings status={(data.voice as { running?: boolean; mode?: string; phase?: string; transcript_preview?: string; reply_preview?: string } | undefined)} onChanged={() => { setData(current => { const next = { ...current }; delete next.voice; return next }); setRefreshNonce(value => value + 1) }} />
    if (active === 'notifications') return <NotificationSettings />
    if (active === 'skills') return <SkillsManager items={(data.skills as { skills?: InventoryItem[] } | undefined)?.skills || []} pending={pendingToggle.replace('skill:', '')} onToggle={(name, enabled) => toggle('skill', name, enabled)} />
    if (active === 'tools') return <ToolsManager items={(data.tools as { tools?: InventoryItem[] } | undefined)?.tools || []} pending={pendingToggle.replace('tool:', '')} onToggle={(name, enabled) => toggle('tool', name, enabled)} />
    if (active === 'plugins') return <PluginManager items={(data.plugins as { plugins?: InventoryItem[] } | undefined)?.plugins || []} pending={pendingToggle.replace('plugin:', '')} onToggle={(name, enabled) => toggle('plugin', name, enabled)} />
    if (active === 'mcp') return <McpManager items={(data.mcp as { mcp?: InventoryItem[] } | undefined)?.mcp || []} pending={pendingToggle.replace('mcp:', '')} onToggle={(name, enabled) => toggle('mcp', name, enabled)} onChanged={() => { setData(current => { const next = { ...current }; delete next.mcp; return next }); setRefreshNonce(value => value + 1) }} onError={setError} />
    if (active === 'hive') return <HiveManager response={data.hive as { enabled: boolean; personas: string[]; hives: HiveItem[] } | undefined} pending={pendingToggle === 'hive:hive'} onToggle={enabled => toggle('hive', 'hive', enabled)} onChanged={() => { setData(current => { const next = { ...current }; delete next.hive; return next }); setRefreshNonce(value => value + 1) }} onError={setError} />
    if (active === 'evolution') {
      if (loading) return <p className="py-8 text-sm text-muted-foreground" role="status">Loading evolution data…</p>
      if (error) return <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive" role="alert">Could not load evolution: {error}</p>
      const evolution = data.evolution as { enabled?: boolean; version?: string; lifecycle?: InventoryItem[]; forges?: InventoryItem[] } | undefined
      return <EvolutionPanel evolution={evolution} onToggle={toggle} pending={pendingToggle} />
    }
    if (active === 'config') return <ConfigurationPanel state={(data.config as Record<string, unknown> | undefined) || {}} onSaved={() => { setData(current => { const next = { ...current }; delete next.config; return next }); setRefreshNonce(value => value + 1) }} />
    if (active === 'gateway') return <GatewayManager items={(data.gateway as { gateways?: InventoryItem[] } | undefined)?.gateways || []} pending={pendingToggle.replace('gateway:', '')} onToggle={(name: string, enabled: boolean) => toggle('gateway', name, enabled)} />
    if (active === 'cron') {
      const cron = data.cron as { jobs?: InventoryItem[]; status?: string; message?: string } | undefined
      return <ScheduledJobsManager jobs={cron?.jobs || []} onChanged={() => { setData(current => { const next = { ...current }; delete next.cron; return next }); setRefreshNonce(value => value + 1) }} onError={setError} />
    }
    if (active === 'billing') {
      const billing = data.billing as { tier?: string; message?: string; status?: string } | undefined
      return <BillingSettings billing={billing} />
    }
    if (active === 'about') {
      const version = data.about as { version?: string; service?: string } | undefined
      return <AboutSettings version={version} backendAvailable={backendAvailable} sessions={sessions.length} />
    }
    return <LiveData data={(data[active] as Record<string, unknown> | undefined) || {}} empty={`Nexus did not report ${active} data.`} />
  }, [active, backendAvailable, data, error, loading, sessions.length, theme])

  const activeLabel = sections.find(section => section.id === active)?.label || 'Settings'
  const activeSection = sections.find(section => section.id === active)
  const ActiveIcon = activeSection?.icon || Palette
  const groupedSections = [...new Set(filteredSections.map(section => section.group))]
  return <div className="settings-overlay fixed inset-0 z-50 flex items-center justify-center p-0 backdrop-blur-sm sm:p-4" role="dialog" aria-modal="true" aria-label="Nexus settings" aria-describedby="settings-description">
      <div
        ref={dialogRef}
        className="settings-modal flex h-full w-full overflow-hidden border bg-background shadow-2xl sm:h-[min(820px,92vh)] sm:w-[min(1320px,calc(100vw-48px))] sm:border"
        style={{
          maxWidth: "1320px",
          maxHeight: "92vh",
        }}
      >
      <aside className="settings-sidebar hidden w-72 shrink-0 flex-col border-r border-border p-4 md:flex">
        <div className="settings-brand"><span className="settings-brand-mark"><Sparkles size={15} /></span><div><p className="text-sm font-semibold tracking-tight">Nexus settings</p><p className="mt-0.5 text-[11px] text-muted-foreground">Control center for your local agent</p></div></div>
        <label className="relative mb-4 block"><Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search settings" aria-label="Search settings" className="h-9 w-full rounded-lg border border-border bg-background pl-9 pr-3 text-sm outline-none placeholder:text-muted-foreground/70 focus:border-ring focus:ring-2 focus:ring-ring/20" /></label>
        <nav className="flex-1 space-y-5 overflow-y-auto pr-1" aria-label="Settings sections">
          {groupedSections.map(group => <div key={group}><p className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/70">{group}</p><div className="space-y-0.5">{filteredSections.filter(section => section.group === group).map(section => { const Icon = section.icon; return <button key={section.id} onClick={() => navigateTo(section.id)} aria-current={active === section.id ? 'page' : undefined} title={`${section.description} · ${section.purpose}`} className={`settings-nav-item group flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition ${active === section.id ? 'is-active font-medium text-foreground' : 'text-muted-foreground hover:bg-background/70 hover:text-foreground'}`}><Icon size={16} className={active === section.id ? 'text-primary' : 'text-muted-foreground/80'} /><span className="min-w-0 flex-1 truncate">{section.label}</span>{active === section.id && <ChevronRight size={14} className="text-muted-foreground" />}</button> })}</div></div>)}
          {!filteredSections.length && <p className="px-2 py-6 text-xs text-muted-foreground">No settings match “{query}”.</p>}
        </nav>
        <div className="mt-4 flex items-center gap-2 border-t border-border px-2 pt-3 text-xs text-muted-foreground"><span className={`size-2 rounded-full ${backendAvailable ? 'bg-emerald-500' : 'bg-amber-500'}`} />{backendAvailable ? 'Backend connected' : 'Backend unavailable'}<span className="ml-auto text-[10px] uppercase tracking-wider text-muted-foreground/60">Local</span></div>
      </aside>
      <section className="flex min-w-0 flex-1 flex-col">
        <header className="settings-header sticky top-0 z-10 px-4 py-4 backdrop-blur sm:px-7"><div className="flex items-start justify-between gap-4"><div className="min-w-0"><div className="mb-3 flex items-center gap-2 md:hidden"><span className="text-sm font-semibold">Settings</span><span className="text-muted-foreground">/</span><span className="truncate text-sm text-muted-foreground">{activeLabel}</span></div><div className="flex items-center gap-3"><span className="hidden size-9 place-items-center rounded-xl bg-primary/10 text-primary sm:grid"><ActiveIcon size={17} /></span><div><div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold tracking-tight">{activeLabel}</h2>{activeSection?.purpose && <span className="settings-purpose-badge">{activeSection.purpose}</span>}</div><p id="settings-description" className="mt-1 text-sm text-muted-foreground">{activeSection?.description || (active === 'appearance' ? 'Preferences saved on this device.' : 'Live data from your Nexus server.')}</p></div></div></div><button type="button" onClick={closeSettings} className="flex size-9 shrink-0 items-center justify-center rounded-xl text-muted-foreground hover:bg-secondary hover:text-foreground focus:outline-none focus:ring-2 focus:ring-ring" aria-label="Close settings"><X size={18} /></button></div><div className="mt-4 flex items-center gap-2 md:hidden"><Search size={15} className="text-muted-foreground" /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Filter settings" aria-label="Filter settings" className="h-8 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-sm outline-none focus:border-ring" /><select aria-label="Settings section" value={active} onChange={event => navigateTo(event.target.value as Section)} className="h-8 max-w-[46%] rounded-md border border-border bg-background px-2 text-xs">{sections.map(section => <option key={section.id} value={section.id}>{section.label}</option>)}</select></div></header>
        <div className="settings-scroll flex-1 overflow-y-auto px-4 py-5 sm:px-7 sm:py-7"><div key={`${active}-${refreshNonce}`} className="settings-page-frame mx-auto max-w-4xl"><div className={`settings-page settings-page--${active}`}>{content}</div></div></div>
      </section>
    </div>
  </div>
}










