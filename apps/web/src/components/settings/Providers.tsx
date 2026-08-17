import { useState, useEffect, type FormEvent } from 'react'
import { CheckCircle2, CircleAlert } from 'lucide-react'
import { api, type InventoryItem, type ProviderDiagnostics, type RuntimeProviderStatus } from '../../lib/api'
import { labelFor, Description } from './utils'

type ProviderProfileItem = { name: string; model?: string; endpoint?: string; active?: boolean; is_default?: boolean; has_credentials?: boolean }
type OAuthLoginRun = { id: string; status: string; message?: string; url?: string }

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
    if (!window.confirm(`Delete provider profile "${profile.name}"?`)) return
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
      {usesOAuth ? (
        <div className="rounded-md border border-border bg-secondary/30 p-3">
          <p className="text-sm font-medium">OAuth account</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {oauthConnected ? 'A real OAuth token is saved in the Nexus OAuth store.' : 'Use Sign in to open this provider\'s real browser authorization flow. API keys are not accepted for this provider.'}
          </p>
          {oauthRun && (
            <div className="mt-3 rounded border border-border bg-background p-3" role="status">
              <p className="text-xs font-medium capitalize">{oauthRun.status.replace(/_/g, ' ')}</p>
              <p className="mt-1 text-xs text-muted-foreground">{oauthRun.message || 'Waiting for the provider…'}</p>
              {oauthRun.url && oauthRun.status !== 'connected' && (
                <a className="mt-2 inline-block text-xs font-medium underline" href={oauthRun.url} target="_blank" rel="noreferrer">Open sign-in page</a>
              )}
              {oauthRun.status === 'waiting_for_code' && (
                <form className="mt-3 flex gap-2" onSubmit={submitOAuthCode}>
                  <input value={oauthCode} onChange={event => setOauthCode(event.target.value)} placeholder="Paste redirect URL or code" className="h-8 min-w-0 flex-1 rounded border border-border bg-background px-2 text-xs" />
                  <button disabled={working || !oauthCode.trim()} className="rounded bg-foreground px-2 text-xs text-background disabled:opacity-50">Submit</button>
                </form>
              )}
              {!['connected', 'failed', 'cancelled'].includes(oauthRun.status) && (
                <button type="button" onClick={async () => { await api.cancelProviderOAuthLogin(oauthRun.id); setOauthRun(null) }} className="mt-3 text-xs text-muted-foreground underline">Cancel sign-in</button>
              )}
            </div>
          )}
          {profileError && <p className="mt-3 text-xs text-destructive" role="alert">{profileError}</p>}
        </div>
      ) : (
        <>
      {profiles.length > 0 && <ol className="mb-4 space-y-2">{profiles.map((profile, index) => <li key={profile.name} className="flex flex-wrap items-start gap-3 rounded-md border border-border px-3 py-2"><span className="mt-0.5 text-xs font-semibold text-muted-foreground">{index + 1}.</span><div className="min-w-0 flex-1"><p className="text-sm font-medium">{profile.name}{profile.is_default ? <span className="ml-2 text-xs font-normal text-emerald-700">Default</span> : null}</p><p className="mt-0.5 text-xs text-muted-foreground">Model: {profile.model || 'not set'} · Endpoint: {profile.endpoint || 'default'}</p>{usesApiKey && <p className="mt-0.5 text-xs text-muted-foreground">API key: {profile.has_credentials ? 'saved' : 'not added'}</p>}</div><div className="flex gap-2 text-xs"><button type="button" onClick={() => editProfile(profile)} className="text-muted-foreground hover:text-foreground">Edit</button>{!profile.is_default && <button type="button" disabled={working} onClick={async () => { setWorking(true); try { await api.setDefaultProviderProfile(name, profile.name); onChanged() } finally { setWorking(false) } }} className="text-muted-foreground hover:text-foreground">Default</button>}<button type="button" disabled={working} onClick={() => removeProfile(profile)} className="text-destructive hover:opacity-80">Delete</button></div></li>)}</ol>}
      <form className="grid gap-3 rounded-md border border-border bg-secondary/30 p-3 sm:grid-cols-2" onSubmit={saveProfile}>
        <p className="sm:col-span-2 text-sm font-medium">{editing ? `Edit profile: ${editing}` : 'Add'}</p>
        <label className="grid gap-1 text-xs font-medium">Nickname<input value={profileName} onChange={event => setProfileName(event.target.value)} placeholder={usesApiKey ? 'e.g. Work key' : 'e.g. Local model'} className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal outline-none focus:border-ring" /></label>
        <label className="grid gap-1 text-xs font-medium">Model<input value={model} onChange={event => setModel(event.target.value)} placeholder={usesApiKey ? 'e.g. provider-chat' : 'e.g. llama3.2'} className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal outline-none focus:border-ring" /></label>
        <label className="grid gap-1 text-xs font-medium">Endpoint<input value={endpoint} onChange={event => setEndpoint(event.target.value)} placeholder={usesApiKey ? 'Optional API endpoint' : 'Local server endpoint'} className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal outline-none focus:border-ring" /></label>
        {usesApiKey && <label className="grid gap-1 text-xs font-medium">API key<input type="password" value={apiKey} onChange={event => setApiKey(event.target.value)} placeholder={editing ? 'Leave blank to keep saved key' : 'Optional; saved locally'} autoComplete="new-password" className="h-9 rounded-md border border-border bg-background px-2 text-sm font-normal outline-none focus:border-ring" /></label>}
        {profileError && <p className="sm:col-span-2 text-xs text-destructive" role="alert">{profileError}</p>}<div className="sm:col-span-2 flex justify-end gap-2"><button type="button" onClick={resetForm} className="rounded-md border border-border px-3 py-1.5 text-xs">Cancel</button><button disabled={working} className="rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background disabled:opacity-50">{working ? 'Saving…' : editing ? 'Save' : 'Add'}</button></div>
      </form>
        </>
      )}
    </div>}
  </div>
}

