import { useEffect, useMemo, useState, type FormEvent } from 'react'
import {
  X, Palette, Cpu, Brain, Sparkles, SlidersHorizontal, Info,
  Wrench, Puzzle, Network, UsersRound, ReceiptText, Settings2, CheckCircle2, CircleAlert, Radio, Clock3, MessageCircle, Monitor, ShieldCheck, Bell, Keyboard, Mic,
} from 'lucide-react'
import { api, type HiveItem, type InventoryItem, type OAuthLoginRun } from '../lib/api'
import { useStore } from '../lib/store'

type Section = 'appearance' | 'chat' | 'workspace' | 'safety' | 'notifications' | 'shortcuts' | 'voice' | 'providers' | 'memory' | 'evolution' | 'config' | 'skills' | 'tools' | 'plugins' | 'mcp' | 'hive' | 'gateway' | 'cron' | 'billing' | 'about'
type Loaded = Record<string, unknown>

const sections: Array<{ id: Section; label: string; icon: typeof Palette }> = [
  { id: 'appearance', label: 'Theme & appearance', icon: Palette },
  { id: 'chat', label: 'Chat', icon: MessageCircle },
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

function labelFor(item: InventoryItem) {
  return String(item.name || item.id || 'Unnamed item')
}

function Description({ item, kind }: { item: InventoryItem; kind?: string }) {
  const supplied = typeof item.description === 'string' && item.description.trim() !== '---' ? item.description.trim() : ''
  const fallback: Record<string, string> = {
    skill: 'Installed local skill discovered by the running Nexus server.',
    tool: 'Registered Nexus tool. Its live availability is shown below.',
    plugin: 'Installed plugin discovered by the running Nexus server.',
    mcp: 'MCP server configured in Nexus.',
    provider: 'Bundled provider implementation reported by Nexus.',
    gateway: 'Gateway adapter reported by the running Nexus server.',
  }
  const description = supplied || (kind ? fallback[kind] || '' : '')
  return description ? <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{description}</p> : null
}

function InventoryList({ items, empty, kind, onToggle, pending }: { items: InventoryItem[]; empty: string; kind?: string; onToggle?: (name: string, enabled: boolean) => void; pending?: string }) {
  if (!items.length) return <p className="py-8 text-sm text-muted-foreground">{empty}</p>
  return <div className="divide-y divide-border rounded-lg border border-border bg-card">
    {items.map((item, index) => {
      const enabled = item.enabled ?? item.active
      const available = item.available
      return <div key={`${labelFor(item)}-${index}`} className="flex items-start gap-3 px-4 py-3">
        {enabled === false ? <CircleAlert size={16} className="mt-0.5 shrink-0 text-amber-600" /> : <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-emerald-600" />}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-foreground">{labelFor(item)}</p>
          <Description item={item} kind={kind} />
          {kind === 'tool' && <p className="mt-1 text-xs text-muted-foreground">{item.read_only === true ? 'Read-only' : 'Can make changes'} · {item.safe === true ? 'concurrency-safe' : 'runs with normal tool safeguards'}</p>}
          {kind === 'provider' && item.configured === false && <p className="mt-1 text-xs text-amber-700">Not configured in Nexus yet.</p>}
          {typeof item.availability_reason === 'string' && item.available === false && <p className="mt-1 text-xs text-amber-700">Status: {item.availability_reason}</p>}
          {available === false && !item.availability_reason && <p className="mt-1 text-xs text-amber-700">Installed but not ready: required configuration or credentials are missing.</p>}
        </div>
        {kind && onToggle && typeof enabled === 'boolean' ? <button onClick={() => onToggle(String(item.id || item.name || ''), !enabled)} disabled={pending === String(item.id || item.name || '')} className={`shrink-0 rounded-md px-2.5 py-1 text-xs font-medium transition disabled:opacity-50 ${enabled ? 'bg-foreground text-background hover:opacity-80' : 'border border-border text-muted-foreground hover:bg-secondary'}`}>{pending === String(item.id || item.name || '') ? 'Saving…' : enabled ? 'On' : 'Off'}</button> : typeof item.status === 'string' && <span className="text-xs capitalize text-muted-foreground">{item.status}</span>}
      </div>
    })}
  </div>
}

function McpManager({ items, pending, onToggle, onChanged, onError }: { items: InventoryItem[]; pending: string; onToggle: (name: string, enabled: boolean) => void; onChanged: () => void; onError: (message: string) => void }) {
  const [name, setName] = useState('')
  const [command, setCommand] = useState('')
  const [args, setArgs] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); onError('')
    try {
      await api.createMcp({ name, command, args: args.split(/\r?\n/).map(value => value.trim()).filter(Boolean), description, active: true })
      setName(''); setCommand(''); setArgs(''); setDescription(''); onChanged()
    } catch (err) { onError(err instanceof Error ? err.message : 'Could not add the MCP server.') } finally { setSaving(false) }
  }
  const remove = async (id: string) => {
    if (!window.confirm(`Delete MCP server “${id}”?`)) return
    try { await api.deleteMcp(id); onChanged() } catch (err) { onError(err instanceof Error ? err.message : 'Could not delete the MCP server.') }
  }
  return <div className="space-y-5">
    <form onSubmit={submit} className="grid gap-3 rounded-lg border border-border bg-secondary/30 p-4 sm:grid-cols-2">
      <div className="sm:col-span-2"><h3 className="text-sm font-semibold">Add MCP server</h3><p className="mt-1 text-xs text-muted-foreground">Add a real stdio MCP command. Use environment references such as <code>${'{'}MY_TOKEN{'}'}</code> for credentials; secrets are never stored here.</p></div>
      <label className="grid gap-1 text-xs font-medium">Server name<input required value={name} onChange={event => setName(event.target.value)} placeholder="e.g. github" className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal" /></label>
      <label className="grid gap-1 text-xs font-medium">Command<input required value={command} onChange={event => setCommand(event.target.value)} placeholder="e.g. npx" className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal font-mono" /></label>
      <label className="grid gap-1 text-xs font-medium sm:col-span-2">Arguments <span className="font-normal text-muted-foreground">(one per line)</span><textarea value={args} onChange={event => setArgs(event.target.value)} rows={3} placeholder="-y&#10;@modelcontextprotocol/server-github" className="rounded-md border border-border bg-background px-2 py-2 text-sm font-normal font-mono" /></label>
      <label className="grid gap-1 text-xs font-medium sm:col-span-2">Description<input value={description} onChange={event => setDescription(event.target.value)} placeholder="What this server provides" className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal" /></label>
      <div className="sm:col-span-2 flex justify-end"><button disabled={saving} className="rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background disabled:opacity-50">{saving ? 'Adding…' : 'Add MCP server'}</button></div>
    </form>
    {!items.length ? <p className="py-5 text-sm text-muted-foreground">No MCP servers are configured yet.</p> : <div className="divide-y divide-border rounded-lg border border-border bg-card">{items.map(item => {
      const id = String(item.id || item.name || '')
      const active = Boolean(item.active)
      return <div key={id} className="flex items-start gap-3 px-4 py-3"><CheckCircle2 size={16} className={`mt-0.5 shrink-0 ${active ? 'text-emerald-600' : 'text-muted-foreground'}`} /><div className="min-w-0 flex-1"><p className="text-sm font-medium">{id}</p><p className="mt-1 break-all font-mono text-xs text-muted-foreground">{String(item.command || '')}</p><Description item={item} kind="mcp" /></div><div className="flex shrink-0 gap-2"><button onClick={() => onToggle(id, !active)} disabled={pending === id} className="rounded-md border border-border px-2.5 py-1 text-xs">{pending === id ? 'Saving…' : active ? 'On' : 'Off'}</button><button onClick={() => remove(id)} className="rounded-md px-2 py-1 text-xs text-destructive hover:bg-destructive/10">Delete</button></div></div>
    })}</div>}
  </div>
}

