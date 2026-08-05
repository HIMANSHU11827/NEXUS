/**
 * Nexus TUI v3.0 — Shared Helpers
 * Pure functions, constants and types extracted from the nexus-tui.tsx monolith.
 * No React state lives here; components and the app orchestrator import these.
 */
import {existsSync, readFileSync} from 'node:fs';
import {mkdir, readFile, readdir, stat, writeFile} from 'node:fs/promises';
import {execFileSync, spawn, execFile as _execFile} from 'node:child_process';
import {promisify} from 'node:util';
import path from 'node:path';

// ── [NEXUS CONFIG]
const configuredApi = process.env.NEXUS_API?.trim();
const configuredHost = process.env.NEXUS_API_HOST?.trim() || '127.0.0.1';
const configuredPort = process.env.NEXUS_API_PORT?.trim() || '8000';
export const API_BASE = configuredApi
    ? configuredApi.replace(/\/$/, '')
    : `http://${configuredHost}:${configuredPort}/api`;
const DASHBOARD_TOKEN = process.env.NEXUS_DASHBOARD_TOKEN?.trim();
export const API_AUTH_HEADERS: Record<string, string> = {
    Authorization: `Bearer ${DASHBOARD_TOKEN || 'nexus-local-tui'}`
};
export const API_JSON_HEADERS: Record<string, string> = {
    ...API_AUTH_HEADERS,
    'Content-Type': 'application/json'
};
export type SandboxTier = 'no_sandbox' | 'normal' | 'docker';
export type PermissionMode = 'auto' | 'all' | 'allowlist' | 'ask';

export const normalizeSandboxTier = (value: string): SandboxTier => {
    const normalized = String(value || '').trim().toLowerCase().replace(/\s+/g, '_');
    if (['normal', 'simple', 'on', 'safe'].includes(normalized)) return 'normal';
    if (['docker', 'advanced'].includes(normalized)) return 'docker';
    return 'no_sandbox';
};

export const nextSandboxTier = (tier: SandboxTier): SandboxTier => {
    if (tier === 'no_sandbox') return 'normal';
    if (tier === 'normal') return 'docker';
    return 'no_sandbox';
};

export const sandboxLabel = (tier: SandboxTier) => {
    if (tier === 'normal') return 'sandbox: simple';
    if (tier === 'docker') return 'sandbox: advanced';
    return 'sandbox: none';
};

export const normalizePermissionMode = (value: string): PermissionMode => {
    const normalized = String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    if (['all', 'bypass', 'dontask', 'dont_ask', 'noask'].includes(normalized)) return 'all';
    if (['allowlist', 'allow_list', 'whitelist', 'pre_authorized', 'checklist'].includes(normalized)) return 'allowlist';
    if (['ask', 'approve', 'approval', 'default', 'ask_once', 'once'].includes(normalized)) return 'ask';
    return 'auto';
};

export const nextPermissionMode = (mode: PermissionMode): PermissionMode => {
    if (mode === 'auto') return 'all';
    if (mode === 'all') return 'allowlist';
    if (mode === 'allowlist') return 'ask';
    return 'auto';
};

export const permissionLabel = (mode: PermissionMode) => `perm: ${mode}`;
export const PROJECT_ROOT = existsSync(path.resolve(process.cwd(), 'pyproject.toml'))
    ? process.cwd()
    : path.resolve(process.cwd(), '..');
export const execFileAsync = promisify(_execFile);

export const syncStopVoiceProcess = () => {
    try {
        execFileSync('powershell.exe', [
            '-NoProfile',
            '-Command',
            `$ProgressPreference='SilentlyContinue'; try { Invoke-RestMethod -Method Post -Uri '${API_BASE}/voice/stop' | Out-Null } catch { }`
        ], {
            cwd: PROJECT_ROOT,
            stdio: 'ignore',
            timeout: 2500,
            windowsHide: true
        });
    } catch {
        // Best effort shutdown.
    }
};

export interface Message {
    role: string;
    content: string;
    activityId?: string;
}

export interface FileStatus {
    name: string;
    status: string;
}

export type TimelineKind = 'read' | 'write' | 'tool' | 'success' | 'error' | 'text' | 'step';

export interface TimelineEvent {
    kind: TimelineKind;
    weight: number;
    label: string;
}

export interface UsageStats {
    contextTokens: number;
    contextLimit: number;
    inputTokens: number;
    outputTokens: number;
}

export interface AgentInfo {
    id: string;
    name: string;
    status: string;
    description?: string;
}

export interface TaskItem {
    id: string;
    subject: string;
    status: string;
    agent?: string;
    /** Local wall-clock time when the task was first observed (real runtime timing). */
    startedAt?: number;
}

export type ActivityKind = 'file' | 'run' | 'mcp' | 'terminal' | 'tool' | 'search' | 'todo' | 'skill' | 'plugin' | 'hive' | 'config' | 'settings' | 'compact';

export const PUBLIC_ACTIVITY_KINDS = new Set([
    'plan', 'todo', 'tool', 'command', 'file', 'test', 'search', 'browser',
    'mcp', 'skill', 'plugin', 'hive', 'agent', 'worker', 'provider', 'rag',
    'approval', 'error', 'retry', 'config', 'settings', 'compact'
]);
export const CHAT_ACTIVITY_KINDS = new Set<ActivityKind>([
    'file', 'run', 'search', 'mcp', 'skill', 'plugin', 'hive', 'tool', 'todo', 'config', 'settings', 'compact'
]);

export const adaptCanonicalEvent = (input: Record<string, any>): Record<string, any> => {
    const payload = input.payload && typeof input.payload === 'object' ? input.payload : {};
    const eventType = String(input.event_type || input.type || '').toLowerCase();
    const inputKind = String(input.kind || '').toLowerCase();
    const family = eventType.includes('.') ? eventType.split('.')[0] : '';
    const kind = family === 'web' ? 'search'
        : ['subagent', 'handoff'].includes(family) ? 'hive'
        : ['plan', 'phase'].includes(family) ? 'plan'
        : ['run', 'conversation', 'message', 'status'].includes(family) ? 'agent'
        : family;
    const error = input.error && typeof input.error === 'object' ? input.error.message : input.error;
    return {
        ...payload, ...input,
        id: input.event_id || input.id,
        kind: ['subagent', 'handoff'].includes(inputKind) ? 'hive' : input.kind || kind || input.legacy_type || input.type,
        action: input.action || input.title || payload.action,
        target: input.target || payload.target || input.related_command || input.related_files?.[0] || input.related_tool,
        command: input.command || payload.command || input.related_command,
        tool: input.tool || payload.tool || input.related_tool,
        error: error || payload.error
    };
};

export interface ActivityItem {
    id: string;
    number: number;
    kind: ActivityKind;
    title: string;
    summary: string;
    status: string;
    detail?: string;
    output?: string;
    error?: string;
    files?: string[];
    command?: string;
    operation?: string;
    preview?: string;
    toolName?: string;
    logo?: string;
    logoColor?: string;
    startedAt?: number;
    durationMs?: number;
    sources?: string[];
    showSources?: boolean;
    showInput?: boolean;
    showOutput?: boolean;
    maxPreviewLines?: number;
    maxPreviewChars?: number;
    intent?: string;
    rules?: string[];
    conditions?: string[];
    oneTimeUse?: boolean;
    maxPerTask?: number;
    parallel?: boolean;
    maxParallel?: number;
    cooldownMs?: number;
}

export type PanelMode = 'workspace' | 'hive' | 'agent' | 'activity' | 'question' | 'plan' | 'mcp';

export interface PendingQuestion {
    id: string;
    prompt: string;
    options: string[];
    allowCustom?: boolean;
}

export const voicePhaseLabel = (phase: string) => {
    const normalized = String(phase || 'off').toLowerCase();
    if (normalized === 'off') return 'off';
    if (normalized === 'ready') return 'ready';
    if (normalized === 'starting') return 'starting';
    if (normalized === 'listening') return 'listening';
    if (normalized === 'waiting') return 'waiting';
    if (normalized === 'hearing') return 'hearing';
    if (normalized === 'processing') return 'processing';
    if (normalized === 'speaking') return 'speaking';
    if (normalized === 'paused') return 'paused';
    if (normalized === 'stopped') return 'stopped';
    if (normalized === 'error') return 'error';
    if (normalized === 'idle') return 'idle';
    return normalized.replace(/_/g, ' ');
};

export const voicePhaseColor = (phase: string) => {
    const normalized = String(phase || 'off').toLowerCase();
    if (normalized === 'error') return 'red';
    if (normalized === 'speaking' || normalized === 'processing' || normalized === 'hearing') return 'yellow';
    if (normalized === 'waiting' || normalized === 'listening' || normalized === 'ready') return 'green';
    if (normalized === 'paused') return 'magentaBright';
    if (normalized === 'starting') return 'blueBright';
    if (normalized === 'off' || normalized === 'stopped' || normalized === 'idle') return 'grey30';
    return 'cyan';
};

