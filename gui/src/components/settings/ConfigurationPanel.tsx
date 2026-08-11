import { useState, useEffect, type FormEvent } from 'react'
import { CpuIcon, ShieldCheck, MemoryStick as MemoryStickIcon, Zap as ZapIcon, Brain, Clock3, FileJson } from 'lucide-react'
import { api } from '../../lib/api'

export function ConfigurationPanel({ state, onSaved }: { state: Record<string, unknown>; onSaved: () => void }) {
  const value = (key: string) => String(state[key] || '')
  const [activeTab, setActiveTab] = useState<'overview' | 'runtime' | 'model' | 'session' | 'advanced' | 'files'>('overview')
  const [model, setModel] = useState('')
  const [provider, setProvider] = useState('')
  const [agent, setAgent] = useState('')
  const [goal, setGoal] = useState('')
  const [mode, setMode] = useState('auto')
  const [sandbox, setSandbox] = useState('no_sandbox')
  const [temperature, setTemperature] = useState('0.7')
  const [maxTokens, setMaxTokens] = useState('4096')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [thinking, setThinking] = useState(true)
  const [additionalDirs, setAdditionalDirs] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  
  // Config files state
  const [configFiles, setConfigFiles] = useState<Array<{ name: string; path: string; size: number; type: string }>>([])
  const [selectedFile, setSelectedFile] = useState<{ name: string; path: string; content: string; size: number } | null>(null)
  const [loadingFiles, setLoadingFiles] = useState(false)
  const [loadingContent, setLoadingContent] = useState(false)

  useEffect(() => {
    setModel(value('model') === 'auto' ? '' : value('model'))
    setProvider(value('provider') === 'auto' ? '' : value('provider'))
    setAgent(value('agent'))
    setGoal(value('goal'))
    setMode(value('mode') || 'auto')
    setSandbox(value('sandbox_tier') || 'no_sandbox')
    setTemperature(value('temperature') || '0.7')
    setMaxTokens(value('max_tokens') || '4096')
    setSystemPrompt(value('system_prompt') || '')
    setThinking(value('thinking') === 'true')
    setAdditionalDirs(value('additional_dirs') || '')
  }, [state])

  const loadConfigFiles = async () => {
    setLoadingFiles(true)
    try {
      const response = await api.configFiles()
      setConfigFiles(response.files)
    } catch (error) {
      console.error('Failed to load config files:', error)
    } finally {
      setLoadingFiles(false)
    }
  }

  const loadFileContent = async (path: string) => {
    setLoadingContent(true)
    try {
      const response = await api.configFile(path)
      const fileName = path.split(/[/\\]/).pop() || path
      setSelectedFile({ ...response, name: fileName })
    } catch (error) {
      console.error('Failed to load file content:', error)
    } finally {
      setLoadingContent(false)
    }
  }

  useEffect(() => {
    if (activeTab === 'files' && configFiles.length === 0) {
      loadConfigFiles()
    }
  }, [activeTab])

  const save = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setMessage('')
    try {
      await Promise.all([
        api.setModel(model || 'auto'), api.setProvider(provider || 'auto'), api.setAgent(agent), api.setGoal(goal), api.setPermissions(mode), api.setSandbox(sandbox), api.setThinking(thinking),
      ])
      setMessage('Runtime configuration saved.')
      onSaved()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Nexus could not save the runtime configuration.')
    } finally { setSaving(false) }
  }

  return (
    <form className="space-y-6" onSubmit={save}>
      <div>
        <h3 className="text-lg font-semibold">Configuration</h3>
        <p className="mt-1 text-sm text-muted-foreground">Configure Nexus runtime, model settings, and advanced options.</p>
      </div>
      
      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-border">
        {[
          { id: 'overview', label: 'Overview' },
          { id: 'runtime', label: 'Runtime' },
          { id: 'model', label: 'Model' },
          { id: 'session', label: 'Session' },
          { id: 'advanced', label: 'Advanced' },
          { id: 'files', label: 'Config Files' },
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
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <CpuIcon size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Current Model</p>
              </div>
              <p className="mt-2 text-lg font-semibold">{model || 'Automatic'}</p>
              <p className="mt-1 text-xs text-muted-foreground">{provider || 'Auto provider'}</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <ShieldCheck size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Sandbox</p>
              </div>
              <p className="mt-2 text-lg font-semibold capitalize">{sandbox}</p>
              <p className="mt-1 text-xs text-muted-foreground">Security tier</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <MemoryStickIcon size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Max Tokens</p>
              </div>
              <p className="mt-2 text-lg font-semibold">{maxTokens}</p>
              <p className="mt-1 text-xs text-muted-foreground">Context window</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-center gap-2">
                <ZapIcon size={18} className="text-muted-foreground" />
                <p className="text-xs font-medium text-muted-foreground">Temperature</p>
              </div>
              <p className="mt-2 text-lg font-semibold">{temperature}</p>
              <p className="mt-1 text-xs text-muted-foreground">Creativity level</p>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-6">
            <h4 className="text-sm font-semibold mb-4">Quick Settings</h4>
            <div className="grid gap-4 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => setActiveTab('runtime')}
                className="rounded-lg border border-border p-4 text-left hover:bg-secondary transition-colors"
              >
                <div className="flex items-center gap-2 mb-2">
                  <CpuIcon size={16} className="text-muted-foreground" />
                  <span className="text-sm font-medium">Runtime Settings</span>
                </div>
                <p className="text-xs text-muted-foreground">Configure model, provider, and agent settings</p>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('model')}
                className="rounded-lg border border-border p-4 text-left hover:bg-secondary transition-colors"
              >
                <div className="flex items-center gap-2 mb-2">
                  <Brain size={16} className="text-muted-foreground" />
                  <span className="text-sm font-medium">Model Parameters</span>
                </div>
                <p className="text-xs text-muted-foreground">Adjust temperature, tokens, and system prompt</p>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('session')}
                className="rounded-lg border border-border p-4 text-left hover:bg-secondary transition-colors"
              >
                <div className="flex items-center gap-2 mb-2">
                  <Clock3 size={16} className="text-muted-foreground" />
                  <span className="text-sm font-medium">Session Settings</span>
                </div>
                <p className="text-xs text-muted-foreground">Manage directories and session persistence</p>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('files')}
                className="rounded-lg border border-border p-4 text-left hover:bg-secondary transition-colors"
              >
                <div className="flex items-center gap-2 mb-2">
                  <FileJson size={16} className="text-muted-foreground" />
                  <span className="text-sm font-medium">Config Files</span>
                </div>
                <p className="text-xs text-muted-foreground">View and edit configuration files</p>
              </button>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'runtime' && (
        <div className="space-y-4">
          <div className="grid gap-4 rounded-lg border border-border bg-card p-6 md:grid-cols-2">
            <label className="grid gap-1.5 text-sm font-medium">Model<input value={model} onChange={event => setModel(event.target.value)} placeholder="Automatic" className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring" /></label>
            <label className="grid gap-1.5 text-sm font-medium">Provider<input value={provider} onChange={event => setProvider(event.target.value)} placeholder="Automatic" className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring" /></label>
            <label className="grid gap-1.5 text-sm font-medium">Agent<input value={agent} onChange={event => setAgent(event.target.value)} placeholder="Default agent" className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring" /></label>
            <label className="grid gap-1.5 text-sm font-medium">Active goal<input value={goal} onChange={event => setGoal(event.target.value)} placeholder="No active goal" className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring" /></label>
          </div>
          <div className="grid gap-4 rounded-lg border border-border bg-card p-6 md:grid-cols-2">
            <label className="grid gap-1.5 text-sm font-medium">Permission mode<select value={mode} onChange={event => setMode(event.target.value)} className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring"><option value="auto">Automatic</option><option value="ask">Ask every time</option><option value="allowlist">Allowlist only</option><option value="all">Allow all</option></select></label>
            <label className="grid gap-1.5 text-sm font-medium">Sandbox tier<select value={sandbox} onChange={event => setSandbox(event.target.value)} className="h-10 rounded-md border border-border bg-background px-3 text-sm font-normal outline-none focus:border-ring"><option value="no_sandbox">No Sandbox</option><option value="normal">Sandbox</option><option value="docker">Advanced Sandbox</option></select></label>
          </div>
        </div>
      )}

      {activeTab === 'model' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm">
            <p className="font-medium">Model parameter persistence is not exposed by this backend</p>
            <p className="mt-1 text-muted-foreground">Temperature, max tokens, and custom system prompts are shown by the legacy UI but cannot be saved through the connected runtime yet.</p>
          </div>
          <div className="grid gap-4 rounded-lg border border-border bg-card p-6 md:grid-cols-2">
            <label className="grid gap-1.5 text-sm font-medium">Temperature<input disabled type="number" value={temperature} className="h-10 rounded-md border border-border bg-secondary px-3 text-sm font-normal opacity-70" /></label>
            <label className="grid gap-1.5 text-sm font-medium">Max tokens<input disabled type="number" value={maxTokens} className="h-10 rounded-md border border-border bg-secondary px-3 text-sm font-normal opacity-70" /></label>
          </div>
          <div className="rounded-lg border border-border bg-card p-6">
            <label className="grid gap-1.5 text-sm font-medium">System prompt<textarea disabled value={systemPrompt} placeholder="Not available through the current runtime API" rows={4} className="w-full rounded-md border border-border bg-secondary px-3 py-2 text-sm font-normal opacity-70 resize-none" /></label>
          </div>
          <div className="rounded-lg border border-border bg-card p-6">
            <label className="flex items-center gap-3">
              <input type="checkbox" checked={thinking} onChange={event => setThinking(event.target.checked)} className="rounded border-border" />
              <span className="text-sm font-medium">Enable thinking mode</span>
            </label>
            <p className="mt-1 text-xs text-muted-foreground">Allow the model to use chain-of-thought reasoning for complex tasks.</p>
          </div>
        </div>
      )}

      {activeTab === 'session' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <label className="grid gap-1.5 text-sm font-medium">Additional directories<input disabled value={additionalDirs} placeholder="Not available through the current runtime API" className="h-10 rounded-md border border-border bg-secondary px-3 text-sm font-normal opacity-70" /></label>
            <p className="mt-1 text-xs text-muted-foreground">This control is disabled until the backend exposes a safe persistence endpoint.</p>
          </div>
          <div className="rounded-lg border border-border bg-card p-6">
            <p className="text-sm font-medium">Session persistence</p>
            <p className="mt-1 text-sm text-muted-foreground">Session history is managed by the Memory & context page and the active Nexus runtime. The current configuration API does not expose separate save-history, tool-output, or auto-resume switches.</p>
          </div>
        </div>
      )}

      {activeTab === 'advanced' && (
        <div className="rounded-lg border border-border bg-card p-6">
          <p className="text-sm font-medium">Advanced runtime controls</p>
          <p className="mt-1 text-sm text-muted-foreground">Parallel execution, response caching, streaming, logging, and developer flags are not exposed by the current configuration API. They belong here only once Nexus can validate and persist them.</p>
        </div>
      )}

      {activeTab === 'files' && (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-6">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium">Configuration Files</p>
                <p className="mt-1 text-xs text-muted-foreground">View and manage all .json, .yaml, .yml, and .jsnol configuration files.</p>
              </div>
              <button type="button" onClick={loadConfigFiles} disabled={loadingFiles} className="rounded-md bg-foreground px-3 py-1.5 text-xs font-medium text-background disabled:opacity-50">
                {loadingFiles ? 'Loading…' : 'Refresh'}
              </button>
            </div>
          </div>
          
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-lg border border-border bg-card">
              <div className="border-b border-border px-4 py-3">
                <p className="text-sm font-medium">Files</p>
              </div>
              <div className="max-h-96 overflow-y-auto">
                {loadingFiles ? (
                  <p className="px-4 py-8 text-sm text-muted-foreground">Loading files…</p>
                ) : configFiles.length === 0 ? (
                  <p className="px-4 py-8 text-sm text-muted-foreground">No config files found.</p>
                ) : (
                  <div className="divide-y divide-border">
                    {configFiles.map((file) => (
                      <button
                        key={file.path}
                        type="button"
                        onClick={() => loadFileContent(file.path)}
                        className={`w-full px-4 py-3 text-left transition hover:bg-secondary ${selectedFile?.path === file.path ? 'bg-secondary' : ''}`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium truncate">{file.name}</p>
                            <p className="mt-0.5 text-xs text-muted-foreground truncate">{file.path}</p>
                          </div>
                          <span className="shrink-0 text-xs text-muted-foreground">{file.type.toUpperCase()}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            
            <div className="rounded-lg border border-border bg-card">
              <div className="border-b border-border px-4 py-3">
                <p className="text-sm font-medium">File Content</p>
              </div>
              <div className="max-h-96 overflow-y-auto">
                {loadingContent ? (
                  <p className="px-4 py-8 text-sm text-muted-foreground">Loading content…</p>
                ) : !selectedFile ? (
                  <p className="px-4 py-8 text-sm text-muted-foreground">Select a file to view its content.</p>
                ) : (
                  <div className="px-4 py-3">
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <p className="text-sm font-medium truncate">{selectedFile.name}</p>
                      <p className="text-xs text-muted-foreground">{(selectedFile.size / 1024).toFixed(1)} KB</p>
                    </div>
                    <pre className="rounded-md bg-secondary p-3 text-xs text-foreground overflow-x-auto whitespace-pre-wrap break-words">
                      {selectedFile.content}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between gap-4"><p className={`text-sm ${message === 'Runtime configuration saved.' ? 'text-emerald-700' : 'text-destructive'}`} role="status">{message}</p><button disabled={saving} className="rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background disabled:opacity-50">{saving ? 'Saving…' : 'Save configuration'}</button></div>
    </form>
  )
}
