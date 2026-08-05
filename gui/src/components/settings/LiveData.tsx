export function LiveData({ data, empty }: { data: Record<string, unknown>; empty: string }) {
  const entries = Object.entries(data)
  if (!entries.length) return <p className="py-8 text-sm text-muted-foreground">{empty}</p>
  return <div className="divide-y divide-border rounded-lg border border-border bg-card">{entries.map(([key, value]) => <div key={key} className="grid grid-cols-[minmax(120px,0.3fr)_1fr] gap-5 px-4 py-3"><p className="text-sm font-medium capitalize text-foreground">{key.replace(/_/g, ' ')}</p><p className="min-w-0 break-words text-sm text-muted-foreground">{typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' ? String(value) : JSON.stringify(value)}</p></div>)}</div>
}