export const voiceBarsForFrame = (phase: string, frame: number, count = 10) => {
    const normalized = String(phase || 'off').toLowerCase();
    if (normalized === 'off' || normalized === 'stopped' || normalized === 'idle') {
        return Array.from({length: count}, () => 1);
    }

    const amplitude = normalized === 'speaking'
        ? 5.4
        : normalized === 'hearing'
            ? 6.0
            : normalized === 'processing'
                ? 4.2
                : 3.0;
    const speed = normalized === 'speaking'
        ? 0.62
        : normalized === 'hearing'
            ? 0.78
            : normalized === 'processing'
                ? 0.42
                : 0.24;

    return Array.from({length: count}, (_, index) => {
        const waveA = Math.sin((frame * speed) + index * 0.82);
        const waveB = Math.sin((frame * (speed * 0.57)) + index * 1.41 + 1.2);
        const raw = Math.abs(waveA * 0.7 + waveB * 0.3);
        return Math.max(1, Math.min(8, Math.round(1 + raw * amplitude)));
    });
};

export const CONTEXT_LIMIT = 256000;
export const MAX_TIMELINE_ITEMS = 32;
export const CONTEXT_BAR_WIDTH = 24;
export const THEME = {
    appBg: '#181b21',
    panelBg: '#181b21',
    panelAltBg: '#181b21',
    panelSoftBg: '#151820',
    inputBg: '#242833',
    paletteBg: '#202228',
    border: '#262a33',
    borderSoft: '#20242c',
    accent: '#3b82f6'
};
export type WorkingPhase =
    | 'thinking'
    | 'querying'
    | 'streaming'
    | 'tool'
    | 'skill'
    | 'plugin'
    | 'mcp'
    | 'hive'
    | 'config'
    | 'settings'
    | 'compact'
    | 'evolution'
    | 'self_improvement'
    | 'knowledge'
    | 'memory'
    | 'no_planning'
    | 'simple_planning'
    | 'advance_planning'
    | 'auditing'
    | 'verifying'
    | 'working';

export const WORKING_STATES: Record<WorkingPhase, {frames: string[]; label: string; action: string; status: string; color: string}> = {
    thinking: {frames: ['●─◌─◌', '◌─●─◌', '◌─◌─●', '◌─●─◌'], label: 'thinking', action: '', status: '', color: 'cyan'},
    querying: {frames: ['●─◌─◌', '◌─●─◌', '◌─◌─●', '◌─●─◌'], label: 'thinking', action: '', status: '', color: 'cyan'},
    streaming: {frames: ['●─◌─◌', '◌─●─◌', '◌─◌─●', '◌─●─◌'], label: 'thinking', action: '', status: '', color: 'cyan'},
    tool: {frames: ['◆', '◇', '◆', '◇'], label: 'tools', action: 'run', status: 'working', color: 'green'},
    skill: {frames: ['✦', '✧', '✦', '✧'], label: 'skills', action: 'use', status: 'working', color: 'magentaBright'},
    plugin: {frames: ['⟐', '⟡', '⟐', '⟡'], label: 'plugins', action: 'bind', status: 'working', color: 'yellowBright'},
    mcp: {frames: ['⎇', '⎉', '⎇', '⎉'], label: 'mcp', action: 'link', status: 'working', color: 'cyanBright'},
    hive: {frames: ['⬡', '⬢', '⬡', '⬢'], label: 'hive', action: 'sync', status: 'working', color: 'blueBright'},
    config: {frames: ['◇', '◈', '◇', '◈'], label: 'config', action: 'set', status: 'working', color: 'yellow'},
    settings: {frames: ['⚙', '⚙', '⚙', '⚙'], label: 'settings', action: 'tune', status: 'working', color: 'cyan'},
    compact: {frames: ['◇◇→◇', '◇◇→◆', '◇→◆', '◆'], label: 'compact', action: '', status: 'compressing', color: 'magentaBright'},
    evolution: {frames: ['◆', '◇', '◆', '◇'], label: 'tools', action: 'run', status: 'working', color: 'greenBright'},
    self_improvement: {frames: ['◆', '◇', '◆', '◇'], label: 'tools', action: 'run', status: 'working', color: 'greenBright'},
    knowledge: {frames: ['✦', '✧', '✦', '✧'], label: 'skills', action: 'use', status: 'working', color: 'yellow'},
    memory: {frames: ['◇◇→◇', '◇◇→◆', '◇→◆', '◆'], label: 'compact', action: '', status: 'compressing', color: 'yellowBright'},
    no_planning: {frames: ['●─◌─◌', '◌─●─◌', '◌─◌─●', '◌─●─◌'], label: 'thinking', action: '', status: '', color: 'grey'},
    simple_planning: {frames: ['●─◌─◌', '◌─●─◌', '◌─◌─●', '◌─●─◌'], label: 'thinking', action: '', status: '', color: 'cyan'},
    advance_planning: {frames: ['●─◌─◌', '◌─●─◌', '◌─◌─●', '◌─●─◌'], label: 'thinking', action: '', status: '', color: 'cyanBright'},
    auditing: {frames: ['◆', '◇', '◆', '◇'], label: 'tools', action: 'run', status: 'working', color: 'yellowBright'},
    verifying: {frames: ['◆', '◇', '◆', '◇'], label: 'tools', action: 'run', status: 'working', color: 'greenBright'},
    working: {frames: ['◆', '◇', '◆', '◇'], label: 'tools', action: 'run', status: 'working', color: 'white'}
};
export const READ_TOOLS = new Set(['read', 'glob', 'grep', 'find', 'ls', 'diagnostics', 'warpgrep']);
export const WRITE_TOOLS = new Set(['edit', 'write', 'patch', 'multi_edit', 'multiedit', 'apply_patch', 'file_edit', 'write_file']);
export const RUN_TOOLS = new Set(['bash', 'shell', 'exec', 'run', 'run_command', 'terminal', 'powershell', 'cmd']);
export const SEARCH_TOOLS = new Set(['search', 'web_search', 'websearch', 'browser_search', 'grep', 'warpgrep']);
export const TODO_TOOLS = new Set(['todo', 'todo_write', 'task', 'task_update', 'update_plan', 'plan']);

