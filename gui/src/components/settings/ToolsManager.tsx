import { useState } from 'react'
import { Hammer, FileText, Shield, Layers, Search, Filter, CheckCircle2, CircleAlert } from 'lucide-react'
import { type InventoryItem } from '../../lib/api'
import { labelFor, Description } from './utils'

export function ToolsManager({ items, pending, onToggle }: { items: InventoryItem[]; pending: string; onToggle: (name: string, enabled: boolean) => void }) {
  const [activeTab, setActiveTab] = useState<'overview' | 'registered' | 'categories' | 'settings'>('overview')
  const [searchQuery, setSearchQuery] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('all')

  // Mock statistics for demonstration
  const stats = {
    totalTools: items.length,
    enabledTools: items.filter(i => i.enabled).length,
    readOnlyTools: items.filter(i => i.read_only).length,
    safeTools: items.filter(i => i.safe).length,
  }

  const categories = [
    { id: 'all', name: 'All Tools', count: items.length },
    { id: 'file', name: 'File Operations', count: items.filter(i => i.name?.toLowerCase().includes('file')).length },
    { id: 'search', name: 'Search', count: items.filter(i => i.name?.toLowerCase().includes('search')).length },
    { id: 'code', name: 'Code', count: items.filter(i => i.name?.toLowerCase().includes('code') || i.name?.toLowerCase().includes('edit')).length },
    { id: 'system', name: 'System', count: items.filter(i => i.name?.toLowerCase().includes('system') || i.name?.toLowerCase().includes('process')).length },
  ]

  const featuredTools = [
    { name: 'File Read', description: 'Read file contents from the workspace', category: 'file', icon: '📄' },
    { name: 'File Write', description: 'Write content to files in the workspace', category: 'file', icon: '✏️' },
    { name: 'Web Search', description: 'Search the web for information', category: 'search', icon: '🔍' },
    { name: 'Code Edit', description: 'Edit code with precision and context', category: 'code', icon: '🔧' },
  ]

  const filteredItems = items.filter(item => {
    const matchesSearch = !searchQuery || item.name?.toLowerCase().includes(searchQuery.toLowerCase())
    const matchesCategory = categoryFilter === 'all' || 
      (categoryFilter === 'file' && item.name?.toLowerCase().includes('file')) ||
      (categoryFilter === 'search' && item.name?.toLowerCase().includes('search')) ||
      (categoryFilter === 'code' && (item.name?.toLowerCase().includes('code') || item.name?.toLowerCase().includes('edit'))) ||
      (categoryFilter === 'system' && (item.name?.toLowerCase().includes('system') || item.name?.toLowerCase().includes('process')))
    return matchesSearch && matchesCategory
  })

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">Tools</h3>
        <p className="mt-1 text-sm text-muted-foreground">Manage Nexus tools for file operations, code editing, and system interactions.</p>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-border">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'registered', label: 'Registered' },
          { id: 'categories', label: 'Categories' },
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
                <Hammer size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Total Tools</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.totalTools}</p>
              <p className="mt-1 text-xs text-muted-foreground">{stats.enabledTools} enabled</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <FileText size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Read-Only</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.readOnlyTools}</p>
              <p className="mt-1 text-xs text-muted-foreground">Safe operations</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Shield size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Safe Tools</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.safeTools}</p>
              <p className="mt-1 text-xs text-muted-foreground">Concurrency-safe</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Layers size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Categories</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{categories.length}</p>
              <p className="mt-1 text-xs text-muted-foreground">Tool groups</p>
            </div>
          </div>

          {/* Featured Tools */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Essential Tools</h4>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {featuredTools.map(tool => (
                <div key={tool.name} className="rounded-lg border border-border p-4 hover:bg-secondary transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-purple-600 text-xl">
                      {tool.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <h5 className="text-sm font-semibold">{tool.name}</h5>
                      <p className="text-xs text-muted-foreground capitalize">{tool.category}</p>
                    </div>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{tool.description}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Quick Actions */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Quick Actions</h4>
            <div className="flex gap-3">
              <button
                onClick={() => setActiveTab('registered')}
                className="rounded-md bg-foreground px-4 py-2 text-sm text-background"
              >
                View All Tools
              </button>
              <button
                onClick={() => setActiveTab('categories')}
                className="rounded-md border border-border px-4 py-2 text-sm"
              >
                Browse Categories
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Registered Tab */}
      {activeTab === 'registered' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <div className="flex items-center justify-between mb-4">
              <h4 className="text-sm font-semibold">Registered Tools</h4>
              <div className="flex gap-2">
                <div className="relative">
                  <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                  <input
                    type="text"
                    placeholder="Search tools..."
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    className="h-10 w-64 rounded-md border border-border bg-background pl-9 pr-3 text-sm"
                  />
                </div>
                <select
                  value={categoryFilter}
                  onChange={e => setCategoryFilter(e.target.value)}
                  className="h-10 rounded-md border border-border bg-background px-3 text-sm"
                >
                  {categories.map(cat => (
                    <option key={cat.id} value={cat.id}>{cat.name} ({cat.count})</option>
                  ))}
                </select>
              </div>
            </div>
            {!filteredItems.length ? (
              <div className="py-8 text-center">
                <Hammer size={48} className="mx-auto text-muted-foreground mb-4" />
                <h4 className="text-sm font-semibold mb-2">No Tools Found</h4>
                <p className="text-xs text-muted-foreground">Try adjusting your search or filter criteria.</p>
              </div>
            ) : (
              <div className="divide-y divide-border rounded-lg border border-border bg-card">
                {filteredItems.map(item => {
                  const id = String(item.id || item.name || '')
                  const enabled = Boolean(item.enabled)
                  const readOnly = Boolean(item.read_only)
                  const safe = Boolean(item.safe)
                  
                  return (
                    <div key={id} className="flex items-start gap-3 px-4 py-3">
                      {enabled === false ? <CircleAlert size={16} className="mt-0.5 shrink-0 text-amber-600" /> : <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-emerald-600" />}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium text-foreground">{labelFor(item)}</p>
                          {readOnly && <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">Read-only</span>}
                          {safe && <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">Safe</span>}
                        </div>
                        <Description item={item} kind="tool" />
                        <p className="mt-1 text-xs text-muted-foreground">{readOnly ? 'Read-only' : 'Can make changes'} · {safe ? 'concurrency-safe' : 'runs with normal tool safeguards'}</p>
                      </div>
                      <button onClick={() => onToggle(id, !enabled)} disabled={pending === id} className={`shrink-0 rounded-md px-2.5 py-1 text-xs font-medium transition disabled:opacity-50 ${enabled ? 'bg-foreground text-background hover:opacity-80' : 'border border-border text-muted-foreground hover:bg-secondary'}`}>{pending === id ? 'Saving…' : enabled ? 'On' : 'Off'}</button>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Categories Tab */}
      {activeTab === 'categories' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Tool Categories</h4>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {categories.map(category => (
                <div key={category.id} className="rounded-lg border border-border p-4 hover:bg-secondary transition-colors cursor-pointer" onClick={() => { setCategoryFilter(category.id); setActiveTab('registered') }}>
                  <div className="flex items-center justify-between">
                    <div>
                      <h5 className="text-sm font-semibold">{category.name}</h5>
                      <p className="text-xs text-muted-foreground">{category.count} tools</p>
                    </div>
                    <Filter size={16} className="text-muted-foreground" />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Category Details</h4>
            <div className="space-y-4">
              <div className="rounded-lg border border-border p-4">
                <h5 className="text-sm font-semibold mb-2">File Operations</h5>
                <p className="text-xs text-muted-foreground mb-2">Tools for reading, writing, and managing files in the workspace.</p>
                <div className="flex flex-wrap gap-2">
                  {items.filter(i => i.name?.toLowerCase().includes('file')).map(item => (
                    <span key={String(item.id)} className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-xs">{labelFor(item)}</span>
                  ))}
                </div>
              </div>
              <div className="rounded-lg border border-border p-4">
                <h5 className="text-sm font-semibold mb-2">Search & Discovery</h5>
                <p className="text-xs text-muted-foreground mb-2">Tools for searching content and discovering information.</p>
                <div className="flex flex-wrap gap-2">
                  {items.filter(i => i.name?.toLowerCase().includes('search')).map(item => (
                    <span key={String(item.id)} className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-xs">{labelFor(item)}</span>
                  ))}
                </div>
              </div>
              <div className="rounded-lg border border-border p-4">
                <h5 className="text-sm font-semibold mb-2">Code Editing</h5>
                <p className="text-xs text-muted-foreground mb-2">Tools for editing code with context awareness.</p>
                <div className="flex flex-wrap gap-2">
                  {items.filter(i => i.name?.toLowerCase().includes('code') || i.name?.toLowerCase().includes('edit')).map(item => (
                    <span key={String(item.id)} className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-xs">{labelFor(item)}</span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Settings Tab */}
      {activeTab === 'settings' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Tool Execution</h4>
            <div className="space-y-4">
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Enable parallel tool execution</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Cache tool results</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked={false} className="rounded border-border" />
                <span className="text-sm">Show tool execution logs</span>
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Tool Safety</h4>
            <div className="space-y-4">
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Require confirmation for destructive operations</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Enable sandbox mode for file operations</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked={false} className="rounded border-border" />
                <span className="text-sm">Restrict file system access to workspace</span>
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Performance</h4>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium block mb-1">Max concurrent tool executions</label>
                <input
                  type="number"
                  defaultValue={5}
                  min="1"
                  max="20"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">Tool execution timeout (seconds)</label>
                <input
                  type="number"
                  defaultValue={30}
                  min="5"
                  max="300"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
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
