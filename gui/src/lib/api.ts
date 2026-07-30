const BASE = '/api'

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json', ...opts.headers as Record<string, string> },
    ...opts,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail || `Request failed: ${res.status}`)
  }
  return res.json()
}

export interface SessionDTO {
  id: string
  title: string
  updated_at: number
}

export interface FileItemDTO {
  name: string
  type: 'file' | 'directory'
  path: string
  size?: number
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  tool_calls?: { name: string; status: string; summary?: string }[]
  work_events?: Record<string, unknown>[]
}

export interface InventoryItem {
  name?: string
  id?: string
  description?: string
  enabled?: boolean
  available?: boolean
  active?: boolean
  status?: string
  [key: string]: unknown
}

export const api = {
  health: () => request<{ status: string }>('/health'),
  probePort: (port: string) => request<{ port: number; address: string; status: string }>('/ports/probe', { method: 'POST', body: JSON.stringify({ port }) }),

  state: () => request<Record<string, unknown>>('/state'),
  version: () => request<{ version?: string; service?: string }>('/version'),
  providers: () => request<{ providers: InventoryItem[]; runtime?: { provider?: string; model?: string } }>('/providers'),
  addCustomProvider: (value: { name: string; id?: string; connection_type: 'api_key' | 'local'; model: string; endpoint: string; api_key?: string }) =>
    request<{ status: string; id: string; name: string }>('/providers/custom', { method: 'POST', body: JSON.stringify(value) }),
  startProviderOAuthLogin: (provider: string) => request<OAuthLoginRun>(`/providers/${encodeURIComponent(provider)}/oauth/login`, { method: 'POST' }),
  getProviderOAuthLogin: (runId: string) => request<OAuthLoginRun>(`/providers/oauth/login/${encodeURIComponent(runId)}`),
  submitProviderOAuthCode: (runId: string, code: string) => request<OAuthLoginRun>(`/providers/oauth/login/${encodeURIComponent(runId)}/code`, { method: 'POST', body: JSON.stringify({ code }) }),
  cancelProviderOAuthLogin: (runId: string) => request<OAuthLoginRun>(`/providers/oauth/login/${encodeURIComponent(runId)}`, { method: 'DELETE' }),
  disconnectProviderOAuthAccount: (provider: string) => request<{ status: string }>(`/providers/${encodeURIComponent(provider)}/oauth/account`, { method: 'DELETE' }),
  addProviderProfile: (provider: string, value: { name: string; model: string; endpoint: string; api_key?: string }) =>
    request<{ status: string }>(`/providers/${encodeURIComponent(provider)}/profiles`, { method: 'POST', body: JSON.stringify(value) }),
  updateProviderProfile: (provider: string, profile: string, value: { name?: string; model?: string; endpoint?: string; api_key?: string }) =>
    request<{ status: string }>(`/providers/${encodeURIComponent(provider)}/profiles/${encodeURIComponent(profile)}`, { method: 'PATCH', body: JSON.stringify(value) }),
  deleteProviderProfile: (provider: string, profile: string) =>
    request<{ status: string }>(`/providers/${encodeURIComponent(provider)}/profiles/${encodeURIComponent(profile)}`, { method: 'DELETE' }),
  setDefaultProviderProfile: (provider: string, profile: string) =>
    request<{ status: string }>(`/providers/${encodeURIComponent(provider)}/profiles/${encodeURIComponent(profile)}/default`, { method: 'POST' }),
  skills: () => request<{ skills: InventoryItem[] }>('/skills'),
  tools: () => request<{ tools: InventoryItem[] }>('/tools'),
  plugins: () => request<{ plugins: InventoryItem[] }>('/plugins'),
  mcp: () => request<{ mcp: InventoryItem[] }>('/mcp'),
  createMcp: (value: { name: string; command: string; args: string[]; description?: string; active?: boolean; env?: Record<string, string> }) =>
    request<{ status: string; id: string }>('/mcp', { method: 'POST', body: JSON.stringify(value) }),
  deleteMcp: (name: string) => request<{ status: string }>(`/mcp/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  gateways: () => request<{ gateways: InventoryItem[] }>('/gateways'),
  agents: () => request<{ agents: InventoryItem[] }>('/agents'),
  hives: () => request<{ enabled: boolean; personas: string[]; hives: HiveItem[] }>('/hives'),
  createHive: (agents: Array<{ task: string; persona: string }>) => request<{ status: string; hive: HiveItem }>('/hives', { method: 'POST', body: JSON.stringify({ agents }) }),
  cancelHive: (id: string) => request<{ status: string }>(`/hives/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  features: () => request<{ features: Record<string, unknown> }>('/features'),
  evolution: () => request<{ enabled: boolean; version: string; lifecycle: InventoryItem[]; forges: InventoryItem[] }>('/evolution'),
  voiceStatus: () => request<{ running: boolean; mode: string; phase: string; started_at?: number; transcript_preview?: string; reply_preview?: string }>('/voice/status'),
  startVoice: (mode: 'auto' | 'manual' | 'text' = 'auto') => request<{ running: boolean; mode: string; phase: string }>('/voice/start', { method: 'POST', body: JSON.stringify({ mode }) }),
  stopVoice: () => request<{ running: boolean; mode: string; phase: string }>('/voice/stop', { method: 'POST' }),
  billing: () => request<{ status: string; message?: string; tier?: string; usage?: Record<string, unknown>; limits?: Record<string, unknown> }>('/billing/status'),
  cronJobs: () => request<{ jobs: InventoryItem[]; status?: string; message?: string }>('/cron/jobs'),
  createCronJob: (value: { name: string; prompt: string; interval_minutes: number; enabled?: boolean }) => request<{ status: string; job: InventoryItem }>('/cron/jobs', { method: 'POST', body: JSON.stringify(value) }),
  updateCronJob: (id: string, value: { enabled?: boolean; interval_minutes?: number }) => request<{ status: string; job: InventoryItem }>(`/cron/jobs/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(value) }),
  runCronJob: (id: string) => request<{ status: string }>(`/cron/jobs/${encodeURIComponent(id)}/run`, { method: 'POST' }),
  deleteCronJob: (id: string) => request<{ status: string }>(`/cron/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  manage: (type: string, name: string, action: 'enable' | 'disable' | 'reload' | 'set' | 'model', value?: unknown) =>
    request<{ status: string; enabled?: boolean; active?: boolean; model?: string }>('/manage', { method: 'POST', body: JSON.stringify({ type, name, action, value }) }),
  setModel: (model: string, sessionId?: string) => request<{ status: string; model: string }>('/model', { method: 'POST', body: JSON.stringify({ model, ...(sessionId ? { session_id: sessionId } : {}) }) }),
  savedModels: () => request<{ models: Array<{ model: string; provider: string; label: string }> }>('/models/saved'),
  setProvider: (provider: string) => request<{ status: string; provider: string }>('/provider', { method: 'POST', body: JSON.stringify({ provider }) }),
  setAgent: (agent: string) => request<{ status: string; agent: string }>('/agent', { method: 'POST', body: JSON.stringify({ agent }) }),
  setGoal: (goal: string) => request<{ status: string; goal: string }>('/goal', { method: 'POST', body: JSON.stringify({ goal }) }),
  setPermissions: (mode: string, sessionId?: string) => request<{ status: string; mode: string }>('/mode', { method: 'POST', body: JSON.stringify({ mode, ...(sessionId ? { session_id: sessionId } : {}) }) }),
  setSandbox: (tier: string, root?: string) => request<{ status: string; tier: string; root: string }>('/sandbox', { method: 'POST', body: JSON.stringify({ tier, ...(root !== undefined ? { root } : {}) }) }),

  listSessions: () => request<SessionDTO[]>('/sessions'),

  createSession: () => request<{ id: string; title: string }>('/sessions/new', { method: 'POST' }),

  loadSession: (id: string) =>
    request<{ status: string; id: string; history: ChatMessage[] }>('/sessions/load', {
      method: 'POST',
      body: JSON.stringify({ id }),
    }),

  deleteSession: (id: string) =>
    request<{ status: string }>(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  renameSession: (id: string, title: string) =>
    request<{ status: string }>('/sessions/rename', {
      method: 'POST',
      body: JSON.stringify({ id, title }),
    }),

  chat: (sessionId: string, prompt: string, opts?: { stream?: boolean; provider?: string; model?: string }) =>
    request<{ response: string } | void>('/chat', {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        prompt,
        stream: opts?.stream ?? false,
        provider: opts?.provider,
        model: opts?.model,
      }),
    }),

  chatStream: (sessionId: string, prompt: string, onData: (text: string) => void, onDone: () => void, onError: (err: string) => void, opts?: { provider?: string; model?: string }): AbortController => {
    const ctrl = new AbortController()
    fetch(`${BASE}/chat`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        prompt,
        stream: true,
        provider: opts?.provider,
        model: opts?.model,
      }),
      signal: ctrl.signal,
    }).then(async res => {
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }))
        onError(body.detail || `Request failed: ${res.status}`)
        return
      }
      const reader = res.body?.getReader()
      if (!reader) { onError('No response body'); return }
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            onData(data)
          } else if (line.startsWith('event: ')) {
            const event = line.slice(7).trim()
            if (event === 'error') {
              onError('Stream error')
            }
          }
        }
      }
      onDone()
    }).catch(err => {
      if (err.name !== 'AbortError') onError(err.message)
    })
    return ctrl
  },

  cancelChat: (sessionId: string) =>
    request<{ status: string }>(`/chat/${encodeURIComponent(sessionId)}/cancel`, { method: 'POST' }),

  fileTree: (path?: string) => request<{ path: string; items: FileItemDTO[] }>(`/files/tree${path ? `?path=${encodeURIComponent(path)}` : ''}`),

  readFile: (path: string) => request<{ path: string; content: string }>(`/files/read?path=${encodeURIComponent(path)}`),

  writeFile: (path: string, content: string) =>
    request<{ status: string }>('/files/write', { method: 'POST', body: JSON.stringify({ path, content }) }),

  createFile: (path: string, type: 'file' | 'folder') =>
    request<{ status: string }>('/files/create', { method: 'POST', body: JSON.stringify({ path, type }) }),

  renameFile: (path: string, name: string) =>
    request<{ status: string; path: string }>('/files/rename', { method: 'POST', body: JSON.stringify({ path, name }) }),

  deleteFile: (path: string) =>
    request<{ status: string }>('/files/delete', { method: 'POST', body: JSON.stringify({ path }) }),

  downloadFile: (path: string) => {
    const a = document.createElement('a')
    a.href = `/api/files/read?path=${encodeURIComponent(path)}`
    a.download = path.split('/').pop() || 'file'
    a.click()
  },

  uploadFile: async (path: string, file: File) => {
    const text = await file.text()
    return api.writeFile(path ? `${path}/${file.name}` : file.name, text)
  },

  uploadAttachments: async (files: File[]) => {
    const form = new FormData()
    files.forEach(file => form.append('files', file, file.webkitRelativePath || file.name))
    const res = await fetch(`${BASE}/upload`, { method: 'POST', body: form, credentials: 'include', cache: 'no-store' })
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(body.detail || `Upload failed: ${res.status}`)
    }
    return res.json() as Promise<{ status: string; files: string[] }>
  },

  moveFile: (source: string, dest: string) =>
    request<{ status: string }>('/files/move', { method: 'POST', body: JSON.stringify({ source, dest }) }),

  zipFile: (source: string) =>
    request<{ status: string; path: string }>('/files/zip', { method: 'POST', body: JSON.stringify({ source }) }),

  unzipFile: (source: string) =>
    request<{ status: string; path: string }>('/files/unzip', { method: 'POST', body: JSON.stringify({ source }) }),

  runCommandStream: async (
    command: string,
    onChunk: (text: string, stream: 'stdout' | 'stderr') => void,
    onDone: (result: { status: string; output: string; exit_code?: number }) => void,
    onError: (message: string) => void,
    profile = 'pwsh',
  ) => {
    try {
      const res = await fetch(`${BASE}/work-events/run-command-stream`, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command, profile, session_id: `terminal-${profile}` }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }))
        onError(body.detail || `Request failed: ${res.status}`); return
      }
      const reader = res.body?.getReader()
      if (!reader) { onError('Terminal stream unavailable'); return }
      const decoder = new TextDecoder(); let buffer = ''
      while (true) {
        const { done, value } = await reader.read(); if (done) break
        buffer += decoder.decode(value, { stream: true })
        const records = buffer.split('\n\n'); buffer = records.pop() || ''
        for (const record of records) {
          const line = record.split('\n').find(item => item.startsWith('data: ')); if (!line) continue
          const payload = JSON.parse(line.slice(6)) as Record<string, unknown>
          if (payload.type === 'chunk') onChunk(String(payload.text || ''), payload.stream === 'stderr' ? 'stderr' : 'stdout')
          if (payload.type === 'done') onDone({ status: String(payload.status || 'done'), output: String(payload.output || ''), exit_code: typeof payload.exit_code === 'number' ? payload.exit_code : undefined })
        }
      }
    } catch (error) { onError(error instanceof Error ? error.message : 'Terminal request failed') }
  },
} as const

export interface OAuthLoginRun {
  id: string
  provider: string
  status: 'starting' | 'waiting_for_browser' | 'waiting_for_code' | 'working' | 'connected' | 'failed' | 'cancelled'
  url?: string
  message?: string
}

export interface HiveAgentItem {
  id: string
  task: string
  persona: string
  status: string
  result?: string
}

export interface HiveItem {
  id: string
  status?: string
  agents: HiveAgentItem[]
}
