import { useState, type FormEvent } from 'react'
import { Calendar, Clock3, CheckCircle2, CircleAlert, RefreshCw, Edit, Trash2, Plus, Info } from 'lucide-react'
import { api, type InventoryItem } from '../../lib/api'
import { labelFor } from './utils'

export function ScheduledJobsManager({ jobs, onChanged, onError }: { jobs: InventoryItem[]; onChanged: () => void; onError: (message: string) => void }) {
  const [activeTab, setActiveTab] = useState<'overview' | 'create' | 'history' | 'settings'>('overview')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [prompt, setPrompt] = useState('')
  const [interval, setInterval] = useState('60')
  const [scheduleType, setScheduleType] = useState<'minutes' | 'hourly' | 'daily' | 'weekly'>('minutes')
  const [persona, setPersona] = useState('WORKER')
  const [saving, setSaving] = useState(false)
  const [editingJob, setEditingJob] = useState<string | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); onError('')
    try {
      if (editingJob) {
        await api.updateCronJob(editingJob, { enabled: true, interval_minutes: Number(interval) })
        setEditingJob(null)
      } else {
        await api.createCronJob({ name, prompt, interval_minutes: Number(interval) })
      }
      setName(''); setDescription(''); setPrompt(''); setInterval('60'); setScheduleType('minutes'); setPersona('WORKER')
      onChanged()
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Could not create the scheduled job.')
    } finally {
      setSaving(false)
    }
  }

  const runAction = async (operation: () => Promise<unknown>) => {
    try {
      await operation()
      onChanged()
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Could not update the scheduled job.')
    }
  }

  const deleteJob = async (id: string) => {
    if (!window.confirm('Delete this scheduled job?')) return
    try {
      await api.deleteCronJob(id)
      onChanged()
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Could not delete the scheduled job.')
    }
  }

  const runJob = async (id: string) => {
    try {
      await api.runCronJob(id)
      onChanged()
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Could not run the scheduled job.')
    }
  }

  const stats = {
    totalJobs: jobs.length,
    activeJobs: jobs.filter(j => j.enabled).length,
    completedRuns: null as number | null,
    failedRuns: null as number | null,
    avgRuntime: null as string | null,
  }

  const scheduleOptions = [
    { value: 'minutes', label: 'Every X minutes', min: 1, max: 43200, default: 60 },
    { value: 'hourly', label: 'Every X hours', min: 1, max: 24, default: 1 },
    { value: 'daily', label: 'Daily at (hour)', min: 0, max: 23, default: 9 },
    { value: 'weekly', label: 'Weekly on (day)', min: 0, max: 6, default: 1 },
  ]

  const personas = ['WORKER', 'RESEARCHER', 'CRITIC', 'VERIFIER', 'COORDINATOR']

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">Scheduled Jobs</h3>
        <p className="mt-1 text-sm text-muted-foreground">Automate recurring tasks with cron-like scheduling for Nexus AI workflows.</p>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-border">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'create', label: 'Create Job' },
          { id: 'history', label: 'Job History' },
          { id: 'settings', label: 'Settings' },
        ].map(tab => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id as any)}
            className={`px-4 py-2 text-sm font-medium transition ${activeTab === tab.id ? 'border-b-2 border-foreground text-foreground' : 'text-muted-foreground hover:text-foreground'}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Overview Tab */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          {/* Statistics Cards */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Clock3 size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Total Jobs</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.totalJobs}</p>
              <p className="mt-1 text-xs text-muted-foreground">{stats.activeJobs} active</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <CheckCircle2 size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Completed Runs</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.completedRuns ?? '—'}</p>
              <p className="mt-1 text-xs text-muted-foreground">This month</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <CircleAlert size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Failed Runs</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.failedRuns ?? '—'}</p>
              <p className="mt-1 text-xs text-muted-foreground">This month</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <RefreshCw size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Avg Runtime</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.avgRuntime ?? '—'}</p>
              <p className="mt-1 text-xs text-muted-foreground">Per job</p>
            </div>
          </div>

          {/* Active Jobs */}
          <div className="rounded-lg border border-border bg-card p-6">
            <div className="flex items-center justify-between mb-4">
              <h4 className="text-sm font-semibold">Active Scheduled Jobs</h4>
              <button
                onClick={() => setActiveTab('create')}
                className="flex items-center gap-2 rounded-md bg-foreground px-3 py-1.5 text-xs text-background"
              >
                <Plus size={14} />
                Add Job
              </button>
            </div>
            {!jobs.length ? (
              <div className="py-8 text-center">
                <Calendar size={48} className="mx-auto text-muted-foreground mb-4" />
                <h4 className="text-sm font-semibold mb-2">No Scheduled Jobs</h4>
                <p className="text-xs text-muted-foreground mb-4">Create your first scheduled job to automate recurring tasks.</p>
                <button
                  onClick={() => setActiveTab('create')}
                  className="rounded-md border border-border px-4 py-2 text-sm"
                >
                  Create Job
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                {jobs.map(job => {
                  const id = String(job.id || '')
                  const enabled = Boolean(job.enabled)
                  return (
                    <div key={id} className="flex items-start gap-4 rounded-lg border border-border p-4 hover:bg-secondary transition-colors">
                      <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${enabled ? 'bg-emerald-100 text-emerald-600' : 'bg-gray-100 text-gray-600'}`}>
                        <Clock3 size={18} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium">{labelFor(job)}</p>
                          <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${enabled ? 'bg-emerald-100 text-emerald-800' : 'bg-gray-100 text-gray-800'}`}>
                            {enabled ? 'Active' : 'Paused'}
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Every {String(job.interval_minutes || 60)} minutes · Last run: Recently
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={() => runJob(id)}
                          className="rounded-md border border-border px-2 py-1 text-xs hover:bg-secondary"
                          title="Run now"
                        >
                          <RefreshCw size={14} />
                        </button>
                        <button
                          onClick={() => { setEditingJob(id); setActiveTab('create') }}
                          className="rounded-md border border-border px-2 py-1 text-xs hover:bg-secondary"
                          title="Edit"
                        >
                          <Edit size={14} />
                        </button>
                        <button
                          onClick={() => runAction(() => api.updateCronJob(id, { enabled: !enabled }))}
                          className={`rounded-md px-2 py-1 text-xs ${enabled ? 'border border-amber-500 text-amber-600 hover:bg-amber-50' : 'border border-emerald-500 text-emerald-600 hover:bg-emerald-50'}`}
                          title={enabled ? 'Pause' : 'Enable'}
                        >
                          {enabled ? 'Pause' : 'Enable'}
                        </button>
                        <button
                          onClick={() => deleteJob(id)}
                          className="rounded-md border border-red-500 px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                          title="Delete"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Quick Actions */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Quick Actions</h4>
            <div className="flex gap-3">
              <button
                onClick={() => setActiveTab('create')}
                className="rounded-md bg-foreground px-4 py-2 text-sm text-background"
              >
                Create New Job
              </button>
              <button
                onClick={() => setActiveTab('history')}
                className="rounded-md border border-border px-4 py-2 text-sm"
              >
                View Run History
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Job Tab */}
      {activeTab === 'create' && (
        <div className="space-y-6">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-2">{editingJob ? 'Edit Scheduled Job' : 'Create New Scheduled Job'}</h4>
            <p className="text-xs text-muted-foreground mb-4">
              Configure automated tasks that run on a schedule. Jobs execute while Nexus server is online.
            </p>

            <form onSubmit={submit} className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="text-xs font-medium block mb-1">Job Name</label>
                  <input
                    required
                    value={name}
                    onChange={event => setName(event.target.value)}
                    placeholder="e.g. Daily project health check"
                    className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium block mb-1">Description (optional)</label>
                  <input
                    value={description}
                    onChange={event => setDescription(event.target.value)}
                    placeholder="Brief description of this job"
                    className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                  />
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="text-xs font-medium block mb-1">Schedule Type</label>
                  <select
                    value={scheduleType}
                    onChange={event => setScheduleType(event.target.value as any)}
                    className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                  >
                    {scheduleOptions.map(option => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium block mb-1">
                    {scheduleType === 'minutes' ? 'Interval (minutes)' :
                     scheduleType === 'hourly' ? 'Every X hours' :
                     scheduleType === 'daily' ? 'Hour (0-23)' :
                     'Day (0-6, 0=Monday)'}
                  </label>
                  <input
                    required
                    type="number"
                    value={interval}
                    onChange={event => setInterval(event.target.value)}
                    min={scheduleOptions.find(o => o.value === scheduleType)?.min || 1}
                    max={scheduleOptions.find(o => o.value === scheduleType)?.max || 43200}
                    className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs font-medium block mb-1">Task Prompt</label>
                <textarea
                  required
                  value={prompt}
                  onChange={event => setPrompt(event.target.value)}
                  rows={4}
                  placeholder="Describe what Nexus should do when this job runs..."
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="text-xs font-medium block mb-1">Agent Persona (optional)</label>
                  <select
                    value={persona}
                    onChange={event => setPersona(event.target.value)}
                    className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                  >
                    {personas.map(p => <option key={p} value={p}>{p}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium block mb-1">Priority</label>
                  <select className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm">
                    <option value="normal">Normal</option>
                    <option value="high">High</option>
                    <option value="low">Low</option>
                  </select>
                </div>
              </div>

              <div className="flex items-center justify-between pt-4 border-t border-border">
                <button
                  type="button"
                  onClick={() => {
                    setEditingJob(null)
                    setName('')
                    setDescription('')
                    setPrompt('')
                    setInterval('60')
                    setScheduleType('minutes')
                    setPersona('WORKER')
                  }}
                  className="text-xs text-muted-foreground hover:text-foreground underline"
                >
                  {editingJob ? 'Cancel Edit' : 'Clear Form'}
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="rounded-md bg-foreground px-4 py-2 text-sm text-background disabled:opacity-50"
                >
                  {saving ? 'Saving…' : editingJob ? 'Update Job' : 'Create Job'}
                </button>
              </div>
            </form>
          </div>

          {/* Tips */}
          <div className="rounded-lg border border-blue-500 bg-blue-50 dark:bg-blue-950/20 p-6">
            <div className="flex items-start gap-3">
              <Info size={20} className="text-blue-600 shrink-0" />
              <div>
                <h4 className="text-sm font-semibold text-blue-900 dark:text-blue-100">Scheduling Tips</h4>
                <ul className="mt-2 space-y-1 text-xs text-blue-800 dark:text-blue-200">
                  <li>• Use minute intervals for frequent checks (e.g., every 5 minutes)</li>
                  <li>• Set daily schedules for maintenance tasks (e.g., daily at 2 AM)</li>
                  <li>• Consider resource usage when setting short intervals</li>
                  <li>• Jobs only run when the Nexus server is online</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* History Tab */}
      {activeTab === 'history' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <div className="flex items-center justify-between mb-4">
              <h4 className="text-sm font-semibold">Job Run History</h4>
              <div className="flex gap-2">
                <button className="px-3 py-1.5 text-xs rounded-md border border-border text-muted-foreground" disabled>
                  Export CSV
                </button>
                <button className="px-3 py-1.5 text-xs rounded-md border border-border text-muted-foreground">
                  Clear History
                </button>
              </div>
            </div>

            {/* Mock history data */}
            <div className="space-y-3">
              {[
                { job: 'Daily project health check', status: 'completed', duration: '2.1s', time: '2026-08-01 09:00' },
                { job: 'Weekly backup', status: 'completed', duration: '5.3s', time: '2026-08-01 08:00' },
                { job: 'Code quality check', status: 'failed', duration: '1.2s', time: '2026-07-31 18:00' },
                { job: 'Daily project health check', status: 'completed', duration: '2.0s', time: '2026-07-31 09:00' },
                { job: 'Dependency update check', status: 'completed', duration: '3.4s', time: '2026-07-30 12:00' },
              ].map((run, index) => (
                <div key={index} className="flex items-center gap-4 rounded-lg border border-border p-4">
                  <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
                    run.status === 'completed' ? 'bg-emerald-100 text-emerald-600' :
                    run.status === 'failed' ? 'bg-red-100 text-red-600' :
                    'bg-blue-100 text-blue-600'
                  }`}>
                    {run.status === 'completed' && <CheckCircle2 size={16} />}
                    {run.status === 'failed' && <CircleAlert size={16} />}
                    {run.status === 'running' && <RefreshCw size={16} className="animate-spin" />}
                  </div>
                  <div className="flex-1">
                    <p className="text-sm font-medium">{run.job}</p>
                    <p className="text-xs text-muted-foreground">{run.time} · Duration: {run.duration}</p>
                  </div>
                  <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                    run.status === 'completed' ? 'bg-emerald-100 text-emerald-800' :
                    run.status === 'failed' ? 'bg-red-100 text-red-800' :
                    'bg-blue-100 text-blue-800'
                  }`}>
                    {run.status}
                  </span>
                </div>
              ))}
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-border">
              <p className="text-xs text-muted-foreground">Showing 5 of 127 runs</p>
              <div className="flex gap-2">
                <button className="px-3 py-1 text-xs rounded-md border border-border text-muted-foreground" disabled>
                  Previous
                </button>
                <button className="px-3 py-1 text-xs rounded-md border border-border text-muted-foreground">
                  Next
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Settings Tab */}
      {activeTab === 'settings' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Job Runtime Configuration</h4>
            <div className="space-y-4">
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Auto-start jobs on server boot</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Send notifications on job completion</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked={false} className="rounded border-border" />
                <span className="text-sm">Retry failed jobs automatically</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Log job output to file</span>
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Resource Limits</h4>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium block mb-1">Max concurrent jobs</label>
                <input
                  type="number"
                  defaultValue={5}
                  min="1"
                  max="20"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">Max job duration (minutes)</label>
                <input
                  type="number"
                  defaultValue={30}
                  min="5"
                  max="120"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">Job timeout (seconds)</label>
                <input
                  type="number"
                  defaultValue={300}
                  min="60"
                  max="3600"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">History & Logging</h4>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium block mb-1">Retain job history (days)</label>
                <input
                  type="number"
                  defaultValue={30}
                  min="7"
                  max="365"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">Log level</label>
                <select className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm">
                  <option value="error">Error only</option>
                  <option value="warn">Warning and above</option>
                  <option value="info">Info and above</option>
                  <option value="debug">Debug (verbose)</option>
                </select>
              </div>
            </div>
          </div>

          <div className="flex justify-end">
            <button className="rounded-md bg-foreground px-4 py-2 text-sm text-background">
              Save Settings
            </button>
          </div>
        </div>
      )}

    </div>
  )
}
