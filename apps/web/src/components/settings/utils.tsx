import { CheckCircle2, CircleAlert } from 'lucide-react'
import { type InventoryItem } from '../../lib/api'

export function labelFor(item: InventoryItem) {
  return String(item.name || item.id || 'Unnamed item')
}

export function Description({ item, kind }: { item: InventoryItem; kind?: string }) {
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

export function InventoryList({ items, empty, kind, onToggle, pending }: { items: InventoryItem[]; empty: string; kind?: string; onToggle?: (name: string, enabled: boolean) => void; pending?: string }) {
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
        {kind && onToggle && typeof enabled === 'boolean' ? <button aria-label={`${labelFor(item)}: ${enabled ? 'enabled' : 'disabled'}. Toggle`} aria-pressed={enabled} onClick={() => onToggle(String(item.id || item.name || ''), !enabled)} disabled={pending === String(item.id || item.name || '')} className={`shrink-0 rounded-md px-2.5 py-1 text-xs font-medium transition disabled:opacity-50 ${enabled ? 'bg-foreground text-background hover:opacity-80' : 'border border-border text-muted-foreground hover:bg-secondary'}`}>{pending === String(item.id || item.name || '') ? 'Saving…' : enabled ? 'Enabled' : 'Disabled'}</button> : typeof item.status === 'string' && <span className="text-xs capitalize text-muted-foreground">{item.status}</span>}
      </div>
    })}
  </div>
}