export const COMMANDS = [
    {name: '/add-dir', description: 'Add extra working directory'},
    {name: '/agents', description: 'Switch or list agents', aliases: ['/agent']},
    {name: '/api', description: 'Check or start TUI API'},
    {name: '/advisor', description: 'Show advisor feature status'},
    {name: '/back', description: 'Return right panel to default'},
    {name: '/background', description: 'Show background session support', aliases: ['/bg']},
    {name: '/batch', description: 'Start multi-agent batch workflow'},
    {name: '/build', description: 'Build GUI or compile TUI'},
    {name: '/branch', description: 'Show current git branch'},
    {name: '/btw', description: 'Ask a side note without special handling'},
    {name: '/cat', description: 'Preview a workspace file'},
    {name: '/cd', description: 'Move TUI working directory'},
    {name: '/chrome', description: 'Show Chrome integration status'},
    {name: '/check', description: 'Run focused checks', aliases: ['/test', '/tests']},
    {name: '/claude-api', description: 'Show Claude API migration support'},
    {name: '/clear', description: 'Clear visible TUI history'},
    {name: '/close', description: 'Close right panel detail', aliases: ['/panel']},
    {name: '/code-review', description: 'Review current git diff'},
    {name: '/color', description: 'Show color/theme control'},
    {name: '/commands', description: 'Show command list', aliases: ['/help', '/']},
    {name: '/compact', description: 'Compact visible TUI history'},
    {name: '/config', description: 'Show runtime config sections'},
    {name: '/conversations', description: 'List saved conversations', aliases: ['/sessions']},
    {name: '/context', description: 'Show context usage'},
    {name: '/copy', description: 'Copy assistant response to clipboard'},
    {name: '/debug', description: 'Show debug diagnostics'},
    {name: '/deep-research', description: 'Run research prompt through chat'},
    {name: '/delete-session', description: 'Delete a conversation'},
    {name: '/desktop', description: 'Show desktop handoff support', aliases: ['/app']},
    {name: '/disable', description: 'Disable tool, skill, MCP, plugin, provider, or feature', aliases: ['/off']},
    {name: '/diff', description: 'Show git diff summary'},
    {name: '/doctor', description: 'Run Nexus health checks'},
    {name: '/docs', description: 'Show important docs'},
    {name: '/effort', description: 'Set reasoning effort mode'},
    {name: '/enable', description: 'Enable tool, skill, MCP, plugin, provider, or feature', aliases: ['/on']},
    {name: '/env', description: 'Show safe env summary'},
    {name: '/exit', description: 'Exit the TUI', aliases: ['/quit']},
    {name: '/export', description: 'Export conversation to a text file'},
    {name: '/fast', description: 'Toggle fast mode hint'},
    {name: '/feedback', description: 'Show feedback/report path', aliases: ['/bug', '/share']},
    {name: '/fewer-permission-prompts', description: 'Inspect permission rules'},
    {name: '/features', description: 'List runtime feature flags'},
    {name: '/files', description: 'Search workspace files'},
    {name: '/focus', description: 'Show focus view support'},
    {name: '/fork', description: 'Fork work to multi-agent flow'},
    {name: '/git', description: 'Show git status', aliases: ['/gst', '/gstatus']},
    {name: '/goal', description: 'Set, show, or clear active Nexus goal'},
    {name: '/gui', description: 'Start, open, or inspect GUI'},
    {name: '/health', description: 'Show API and runtime health'},
    {name: '/heapdump', description: 'Write local Node heap info'},
    {name: '/hive', description: 'Open hive or worker detail'},
    {name: '/history', description: 'Load current conversation history'},
    {name: '/hooks', description: 'Show configured hooks'},
    {name: '/ide', description: 'Open project in VS Code', aliases: ['/editor']},
    {name: '/init', description: 'Initialize project memory files'},
    {name: '/insights', description: 'Summarize local session history'},
    {name: '/install-github-app', description: 'Show GitHub app setup support'},
    {name: '/install-slack-app', description: 'Show Slack app setup support'},
    {name: '/keybindings', description: 'Open keybinding notes'},
    {name: '/login', description: 'Show auth environment status'},
    {name: '/logout', description: 'Clear local provider override'},
    {name: '/logs', description: 'Show recent Nexus logs'},
    {name: '/log', description: 'Show recent git commits'},
    {name: '/loop', description: 'Show scheduler loop support', aliases: ['/proactive']},
    {name: '/ls', description: 'List workspace files'},
    {name: '/memory', description: 'Show or open project memory'},
    {name: '/mcp', description: 'Show MCP configuration', aliases: ['/mcps', '/mpc']},
    {name: '/mobile', description: 'Show mobile handoff support', aliases: ['/ios', '/android']},
    {name: '/mode', description: 'Switch permission mode', aliases: ['/permissions', '/allowed-tools']},
    {name: '/model', description: 'Switch model', aliases: ['/models']},
    {name: '/multi-agent', description: 'Start multi-agent workflow', aliases: ['/multi_agent']},
    {name: '/new', description: 'Create new conversation'},
    {name: '/open', description: 'Open work row detail', aliases: ['/detail']},
    {name: '/open-gui', description: 'Open GUI in browser'},
    {name: '/output-style', description: 'Show output style config'},
    {name: '/passes', description: 'Show passes support'},
    {name: '/paste', description: 'Attach image from Windows clipboard'},
    {name: '/plugins', description: 'List enabled plugins', aliases: ['/plugin']},
    {name: '/plan', description: 'Switch to ask permission mode'},
    {name: '/providers', description: 'Show configured providers'},
    {name: '/provider', description: 'Set provider override', aliases: ['/connect']},
    {name: '/pwd', description: 'Show workspace path'},
    {name: '/powerup', description: 'Show feature lessons support'},
    {name: '/privacy-settings', description: 'Show privacy settings support'},
    {name: '/radio', description: 'Show radio support'},
    {name: '/recap', description: 'Show compact session recap'},
    {name: '/readme', description: 'Preview README'},
    {name: '/reload', description: 'Reload runtime, session, tasks, skills, plugins, tools, or MCP', aliases: ['/reload-plugins', '/reload-skills']},
    {name: '/rename', description: 'Rename current conversation'},
    {name: '/reset', description: 'Reset Nexus runtime or tasks'},
    {name: '/resume', description: 'Resume conversation', aliases: ['/load']},
    {name: '/review', description: 'Review current git diff'},
    {name: '/rewind', description: 'Show rewind/checkpoint support', aliases: ['/checkpoint', '/undo']},
    {name: '/remote-control', description: 'Show remote control support', aliases: ['/rc']},
    {name: '/remote-env', description: 'Show remote environment support'},
    {name: '/run', description: 'Run command through Nexus API'},
    {name: '/run-skill-generator', description: 'Show run skill generator support'},
    {name: '/sandbox', description: 'Switch command sandbox tier'},
    {name: '/scheduler', description: 'Show scheduler feature state'},
    {name: '/schedule', description: 'Show scheduler feature state', aliases: ['/routines']},
    {name: '/scroll-speed', description: 'Show scroll speed support'},
    {name: '/security-review', description: 'Review current diff for security risks'},
    {name: '/setup-bedrock', description: 'Show Bedrock provider setup help'},
    {name: '/setup-vertex', description: 'Show Vertex provider setup help'},
    {name: '/settings', description: 'Alias for config'},
    {name: '/simplify', description: 'Review diff for simplification'},
    {name: '/skills', description: 'List installed skills', aliases: ['/skill']},
    {name: '/sources', description: 'Toggle activity source URLs'},
    {name: '/status', description: 'Show kernel status'},
    {name: '/statusline', description: 'Show status line settings'},
    {name: '/stickers', description: 'Show sticker support'},
    {name: '/stop', description: 'Stop current thinking stream'},
    {name: '/retry', description: 'Retry the last user prompt verbatim'},
    {name: '/tasks', description: 'List tasks', aliases: ['/bashes']},
    {name: '/team-onboarding', description: 'Generate local onboarding recap'},
    {name: '/teleport', description: 'Show teleport support', aliases: ['/tp']},
    {name: '/terminal-setup', description: 'Show terminal keybinding setup'},
    {name: '/theme', description: 'Show theme settings'},
    {name: '/todo', description: 'Create or update todo item'},
    {name: '/tools', description: 'List registered tools', aliases: ['/tool']},
    {name: '/tui', description: 'Show terminal UI renderer'},
    {name: '/ultraplan', description: 'Draft a high-effort plan prompt'},
    {name: '/ultrareview', description: 'Alias for code review'},
    {name: '/upgrade', description: 'Show upgrade support'},
    {name: '/evolution', description: 'Show evolution feature state'},
    {name: '/reminders', description: 'Show reminders feature state'},
    {name: '/tree', description: 'Show workspace tree'},
    {name: '/usage', description: 'Show token usage', aliases: ['/cost', '/stats']},
    {name: '/usage-credits', description: 'Show usage credits support'},
    {name: '/version', description: 'Show versions'},
    {name: '/voice', description: 'Show or toggle voice mode'},
    {name: '/where', description: 'Show active paths'},
    {name: '/work', description: 'Show recent work events'}
];

export const commandDefinitionFor = (value: string) => COMMANDS.find(command =>
    command.name === value || command.aliases?.includes(value)
);

export const estimateTokens = (value: string) => Math.ceil(value.replace(/\s+/g, ' ').trim().length / 4);

export const formatTokens = (value: number) => {
    if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
    return `${value}`;
};

export const formatContextPercent = (tokens: number, limit: number) => {
    if (limit <= 0 || tokens <= 0) return '0%';
    const percent = (tokens / limit) * 100;
    if (percent < 1) return '<1%';
    return `${Math.min(100, Math.round(percent))}%`;
};

export const compactTaskSubject = (value: string, maxLength = 82) => {
    const normalized = value.replace(/\s+/g, ' ').trim();
    if (normalized.length <= maxLength) return normalized;
    return `${normalized.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…`;
};

export const taskStatusGlyph = (status: string) => {
    const normalized = status.toLowerCase();
    if (normalized.includes('complete') || normalized.includes('done')) return '✓';
    if (normalized.includes('running') || normalized.includes('progress')) return '◐';
    if (normalized.includes('error') || normalized.includes('fail')) return '!';
    return '□';
};

/** Compact state glyph for a task row: (·/▶/✓/✗/⏸/⛔). Real state only. */
export const taskStateGlyph = (status: string): string => {
    const normalized = String(status || '').toLowerCase();
    if (['done', 'completed', 'success', 'finished', 'complete'].includes(normalized)) return '✓';
    if (['error', 'failed', 'failure'].includes(normalized)) return '✗';
    if (['cancelled', 'canceled', 'aborted'].includes(normalized)) return '⛔';
    if (['blocked', 'paused', 'waiting', 'vetoed'].includes(normalized)) return '⏸';
    if (['running', 'active', 'working', 'in_progress', 'queued', 'pending'].includes(normalized)) return '▶';
    return '·';
};

/** Human label for a task status, blanked for the trivial idle state. */
export const taskStateLabel = (status: string): string => {
    const normalized = String(status || '').toLowerCase().replace(/[_-]+/g, ' ');
    const alias: Record<string, string> = {
        'in_progress': 'running',
        'in progress': 'running',
        queued: 'queued',
        pending: 'pending',
        working: 'running',
        active: 'running',
        completed: 'done',
        finished: 'done',
        success: 'done',
        failed: 'error',
        cancelled: 'cancelled',
        canceled: 'cancelled',
        aborted: 'cancelled'
    };
    return alias[normalized] || normalized;
};

/** Elapsed label for a task observed at `startedAt`, '' when unknown. */
export const taskElapsedLabel = (startedAt?: number): string => {
    if (!startedAt || !Number.isFinite(startedAt)) return '';
    const elapsed = Date.now() - startedAt;
    if (elapsed < 0) return '';
    if (elapsed < 1000) return '0s';
    const totalSeconds = Math.floor(elapsed / 1000);
    if (totalSeconds < 60) return `${totalSeconds}s`;
    const minutes = Math.floor(totalSeconds / 60);
    if (minutes < 60) return `${minutes}m${totalSeconds % 60}s`;
    return `${Math.floor(minutes / 60)}h${minutes % 60}m`;
};

const editDistance = (left: string, right: string) => {
    const matrix = Array.from({length: left.length + 1}, (_, row) => [row, ...Array(right.length).fill(0)]);
    for (let column = 1; column <= right.length; column++) {
        matrix[0][column] = column;
    }
    for (let row = 1; row <= left.length; row++) {
        for (let column = 1; column <= right.length; column++) {
            const cost = left[row - 1] === right[column - 1] ? 0 : 1;
            matrix[row][column] = Math.min(
                matrix[row - 1][column] + 1,
                matrix[row][column - 1] + 1,
                matrix[row - 1][column - 1] + cost
            );
        }
    }
    return matrix[left.length][right.length];
};

