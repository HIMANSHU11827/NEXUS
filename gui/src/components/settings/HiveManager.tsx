import { useState, type FormEvent } from 'react'
import { UsersRound, Brain, CheckCircle2, Play, Square, Info } from 'lucide-react'
import { api, type HiveItem } from '../../lib/api'

export function HiveManager({ response, pending, onToggle, onChanged, onError }: { response?: { enabled: boolean; personas: string[]; hives: HiveItem[] }; pending: boolean; onToggle: (enabled: boolean) => void; onChanged: () => void; onError: (message: string) => void }) {
  const [activeTab, setActiveTab] = useState<'overview' | 'create' | 'activity' | 'personas' | 'settings'>('overview')
  const [agents, setAgents] = useState([{ task: '', persona: 'WORKER' }])
  const [starting, setStarting] = useState(false)
  const enabled = response?.enabled ?? false
  const personas = response?.personas?.length ? response.personas : ['WORKER', 'RESEARCHER', 'CRITIC', 'VERIFIER', 'COORDINATOR']
  const hives = response?.hives || []

  const updateAgent = (index: number, field: 'task' | 'persona', value: string) => setAgents(current => current.map((agent, agentIndex) => agentIndex === index ? { ...agent, [field]: value } : agent))

  const start = async (event: FormEvent) => {
    event.preventDefault(); setStarting(true); onError('')
    try { await api.createHive(agents.filter(agent => agent.task.trim())); setAgents([{ task: '', persona: 'WORKER' }]); onChanged() } catch (err) { onError(err instanceof Error ? err.message : 'Could not start the hive.') } finally { setStarting(false) }
  }

  const cancel = async (id: string) => { try { await api.cancelHive(id); onChanged() } catch (err) { onError(err instanceof Error ? err.message : 'Could not cancel the hive.') } }
  const resume = async (id: string) => { try { await api.resumeHive(id); onChanged() } catch (err) { onError(err instanceof Error ? err.message : 'Could not resume the hive.') } }

  // Mock statistics for demonstration
  const stats = {
    totalHives: hives.length,
    runningHives: hives.filter(h => h.status === 'running').length,
    completedHives: hives.filter(h => h.status === 'completed').length,
    totalAgents: hives.reduce((sum, h) => sum + h.agents.length, 0),
    avgAgentsPerHive: hives.length > 0 ? (hives.reduce((sum, h) => sum + h.agents.length, 0) / hives.length).toFixed(1) : 0,
    successRate: hives.length > 0 ? ((hives.filter(h => h.status === 'completed').length / hives.length) * 100).toFixed(0) : 0,
  }

  const personaDescriptions: Record<string, string> = {
    WORKER: 'Executes assigned tasks with focus on completion',
    RESEARCHER: 'Gathers information and performs deep analysis',
    CRITIC: 'Reviews work and provides constructive feedback',
    VERIFIER: 'Validates results and checks for errors',
    COORDINATOR: 'Manages other agents and orchestrates workflows',
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold">Hive Multi-Agent System</h3>
        <p className="mt-1 text-sm text-muted-foreground">Spawn and coordinate specialized sub-agents for complex multi-agent workflows.</p>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-border">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'create', label: 'Create Hive' },
          { id: 'activity', label: 'Activity' },
          { id: 'personas', label: 'Personas' },
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
          {/* Runtime Toggle */}
          <div className="flex items-center justify-between rounded-lg border border-border bg-card p-6">
            <div>
              <h4 className="text-sm font-semibold">Hive Runtime</h4>
              <p className="mt-1 text-xs text-muted-foreground">
                Enables the multi-agent Hive engine for spawning specialized sub-agents. A configured LLM provider is required.
              </p>
            </div>
            <button 
              onClick={() => onToggle(!enabled)} 
              disabled={pending}
              className={`rounded-md px-4 py-2 text-sm font-medium ${enabled ? 'bg-foreground text-background' : 'border border-border text-muted-foreground'}`}
            >
              {pending ? 'Saving…' : enabled ? 'Running' : 'Stopped'}
            </button>
          </div>

          {/* Statistics Cards */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <UsersRound size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Total Hives</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.totalHives}</p>
              <p className="mt-1 text-xs text-muted-foreground">{stats.runningHives} running</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <Brain size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Total Agents</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.totalAgents}</p>
              <p className="mt-1 text-xs text-muted-foreground">{stats.avgAgentsPerHive} avg/hive</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <CheckCircle2 size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Success Rate</p>
              </div>
              <p className="mt-2 text-2xl font-bold">{stats.successRate}%</p>
              <p className="mt-1 text-xs text-muted-foreground">{stats.completedHives} completed</p>
            </div>
          </div>

          {/* Available Personas */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Available Personas</h4>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {personas.map((persona, index) => (
                <div key={index} className="rounded-lg border border-border p-4 hover:bg-secondary transition-colors">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-100 text-blue-600 text-xs font-bold">
                      {persona[0]}
                    </div>
                    <p className="text-sm font-medium">{persona}</p>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{personaDescriptions[persona] || 'Specialized agent role'}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Quick Actions */}
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Quick Actions</h4>
            <div className="flex gap-3">
              <button 
                onClick={() => setActiveTab('create')}
                className="rounded-md bg-foreground px-4 py-2 text-sm text-background"
              >
                Create New Hive
              </button>
              <button 
                onClick={() => setActiveTab('activity')}
                className="rounded-md border border-border px-4 py-2 text-sm"
              >
                View Activity
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Hive Tab */}
      {activeTab === 'create' && (
        <div className="space-y-6">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-2">Create New Hive</h4>
            <p className="text-xs text-muted-foreground mb-4">
              Each row represents a specialized sub-agent with a specific persona and task. Agents will work collaboratively to complete the overall objective.
            </p>

            <form onSubmit={start} className="space-y-4">
              {agents.map((agent, index) => (
                <div key={index} className="grid gap-3 sm:grid-cols-[1fr_180px_auto] items-start">
                  <div>
                    <label className="text-xs font-medium block mb-1">Task Description</label>
                    <input
                      required
                      value={agent.task}
                      onChange={event => updateAgent(index, 'task', event.target.value)}
                      placeholder="Describe the agent's specific task..."
                      className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-medium block mb-1">Persona</label>
                    <select
                      value={agent.persona}
                      onChange={event => updateAgent(index, 'persona', event.target.value)}
                      className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                    >
                      {personas.map(persona => (
                        <option key={persona} value={persona}>{persona}</option>
                      ))}
                    </select>
                  </div>
                  <div className="pt-5">
                    <button
                      type="button"
                      onClick={() => setAgents(current => current.length === 1 ? current : current.filter((_, agentIndex) => agentIndex !== index))}
                      disabled={agents.length === 1}
                      className="text-xs text-destructive disabled:opacity-30 hover:underline"
                    >
                      Remove
                    </button>
                  </div>
                </div>
              ))}

              <div className="flex items-center justify-between pt-4 border-t border-border">
                <button
                  type="button"
                  onClick={() => setAgents(current => [...current, { task: '', persona: 'WORKER' }])}
                  className="text-xs text-muted-foreground hover:text-foreground underline"
                >
                  + Add another agent
                </button>
                <button
                  type="submit"
                  disabled={!enabled || starting}
                  className="rounded-md bg-foreground px-4 py-2 text-sm text-background disabled:opacity-50"
                >
                  {starting ? 'Starting Hive…' : 'Start Hive'}
                </button>
              </div>
            </form>
          </div>

          {/* Tips */}
          <div className="rounded-lg border border-blue-500 bg-blue-50 dark:bg-blue-950/20 p-6">
            <div className="flex items-start gap-3">
              <Info size={20} className="text-blue-600 shrink-0" />
              <div>
                <h4 className="text-sm font-semibold text-blue-900 dark:text-blue-100">Hive Best Practices</h4>
                <ul className="mt-2 space-y-1 text-xs text-blue-800 dark:text-blue-200">
                  <li>• Use RESEARCHER agents for information gathering and analysis</li>
                  <li>• Assign CRITIC agents to review and validate work</li>
                  <li>• Use COORDINATOR to manage complex multi-step workflows</li>
                  <li>• Each agent should have a clear, specific task</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Activity Tab */}
      {activeTab === 'activity' && (
        <div className="space-y-4">
          {!hives.length ? (
            <div className="rounded-lg border border-border bg-card p-12 text-center">
              <UsersRound size={48} className="mx-auto text-muted-foreground mb-4" />
              <h4 className="text-sm font-semibold mb-2">No Hive Activity</h4>
              <p className="text-xs text-muted-foreground mb-4">No Hive runs have been created since this server started.</p>
              <button
                onClick={() => setActiveTab('create')}
                className="rounded-md bg-foreground px-4 py-2 text-sm text-background"
              >
                Create Your First Hive
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {hives.map(hive => (
                <div key={hive.id} className="rounded-lg border border-border bg-card p-6">
                  <div className="flex items-start justify-between gap-4 mb-4">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                          hive.status === 'running' ? 'bg-emerald-100 text-emerald-800' :
                          hive.status === 'completed' ? 'bg-blue-100 text-blue-800' :
                          hive.status === 'failed' ? 'bg-red-100 text-red-800' :
                          'bg-gray-100 text-gray-800'
                        }`}>
                          {hive.status === 'running' && <Play size={10} className="mr-1" />}
                          {hive.status === 'completed' && <CheckCircle2 size={10} className="mr-1" />}
                          {hive.status || 'unknown'}
                        </span>
                        <p className="font-mono text-xs text-muted-foreground">{hive.id}</p>
                      </div>
                      <p className="mt-2 text-sm">
                        {hive.agents.length} agent{hive.agents.length === 1 ? '' : 's'} · {hive.agents.filter(a => a.status === 'completed').length} completed
                      </p>
                    </div>
                    <div className="flex gap-2">
                      {hive.status === 'running' && (
                        <button
                          onClick={() => cancel(hive.id)}
                          className="flex items-center gap-2 rounded-md border border-red-500 px-3 py-1.5 text-xs text-red-600 hover:bg-red-50"
                        >
                          <Square size={12} />
                          Cancel
                        </button>
                      )}
                      {hive.status !== 'running' && hive.status !== 'completed' && !hive.resumed_to && (
                        <button
                          onClick={() => resume(hive.id)}
                          className="flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-xs hover:bg-secondary"
                        >
                          <Play size={12} />
                          Resume
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="space-y-2">
                    {hive.agents.map(agent => (
                      <div key={agent.id} className="flex items-start gap-3 rounded-lg border border-border p-3">
                        <div className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                          agent.status === 'completed' ? 'bg-emerald-100 text-emerald-600' :
                          agent.status === 'running' ? 'bg-blue-100 text-blue-600' :
                          agent.status === 'failed' ? 'bg-red-100 text-red-600' :
                          'bg-gray-100 text-gray-600'
                        }`}>
                          {agent.persona[0]}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-medium">{agent.persona}</p>
                            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs ${
                              agent.status === 'completed' ? 'bg-emerald-100 text-emerald-800' :
                              agent.status === 'running' ? 'bg-blue-100 text-blue-800' :
                              agent.status === 'failed' ? 'bg-red-100 text-red-800' :
                              'bg-gray-100 text-gray-800'
                            }`}>
                              {agent.status}
                            </span>
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground truncate">{agent.task}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Personas Tab */}
      {activeTab === 'personas' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Agent Personas</h4>
            <p className="text-xs text-muted-foreground mb-4">
              Personas define the role and behavior of each sub-agent in a Hive. Choose the right persona for each task to optimize collaboration.
            </p>

            <div className="space-y-4">
              {personas.map((persona, index) => (
                <div key={index} className="rounded-lg border border-border p-4">
                  <div className="flex items-start gap-4">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-purple-600 text-lg font-bold text-white">
                      {persona[0]}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <h5 className="text-sm font-semibold">{persona}</h5>
                        <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">
                          Default
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{personaDescriptions[persona] || 'Specialized agent role for specific tasks'}</p>
                      <div className="mt-3 flex gap-2">
                        <button className="text-xs text-blue-600 hover:text-blue-700 underline">
                          View capabilities
                        </button>
                        <button className="text-xs text-muted-foreground hover:text-foreground underline">
                          Customize
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Create Custom Persona</h4>
            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium block mb-1">Persona Name</label>
                <input
                  type="text"
                  placeholder="e.g., CODE_REVIEWER"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">Description</label>
                <textarea
                  rows={3}
                  placeholder="Describe the persona's role and capabilities..."
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                />
              </div>
              <button className="rounded-md bg-foreground px-4 py-2 text-sm text-background">
                Add Persona
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Settings Tab */}
      {activeTab === 'settings' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Hive Runtime Configuration</h4>
            <div className="space-y-4">
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Auto-start Hive agents on server boot</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Enable agent collaboration via blackboard</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked={false} className="rounded border-border" />
                <span className="text-sm">Log all agent communications</span>
              </label>
              <label className="flex items-center gap-3">
                <input type="checkbox" defaultChecked className="rounded border-border" />
                <span className="text-sm">Allow agents to spawn sub-agents</span>
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Resource Limits</h4>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium block mb-1">Max concurrent agents</label>
                <input
                  type="number"
                  defaultValue={10}
                  min="1"
                  max="50"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">Agent timeout (seconds)</label>
                <input
                  type="number"
                  defaultValue={300}
                  min="30"
                  max="3600"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">Max hive duration (minutes)</label>
                <input
                  type="number"
                  defaultValue={60}
                  min="5"
                  max="480"
                  className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                />
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Agent Behavior</h4>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium block mb-1">Default collaboration model</label>
                <select className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm">
                  <option value="blackboard">Blackboard (shared memory)</option>
                  <option value="message">Message passing</option>
                  <option value="hybrid">Hybrid approach</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-medium block mb-1">Task assignment strategy</label>
                <select className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm">
                  <option value="manual">Manual assignment</option>
                  <option value="auto">Automatic based on persona</option>
                  <option value="dynamic">Dynamic reassignment</option>
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
