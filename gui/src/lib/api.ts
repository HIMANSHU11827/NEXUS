const BASE = '/api'

export const DEFAULT_REQUEST_TIMEOUT_MS = 12000

export class TimeoutError extends Error {
  constructor(message = 'The request timed out. Please try again.') {
    super(message)
    this.name = 'TimeoutError'
  }
}

export interface RequestOptions extends RequestInit {
  timeoutMs?: number
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS, signal: externalSignal, ...rest } = opts
  const ctrl = new AbortController()
  let timedOut = false
  const onExternalAbort = () => ctrl.abort()
  if (externalSignal) {
    if (externalSignal.aborted) ctrl.abort()
    else externalSignal.addEventListener('abort', onExternalAbort)
  }
  let timer: ReturnType<typeof setTimeout> | undefined
  if (timeoutMs > 0) {
    timer = setTimeout(() => {
      timedOut = true
      ctrl.abort()
    }, timeoutMs)
  }
  try {
    const res = await fetch(`${BASE}${path}`, {
      credentials: 'include',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', ...rest.headers as Record<string, string> },
      ...rest,
      signal: ctrl.signal,
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }))
      const detail = body?.detail || body?.message || body?.error?.message || body?.error || res.statusText
      throw new Error(typeof detail === 'string' ? detail : `Request failed: ${res.status}`)
    }
    try {
      return await res.json()
    } catch {
      throw new Error('The server returned an invalid response.')
    }
  } catch (err) {
    if (timedOut) throw new TimeoutError()
    throw err
  } finally {
    if (timer !== undefined) clearTimeout(timer)
    externalSignal?.removeEventListener('abort', onExternalAbort)
  }
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
  turn_id?: string
  tool_calls?: { name: string; status: string; summary?: string }[]
  work_events?: Record<string, unknown>[]
}

export interface CheckpointItemDTO {
  checkpoint_id: string
  session_id: string
  run_id: string
  turn_id: string
  created_at: number
  file_count: number
  size_bytes: number
}