export const commandMatches = (query: string) => {
    const normalized = query.toLowerCase();
    if (!normalized.startsWith('/')) return [];
    if (normalized === '/') return COMMANDS.slice(0, 10);

    return COMMANDS
        .map(command => {
            const names = [command.name, ...(command.aliases || [])];
            const score = Math.min(...names.map(name => {
                if (name.startsWith(normalized)) return 0;
                if (name.includes(normalized)) return 1;
                return editDistance(normalized.replace('/', ''), name.replace('/', '')) <= 2 ? 2 : 99;
            }));
            return {command, score};
        })
        .filter(item => item.score < 99)
        .sort((a, b) => a.score - b.score || a.command.name.localeCompare(b.command.name))
        .slice(0, 10)
        .map(item => item.command);
};

export const timelineColor = (kind: TimelineKind) => {
    if (kind === 'read') return 'blue';
    if (kind === 'write') return 'cyan';
    if (kind === 'tool') return 'blueBright';
    if (kind === 'success') return 'green';
    if (kind === 'error') return 'red';
    if (kind === 'text') return 'grey';
    return 'grey30';
};

export const timelineGlyph = (event: TimelineEvent) => {
    if (event.kind === 'error') return '▆';
    if (event.kind === 'success') return '▇';
    if (event.weight >= 220) return '█';
    if (event.weight >= 120) return '▇';
    if (event.weight >= 60) return '▅';
    if (event.weight >= 20) return '▃';
    return '▂';
};

export const classifyTool = (toolName: string): TimelineKind => {
    const normalized = toolName.toLowerCase();
    if (READ_TOOLS.has(normalized)) return 'read';
    if (WRITE_TOOLS.has(normalized)) return 'write';
    return 'tool';
};

export const inferActivityKind = (toolName: string, params: Record<string, any>): ActivityKind => {
    const normalized = toolName.toLowerCase();
    const blob = `${normalized} ${JSON.stringify(params || {})}`.toLowerCase();

    if (blob.includes('compact') || blob.includes('memory')) return 'compact';
    if (blob.includes('settings') || blob.includes('theme') || blob.includes('statusline') || blob.includes('output-style')) return 'settings';
    if (blob.includes('config') || /\.(ya?ml|json|jsnol|toml|env)\b/.test(blob)) return 'config';
    if (blob.includes('hive') || blob.includes('worker') || blob.includes('agent')) return 'hive';
    if (blob.includes('skill')) return 'skill';
    if (blob.includes('plugin')) return 'plugin';
    if (blob.includes('mcp')) return 'mcp';
    if (SEARCH_TOOLS.has(normalized) || normalized.includes('search')) return 'search';
    if (TODO_TOOLS.has(normalized) || normalized.includes('todo')) return 'todo';
    if (normalized === 'terminal') return 'terminal';
    if (RUN_TOOLS.has(normalized)) return 'run';
    if (normalized === 'file_edit' || normalized === 'write_file' || WRITE_TOOLS.has(normalized)) return 'file';
    return 'tool';
};

export const inferWorkingPhaseFromTool = (toolName: string, params: Record<string, any>): WorkingPhase => {
    const normalized = toolName.toLowerCase();
    const blob = `${normalized} ${JSON.stringify(params || {})}`.toLowerCase();

    if (blob.includes('compact') || blob.includes('memory')) return 'compact';
    if (blob.includes('settings') || blob.includes('theme') || blob.includes('statusline') || blob.includes('output-style')) return 'settings';
    if (blob.includes('config') || /\.(ya?ml|json|jsnol|toml|env)\b/.test(blob)) return 'config';
    if (blob.includes('self_improvement') || blob.includes('improvement')) return 'self_improvement';
    if (blob.includes('evolution')) return 'evolution';
    if (blob.includes('knowledge')) return 'knowledge';
    if (blob.includes('audit')) return 'auditing';
    if (blob.includes('verify') || blob.includes('validation') || blob.includes('check')) return 'verifying';
    if (blob.includes('hive') || blob.includes('worker') || blob.includes('agent')) return 'hive';
    if (blob.includes('plugin')) return 'plugin';
    if (blob.includes('skill')) return 'skill';
    if (blob.includes('mcp')) return 'mcp';
    if (blob.includes('advanced_plan') || blob.includes('ultraplan')) return 'advance_planning';
    if (blob.includes('plan')) return 'simple_planning';
    if (RUN_TOOLS.has(normalized) || normalized === 'terminal') return 'working';
    return 'tool';
};

export const inferWorkingPhaseFromText = (text: string): WorkingPhase | null => {
    const normalized = text.toLowerCase();
    if (!normalized.trim()) return null;
    if (normalized.includes('compact') || normalized.includes('compress')) return 'compact';
    if (normalized.includes('settings') || normalized.includes('theme') || normalized.includes('statusline') || normalized.includes('output-style')) return 'settings';
    if (normalized.includes('config') || /\.(ya?ml|json|jsnol|toml|env)\b/.test(normalized)) return 'config';
    if (normalized.includes('self improvement')) return 'self_improvement';
    if (normalized.includes('evolution')) return 'evolution';
    if (normalized.includes('memory')) return 'compact';
    if (normalized.includes('knowledge')) return 'knowledge';
    if (normalized.includes('plugin')) return 'plugin';
    if (normalized.includes('skill')) return 'skill';
    if (normalized.includes('mcp')) return 'mcp';
    if (normalized.includes('hive') || normalized.includes('worker')) return 'hive';
    if (normalized.includes('auditing') || normalized.includes('audit')) return 'auditing';
    if (normalized.includes('verify') || normalized.includes('checking')) return 'verifying';
    if (normalized.includes('advanced plan') || normalized.includes('step by step plan')) return 'advance_planning';
    if (normalized.includes('plan')) return 'simple_planning';
    if (normalized.includes('working')) return 'working';
    return null;
};

export const statusColor = (status: string) => {
    const normalized = status.toLowerCase();
    if (normalized.includes('error') || normalized.includes('fail')) return 'red';
    if (normalized.includes('done') || normalized.includes('complete')) return 'green';
    if (normalized.includes('progress') || normalized.includes('running')) return 'cyan';
    return 'grey30';
};

export const activityStatusGlyph = (status: string) => {
    const normalized = status.toLowerCase();
    if (normalized.includes('error') || normalized.includes('fail')) return '×';
    if (normalized.includes('done') || normalized.includes('complete') || normalized.includes('success')) return '✓';
    if (normalized.includes('blocked')) return '!';
    if (normalized.includes('cancel')) return '−';
    if (normalized.includes('running') || normalized.includes('progress') || normalized.includes('queued') || normalized.includes('pending')) return '•';
    return '·';
};

export const activityColor = (kind: ActivityKind) => {
    if (kind === 'file') return 'grey';
    if (kind === 'search') return 'blueBright';
    if (kind === 'todo') return 'green';
    if (kind === 'run' || kind === 'terminal') return 'cyan';
    if (kind === 'mcp') return 'magenta';
    if (kind === 'skill') return 'yellowBright';
    if (kind === 'plugin') return 'yellow';
    if (kind === 'hive') return 'cyanBright';
    if (kind === 'config') return 'yellow';
    if (kind === 'settings') return 'cyan';
    if (kind === 'compact') return 'magentaBright';
    return 'blueBright';
};

export const activityGlyph = (kind: ActivityKind) => {
    if (kind === 'file') return '✎';
    if (kind === 'search') return '⌕';
    if (kind === 'todo') return '☑';
    if (kind === 'run' || kind === 'terminal') return '▹';
    if (kind === 'mcp') return '◇';
    if (kind === 'skill') return '✦';
    if (kind === 'plugin') return '⟐';
    if (kind === 'hive') return '⬡';
    if (kind === 'config') return '◇';
    if (kind === 'settings') return '⚙';
    if (kind === 'compact') return '◆';
    return '◦';
};

export const IDENTITY_LOGOS = ['⠶', '⡇', '⠿', '⟐', '◈', '⎇', '⌬', '✦', '⬡', '◆', '◇', '⌁', '⟒', '⊕', '⊖'];
export const IDENTITY_COLORS = ['yellowBright', 'cyanBright', 'magentaBright', 'greenBright', 'blueBright', 'yellow', 'cyan', 'magenta'];

const stableHash = (value: string) => {
    let hash = 2166136261;
    for (const char of value) {
        hash ^= char.charCodeAt(0);
        hash = Math.imul(hash, 16777619);
    }
    return Math.abs(hash >>> 0);
};

export const cleanIdentityName = (value: unknown) => String(value || '')
    .trim()
    .replace(/^mcp[.:/_-]/i, '')
    .replace(/^skill[.:/_-]/i, '')
    .replace(/^plugin[.:/_-]/i, '')
    .replace(/^tool[.:/_-]/i, '')
    .replace(/^hive[.:/_-]/i, '')
    .replace(/\\/g, '/')
    .split('/')
    .pop() || '';

export type ActivityDisplayMeta = Partial<{
    logo: string;
    color: string;
    short: string;
    name: string;
    showSources: boolean;
    showInput: boolean;
    showOutput: boolean;
    maxPreviewLines: number;
    maxPreviewChars: number;
    intent: string;
    rules: string[];
    conditions: string[];
    oneTimeUse: boolean;
    maxPerTask: number;
    parallel: boolean;
    maxParallel: number;
    cooldownMs: number;
}>;

