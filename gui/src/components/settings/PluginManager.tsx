import { useState } from 'react'
import { Puzzle, Shield, Download, Star, Plus } from 'lucide-react'
import { type InventoryItem } from '../../lib/api'
import { Description } from './utils'

export function PluginManager({ items, pending, onToggle }: { items: InventoryItem[]; pending: string; onToggle: (name: string, enabled: boolean) => void }) {
  const [activeTab, setActiveTab] = useState<'overview' | 'installed' | 'marketplace' | 'settings'>('overview')

  const stats = {
    totalPlugins: items.length,
    activePlugins: items.filter(i => i.enabled).length,
    trustedPlugins: items.filter(i => i.trusted).length,
    totalDownloads: null as number | null,
  }

  const featuredPlugins = [
    { name: 'Code Formatter', description: 'Auto-format code with Prettier and Black', downloads: '2.4K', rating: 4.8, icon: '🎨' },
    { name: 'Git Integration', description: 'Git operations and version control', downloads: '1.8K', rating: 4.9, icon: '📦' },
    { name: 'Database Tools', description: 'SQL database management and queries', downloads: '1.2K', rating: 4.7, icon: '🗄️' },
    { name: 'API Tester', description: 'Test and document API endpoints', downloads: '956', rating: 4.6, icon: '🔌' },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">Plugins</h3>
        <p className="mt-1 text-sm text-muted-foreground">Manage Nexus plugins for extended functionality and custom integrations.</p>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-border">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'installed', label: 'Installed' },
          { id: 'marketplace', label: 'Marketplace' },
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
                <Puzzle size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Total Plugins</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.totalPlugins}</p>
              <p className="mt-1 text-xs text-muted-foreground">{stats.activePlugins} active</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Shield size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Trusted Plugins</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.trustedPlugins}</p>
              <p className="mt-1 text-xs text-muted-foreground">Verified</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Download size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Total Downloads</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.totalDownloads ?? '—'}</p>
              <p className="mt-1 text-xs text-muted-foreground">All time</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Star size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Avg Rating</p>
              </div>
              <p className="mt-2 text-2xl font-bold">4.7</p>
              <p className="mt-1 text-xs text-muted-foreground">User rating</p>
            </div>
          </div>

          {/* Featured Plugins */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Popular Plugins</h4>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {featuredPlugins.map(plugin => (
                <div key={plugin.name} className="rounded-lg border border-border p-4 hover:bg-secondary transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-purple-600 text-xl">
                      {plugin.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <h5 className="text-sm font-semibold">{plugin.name}</h5>
                      <p className="text-xs text-muted-foreground">{plugin.downloads} downloads</p>
                    </div>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{plugin.description}</p>
                  <div className="mt-3 flex items-center justify-between">
                    <div className="flex items-center gap-1">
                      <Star size={12} className="text-amber-500 fill-amber-500" />
                      <span className="text-xs">{plugin.rating}</span>
                    </div>
                    <button
                      onClick={() => setActiveTab('marketplace')}
                      className="text-xs text-blue-600 hover:text-blue-700 underline"
                    >
                      View
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Quick Actions */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Quick Actions</h4>
            <div className="flex gap-3">
              <button
                onClick={() => setActiveTab('marketplace')}
                className="rounded-md bg-foreground px-4 py-2 text-sm text-background"
              >
                Browse Marketplace
              </button>
              <button
                onClick={() => setActiveTab('installed')}
                className="rounded-md border border-border px-4 py-2 text-sm"
              >
                Manage Installed
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Installed Tab */}
      {activeTab === 'installed' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <div className="flex items-center justify-between mb-4">
              <h4 className="text-sm font-semibold">Installed Plugins</h4>
              <button
                onClick={() => setActiveTab('marketplace')}
                className="flex items-center gap-2 rounded-md bg-foreground px-3 py-1.5 text-xs text-background"
              >
                <Plus size={14} />
                Add Plugin
              </button>
            </div>
            {!items.length ? (
              <div className="py-8 text-center">
                <Puzzle size={48} className="mx-auto text-muted-foreground mb-4" />
                <h4 className="text-sm font-semibold mb-2">No Plugins Installed</h4>
                <p className="text-xs text-muted-foreground mb-4">Browse the marketplace to install plugins.</p>
                <button
                  onClick={() => setActiveTab('marketplace')}
                  className="rounded-md border border-border px-4 py-2 text-sm"
                >
                  Browse Marketplace
                </button>
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {items.map(item => {
                  const id = String(item.id || item.name || '')
                  const enabled = Boolean(item.enabled)
                  const pluginName = id.split('@')[0]
                  const version = id.includes('@') ? id.split('@')[1] : 'unknown'
                  
                  return (
                    <div key={id} className={`rounded-lg border ${enabled ? 'border-border bg-card' : 'border-border bg-secondary/30'} p-4`}>
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <Puzzle size={16} className={enabled ? 'text-foreground' : 'text-muted-foreground'} />
                            <h4 className="text-sm font-semibold">{pluginName}</h4>
                            {version !== 'unknown' && <span className="text-xs text-muted-foreground">v{version}</span>}
                            {enabled && (
                              <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">
                                Active
                              </span>
                            )}
                          </div>
                          <Description item={item} kind="plugin" />
                          <div className="mt-2 flex flex-wrap gap-2">
                            {item.available !== false && (
                              <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">
                                Available
                              </span>
                            )}
                            {item.trusted === true && (
                              <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">
                                <Shield size={10} className="mr-1" />
                                Trusted
                              </span>
                            )}
                          </div>
                        </div>
                        <button
                          onClick={() => onToggle(id, !enabled)}
                          disabled={pending === id}
                          className={`shrink-0 rounded-md px-2.5 py-1 text-xs ${enabled ? 'bg-foreground text-background' : 'border border-border text-muted-foreground'}`}
                        >
                          {pending === id ? 'Saving…' : enabled ? 'On' : 'Off'}
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Marketplace Tab */}
      {activeTab === 'marketplace' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <div className="flex items-center justify-between mb-4">
              <h4 className="text-sm font-semibold">Plugin Marketplace</h4>
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="Search plugins..."
                  className="h-10 w-64 rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {[...featuredPlugins, 
                { name: 'Security Scanner', description: 'Security vulnerability scanning and analysis', downloads: '834', rating: 4.5, icon: '🔒' },
                { name: 'Performance Monitor', description: 'Monitor and analyze system performance', downloads: '678', rating: 4.4, icon: '📊' },
                { name: 'Test Runner', description: 'Automated testing framework integration', downloads: '545', rating: 4.6, icon: '🧪' },
              ].map((plugin, index) => (
                <div key={index} className="rounded-lg border border-border p-4 hover:bg-secondary transition-colors">
                  <div className="flex items-start gap-3">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-purple-600 text-2xl">
                      {plugin.icon}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <h5 className="text-sm font-semibold">{plugin.name}</h5>
                        {index < 4 && (
                          <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                            <Star size={10} className="mr-1" />
                            Featured
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{plugin.description}</p>
                      <div className="mt-2 flex items-center gap-3">
                        <div className="flex items-center gap-1">
                          <Star size={12} className="text-amber-500 fill-amber-500" />
                          <span className="text-xs">{plugin.rating}</span>
                        </div>
                        <span className="text-xs text-muted-foreground">·</span>
                        <span className="text-xs text-muted-foreground">{plugin.downloads} downloads</span>
                      </div>
                    </div>
                  </div>
                  <div className="mt-4 flex gap-2">
                    <button className="flex-1 rounded-md bg-foreground px-3 py-1.5 text-xs text-background">
                      Install
                    </button>
                    <button className="rounded-md border border-border px-3 py-1.5 text-xs">
                      Details
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Settings Tab */}
      {activeTab === 'settings' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Plugin Trust Model</h4>
            <p className="text-xs text-muted-foreground mb-4">Configure how Nexus handles plugin security and permissions.</p>
            <div className="space-y-4">
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Require explicit approval for new plugins</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Allow plugins to access file system</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked={false} className="rounded border-border" />
                <span className="text-sm">Allow plugins to make network requests</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked={false} className="rounded border-border" />
                <span className="text-sm">Allow plugins to execute commands</span>
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Plugin Lifecycle Hooks</h4>
            <p className="text-xs text-muted-foreground mb-4">Configure when plugins are loaded and unloaded.</p>
            <div className="space-y-4">
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Load plugins on server startup</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Unload plugins on server shutdown</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked={false} className="rounded border-border" />
                <span className="text-sm">Reload plugins on configuration change</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked={false} className="rounded border-border" />
                <span className="text-sm">Auto-update plugins (when available)</span>
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Plugin Directory</h4>
            <p className="text-xs text-muted-foreground mb-4">Configure where Nexus looks for plugin files.</p>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium block mb-1">Plugin directory path</label>
                <input
                  type="text"
                  placeholder="plugins/"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">Custom plugin registry URL</label>
                <input
                  type="url"
                  placeholder="https://registry.example.com"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Plugin Security</h4>
            <div className="space-y-4">
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Verify plugin signatures</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Scan for known vulnerabilities</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked={false} className="rounded border-border" />
                <span className="text-sm">Sandbox plugin execution</span>
              </label>
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
