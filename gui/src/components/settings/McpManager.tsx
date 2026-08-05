import { useState, type FormEvent } from 'react'
import { Network, Terminal, Code, Activity, Plus, Trash2, Info } from 'lucide-react'
import { api, type InventoryItem } from '../../lib/api'
import { Description } from './utils'

export function McpManager({ items, pending, onToggle, onChanged, onError }: { items: InventoryItem[]; pending: string; onToggle: (name: string, enabled: boolean) => void; onChanged: () => void; onError: (message: string) => void }) {
  const [activeTab, setActiveTab] = useState<'overview' | 'installed' | 'add' | 'settings'>('overview')
  const [name, setName] = useState('')
  const [command, setCommand] = useState('')
  const [args, setArgs] = useState('')
  const [description, setDescription] = useState('')
  const [envVars, setEnvVars] = useState('')
  const [workingDir, setWorkingDir] = useState('')
  const [saving, setSaving] = useState(false)
  
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); onError('')
    try {
      let env = undefined
      if (envVars.trim()) {
        try {
          env = JSON.parse(envVars)
        } catch (e) {
          throw new Error('Invalid JSON in environment variables')
        }
      }
      await api.createMcp({ 
        name, 
        command, 
        args: args.split(/\r?\n/).map(value => value.trim()).filter(Boolean), 
        description, 
        active: true,
        env,
        working_dir: workingDir || undefined
      })
      setName(''); setCommand(''); setArgs(''); setDescription(''); setEnvVars(''); setWorkingDir(''); onChanged()
    } catch (err) { onError(err instanceof Error ? err.message : 'Could not add the MCP server.') } finally { setSaving(false) }
  }
  
  const remove = async (id: string) => {
    if (!window.confirm(`Delete MCP server "${id}"?`)) return
    try { await api.deleteMcp(id); onChanged() } catch (err) { onError(err instanceof Error ? err.message : 'Could not delete the MCP server.') }
  }
  
  // Mock statistics for demonstration
  const stats = {
    totalServers: items.length,
    activeServers: items.filter(i => i.active).length,
    totalTools: items.reduce((sum, i) => sum + (Array.isArray(i.tools) ? i.tools.length : 0), 0),
    avgResponseTime: '45ms',
  }

  const featuredServers = [
    { name: 'GitHub', description: 'GitHub repository management and PR tools', tools: 12, icon: '🐙' },
    { name: 'Filesystem', description: 'Local file system operations and management', tools: 8, icon: '📁' },
    { name: 'Database', description: 'SQL database query and management', tools: 6, icon: '🗄️' },
    { name: 'Web Search', description: 'Web search and content retrieval', tools: 4, icon: '🔍' },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">MCP Servers</h3>
        <p className="mt-1 text-sm text-muted-foreground">Model Context Protocol servers for extended tool capabilities and integrations.</p>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-border">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'installed', label: 'Installed' },
          { id: 'add', label: 'Add Server' },
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
                <Network size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Total Servers</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.totalServers}</p>
              <p className="mt-1 text-xs text-muted-foreground">{stats.activeServers} active</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Code size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Available Tools</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.totalTools}</p>
              <p className="mt-1 text-xs text-muted-foreground">Across servers</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Activity size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Avg Response</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.avgResponseTime}</p>
              <p className="mt-1 text-xs text-muted-foreground">Per request</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Terminal size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Protocol</p>
              </div>
              <p className="mt-2 text-2xl font-bold">MCP</p>
              <p className="mt-1 text-xs text-muted-foreground">v1.0</p>
            </div>
          </div>

          {/* Featured Servers */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Popular MCP Servers</h4>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {featuredServers.map(server => (
                <div key={server.name} className="rounded-lg border border-border p-4 hover:bg-secondary transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-purple-600 text-xl">
                      {server.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <h5 className="text-sm font-semibold">{server.name}</h5>
                      <p className="text-xs text-muted-foreground">{server.tools} tools</p>
                    </div>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{server.description}</p>
                  <button
                    onClick={() => setActiveTab('add')}
                    className="mt-3 w-full rounded-md border border-border px-3 py-1.5 text-xs hover:bg-secondary"
                  >
                    Install
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Quick Actions */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Quick Actions</h4>
            <div className="flex gap-3">
              <button
                onClick={() => setActiveTab('add')}
                className="rounded-md bg-foreground px-4 py-2 text-sm text-background"
              >
                Add New Server
              </button>
              <button
                onClick={() => setActiveTab('installed')}
                className="rounded-md border border-border px-4 py-2 text-sm"
              >
                View Installed
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
              <h4 className="text-sm font-semibold">Installed MCP Servers</h4>
              <button
                onClick={() => setActiveTab('add')}
                className="flex items-center gap-2 rounded-md bg-foreground px-3 py-1.5 text-xs text-background"
              >
                <Plus size={14} />
                Add Server
              </button>
            </div>
            {!items.length ? (
              <div className="py-8 text-center">
                <Network size={48} className="mx-auto text-muted-foreground mb-4" />
                <h4 className="text-sm font-semibold mb-2">No MCP Servers Installed</h4>
                <p className="text-xs text-muted-foreground mb-4">Add MCP servers to extend Nexus AI capabilities.</p>
                <button
                  onClick={() => setActiveTab('add')}
                  className="rounded-md border border-border px-4 py-2 text-sm"
                >
                  Add First Server
                </button>
              </div>
            ) : (
              <div className="space-y-3">
                {items.map(item => {
                  const id = String(item.id || item.name || '')
                  const active = Boolean(item.active)
                  const tools = Array.isArray(item.tools) ? item.tools.length : 0
                  return (
                    <div key={id} className={`rounded-lg border ${active ? 'border-border bg-card' : 'border-border bg-secondary/30'} p-4`}>
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <Network size={16} className={active ? 'text-foreground' : 'text-muted-foreground'} />
                            <h4 className="text-sm font-semibold">{id}</h4>
                            {active && (
                              <span className="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">
                                Active
                              </span>
                            )}
                            <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">
                              {tools} tools
                            </span>
                          </div>
                          <p className="mt-1 font-mono text-xs text-muted-foreground">{String(item.command || '')}</p>
                          <Description item={item} kind="mcp" />
                          {Array.isArray(item.args) && item.args.length > 0 && (
                            <p className="mt-1 text-xs text-muted-foreground">Args: {item.args.map(String).join(' ')}</p>
                          )}
                          {typeof item.working_dir === 'string' && item.working_dir && (
                            <p className="mt-1 text-xs text-muted-foreground">Working dir: {item.working_dir}</p>
                          )}
                        </div>
                        <div className="flex shrink-0 gap-2">
                          <button
                            onClick={() => onToggle(id, !active)}
                            disabled={pending === id}
                            className={`rounded-md px-2.5 py-1 text-xs ${active ? 'bg-foreground text-background' : 'border border-border text-muted-foreground'}`}
                          >
                            {pending === id ? 'Saving…' : active ? 'On' : 'Off'}
                          </button>
                          <button
                            onClick={() => remove(id)}
                            className="rounded-md px-2 py-1 text-xs text-destructive hover:bg-destructive/10"
                          >
                            <Trash2 size={12} />
                          </button>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Add Server Tab */}
      {activeTab === 'add' && (
        <div className="space-y-6">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-2">Add MCP Server</h4>
            <p className="text-xs text-muted-foreground mb-4">
              Configure a new Model Context Protocol server for extended capabilities and integrations.
            </p>

            <form onSubmit={submit} className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="text-xs font-medium block mb-1">Server Name</label>
                  <input 
                    required 
                    value={name} 
                    onChange={event => setName(event.target.value)} 
                    placeholder="e.g. github" 
                    className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm" 
                  />
                </div>
                <div>
                  <label className="text-xs font-medium block mb-1">Command</label>
                  <input 
                    required 
                    value={command} 
                    onChange={event => setCommand(event.target.value)} 
                    placeholder="e.g. npx" 
                    className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm font-mono" 
                  />
                </div>
              </div>

              <div>
                <label className="text-xs font-medium block mb-1">Arguments (one per line)</label>
                <textarea 
                  value={args} 
                  onChange={event => setArgs(event.target.value)} 
                  rows={3} 
                  placeholder="e.g. @modelcontextprotocol/server-github" 
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm font-mono" 
                />
              </div>

              <div>
                <label className="text-xs font-medium block mb-1">Description</label>
                <input 
                  value={description} 
                  onChange={event => setDescription(event.target.value)} 
                  placeholder="Brief description of this MCP server" 
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm" 
                />
              </div>

              <div>
                <label className="text-xs font-medium block mb-1">Environment Variables (JSON)</label>
                <textarea 
                  value={envVars} 
                  onChange={event => setEnvVars(event.target.value)} 
                  rows={3} 
                  placeholder='{"GITHUB_TOKEN": "your_token"}' 
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm font-mono" 
                />
              </div>

              <div>
                <label className="text-xs font-medium block mb-1">Working Directory</label>
                <input 
                  value={workingDir} 
                  onChange={event => setWorkingDir(event.target.value)} 
                  placeholder="Optional working directory" 
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm" 
                />
              </div>

              <div className="flex items-center justify-between pt-4 border-t border-border">
                <button
                  type="button"
                  onClick={() => { setName(''); setCommand(''); setArgs(''); setDescription(''); setEnvVars(''); setWorkingDir('') }}
                  className="text-xs text-muted-foreground hover:text-foreground underline"
                >
                  Clear Form
                </button>
                <button 
                  type="submit" 
                  disabled={saving} 
                  className="rounded-md bg-foreground px-4 py-2 text-sm text-background disabled:opacity-50"
                >
                  {saving ? 'Adding…' : 'Add Server'}
                </button>
              </div>
            </form>
          </div>

          {/* Tips */}
          <div className="rounded-lg border border-blue-500 bg-blue-50 dark:bg-blue-950/20 p-6">
            <div className="flex items-start gap-3">
              <Info size={20} className="text-blue-600 shrink-0" />
              <div>
                <h4 className="text-sm font-semibold text-blue-900 dark:text-blue-100">MCP Server Tips</h4>
                <ul className="mt-2 space-y-1 text-xs text-blue-800 dark:text-blue-200">
                  <li>• Use npx for Node.js-based MCP servers without installation</li>
                  <li>• Environment variables should be valid JSON format</li>
                  <li>• Working directory is optional but can help with relative paths</li>
                  <li>• Each MCP server can provide multiple tools to Nexus AI</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Settings Tab */}
      {activeTab === 'settings' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">MCP Runtime Configuration</h4>
            <div className="space-y-4">
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Auto-start MCP servers on boot</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Enable tool caching</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked={false} className="rounded border-border" />
                <span className="text-sm">Log MCP server communications</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Allow servers to spawn subprocesses</span>
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Resource Limits</h4>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium block mb-1">Max concurrent servers</label>
                <input 
                  type="number" 
                  defaultValue={5} 
                  min="1" 
                  max="20" 
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm" 
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">Server timeout (seconds)</label>
                <input 
                  type="number" 
                  defaultValue={30} 
                  min="5" 
                  max="300" 
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm" 
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">Tool execution timeout (seconds)</label>
                <input 
                  type="number" 
                  defaultValue={60} 
                  min="10" 
                  max="600" 
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm" 
                />
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Security Settings</h4>
            <div className="space-y-4">
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Validate server certificates</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Restrict file system access</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked={false} className="rounded border-border" />
                <span className="text-sm">Allow network access from servers</span>
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
