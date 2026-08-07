import { CircleAlert, CircleCheck, ReceiptText } from 'lucide-react'

type Billing = {
  tier?: string
  message?: string
  status?: string
  usage?: Record<string, unknown>
  limits?: Record<string, unknown>
}

function ValueList({ title, values }: { title: string; values: Record<string, unknown> }) {
  const entries = Object.entries(values)
  if (!entries.length) return null
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h4 className="text-sm font-semibold">{title}</h4>
      <dl className="mt-3 divide-y divide-border">
        {entries.map(([key, value]) => (
          <div key={key} className="flex items-center justify-between gap-4 py-2 text-sm">
            <dt className="text-muted-foreground">{key.replace(/[_-]/g, ' ')}</dt>
            <dd className="font-medium text-right">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

export function BillingSettings({ billing }: { billing?: Billing }) {
  const usage = billing?.usage ?? {}
  const limits = billing?.limits ?? {}
  const hasUsage = Object.keys(usage).length > 0
  const hasLimits = Object.keys(limits).length > 0
  const healthy = billing?.status === 'ok' || billing?.status === 'success'

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">Billing & usage</h3>
        <p className="mt-1 text-sm text-muted-foreground">A truthful view of what the connected Nexus runtime reports. No estimated costs are shown.</p>
      </div>

      <div className={`rounded-lg border p-4 ${healthy ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-border bg-card'}`}>
        <div className="flex items-start gap-3">
          {healthy ? <CircleCheck size={20} className="mt-0.5 text-emerald-600" /> : <CircleAlert size={20} className="mt-0.5 text-muted-foreground" />}
          <div>
            <p className="text-sm font-semibold">{billing?.tier || 'Local-first runtime'}</p>
            <p className="mt-1 text-sm text-muted-foreground">{billing?.message || 'The backend did not report a billing provider or usage records.'}</p>
          </div>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-lg border border-border bg-card p-4"><ReceiptText size={18} className="text-muted-foreground" /><p className="mt-2 text-xs text-muted-foreground">Plan</p><p className="mt-1 font-semibold">{billing?.tier || 'Local'}</p></div>
        <div className="rounded-lg border border-border bg-card p-4"><p className="text-xs text-muted-foreground">Backend status</p><p className="mt-1 font-semibold">{billing?.status || 'Unknown'}</p></div>
        <div className="rounded-lg border border-border bg-card p-4"><p className="text-xs text-muted-foreground">Reported usage fields</p><p className="mt-1 font-semibold">{Object.keys(usage).length}</p></div>
      </div>

      {!hasUsage && !hasLimits && (
        <div className="rounded-lg border border-dashed border-border p-6 text-center">
          <p className="text-sm font-medium">No billable usage is available</p>
          <p className="mt-2 text-sm text-muted-foreground">Nexus is running locally, and this server currently exposes no cost, token, budget, or provider billing records.</p>
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-2"><ValueList title="Reported usage" values={usage} /><ValueList title="Reported limits" values={limits} /></div>
    </div>
  )
}