export interface RestoreCheckpointResult {
  checkpoint_id: string
  session_id: string
  ok: boolean
  restored: number
  removed: number
  failed: number
  failures: Array<{ path: string; error: string }>
  messages: string[]
  workspace_root: string
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

export interface CommandDTO {
  name: string
  description: string
  category: string
  args: Record<string, string>
  aliases: string[]
  execution?: 'shared' | 'client' | string
}

export interface CommandResultDTO {
  status: string
  output?: string
  formatted?: string
  content_type?: string
  data?: Record<string, unknown>
  error?: string
}

export interface RuntimeProviderStatus {
  model?: string
  provider?: string
  health?: string
  provider_status?: {
    configured?: boolean
    reachable?: boolean | null
    endpoint?: string
    reason?: string
  }
  provider_diagnostics?: ProviderDiagnostics
}

export interface ProviderDiagnostics {
  active?: { provider?: string; profile?: string; model?: string }
  attempts?: Array<{
    provider_id?: string
    profile?: string
    model?: string
    status?: string
    failure_class?: string
    strategy?: string
    reason?: string
    duration_ms?: number
    timestamp?: number
  }>
  fallback_attempts?: number
  cooldowns?: Array<{
    provider?: string
    profile?: string
    active?: boolean
    enabled?: boolean
    cooldown_seconds?: number
    reason?: string
    error_count?: number
  }>
  last_failure?: {
    provider?: string
    profile?: string
    model?: string
    failure_class?: string
    strategy?: string
    reason?: string
    timestamp?: number
  } | null
}

export interface WorkspaceValidation {
  valid: boolean
  reason?: string
  path?: string
  exists?: boolean
  is_dir?: boolean
  readable?: boolean
  writable?: boolean
}

export interface AdditionalDirInfo {
  path: string
  name: string
  available: boolean
  readable: boolean
  writable: boolean
  access_mode: string
  index_status: string
  file_count: number
  last_scanned?: number | null
}

export interface WorkspaceSummary {
  status?: string
  root: string
  workspace_name: string
  state: string
  exists: boolean
  readable: boolean
  writable: boolean
  root_protection: boolean
  read_permission: string
  write_permission: string
  configured_root: string
  is_repo: boolean
  git_branch?: string
  last_scanned?: number | null
  file_count: number
  folder_count: number
  indexed_file_count: number
  indexed_text_size: number
  additional_directory_count: number
  languages: string[]
  project_type: string
  project_name: string
  additional_dirs: AdditionalDirInfo[]
  session_count: number
  index: WorkspaceIndex
  health: HealthCheck[]
}

export interface WorkspaceGit {
  status: string
  available: boolean
  is_repo: boolean
  root?: string
  branch?: string
  upstream?: string
  changed_files?: number
  staged_files?: number
  untracked_files?: number
  last_commit?: string
}

export interface WorkspaceStats {
  status: string
  stats: {
    files: number
    folders: number
    indexed_files: number
    ignored_files: number
    failed_files: number
    source_files: number
    documentation_files: number
    binary_files: number
    total_size: number
    indexed_text_size: number
    languages: Record<string, number>
    calculated_at: number
  }
}

export interface WorkspaceProject {
  status: string
  project: {
    name: string
    type: string
    languages: string[]
    frameworks: string[]
    package_manager?: string | null
    build_command?: string | null
    dev_command?: string | null
    test_command?: string | null
    lint_command?: string | null
    format_command?: string | null
    entry_points: string[]
    manifests: string[]
    lock_files: string[]
    config_files: string[]
    documentation?: string[]
    detected_at: number
  }
}

export interface WorkspaceIndex {
  status: string
  indexed_files: number
  total_chunks: number
  index_storage_size: number
  last_full_scan?: string | number | null
  last_incremental_scan?: string | number | null
  current_file?: string
  recent_errors: string[]
}

export interface IgnoreRule {
  pattern: string
  source: string
  kind: string
  negated: boolean
}

export interface ProtectedPath {
  pattern: string
  reason: string
  policy: string
  scope: string
  mandatory: boolean
  exists: boolean
}

export interface HealthCheck {
  name: string
  status: 'healthy' | 'warning' | 'failed' | 'unsupported' | 'not_checked'
  detail: string
}

export interface WorkspaceActivity {
  status: string
  events: Array<{
    timestamp: number
    event_type: string
    description: string
    status: string
    details?: unknown
  }>
}

export interface WorkspaceStorage {
  status: string
  session_count: number
  session_storage_size: number
  cache_size: number
  index_size: number
  temp_size: number
  work_event_count: number
}

export interface WorkspaceInstructions {
  status: string
  instructions: string
  active: boolean
  updated_at?: number | null
}

export interface WorkspaceMemory {
  status: string
  enabled: boolean
  entry_count: number
  storage_size: number
  last_update?: number | null
  last_retrieval?: number | null
  scope: string
  unavailable_reason?: string
}

export type WorkspaceAccessMode = 'read_only' | 'read_write' | 'index_only' | 'disabled'

// ── Safety settings types ─────────────────────────────────────────────────────
export type SafetyPermissionMode = 'automatic' | 'ask' | 'read_only' | 'restricted' | 'trusted' | 'custom' | 'deny_all'
export type SafetySandboxMode = 'no_tools' | 'read_only' | 'workspace' | 'restricted' | 'isolated_temp' | 'custom' | 'no_sandbox'
export type SafetyPolicy = 'allow' | 'ask' | 'deny' | 'read_only' | 'session'

export interface SafetyModeInfo {
  id: string
  label: string
  description: string
  [key: string]: unknown
}

export interface SafetyProtectedPath {
  path: string
  reason: string
  source: string
  exists: boolean
  read: SafetyPolicy
  write: SafetyPolicy
  delete: SafetyPolicy
  mandatory: boolean
  [key: string]: unknown
}

export interface SafetyTempPermission {
  id: string
  action: string
  scope: string
  reason: string
  created_at: number
  expires_at: number
  permanent?: boolean
  [key: string]: unknown
}

export interface SafetyApproval {
  id: string
  action: string
  target: string
  granted_at: number
  expires_at?: number
  granted_by: string
  revocable?: boolean
  [key: string]: unknown
}

export interface SafetyEvent {
  id: string
  time: number
  event_type: string
  action: string
  risk: string
  decision: string
  [key: string]: unknown
}

export interface SafetyDiagnostic {
  name: string
  status: 'healthy' | 'ok' | 'warning' | 'failed' | 'error'
  detail?: string
  action?: string
}

export interface SafetySummary {
  workspace: string
  workspace_exists: boolean
  permission_mode: SafetyPermissionMode
  permission_label: string
  sandbox_mode: SafetySandboxMode
  sandbox_label: string
  root_protection: boolean
  command_protection: boolean
  file_protection: boolean
  network_policy: string
  network_policy_label: string
  browser_policy: string
  mcp_policy: string
  destructive_policy: string
  active_temp_permissions: number
  pending_approvals: number
  blocked_action_count: number
  last_safety_event: SafetyEvent | null
  backend_status: string
  protected_path_count: number
  redaction_active: boolean
  secret_counts: { protected: number; blocked: number; redacted: number; pending: number; last_scan: number | null }
  last_saved: number | null
}

export interface SafetySettings {
  [key: string]: unknown
}

export interface SafetyMeta {
  permission_modes: SafetyModeInfo[]
  sandbox_modes: SafetyModeInfo[]
  command_categories: Array<{ id: string; label: string; description?: string; risk: string }>
  file_policy_categories: Array<{ id: string; label: string; description?: string }>
  filesystem_options: Array<{ id: string; label: string; description?: string }>
  secret_protection_options: Array<{ id: string; label: string; description?: string }>
  network_policies: Array<{ id: string; label: string; description?: string }>
  browser_options: Array<{ id: string; label: string; description?: string }>
  mcp_options: Array<{ id: string; label: string; description?: string }>
  package_options: Array<{ id: string; label: string; description?: string }>
  package_managers: Array<{ id: string; label: string; description?: string }>
  process_options: Array<{ id: string; label: string; description?: string }>
  destructive_actions: Array<{ id: string; label: string; description?: string; risk: string }>
  checkpoint_options: Array<{ id: string; label: string; description?: string }>
  default_protected_paths: Array<{ pattern: string; reason: string; source: string; mandatory: boolean; read_policy: string; write_policy: string; delete_policy: string }>
  presets: Array<{ id: string; label: string; description: string; recommended?: boolean; [key: string]: unknown }>
}

export interface SafetyPreset {
  id: string
  label: string
  description: string
  recommended?: boolean
  [key: string]: unknown
}

export interface SafetySaveResult {
  ok: boolean
  errors?: string[]
  permission_mode?: SafetyPermissionMode
  sandbox_mode?: SafetySandboxMode
  permission_changed?: boolean
  sandbox_changed?: boolean
  workspace?: string
  workspace_unchanged?: boolean
}

export const api = {
  request: <T>(path: string, opts: RequestOptions = {}): Promise<T> => request<T>(path, opts),
  health: () => request<{ status: string }>('/health'),
  status: () => request<RuntimeProviderStatus>('/status'),
  probePort: (port: string) => request<{ port: number; address: string; status: string }>('/ports/probe', { method: 'POST', body: JSON.stringify({ port }) }),

  state: () => request<Record<string, unknown>>('/state'),
  version: () => request<{ version?: string; service?: string }>('/version'),
  providers: () => request<{ providers: InventoryItem[]; runtime?: { provider?: string; profile?: string; model?: string }; diagnostics?: ProviderDiagnostics }>('/providers'),
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
  commands: () => request<{ commands: CommandDTO[] }>('/commands'),
  command: (command: string, args?: string, sessionId?: string) => request<CommandResultDTO>('/command', {
    method: 'POST',
    body: JSON.stringify({ command, args: args || command, ...(sessionId ? { session_id: sessionId } : {}) }),
  }),
  createMcp: (value: { name: string; command: string; args: string[]; description?: string; active?: boolean; env?: Record<string, string>; working_dir?: string }) =>
    request<{ status: string; id: string }>('/mcp', { method: 'POST', body: JSON.stringify(value) }),
  deleteMcp: (name: string) => request<{ status: string }>(`/mcp/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  gateways: () => request<{ gateways: InventoryItem[] }>('/gateways'),
  agents: () => request<{ agents: InventoryItem[] }>('/agents'),
  hives: () => request<{ enabled: boolean; personas: string[]; hives: HiveItem[] }>('/hives'),
  createHive: (agents: Array<{ task: string; persona: string }>) => request<{ status: string; hive: HiveItem }>('/hives', { method: 'POST', body: JSON.stringify({ agents }) }),
  cancelHive: (id: string) => request<{ status: string }>(`/hives/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  resumeHive: (id: string) => request<{ status: string; hive: HiveItem }>(`/hives/${encodeURIComponent(id)}/resume`, { method: 'POST' }),
  features: () => request<{ features: Record<string, unknown> }>('/features'),
  evolution: () => request<{ enabled: boolean; version: string; lifecycle: InventoryItem[]; forges: InventoryItem[] }>('/evolution'),
  configFiles: () => request<{ files: Array<{ name: string; path: string; size: number; type: string }> }>('/config/files'),
  configFile: (path: string) => request<{ path: string; content: string; size: number }>(`/config/file?path=${encodeURIComponent(path)}`),
  billing: () => request<{ status: string; message?: string; tier?: string; usage?: Record<string, unknown>; limits?: Record<string, unknown> }>('/billing/status'),
  cronJobs: () => request<{ jobs: InventoryItem[]; status?: string; message?: string }>('/cron/jobs'),
  createCronJob: (value: { name: string; prompt: string; interval_minutes: number; enabled?: boolean }) => request<{ status: string; job: InventoryItem }>('/cron/jobs', { method: 'POST', body: JSON.stringify(value) }),
  updateCronJob: (id: string, value: { enabled?: boolean; interval_minutes?: number }) => request<{ status: string; job: InventoryItem }>(`/cron/jobs/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(value) }),
  runCronJob: (id: string) => request<{ status: string }>(`/cron/jobs/${encodeURIComponent(id)}/run`, { method: 'POST' }),
  deleteCronJob: (id: string) => request<{ status: string }>(`/cron/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  manage: (type: string, name: string, action: 'enable' | 'disable' | 'reload' | 'set' | 'model', value?: unknown) =>
    request<{ status: string; enabled?: boolean; active?: boolean; model?: string }>('/manage', { method: 'POST', body: JSON.stringify({ type, name, action, value }) }),
  setModel: (model: string, sessionId?: string, provider?: string, profile?: string) => request<{ status: string; model: string; provider?: string; profile?: string }>('/model', { method: 'POST', body: JSON.stringify({ model, ...(sessionId ? { session_id: sessionId } : {}), ...(provider ? { provider } : {}), ...(profile ? { profile } : {}) }) }),
  getModel: () => request<{ status: string; model: string; provider?: string; profile?: string }>('/model'),
  savedModels: () => request<{ models: Array<{ model: string; provider: string; alias?: string; label: string }> }>('/models/saved'),
  setProvider: (provider: string) => request<{ status: string; provider: string }>('/provider', { method: 'POST', body: JSON.stringify({ provider }) }),
  setAgent: (agent: string) => request<{ status: string; agent: string }>('/agent', { method: 'POST', body: JSON.stringify({ agent }) }),
  setGoal: (goal: string) => request<{ status: string; goal: string }>('/goal', { method: 'POST', body: JSON.stringify({ goal }) }),
  setPermissions: (mode: string, sessionId?: string) => request<{ status: string; mode: string }>('/mode', { method: 'POST', body: JSON.stringify({ mode, ...(sessionId ? { session_id: sessionId } : {}) }) }),
  setSandbox: (tier: string, root?: string) => request<{ status: string; tier: string; root: string }>('/sandbox', { method: 'POST', body: JSON.stringify({ tier, ...(root !== undefined ? { root } : {}) }) }),
  setThinking: (enabled: boolean) => request<{ status: string; thinking: boolean }>('/thinking', { method: 'POST', body: JSON.stringify({ enabled }) }),

  safetySummary: () => request<SafetySummary>('/safety/summary'),
  safetySettings: () => request<SafetySettings>('/safety/settings'),
  safetyMeta: () => request<SafetyMeta>('/safety/meta'),
  safetySave: (settings: Record<string, unknown>) => request<SafetySaveResult>('/safety/save', { method: 'POST', body: JSON.stringify(settings) }),
  safetyReset: () => request<SafetySaveResult>('/safety/reset', { method: 'POST', body: JSON.stringify({ confirm: true }) }),
  safetySetPermissionMode: (mode: SafetyPermissionMode) => request<SafetySaveResult>('/safety/permission-mode', { method: 'POST', body: JSON.stringify({ mode }) }),
  safetySetSandboxMode: (mode: SafetySandboxMode) => request<SafetySaveResult>('/safety/sandbox-mode', { method: 'POST', body: JSON.stringify({ mode }) }),
  safetyProtectedPaths: () => request<{ paths: SafetyProtectedPath[]; mandatory: SafetyProtectedPath[] }>('/safety/protected-paths'),
  safetyAddProtectedPath: (value: { path: string; reason?: string; read?: SafetyPolicy; write?: SafetyPolicy; delete?: SafetyPolicy }) =>
    request<{ ok: boolean; errors?: string[] }>('/safety/protected-paths', { method: 'POST', body: JSON.stringify(value) }),
  safetyUpdateProtectedPath: (pattern: string, updates: Record<string, unknown>) =>
    request<{ ok: boolean; errors?: string[] }>('/safety/protected-paths', { method: 'PATCH', body: JSON.stringify({ pattern, ...updates }) }),
  safetyRemoveProtectedPath: (pattern: string) =>
    request<{ ok: boolean; errors?: string[] }>('/safety/protected-paths', { method: 'DELETE', body: JSON.stringify({ pattern }) }),
  safetyTestPath: (path: string) => request<{ ok: boolean; errors?: string[]; result: { path: string; resolved: string; exists: boolean; is_dir: boolean; inside_workspace: boolean; matches_protected: number; matched_patterns: string[] } }>('/safety/protected-paths/test', { method: 'POST', body: JSON.stringify({ path }) }),
  safetyResetProtectedPaths: () => request<{ ok: boolean; errors?: string[] }>('/safety/protected-paths/reset', { method: 'POST', body: JSON.stringify({ confirm: true }) }),
  safetyTempPermissions: () => request<{ permissions: SafetyTempPermission[] }>('/safety/temp-permissions'),
  safetyAddTempPermission: (value: { action: string; scope: string; reason?: string; duration_seconds?: number }) =>
    request<{ ok: boolean; errors?: string[] }>('/safety/temp-permissions', { method: 'POST', body: JSON.stringify(value) }),
  safetyRevokeTempPermission: (id: string) => request<{ ok: boolean; errors?: string[] }>('/safety/temp-permissions/revoke', { method: 'POST', body: JSON.stringify({ id }) }),
  safetyExtendTempPermission: (id: string, seconds: number) => request<{ ok: boolean; errors?: string[] }>('/safety/temp-permissions/extend', { method: 'POST', body: JSON.stringify({ id, seconds }) }),
  safetyConvertTempPermission: (id: string) => request<{ ok: boolean; errors?: string[] }>('/safety/temp-permissions/convert', { method: 'POST', body: JSON.stringify({ id }) }),
  safetyApprovals: () => request<{ approvals: SafetyApproval[] }>('/safety/approvals'),
  safetyRevokeApproval: (id: string) => request<{ ok: boolean; errors?: string[] }>('/safety/approvals/revoke', { method: 'POST', body: JSON.stringify({ id }) }),
  safetyClearApprovals: () => request<{ ok: boolean; errors?: string[] }>('/safety/approvals/clear', { method: 'POST', body: JSON.stringify({ confirm: true }) }),
  safetyEvents: () => request<{ events: SafetyEvent[] }>('/safety/events'),
  safetyDiagnostics: () => request<{ status: string; run_at: number; checks: SafetyDiagnostic[] }>('/safety/diagnostics'),
  safetyPresets: () => request<{ presets: SafetyPreset[] }>('/safety/presets'),
  safetyApplyPreset: (preset: string) => request<SafetySaveResult>('/safety/presets/apply', { method: 'POST', body: JSON.stringify({ preset }) }),

  memoryStatistics: () => request<{ status: string; statistics: Record<string, unknown> }>('/memory/statistics'),
  memorySearch: (query: string, memoryTypes?: string[]) => request<{ status: string; results: Array<{ type: string; content: string; match_position: number }>; count: number }>('/memory/search', { method: 'POST', body: JSON.stringify({ query, memory_types: memoryTypes }) }),
  memoryExport: (format: 'json' | 'text' = 'json') => request<{ status: string; format: string; data: string }>('/memory/export', { method: 'POST', body: JSON.stringify({ format }) }),
  memoryImport: (data: string, format: 'json' | 'text' = 'json') => request<{ status: string; message: string }>('/memory/import', { method: 'POST', body: JSON.stringify({ data, format }) }),
  memoryClear: (memoryType: string = 'all') => request<{ status: string; message: string }>('/memory/clear', { method: 'POST', body: JSON.stringify({ memory_type: memoryType }) }),
  memorySessions: () => request<{ status: string; sessions: Array<{ id: string; file: string; size: number; modified: number; modified_iso: string }>; count: number }>('/memory/sessions'),


  workspace: (opts?: RequestOptions) => request<WorkspaceSummary>('/workspace', opts),
  workspaceGit: () => request<WorkspaceGit>('/workspace/git'),
  workspaceStats: () => request<WorkspaceStats>('/workspace/stats'),
  workspaceProject: () => request<WorkspaceProject>('/workspace/project'),
  workspaceIndex: () => request<{ status: string } & WorkspaceIndex>('/workspace/index'),
  rebuildIndex: () => request<{ status: string; message: string }>('/workspace/index/rebuild', { method: 'POST' }),
  clearIndex: () => request<{ status: string; message: string }>('/workspace/index/clear', { method: 'POST' }),
  workspaceIgnore: () => request<{ status: string; rules: IgnoreRule[] }>('/workspace/ignore'),
  testIgnorePath: (path: string) => request<{ status: string; result: { path: string; ignored: boolean; matched?: string | null; source?: string | null; existence: string } }>('/workspace/ignore/test', { method: 'POST', body: JSON.stringify({ path }) }),
  workspaceProtected: () => request<{ status: string; paths: ProtectedPath[] }>('/workspace/protected'),
  addProtectedPath: (value: { pattern: string; reason?: string; policy: string }) => request<{ status: string }>('/workspace/protected', { method: 'POST', body: JSON.stringify(value) }),
  removeProtectedPath: (pattern: string) => request<{ status: string; removed: boolean }>(`/workspace/protected?pattern=${encodeURIComponent(pattern)}`, { method: 'DELETE' }),
  workspaceStorage: () => request<WorkspaceStorage>('/workspace/storage'),
  clearStorage: (target: string) => request<{ status: string; removed: number; note: string }>('/workspace/storage/clear', { method: 'POST', body: JSON.stringify({ target }) }),
  workspaceHealth: () => request<{ status: string; checks: HealthCheck[] }>('/workspace/health'),
  workspaceActivity: () => request<WorkspaceActivity>('/workspace/activity'),
  workspaceInstructions: () => request<WorkspaceInstructions>('/workspace/instructions'),
  saveWorkspaceInstructions: (instructions: string) => request<{ status: string }>('/workspace/instructions', { method: 'POST', body: JSON.stringify({ instructions }) }),
  workspaceMemory: () => request<WorkspaceMemory>('/workspace/memory'),
  clearWorkspaceMemory: () => request<{ status: string; cleared: boolean; note: string }>('/workspace/memory/clear', { method: 'POST' }),
  exportWorkspace: () => request<{ status: string; format: string; version: number; exported_at: number; workspace: Record<string, unknown>; git?: unknown }>('/workspace/export'),
  importWorkspace: (config: unknown, apply: boolean) => request<{ status: string; applied: boolean; preview: Record<string, unknown> }>('/workspace/import', { method: 'POST', body: JSON.stringify({ config, apply }) }),
  resetWorkspace: () => request<{ status: string; message: string }>('/workspace/reset', { method: 'POST' }),
  validateWorkspacePath: (path: string) => request<{ status: string; validation: WorkspaceValidation }>(`/workspace/validate?path=${encodeURIComponent(path)}`),
  setWorkspaceRoot: (path: string) => request<{ status: string; path: string; previous: string; validation: WorkspaceValidation }>('/workspace/root', { method: 'POST', body: JSON.stringify({ path }) }),
  addWorkspaceDir: (path: string, accessMode: WorkspaceAccessMode) => request<{ status: string; path: string; access_mode: string; additional_dirs: string[] }>('/workspace/dirs', { method: 'POST', body: JSON.stringify({ path, access_mode: accessMode }) }),
  updateWorkspaceDirAccess: (path: string, accessMode: WorkspaceAccessMode) => request<{ status: string; path: string; access_mode: string }>('/workspace/dirs', { method: 'PATCH', body: JSON.stringify({ path, access_mode: accessMode }) }),
  removeWorkspaceDir: (path: string) => request<{ status: string; removed: boolean; note: string }>(`/workspace/dirs?path=${encodeURIComponent(path)}`, { method: 'DELETE' }),
  workspaceTree: (path?: string) => request<{ status: string; path: string; items: FileItemDTO[] }>(`/files/tree${path ? `?path=${encodeURIComponent(path)}` : ''}`),

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

  listCheckpoints: (sessionId: string) =>
    request<{ checkpoints: CheckpointItemDTO[] }>(`/checkpoints?session_id=${encodeURIComponent(sessionId)}`),

  restoreCheckpoint: (checkpointId: string, sessionId: string) =>
    request<RestoreCheckpointResult>(`/checkpoints/${encodeURIComponent(checkpointId)}/restore`, {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    }),

  deleteCheckpoint: (checkpointId: string, sessionId: string) =>
    request<{ deleted: boolean }>(`/checkpoints/${encodeURIComponent(checkpointId)}?session_id=${encodeURIComponent(sessionId)}`, { method: 'DELETE' }),

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

  readFile: (path: string) => request<{ path: string; content: string }>(`/files/read?path=${encodeURIComponent(path)}&format=json`),

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
          let payload: Record<string, unknown>
          try {
            payload = JSON.parse(line.slice(6)) as Record<string, unknown>
          } catch {
            // A partial/corrupt SSE frame must not terminate the terminal
            // stream; the durable event replay remains authoritative.
            continue
          }
          if (payload.type === 'chunk') onChunk(String(payload.text || ''), payload.stream === 'stderr' ? 'stderr' : 'stdout')
          if (payload.type === 'done') onDone({ status: String(payload.status || 'done'), output: String(payload.output || ''), exit_code: typeof payload.exit_code === 'number' ? payload.exit_code : undefined })
        }
      }
    } catch (error) { onError(error instanceof Error ? error.message : 'Terminal request failed') }
  },

  // Voice API
  voiceStatus: async (sessionId = 'default') => {
    return request<{ status: string; enabled: boolean; auto_speak: boolean; continuous_listening: boolean; voice_name: string; whisper_language: string; statistics: Record<string, unknown> }>(`/voice/status?session_id=${sessionId}`)
  },

  voiceListenStart: async (sessionId = 'default', continuous = true) => {
    return request<{ status: string; listening: boolean; continuous: boolean }>('/voice/listen/start', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, continuous }),
    })
  },

  voiceListenStop: async (sessionId = 'default') => {
    return request<{ status: string; listening: boolean }>(`/voice/listen/stop?session_id=${sessionId}`, { method: 'POST' })
  },

  voiceTranscribe: async (sessionId = 'default', continuous = false) => {
    return request<{ status: string; text: string }>('/voice/transcribe', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, continuous }),
    })
  },

  voiceSpeak: async (text: string, sessionId = 'default', blocking = false) => {
    return request<{ status: string; spoken: boolean }>('/voice/speak', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, text, blocking }),
    })
  },

  voiceSpeakStop: async (sessionId = 'default') => {
    return request<{ status: string }>(`/voice/speak/stop?session_id=${sessionId}`, { method: 'POST' })
  },

  voiceVoices: async () => {
    return request<{ status: string; voices: string[] }>('/voice/voices')
  },

  voiceLanguages: async () => {
    return request<{ status: string; languages: string[] }>('/voice/languages')
  },

  voiceHistory: async (sessionId = 'default', limit = 10) => {
    return request<{ status: string; history: Array<{ timestamp: number; transcript: string; reply: string; success: boolean; voice_name?: string; language?: string }> }>(`/voice/history?session_id=${sessionId}&limit=${limit}`)
  },

  voiceStatistics: async () => request<{ status: string; statistics: Record<string, unknown> }>('/voice/statistics'),
  voiceSearch: async (query: string) => request<{ status: string; results: Array<{ timestamp: number; transcript: string; reply: string; success: boolean; voice_name?: string; language?: string }> }>('/voice/search', { method: 'POST', body: JSON.stringify({ query }) }),
  voiceExport: async (format: 'json' | 'text' = 'json') => request<{ status: string; format: string; data: string }>('/voice/export', { method: 'POST', body: JSON.stringify({ format }) }),
  voiceClearHistory: async () => request<{ status: string; message: string }>('/voice/clear-history', { method: 'POST' }),
  voiceResetStatistics: async () => request<{ status: string; message: string }>('/voice/reset-statistics', { method: 'POST' }),
  voiceDevices: async () => request<{ status: string; devices: Record<string, unknown> }>('/voice/devices'),
  startVoice: async (mode = 'auto') => request<{ status: string; running?: boolean }>('/voice/start', { method: 'POST', body: JSON.stringify({ mode }) }),
  stopVoice: async () => request<{ status: string; running?: boolean }>('/voice/stop', { method: 'POST' }),

  voiceSettings: async (settings: Record<string, unknown>, sessionId = 'default') => {
    return request<{ status: string; settings: Record<string, unknown> }>('/voice/settings', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, ...settings }),
    })
  },

  voiceStream: (sessionId = 'default', onTranscription: (text: string) => void, onError: (error: string) => void): AbortController => {
    const ctrl = new AbortController()
    const url = `${BASE}/voice/stream?session_id=${sessionId}`
    
    fetch(url, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      signal: ctrl.signal,
    }).then(async res => {
      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }))
        onError(body.detail || `Request failed: ${res.status}`)
        return
      }
      const reader = res.body?.getReader()
      if (!reader) { onError('Stream unavailable'); return }
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
            try {
              const parsed = JSON.parse(data)
              if (parsed.type === 'transcription' && parsed.text) {
                onTranscription(parsed.text)
              } else if (parsed.type === 'error') {
                onError(parsed.message || 'Voice stream error')
              }
            } catch (e) {
              // Ignore parse errors for keepalive
            }
          }
        }
      }
    }).catch(err => {
      if (err.name !== 'AbortError') onError(err.message)
    })
    
    return ctrl
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
  partial?: boolean
  agents: HiveAgentItem[]
  resumed_from?: string
  resumed_to?: string
  resume_required?: boolean
  resume_note?: string
}
