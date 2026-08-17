import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  api,
  type AdditionalDirInfo,
  type HealthCheck,
  type WorkspaceAccessMode,
  type WorkspaceInstructions,
  type WorkspaceSummary,
} from '../lib/api'

const ACCESS_MODES: Array<{ id: WorkspaceAccessMode; label: string }> = [
  { id: 'read_write', label: 'Read & write' },
  { id: 'read_only', label: 'Read only' },
  { id: 'index_only', label: 'Index only' },
  { id: 'disabled', label: 'Disabled' },
]

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = value
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size < 10 && unit > 0 ? size.toFixed(1) : Math.round(size)} ${units[unit]}`
}

function InfoBlock({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-2 break-all text-lg font-semibold">{value}</p>
      <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
    </div>
  )
}

function HealthRow({ check }: { check: HealthCheck }) {
  const tone =
    check.status === 'healthy'
      ? 'text-emerald-700'
      : check.status === 'warning'
        ? 'text-amber-700'
        : 'text-destructive'
  return (
    <div className="flex items-start justify-between gap-4 px-4 py-3">
      <div className="min-w-0">
        <p className="text-sm font-medium">{check.name}</p>
        {check.detail && <p className="mt-0.5 text-xs text-muted-foreground">{check.detail}</p>}
      </div>
      <span className={`shrink-0 text-xs font-medium capitalize ${tone}`}>{check.status}</span>
    </div>
  )
}

export default function WorkspaceSettingsPanel({
  state: _state,
  onSaved,
}: {
  state: Record<string, unknown>
  onSaved: () => void
}) {
  const [summary, setSummary] = useState<WorkspaceSummary | null>(null)
  const [instructions, setInstructions] = useState('')
  const [rootInput, setRootInput] = useState('')
  const [dirInput, setDirInput] = useState('')
  const [dirMode, setDirMode] = useState<WorkspaceAccessMode>('read_write')
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState<'overview' | 'directories' | 'index' | 'instructions' | 'health'>('overview')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [workspace, instructionData] = await Promise.all([
        api.workspace(),
        api.workspaceInstructions().catch(() => ({ instructions: '' } as WorkspaceInstructions)),
      ])
      setSummary(workspace)
      setRootInput(workspace.root || '')
      setInstructions(typeof instructionData.instructions === 'string' ? instructionData.instructions : '')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load workspace settings.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const run = async (label: string, action: () => Promise<void>) => {
    setWorking(label)
    setMessage('')
    setError('')
    try {
      await action()
      await load()
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : `Could not ${label}.`)
    } finally {
      setWorking('')
    }
  }

  const setRoot = async (event: FormEvent) => {
    event.preventDefault()
    const path = rootInput.trim()
    if (!path) return
    await run('update workspace root', async () => {
      const validation = await api.validateWorkspacePath(path)
      if (!validation.validation?.valid) {
        throw new Error(validation.validation?.reason || 'That path is not a valid workspace root.')
      }
      await api.setWorkspaceRoot(path)
      setMessage('Workspace root updated.')
    })
  }

  const addDirectory = async (event: FormEvent) => {
    event.preventDefault()
    const path = dirInput.trim()
    if (!path) return
    await run('add directory', async () => {
      await api.addWorkspaceDir(path, dirMode)
      setDirInput('')
      setMessage('Additional directory added.')
    })
  }

  const updateDir = async (dir: AdditionalDirInfo, accessMode: WorkspaceAccessMode) => {
    await run('update directory access', async () => {
      await api.updateWorkspaceDirAccess(dir.path, accessMode)
      setMessage('Directory access updated.')
    })
  }

  const removeDir = async (dir: AdditionalDirInfo) => {
    if (!window.confirm(`Remove additional directory?\n${dir.path}`)) return
    await run('remove directory', async () => {
      await api.removeWorkspaceDir(dir.path)
      setMessage('Additional directory removed.')
    })
  }

  const saveInstructions = async (event: FormEvent) => {
    event.preventDefault()
    await run('save instructions', async () => {
      await api.saveWorkspaceInstructions(instructions)
      setMessage('Workspace instructions saved.')
    })
  }

  if (loading && !summary) {
    return <p className="py-8 text-sm text-muted-foreground" role="status">Loading workspace…</p>
  }

  if (error && !summary) {
    return <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive" role="alert">{error}</p>
  }

  const dirs = summary?.additional_dirs || []
  const health = summary?.health || []

  return (
    <div className="space-y-4">
      <div><h3 className="text-sm font-semibold">Workspace</h3><p className="mt-1 text-sm text-muted-foreground">Configure workspace root, directories, indexing, and project instructions.</p></div>
      
      {error && <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive" role="alert">{error}</div>}
      
      <div className="flex gap-2 border-b border-border">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'directories', label: 'Directories' },
          { id: 'index', label: 'Index' },
          { id: 'instructions', label: 'Instructions' },
          { id: 'health', label: 'Health' },
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
            <InfoBlock title="Root" value={summary?.root || 'Unavailable'} detail={`${summary?.state || 'unknown'} · ${summary?.exists ? 'exists on disk' : 'missing'}`} />
            <InfoBlock
              title="Project"
              value={summary?.project_name || summary?.workspace_name || 'Unnamed'}
              detail={`${summary?.project_type || 'unknown'} · ${summary?.git_branch ? `git ${summary.git_branch}` : 'not a git repo'}`}
            />
            <InfoBlock title="Files" value={String(summary?.file_count ?? 0)} detail={`${summary?.folder_count ?? 0} folders · ${summary?.indexed_file_count ?? 0} indexed`} />
            <InfoBlock title="Index text" value={formatBytes(summary?.indexed_text_size || 0)} detail={`${summary?.additional_directory_count ?? 0} additional director${(summary?.additional_directory_count || 0) === 1 ? 'y' : 'ies'}`} />
          </div>

          <form className="space-y-3 rounded-lg border border-border bg-card p-4" onSubmit={setRoot}>
            <div>
              <h3 className="text-sm font-medium">Workspace root</h3>
              <p className="mt-1 text-xs text-muted-foreground">Change the primary project directory Nexus uses for tools and indexing.</p>
            </div>
            <label className="grid gap-1.5 text-sm font-medium">
              Path
              <input
                value={rootInput}
                onChange={event => setRootInput(event.target.value)}
                className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring"
                placeholder="C:\path\to\project"
              />
            </label>
            <div className="flex justify-end">
              <button
                disabled={!!working || !rootInput.trim() || rootInput.trim() === summary?.root}
                className="rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background disabled:opacity-50"
              >
                {working === 'update workspace root' ? 'Updating…' : 'Set workspace root'}
              </button>
            </div>
          </form>
        </div>
      )}

      {activeTab === 'directories' && (
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-medium">Additional directories</h3>
            <p className="mt-1 text-xs text-muted-foreground">Optional paths Nexus may read, write, or index outside the primary root.</p>
          </div>
          {dirs.length ? (
            <div className="divide-y divide-border rounded-lg border border-border bg-card">
              {dirs.map(dir => (
                <div key={dir.path} className="flex flex-wrap items-start gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{dir.name || dir.path}</p>
                    <p className="mt-0.5 break-all text-xs text-muted-foreground">{dir.path}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {dir.available ? 'Available' : 'Unavailable'} · {dir.file_count} files · index {dir.index_status}
                    </p>
                  </div>
                  <select
                    value={(dir.access_mode as WorkspaceAccessMode) || 'read_write'}
                    disabled={!!working}
                    onChange={event => void updateDir(dir, event.target.value as WorkspaceAccessMode)}
                    className="h-8 rounded-md border border-border bg-background px-2 text-xs"
                  >
                    {ACCESS_MODES.map(mode => (
                      <option key={mode.id} value={mode.id}>{mode.label}</option>
                    ))}
                  </select>
                  <button type="button" disabled={!!working} onClick={() => void removeDir(dir)} className="text-xs text-destructive hover:opacity-80">
                    Remove
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="rounded-lg border border-border bg-card px-4 py-6 text-sm text-muted-foreground">No additional directories are configured.</p>
          )}
          <form className="grid gap-3 rounded-lg border border-border bg-secondary/30 p-4 sm:grid-cols-[1fr_auto_auto]" onSubmit={addDirectory}>
            <input
              value={dirInput}
              onChange={event => setDirInput(event.target.value)}
              placeholder="Absolute path to add"
              className="h-10 rounded-md border border-border bg-background px-3 text-sm outline-none focus:border-ring"
            />
            <select value={dirMode} onChange={event => setDirMode(event.target.value as WorkspaceAccessMode)} className="h-10 rounded-md border border-border bg-background px-2 text-sm">
              {ACCESS_MODES.map(mode => (
                <option key={mode.id} value={mode.id}>{mode.label}</option>
              ))}
            </select>
            <button disabled={!!working || !dirInput.trim()} className="rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background disabled:opacity-50">
              {working === 'add directory' ? 'Adding…' : 'Add'}
            </button>
          </form>
        </div>
      )}

      {activeTab === 'index' && (
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-medium">Index</h3>
            <p className="mt-1 text-xs text-muted-foreground">Rebuild or clear the workspace search index used for retrieval.</p>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3">
            <div>
              <p className="text-sm font-medium capitalize">{summary?.index?.status || 'unknown'}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {summary?.index?.indexed_files ?? 0} indexed files · {formatBytes(summary?.index?.index_storage_size || 0)} on disk
              </p>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={!!working}
                onClick={() => void run('rebuild index', async () => { await api.rebuildIndex(); setMessage('Index rebuild started.') })}
                className="rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-secondary"
              >
                {working === 'rebuild index' ? 'Rebuilding…' : 'Rebuild'}
              </button>
              <button
                type="button"
                disabled={!!working}
                onClick={() => {
                  if (!window.confirm('Clear the workspace index?')) return
                  void run('clear index', async () => { await api.clearIndex(); setMessage('Index cleared.') })
                }}
                className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-destructive hover:bg-secondary"
              >
                {working === 'clear index' ? 'Clearing…' : 'Clear'}
              </button>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'instructions' && (
        <div className="space-y-4">
          <form className="space-y-3 rounded-lg border border-border bg-card p-4" onSubmit={saveInstructions}>
            <div>
              <h3 className="text-sm font-medium">Workspace instructions</h3>
              <p className="mt-1 text-xs text-muted-foreground">Optional standing guidance Nexus should follow in this project.</p>
            </div>
            <textarea
              value={instructions}
              onChange={event => setInstructions(event.target.value)}
              rows={6}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-ring"
              placeholder="Project conventions, build commands, things to avoid…"
            />
            <div className="flex justify-end">
              <button disabled={!!working} className="rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background disabled:opacity-50">
                {working === 'save instructions' ? 'Saving…' : 'Save instructions'}
              </button>
            </div>
          </form>
        </div>
      )}

      {activeTab === 'health' && (
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-medium">Health</h3>
            <p className="mt-1 text-xs text-muted-foreground">Live checks reported by the Nexus workspace service.</p>
          </div>
          {health.length ? (
            <div className="divide-y divide-border rounded-lg border border-border bg-card">
              {health.map(check => <HealthRow key={check.name} check={check} />)}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No health checks were reported.</p>
          )}
        </div>
      )}

      {message && <p className="text-sm text-emerald-700" role="status">{message}</p>}
    </div>
  )
}
