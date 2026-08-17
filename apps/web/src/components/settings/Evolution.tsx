import { useState } from 'react'
import { CheckCircle2, CircleAlert } from 'lucide-react'
import { type InventoryItem } from '../../lib/api'
import { labelFor, Description } from './utils'

function InfoBlock({ title, value, detail }: { title: string; value: string; detail: string }) {
  return <div className="mb-4 rounded-lg border border-border bg-card p-4"><p className="text-sm font-medium">{title}</p><p className="mt-2 text-lg font-semibold">{value}</p><p className="mt-1 text-sm text-muted-foreground">{detail}</p></div>
}

function EvolutionGroup({ title, detail, items }: { title: string; detail: string; items: InventoryItem[] }) {
  return <section><div className="mb-2"><h3 className="text-sm font-semibold">{title}</h3><p className="mt-0.5 text-xs text-muted-foreground">{detail}</p></div>{items.length ? <div className="divide-y divide-border rounded-lg border border-border bg-card">{items.map(item => <div key={String(item.id)} className="flex items-start gap-3 px-4 py-3">{item.available === false ? <CircleAlert size={16} className="mt-0.5 shrink-0 text-amber-600" /> : <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-emerald-600" />}<div className="min-w-0 flex-1"><p className="text-sm font-medium text-foreground">{labelFor(item)}</p><Description item={item} /><p className="mt-1 text-xs text-muted-foreground">{item.available === false ? 'Unavailable in this runtime' : 'Available in this runtime'}</p></div></div>)}</div> : <p className="py-4 text-sm text-muted-foreground">No evolution components were reported by Nexus.</p>}</section>
}

export function EvolutionPanel({ evolution, onToggle, pending }: { evolution?: { enabled?: boolean; version?: string; lifecycle?: InventoryItem[]; forges?: InventoryItem[] }; onToggle: (kind: string, name: string, enabled: boolean) => void; pending: string }) {
  const [activeTab, setActiveTab] = useState<'overview' | 'lifecycle' | 'forges'>('overview')
  const enabled = evolution?.enabled === true
  const lifecycle = evolution?.lifecycle || []
  const forges = evolution?.forges || []
  
  return <div className="space-y-4">
    <div><h3 className="text-sm font-semibold">Evolution</h3><p className="mt-1 text-sm text-muted-foreground">Phonix evolution system for self-improvement and specialized artifact generation.</p></div>
    
    <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3">
      <span className={`size-2 rounded-full ${enabled ? 'bg-emerald-500' : 'bg-amber-500'}`} />
      <div className="flex-1">
        <p className="text-sm font-medium">Phonix evolution {evolution?.version || ''}</p>
        <p className="text-xs text-muted-foreground">Lifecycle and forge availability are checked from your running Nexus server.</p>
      </div>
      <button onClick={() => onToggle('feature', 'evolution', !enabled)} disabled={pending === 'feature:evolution'} className={`rounded-md px-2.5 py-1 text-xs font-medium ${enabled ? 'bg-foreground text-background' : 'border border-border text-muted-foreground'}`}>{pending === 'feature:evolution' ? 'Saving…' : enabled ? 'On' : 'Off'}</button>
    </div>
    
    <div className="flex gap-2 border-b border-border">
      {[
        { id: 'overview', label: 'Overview' },
        { id: 'lifecycle', label: 'Lifecycle' },
        { id: 'forges', label: 'Forges' },
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
          <InfoBlock title="Status" value={enabled ? 'Enabled' : 'Disabled'} detail={evolution?.version || 'Unknown version'} />
          <InfoBlock title="Lifecycle components" value={String(lifecycle.length)} detail="Evolution pipeline stages" />
          <InfoBlock title="Forge modules" value={String(forges.length)} detail="Specialized artifact generators" />
        </div>
        
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm font-medium">About Evolution</p>
          <p className="mt-1 text-xs text-muted-foreground">The Phonix evolution system enables Nexus to improve itself over time through automated testing, versioning, and specialized forge modules for creating custom artifacts.</p>
        </div>
      </div>
    )}

    {activeTab === 'lifecycle' && (
      <div className="space-y-4">
        <EvolutionGroup title="Lifecycle" detail="The ordered Phonix evolution pipeline." items={lifecycle} />
      </div>
    )}

    {activeTab === 'forges' && (
      <div className="space-y-4">
        <EvolutionGroup title="Forges" detail="Installed modules that create specialized evolution artifacts." items={forges} />
      </div>
    )}
  </div>
}
