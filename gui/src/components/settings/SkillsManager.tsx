import { useState } from 'react'
import { GraduationCap, BookOpen, Target, Award, Search, CheckCircle2, CircleAlert } from 'lucide-react'
import { type InventoryItem } from '../../lib/api'
import { labelFor, Description } from './utils'

export function SkillsManager({ items, pending, onToggle }: { items: InventoryItem[]; pending: string; onToggle: (name: string, enabled: boolean) => void }) {
  const [activeTab, setActiveTab] = useState<'overview' | 'installed' | 'categories' | 'settings'>('overview')
  const [searchQuery, setSearchQuery] = useState('')

  const stats = {
    totalSkills: items.length,
    activeSkills: items.filter(i => i.enabled).length,
    skillCategories: new Set(items.map(i => i.category || 'General')).size,
    totalExecutions: null as number | null,
  }

  const categories = [
    { id: 'all', name: 'All Skills', count: items.length, icon: '📚' },
    { id: 'coding', name: 'Coding', count: items.filter(i => String(i.category || '').toLowerCase().includes('code')).length, icon: '💻' },
    { id: 'analysis', name: 'Analysis', count: items.filter(i => String(i.category || '').toLowerCase().includes('analysis')).length, icon: '📊' },
    { id: 'writing', name: 'Writing', count: items.filter(i => String(i.category || '').toLowerCase().includes('writing')).length, icon: '✍️' },
    { id: 'research', name: 'Research', count: items.filter(i => String(i.category || '').toLowerCase().includes('research')).length, icon: '🔬' },
  ]

  const featuredSkills = [
    { name: 'Code Review', description: 'Automated code review and quality checks', category: 'coding', executions: '1.2K', icon: '🔍' },
    { name: 'Data Analysis', description: 'Statistical analysis and data visualization', category: 'analysis', executions: '856', icon: '📈' },
    { name: 'Technical Writing', description: 'Generate technical documentation', category: 'writing', executions: '634', icon: '📝' },
    { name: 'Research Assistant', description: 'Deep research and information gathering', category: 'research', executions: '445', icon: '🎓' },
  ]

  const filteredItems = items.filter(item => {
    return !searchQuery || String(item.name || item.id || '').toLowerCase().includes(searchQuery.toLowerCase())
  })

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">Skills</h3>
        <p className="mt-1 text-sm text-muted-foreground">Manage Nexus skills for specialized AI capabilities and task automation.</p>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-border">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'installed', label: 'Installed' },
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
                <GraduationCap size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Total Skills</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.totalSkills}</p>
              <p className="mt-1 text-xs text-muted-foreground">{stats.activeSkills} active</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <BookOpen size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Categories</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.skillCategories}</p>
              <p className="mt-1 text-xs text-muted-foreground">Skill groups</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Target size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Executions</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.totalExecutions ?? '—'}</p>
              <p className="mt-1 text-xs text-muted-foreground">History not reported by the server</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Award size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Success Rate</p>
              </div>
              <p className="mt-2 text-2xl font-bold">—</p>
              <p className="mt-1 text-xs text-muted-foreground">Not reported by the server</p>
            </div>
          </div>

          {/* Featured Skills */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Popular Skills</h4>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {featuredSkills.map(skill => (
                <div key={skill.name} className="rounded-lg border border-border p-4 hover:bg-secondary transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-purple-600 text-xl">
                      {skill.icon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <h5 className="text-sm font-semibold">{skill.name}</h5>
                      <p className="text-xs text-muted-foreground capitalize">{skill.category}</p>
                    </div>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{skill.description}</p>
                  <p className="mt-2 text-xs text-muted-foreground">{skill.executions} executions</p>
                </div>
              ))}
            </div>
          </div>

          {/* Quick Actions */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Quick Actions</h4>
            <div className="flex gap-3">
              <button
                onClick={() => setActiveTab('installed')}
                className="rounded-md bg-foreground px-4 py-2 text-sm text-background"
              >
                View All Skills
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

      {/* Installed Tab */}
      {activeTab === 'installed' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <div className="flex items-center justify-between mb-4">
              <h4 className="text-sm font-semibold">Installed Skills</h4>
              <div className="relative">
                <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <input
                  type="text"
                  placeholder="Search skills..."
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  className="h-10 w-64 rounded-md border border-border bg-background pl-9 pr-3 text-sm"
                />
              </div>
            </div>
            {!filteredItems.length ? (
              <div className="py-8 text-center">
                <GraduationCap size={48} className="mx-auto text-muted-foreground mb-4" />
                <h4 className="text-sm font-semibold mb-2">No Skills Found</h4>
                <p className="text-xs text-muted-foreground">Try adjusting your search criteria.</p>
              </div>
            ) : (
              <div className="divide-y divide-border rounded-lg border border-border bg-card">
                {filteredItems.map(item => {
                  const id = String(item.id || item.name || '')
                  const enabled = Boolean(item.enabled)
                  
                  return (
                    <div key={id} className="flex items-start gap-3 px-4 py-3">
                      {enabled === false ? <CircleAlert size={16} className="mt-0.5 shrink-0 text-amber-600" /> : <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-emerald-600" />}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium text-foreground">{labelFor(item)}</p>
                          {typeof item.category === 'string' && <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">{item.category}</span>}
                        </div>
                        <Description item={item} kind="skill" />
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
            <h4 className="text-sm font-semibold mb-4">Skill Categories</h4>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {categories.map(category => (
                <div key={category.id} className="rounded-lg border border-border p-4 hover:bg-secondary transition-colors cursor-pointer">
                  <div className="flex items-center gap-3">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-purple-600 text-2xl">
                      {category.icon}
                    </div>
                    <div className="flex-1">
                      <h5 className="text-sm font-semibold">{category.name}</h5>
                      <p className="text-xs text-muted-foreground">{category.count} skills</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Skill Discovery</h4>
            <div className="space-y-4">
              <div className="rounded-lg border border-border p-4">
                <h5 className="text-sm font-semibold mb-2">Coding Skills</h5>
                <p className="text-xs text-muted-foreground mb-2">Skills for code generation, review, and debugging.</p>
                <div className="flex flex-wrap gap-2">
                  {items.filter(i => String(i.category || '').toLowerCase().includes('code')).map(item => (
                    <span key={String(item.id)} className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-xs">{labelFor(item)}</span>
                  ))}
                </div>
              </div>
              <div className="rounded-lg border border-border p-4">
                <h5 className="text-sm font-semibold mb-2">Analysis Skills</h5>
                <p className="text-xs text-muted-foreground mb-2">Skills for data analysis and visualization.</p>
                <div className="flex flex-wrap gap-2">
                  {items.filter(i => String(i.category || '').toLowerCase().includes('analysis')).map(item => (
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
            <h4 className="text-sm font-semibold mb-4">Skill Execution</h4>
            <div className="space-y-4">
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Auto-select best skill for task</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Enable skill chaining</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked={false} className="rounded border-border" />
                <span className="text-sm">Show skill execution logs</span>
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Skill Learning</h4>
            <div className="space-y-4">
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Enable skill improvement from usage</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked={false} className="rounded border-border" />
                <span className="text-sm">Share anonymized usage data</span>
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Performance</h4>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium block mb-1">Max concurrent skill executions</label>
                <input
                  type="number"
                  defaultValue={3}
                  min="1"
                  max="10"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">Skill execution timeout (seconds)</label>
                <input
                  type="number"
                  defaultValue={60}
                  min="10"
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