const parseOptionalBool = (value: unknown): boolean | undefined => {
    if (typeof value === 'boolean') return value;
    const normalized = String(value ?? '').trim().toLowerCase();
    if (['true', 'yes', 'on', '1'].includes(normalized)) return true;
    if (['false', 'no', 'off', '0'].includes(normalized)) return false;
    return undefined;
};

const parseOptionalNumber = (value: unknown): number | undefined => {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
};

const parseOptionalStringList = (value: unknown): string[] | undefined => {
    if (Array.isArray(value)) {
        const list = value.map(item => String(item ?? '').trim()).filter(Boolean);
        return list.length > 0 ? list : undefined;
    }
    const raw = String(value ?? '').trim();
    if (!raw) return undefined;
    const list = raw.split(/\s*(?:;|,|\n)\s*/).map(item => item.trim()).filter(Boolean);
    return list.length > 0 ? list : undefined;
};

const readIdentityMetaFile = (filePath: string): ActivityDisplayMeta => {
    if (!existsSync(filePath)) return {};
    try {
        const raw = readFileSync(filePath, 'utf8');
        const json = raw.trim().startsWith('{') ? JSON.parse(raw) : null;
        if (json) {
            const constitution = json.constitution || {};
            const activity = json.activity || {};
            const execution = json.execution || json.runtime || {};
            const pick = (snake: string, camel?: string) =>
                constitution[snake] ?? (camel ? constitution[camel] : undefined) ??
                execution[snake] ?? (camel ? execution[camel] : undefined) ??
                activity[snake] ?? (camel ? activity[camel] : undefined) ??
                json[snake] ?? (camel ? json[camel] : undefined);
            return {
                logo: json.logo || json.icon || json.glyph,
                color: json.color || json.logoColor || json.logo_color,
                short: json.short || json.shortName || json.short_name,
                name: json.name || json.id,
                showSources: parseOptionalBool(pick('show_sources', 'showSources')),
                showInput: parseOptionalBool(pick('show_input', 'showInput')),
                showOutput: parseOptionalBool(pick('show_output', 'showOutput')),
                maxPreviewLines: parseOptionalNumber(pick('max_preview_lines', 'maxPreviewLines')),
                maxPreviewChars: parseOptionalNumber(pick('max_preview_chars', 'maxPreviewChars')),
                intent: pick('intent'),
                rules: parseOptionalStringList(pick('rules')),
                conditions: parseOptionalStringList(pick('conditions')),
                oneTimeUse: parseOptionalBool(pick('one_time_use', 'oneTimeUse')),
                maxPerTask: parseOptionalNumber(pick('max_per_task', 'maxPerTask')),
                parallel: parseOptionalBool(pick('parallel')),
                maxParallel: parseOptionalNumber(pick('max_parallel', 'maxParallel')),
                cooldownMs: parseOptionalNumber(pick('cooldown_ms', 'cooldownMs'))
            };
        }
        const frontMatter = raw.match(/^---\s*\n([\s\S]*?)\n---/);
        const source = frontMatter ? frontMatter[1] : raw.split(/\r?\n/).slice(0, 40).join('\n');
        const pick = (key: string) => {
            const match = source.match(new RegExp(`^${key}:\\s*["']?([^"'\\n#]+)`, 'im'));
            return match?.[1]?.trim();
        };
        return {
            logo: pick('logo') || pick('icon') || pick('glyph'),
            color: pick('color') || pick('logoColor') || pick('logo_color'),
            short: pick('short') || pick('shortName') || pick('short_name'),
            name: pick('name') || pick('id'),
            showSources: parseOptionalBool(pick('show_sources') || pick('showSources') || pick('activity.show_sources') || pick('activity.showSources')),
            showInput: parseOptionalBool(pick('show_input') || pick('showInput') || pick('activity.show_input') || pick('activity.showInput')),
            showOutput: parseOptionalBool(pick('show_output') || pick('showOutput') || pick('activity.show_output') || pick('activity.showOutput')),
            maxPreviewLines: parseOptionalNumber(pick('max_preview_lines') || pick('maxPreviewLines') || pick('activity.max_preview_lines') || pick('activity.maxPreviewLines')),
            maxPreviewChars: parseOptionalNumber(pick('max_preview_chars') || pick('maxPreviewChars') || pick('activity.max_preview_chars') || pick('activity.maxPreviewChars')),
            intent: pick('intent') || pick('constitution.intent') || pick('activity.intent') || pick('execution.intent'),
            rules: parseOptionalStringList(pick('rules') || pick('constitution.rules') || pick('activity.rules') || pick('execution.rules')),
            conditions: parseOptionalStringList(pick('conditions') || pick('constitution.conditions') || pick('activity.conditions') || pick('execution.conditions')),
            oneTimeUse: parseOptionalBool(pick('one_time_use') || pick('oneTimeUse') || pick('constitution.one_time_use') || pick('constitution.oneTimeUse')),
            maxPerTask: parseOptionalNumber(pick('max_per_task') || pick('maxPerTask') || pick('constitution.max_per_task') || pick('constitution.maxPerTask')),
            parallel: parseOptionalBool(pick('parallel') || pick('execution.parallel') || pick('activity.parallel')),
            maxParallel: parseOptionalNumber(pick('max_parallel') || pick('maxParallel') || pick('execution.max_parallel') || pick('execution.maxParallel')),
            cooldownMs: parseOptionalNumber(pick('cooldown_ms') || pick('cooldownMs') || pick('execution.cooldown_ms') || pick('execution.cooldownMs'))
        };
    } catch {
        return {};
    }
};