function HiveManager({ response, pending, onToggle, onChanged, onError }: { response?: { enabled: boolean; personas: string[]; hives: HiveItem[] }; pending: boolean; onToggle: (enabled: boolean) => void; onChanged: () => void; onError: (message: string) => void }) {
  const [agents, setAgents] = useState([{ task: '', persona: 'WORKER' }])
  const [starting, setStarting] = useState(false)
  const enabled = response?.enabled ?? false
  const personas = response?.personas?.length ? response.personas : ['WORKER']
  const updateAgent = (index: number, field: 'task' | 'persona', value: string) => setAgents(current => current.map((agent, agentIndex) => agentIndex === index ? { ...agent, [field]: value } : agent))
  const start = async (event: FormEvent) => {
    event.preventDefault(); setStarting(true); onError('')
    try { await api.createHive(agents.filter(agent => agent.task.trim())); setAgents([{ task: '', persona: 'WORKER' }]); onChanged() } catch (err) { onError(err instanceof Error ? err.message : 'Could not start the hive.') } finally { setStarting(false) }
  }
  const cancel = async (id: string) => { try { await api.cancelHive(id); onChanged() } catch (err) { onError(err instanceof Error ? err.message : 'Could not cancel the hive.') } }
  return <div className="space-y-5">
    <div className="flex items-center justify-between rounded-lg border border-border p-4"><div><h3 className="text-sm font-semibold">Hive runtime</h3><p className="mt-1 text-xs text-muted-foreground">Starts real sub-agent tasks through the Hive engine. A configured LLM provider is required for agents to complete work.</p></div><button onClick={() => onToggle(!enabled)} disabled={pending} className={`rounded-md px-3 py-1.5 text-xs font-medium ${enabled ? 'bg-foreground text-background' : 'border border-border text-muted-foreground'}`}>{pending ? 'Saving…' : enabled ? 'On' : 'Off'}</button></div>
    <form onSubmit={start} className="space-y-3 rounded-lg border border-border bg-secondary/30 p-4"><div><h3 className="text-sm font-semibold">Start a hive</h3><p className="mt-1 text-xs text-muted-foreground">Each row becomes a real Hive sub-agent.</p></div>{agents.map((agent, index) => <div key={index} className="grid gap-2 sm:grid-cols-[1fr_150px_auto]"><input required value={agent.task} onChange={event => updateAgent(index, 'task', event.target.value)} placeholder="Sub-agent task" className="h-9 rounded-md border border-border bg-background px-2 text-sm" /><select value={agent.persona} onChange={event => updateAgent(index, 'persona', event.target.value)} className="h-9 rounded-md border border-border bg-background px-2 text-sm">{personas.map(persona => <option key={persona} value={persona}>{persona}</option>)}</select><button type="button" onClick={() => setAgents(current => current.length === 1 ? current : current.filter((_, agentIndex) => agentIndex !== index))} disabled={agents.length === 1} className="text-xs text-destructive disabled:opacity-30">Remove</button></div>)}<div className="flex justify-between"><button type="button" onClick={() => setAgents(current => [...current, { task: '', persona: 'WORKER' }])} className="text-xs text-muted-foreground underline">Add sub-agent</button><button disabled={!enabled || starting} className="rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background disabled:opacity-50">{starting ? 'Starting…' : 'Start hive'}</button></div></form>
    <div><h3 className="mb-2 text-sm font-semibold">Hive activity</h3>{!response?.hives?.length ? <p className="py-4 text-sm text-muted-foreground">No Hive runs have been created since this server started.</p> : <div className="space-y-2">{response.hives.map(hive => <div key={hive.id} className="rounded-lg border border-border p-3"><div className="flex items-center justify-between gap-3"><div><p className="font-mono text-xs text-muted-foreground">{hive.id}</p><p className="mt-1 text-sm capitalize">{hive.status || 'unknown'} · {hive.agents.length} agent{hive.agents.length === 1 ? '' : 's'}</p></div>{hive.status === 'running' && <button onClick={() => cancel(hive.id)} className="rounded-md border border-border px-2.5 py-1 text-xs">Cancel</button>}</div><ul className="mt-3 space-y-1 text-xs text-muted-foreground">{hive.agents.map(agent => <li key={agent.id}>{agent.persona}: {agent.task} <span className="capitalize">({agent.status})</span></li>)}</ul></div>)}</div>}</div>
  </div>
}

function GatewayManager({ items, pending, onToggle }: { items: InventoryItem[]; pending: string; onToggle: (name: string, enabled: boolean) => void }) {
  return <div className="space-y-3">{!items.length ? <p className="py-8 text-sm text-muted-foreground">No bundled gateway adapters were found.</p> : items.map(item => { const id = String(item.id || item.name || ''); const enabled = Boolean(item.enabled); const required = Array.isArray(item.required_env) ? item.required_env as unknown[][] : []; return <div key={id} className="rounded-lg border border-border p-4"><div className="flex items-start gap-3"><CheckCircle2 size={16} className={`mt-0.5 shrink-0 ${item.available ? 'text-emerald-600' : 'text-amber-600'}`} /><div className="min-w-0 flex-1"><h3 className="text-sm font-semibold">{labelFor(item)}</h3><Description item={item} kind="gateway" />{required.length > 0 && <p className="mt-2 text-xs text-muted-foreground">Environment setup: {required.map(group => group.join(' or ')).join(' · ')}</p>}{item.available === false && <p className="mt-1 text-xs text-amber-700">It cannot start until the required environment variables are configured.</p>}</div><button onClick={() => onToggle(id, !enabled)} disabled={pending === id} className={`rounded-md px-2.5 py-1 text-xs ${enabled ? 'bg-foreground text-background' : 'border border-border text-muted-foreground'}`}>{pending === id ? 'Saving…' : enabled ? 'On' : 'Off'}</button></div></div> })}</div>
}

function ScheduledJobsManager({ jobs, onChanged, onError }: { jobs: InventoryItem[]; onChanged: () => void; onError: (message: string) => void }) {
  const [name, setName] = useState(''); const [prompt, setPrompt] = useState(''); const [interval, setInterval] = useState('60'); const [saving, setSaving] = useState(false)
  const submit = async (event: FormEvent) => { event.preventDefault(); setSaving(true); onError(''); try { await api.createCronJob({ name, prompt, interval_minutes: Number(interval) }); setName(''); setPrompt(''); setInterval('60'); onChanged() } catch (err) { onError(err instanceof Error ? err.message : 'Could not create the scheduled job.') } finally { setSaving(false) } }
  const runAction = async (operation: () => Promise<unknown>) => { try { await operation(); onChanged() } catch (err) { onError(err instanceof Error ? err.message : 'Could not update the scheduled job.') } }
  return <div className="space-y-5"><form onSubmit={submit} className="grid gap-3 rounded-lg border border-border bg-secondary/30 p-4"><div><h3 className="text-sm font-semibold">Create scheduled job</h3><p className="mt-1 text-xs text-muted-foreground">Jobs run on this Nexus server while it is online and are saved in Nexus configuration.</p></div><label className="grid gap-1 text-xs font-medium">Name<input required value={name} onChange={event => setName(event.target.value)} placeholder="e.g. Daily project health check" className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal" /></label><label className="grid gap-1 text-xs font-medium">Every (minutes)<input required min="1" max="43200" type="number" value={interval} onChange={event => setInterval(event.target.value)} className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal" /></label><label className="grid gap-1 text-xs font-medium">Task prompt<textarea required value={prompt} onChange={event => setPrompt(event.target.value)} rows={3} placeholder="What Nexus should do when this job runs" className="rounded-md border border-border bg-background px-2 py-2 text-sm font-normal" /></label><div className="flex justify-end"><button disabled={saving} className="rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background disabled:opacity-50">{saving ? 'Creating…' : 'Create job'}</button></div></form>{!jobs.length ? <p className="py-4 text-sm text-muted-foreground">No scheduled jobs are configured.</p> : <div className="divide-y divide-border rounded-lg border border-border bg-card">{jobs.map(job => { const id = String(job.id || ''); const enabled = Boolean(job.enabled); return <div key={id} className="flex items-start gap-3 px-4 py-3"><Clock3 size={16} className="mt-0.5 text-muted-foreground" /><div className="min-w-0 flex-1"><p className="text-sm font-medium">{labelFor(job)}</p><p className="mt-1 text-xs text-muted-foreground">Every {String(job.interval_minutes || '?')} minutes · Last result: {String(job.last_status || 'never')} · Runs: {String(job.run_count || 0)}</p>{job.last_error ? <p className="mt-1 text-xs text-destructive">{String(job.last_error)}</p> : null}</div><div className="flex flex-wrap justify-end gap-2"><button onClick={() => runAction(() => api.updateCronJob(id, { enabled: !enabled }))} className="rounded-md border border-border px-2 py-1 text-xs">{enabled ? 'Pause' : 'Enable'}</button><button disabled={!enabled} onClick={() => runAction(() => api.runCronJob(id))} className="rounded-md border border-border px-2 py-1 text-xs disabled:opacity-40">Run now</button><button onClick={() => { if (window.confirm(`Delete scheduled job “${labelFor(job)}”?`)) void runAction(() => api.deleteCronJob(id)) }} className="px-2 py-1 text-xs text-destructive">Delete</button></div></div> })}</div>}</div>
}

