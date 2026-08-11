import { useState, type FormEvent } from 'react'
import { Calendar, Clock3, RefreshCw, Edit, Trash2, Plus, Info } from 'lucide-react'
import { api, type InventoryItem } from '../../lib/api'
import { labelFor } from './utils'

type JobTab = 'overview' | 'create' | 'history' | 'settings'

export function ScheduledJobsManager({ jobs, onChanged, onError }: { jobs: InventoryItem[]; onChanged: () => void; onError: (message: string) => void }) {
  const [activeTab, setActiveTab] = useState<JobTab>('overview')
  const [name, setName] = useState('')
  const [prompt, setPrompt] = useState('')
  const [interval, setInterval] = useState('60')
  const [saving, setSaving] = useState(false)
  const [editingJob, setEditingJob] = useState<string | null>(null)

  const resetForm = () => { setName(''); setPrompt(''); setInterval('60'); setEditingJob(null) }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    onError('')
    try {
      if (editingJob) {
        await api.updateCronJob(editingJob, { interval_minutes: Number(interval) })
      } else {
        await api.createCronJob({ name, prompt, interval_minutes: Number(interval) })
      }
      resetForm()
      onChanged()
      setActiveTab('overview')
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Could not save the scheduled job.')
    } finally { setSaving(false) }
  }

  const update = async (operation: () => Promise<unknown>) => {
    try { await operation(); onChanged() } catch (err) { onError(err instanceof Error ? err.message : 'Could not update the scheduled job.') }
  }

  const edit = (job: InventoryItem) => {
    setEditingJob(String(job.id || ''))
    setName(String(job.name || ''))
    setPrompt(String(job.prompt || ''))
    setInterval(String(job.interval_minutes || 60))
    setActiveTab('create')
  }

  const deleteJob = async (id: string) => {
    if (!window.confirm('Delete this scheduled job?')) return
    await update(() => api.deleteCronJob(id))
  }

  const runJob = async (id: string) => { await update(() => api.runCronJob(id)) }
  const activeJobs = jobs.filter(job => job.enabled).length

  const tabs: { id: JobTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'create', label: 'Create job' },
    { id: 'history', label: 'Run history' },
    { id: 'settings', label: 'Scheduler limits' },
  ]

  return <div className="space-y-6">
    <div>
      <h3 className="text-lg font-semibold">Scheduled Jobs</h3>
      <p className="mt-1 text-sm text-muted-foreground">Create and operate recurring jobs that run while the Nexus server is online.</p>
    </div>

    <div className="flex flex-wrap gap-2 border-b border-border">
      {tabs.map(tab => <button key={tab.id} type="button" onClick={() => setActiveTab(tab.id)} className={`px-4 py-2 text-sm font-medium transition ${activeTab === tab.id ? 'border-b-2 border-foreground text-foreground' : 'text-muted-foreground hover:text-foreground'}`}>{tab.label}</button>)}
    </div>

    {activeTab === 'overview' && <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Stat label="Configured jobs" value={jobs.length} detail={`${activeJobs} enabled`} />
        <Stat label="Run history" value="—" detail="Not reported by server" />
        <Stat label="Runtime metrics" value="—" detail="Not reported by server" />
      </div>
      <div className="rounded-lg border border-border bg-card p-6">
        <div className="mb-4 flex items-center justify-between gap-3"><div><h4 className="text-sm font-semibold">Configured jobs</h4><p className="mt-1 text-xs text-muted-foreground">These rows are returned by the scheduler API.</p></div><button type="button" onClick={() => { resetForm(); setActiveTab('create') }} className="flex items-center gap-2 rounded-md bg-foreground px-3 py-1.5 text-xs text-background"><Plus size={14} /> Add job</button></div>
        {!jobs.length ? <EmptyState /> : <div className="space-y-3">{jobs.map(job => {
          const id = String(job.id || job.name || '')
          const enabled = Boolean(job.enabled)
          return <div key={id} className="flex items-start gap-4 rounded-lg border border-border p-4"><div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${enabled ? 'bg-emerald-100 text-emerald-600' : 'bg-gray-100 text-gray-600'}`}><Clock3 size={18} /></div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="text-sm font-medium">{labelFor(job)}</p><span className={`rounded-full px-2 py-0.5 text-xs ${enabled ? 'bg-emerald-100 text-emerald-800' : 'bg-gray-100 text-gray-800'}`}>{enabled ? 'Enabled' : 'Paused'}</span></div><p className="mt-1 text-xs text-muted-foreground">Every {String(job.interval_minutes || 60)} minutes · Run history is not reported</p>{job.description && <p className="mt-1 text-xs text-muted-foreground">{String(job.description)}</p>}</div><div className="flex gap-2"><button type="button" onClick={() => runJob(id)} className="rounded-md border border-border px-2 py-1 text-xs" title="Run now" aria-label={`Run ${labelFor(job)} now`}><RefreshCw size={14} /></button><button type="button" onClick={() => edit(job)} className="rounded-md border border-border px-2 py-1 text-xs" title="Edit" aria-label={`Edit ${labelFor(job)}`}><Edit size={14} /></button><button type="button" onClick={() => update(() => api.updateCronJob(id, { enabled: !enabled }))} className="rounded-md border border-border px-2 py-1 text-xs">{enabled ? 'Pause' : 'Enable'}</button><button type="button" onClick={() => deleteJob(id)} className="rounded-md border border-red-500 px-2 py-1 text-xs text-red-600" title="Delete" aria-label={`Delete ${labelFor(job)}`}><Trash2 size={14} /></button></div></div>
        })}</div>}
      </div>
    </div>}

    {activeTab === 'create' && <div className="space-y-6">
      <div className="rounded-lg border border-border bg-card p-6"><h4 className="text-sm font-semibold">{editingJob ? 'Edit scheduled job' : 'Create scheduled job'}</h4><p className="mt-1 text-xs text-muted-foreground">Only fields supported by the scheduler API are editable here.</p><form onSubmit={submit} className="mt-5 space-y-4"><div><label className="text-xs font-medium">Job name</label><input required value={name} onChange={event => setName(event.target.value)} disabled={Boolean(editingJob)} className="mt-1 h-10 w-full rounded-md border border-border bg-background px-3 text-sm disabled:opacity-60" /></div><div><label className="text-xs font-medium">Task prompt</label><textarea required value={prompt} onChange={event => setPrompt(event.target.value)} disabled={Boolean(editingJob)} rows={5} className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm disabled:opacity-60" /></div><div><label className="text-xs font-medium">Interval (minutes)</label><input required type="number" min="1" max="43200" value={interval} onChange={event => setInterval(event.target.value)} className="mt-1 h-10 w-full rounded-md border border-border bg-background px-3 text-sm" /></div><div className="flex items-center justify-between border-t border-border pt-4"><button type="button" onClick={resetForm} className="text-xs text-muted-foreground underline">{editingJob ? 'Cancel edit' : 'Clear form'}</button><button type="submit" disabled={saving} className="rounded-md bg-foreground px-4 py-2 text-sm text-background disabled:opacity-50">{saving ? 'Saving…' : editingJob ? 'Update interval' : 'Create job'}</button></div></form></div>
      <div className="rounded-lg border border-blue-500 bg-blue-50 p-5 dark:bg-blue-950/20"><div className="flex items-start gap-3"><Info size={18} className="shrink-0 text-blue-600" /><p className="text-xs text-blue-900 dark:text-blue-100">Jobs execute only while the Nexus server is online. The backend currently persists the name, prompt, interval, and enabled state.</p></div></div>
    </div>}

    {activeTab === 'history' && <div className="rounded-lg border border-border bg-card p-8 text-center"><Calendar size={40} className="mx-auto mb-3 text-muted-foreground" /><h4 className="text-sm font-semibold">Run history is not available</h4><p className="mx-auto mt-2 max-w-lg text-xs text-muted-foreground">The current scheduler API exposes job CRUD and run-now actions, but does not expose execution history, durations, logs, export, or clear-history actions. No sample runs are shown.</p></div>}

    {activeTab === 'settings' && <div className="space-y-4"><div className="rounded-lg border border-border bg-card p-6"><h4 className="text-sm font-semibold">Scheduler limits</h4><p className="mt-2 text-sm text-muted-foreground">Boot behavior, notifications, retry policy, concurrency limits, timeouts, retention, and logging are not exposed by the current scheduler API.</p><div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-100">These values are intentionally not rendered as editable controls because the server cannot persist them.</div></div><div className="rounded-lg border border-border bg-card p-6"><h4 className="text-sm font-semibold">Available controls</h4><p className="mt-2 text-xs text-muted-foreground">Use Overview to enable, pause, run, edit, or delete jobs. Use Create job to configure a persisted interval and prompt.</p></div></div>}
  </div>
}

function Stat({ label, value, detail }: { label: string; value: string | number; detail: string }) { return <div className="rounded-lg border border-border bg-card p-4"><p className="text-xs font-medium text-muted-foreground">{label}</p><p className="mt-2 text-2xl font-bold">{value}</p><p className="mt-1 text-xs text-muted-foreground">{detail}</p></div> }
function EmptyState() { return <div className="py-8 text-center"><Calendar size={40} className="mx-auto mb-3 text-muted-foreground" /><h4 className="text-sm font-semibold">No scheduled jobs</h4><p className="mt-2 text-xs text-muted-foreground">Create the first job to automate a recurring Nexus task.</p></div> }