export function ProviderList({ providers, pending, runtimeStatus, diagnostics, onToggle, onChanged }: { providers: InventoryItem[]; pending: string; runtimeStatus?: RuntimeProviderStatus; diagnostics?: ProviderDiagnostics; onToggle: (name: string, enabled: boolean) => void; onChanged: () => void }) {
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
  const reachability = runtimeStatus?.provider_status
  const recentAttempt = diagnostics?.attempts?.slice(-1)[0]
  const fallbackCount = diagnostics?.fallback_attempts || 0
  const runtimeLabel = runtimeStatus?.health === 'degraded' ? 'Degraded' : reachability?.reachable === true ? 'Reachable' : reachability?.reachable === false ? 'Unavailable' : 'Configured'
  const runtimeTone = runtimeStatus?.health === 'degraded' || reachability?.reachable === false ? 'border-amber-300 bg-amber-50 text-amber-900' : 'border-emerald-300 bg-emerald-50 text-emerald-900'
  const active = diagnostics?.active
  const cooldowns = diagnostics?.cooldowns || []
  const lastFailure = diagnostics?.last_failure
  return <div className="space-y-6">
    <section className={`rounded-lg border p-4 ${runtimeTone}`} role="status">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h3 className="text-sm font-semibold">Active runtime</h3><p className="mt-1 text-xs">Provider: {active?.provider || runtimeStatus?.provider || 'unknown'} · Profile: {active?.profile || 'default'} · Model: {active?.model || runtimeStatus?.model || 'unknown'}</p><p className="mt-1 text-xs opacity-80">{reachability?.reason === 'remote_probe_deferred' ? 'Remote reachability is checked when a request runs.' : reachability?.endpoint || 'The backend did not report an endpoint.'}</p><p className="mt-1 text-xs opacity-80">Fallback attempts in the current runtime: {diagnostics?.fallback_attempts || 0}</p>{lastFailure && <p className="mt-1 text-xs" role="status">Last failure: {lastFailure.provider || 'provider'}{lastFailure.profile ? `/${lastFailure.profile}` : ''} · {lastFailure.failure_class || 'unknown'}{lastFailure.reason ? ` · ${lastFailure.reason}` : ''}</p>}{cooldowns.length > 0 && <div className="mt-2 text-xs"><p className="font-medium">Cooling down</p><ul className="mt-1 space-y-0.5">{cooldowns.slice(0, 5).map(item => <li key={`${item.provider}-${item.profile}`}>{item.provider}/{item.profile}: {Math.ceil(item.cooldown_seconds || 0)}s{item.reason ? ` · ${item.reason}` : ''}</li>)}</ul></div>}</div>
        <span className="rounded-full border border-current/20 px-2 py-1 text-xs font-medium">{runtimeLabel}</span>
      </div>
      {recentAttempt && <p className="mt-2 text-xs opacity-80">Last route: {recentAttempt.provider_id || 'unknown'} · {recentAttempt.status || 'unknown'}{fallbackCount > 0 ? ` · ${fallbackCount} fallback${fallbackCount === 1 ? '' : 's'}` : ''}{recentAttempt.reason ? ` · ${recentAttempt.reason}` : ''}</p>}
    </section>
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
