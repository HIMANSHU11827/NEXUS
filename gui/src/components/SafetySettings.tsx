import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  api,
  type SafetyDiagnostic,
  type SafetyEvent,
  type SafetyMeta,
  type SafetyPermissionMode,
  type SafetyPolicy,
  type SafetyProtectedPath,
  type SafetySandboxMode,
  type SafetySettings as SafetySettingsState,
  type SafetySummary,
} from '../lib/api'

type Props = {
  onOpenWorkspace: () => void
  onDirtyChange: (dirty: boolean) => void
}

const POLICY_OPTIONS: SafetyPolicy[] = ['allow', 'ask', 'deny', 'read_only', 'session']

function cloneSettings(value: SafetySettingsState): SafetySettingsState {
  return JSON.parse(JSON.stringify(value)) as SafetySettingsState
}

function InfoBlock({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-2 text-lg font-semibold">{value}</p>
      <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
    </div>
  )
}

function Section({ title, detail, children }: { title: string; detail: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold">{title}</h3>
        <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
      </div>
      {children}
    </section>
  )
}

function formatTime(value?: number | null) {
  if (!value) return 'Never'
  try {
    return new Date(value * 1000).toLocaleString()
  } catch {
    return 'Unknown'
  }
}

export default function SafetySettings({ onOpenWorkspace, onDirtyChange }: Props) {
  const [summary, setSummary] = useState<SafetySummary | null>(null)
  const [meta, setMeta] = useState<SafetyMeta | null>(null)
  const [settings, setSettings] = useState<SafetySettingsState | null>(null)
  const [baseline, setBaseline] = useState<string>('')
  const [paths, setPaths] = useState<SafetyProtectedPath[]>([])
  const [events, setEvents] = useState<SafetyEvent[]>([])
  const [diagnostics, setDiagnostics] = useState<SafetyDiagnostic[]>([])
  const [pathInput, setPathInput] = useState('')
  const [pathReason, setPathReason] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [working, setWorking] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState<'overview' | 'policies' | 'paths' | 'diagnostics'>('overview')
  const onDirtyChangeRef = useRef(onDirtyChange)
  onDirtyChangeRef.current = onDirtyChange

  const dirty = useMemo(() => {
    if (!settings || !baseline) return false
    return JSON.stringify(settings) !== baseline
  }, [baseline, settings])

  useEffect(() => {
    onDirtyChangeRef.current(dirty)
  }, [dirty])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [summaryData, settingsData, metaData, pathData, eventData, diagnosticData] = await Promise.all([
        api.safetySummary(),
        api.safetySettings(),
        api.safetyMeta(),
        api.safetyProtectedPaths().catch(() => ({ paths: [] as SafetyProtectedPath[] })),
        api.safetyEvents().catch(() => ({ events: [] as SafetyEvent[] })),
        api.safetyDiagnostics().catch(() => ({ checks: [] as SafetyDiagnostic[] })),
      ])
      const next = cloneSettings(settingsData)
      setSummary(summaryData)
      setMeta(metaData)
      setSettings(next)
      setBaseline(JSON.stringify(next))
      setPaths(pathData.paths || [])
      setEvents((eventData.events || []).slice(0, 8))
      setDiagnostics(diagnosticData.checks || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load safety settings.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    return () => onDirtyChangeRef.current(false)
  }, [load])

  const updateSetting = (patch: (current: SafetySettingsState) => void) => {
    setSettings(current => {
      if (!current) return current
      const next = cloneSettings(current)
      patch(next)
      return next
    })
    setMessage('')
  }

  const save = async () => {
    if (!settings) return
    setSaving(true)
    setMessage('')
    setError('')
    try {
      const result = await api.safetySave(settings)
      if (!result.ok) throw new Error((result.errors || ['Save failed']).join('; '))
      setMessage('Safety settings saved.')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save safety settings.')
    } finally {
      setSaving(false)
    }
  }

  const reset = async () => {
    if (!window.confirm('Reset all Safety settings to defaults?')) return
    setWorking('reset')
    setMessage('')
    setError('')
    try {
      const result = await api.safetyReset()
      if (!result.ok) throw new Error((result.errors || ['Reset failed']).join('; '))
      setMessage('Safety settings reset to defaults.')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reset safety settings.')
    } finally {
      setWorking('')
    }
  }

  const applyPreset = async (preset: string) => {
    if (dirty && !window.confirm('Apply this preset and discard unsaved Safety changes?')) return
    setWorking(`preset:${preset}`)
    setMessage('')
    setError('')
    try {
      const result = await api.safetyApplyPreset(preset)
      if (!result.ok) throw new Error((result.errors || ['Preset failed']).join('; '))
      setMessage('Safety preset applied.')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not apply preset.')
    } finally {
      setWorking('')
    }
  }

  const addProtectedPath = async () => {
    const path = pathInput.trim()
    if (!path) return
    setWorking('add-path')
    setError('')
    try {
      const result = await api.safetyAddProtectedPath({ path, reason: pathReason.trim() || undefined, read: 'ask', write: 'deny', delete: 'deny' })
      if (!result.ok) throw new Error((result.errors || ['Could not add path']).join('; '))
      setPathInput('')
      setPathReason('')
      setMessage('Protected path added.')
      const pathData = await api.safetyProtectedPaths()
      setPaths(pathData.paths || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add protected path.')
    } finally {
      setWorking('')
    }
  }

  const removeProtectedPath = async (path: SafetyProtectedPath) => {
    if (path.mandatory) return
    if (!window.confirm(`Remove protected path?\n${path.path}`)) return
    setWorking(`remove:${path.path}`)
    try {
      const result = await api.safetyRemoveProtectedPath(path.path)
      if (!result.ok) throw new Error((result.errors || ['Could not remove path']).join('; '))
      setMessage('Protected path removed.')
      const pathData = await api.safetyProtectedPaths()
      setPaths(pathData.paths || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove protected path.')
    } finally {
      setWorking('')
    }
  }

  if (loading && !settings) {
    return <p className="py-8 text-sm text-muted-foreground" role="status">Loading safety settings…</p>
  }

  if (error && !settings) {
    return <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive" role="alert">{error}</p>
  }

  if (!settings || !meta) return null

  const permissionMode = String(settings.permission_mode || 'automatic') as SafetyPermissionMode
  const sandboxMode = String(settings.sandbox_mode || 'workspace') as SafetySandboxMode
  const network = (settings.network && typeof settings.network === 'object' ? settings.network : {}) as Record<string, unknown>
  const filesystem = (settings.filesystem && typeof settings.filesystem === 'object' ? settings.filesystem : {}) as Record<string, boolean>
  const secrets = (settings.secret_protection && typeof settings.secret_protection === 'object' ? settings.secret_protection : {}) as Record<string, boolean>
  const destructive = (settings.destructive && typeof settings.destructive === 'object' ? settings.destructive : {}) as Record<string, unknown>
  const commandPolicies = (settings.command_policies && typeof settings.command_policies === 'object' ? settings.command_policies : {}) as Record<string, string>
  const filePolicies = (settings.file_policies && typeof settings.file_policies === 'object' ? settings.file_policies : {}) as Record<string, string>

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">Safety</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Permission mode, sandboxing, and protected paths are separate from the workspace root.
          </p>
        </div>
        <button type="button" onClick={onOpenWorkspace} className="rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-secondary">
          Open Workspace settings
        </button>
      </div>

      {error && <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive" role="alert">{error}</div>}
      
      <div className="flex gap-2 border-b border-border">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'policies', label: 'Policies' },
          { id: 'paths', label: 'Protected Paths' },
          { id: 'diagnostics', label: 'Diagnostics' },
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as any)}
            className={`px-3 py-2 text-sm font-medium transition ${activeTab === tab.id ? 'border-b-2 border-foreground text-foreground' : 'text-muted-foreground hover:text-foreground'}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'overview' && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <InfoBlock title="Permission" value={summary?.permission_label || permissionMode} detail={`Mode: ${permissionMode}`} />
            <InfoBlock title="Sandbox" value={summary?.sandbox_label || sandboxMode} detail={`Mode: ${sandboxMode}`} />
            <InfoBlock title="Protected paths" value={String(summary?.protected_path_count ?? paths.length)} detail={`${summary?.active_temp_permissions ?? 0} temp permissions · ${summary?.pending_approvals ?? 0} approvals`} />
            <InfoBlock title="Workspace" value={summary?.workspace_exists ? 'Connected' : 'Missing'} detail={summary?.workspace || 'No workspace reported'} />
          </div>

          <Section title="Presets" detail="Apply a curated safety profile. You can still fine-tune afterward.">
            <div className="grid gap-3 sm:grid-cols-2">
              {(meta.presets || []).map(preset => (
                <button
                  key={preset.id}
                  type="button"
                  disabled={!!working}
                  onClick={() => void applyPreset(preset.id)}
                  className="rounded-lg border border-border bg-card p-4 text-left transition hover:border-foreground/40"
                >
                  <p className="text-sm font-medium">{preset.label}{preset.recommended ? <span className="ml-2 text-xs font-normal text-emerald-700">Recommended</span> : null}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{preset.description}</p>
                  {working === `preset:${preset.id}` && <p className="mt-2 text-xs text-muted-foreground">Applying…</p>}
                </button>
              ))}
            </div>
          </Section>

          <Section title="Core modes" detail="These two controls decide how freely Nexus may act and how isolated tool execution is.">
            <div className="grid gap-4 rounded-lg border border-border bg-card p-4 md:grid-cols-2">
              <label className="grid gap-1.5 text-sm font-medium">
                Permission mode
                <select
                  value={permissionMode}
                  onChange={event => updateSetting(current => { current.permission_mode = event.target.value })}
                  className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring"
                >
                  {(meta.permission_modes || []).map(mode => (
                    <option key={mode.id} value={mode.id}>{mode.label}</option>
                  ))}
                </select>
                <span className="text-xs font-normal text-muted-foreground">
                  {(meta.permission_modes || []).find(mode => mode.id === permissionMode)?.description}
                </span>
              </label>
              <label className="grid gap-1.5 text-sm font-medium">
                Sandbox mode
                <select
                  value={sandboxMode}
                  onChange={event => updateSetting(current => { current.sandbox_mode = event.target.value })}
                  className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring"
                >
                  {(meta.sandbox_modes || []).map(mode => (
                    <option key={mode.id} value={mode.id}>{mode.label}</option>
                  ))}
                </select>
                <span className="text-xs font-normal text-muted-foreground">
                  {(meta.sandbox_modes || []).find(mode => mode.id === sandboxMode)?.description}
                </span>
              </label>
            </div>
          </Section>
        </div>
      )}

      {activeTab === 'policies' && (
        <div className="space-y-4">
          <Section title="Network" detail="Controls outbound destinations for tools and browsers.">
            <div className="rounded-lg border border-border bg-card p-4">
              <label className="grid gap-1.5 text-sm font-medium">
                Network policy
                <select
                  value={String(network.policy || 'ask')}
                  onChange={event => updateSetting(current => {
                    const nextNetwork = { ...(typeof current.network === 'object' && current.network ? current.network as Record<string, unknown> : {}), policy: event.target.value }
                    current.network = nextNetwork
                  })}
                  className="h-10 max-w-md rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring"
                >
                  {(meta.network_policies || []).map(policy => (
                    <option key={policy.id} value={policy.id}>{policy.label}</option>
                  ))}
                </select>
              </label>
            </div>
          </Section>

          <Section title="Filesystem safeguards" detail="Boolean gates for where Nexus may touch the filesystem.">
            <div className="divide-y divide-border rounded-lg border border-border bg-card">
              {(meta.filesystem_options || []).map(option => (
                <label key={option.id} className="flex items-start gap-3 px-4 py-3">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={Boolean(filesystem[option.id])}
                    onChange={event => updateSetting(current => {
                      const next = { ...(typeof current.filesystem === 'object' && current.filesystem ? current.filesystem as Record<string, unknown> : {}), [option.id]: event.target.checked }
                      current.filesystem = next
                    })}
                  />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{option.label}</span>
                    {option.description && <span className="mt-0.5 block text-xs text-muted-foreground">{option.description}</span>}
                  </span>
                </label>
              ))}
            </div>
          </Section>

          <Section title="Secret protection" detail="Detection and redaction controls for credentials and sensitive material.">
            <div className="divide-y divide-border rounded-lg border border-border bg-card">
              {(meta.secret_protection_options || []).slice(0, 10).map(option => (
                <label key={option.id} className="flex items-start gap-3 px-4 py-3">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={Boolean(secrets[option.id])}
                    onChange={event => updateSetting(current => {
                      const next = { ...(typeof current.secret_protection === 'object' && current.secret_protection ? current.secret_protection as Record<string, unknown> : {}), [option.id]: event.target.checked }
                      current.secret_protection = next
                    })}
                  />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{option.label}</span>
                    {option.description && <span className="mt-0.5 block text-xs text-muted-foreground">{option.description}</span>}
                  </span>
                </label>
              ))}
            </div>
          </Section>

          <Section title="High-risk command policies" detail="How Nexus treats dangerous command categories.">
            <div className="grid gap-3 rounded-lg border border-border bg-card p-4 md:grid-cols-2">
              {(meta.command_categories || []).filter(item => ['destructive_commands', 'privilege_escalation', 'credential_access', 'outside_workspace'].includes(item.id)).map(item => (
                <label key={item.id} className="grid gap-1.5 text-sm font-medium">
                  {item.label}
                  <select
                    value={commandPolicies[item.id] || 'ask'}
                    onChange={event => updateSetting(current => {
                      const next = { ...(typeof current.command_policies === 'object' && current.command_policies ? current.command_policies as Record<string, unknown> : {}), [item.id]: event.target.value }
                      current.command_policies = next
                    })}
                    className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal"
                  >
                    {POLICY_OPTIONS.map(option => <option key={option} value={option}>{option}</option>)}
                  </select>
                </label>
              ))}
            </div>
          </Section>

          <Section title="File change policies" detail="Approval rules for common file mutations.">
            <div className="grid gap-3 rounded-lg border border-border bg-card p-4 md:grid-cols-2">
              {(meta.file_policy_categories || []).filter(item => ['create_file', 'modify_file', 'delete_file', 'delete_directory'].includes(item.id)).map(item => (
                <label key={item.id} className="grid gap-1.5 text-sm font-medium">
                  {item.label}
                  <select
                    value={filePolicies[item.id] || 'ask'}
                    onChange={event => updateSetting(current => {
                      const next = { ...(typeof current.file_policies === 'object' && current.file_policies ? current.file_policies as Record<string, unknown> : {}), [item.id]: event.target.value }
                      current.file_policies = next
                    })}
                    className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal"
                  >
                    {POLICY_OPTIONS.map(option => <option key={option} value={option}>{option}</option>)}
                  </select>
                </label>
              ))}
            </div>
          </Section>

          <Section title="Destructive actions" detail="Extra confirmation gates for irreversible operations.">
            <div className="divide-y divide-border rounded-lg border border-border bg-card">
              <label className="flex items-start gap-3 px-4 py-3">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={Boolean(destructive.require_approval)}
                  onChange={event => updateSetting(current => {
                    const next = { ...(typeof current.destructive === 'object' && current.destructive ? current.destructive as Record<string, unknown> : {}), require_approval: event.target.checked }
                    current.destructive = next
                  })}
                />
                <span className="text-sm font-medium">Require approval for destructive actions</span>
              </label>
              <label className="flex items-start gap-3 px-4 py-3">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={Boolean(destructive.require_typed_confirmation)}
                  onChange={event => updateSetting(current => {
                    const next = { ...(typeof current.destructive === 'object' && current.destructive ? current.destructive as Record<string, unknown> : {}), require_typed_confirmation: event.target.checked }
                    current.destructive = next
                  })}
                />
                <span className="text-sm font-medium">Require typed confirmation for critical deletes</span>
              </label>
            </div>
          </Section>
        </div>
      )}

      {activeTab === 'paths' && (
        <div className="space-y-4">
          <Section title="Protected paths" detail="Patterns Nexus treats carefully. Mandatory defaults cannot be removed.">
            <div className="divide-y divide-border rounded-lg border border-border bg-card">
              {paths.length ? paths.map(path => (
                <div key={path.path} className="flex items-start justify-between gap-3 px-4 py-3">
                  <div className="min-w-0">
                    <p className="break-all text-sm font-medium">{path.path}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {path.reason || 'Protected path'} · read {path.read} · write {path.write} · delete {path.delete}
                      {path.mandatory ? ' · mandatory' : ''}
                    </p>
                  </div>
                  {!path.mandatory && (
                    <button
                      type="button"
                      disabled={!!working}
                      onClick={() => void removeProtectedPath(path)}
                      className="shrink-0 text-xs text-destructive hover:opacity-80"
                    >
                      Remove
                    </button>
                  )}
                </div>
              )) : (
                <p className="px-4 py-6 text-sm text-muted-foreground">No protected paths were reported.</p>
              )}
            </div>
            <div className="grid gap-3 rounded-lg border border-border bg-secondary/30 p-4 sm:grid-cols-[1fr_1fr_auto]">
              <input
                value={pathInput}
                onChange={event => setPathInput(event.target.value)}
                placeholder="Path or glob pattern"
                className="h-10 rounded-md border border-border bg-background px-3 text-sm outline-none focus:border-ring"
              />
              <input
                value={pathReason}
                onChange={event => setPathReason(event.target.value)}
                placeholder="Reason (optional)"
                className="h-10 rounded-md border border-border bg-background px-3 text-sm outline-none focus:border-ring"
              />
              <button
                type="button"
                disabled={!!working || !pathInput.trim()}
                onClick={() => void addProtectedPath()}
                className="rounded-md bg-foreground px-3 text-sm font-medium text-background disabled:opacity-50"
              >
                {working === 'add-path' ? 'Adding…' : 'Add'}
              </button>
            </div>
          </Section>
        </div>
      )}

      {activeTab === 'diagnostics' && (
        <div className="space-y-4">
          {diagnostics.length > 0 && (
            <Section title="Diagnostics" detail="Latest safety self-checks from the Nexus backend.">
              <div className="divide-y divide-border rounded-lg border border-border bg-card">
                {diagnostics.map(check => (
                  <div key={check.name} className="flex items-start justify-between gap-4 px-4 py-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium">{check.name}</p>
                      {check.detail && <p className="mt-0.5 text-xs text-muted-foreground">{check.detail}</p>}
                    </div>
                    <span className={`shrink-0 text-xs font-medium capitalize ${check.status === 'healthy' ? 'text-emerald-700' : check.status === 'warning' ? 'text-amber-700' : 'text-destructive'}`}>
                      {check.status}
                    </span>
                  </div>
                ))}
              </div>
            </Section>
          )}
          {events.length > 0 && (
            <Section title="Recent safety events" detail="Latest decisions recorded by the safety store.">
              <div className="divide-y divide-border rounded-lg border border-border bg-card">
                {events.map(event => (
                  <div key={event.id} className="px-4 py-3">
                    <p className="text-sm font-medium">{event.action || event.event_type}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {formatTime(event.time)} · {event.decision || 'n/a'} · risk {event.risk || 'unknown'}
                    </p>
                  </div>
                ))}
              </div>
            </Section>
          )}
        </div>
      )}

      <div className="sticky bottom-0 -mx-1 flex flex-wrap items-center justify-between gap-3 border-t border-border bg-background/95 px-1 py-3 backdrop-blur">
        <div className="min-w-0">
          <p className={`text-sm ${error ? 'text-destructive' : message ? 'text-emerald-700' : dirty ? 'text-amber-700' : 'text-muted-foreground'}`} role="status">
            {error || message || (dirty ? 'You have unsaved Safety changes.' : `Last saved: ${formatTime(summary?.last_saved)}`)}
          </p>
        </div>
        <div className="flex gap-2">
          <button type="button" disabled={!!working || saving} onClick={() => void reset()} className="rounded-md border border-border px-3 py-2 text-sm hover:bg-secondary disabled:opacity-50">
            {working === 'reset' ? 'Resetting…' : 'Reset defaults'}
          </button>
          <button type="button" disabled={!dirty || saving} onClick={() => void save()} className="rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background disabled:opacity-50">
            {saving ? 'Saving…' : 'Save safety settings'}
          </button>
        </div>
      </div>
    </div>
  )
}
