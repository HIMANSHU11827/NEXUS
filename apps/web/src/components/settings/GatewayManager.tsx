import { useState } from 'react'
import { Globe, MessageSquare, Zap, Send, Network } from 'lucide-react'
import { type InventoryItem } from '../../lib/api'
import { labelFor, Description } from './utils'

type GatewayTab = 'overview' | 'platforms' | 'messages' | 'policy'

export function GatewayManager({ items, pending, onToggle }: { items: InventoryItem[]; pending: string; onToggle: (name: string, enabled: boolean) => void }) {
  const [activeTab, setActiveTab] = useState<GatewayTab>('overview')
  const available = items.filter(item => item.available)
  const enabled = items.filter(item => item.enabled)
  const activeConnections = items.filter(item => item.available && item.enabled)

  const tabs: { id: GatewayTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'platforms', label: 'Configured platforms' },
    { id: 'messages', label: 'Messages' },
    { id: 'policy', label: 'Integration policy' },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">Messaging Gateway</h3>
        <p className="mt-1 text-sm text-muted-foreground">Manage the messaging integrations reported by the running Nexus server.</p>
      </div>

      <div className="flex flex-wrap gap-2 border-b border-border">
        {tabs.map(tab => (
          <button key={tab.id} type="button" onClick={() => setActiveTab(tab.id)} className={`px-4 py-2 text-sm font-medium transition ${activeTab === tab.id ? 'border-b-2 border-foreground text-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'overview' && (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat icon={<Globe size={18} />} label="Configured platforms" value={items.length} detail={`${enabled.length} enabled`} />
            <Stat icon={<Network size={18} />} label="Available platforms" value={available.length} detail="Credentials detected" />
            <Stat icon={<Zap size={18} />} label="Active connections" value={activeConnections.length} detail="Enabled and available" />
            <Stat icon={<MessageSquare size={18} />} label="Message history" value="—" detail="Not reported by server" />
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <div className="flex items-center justify-between gap-3 mb-4">
              <div>
                <h4 className="text-sm font-semibold">Connection health</h4>
                <p className="mt-1 text-xs text-muted-foreground">Status is derived from the provider inventory; no platform usage or message counts are invented.</p>
              </div>
              <button type="button" onClick={() => setActiveTab('platforms')} className="rounded-md bg-foreground px-3 py-1.5 text-xs text-background">Manage platforms</button>
            </div>
            {items.length === 0 ? (
              <EmptyState title="No gateway integrations reported" detail="The backend returned no messaging platform definitions." />
            ) : (
              <div className="space-y-3">
                {items.map(item => <GatewayItem key={String(item.id || item.name)} item={item} pending={pending} onToggle={onToggle} />)}
              </div>
            )}
          </div>
        </div>
      )}

      {activeTab === 'platforms' && (
        <div className="rounded-lg border border-border bg-card p-6">
          <div className="mb-4">
            <h4 className="text-sm font-semibold">Configured platforms</h4>
            <p className="mt-1 text-xs text-muted-foreground">Only integrations returned by the backend are shown. Setup details come from each provider’s metadata.</p>
          </div>
          {items.length === 0 ? <EmptyState title="No platforms configured" detail="Configure a gateway provider on the server, then refresh this page." /> : <div className="space-y-3">{items.map(item => <GatewayItem key={String(item.id || item.name)} item={item} pending={pending} onToggle={onToggle} />)}</div>}
        </div>
      )}

      {activeTab === 'messages' && (
        <div className="rounded-lg border border-border bg-card p-8 text-center">
          <MessageSquare size={40} className="mx-auto mb-3 text-muted-foreground" />
          <h4 className="text-sm font-semibold">Message history is not available</h4>
          <p className="mx-auto mt-2 max-w-lg text-xs text-muted-foreground">The gateway API currently reports platform configuration only. It does not expose message history, delivery logs, export, or clear-history actions, so this page does not display sample messages.</p>
        </div>
      )}

      {activeTab === 'policy' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold">Integration policy</h4>
            <p className="mt-2 text-sm text-muted-foreground">Connection enablement is the only gateway setting currently exposed by the running server.</p>
            <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-100">Message authentication, queueing, rate limits, retention, logging, and retry policies are not available through the current gateway API. They are intentionally not rendered as editable controls.</div>
          </div>
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold">Where to change related controls</h4>
            <p className="mt-2 text-xs text-muted-foreground">Use Safety for permissions and protected paths, Providers for credentials, and Configuration for runtime defaults.</p>
          </div>
        </div>
      )}
    </div>
  )
}

function Stat({ icon, label, value, detail }: { icon: React.ReactNode; label: string; value: number | string; detail: string }) {
  return <div className="rounded-lg border border-border bg-card p-4"><div className="flex items-center gap-2"><span className="text-muted-foreground">{icon}</span><p className="text-xs font-medium text-muted-foreground">{label}</p></div><p className="mt-2 text-2xl font-bold">{value}</p><p className="mt-1 text-xs text-muted-foreground">{detail}</p></div>
}

function GatewayItem({ item, pending, onToggle }: { item: InventoryItem; pending: string; onToggle: (name: string, enabled: boolean) => void }) {
  const id = String(item.id || item.name || '')
  const isEnabled = Boolean(item.enabled)
  const required = Array.isArray(item.required_env) ? item.required_env as unknown[][] : []
  return <div className="flex items-start gap-4 rounded-lg border border-border p-4 hover:bg-secondary transition-colors"><div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${isEnabled && item.available ? 'bg-emerald-100 text-emerald-600' : 'bg-gray-100 text-gray-600'}`}><Send size={18} /></div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="text-sm font-medium">{labelFor(item)}</p><span className={`rounded-full px-2 py-0.5 text-xs ${isEnabled && item.available ? 'bg-emerald-100 text-emerald-800' : item.available ? 'bg-blue-100 text-blue-800' : 'bg-amber-100 text-amber-800'}`}>{isEnabled && item.available ? 'Active' : item.available ? 'Available' : 'Needs config'}</span></div><Description item={item} kind="gateway" />{required.length > 0 && <p className="mt-1 text-xs text-muted-foreground">Required: {required.map(group => group.join(' or ')).join(' · ')}</p>}</div><button type="button" onClick={() => onToggle(id, !isEnabled)} disabled={pending === id} className={`rounded-md px-2.5 py-1 text-xs ${isEnabled ? 'bg-foreground text-background' : 'border border-border text-muted-foreground'}`}>{pending === id ? 'Saving…' : isEnabled ? 'On' : 'Off'}</button></div>
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="py-8 text-center"><Globe size={40} className="mx-auto mb-3 text-muted-foreground" /><h4 className="text-sm font-semibold">{title}</h4><p className="mx-auto mt-2 max-w-md text-xs text-muted-foreground">{detail}</p></div>
}