const identityMetaCandidates = (kind: ActivityKind, name: string) => {
    const id = cleanIdentityName(name);
    if (!id) return [];
    const lower = id.toLowerCase();
    const byKind: Partial<Record<ActivityKind, string[]>> = {
        skill: [
            path.join(PROJECT_ROOT, 'skills', id, 'SKILL.md'),
            path.join(PROJECT_ROOT, 'skills', lower, 'SKILL.md')
        ],
        tool: [
            path.join(PROJECT_ROOT, 'tools', id, `${id}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', lower, `${lower}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', id, `${id}.json`),
            path.join(PROJECT_ROOT, 'tools', lower, `${lower}.json`),
            path.join(PROJECT_ROOT, 'tools', id, `${id}.md`),
            path.join(PROJECT_ROOT, 'tools', lower, `${lower}.md`)
        ],
        terminal: [
            path.join(PROJECT_ROOT, 'tools', id, `${id}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', lower, `${lower}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', 'terminal', 'terminal.jsnol')
        ],
        run: [
            path.join(PROJECT_ROOT, 'tools', id, `${id}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', lower, `${lower}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', 'terminal', 'terminal.jsnol')
        ],
        search: [
            path.join(PROJECT_ROOT, 'tools', id, `${id}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', lower, `${lower}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', 'web_search', 'web_search.jsnol'),
            path.join(PROJECT_ROOT, 'tools', 'code_search', 'code_search.jsnol')
        ],
        mcp: [
            path.join(PROJECT_ROOT, 'mcp', id, `${id}.json`),
            path.join(PROJECT_ROOT, 'mcp', lower, `${lower}.json`),
            path.join(PROJECT_ROOT, 'mcp', id, `${id}.yml`),
            path.join(PROJECT_ROOT, 'mcp', lower, `${lower}.yml`),
            path.join(PROJECT_ROOT, 'mcp', id, 'read.md'),
            path.join(PROJECT_ROOT, 'mcp', lower, 'read.md')
        ],
        plugin: [
            path.join(PROJECT_ROOT, 'plugins', id, 'plugin.json'),
            path.join(PROJECT_ROOT, 'plugins', lower, 'plugin.json'),
            path.join(PROJECT_ROOT, 'plugins', id, 'plugin.yml'),
            path.join(PROJECT_ROOT, 'plugins', lower, 'plugin.yml'),
            path.join(PROJECT_ROOT, 'plugins', id, 'README.md'),
            path.join(PROJECT_ROOT, 'plugins', lower, 'README.md')
        ],
        hive: [
            path.join(PROJECT_ROOT, 'hive', 'agents', id, 'agent.md'),
            path.join(PROJECT_ROOT, 'hive', 'agents', lower, 'agent.md'),
            path.join(PROJECT_ROOT, 'hive', 'agents', id, 'agent.yml'),
            path.join(PROJECT_ROOT, 'hive', 'agents', lower, 'agent.yml')
        ],
        config: [path.join(PROJECT_ROOT, 'config', id)],
        settings: [path.join(PROJECT_ROOT, 'config', 'settings.yml')],
        compact: [path.join(PROJECT_ROOT, 'context', 'compressor.py')]
    };
    return byKind[kind] || [];
};

export const resolveActivityIdentity = (kind: ActivityKind, name: string) => {
    const id = cleanIdentityName(name) || kind;
    const key = `${kind}:${id.toLowerCase()}`;
    for (const candidate of identityMetaCandidates(kind, id)) {
        const meta = readIdentityMetaFile(candidate);
        if (
            meta.logo || meta.color || meta.short || meta.name ||
            meta.showSources !== undefined || meta.showInput !== undefined || meta.showOutput !== undefined ||
            meta.maxPreviewLines !== undefined || meta.maxPreviewChars !== undefined ||
            meta.intent || meta.rules || meta.conditions || meta.oneTimeUse !== undefined || meta.maxPerTask !== undefined ||
            meta.parallel !== undefined || meta.maxParallel !== undefined || meta.cooldownMs !== undefined
        ) {
            return {
                logo: (meta.logo || activityGlyph(kind)).trim(),
                color: meta.color || activityColor(kind),
                label: meta.short || meta.name || id,
                showSources: meta.showSources,
                showInput: meta.showInput,
                showOutput: meta.showOutput,
                maxPreviewLines: meta.maxPreviewLines,
                maxPreviewChars: meta.maxPreviewChars,
                intent: meta.intent,
                rules: meta.rules,
                conditions: meta.conditions,
                oneTimeUse: meta.oneTimeUse,
                maxPerTask: meta.maxPerTask,
                parallel: meta.parallel,
                maxParallel: meta.maxParallel,
                cooldownMs: meta.cooldownMs
            };
        }
    }
    const hash = stableHash(key);
    return {
        logo: IDENTITY_LOGOS[hash % IDENTITY_LOGOS.length],
        color: IDENTITY_COLORS[hash % IDENTITY_COLORS.length],
        label: id,
        showSources: undefined,
        showInput: undefined,
        showOutput: undefined,
        maxPreviewLines: undefined,
        maxPreviewChars: undefined,
        intent: undefined,
        rules: undefined,
        conditions: undefined,
        oneTimeUse: undefined,
        maxPerTask: undefined,
        parallel: undefined,
        maxParallel: undefined,
        cooldownMs: undefined
    };
};

const activityActionIdentity = (activity: Omit<ActivityItem, 'id' | 'number'>) => {
    const operation = String(activity.operation || activity.title || activity.toolName || '').toLowerCase();
    if (activity.kind === 'file') {
        if (operation.includes('read') || operation.includes('view')) return {logo: '→', color: 'grey'};
        if (operation.includes('create') || operation.includes('write')) return {logo: '+', color: 'greenBright'};
        if (operation.includes('delete') || operation.includes('remove')) return {logo: '×', color: 'red'};
        return {logo: '✎', color: 'magentaBright'};
    }
    if (activity.kind === 'search') return {logo: '⌕', color: 'blueBright'};
    if (activity.kind === 'run' || activity.kind === 'terminal') return {logo: '$', color: 'cyanBright'};
    if (activity.kind === 'todo') return {logo: '☑', color: 'green'};
    if (activity.kind === 'config') return {logo: '◇', color: 'yellow'};
    if (activity.kind === 'settings') return {logo: '⚙', color: 'cyan'};
    if (activity.kind === 'compact') return {logo: '◆', color: 'magentaBright'};
    if (activity.kind === 'tool') return {logo: '◆', color: 'green'};
    return null;
};

export const withActivityIdentity = <T extends Omit<ActivityItem, 'id' | 'number'>>(activity: T): T => {
    const identityName = activity.toolName || activity.summary || activity.title || activity.kind;
    const identity = resolveActivityIdentity(activity.kind, identityName);
    const actionIdentity = activityActionIdentity(activity);
    if (actionIdentity) {
        return {
            ...activity,
            logo: activity.logo || actionIdentity.logo,
            logoColor: activity.logoColor || actionIdentity.color,
            showSources: activity.showSources ?? identity.showSources,
            showInput: activity.showInput ?? identity.showInput,
            showOutput: activity.showOutput ?? identity.showOutput,
            maxPreviewLines: activity.maxPreviewLines ?? identity.maxPreviewLines,
            maxPreviewChars: activity.maxPreviewChars ?? identity.maxPreviewChars,
            intent: activity.intent ?? identity.intent,
            rules: activity.rules ?? identity.rules,
            conditions: activity.conditions ?? identity.conditions,
            oneTimeUse: activity.oneTimeUse ?? identity.oneTimeUse,
            maxPerTask: activity.maxPerTask ?? identity.maxPerTask,
            parallel: activity.parallel ?? identity.parallel,
            maxParallel: activity.maxParallel ?? identity.maxParallel,
            cooldownMs: activity.cooldownMs ?? identity.cooldownMs
        };
    }
    return {
        ...activity,
        logo: activity.logo || identity.logo,
        logoColor: activity.logoColor || identity.color,
        showSources: activity.showSources ?? identity.showSources,
        showInput: activity.showInput ?? identity.showInput,
        showOutput: activity.showOutput ?? identity.showOutput,
        maxPreviewLines: activity.maxPreviewLines ?? identity.maxPreviewLines,
        maxPreviewChars: activity.maxPreviewChars ?? identity.maxPreviewChars,
        intent: activity.intent ?? identity.intent,
        rules: activity.rules ?? identity.rules,
        conditions: activity.conditions ?? identity.conditions,
        oneTimeUse: activity.oneTimeUse ?? identity.oneTimeUse,
        maxPerTask: activity.maxPerTask ?? identity.maxPerTask,
        parallel: activity.parallel ?? identity.parallel,
        maxParallel: activity.maxParallel ?? identity.maxParallel,
        cooldownMs: activity.cooldownMs ?? identity.cooldownMs
    };
};

export const getFileName = (value: string) => value.split(/[/\\]/).pop() || value;

export const cleanPreview = (value: unknown, lines = 14) => String(value || '')
    .replace(/\r\n/g, '\n')
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/(?:\x1b)?\[<\d+;\d+;\d+[mM]/g, '')
    .split('\n')
    .slice(0, lines)
    .join('\n')
    .trim();

export const codePreviewLines = (value: string, limit = 36) => cleanPreview(value, limit)
    .split('\n')
    .filter((line, index, lines) => line.length > 0 || index < lines.length - 1)
    .map((line, index) => `${String(index + 1).padStart(3, ' ')}  ${line}`);

export const compactDetailPreview = (value: unknown, lines = 10, chars = 1200) => {
    const cleaned = cleanPreview(value, lines);
    return cleaned.length > chars ? `${cleaned.slice(0, chars).trimEnd()}…` : cleaned;
};

export const formatDurationMs = (value?: number) => {
    if (value == null || !Number.isFinite(value) || value < 0) return '';
    if (value < 1000) return `${Math.round(value)}ms`;
    return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}s`;
};

export const normalizeActivityStatus = (status: unknown, error?: unknown) => {
    const value = String(status || '').toLowerCase();
    if (value.includes('block') || value.includes('guardrail') || value.includes('denied')) return 'blocked';
    if (error || value.includes('error') || value.includes('fail') || value.includes('exception')) return 'error';
    if (value === 'success' || value === 'succeeded' || value === 'complete' || value === 'completed') return 'done';
    if (value === 'in_progress' || value === 'started') return 'running';
    if (value === 'cancelled' || value === 'canceled') return 'cancelled';
    return value || 'running';
};

export const extractUrls = (value: unknown) => {
    const matches = String(value || '').match(/https?:\/\/[^\s)\]]+|www\.[^\s)\]]+/g) || [];
    return [...new Set(matches.map(url => url.replace(/[.,;:]+$/, '')))].slice(0, 8);
};

export const compactActivityOutputPreview = (activity: ActivityItem) => {
    const raw = activity.error
        || (activity.showOutput !== false ? (activity.output || activity.preview) : '')
        || (activity.showInput !== false ? activity.detail : '')
        || '';
    const lineLimit = activity.maxPreviewLines ?? (activity.kind === 'search' ? 5 : 8);
    const charLimit = activity.maxPreviewChars ?? (activity.kind === 'search' ? 520 : 900);
    const scrubbed = String(raw)
        .replace(/\]\(https?:\/\/[^)]+\)/g, ']')
        .replace(/https?:\/\/\S+/g, '<link>')
        .replace(/www\.\S+/g, '<link>')
        .replace(/\s+/g, ' ')
        .trim();
    return compactDetailPreview(scrubbed, lineLimit, charLimit);
};

export const activityPreviewLabel = (activity: ActivityItem) => {
    if (activity.error) return 'error';
    if (activity.kind === 'search') return 'results';
    if (activity.output) return 'output';
    if (activity.preview) return 'preview';
    return 'input';
};

export const formatToolInput = (params: Record<string, any>) => Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .filter(([key]) => !['file_text', 'content', 'new_str', 'new_string', 'old_str'].includes(key))
    .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
    .join('\n');

export const runLocal = async (file: string, args: string[], cwd = PROJECT_ROOT, timeout = 20000) => {
    try {
        const {stdout, stderr} = await execFileAsync(file, args, {
            cwd,
            timeout,
            windowsHide: true,
            maxBuffer: 1024 * 1024
        });
        return cleanPreview([stdout, stderr].filter(Boolean).join('\n'), 80);
    } catch (error: any) {
        const output = [error.stdout, error.stderr, error.message].filter(Boolean).join('\n');
        return cleanPreview(output, 80);
    }
};

export const runLocalResult = async (file: string, args: string[], cwd = PROJECT_ROOT, timeout = 20000) => {
    try {
        const {stdout, stderr} = await execFileAsync(file, args, {
            cwd,
            timeout,
            windowsHide: true,
            maxBuffer: 1024 * 1024
        });
        return {ok: true, output: cleanPreview([stdout, stderr].filter(Boolean).join('\n'), 80)};
    } catch (error: any) {
        const output = [error.stdout, error.stderr, error.message].filter(Boolean).join('\n');
        return {ok: false, output: cleanPreview(output, 80)};
    }
};

export const startDetached = (file: string, args: string[], cwd = PROJECT_ROOT) => {
    const child = spawn(file, args, {
        cwd,
        detached: true,
        stdio: 'ignore',
        windowsHide: true
    });
    child.unref();
};

export const apiHasTuiCapabilities = async () => {
    try {
        const [health, status, voice] = await Promise.all([
            fetch(`${API_BASE}/health`, {headers: API_AUTH_HEADERS}),
            fetch(`${API_BASE}/status`, {headers: API_AUTH_HEADERS}),
            fetch(`${API_BASE}/voice/status`, {headers: API_AUTH_HEADERS})
        ]);
        return health.ok && status.ok && voice.ok;
    } catch {
        return false;
    }
};

export const clearApiPortForRestart = async () => {
    if (process.platform !== 'win32') return;
    const command = [
        '$ErrorActionPreference = "SilentlyContinue"',
        '$pids = netstat -ano | Select-String ":8000\\s+.*LISTENING" | ForEach-Object { ($_ -split "\\s+")[-1] } | Sort-Object -Unique',
        'foreach ($id in $pids) { if ($id -match "^\\d+$") { taskkill /F /PID $id | Out-Null } }'
    ].join('; ');
    try {
        await execFileAsync('powershell.exe', ['-NoProfile', '-Command', command], {
            cwd: PROJECT_ROOT,
            timeout: 5000,
            windowsHide: true
        });
    } catch {
        // Best effort; the subsequent server start/poll will report failure if the port stays busy.
    }
};

export const commandExists = async (command: string) => {
    try {
        await execFileAsync(process.platform === 'win32' ? 'where' : 'which', [command], {
            cwd: PROJECT_ROOT,
            timeout: 5000,
            windowsHide: true
        });
        return true;
    } catch {
        return false;
    }
};

export const safeRelativePath = (input: string) => {
    const target = path.resolve(PROJECT_ROOT, input || '.');
    const root = path.resolve(PROJECT_ROOT);
    if (!target.startsWith(root)) {
        throw new Error('Path escapes workspace');
    }
    return target;
};

const normalizeAttachmentPath = (value: string) => {
    let cleaned = value.trim().replace(/^@/, '').replace(/^['"]|['"]$/g, '');
    cleaned = cleaned.replace(/[),.;]+$/g, '');
    if (cleaned.startsWith('file:///')) {
        cleaned = decodeURIComponent(cleaned.replace(/^file:\/\/\//, ''));
        if (/^[A-Za-z]\|/.test(cleaned)) {
            cleaned = `${cleaned[0]}:${cleaned.slice(2)}`;
        }
    }
    return path.isAbsolute(cleaned) ? path.resolve(cleaned) : path.resolve(PROJECT_ROOT, cleaned);
};

const extractAttachmentCandidates = (value: string) => {
    const candidates = new Set<string>();
    const quoted = value.matchAll(/["']([^"']+)["']/g);
    for (const match of quoted) candidates.add(match[1]);

    const fileUrls = value.matchAll(/file:\/\/\/[^\s"'<>]+/gi);
    for (const match of fileUrls) candidates.add(match[0]);

    const atPaths = value.matchAll(/@([^\s]+)/g);
    for (const match of atPaths) candidates.add(match[1]);

    const trimmed = value.trim();
    if (trimmed) candidates.add(trimmed);

    return [...candidates];
};

export const resolveInputAttachments = async (value: string) => {
    const seen = new Set<string>();
    const files: Array<{path: string; name: string; size: number; kind: string}> = [];

    for (const candidate of extractAttachmentCandidates(value)) {
        try {
            const resolved = normalizeAttachmentPath(candidate);
            if (seen.has(resolved) || !existsSync(resolved)) continue;
            const info = await stat(resolved);
            if (!info.isFile()) continue;
            seen.add(resolved);
            files.push({
                path: resolved,
                name: path.basename(resolved),
                size: info.size,
                kind: path.extname(resolved).replace('.', '').toLowerCase() || 'file'
            });
        } catch {
            // Ignore non-path text; normal chat should keep working.
        }
    }

    return files;
};

export const attachmentPrompt = (prompt: string, files: Array<{path: string; name: string; size: number; kind: string}>) => {
    if (files.length === 0) return prompt;
    const cleanPrompt = prompt.trim() || 'Please inspect the attached file(s).';
    const fileLines = files.map(file => `- ${file.name} (${file.kind}, ${formatTokens(file.size)}B): ${file.path}`);
    return `${cleanPrompt}\n\nAttached files:\n${fileLines.join('\n')}`;
};

export const saveClipboardImage = async () => {
    const uploadDir = path.join(PROJECT_ROOT, 'workspace', 'uploads');
    await mkdir(uploadDir, {recursive: true});
    const output = path.join(uploadDir, `clipboard-${Date.now()}.png`);
    const script = [
        'Add-Type -AssemblyName System.Windows.Forms',
        'Add-Type -AssemblyName System.Drawing',
        '$img = [System.Windows.Forms.Clipboard]::GetImage()',
        'if ($null -eq $img) { exit 2 }',
        `$img.Save(${JSON.stringify(output)}, [System.Drawing.Imaging.ImageFormat]::Png)`,
        '$img.Dispose()'
    ].join('; ');

    await execFileAsync('powershell.exe', ['-NoProfile', '-STA', '-Command', script], {
        cwd: PROJECT_ROOT,
        timeout: 15000,
        windowsHide: true
    });

    return output;
};

export const listDirectory = async (target: string, limit = 40) => {
    const entries = await readdir(target, {withFileTypes: true});
    return entries
        .filter(entry => !['node_modules', '.git', '__pycache__', '.venv'].includes(entry.name))
        .slice(0, limit)
        .map(entry => `${entry.isDirectory() ? '[DIR] ' : '      '}${entry.name}`)
        .join('\n');
};

export const treeDirectory = async (target: string, depth = 2, prefix = ''): Promise<string[]> => {
    if (depth <= 0) return [];
    const entries = (await readdir(target, {withFileTypes: true}))
        .filter(entry => !['node_modules', '.git', '__pycache__', '.venv'].includes(entry.name))
        .slice(0, 24);
    const lines: string[] = [];
    for (const entry of entries) {
        lines.push(`${prefix}${entry.isDirectory() ? '+ ' : '- '}${entry.name}`);
        if (entry.isDirectory()) {
            lines.push(...await treeDirectory(path.join(target, entry.name), depth - 1, `${prefix}  `));
        }
    }
    return lines;
};

export const readYamlSectionNames = async (filePath: string) => {
    const content = await readFile(filePath, 'utf8');
    return content
        .split(/\r?\n/)
        .filter(line => /^[A-Za-z0-9_.-]+:\s*$/.test(line))
        .map(line => line.replace(':', '').trim());
};

export const activityFromTool = (toolName: string, params: Record<string, any>): Omit<ActivityItem, 'id' | 'number'> => {
    const normalized = toolName.toLowerCase();
    const kind = inferActivityKind(toolName, params);
    const rawPath = params.path || params.filename || params.file || params.filepath || params.uri || '';
    const fileName = rawPath ? getFileName(String(rawPath)) : '';
    const command = String(params.command || params.cmd || params.script || '');
    const query = String(params.query || params.q || params.pattern || params.search || params.prompt || '');

    if (SEARCH_TOOLS.has(normalized) || normalized.includes('search')) {
        const summary = query || command || toolName;
        return {
            kind: 'search',
            title: normalized.includes('web') || params.url ? 'Searched web' : 'Searched files',
            summary,
            status: 'running',
            command: summary || undefined,
            detail: formatToolInput(params),
            sources: extractUrls(JSON.stringify(params || {})),
            toolName
        };
    }

    if (TODO_TOOLS.has(normalized) || normalized.includes('todo')) {
        return {
            kind: 'todo',
            title: 'Updated todo list',
            summary: query || command || toolName,
            status: 'running',
            detail: formatToolInput(params),
            toolName
        };
    }

    if (normalized === 'file_edit' || normalized === 'write_file' || WRITE_TOOLS.has(normalized)) {
        const editCommand = String(params.command || '').toLowerCase();
        const preview = cleanPreview(
            params.new_str || params.new_string || params.file_text || params.content || params.old_str,
            120
        );
        const verb = editCommand === 'create' || normalized === 'write_file'
            ? 'Created'
            : editCommand === 'view'
                ? 'Read'
                : 'Edited';
        return {
            kind: 'file',
            title: `${verb} a file`,
            summary: fileName || toolName,
            status: 'running',
            files: fileName ? [fileName] : [],
            operation: editCommand || normalized,
            preview: preview || undefined,
            detail: formatToolInput(params),
            toolName
        };
    }

    if (kind === 'mcp') {
        return {
            kind: 'mcp',
            title: 'MCP call',
            summary: toolName,
            status: 'running',
            command: command || undefined,
            detail: formatToolInput(params),
            toolName
        };
    }

    if (kind === 'skill') {
        return {
            kind: 'skill',
            title: 'Used skill',
            summary: toolName,
            status: 'running',
            detail: formatToolInput(params),
            toolName
        };
    }

    if (kind === 'plugin') {
        return {
            kind: 'plugin',
            title: 'Used plugin',
            summary: toolName,
            status: 'running',
            detail: formatToolInput(params),
            toolName
        };
    }

    if (kind === 'hive') {
        return {
            kind: 'hive',
            title: 'Hive action',
            summary: command || query || toolName,
            status: 'running',
            detail: formatToolInput(params),
            toolName
        };
    }

    if (RUN_TOOLS.has(normalized)) {
        return {
            kind: normalized === 'terminal' ? 'terminal' : 'run',
            title: 'Ran command',
            summary: command || toolName,
            status: 'running',
            command: command || undefined,
            detail: formatToolInput(params),
            toolName
        };
    }

    return {
        kind: 'tool',
        title: `Used ${toolName}`,
        summary: command || fileName || toolName,
        status: 'running',
        command: command || undefined,
        detail: formatToolInput(params),
        toolName
    };
};

export const readTodoMarkdown = async (): Promise<TaskItem[]> => {
    const candidates = [
        path.resolve(process.cwd(), 'workspace', 'todo.md'),
        path.resolve(process.cwd(), '..', 'workspace', 'todo.md')
    ];

    for (const candidate of candidates) {
        try {
            const markdown = await readFile(candidate, 'utf8');
            return markdown
                .split(/\r?\n/)
                .map((line, index) => {
                    const match = line.match(/^\s*-\s+\[([ xX])\]\s+(.+?)\s*$/);
                    if (!match) return null;
                    const checked = match[1].toLowerCase() === 'x';
                    return {
                        id: `todo-md-${index}`,
                        subject: match[2].replace(/^Phase\s+\d+:\s*/i, '').trim(),
                        status: checked ? 'completed' : 'pending'
                    };
                })
                .filter((task): task is TaskItem => Boolean(task));
        } catch {
            // Try the next likely workspace root.
        }
    }

    return [];
};

export const clearTerminalForInk = () => {
    if (!process.stdout.isTTY) return;
    process.stdout.write('\x1b[2J\x1b[3J\x1b[H');
};

export const extractSsePayload = (frame: string) => frame
    .replace(/\r/g, '')
    .split('\n')
    .filter(line => !line.startsWith('event:'))
    .map(line => line.startsWith('data:') ? line.replace(/^data:\s?/, '') : line)
    .join('\n');

export const cleanVisibleAssistantText = (text: string) => {
    let cleaned = String(text || '');
    cleaned = cleaned.replace(/\[NEXUS_BOOT\]:[^\n]*/g, '');
    cleaned = cleaned.replace(/\[THINKING:[^\]]+\]/g, '');
    cleaned = cleaned.replace(/<thinking>[\s\S]*?<\/thinking>/gi, '');
    cleaned = cleaned.replace(/<\/?thinking>/gi, '');
    cleaned = cleaned.replace(/TASK_COMPLETE/g, '');
    cleaned = cleaned.replace(/\n{3,}/g, '\n\n');
    return cleaned.trim();
};

export const mouseWheelDirection = (value: string, maxX: number) => {
    const matches = Array.from(value.matchAll(/\x1b\[<(\d+);(\d+);(\d+)[mM]/g));
    for (const match of matches) {
        const button = Number(match[1]);
        const x = Number(match[2]);
        if (!Number.isFinite(button) || !Number.isFinite(x) || x > maxX) continue;
        if ((button & 64) === 0) continue;
        return (button & 1) === 0 ? 1 : -1;
    }
    return 0;
};

export const mouseWheelDirections = (value: string, maxX: number) => {
    const directions: number[] = [];
    for (const match of value.matchAll(/\x1b\[<(\d+);(\d+);(\d+)[mM]/g)) {
        const button = Number(match[1]);
        const x = Number(match[2]);
        if (Number.isFinite(button) && Number.isFinite(x) && x <= maxX && (button & 64) !== 0) {
            directions.push((button & 1) === 0 ? 1 : -1);
        }
    }
    // X10 mouse protocol fallback used by some Windows terminal configurations.
    for (const match of value.matchAll(/\x1b\[M([\s\S])([\s\S])([\s\S])/g)) {
        const button = match[1].charCodeAt(0) - 32;
        const x = match[2].charCodeAt(0) - 32;
        if (x <= maxX && (button & 64) !== 0) directions.push((button & 1) === 0 ? 1 : -1);
    }
    return directions;
};

export const mousePointer = (value: string, maxX: number) => {
    const matches = Array.from(value.matchAll(/\x1b\[<(\d+);(\d+);(\d+)([mM])/g));
    const match = matches[matches.length - 1];
    if (match) {
        const rawButton = Number(match[1]);
        const x = Number(match[2]);
        const y = Number(match[3]);
        const pressed = match[4] === 'M';
        if (!Number.isFinite(rawButton) || !Number.isFinite(x) || !Number.isFinite(y) || x > maxX) return null;
        return {button: pressed ? rawButton & 3 : 35, x, y, pressed};
    }

    // X10 mouse protocol fallback used by some Windows terminal configurations.
    const x10Matches = Array.from(value.matchAll(/\x1b\[M([\s\S])([\s\S])([\s\S])/g));
    const x10Match = x10Matches[x10Matches.length - 1];
    if (!x10Match) return null;
    const rawButton = x10Match[1].charCodeAt(0) - 32;
    const x = x10Match[2].charCodeAt(0) - 32;
    const y = x10Match[3].charCodeAt(0) - 32;
    const button = rawButton & 3;
    const pressed = button !== 3;
    if (!Number.isFinite(rawButton) || !Number.isFinite(x) || !Number.isFinite(y) || x > maxX) return null;
    return {button: pressed ? button : 35, x, y, pressed};
};

export const sanitizeComposerInput = (value: string) => value
    .replace(/(?:\x1b)?\[<\d+;\d+;\d+[mM]/g, '')
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '');

export const parseQuestionMarker = (text: string): PendingQuestion | null => {
    const match = text.match(/\[QUESTION:(.*?)\]/s);
    if (!match) return null;
    try {
        const data = JSON.parse(match[1]);
        const options = Array.isArray(data.options)
            ? data.options.map((option: unknown) => String(option)).filter(Boolean).slice(0, 8)
            : [];
        if (!data.prompt || options.length === 0) return null;
        return {
            id: `question-${Date.now()}`,
            prompt: String(data.prompt),
            options,
            allowCustom: data.allowCustom !== false
        };
    } catch {
        return null;
    }
};

export const stripQuestionMarkers = (text: string) => text.replace(/\[QUESTION:.*?\]/gs, '');

export interface ChatLine {
    key: string;
    text: string;
    color: string;
    prefix?: string;
    prefixColor?: string;
    reservePrefix?: boolean;
    bold?: boolean;
    activityId?: string;
    activity?: ActivityItem;
}

export const activityFromWorkEvent = (event: Record<string, any>): Omit<ActivityItem, 'id' | 'number'> => {
    event = adaptCanonicalEvent(event);
    const eventKind = String(event.kind || event.type || 'tool').toLowerCase();
    const toolName = String(event.tool || event.name || event.server || eventKind);
    const target = String(event.target || event.path || event.command || event.query || toolName);
    const details = event.args || event.arguments || event.input;
    const output = cleanPreview(event.output || event.stdout || event.chunk || event.result || '', 30) || undefined;
    const error = cleanPreview(event.error || event.stderr || event.preview_error || '', 16) || undefined;
    const sourceValues = [
        event.url,
        event.source_url,
        event.sources,
        event.citations,
        event.links,
        target,
        output
    ];
    const common = {
        title: String(event.action || event.title || event.label || 'Agent activity'),
        summary: target,
        status: normalizeActivityStatus(event.status, error),
        detail: [
            details ? (typeof details === 'string' ? details : JSON.stringify(details, null, 2)) : '',
            event.duration_ms != null ? `duration: ${event.duration_ms} ms` : '',
            event.exit_code != null ? `exit code: ${event.exit_code}` : '',
            event.changed_lines || event.line_changes ? `changed lines: ${JSON.stringify(event.changed_lines || event.line_changes)}` : '',
            event.diff || event.patch || ''
        ].filter(Boolean).join('\n') || undefined,
        output,
        error,
        durationMs: event.duration_ms ?? event.durationMs,
        sources: sourceValues.flatMap(value => Array.isArray(value) ? value.map(String) : extractUrls(value)),
        toolName
    };
    if (eventKind === 'file') return {...common, kind: 'file', files: target ? [target] : [], operation: String(event.operation || event.action || '')};
    if (eventKind === 'command') return {...common, kind: 'run', command: String(event.command || target)};
    if (eventKind === 'search' || eventKind === 'browser' || eventKind === 'rag') return {...common, kind: 'search', command: String(event.query || target)};
    if (eventKind === 'plan') {
        const items = Array.isArray(event.items) ? event.items.map(String) : [];
        const planName = items.length > 1 ? 'Advanced Planning' : 'Simple Planning';
        return {
            ...common,
            kind: 'todo',
            title: planName,
            summary: `${items.length || 1} step${items.length === 1 ? '' : 's'}`,
            detail: items.length > 0
                ? items.map((item: string, index: number) => `${index + 1}. ${item}`).join('\n')
                : 'Resolving planning steps…',
            toolName: 'plan'
        };
    }
    if (eventKind === 'todo') return {...common, kind: 'todo', preview: cleanPreview(event.preview || event.result || '', 120) || undefined};
    if (eventKind === 'mcp') return {...common, kind: 'mcp'};
    if (eventKind === 'skill') return {...common, kind: 'skill'};
    if (eventKind === 'plugin') return {...common, kind: 'plugin'};
    if (['hive', 'agent', 'worker'].includes(eventKind)) return {...common, kind: 'hive'};
    return {...common, kind: 'tool'};
};
