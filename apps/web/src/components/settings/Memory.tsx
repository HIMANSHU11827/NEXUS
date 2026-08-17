import { useState, useEffect } from 'react'
import { api } from '../../lib/api'

function InfoBlock({ title, value, detail }: { title: string; value: string; detail: string }) {
  return <div className="mb-4 rounded-lg border border-border bg-card p-4"><p className="text-sm font-medium">{title}</p><p className="mt-2 text-lg font-semibold">{value}</p><p className="mt-1 text-sm text-muted-foreground">{detail}</p></div>
}

export function MemorySettings({ state }: { state: Record<string, unknown> }) {
  const [stats, setStats] = useState<Record<string, unknown> | null>(null)
  const [sessions, setSessions] = useState<Array<{ id: string; file: string; size: number; modified: number; modified_iso: string }>>([])
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Array<{ type: string; content: string; match_position: number }>>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [activeTab, setActiveTab] = useState<'overview' | 'search' | 'sessions' | 'export'>('overview')
  const [exportFormat, setExportFormat] = useState<'json' | 'text'>('json')
  const [exportData, setExportData] = useState('')
  const [importData, setImportData] = useState('')
  const [importFormat, setImportFormat] = useState<'json' | 'text'>('json')
  const [clearType, setClearType] = useState('all')

  const loadStats = async () => {
    try {
      const result = await api.memoryStatistics()
      if (result.status === 'success') {
        setStats(result.statistics)
      }
    } catch (err) {
      console.error('Memory stats error:', err)
    }
  }

  const loadSessions = async () => {
    try {
      const result = await api.memorySessions()
      if (result.status === 'success') {
        setSessions(result.sessions)
      }
    } catch (err) {
      console.error('Memory sessions error:', err)
    }
  }

  const performSearch = async () => {
    if (!searchQuery.trim()) return
    setLoading(true); setError(''); setMessage('')
    try {
      const result = await api.memorySearch(searchQuery)
      if (result.status === 'success') {
        setSearchResults(result.results)
      } else {
        setError('Search failed')
      }
    } catch (err) {
      setError('Search failed')
    } finally {
      setLoading(false)
    }
  }

  const performExport = async () => {
    setLoading(true); setError(''); setMessage('')
    try {
      const result = await api.memoryExport(exportFormat)
      if (result.status === 'success') {
        setExportData(result.data)
      } else {
        setError('Export failed')
      }
    } catch (err) {
      setError('Export failed')
    } finally {
      setLoading(false)
    }
  }

  const performImport = async () => {
    if (!importData.trim()) return
    setLoading(true); setError(''); setMessage('')
    try {
      const result = await api.memoryImport(importData, importFormat)
      if (result.status === 'success') {
        setImportData('')
        setMessage('Memory imported successfully')
      } else {
        setError('Import failed')
      }
    } catch (err) {
      setError('Import failed')
    } finally {
      setLoading(false)
    }
  }

  const performClear = async () => {
    if (!window.confirm(`Clear ${clearType} memory? This cannot be undone.`)) return
    setLoading(true); setError(''); setMessage('')
    try {
      const result = await api.memoryClear(clearType)
      if (result.status === 'success') {
        setMessage(result.message || 'Memory cleared successfully')
        loadStats()
      } else {
        setError('Clear failed')
      }
    } catch (err) {
      setError('Clear failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadStats()
    loadSessions()
  }, [])

  return <div className="space-y-4">
    <div><h3 className="text-sm font-semibold">Memory & context</h3><p className="mt-1 text-sm text-muted-foreground">Manage NEXUS memory systems including sessions, in-memory data, and knowledge retrieval.</p></div>
    
    {error && <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive" role="alert">{error}</div>}
    {message && <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 text-sm text-emerald-700 dark:text-emerald-400" role="status">{message}</div>}
    
    <div className="flex gap-2 border-b border-border">
      {[
        { id: 'overview', label: 'Overview' },
        { id: 'search', label: 'Search' },
        { id: 'sessions', label: 'Sessions' },
        { id: 'export', label: 'Export/Import' },
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
          <InfoBlock title="Current sessions" value={String(state.session_count || 0)} detail="Sessions available to the running server." />
          <InfoBlock title="Agent capacity" value={String(state.agent_count || 0)} detail="Agents reported by the active Nexus runtime." />
          {stats && (
            <>
              <InfoBlock title="In-memory keys" value={String(Array.isArray(stats.in_memory_keys) ? stats.in_memory_keys.length : 0)} detail="Active in-memory data types." />
              <InfoBlock title="Session history length" value={String(stats.session_history_length || 0)} detail="Number of turns in current session." />
              <InfoBlock title="Total sessions" value={String(stats.total_sessions || 0)} detail="All session files in storage." />
              <InfoBlock title="In-memory size" value={`${((Number(stats.in_memory_size) || 0) / 1024).toFixed(1)} KB`} detail="Total in-memory data size." />
            </>
          )}
        </div>
        
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm font-medium">Privacy</p>
          <p className="mt-1 text-sm text-muted-foreground">Memory remains local to this Nexus installation unless you explicitly enable an external provider or gateway.</p>
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm font-medium">Clear Memory</p>
          <p className="mt-1 text-sm text-muted-foreground">Remove specific or all memory types. This action cannot be undone.</p>
          <div className="mt-3 flex gap-2">
            <select value={clearType} onChange={e => setClearType(e.target.value)} className="h-9 rounded-md border border-border bg-background px-2 text-sm">
              <option value="all">All memory</option>
              <option value="in_memory">In-memory only</option>
              <option value="session">Session history only</option>
            </select>
            <button onClick={performClear} disabled={loading} className="rounded-md bg-destructive px-3 py-1.5 text-sm font-medium text-background disabled:opacity-50">
              {loading ? 'Clearing...' : 'Clear'}
            </button>
          </div>
        </div>
      </div>
    )}

    {activeTab === 'search' && (
      <div className="space-y-4">
        <div className="flex gap-2">
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search memory..."
            className="flex-1 h-9 rounded-md border border-border bg-background px-3 text-sm"
            onKeyDown={e => e.key === 'Enter' && performSearch()}
          />
          <button onClick={performSearch} disabled={loading || !searchQuery.trim()} className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background disabled:opacity-50">
            {loading ? 'Searching...' : 'Search'}
          </button>
        </div>
        
        {searchResults.length > 0 && (
          <div className="rounded-lg border border-border bg-card">
            <p className="px-4 py-3 text-sm font-medium">{searchResults.length} result{searchResults.length === 1 ? '' : 's'}</p>
            <div className="divide-y divide-border">
              {searchResults.map((result, i) => (
                <div key={i} className="px-4 py-3">
                  <p className="text-xs font-medium text-muted-foreground">{result.type}</p>
                  <p className="mt-1 text-sm">{result.content}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    )}

    {activeTab === 'sessions' && (
      <div className="space-y-4">
        {sessions.length === 0 ? (
          <p className="py-8 text-sm text-muted-foreground">No sessions found.</p>
        ) : (
          <div className="rounded-lg border border-border bg-card">
            <div className="divide-y divide-border">
              {sessions.map(session => (
                <div key={session.id} className="px-4 py-3">
                  <p className="text-sm font-medium">{session.id}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {session.modified_iso} · {(session.size / 1024).toFixed(1)} KB
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    )}

    {activeTab === 'export' && (
      <div className="space-y-4">
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm font-medium">Export Memory</p>
          <p className="mt-1 text-sm text-muted-foreground">Export all memory data to JSON or text format.</p>
          <div className="mt-3 flex gap-2">
            <select value={exportFormat} onChange={e => setExportFormat(e.target.value as 'json' | 'text')} className="h-9 rounded-md border border-border bg-background px-2 text-sm">
              <option value="json">JSON</option>
              <option value="text">Text</option>
            </select>
            <button onClick={performExport} disabled={loading} className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background disabled:opacity-50">
              {loading ? 'Exporting...' : 'Export'}
            </button>
          </div>
          {exportData && (
            <div className="mt-3">
              <textarea
                value={exportData}
                readOnly
                rows={10}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs font-mono"
              />
            </div>
          )}
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm font-medium">Import Memory</p>
          <p className="mt-1 text-sm text-muted-foreground">Import memory data from JSON or text format.</p>
          <div className="mt-3 space-y-3">
            <select value={importFormat} onChange={e => setImportFormat(e.target.value as 'json' | 'text')} className="h-9 rounded-md border border-border bg-background px-2 text-sm">
              <option value="json">JSON</option>
              <option value="text">Text</option>
            </select>
            <textarea
              value={importData}
              onChange={e => setImportData(e.target.value)}
              placeholder="Paste memory data here..."
              rows={6}
              className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            />
            <button onClick={performImport} disabled={loading || !importData.trim()} className="rounded-md bg-foreground px-3 py-1.5 text-sm font-medium text-background disabled:opacity-50">
              {loading ? 'Importing...' : 'Import'}
            </button>
          </div>
        </div>
      </div>
    )}
  </div>
}