type ProviderProfileItem = { name: string; model?: string; endpoint?: string; active?: boolean; is_default?: boolean; has_credentials?: boolean }

function ProviderList({ providers, pending, onToggle, onChanged }: { providers: InventoryItem[]; pending: string; onToggle: (name: string, enabled: boolean) => void; onChanged: () => void }) {
  const [addingCustom, setAddingCustom] = useState(false)
  const [customName, setCustomName] = useState('')
  const [customId, setCustomId] = useState('')
  const [customType, setCustomType] = useState<'api_key' | 'local'>('api_key')
  const [customModel, setCustomModel] = useState('')
  const [customEndpoint, setCustomEndpoint] = useState('')
  const [customApiKey, setCustomApiKey] = useState('')
  const [customError, setCustomError] = useState('')
  const [creatingCustom, setCreatingCustom] = useState(false)
  const local = providers.filter(provider => provider.group === 'local')
  const oauth = providers.filter(provider => provider.group === 'oauth')
  const cloud = providers.filter(provider => provider.group === 'cloud' || !provider.group)
  const resetCustom = () => { setAddingCustom(false); setCustomName(''); setCustomId(''); setCustomType('api_key'); setCustomModel(''); setCustomEndpoint(''); setCustomApiKey(''); setCustomError('') }
  const createCustom = async (event: FormEvent) => {
    event.preventDefault(); setCreatingCustom(true); setCustomError('')
    try {
      await api.addCustomProvider({ name: customName.trim(), id: customId.trim() || undefined, connection_type: customType, model: customModel.trim(), endpoint: customEndpoint.trim(), ...(customType === 'api_key' && customApiKey ? { api_key: customApiKey } : {}) })
      resetCustom(); onChanged()
    } catch (error) { setCustomError(error instanceof Error ? error.message : 'Could not add the custom provider.') }
    finally { setCreatingCustom(false) }
  }
  return <div className="space-y-6">
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-end justify-between gap-3"><div><h3 className="text-sm font-semibold">Add custom provider</h3><p className="mt-1 text-xs text-muted-foreground">Create a new OpenAI-compatible API or local provider. This does not select from the installed provider list.</p></div><button type="button" onClick={() => setAddingCustom(value => !value)} className="rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background">{addingCustom ? 'Close' : 'Add provider'}</button></div>
      {addingCustom && <form className="mt-4 grid gap-3 border-t border-border pt-4 sm:grid-cols-2" onSubmit={createCustom}>
        <label className="grid gap-1 text-xs font-medium">Provider name<input required value={customName} onChange={event => setCustomName(event.target.value)} placeholder="e.g. My company AI" className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal outline-none focus:border-ring" /></label>
        <label className="grid gap-1 text-xs font-medium">Provider id <span className="font-normal text-muted-foreground">(optional)</span><input value={customId} onChange={event => setCustomId(event.target.value)} placeholder="e.g. company-ai" className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal outline-none focus:border-ring" /></label>
        <label className="grid gap-1 text-xs font-medium">Connection type<select value={customType} onChange={event => setCustomType(event.target.value as 'api_key' | 'local')} className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal outline-none focus:border-ring"><option value="api_key">Cloud API key</option><option value="local">Local or self-hosted</option></select></label>
        <label className="grid gap-1 text-xs font-medium">Model<input required value={customModel} onChange={event => setCustomModel(event.target.value)} placeholder="e.g. my-model" className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal outline-none focus:border-ring" /></label>
        <label className="grid gap-1 text-xs font-medium sm:col-span-2">OpenAI-compatible chat-completions endpoint<input required value={customEndpoint} onChange={event => setCustomEndpoint(event.target.value)} placeholder="https://api.example.com/v1/chat/completions" className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal outline-none focus:border-ring" /></label>
        {customType === 'api_key' && <label className="grid gap-1 text-xs font-medium sm:col-span-2">API key <span className="font-normal text-muted-foreground">(optional)</span><input type="password" value={customApiKey} onChange={event => setCustomApiKey(event.target.value)} autoComplete="new-password" placeholder="Saved locally and never displayed again" className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal outline-none focus:border-ring" /></label>}
        {customError && <p className="sm:col-span-2 text-xs text-destructive" role="alert">{customError}</p>}<div className="sm:col-span-2 flex justify-end gap-2"><button type="button" onClick={resetCustom} className="rounded-md border border-border px-3 py-1.5 text-xs">Cancel</button><button disabled={creatingCustom} className="rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background disabled:opacity-50">{creatingCustom ? 'Adding…' : 'Add provider'}</button></div>
      </form>}
    </section>
    <ProviderGroup title="Local providers" detail="Run on this computer or a self-hosted endpoint." providers={local} pending={pending} onToggle={onToggle} onChanged={onChanged} />
    <ProviderGroup title="Cloud API-key providers" detail="Use a provider API key and an optional model or endpoint profile." providers={cloud} pending={pending} onToggle={onToggle} onChanged={onChanged} />
    <ProviderGroup title="OAuth account providers" detail="Sign in through the provider account flow managed by Nexus; these do not use API-key profiles." providers={oauth} pending={pending} onToggle={onToggle} onChanged={onChanged} />
  </div>
}

function ProviderGroup({ title, detail, providers, pending, onToggle, onChanged }: { title: string; detail: string; providers: InventoryItem[]; pending: string; onToggle: (name: string, enabled: boolean) => void; onChanged: () => void }) {
  if (!providers.length) return null
  return <section><div className="mb-2"><h3 className="text-sm font-semibold">{title}</h3><p className="mt-0.5 text-xs text-muted-foreground">{detail}</p></div><div className="divide-y divide-border rounded-lg border border-border bg-card">{providers.map(provider => <ProviderRow key={String(provider.id)} provider={provider} pending={pending} onToggle={onToggle} onChanged={onChanged} openRequested={false} />)}</div></section>
}

function ProviderRow({ provider, pending, onToggle, onChanged, openRequested }: { provider: InventoryItem; pending: string; onToggle: (name: string, enabled: boolean) => void; onChanged: () => void; openRequested: boolean }) {
  const name = String(provider.id || provider.name || '')
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [profileName, setProfileName] = useState('')
  const [model, setModel] = useState('')
  const [endpoint, setEndpoint] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [working, setWorking] = useState(false)
  const [profileError, setProfileError] = useState('')
  const [oauthRun, setOauthRun] = useState<OAuthLoginRun | null>(null)
  const [oauthCode, setOauthCode] = useState('')
  const active = provider.active === true
  const saving = pending === name
  const profiles = Array.isArray(provider.profiles) ? provider.profiles as ProviderProfileItem[] : []
  const providerKind = provider.group === 'oauth' ? 'oauth' : provider.group === 'local' ? 'local' : 'cloud'
  const usesApiKey = providerKind === 'cloud'
  const usesOAuth = providerKind === 'oauth'
  const oauthConnected = provider.oauth_connected === true
  useEffect(() => { if (openRequested) setExpanded(true) }, [openRequested])
  useEffect(() => {
    if (!oauthRun || ['connected', 'failed', 'cancelled'].includes(oauthRun.status)) return
    const timer = window.setInterval(() => {
      api.getProviderOAuthLogin(oauthRun.id).then(run => {
        setOauthRun(run)
        if (run.status === 'connected') onChanged()
      }).catch(error => setProfileError(error instanceof Error ? error.message : 'Could not check sign-in status.'))
    }, 1200)
    return () => window.clearInterval(timer)
  }, [oauthRun?.id, oauthRun?.status, onChanged])
  const resetForm = () => { setEditing(null); setProfileName(''); setModel(''); setEndpoint(''); setApiKey(''); setProfileError('') }
  const editProfile = (profile: ProviderProfileItem) => { setEditing(profile.name); setProfileName(profile.name); setModel(profile.model || ''); setEndpoint(profile.endpoint || ''); setApiKey(''); setProfileError('') }
  const saveProfile = async (event: FormEvent) => {
    event.preventDefault()
    if (!profileName.trim()) { setProfileError('A profile nickname is required.'); return }
    setWorking(true); setProfileError('')
    try {
      if (editing) await api.updateProviderProfile(name, editing, { name: profileName.trim(), model: model.trim(), endpoint: endpoint.trim(), ...(apiKey ? { api_key: apiKey } : {}) })
      else await api.addProviderProfile(name, { name: profileName.trim(), model: model.trim(), endpoint: endpoint.trim(), ...(apiKey ? { api_key: apiKey } : {}) })
      resetForm(); onChanged()
    } catch (error) { setProfileError(error instanceof Error ? error.message : 'Could not save the provider profile.') }
    finally { setWorking(false) }
  }
  const removeProfile = async (profile: ProviderProfileItem) => {
    if (!window.confirm(`Delete provider profile “${profile.name}”?`)) return
    setWorking(true); setProfileError('')
    try { await api.deleteProviderProfile(name, profile.name); if (editing === profile.name) resetForm(); onChanged() }
    catch (error) { setProfileError(error instanceof Error ? error.message : 'Could not delete the provider profile.') }
    finally { setWorking(false) }
  }
  const startOAuth = async () => {
    setWorking(true); setProfileError('')
    try {
      const run = await api.startProviderOAuthLogin(name)
      setOauthRun(run)
      if (run.url) window.open(run.url, '_blank', 'noopener,noreferrer')
    } catch (error) { setProfileError(error instanceof Error ? error.message : 'Could not start OAuth sign-in.') }
    finally { setWorking(false) }
  }
  const submitOAuthCode = async (event: FormEvent) => {
    event.preventDefault()
    if (!oauthRun || !oauthCode.trim()) return
    setWorking(true); setProfileError('')
    try { setOauthRun(await api.submitProviderOAuthCode(oauthRun.id, oauthCode.trim())); setOauthCode('') }
    catch (error) { setProfileError(error instanceof Error ? error.message : 'Could not submit the authorization code.') }
    finally { setWorking(false) }
  }
  const disconnectOAuth = async () => {
    if (!window.confirm(`Disconnect the saved ${labelFor(provider)} account?`)) return
    setWorking(true); setProfileError('')
    try { await api.disconnectProviderOAuthAccount(name); setOauthRun(null); onChanged() }
    catch (error) { setProfileError(error instanceof Error ? error.message : 'Could not disconnect this account.') }
    finally { setWorking(false) }
  }
  return <div id={`provider-${name}`} className="px-4 py-3">
    <button type="button" onClick={() => setExpanded(value => !value)} aria-expanded={expanded} className="flex w-full items-start gap-3 rounded-md text-left transition hover:bg-secondary/40">
      {active ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-emerald-600" /> : <CircleAlert size={16} className="mt-0.5 shrink-0 text-amber-600" />}
      <div className="min-w-0 flex-1"><p className="text-sm font-medium text-foreground">{labelFor(provider)}</p><Description item={provider} kind="provider" />{usesOAuth ? <p className="mt-1 text-xs text-muted-foreground">OAuth: {oauthConnected ? 'connected' : 'not connected'}</p> : <p className="mt-1 text-xs text-muted-foreground">Profiles: {profiles.length}</p>}</div>
    </button>
    <div className="mt-2 flex justify-end">{usesOAuth ? <button type="button" onClick={oauthConnected ? disconnectOAuth : startOAuth} disabled={working} className="rounded-md bg-foreground px-2.5 py-1 text-xs font-medium text-background transition hover:opacity-80 disabled:opacity-50">{working ? 'Working…' : oauthConnected ? 'Disconnect' : 'Sign in'}</button> : <button type="button" onClick={event => { event.stopPropagation(); onToggle(name, !active) }} disabled={saving} className={`rounded-md px-2.5 py-1 text-xs font-medium transition disabled:opacity-50 ${active ? 'bg-foreground text-background hover:opacity-80' : 'border border-border text-muted-foreground hover:bg-secondary'}`}>{saving ? 'Saving…' : active ? 'On' : 'Off'}</button>}</div>
    {expanded && <div className="mt-3 border-t border-border pt-3">
      {usesOAuth ? <div className="rounded-md border border-border bg-secondary/30 p-3"><p className="text-sm font-medium">OAuth account</p><p className="mt-1 text-xs text-muted-foreground">{oauthConnected ? 'A real OAuth token is saved in the Nexus OAuth store.' : 'Use Sign in to open this provider’s real browser authorization flow. API keys are not accepted for this provider.'}</p>{oauthRun && <div className="mt-3 rounded border border-border bg-background p-3" role="status"><p className="text-xs font-medium capitalize">{oauthRun.status.replace(/_/g, ' ')}</p><p className="mt-1 text-xs text-muted-foreground">{oauthRun.message || 'Waiting for the provider…'}</p>{oauthRun.url && oauthRun.status !== 'connected' && <a className="mt-2 inline-block text-xs font-medium underline" href={oauthRun.url} target="_blank" rel="noreferrer">Open sign-in page</a>}{oauthRun.status === 'waiting_for_code' && <form className="mt-3 flex gap-2" onSubmit={submitOAuthCode}><input value={oauthCode} onChange={event => setOauthCode(event.target.value)} placeholder="Paste redirect URL or code" className="h-8 min-w-0 flex-1 rounded border border-border bg-background px-2 text-xs" /><button disabled={working || !oauthCode.trim()} className="rounded bg-foreground px-2 text-xs text-background disabled:opacity-50">Submit</button></form>}{!['connected', 'failed', 'cancelled'].includes(oauthRun.status) && <button type="button" onClick={async () => { await api.cancelProviderOAuthLogin(oauthRun.id); setOauthRun(null) }} className="mt-3 text-xs text-muted-foreground underline">Cancel sign-in</button>}</div>}{profileError && <p className="mt-3 text-xs text-destructive" role="alert">{profileError}</p>}</div> : <>
      {profiles.length > 0 && <ol className="mb-4 space-y-2">{profiles.map((profile, index) => <li key={profile.name} className="flex flex-wrap items-start gap-3 rounded-md border border-border px-3 py-2"><span className="mt-0.5 text-xs font-semibold text-muted-foreground">{index + 1}.</span><div className="min-w-0 flex-1"><p className="text-sm font-medium">{profile.name}{profile.is_default ? <span className="ml-2 text-xs font-normal text-emerald-700">Default</span> : null}</p><p className="mt-0.5 text-xs text-muted-foreground">Model: {profile.model || 'not set'} · Endpoint: {profile.endpoint || 'default'}</p>{usesApiKey && <p className="mt-0.5 text-xs text-muted-foreground">API key: {profile.has_credentials ? 'saved' : 'not added'}</p>}</div><div className="flex gap-2 text-xs"><button type="button" onClick={() => editProfile(profile)} className="text-muted-foreground hover:text-foreground">Edit</button>{!profile.is_default && <button type="button" disabled={working} onClick={async () => { setWorking(true); try { await api.setDefaultProviderProfile(name, profile.name); onChanged() } finally { setWorking(false) } }} className="text-muted-foreground hover:text-foreground">Default</button>}<button type="button" disabled={working} onClick={() => removeProfile(profile)} className="text-destructive hover:opacity-80">Delete</button></div></li>)}</ol>}
      <form className="grid gap-3 rounded-md border border-border bg-secondary/30 p-3 sm:grid-cols-2" onSubmit={saveProfile}>
        <p className="sm:col-span-2 text-sm font-medium">{editing ? `Edit profile: ${editing}` : 'Add'}</p>
        <label className="grid gap-1 text-xs font-medium">Nickname<input value={profileName} onChange={event => setProfileName(event.target.value)} placeholder={usesApiKey ? 'e.g. Work key' : 'e.g. Local model'} className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal outline-none focus:border-ring" /></label>
        <label className="grid gap-1 text-xs font-medium">Model<input value={model} onChange={event => setModel(event.target.value)} placeholder={usesApiKey ? 'e.g. provider-chat' : 'e.g. llama3.2'} className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal outline-none focus:border-ring" /></label>
        <label className="grid gap-1 text-xs font-medium">Endpoint<input value={endpoint} onChange={event => setEndpoint(event.target.value)} placeholder={usesApiKey ? 'Optional API endpoint' : 'Local server endpoint'} className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal outline-none focus:border-ring" /></label>
        {usesApiKey && <label className="grid gap-1 text-xs font-medium">API key<input type="password" value={apiKey} onChange={event => setApiKey(event.target.value)} placeholder={editing ? 'Leave blank to keep saved key' : 'Optional; saved locally'} autoComplete="new-password" className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal outline-none focus:border-ring" /></label>}
        {profileError && <p className="sm:col-span-2 text-xs text-destructive" role="alert">{profileError}</p>}<div className="sm:col-span-2 flex justify-end gap-2"><button type="button" onClick={resetForm} className="rounded-md border border-border px-3 py-1.5 text-xs">Cancel</button><button disabled={working} className="rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background disabled:opacity-50">{working ? 'Saving…' : editing ? 'Save' : 'Add'}</button></div>
      </form>
      </>}
    </div>}
  </div>
}

export default function SettingsPanel({ onClose }: { onClose: () => void }) {
  const { backendAvailable, sessions } = useStore()
  const [active, setActive] = useState<Section>('appearance')
  const [data, setData] = useState<Loaded>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [theme, setTheme] = useState(() => localStorage.getItem('nexus-theme') || 'light')
  const [pendingToggle, setPendingToggle] = useState('')

  useEffect(() => {
    const saved = localStorage.getItem('nexus-theme') || 'light'
    const themeClass = saved === 'dark' ? 'dark' : saved === 'light' ? '' : `theme-${saved}`
    document.documentElement.classList.remove('dark', 'theme-grey', 'theme-glass', 'theme-green', 'theme-blue', 'theme-purple')
    if (themeClass) document.documentElement.classList.add(themeClass)
  }, [])

  useEffect(() => {
    const loaders: Partial<Record<Section, () => Promise<unknown>>> = {
      providers: api.providers, skills: api.skills, tools: api.tools, plugins: api.plugins,
      mcp: api.mcp, hive: api.hives, gateway: api.gateways, cron: api.cronJobs,
      evolution: api.evolution, config: api.state, memory: api.state, chat: api.state, workspace: api.state,
      safety: api.state, notifications: api.state, voice: api.voiceStatus, billing: api.billing, about: api.version,
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
    if (active === 'appearance') return <Appearance theme={theme} onTheme={value => {
      setTheme(value); localStorage.setItem('nexus-theme', value);
      document.documentElement.classList.remove('dark', 'theme-grey', 'theme-glass', 'theme-green', 'theme-blue', 'theme-purple')
      const themeClass = value === 'dark' ? 'dark' : value === 'light' ? '' : `theme-${value}`
      if (themeClass) document.documentElement.classList.add(themeClass)
    }} />
    if (active === 'shortcuts') return <KeyboardShortcuts />
    if (loading) return <p className="py-8 text-sm text-muted-foreground" role="status">Loading live Nexus data…</p>
    if (error) return <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive" role="alert">Could not load this section: {error}</p>
    if (active === 'providers') {
      const response = data.providers as { providers?: InventoryItem[] } | undefined
      return response?.providers?.length ? <ProviderList providers={response.providers} pending={pendingToggle.replace('provider:', '')} onToggle={(name, enabled) => toggle('provider', name, enabled)} onChanged={() => setData(current => { const next = { ...current }; delete next.providers; return next })} /> : <p className="py-8 text-sm text-muted-foreground">No provider implementations were reported.</p>
    }
    if (active === 'chat') return <ChatSettings state={(data.chat as Record<string, unknown> | undefined) || {}} sessions={sessions.length} />
    if (active === 'workspace') return <WorkspaceSettings state={(data.workspace as Record<string, unknown> | undefined) || {}} />
    if (active === 'safety') return <SafetySettings state={(data.safety as Record<string, unknown> | undefined) || {}} onSaved={() => setData(current => { const next = { ...current }; delete next.safety; delete next.config; return next })} />
    if (active === 'memory') return <MemorySettings state={(data.memory as Record<string, unknown> | undefined) || {}} />
    if (active === 'voice') return <VoiceSettings status={(data.voice as { running?: boolean; mode?: string; phase?: string; transcript_preview?: string; reply_preview?: string } | undefined)} onChanged={() => setData(current => { const next = { ...current }; delete next.voice; return next })} />
    if (active === 'notifications') return <NotificationSettings />
    if (active === 'skills') return <InventoryList items={(data.skills as { skills?: InventoryItem[] } | undefined)?.skills || []} empty="Nexus reported no installed skills." kind="skill" pending={pendingToggle.replace('skill:', '')} onToggle={(name, enabled) => toggle('skill', name, enabled)} />
    if (active === 'tools') return <InventoryList items={(data.tools as { tools?: InventoryItem[] } | undefined)?.tools || []} empty="Nexus reported no registered tools." kind="tool" pending={pendingToggle.replace('tool:', '')} onToggle={(name, enabled) => toggle('tool', name, enabled)} />
    if (active === 'plugins') return <InventoryList items={(data.plugins as { plugins?: InventoryItem[] } | undefined)?.plugins || []} empty="No plugins are installed or configured." kind="plugin" pending={pendingToggle.replace('plugin:', '')} onToggle={(name, enabled) => toggle('plugin', name, enabled)} />
    if (active === 'mcp') return <McpManager items={(data.mcp as { mcp?: InventoryItem[] } | undefined)?.mcp || []} pending={pendingToggle.replace('mcp:', '')} onToggle={(name, enabled) => toggle('mcp', name, enabled)} onChanged={() => setData(current => { const next = { ...current }; delete next.mcp; return next })} onError={setError} />
    if (active === 'hive') return <HiveManager response={data.hive as { enabled: boolean; personas: string[]; hives: HiveItem[] } | undefined} pending={pendingToggle === 'hive:hive'} onToggle={enabled => toggle('hive', 'hive', enabled)} onChanged={() => setData(current => { const next = { ...current }; delete next.hive; return next })} onError={setError} />
    if (active === 'evolution') {
      const evolution = data.evolution as { enabled?: boolean; version?: string; lifecycle?: InventoryItem[]; forges?: InventoryItem[] } | undefined
      return <EvolutionPanel evolution={evolution} onToggle={toggle} pending={pendingToggle} />
    }
    if (active === 'config') return <ConfigurationPanel state={(data.config as Record<string, unknown> | undefined) || {}} onSaved={() => setData(current => { const next = { ...current }; delete next.config; return next })} />
    if (active === 'gateway') return <GatewayManager items={(data.gateway as { gateways?: InventoryItem[] } | undefined)?.gateways || []} pending={pendingToggle.replace('gateway:', '')} onToggle={(name, enabled) => toggle('gateway', name, enabled)} />
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
      return <div className="space-y-3"><InfoBlock title="Nexus AI" value={version?.version || 'Version unavailable'} detail={version?.service || 'Local-first autonomous agent framework'} /><InfoBlock title="Connection" value={backendAvailable ? 'Backend connected' : 'Backend disconnected'} detail={`${sessions.length} local chat session${sessions.length === 1 ? '' : 's'}`} /></div>
    }
    return <LiveData data={(data[active] as Record<string, unknown> | undefined) || {}} empty={`Nexus did not report ${active} data.`} />
  }, [active, backendAvailable, data, error, loading, sessions.length, theme])

  const activeLabel = sections.find(section => section.id === active)?.label || 'Settings'
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/20 p-4 backdrop-blur-[1px]" role="dialog" aria-modal="true" aria-label="Nexus settings">
      <div
        className="flex overflow-hidden rounded-xl border border-border bg-background shadow-2xl"
        style={{
          width: "min(1240px, calc(100vw - 32px))",
          height: "min(760px, calc(100vh - 32px))",
        }}
      >
      <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-secondary/35 p-3">
        <div className="mb-4 px-2 pt-1"><p className="text-sm font-semibold">Nexus settings</p><p className="mt-0.5 text-xs text-muted-foreground">Workspace configuration</p></div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto" aria-label="Settings sections">
          {sections.map(section => { const Icon = section.icon; return <button key={section.id} onClick={() => setActive(section.id)} className={`flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition ${active === section.id ? 'bg-background font-medium text-foreground shadow-sm ring-1 ring-border' : 'text-muted-foreground hover:bg-background/70 hover:text-foreground'}`}><Icon size={16} />{section.label}</button> })}
        </nav>
      </aside>
      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border px-7 py-4"><div><h2 className="text-base font-semibold">{activeLabel}</h2><p className="mt-0.5 text-xs text-muted-foreground">{active === 'appearance' ? 'Preferences saved on this device.' : 'Data reported by your running Nexus server.'}</p></div><button onClick={onClose} className="flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground" aria-label="Close settings"><X size={17} /></button></header>
        <div className="flex-1 overflow-y-auto px-7 py-6"><div className="mx-auto max-w-4xl">{content}</div></div>
      </section>
    </div>
  </div>
}

function Appearance({ theme, onTheme }: { theme: string; onTheme: (theme: string) => void }) {
  const options = [
    { value: 'light', label: 'Light', detail: 'Bright, clean workspace', bg: 'bg-white', dotDark: 'bg-gray-900', dotMid: 'bg-gray-300', dotLight: 'bg-gray-100' },
    { value: 'dark', label: 'Dark', detail: 'Low-light, easy on the eyes', bg: 'bg-gray-900', dotDark: 'bg-gray-100', dotMid: 'bg-gray-500', dotLight: 'bg-gray-700' },
    { value: 'grey', label: 'Grey', detail: 'Neutral grey tones', bg: 'bg-gray-100', dotDark: 'bg-gray-700', dotMid: 'bg-gray-400', dotLight: 'bg-gray-200' },
    { value: 'glass', label: 'Glass', detail: 'Translucent soft overlay', bg: 'bg-white/40', dotDark: 'bg-sky-300', dotMid: 'bg-white/60', dotLight: 'bg-sky-100' },
    { value: 'green', label: 'Green', detail: 'Calming green palette', bg: 'bg-green-900', dotDark: 'bg-green-100', dotMid: 'bg-green-400', dotLight: 'bg-green-700' },
    { value: 'blue', label: 'Blue', detail: 'Cool blue workspace', bg: 'bg-blue-900', dotDark: 'bg-blue-100', dotMid: 'bg-blue-400', dotLight: 'bg-blue-700' },
    { value: 'purple', label: 'Purple', detail: 'Creative purple mode', bg: 'bg-purple-900', dotDark: 'bg-purple-100', dotMid: 'bg-purple-400', dotLight: 'bg-purple-700' },
    { value: 'pink', label: 'Pink', detail: 'Soft pink accents', bg: 'bg-pink-900', dotDark: 'bg-pink-100', dotMid: 'bg-pink-400', dotLight: 'bg-pink-700' },
    { value: 'red', label: 'Red', detail: 'Bold red highlights', bg: 'bg-red-900', dotDark: 'bg-red-100', dotMid: 'bg-red-400', dotLight: 'bg-red-700' },
    { value: 'orange', label: 'Orange', detail: 'Warm orange tones', bg: 'bg-orange-900', dotDark: 'bg-orange-100', dotMid: 'bg-orange-400', dotLight: 'bg-orange-700' },
  ] as const
  return <div className="space-y-6"><div><h3 className="text-sm font-semibold">Color theme</h3><p className="mt-1 text-sm text-muted-foreground">Choose how Nexus looks in this browser. Themes apply instantly and are saved to this device.</p></div><div className="grid max-w-3xl grid-cols-2 gap-3 sm:grid-cols-3">{options.map(choice => <button key={choice.value} onClick={() => onTheme(choice.value)} className={`rounded-xl border p-4 text-left transition hover:border-foreground/60 ${theme === choice.value ? 'border-foreground bg-secondary ring-1 ring-foreground/25' : 'border-border'}`}><div className={`mb-3 flex items-center gap-1.5 rounded-lg border border-border/70 px-2 py-1.5 ${choice.bg}`}><span className={`h-3 w-3 rounded-full ${choice.dotDark}`} /><span className={`h-3 w-3 rounded-full ${choice.dotMid}`} /><span className={`h-3 w-3 rounded-full ${choice.dotLight}`} /></div><p className="font-medium capitalize">{choice.label}</p><p className="mt-1 text-xs text-muted-foreground">{choice.detail}</p>{theme === choice.value && <span className="mt-2 inline-flex items-center gap-1.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-400"><span className="h-1.5 w-1.5 rounded-full bg-current" />Active</span>}</button>)}</div></div>
}

function ChatSettings({ state, sessions }: { state: Record<string, unknown>; sessions: number }) {
  const running = Number(state.task_count || 0)
  return <div className="space-y-4"><div><h3 className="text-sm font-semibold">Chat sessions</h3><p className="mt-1 text-sm text-muted-foreground">Conversation history is stored locally by the Nexus server and restored when you reopen a session.</p></div><div className="grid gap-3 sm:grid-cols-2"><InfoBlock title="Saved sessions" value={String(sessions)} detail="Sessions currently loaded in the GUI." /><InfoBlock title="Recorded tasks" value={String(running)} detail="Tasks reported by the running Nexus server." /></div><div className="rounded-lg border border-border bg-card p-4"><p className="text-sm font-medium">Message controls</p><p className="mt-1 text-sm text-muted-foreground">Enter sends a message. Shift + Enter adds a new line. Use Stop while a response is actively running.</p></div></div>
}

function WorkspaceSettings({ state }: { state: Record<string, unknown> }) {
  const dirs = Array.isArray(state.additional_dirs) ? state.additional_dirs as string[] : []
  return <div className="space-y-4"><div><h3 className="text-sm font-semibold">Workspace access</h3><p className="mt-1 text-sm text-muted-foreground">Nexus tools operate in the current project workspace. Additional directories are controlled by the runtime configuration.</p></div><InfoBlock title="Additional directories" value={String(dirs.length)} detail={dirs.length ? dirs.join(', ') : 'No additional directories are configured.'} /><div className="rounded-lg border border-border bg-card p-4"><p className="text-sm font-medium">File activity</p><p className="mt-1 text-sm text-muted-foreground">Real file reads, creates, edits, and deletes appear in the chat activity cards. Open Configuration to change allowed directories.</p></div></div>
}

function SafetySettings({ state, onSaved }: { state: Record<string, unknown>; onSaved: () => void }) {
  const [permission, setPermission] = useState(String(state.mode || 'auto'))
  const [sandbox, setSandbox] = useState(String(state.sandbox_tier || 'normal'))
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  useEffect(() => { setPermission(String(state.mode || 'auto')); setSandbox(String(state.sandbox_tier || 'normal')) }, [state])
  const save = async () => { setSaving(true); setMessage(''); try { await Promise.all([api.setPermissions(permission), api.setSandbox(sandbox)]); setMessage('Safety settings saved.'); onSaved() } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not save safety settings.') } finally { setSaving(false) } }
  return <div className="space-y-5"><div><h3 className="text-sm font-semibold">Command safeguards</h3><p className="mt-1 text-sm text-muted-foreground">These are real runtime controls used before Nexus runs tools and commands.</p></div><div className="grid gap-4 rounded-lg border border-border bg-card p-4 md:grid-cols-2"><label className="grid gap-1.5 text-sm font-medium">Permission mode<select value={permission} onChange={event => setPermission(event.target.value)} className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal"><option value="auto">Automatic</option><option value="ask">Ask every time</option><option value="allowlist">Allowlist only</option><option value="all">Allow all</option></select></label><label className="grid gap-1.5 text-sm font-medium">Sandbox tier<select value={sandbox} onChange={event => setSandbox(event.target.value)} className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal"><option value="no_sandbox">No Sandbox</option><option value="normal">Sandbox</option><option value="docker">Advanced Sandbox</option></select></label></div><div className="flex items-center justify-between gap-4"><p className={`text-sm ${message === 'Safety settings saved.' ? 'text-emerald-700' : 'text-destructive'}`} role="status">{message}</p><button type="button" disabled={saving} onClick={save} className="rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background disabled:opacity-50">{saving ? 'Saving…' : 'Save safety settings'}</button></div></div>
}

function MemorySettings({ state }: { state: Record<string, unknown> }) {
  return <div className="space-y-4"><div><h3 className="text-sm font-semibold">Memory & context</h3><p className="mt-1 text-sm text-muted-foreground">Nexus synchronizes session messages to local memory when a session is loaded or completed.</p></div><div className="grid gap-3 sm:grid-cols-2"><InfoBlock title="Current sessions" value={String(state.session_count || 0)} detail="Sessions available to the running server." /><InfoBlock title="Agent capacity" value={String(state.agent_count || 0)} detail="Agents reported by the active Nexus runtime." /></div><div className="rounded-lg border border-border bg-card p-4"><p className="text-sm font-medium">Privacy</p><p className="mt-1 text-sm text-muted-foreground">Memory remains local to this Nexus installation unless you explicitly enable an external provider or gateway.</p></div></div>
}

function VoiceSettings({ status, onChanged }: { status?: { running?: boolean; mode?: string; phase?: string; transcript_preview?: string; reply_preview?: string }; onChanged: () => void }) {
  const [working, setWorking] = useState(false)
  const [message, setMessage] = useState('')
  const running = status?.running === true
  const change = async () => { setWorking(true); setMessage(''); try { if (running) await api.stopVoice(); else await api.startVoice('auto'); onChanged() } catch (error) { setMessage(error instanceof Error ? error.message : 'Voice service could not be changed.') } finally { setWorking(false) } }
  return <div className="space-y-4"><div><h3 className="text-sm font-semibold">Voice runtime</h3><p className="mt-1 text-sm text-muted-foreground">Controls the actual local voice process provided by Nexus.</p></div><InfoBlock title="Status" value={running ? 'Running' : 'Stopped'} detail={`Mode: ${status?.mode || 'off'} · Phase: ${status?.phase || 'off'}`} /><div className="rounded-lg border border-border bg-card p-4"><p className="text-sm font-medium">Latest voice activity</p><p className="mt-1 text-sm text-muted-foreground">{status?.transcript_preview || status?.reply_preview || 'No live voice transcript or reply is available.'}</p></div><div className="flex items-center justify-between gap-4"><p className="text-sm text-destructive" role="status">{message}</p><button type="button" disabled={working} onClick={change} className="rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background disabled:opacity-50">{working ? 'Working…' : running ? 'Stop voice' : 'Start voice'}</button></div></div>
}

function NotificationSettings() {
  const [enabled, setEnabled] = useState(() => localStorage.getItem('nexus-notifications') === 'enabled')
  const [message, setMessage] = useState('')
  const update = async () => { if (!enabled && 'Notification' in window) { const permission = await Notification.requestPermission(); if (permission !== 'granted') { setMessage('Browser notifications were not permitted.'); return } } const next = !enabled; setEnabled(next); localStorage.setItem('nexus-notifications', next ? 'enabled' : 'disabled'); setMessage(next ? 'Browser notifications are enabled on this device.' : 'Browser notifications are disabled on this device.') }
  const supported = typeof window !== 'undefined' && 'Notification' in window
  return <div className="space-y-4"><div><h3 className="text-sm font-semibold">Browser notifications</h3><p className="mt-1 text-sm text-muted-foreground">This preference is saved in this browser. Nexus will only use it when browser permission is granted.</p></div><div className="flex items-center gap-3 rounded-lg border border-border bg-card p-4"><div className="flex-1"><p className="text-sm font-medium">Task completion notifications</p><p className="mt-1 text-xs text-muted-foreground">{supported ? `Browser permission: ${Notification.permission}` : 'This browser does not support notifications.'}</p></div><button type="button" disabled={!supported} onClick={update} className={`rounded-md px-3 py-1.5 text-xs font-medium ${enabled ? 'bg-foreground text-background' : 'border border-border text-muted-foreground'}`}>{enabled ? 'On' : 'Off'}</button></div>{message && <p className="text-sm text-muted-foreground" role="status">{message}</p>}</div>
}

function BillingSettings({ billing }: { billing?: { tier?: string; message?: string; status?: string } }) {
  const configured = billing?.status && billing.status !== 'not_configured'
  return <div className="space-y-4"><div><h3 className="text-sm font-semibold">Billing</h3><p className="mt-1 text-sm text-muted-foreground">Nexus is local-first. Provider charges are handled by the provider account you configure, not by Nexus.</p></div><InfoBlock title="Nexus billing" value={configured ? billing?.status || 'Available' : 'Not configured'} detail={billing?.message || 'Nexus has no built-in billing system in this installation.'} /><div className="rounded-lg border border-border bg-card p-4"><p className="text-sm font-medium">Provider usage</p><p className="mt-1 text-sm text-muted-foreground">Review tokens, credits, and invoices in each cloud provider’s own account. Local providers do not use a Nexus billing account.</p></div></div>
}

function KeyboardShortcuts() {
  const shortcuts = [
    { keys: ['Ctrl', 'B'], action: 'Show or hide the chat history sidebar' },
    { keys: ['Ctrl', 'K'], action: 'Focus the chat-history search box' },
    { keys: ['Enter'], action: 'Send the message in the composer' },
    { keys: ['Shift', 'Enter'], action: 'Insert a new line in the composer' },
    { keys: ['Enter'], action: 'Confirm a file or chat rename', context: 'while renaming' },
    { keys: ['Esc'], action: 'Cancel a file or chat rename', context: 'while renaming' },
  ]
  return <div className="space-y-4"><div><h3 className="text-sm font-semibold">Available shortcuts</h3><p className="mt-1 text-sm text-muted-foreground">These are the shortcuts implemented in this Nexus GUI. Use ⌘ instead of Ctrl on macOS.</p></div><div className="divide-y divide-border rounded-lg border border-border bg-card">{shortcuts.map((shortcut, index) => <div key={`${shortcut.action}-${index}`} className="flex items-center justify-between gap-6 px-4 py-3"><div><p className="text-sm text-foreground">{shortcut.action}</p>{shortcut.context && <p className="mt-0.5 text-xs text-muted-foreground">{shortcut.context}</p>}</div><div className="flex shrink-0 items-center gap-1">{shortcut.keys.map(key => <kbd key={key} className="rounded border border-border bg-secondary px-1.5 py-0.5 text-xs font-medium text-foreground">{key}</kbd>)}</div></div>)}</div></div>
}

function ConfigurationPanel({ state, onSaved }: { state: Record<string, unknown>; onSaved: () => void }) {
  const value = (key: string) => String(state[key] || '')
  const [model, setModel] = useState('')
  const [provider, setProvider] = useState('')
  const [agent, setAgent] = useState('')
  const [goal, setGoal] = useState('')
  const [mode, setMode] = useState('auto')
  const [sandbox, setSandbox] = useState('normal')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    setModel(value('model') === 'auto' ? '' : value('model'))
    setProvider(value('provider') === 'auto' ? '' : value('provider'))
    setAgent(value('agent'))
    setGoal(value('goal'))
    setMode(value('mode') || 'auto')
    setSandbox(value('sandbox_tier') || 'normal')
  }, [state])

  const save = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setMessage('')
    try {
      await Promise.all([
        api.setModel(model || 'auto'), api.setProvider(provider || 'auto'), api.setAgent(agent), api.setGoal(goal), api.setPermissions(mode), api.setSandbox(sandbox),
      ])
      setMessage('Runtime configuration saved.')
      onSaved()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Nexus could not save the runtime configuration.')
    } finally { setSaving(false) }
  }

  return <form className="space-y-6" onSubmit={save}>
    <div><h3 className="text-sm font-semibold">Runtime configuration</h3><p className="mt-1 text-sm text-muted-foreground">These values apply to new and active Nexus sessions. Leave model or provider blank for automatic selection.</p></div>
    <div className="grid gap-4 rounded-lg border border-border bg-card p-4 md:grid-cols-2">
      <label className="grid gap-1.5 text-sm font-medium">Model<input value={model} onChange={event => setModel(event.target.value)} placeholder="Automatic" className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring" /></label>
      <label className="grid gap-1.5 text-sm font-medium">Provider<input value={provider} onChange={event => setProvider(event.target.value)} placeholder="Automatic" className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring" /></label>
      <label className="grid gap-1.5 text-sm font-medium">Agent<input value={agent} onChange={event => setAgent(event.target.value)} placeholder="Default agent" className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring" /></label>
      <label className="grid gap-1.5 text-sm font-medium">Active goal<input value={goal} onChange={event => setGoal(event.target.value)} placeholder="No active goal" className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring" /></label>
    </div>
    <div className="grid gap-4 rounded-lg border border-border bg-card p-4 md:grid-cols-2">
      <label className="grid gap-1.5 text-sm font-medium">Permission mode<select value={mode} onChange={event => setMode(event.target.value)} className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring"><option value="auto">Automatic</option><option value="ask">Ask every time</option><option value="allowlist">Allowlist only</option><option value="all">Allow all</option></select></label>
      <label className="grid gap-1.5 text-sm font-medium">Sandbox tier<select value={sandbox} onChange={event => setSandbox(event.target.value)} className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring"><option value="no_sandbox">No Sandbox</option><option value="normal">Sandbox</option><option value="docker">Advanced Sandbox</option></select></label>
    </div>
    <div className="flex items-center justify-between gap-4"><p className={`text-sm ${message === 'Runtime configuration saved.' ? 'text-emerald-700' : 'text-destructive'}`} role="status">{message}</p><button disabled={saving} className="rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background disabled:opacity-50">{saving ? 'Saving…' : 'Save configuration'}</button></div>
  </form>
}

function InfoBlock({ title, value, detail }: { title: string; value: string; detail: string }) {
  return <div className="mb-4 rounded-lg border border-border bg-card p-4"><p className="text-sm font-medium">{title}</p><p className="mt-2 text-lg font-semibold">{value}</p><p className="mt-1 text-sm text-muted-foreground">{detail}</p></div>
}

function EvolutionPanel({ evolution, onToggle, pending }: { evolution?: { enabled?: boolean; version?: string; lifecycle?: InventoryItem[]; forges?: InventoryItem[] }; onToggle: (kind: string, name: string, enabled: boolean) => void; pending: string }) {
  const enabled = evolution?.enabled === true
  const lifecycle = evolution?.lifecycle || []
  const forges = evolution?.forges || []
  return <div className="space-y-6">
    <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3"><span className={`size-2 rounded-full ${enabled ? 'bg-emerald-500' : 'bg-amber-500'}`} /><div className="flex-1"><p className="text-sm font-medium">Phonix evolution {evolution?.version || ''}</p><p className="text-xs text-muted-foreground">Lifecycle and forge availability are checked from your running Nexus server.</p></div><button onClick={() => onToggle('feature', 'evolution', !enabled)} disabled={pending === 'feature:evolution'} className={`rounded-md px-2.5 py-1 text-xs font-medium ${enabled ? 'bg-foreground text-background' : 'border border-border text-muted-foreground'}`}>{pending === 'feature:evolution' ? 'Saving…' : enabled ? 'On' : 'Off'}</button></div>
    <EvolutionGroup title="Lifecycle" detail="The ordered Phonix evolution pipeline." items={lifecycle} />
    <EvolutionGroup title="Forges" detail="Installed modules that create specialized evolution artifacts." items={forges} />
  </div>
}

function EvolutionGroup({ title, detail, items }: { title: string; detail: string; items: InventoryItem[] }) {
  return <section><div className="mb-2"><h3 className="text-sm font-semibold">{title}</h3><p className="mt-0.5 text-xs text-muted-foreground">{detail}</p></div>{items.length ? <div className="divide-y divide-border rounded-lg border border-border bg-card">{items.map(item => <div key={String(item.id)} className="flex items-start gap-3 px-4 py-3">{item.available === false ? <CircleAlert size={16} className="mt-0.5 shrink-0 text-amber-600" /> : <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-emerald-600" />}<div className="min-w-0 flex-1"><p className="text-sm font-medium text-foreground">{labelFor(item)}</p><Description item={item} /><p className="mt-1 text-xs text-muted-foreground">{item.available === false ? 'Unavailable in this runtime' : 'Available in this runtime'}</p></div></div>)}</div> : <p className="py-4 text-sm text-muted-foreground">No evolution components were reported by Nexus.</p>}</section>
}

function LiveData({ data, empty }: { data: Record<string, unknown>; empty: string }) {
  const entries = Object.entries(data)
  if (!entries.length) return <p className="py-8 text-sm text-muted-foreground">{empty}</p>
  return <div className="divide-y divide-border rounded-lg border border-border bg-card">{entries.map(([key, value]) => <div key={key} className="grid grid-cols-[minmax(120px,0.3fr)_1fr] gap-5 px-4 py-3"><p className="text-sm font-medium capitalize text-foreground">{key.replace(/_/g, ' ')}</p><p className="min-w-0 break-words text-sm text-muted-foreground">{typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' ? String(value) : JSON.stringify(value)}</p></div>)}</div>
}
