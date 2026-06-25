import React, {useState, useEffect, useRef} from 'react';
import {existsSync} from 'node:fs';
import {mkdir, readFile, readdir, stat, writeFile} from 'node:fs/promises';
import {execFile, execFileSync, spawn} from 'node:child_process';
import {promisify} from 'node:util';
import path from 'node:path';
import {render, Box, Text, useApp, useInput} from 'ink';
import TextInput from 'ink-text-input';

// ── [NEXUS CONFIG]
const API_BASE = "http://localhost:8000/api";
const PROJECT_ROOT = existsSync(path.resolve(process.cwd(), 'pyproject.toml'))
    ? process.cwd()
    : path.resolve(process.cwd(), '..');
const execFileAsync = promisify(execFile);

const syncStopVoiceProcess = () => {
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

interface Message {
    role: string;
    content: string;
    activityId?: string;
}

interface FileStatus {
    name: string;
    status: string;
}

type TimelineKind = 'read' | 'write' | 'tool' | 'success' | 'error' | 'text' | 'step';

interface TimelineEvent {
    kind: TimelineKind;
    weight: number;
    label: string;
}

interface UsageStats {
    contextTokens: number;
    contextLimit: number;
    inputTokens: number;
    outputTokens: number;
}

interface AgentInfo {
    id: string;
    name: string;
    status: string;
    description?: string;
}

interface TaskItem {
    id: string;
    subject: string;
    status: string;
    agent?: string;
}

type ActivityKind = 'file' | 'run' | 'mcp' | 'terminal' | 'tool' | 'search' | 'todo' | 'skill' | 'plugin' | 'hive';

interface ActivityItem {
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
}

type PanelMode = 'workspace' | 'hive' | 'agent' | 'activity' | 'question';

interface PendingQuestion {
    id: string;
    prompt: string;
    options: string[];
    allowCustom?: boolean;
}

const voicePhaseLabel = (phase: string) => {
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

const voicePhaseColor = (phase: string) => {
    const normalized = String(phase || 'off').toLowerCase();
    if (normalized === 'error') return 'red';
    if (normalized === 'speaking' || normalized === 'processing' || normalized === 'hearing') return 'yellow';
    if (normalized === 'waiting' || normalized === 'listening' || normalized === 'ready') return 'green';
    if (normalized === 'paused') return 'magentaBright';
    if (normalized === 'starting') return 'blueBright';
    if (normalized === 'off' || normalized === 'stopped' || normalized === 'idle') return 'grey30';
    return 'cyan';
};

const voiceBarsForFrame = (phase: string, frame: number, count = 10) => {
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

const VoiceEqualizer = React.memo(({
    phase,
    frame,
    color,
    bars = 10
}: {
    phase: string;
    frame: number;
    color?: string;
    bars?: number;
}) => {
    const heights = voiceBarsForFrame(phase, frame, bars);
    return (
        <Box>
            {heights.map((height, index) => (
                <Text key={`voice-bar-${index}`} color={color || voicePhaseColor(phase)}>
                    {'▁▂▃▄▅▆▇█'[Math.max(0, Math.min(7, height - 1))]}{index < heights.length - 1 ? ' ' : ''}
                </Text>
            ))}
        </Box>
    );
});

interface NexusWorkspacePanelProps {
    timeline: TimelineEvent[];
    usage: UsageStats;
    mode: PanelMode;
    agents: AgentInfo[];
    tasks: TaskItem[];
    touchedFiles: FileStatus[];
    activityItems: ActivityItem[];
    pendingQuestion: PendingQuestion | null;
    selectedActivityId: string | null;
    selectedAgentId: string | null;
    motionFrame: number;
    width: number;
    height: number;
}

const CONTEXT_LIMIT = 256000;
const MAX_TIMELINE_ITEMS = 32;
const CONTEXT_BAR_WIDTH = 24;
const THEME = {
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
const NEXUS_LOGO = [
    '  ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗',
    '  ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝',
    '  ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗',
    '  ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║',
    '  ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║',
    '  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝'
];
const LOGO_GRADIENT = ['#4f8cff', '#5d83ff', '#6f78f0', '#806edf', '#9167d2', '#7d7cff'];
const LOGO_OUTLINE_CHARS = new Set(['╔', '╗', '╚', '╝', '═', '║']);
type WorkingPhase =
    | 'thinking'
    | 'querying'
    | 'streaming'
    | 'tool'
    | 'skill'
    | 'plugin'
    | 'mcp'
    | 'hive'
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

const WORKING_STATES: Record<WorkingPhase, {frames: string[]; text: string; color: string}> = {
    thinking: {frames: ['◜ ', '◠ ', '◝ ', '◞ '], text: 'thinking', color: 'cyan'},
    querying: {frames: ['▰▱▱', '▰▰▱', '▰▰▰', '▱▰▰'], text: 'working', color: 'blueBright'},
    streaming: {frames: ['›  ', '›› ', '›››', ' ››'], text: 'streaming response', color: 'cyan'},
    tool: {frames: ['✣ ', '✥ ', '✣ ', '✥ '], text: 'using tools', color: 'green'},
    skill: {frames: ['✦ ', '✧ ', '✦ ', '✧ '], text: 'using skills', color: 'magentaBright'},
    plugin: {frames: ['◫ ', '◧ ', '◨ ', '◫ '], text: 'loading plugins', color: 'yellowBright'},
    mcp: {frames: ['◎ ', '◉ ', '◎ ', '◉ '], text: 'calling mcp', color: 'cyanBright'},
    hive: {frames: ['⬡ ', '⬢ ', '⬣ ', '⬢ '], text: 'syncing hive', color: 'blueBright'},
    evolution: {frames: ['↺ ', '↻ ', '↺ ', '↻ '], text: 'evolving', color: 'greenBright'},
    self_improvement: {frames: ['△ ', '▲ ', '△ ', '▲ '], text: 'self improving', color: 'greenBright'},
    knowledge: {frames: ['✶ ', '✷ ', '✶ ', '✷ '], text: 'loading knowledge', color: 'yellow'},
    memory: {frames: ['◨ ', '◧ ', '◩ ', '◪ '], text: 'reading memory', color: 'yellowBright'},
    no_planning: {frames: ['·  ', '·· ', '···', ' ··'], text: 'direct response', color: 'grey'},
    simple_planning: {frames: ['□  ', '▣  ', '▣▣ ', '▣▣▣'], text: 'simple planning', color: 'cyan'},
    advance_planning: {frames: ['▁▃▅', '▂▄▆', '▃▅▇', '▄▆█'], text: 'advance planning', color: 'cyanBright'},
    auditing: {frames: ['◰ ', '◳ ', '◲ ', '◱ '], text: 'auditing', color: 'yellowBright'},
    verifying: {frames: ['✓  ', '✓· ', '✓✓ ', '✓✓✓'], text: 'verifying', color: 'greenBright'},
    working: {frames: ['▖ ', '▘ ', '▝ ', '▗ '], text: 'working', color: 'white'}
};
const READ_TOOLS = new Set(['read', 'glob', 'grep', 'find', 'ls', 'diagnostics', 'warpgrep']);
const WRITE_TOOLS = new Set(['edit', 'write', 'patch', 'multi_edit', 'multiedit', 'apply_patch', 'file_edit', 'write_file']);
const RUN_TOOLS = new Set(['bash', 'shell', 'exec', 'run', 'run_command', 'terminal', 'powershell', 'cmd']);
const SEARCH_TOOLS = new Set(['search', 'web_search', 'websearch', 'browser_search', 'grep', 'warpgrep']);
const TODO_TOOLS = new Set(['todo', 'todo_write', 'task', 'task_update', 'update_plan', 'plan']);

const COMMANDS = [
    {name: '/add-dir', description: 'Add extra working directory'},
    {name: '/agents', description: 'Switch or list agents', aliases: ['/agent']},
    {name: '/api', description: 'Check or start CLI API'},
    {name: '/advisor', description: 'Show advisor feature status'},
    {name: '/back', description: 'Return right panel to default'},
    {name: '/background', description: 'Show background session support', aliases: ['/bg']},
    {name: '/batch', description: 'Start multi-agent batch workflow'},
    {name: '/build', description: 'Build GUI or compile CLI'},
    {name: '/branch', description: 'Show current git branch'},
    {name: '/btw', description: 'Ask a side note without special handling'},
    {name: '/cat', description: 'Preview a workspace file'},
    {name: '/cd', description: 'Move CLI working directory'},
    {name: '/chrome', description: 'Show Chrome integration status'},
    {name: '/check', description: 'Run focused checks', aliases: ['/test', '/tests']},
    {name: '/claude-api', description: 'Show Claude API migration support'},
    {name: '/clear', description: 'Clear visible CLI history'},
    {name: '/close', description: 'Close right panel detail', aliases: ['/panel']},
    {name: '/code-review', description: 'Review current git diff'},
    {name: '/color', description: 'Show color/theme control'},
    {name: '/commands', description: 'Show command list', aliases: ['/help', '/']},
    {name: '/compact', description: 'Compact visible CLI history'},
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
    {name: '/exit', description: 'Exit the CLI', aliases: ['/quit']},
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
    {name: '/plan', description: 'Switch to plan permission mode'},
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
    {name: '/sandbox', description: 'Switch permission sandbox mode'},
    {name: '/scheduler', description: 'Show scheduler feature state'},
    {name: '/schedule', description: 'Show scheduler feature state', aliases: ['/routines']},
    {name: '/scroll-speed', description: 'Show scroll speed support'},
    {name: '/security-review', description: 'Review current diff for security risks'},
    {name: '/setup-bedrock', description: 'Show Bedrock provider setup help'},
    {name: '/setup-vertex', description: 'Show Vertex provider setup help'},
    {name: '/settings', description: 'Alias for config'},
    {name: '/simplify', description: 'Review diff for simplification'},
    {name: '/skills', description: 'List installed skills', aliases: ['/skill']},
    {name: '/status', description: 'Show kernel status'},
    {name: '/statusline', description: 'Show status line settings'},
    {name: '/stickers', description: 'Show sticker support'},
    {name: '/stop', description: 'Stop current thinking stream'},
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

const commandDefinitionFor = (value: string) => COMMANDS.find(command =>
    command.name === value || command.aliases?.includes(value)
);

const estimateTokens = (value: string) => Math.ceil(value.replace(/\s+/g, ' ').trim().length / 4);

const formatTokens = (value: number) => {
    if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
    return `${value}`;
};

const formatContextPercent = (tokens: number, limit: number) => {
    if (limit <= 0 || tokens <= 0) return '0%';
    const percent = (tokens / limit) * 100;
    if (percent < 1) return '<1%';
    return `${Math.min(100, Math.round(percent))}%`;
};

const compactTaskSubject = (value: string, maxLength = 82) => {
    const normalized = value.replace(/\s+/g, ' ').trim();
    if (normalized.length <= maxLength) return normalized;
    return `${normalized.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…`;
};

const taskStatusGlyph = (status: string) => {
    const normalized = status.toLowerCase();
    if (normalized.includes('complete') || normalized.includes('done')) return '✓';
    if (normalized.includes('running') || normalized.includes('progress')) return '◐';
    if (normalized.includes('error') || normalized.includes('fail')) return '!';
    return '□';
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

const commandMatches = (query: string) => {
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

const timelineColor = (kind: TimelineKind) => {
    if (kind === 'read') return 'blue';
    if (kind === 'write') return 'cyan';
    if (kind === 'tool') return 'blueBright';
    if (kind === 'success') return 'green';
    if (kind === 'error') return 'red';
    if (kind === 'text') return 'grey';
    return 'grey30';
};

const timelineGlyph = (event: TimelineEvent) => {
    if (event.kind === 'error') return '▆';
    if (event.kind === 'success') return '▇';
    if (event.weight >= 220) return '█';
    if (event.weight >= 120) return '▇';
    if (event.weight >= 60) return '▅';
    if (event.weight >= 20) return '▃';
    return '▂';
};

const classifyTool = (toolName: string): TimelineKind => {
    const normalized = toolName.toLowerCase();
    if (READ_TOOLS.has(normalized)) return 'read';
    if (WRITE_TOOLS.has(normalized)) return 'write';
    return 'tool';
};

const inferActivityKind = (toolName: string, params: Record<string, any>): ActivityKind => {
    const normalized = toolName.toLowerCase();
    const blob = `${normalized} ${JSON.stringify(params || {})}`.toLowerCase();

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

const inferWorkingPhaseFromTool = (toolName: string, params: Record<string, any>): WorkingPhase => {
    const normalized = toolName.toLowerCase();
    const blob = `${normalized} ${JSON.stringify(params || {})}`.toLowerCase();

    if (blob.includes('self_improvement') || blob.includes('improvement')) return 'self_improvement';
    if (blob.includes('evolution')) return 'evolution';
    if (blob.includes('memory')) return 'memory';
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

const inferWorkingPhaseFromText = (text: string): WorkingPhase | null => {
    const normalized = text.toLowerCase();
    if (!normalized.trim()) return null;
    if (normalized.includes('self improvement')) return 'self_improvement';
    if (normalized.includes('evolution')) return 'evolution';
    if (normalized.includes('memory')) return 'memory';
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

const statusColor = (status: string) => {
    const normalized = status.toLowerCase();
    if (normalized.includes('error') || normalized.includes('fail')) return 'red';
    if (normalized.includes('done') || normalized.includes('complete')) return 'green';
    if (normalized.includes('progress') || normalized.includes('running')) return 'cyan';
    return 'grey30';
};

const activityColor = (kind: ActivityKind) => {
    if (kind === 'file') return 'grey';
    if (kind === 'search') return 'blueBright';
    if (kind === 'todo') return 'green';
    if (kind === 'run' || kind === 'terminal') return 'cyan';
    if (kind === 'mcp') return 'magenta';
    if (kind === 'skill') return 'yellowBright';
    if (kind === 'plugin') return 'yellow';
    if (kind === 'hive') return 'cyanBright';
    return 'blueBright';
};

const activityGlyph = (kind: ActivityKind) => {
    if (kind === 'file') return '✎';
    if (kind === 'search') return '⌕';
    if (kind === 'todo') return '☑';
    if (kind === 'run' || kind === 'terminal') return '▹';
    if (kind === 'mcp') return '◇';
    if (kind === 'skill') return '✦';
    if (kind === 'plugin') return '⬢';
    if (kind === 'hive') return '⬡';
    return '◦';
};

const getFileName = (value: string) => value.split(/[/\\]/).pop() || value;

const cleanPreview = (value: unknown, lines = 14) => String(value || '')
    .replace(/\r\n/g, '\n')
    .split('\n')
    .slice(0, lines)
    .join('\n')
    .trim();

const codePreviewLines = (value: string, limit = 36) => cleanPreview(value, limit)
    .split('\n')
    .filter((line, index, lines) => line.length > 0 || index < lines.length - 1)
    .map((line, index) => `${String(index + 1).padStart(3, ' ')}  ${line}`);

const formatToolInput = (params: Record<string, any>) => Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .filter(([key]) => !['file_text', 'content', 'new_str', 'new_string', 'old_str'].includes(key))
    .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
    .join('\n');

const runLocal = async (file: string, args: string[], cwd = PROJECT_ROOT, timeout = 20000) => {
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

const runLocalResult = async (file: string, args: string[], cwd = PROJECT_ROOT, timeout = 20000) => {
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

const startDetached = (file: string, args: string[], cwd = PROJECT_ROOT) => {
    const child = spawn(file, args, {
        cwd,
        detached: true,
        stdio: 'ignore',
        windowsHide: true
    });
    child.unref();
};

const commandExists = async (command: string) => {
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

const safeRelativePath = (input: string) => {
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

const resolveInputAttachments = async (value: string) => {
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

const attachmentPrompt = (prompt: string, files: Array<{path: string; name: string; size: number; kind: string}>) => {
    if (files.length === 0) return prompt;
    const cleanPrompt = prompt.trim() || 'Please inspect the attached file(s).';
    const fileLines = files.map(file => `- ${file.name} (${file.kind}, ${formatTokens(file.size)}B): ${file.path}`);
    return `${cleanPrompt}\n\nAttached files:\n${fileLines.join('\n')}`;
};

const saveClipboardImage = async () => {
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

const listDirectory = async (target: string, limit = 40) => {
    const entries = await readdir(target, {withFileTypes: true});
    return entries
        .filter(entry => !['node_modules', '.git', '__pycache__', '.venv'].includes(entry.name))
        .slice(0, limit)
        .map(entry => `${entry.isDirectory() ? '[DIR] ' : '      '}${entry.name}`)
        .join('\n');
};

const treeDirectory = async (target: string, depth = 2, prefix = ''): Promise<string[]> => {
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

const readYamlSectionNames = async (filePath: string) => {
    const content = await readFile(filePath, 'utf8');
    return content
        .split(/\r?\n/)
        .filter(line => /^[A-Za-z0-9_.-]+:\s*$/.test(line))
        .map(line => line.replace(':', '').trim());
};

const activityFromTool = (toolName: string, params: Record<string, any>): Omit<ActivityItem, 'id' | 'number'> => {
    const normalized = toolName.toLowerCase();
    const kind = inferActivityKind(toolName, params);
    const rawPath = params.path || params.filename || params.file || params.filepath || params.uri || '';
    const fileName = rawPath ? getFileName(String(rawPath)) : '';
    const command = String(params.command || params.cmd || params.script || '');
    const query = String(params.query || params.q || params.pattern || params.search || params.prompt || '');

    if (SEARCH_TOOLS.has(normalized) || normalized.includes('search')) {
        return {
            kind: 'search',
            title: normalized.includes('web') || params.url ? 'Searched web' : 'Searched files',
            summary: query || command || toolName,
            status: 'running',
            command: query || command || undefined,
            detail: formatToolInput(params),
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

const readTodoMarkdown = async (): Promise<TaskItem[]> => {
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

const clearTerminalForInk = () => {
    if (!process.stdout.isTTY) return;
    process.stdout.write('\x1b[2J\x1b[3J\x1b[H');
};

const extractSsePayload = (frame: string) => frame
    .replace(/\r/g, '')
    .split('\n')
    .filter(line => !line.startsWith('event:'))
    .map(line => line.startsWith('data:') ? line.replace(/^data:\s?/, '') : line)
    .join('\n');

const cleanVisibleAssistantText = (text: string) => {
    let cleaned = String(text || '');
    cleaned = cleaned.replace(/\[NEXUS_BOOT\]:[^\n]*/g, '');
    cleaned = cleaned.replace(/\[THINKING:[^\]]+\]/g, '');
    cleaned = cleaned.replace(/<thinking>[\s\S]*?<\/thinking>/gi, '');
    cleaned = cleaned.replace(/<\/?thinking>/gi, '');
    cleaned = cleaned.replace(/TASK_COMPLETE/g, '');
    cleaned = cleaned.replace(/\n{3,}/g, '\n\n');
    return cleaned.trim();
};

const logoColorForColumn = (column: number, width: number, frame = 0) => {
    const ratio = width <= 1 ? 0 : column / (width - 1);
    const drift = ((frame % 48) / 48) * 0.35;
    const index = Math.min(LOGO_GRADIENT.length - 1, Math.floor(((ratio + drift) % 1) * LOGO_GRADIENT.length));
    return LOGO_GRADIENT[index];
};

const LogoLine = React.memo(({line, frame}: {line: string; frame: number}) => (
    <Text bold>
        {Array.from(line).map((char, index) => {
            if (LOGO_OUTLINE_CHARS.has(char)) {
                return (
                    <Text key={`${index}-${char}`} color="grey30" dimColor>
                        {char}
                    </Text>
                );
            }

            return (
                <Text key={`${index}-${char}`} color={logoColorForColumn(index, line.length, frame)}>
                    {char}
                </Text>
            );
        })}
    </Text>
));

const Banner = React.memo(({width, frame}: {width: number; frame: number}) => {
    const logoWidth = Math.min(58, Math.max(1, width));

    return (
        <Box
            flexDirection="column"
            alignItems="center"
            flexShrink={0}
            height={8}
            paddingTop={1}
            marginBottom={0}
            backgroundColor={THEME.panelAltBg}
        >
            <Box flexDirection="column" width={logoWidth} alignItems="center">
                {NEXUS_LOGO.map(line => (
                    <LogoLine key={line} line={line} frame={frame} />
                ))}
            </Box>
            <Box marginTop={0}>
                <Text color="grey30">ask </Text>
                <Text color="grey">edit </Text>
                <Text color="grey30">run </Text>
                <Text color="magenta">/help</Text>
                <Text color="grey30"> commands</Text>
            </Box>
        </Box>
    );
});

const WorkingStatus = React.memo(({frame, width, phase}: {frame: number; width: number; phase: WorkingPhase}) => {
    const state = WORKING_STATES[phase];
    const pulse = ['.  ', '.. ', '...'][frame % 3];
    const symbol = state.frames[frame % state.frames.length];

    return (
        <Box width={width} backgroundColor={THEME.panelSoftBg} paddingX={1}>
            <Text color={state.color}>{symbol} </Text>
            <Text color="grey">NEXUS </Text>
            <Text color={state.color}>{state.text}</Text>
            <Text color="grey">{pulse}</Text>
        </Box>
    );
});

const HistoryItem = ({
    msg,
    activity,
    width,
    index
}: {
    msg: Message;
    activity?: ActivityItem;
    width: number;
    index: number;
}) => {
    if (msg.role === 'assistant' && msg.content.trim().length === 0) {
        return null;
    }

    if (msg.role === 'activity' && activity) {
        return (
            <Box marginTop={index > 0 ? 1 : 0} marginBottom={1} width={width}>
                <Text color={activityColor(activity.kind)}>{activityGlyph(activity.kind)} </Text>
                <Text color="grey">{activity.title}</Text>
                <Text color="grey30">  › </Text>
                <Text color="grey30">/open {activity.number}</Text>
            </Box>
        );
    }

    const prefix = msg.role === 'user' ? '> ' : msg.role === 'command' ? '◆ ' : msg.role === 'system' ? '! ' : '';
    const prefixColor = msg.role === 'user' ? 'blue' : msg.role === 'command' ? 'cyan' : msg.role === 'system' ? 'red' : 'magenta';
    const contentWidth = Math.max(1, width - (prefix ? 2 : 0));
    const topGap = msg.role === 'user' && index > 0 ? 1 : 0;
    const bottomGap = msg.role === 'assistant' || msg.role === 'command' || msg.role === 'system' ? 1 : 0;

    return (
        <Box marginTop={topGap} marginBottom={bottomGap} width={width}>
            {prefix && (
                <Box width={2} flexShrink={0}>
                    <Text bold color={prefixColor}>{prefix}</Text>
                </Box>
            )}
            <Box width={contentWidth}>
                <Text wrap="wrap" color={msg.role === 'system' ? "red" : msg.role === 'command' ? "grey" : "white"}>
                    {msg.content}
                </Text>
            </Box>
        </Box>
    );
};

interface ChatLine {
    key: string;
    text: string;
    color: string;
    prefix?: string;
    prefixColor?: string;
    reservePrefix?: boolean;
}

const wrapPlainLine = (line: string, width: number) => {
    const normalized = line.replace(/\t/g, '    ');
    if (normalized.length === 0) return [''];

    const rows: string[] = [];
    let rest = normalized;
    while (rest.length > width) {
        let cut = rest.lastIndexOf(' ', width);
        if (cut <= 0) cut = width;
        rows.push(rest.slice(0, cut).trimEnd());
        rest = rest.slice(cut).trimStart();
    }
    rows.push(rest);
    return rows;
};

const buildChatLines = (history: Message[], activityItems: ActivityItem[], width: number): ChatLine[] => {
    const rows: ChatLine[] = [];
    const appendGap = (key: string) => {
        if (rows.length > 0 && rows[rows.length - 1].text !== '') {
            rows.push({key, text: '', color: 'grey'});
        }
    };

    const appendWrapped = (
        key: string,
        content: string,
        color: string,
        prefix = '',
        prefixColor = 'grey'
    ) => {
        const reservePrefix = prefix.length > 0;
        const contentWidth = Math.max(1, width - (reservePrefix ? 2 : 0));
        const sourceLines = content.replace(/\r/g, '').split('\n');
        let first = true;

        for (const sourceLine of sourceLines) {
            for (const wrapped of wrapPlainLine(sourceLine, contentWidth)) {
                rows.push({
                    key: `${key}-${rows.length}`,
                    text: wrapped,
                    color,
                    prefix: first ? prefix : undefined,
                    prefixColor,
                    reservePrefix
                });
                first = false;
            }
        }
    };

    history.forEach((msg, index) => {
        if (msg.role === 'assistant' && msg.content.trim().length === 0) return;

        if (msg.role === 'user') {
            appendGap(`before-user-${index}`);
            appendWrapped(`user-${index}`, msg.content, 'white', '> ', 'blue');
            return;
        }

        if (msg.role === 'activity') {
            const activity = msg.activityId
                ? activityItems.find(item => item.id === msg.activityId)
                : undefined;
            if (!activity) return;
            appendGap(`before-activity-${index}`);
            appendWrapped(
                `activity-${index}`,
                `${activityGlyph(activity.kind)} ${activity.title}  > /open ${activity.number}`,
                'grey'
            );
            appendGap(`after-activity-${index}`);
            return;
        }

        if (msg.role === 'command') {
            appendWrapped(`command-${index}`, msg.content, 'grey', '◆ ', 'cyan');
            appendGap(`after-command-${index}`);
            return;
        }

        if (msg.role === 'system') {
            appendWrapped(`system-${index}`, msg.content, 'red', '! ', 'red');
            appendGap(`after-system-${index}`);
            return;
        }

        appendWrapped(`assistant-${index}`, cleanVisibleAssistantText(msg.content), 'white');
        appendGap(`after-assistant-${index}`);
    });

    return rows;
};

const appendVoicePreviewLines = (
    rows: ChatLine[],
    width: number,
    voiceMode: 'off' | 'auto' | 'manual' | 'text',
    voicePhase: string,
    voiceTranscriptPreview: string,
    voiceReplyPreview: string,
    history: Message[]
) => {
    if (voiceMode === 'off') return rows;

    const latestUser = [...history].reverse().find(msg => msg.role === 'user')?.content.trim() || '';
    const latestAssistant = [...history].reverse().find(msg => msg.role === 'assistant')?.content.trim() || '';
    const transcript = String(voiceTranscriptPreview || '').trim();
    const reply = String(voiceReplyPreview || '').trim();
    const normalizedLatestAssistant = cleanVisibleAssistantText(latestAssistant);

    const appendWrapped = (
        key: string,
        content: string,
        color: string,
        prefix = '',
        prefixColor = 'grey'
    ) => {
        const reservePrefix = prefix.length > 0;
        const contentWidth = Math.max(1, width - (reservePrefix ? 2 : 0));
        const sourceLines = content.replace(/\r/g, '').split('\n');
        let first = true;

        for (const sourceLine of sourceLines) {
            for (const wrapped of wrapPlainLine(sourceLine, contentWidth)) {
                rows.push({
                    key: `${key}-${rows.length}`,
                    text: wrapped,
                    color,
                    prefix: first ? prefix : undefined,
                    prefixColor,
                    reservePrefix
                });
                first = false;
            }
        }
    };

    if (rows.length > 0 && rows[rows.length - 1].text !== '') {
        rows.push({key: `voice-gap-${rows.length}`, text: '', color: 'grey'});
    }

    if (transcript && transcript !== latestUser) {
        appendWrapped(`voice-heard-${rows.length}`, transcript, 'green', '> ', 'blue');
    }

    if (reply && reply !== normalizedLatestAssistant) {
        appendWrapped(`voice-reply-${rows.length}`, reply, 'yellow');
    }

    const statusText = `🎙 ${voiceMode} · ${voicePhaseLabel(voicePhase)}`;
    appendWrapped(`voice-status-${rows.length}`, statusText, voicePhaseColor(voicePhase));

    return rows;
};

const ChatLineView = React.memo(({line, width}: {line: ChatLine; width: number}) => {
    const contentWidth = Math.max(1, width - (line.reservePrefix ? 2 : 0));

    return (
        <Box width={width}>
            {line.reservePrefix && (
                <Box width={2} flexShrink={0}>
                    <Text bold color={line.prefixColor}>{line.prefix || '  '}</Text>
                </Box>
            )}
            <Box width={contentWidth}>
                <Text color={line.color}>{line.text || ' '}</Text>
            </Box>
        </Box>
    );
});

const mouseWheelDirection = (value: string, maxX: number) => {
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

const parseQuestionMarker = (text: string): PendingQuestion | null => {
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

const stripQuestionMarkers = (text: string) => text.replace(/\[QUESTION:.*?\]/gs, '');

const detectChoiceQuestion = (text: string): PendingQuestion | null => {
    const lines = text.replace(/\r/g, '').split('\n').map(line => line.trim()).filter(Boolean);
    const optionMatches = lines
        .map((line, index) => ({index, match: line.match(/^(?:[-*]\s*)?(?:\(?([A-Ha-h1-8])\)?[.)-])\s+(.+)$/)}))
        .filter((item): item is {index: number; match: RegExpMatchArray} => Boolean(item.match))
        .slice(0, 8);
    const options = optionMatches.map(item => item.match[2].trim());

    if (options.length < 2) return null;

    const firstOptionIndex = optionMatches[0]?.index ?? -1;
    const contiguous = optionMatches.every((item, index) => index === 0 || item.index === optionMatches[index - 1].index + 1);
    if (!contiguous || firstOptionIndex < 0) return null;

    const promptLines = firstOptionIndex > 0 ? lines.slice(Math.max(0, firstOptionIndex - 3), firstOptionIndex) : [];
    const prompt = promptLines.join(' ') || 'Choose how Nexus should continue.';
    const promptLooksLikeQuestion = /[?]/.test(prompt) || /\b(choose|pick|select|option|which|what|question)\b/i.test(prompt);
    if (!promptLooksLikeQuestion) return null;

    return {
        id: `question-${Date.now()}`,
        prompt,
        options,
        allowCustom: true
    };
};

const ContextMeter = React.memo(({timeline, usage}: {timeline: TimelineEvent[]; usage: UsageStats}) => {
    const rawPercent = usage.contextLimit > 0 ? Math.min(100, (usage.contextTokens / usage.contextLimit) * 100) : 0;
    const filledCells = rawPercent > 0
        ? Math.max(1, Math.min(CONTEXT_BAR_WIDTH, Math.round((rawPercent / 100) * CONTEXT_BAR_WIDTH)))
        : 0;
    const emptyCells = CONTEXT_BAR_WIDTH - filledCells;
    const contextLabel = formatContextPercent(usage.contextTokens, usage.contextLimit);
    const visibleTimeline = timeline.length > 0 ? timeline.slice(-MAX_TIMELINE_ITEMS) : [
        {kind: 'step' as TimelineKind, weight: 1, label: 'Session ready'}
    ];
    const contextColor = rawPercent >= 85 ? 'red' : rawPercent >= 60 ? 'yellow' : 'green';

    return (
        <Box flexDirection="column" marginBottom={1}>
            <Box justifyContent="space-between">
                <Text color="white" bold>Context</Text>
                <Text color={contextColor}>{contextLabel}</Text>
            </Box>

            <Box>
                <Text color={contextColor}>{'█'.repeat(filledCells)}</Text>
                <Text color="grey30">{'░'.repeat(emptyCells)}</Text>
            </Box>

            <Box>
                <Text color="grey">Tokens </Text>
                <Text color="grey30">↑ </Text>
                <Text color="grey">{formatTokens(usage.inputTokens)} </Text>
                <Text color="grey30">↓ </Text>
                <Text color="grey">{formatTokens(usage.outputTokens)}</Text>
                <Text color="grey30"> · total </Text>
                <Text color="grey">{formatTokens(usage.contextTokens)}</Text>
            </Box>

            <Box marginTop={1}>
                <Text color="grey30">Activity </Text>
                {visibleTimeline.slice(-18).map((event, index) => (
                    <Text key={`${event.kind}-${event.label}-${index}`} color={timelineColor(event.kind)}>
                        {timelineGlyph(event)}
                    </Text>
                ))}
            </Box>
        </Box>
    );
});

const TodoPanelBody = React.memo(({tasks, width}: {tasks: TaskItem[]; width: number}) => {
    const subjectWidth = Math.max(16, width - 4);

    if (tasks.length === 0) {
        return <Box flexGrow={1} />;
    }

    return (
        <Box flexDirection="column" flexGrow={1}>
            <Box flexDirection="column" marginBottom={1}>
                <Text color="white" bold>Todo</Text>
                {tasks.slice(0, 8).map(task => {
                    const glyph = taskStatusGlyph(task.status);
                    const color = statusColor(task.status);
                    const completed = glyph === '✓';

                    return (
                        <Box key={task.id} marginTop={1}>
                            <Box width={2} flexShrink={0}>
                                <Text color={color}>{glyph}</Text>
                            </Box>
                            <Box flexDirection="column" width={subjectWidth}>
                                <Text color={completed ? 'green' : 'grey'} dimColor={completed} strikethrough={completed} wrap="wrap">
                                    {compactTaskSubject(task.subject)}
                                </Text>
                                {glyph !== '□' && !completed && (
                                    <Text color={color}>{task.status}</Text>
                                )}
                            </Box>
                        </Box>
                    );
                })}
            </Box>

            <Box flexGrow={1} />
        </Box>
    );
});

const WorkspacePanelBody = React.memo(({
    tasks,
    activityItems,
    pendingQuestion,
    voiceMode,
    voicePhase,
    voiceTranscriptPreview,
    voiceReplyPreview,
    motionFrame
}: {
    tasks: TaskItem[];
    activityItems: ActivityItem[];
    pendingQuestion: PendingQuestion | null;
    voiceMode: 'off' | 'auto' | 'manual' | 'text';
    voicePhase: string;
    voiceTranscriptPreview: string;
    voiceReplyPreview: string;
    motionFrame: number;
}) => {
    const recent = activityItems.slice(0, 6);

    return (
        <Box flexDirection="column" flexGrow={1}>
            <Box marginBottom={1}>
                <Text color="white" bold>Status</Text>
            </Box>

            <Text color="grey">
                voice: <Text color={voiceMode === 'off' ? 'grey30' : 'green'}>{voiceMode}</Text>
                <Text color="grey30"> · </Text>
                phase: <Text color={voicePhaseColor(voicePhase)}>{voicePhaseLabel(voicePhase)}</Text>
            </Text>

            {voiceMode !== 'off' && (
                <Box marginTop={1} flexDirection="column">
                    <Text color="white" bold>Voice</Text>
                    <VoiceEqualizer phase={voicePhase} frame={motionFrame} bars={10} />
                    <Text color={voicePhaseColor(voicePhase)}>{voicePhaseLabel(voicePhase)}</Text>
                    {voiceTranscriptPreview ? (
                        <Text color="grey" wrap="wrap">heard: {voiceTranscriptPreview}</Text>
                    ) : null}
                    {voiceReplyPreview ? (
                        <Text color="grey" wrap="wrap">reply: {voiceReplyPreview}</Text>
                    ) : null}
                </Box>
            )}

            {pendingQuestion && (
                <Box marginTop={1} flexDirection="column">
                    <Text color="white" bold>Question ready</Text>
                    <Text color="grey" wrap="wrap">{pendingQuestion.prompt}</Text>
                </Box>
            )}

            <Box marginTop={1} flexDirection="column">
                <Text color="white" bold>Recent Activity</Text>
                {recent.length === 0 ? (
                    <Text color="grey30">No tracked activity yet</Text>
                ) : (
                    recent.map(item => (
                        <Box key={item.id} marginTop={1}>
                            <Box width={2} flexShrink={0}>
                                <Text color={activityColor(item.kind)}>{activityGlyph(item.kind)}</Text>
                            </Box>
                            <Box flexDirection="column">
                                <Text color="white" wrap="wrap">{item.title}</Text>
                                <Text color="grey" wrap="wrap">{item.summary}</Text>
                            </Box>
                        </Box>
                    ))
                )}
            </Box>

            {tasks.length > 0 && (
                <Box marginTop={1} flexDirection="column">
                    <Text color="white" bold>Todo</Text>
                    {tasks.slice(0, 4).map(task => (
                        <Box key={task.id} marginTop={1}>
                            <Box width={2} flexShrink={0}>
                                <Text color={statusColor(task.status)}>{taskStatusGlyph(task.status)}</Text>
                            </Box>
                            <Text color="grey" wrap="wrap">{compactTaskSubject(task.subject)}</Text>
                        </Box>
                    ))}
                </Box>
            )}

            <Box flexGrow={1} />
        </Box>
    );
});

const CommandPalette = React.memo(({matches, selectedIndex}: {matches: typeof COMMANDS; selectedIndex: number}) => {
    if (matches.length === 0) return null;

    return (
        <Box flexDirection="column" marginX={1} marginBottom={0} borderStyle="single" borderColor={THEME.border} backgroundColor={THEME.paletteBg}>
            {matches.map((command, index) => {
                const selected = index === selectedIndex;
                return (
                    <Box key={command.name} backgroundColor={selected ? '#ffb27c' : THEME.paletteBg}>
                        <Box width={18}>
                            <Text color={selected ? 'black' : 'white'} bold>{command.name}</Text>
                        </Box>
                        <Text color={selected ? 'black' : 'grey'}>{command.description}</Text>
                    </Box>
                );
            })}
            <Box justifyContent="flex-end" backgroundColor={THEME.paletteBg}>
                <Text color="grey30">tab complete  ↑↓ select  enter run</Text>
            </Box>
        </Box>
    );
});

const ActivityPanelBody = React.memo(({activity}: {activity: ActivityItem | null}) => (
    <Box flexDirection="column" flexGrow={1}>
        {activity && (
            <>
                <Box justifyContent="space-between" marginBottom={1}>
                    <Text color={activityColor(activity.kind)} bold>{activity.title}</Text>
                    <Text color={statusColor(activity.status)}>{activity.status}</Text>
                </Box>

                <Box marginBottom={1}>
                    <Text color="grey" wrap="wrap">{activity.summary}</Text>
                </Box>

                {activity.files && activity.files.length > 0 && (
                    <Box flexDirection="column" marginBottom={1}>
                        <Text color="white" bold>Files</Text>
                        {activity.files.map(file => (
                            <Text key={file} color="grey">{file}</Text>
                        ))}
                    </Box>
                )}

                {activity.operation && (
                    <Box justifyContent="space-between" marginBottom={1}>
                        <Text color="grey">Operation</Text>
                        <Text color="yellow">{activity.operation}</Text>
                    </Box>
                )}

                {activity.command && (
                    <Box flexDirection="column" marginBottom={1}>
                        <Text color="white" bold>Command</Text>
                        <Text color="cyan" wrap="wrap">{activity.command}</Text>
                    </Box>
                )}

                {activity.preview && (
                    <Box flexDirection="column" marginBottom={1}>
                        <Text color="white" bold>Code</Text>
                        <Box flexDirection="column" borderStyle="single" borderColor={THEME.border} paddingX={1} marginTop={1}>
                            {codePreviewLines(activity.preview).map(line => (
                                <Text key={line} color="grey" wrap="wrap">{line}</Text>
                            ))}
                        </Box>
                    </Box>
                )}

                {activity.detail && (
                    <Box flexDirection="column" marginBottom={1}>
                        <Text color="white" bold>Input</Text>
                        <Text color="grey" wrap="wrap">{activity.detail}</Text>
                    </Box>
                )}

                {activity.output && (
                    <Box flexDirection="column" marginBottom={1}>
                        <Text color="white" bold>Output</Text>
                        <Text color="grey" wrap="wrap">{activity.output}</Text>
                    </Box>
                )}

                {activity.error && (
                    <Box flexDirection="column" marginBottom={1}>
                        <Text color="red" bold>Error</Text>
                        <Text color="red" wrap="wrap">{activity.error}</Text>
                    </Box>
                )}

                <Box marginTop={1}>
                    <Text color="grey30">/back returns to todo</Text>
                </Box>
            </>
        )}

        <Box flexGrow={1} />
    </Box>
));

const QuestionPanelBody = React.memo(({question}: {question: PendingQuestion | null}) => (
    <Box flexDirection="column" flexGrow={1}>
        <Box marginBottom={1}>
            <Text color="white" bold>Question</Text>
        </Box>

        {question ? (
            <>
                <Box marginBottom={1}>
                    <Text color="white" wrap="wrap">{question.prompt}</Text>
                </Box>

                {question.options.map((option, index) => (
                    <Box key={`${question.id}-${index}`} marginTop={1}>
                        <Box width={3}>
                            <Text color="cyan">{index + 1}.</Text>
                        </Box>
                        <Text color="white" wrap="wrap">{option}</Text>
                    </Box>
                ))}

                {question.allowCustom !== false && (
                    <Box marginTop={1}>
                        <Box width={3}>
                            <Text color="magenta">{question.options.length + 1}.</Text>
                        </Box>
                        <Text color="grey">write answer in chat box</Text>
                    </Box>
                )}

                <Box marginTop={1}>
                    <Text color="grey30">press number to choose, or type custom in chat box</Text>
                </Box>
            </>
        ) : (
            <Text color="grey30">No pending question</Text>
        )}

        <Box flexGrow={1} />
    </Box>
));

const HivePanelBody = React.memo(({agents, selectedAgentId, tasks}: {agents: AgentInfo[]; selectedAgentId: string | null; tasks: TaskItem[]}) => {
    const selectedAgent = agents.find(agent => agent.id === selectedAgentId) || null;
    const agentTasks = selectedAgent ? tasks.filter(task => task.agent === selectedAgent.id || task.agent === selectedAgent.name) : [];

    if (selectedAgent) {
        return (
            <Box flexDirection="column" flexGrow={1}>
                <Box marginBottom={1}>
                    <Text color="cyan" bold>{selectedAgent.name}</Text>
                </Box>
                <Box justifyContent="space-between">
                    <Text color="grey">Status</Text>
                    <Text color={statusColor(selectedAgent.status)}>{selectedAgent.status}</Text>
                </Box>
                {selectedAgent.description && (
                    <Box marginTop={1}>
                        <Text color="grey" wrap="wrap">{selectedAgent.description}</Text>
                    </Box>
                )}
                {agentTasks.length > 0 && (
                    <Box flexDirection="column" marginTop={1}>
                        <Text color="white" bold>Work</Text>
                        {agentTasks.map(task => (
                            <Box key={task.id} justifyContent="space-between">
                                <Text color="grey">{task.subject}</Text>
                                <Text color={statusColor(task.status)}>{task.status}</Text>
                            </Box>
                        ))}
                    </Box>
                )}
                <Box marginTop={1}>
                    <Text color="grey30">/back returns to hive</Text>
                </Box>
                <Box flexGrow={1} />
            </Box>
        );
    }

    return (
        <Box flexDirection="column" flexGrow={1}>
            <Box justifyContent="space-between" marginBottom={1}>
                <Text color="white" bold>Hive</Text>
                <Text color="green">{agents.length}</Text>
            </Box>
            {agents.length === 0 ? (
                <Text color="grey30">No workers active</Text>
            ) : (
                agents.map((agent, index) => (
                    <Box key={agent.id} justifyContent="space-between">
                        <Text color="cyan">{index + 1}. {agent.name}</Text>
                        <Text color={statusColor(agent.status)}>{agent.status}</Text>
                    </Box>
                ))
            )}
            {agents.length > 0 && (
                <Box marginTop={1}>
                    <Text color="grey30">type /hive 1 to open worker</Text>
                </Box>
            )}
            <Box marginTop={1}>
                <Text color="grey30">/close hides hive</Text>
            </Box>
            <Box flexGrow={1} />
        </Box>
    );
});

const NexusWorkspacePanel = React.memo(({
    timeline,
    usage,
    mode,
    agents,
    tasks,
    activityItems,
    pendingQuestion,
    selectedActivityId,
    selectedAgentId,
    width,
    height,
    voiceMode,
    voicePhase,
    voiceTranscriptPreview,
    voiceReplyPreview,
    motionFrame
}: NexusWorkspacePanelProps & {
    voiceMode: 'off' | 'auto' | 'manual' | 'text';
    voicePhase: string;
    voiceTranscriptPreview: string;
    voiceReplyPreview: string;
}) => {
    const selectedActivity = activityItems.find(activity => activity.id === selectedActivityId) || null;

    return (
        <Box
            flexDirection="column"
            width={width}
            height={height}
            borderStyle="single"
            borderColor={THEME.borderSoft}
            paddingX={1}
            paddingY={1}
            backgroundColor={THEME.panelBg}
        >
            <Box marginBottom={1}>
                <Text bold color="grey">◇ NEXUS WORKSPACE</Text>
            </Box>

            <ContextMeter timeline={timeline} usage={usage} />

            {mode === 'question' ? (
                <QuestionPanelBody question={pendingQuestion} />
            ) : mode === 'hive' || mode === 'agent' ? (
                <HivePanelBody agents={agents} selectedAgentId={mode === 'agent' ? selectedAgentId : null} tasks={tasks} />
            ) : mode === 'activity' ? (
                <ActivityPanelBody activity={selectedActivity} />
            ) : (
                <WorkspacePanelBody
                    tasks={tasks}
                    activityItems={activityItems}
                    pendingQuestion={pendingQuestion}
                    voiceMode={voiceMode}
                    voicePhase={voicePhase}
                    voiceTranscriptPreview={voiceTranscriptPreview}
                    voiceReplyPreview={voiceReplyPreview}
                    motionFrame={motionFrame}
                />
            )}
        </Box>
    );
});


const App = () => {
    const [input, setInput] = useState('');
    const [commandIndex, setCommandIndex] = useState(0);
    const [history, setHistory] = useState<Message[]>([]);
    const [sessionId, setSessionId] = useState('default');
    const [provider, setProvider] = useState('');
    const [model, setModel] = useState('');
    const [extraDirs, setExtraDirs] = useState<string[]>([]);
    const [activities, setActivities] = useState<string[]>([]);
    const [touchedFiles, setTouchedFiles] = useState<FileStatus[]>([]);
    const [lastChange, setLastChange] = useState<string>('');
    const [panelMode, setPanelMode] = useState<PanelMode>('workspace');
    const [voiceMode, setVoiceMode] = useState<'off' | 'auto' | 'manual' | 'text'>('off');
    const [voicePhase, setVoicePhase] = useState('off');
    const [voiceTranscriptPreview, setVoiceTranscriptPreview] = useState('');
    const [voiceReplyPreview, setVoiceReplyPreview] = useState('');
    const voiceSessionIdRef = useRef<string | null>(null);
    const voiceShutdownRef = useRef(false);
    const [agents, setAgents] = useState<AgentInfo[]>([]);
    const [tasks, setTasks] = useState<TaskItem[]>([]);
    const [activityItems, setActivityItems] = useState<ActivityItem[]>([]);
    const [pendingQuestion, setPendingQuestion] = useState<PendingQuestion | null>(null);
    const [selectedActivityId, setSelectedActivityId] = useState<string | null>(null);
    const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
    const [timeline, setTimeline] = useState<TimelineEvent[]>([
        {kind: 'step', weight: 1, label: 'Session ready'}
    ]);
    const [chatScroll, setChatScroll] = useState(0);
    const activityCounter = useRef(0);
    const previousChatLineCount = useRef(0);
    const voiceJustStartedRef = useRef(0);
    const [isThinking, setIsThinking] = useState(false);
    const [workingPhase, setWorkingPhase] = useState<WorkingPhase>('thinking');
    const [motionFrame, setMotionFrame] = useState(0);
    const [terminalSize, setTerminalSize] = useState({
        width: process.stdout.columns || 100,
        height: Math.max(process.stdout.rows || 30, 25)
    });
    const {exit} = useApp();
    const slashInput = input.trimStart();
    const slashToken = slashInput.startsWith('/') && !slashInput.includes(' ') ? slashInput : '';
    const slashMatches = slashToken ? commandMatches(slashToken) : [];
    const showCommandPalette = slashMatches.length > 0;
    const {width, height} = terminalSize;
    const isWide = width > 110;
    const sidebarWidth = isWide ? Math.min(52, Math.max(38, Math.floor(width * 0.30))) : 0;
    const leftPanelWidth = Math.max(40, width - sidebarWidth);
    const chatContentWidth = Math.max(20, leftPanelWidth - 2);
    const chatViewportHeight = Math.max(3, height - 12);
    const baseChatLines = buildChatLines(history, activityItems, chatContentWidth);
    const chatLines = appendVoicePreviewLines(
        [...baseChatLines],
        chatContentWidth,
        voiceMode,
        voicePhase,
        voiceTranscriptPreview,
        voiceReplyPreview,
        history
    );
    const visibleChatLineCount = Math.max(1, chatViewportHeight - (isThinking ? 1 : 0));
    const maxChatScroll = Math.max(0, chatLines.length - visibleChatLineCount);
    const safeChatScroll = Math.min(chatScroll, maxChatScroll);
    const chatEnd = chatLines.length - safeChatScroll;
    const visibleChatLines = chatLines.slice(Math.max(0, chatEnd - visibleChatLineCount), chatEnd);

    useEffect(() => {
        setCommandIndex(0);
    }, [slashToken]);

    useEffect(() => {
        const previous = previousChatLineCount.current;
        const delta = chatLines.length - previous;
        previousChatLineCount.current = chatLines.length;

        setChatScroll(scroll => {
            if (delta > 0 && scroll > 0) {
                return Math.min(maxChatScroll, scroll + delta);
            }
            return Math.min(scroll, maxChatScroll);
        });
    }, [chatLines.length, maxChatScroll]);

    useEffect(() => {
        if (!process.stdout.isTTY) return;
        process.stdout.write('\x1b[?1000h\x1b[?1002h\x1b[?1006h');
        return () => {
            process.stdout.write('\x1b[?1000l\x1b[?1002l\x1b[?1006l');
        };
    }, []);

    useEffect(() => {
        const timer = setInterval(() => {
            setMotionFrame(frame => (frame + 1) % 10000);
        }, 350);
        return () => clearInterval(timer);
    }, []);

    const stopVoiceIfRunning = async () => {
        if (voiceShutdownRef.current) return;
        voiceShutdownRef.current = true;
        try {
            const statusRes = await fetch(`${API_BASE}/voice/status`);
            const statusData = await statusRes.json();
            if (statusData?.running) {
                await fetch(`${API_BASE}/voice/stop`, {method: 'POST'});
            }
        } catch {
            // Best effort shutdown.
        } finally {
            setVoiceMode('off');
            setVoicePhase('off');
            setVoiceTranscriptPreview('');
            setVoiceReplyPreview('');
            voiceSessionIdRef.current = null;
            voiceShutdownRef.current = false;
        }
    };

    useEffect(() => {
        const handleProcessShutdown = () => {
            syncStopVoiceProcess();
        };

        process.once('SIGINT', handleProcessShutdown);
        process.once('SIGTERM', handleProcessShutdown);
        process.once('SIGHUP', handleProcessShutdown);
        process.once('beforeExit', handleProcessShutdown);
        process.once('exit', handleProcessShutdown);

        return () => {
            process.removeListener('SIGINT', handleProcessShutdown);
            process.removeListener('SIGTERM', handleProcessShutdown);
            process.removeListener('SIGHUP', handleProcessShutdown);
            process.removeListener('beforeExit', handleProcessShutdown);
            process.removeListener('exit', handleProcessShutdown);
            handleProcessShutdown();
        };
    }, []);

    useInput((value, key) => {
        const scrollPage = Math.max(1, visibleChatLineCount - 2);
        const wheelDirection = mouseWheelDirection(value, leftPanelWidth);

        if (panelMode === 'question' && pendingQuestion && /^[1-9]$/.test(value)) {
            const selectedIndex = Number(value) - 1;
            if (selectedIndex >= 0 && selectedIndex < pendingQuestion.options.length) {
                setInput(pendingQuestion.options[selectedIndex]);
                setPendingQuestion(null);
                setPanelMode('workspace');
            } else if (pendingQuestion.allowCustom !== false && selectedIndex === pendingQuestion.options.length) {
                setInput('');
            }
            return;
        }

        if (wheelDirection !== 0) {
            setChatScroll(scroll => Math.max(0, Math.min(maxChatScroll, scroll + (wheelDirection * 3))));
            return;
        }

        if (key.pageUp || (key.ctrl && value === 'u')) {
            setChatScroll(scroll => Math.min(maxChatScroll, scroll + scrollPage));
            return;
        }

        if (key.pageDown || (key.ctrl && value === 'd')) {
            setChatScroll(scroll => Math.max(0, scroll - scrollPage));
            return;
        }

        if (!showCommandPalette && input.length === 0 && key.upArrow) {
            setChatScroll(scroll => Math.min(maxChatScroll, scroll + 1));
            return;
        }

        if (!showCommandPalette && input.length === 0 && key.downArrow) {
            setChatScroll(scroll => Math.max(0, scroll - 1));
            return;
        }

        if (!showCommandPalette) return;

        if (key.upArrow) {
            setCommandIndex(index => (index <= 0 ? slashMatches.length - 1 : index - 1));
            return;
        }

        if (key.downArrow) {
            setCommandIndex(index => (index + 1) % slashMatches.length);
            return;
        }

        if (key.tab) {
            const selected = slashMatches[Math.min(commandIndex, slashMatches.length - 1)];
            if (selected) {
                setInput(`${selected.name} `);
            }
        }
    });

    useEffect(() => {
        const handleResize = () => setTerminalSize({
            width: process.stdout.columns || 100,
            height: Math.max(process.stdout.rows || 30, 25)
        });
        process.stdout.on('resize', handleResize);
        return () => { process.stdout.off('resize', handleResize); };
    }, []);

    const loadPanelData = async () => {
        let nextAgents = agents;
        let nextTasks = tasks;
        try {
            const agentsResponse = await fetch(`${API_BASE}/agents`);
            const agentsData = await agentsResponse.json();
            if (Array.isArray(agentsData.agents)) {
                nextAgents = agentsData.agents.map((agent: any) => ({
                    id: String(agent.id || agent.name || ''),
                    name: String(agent.name || agent.id || 'Agent'),
                    status: String(agent.status || 'idle'),
                    description: agent.description ? String(agent.description) : undefined
                })).filter((agent: AgentInfo) => agent.id);
                setAgents(nextAgents);
            }
        } catch {
            // Keep the existing panel data if the API is not reachable.
        }

        try {
            const tasksResponse = await fetch(`${API_BASE}/tasks`);
            const tasksData = await tasksResponse.json();
            if (Array.isArray(tasksData.tasks)) {
                nextTasks = tasksData.tasks.map((task: any) => ({
                    id: String(task.id || task.subject || ''),
                    subject: String(task.subject || task.title || 'Task'),
                    status: String(task.status || 'pending'),
                    agent: task.agent ? String(task.agent) : undefined
                })).filter((task: TaskItem) => task.id);
                setTasks(nextTasks);
            }
        } catch {
            // Tasks are optional; the clean panel is better than stale error text.
        }

        if (nextTasks.length === 0) {
            const markdownTasks = await readTodoMarkdown();
            if (markdownTasks.length > 0) {
                nextTasks = markdownTasks;
                setTasks(nextTasks);
            }
        }

        try {
            const voiceResponse = await fetch(`${API_BASE}/voice/status`);
            const voiceData = await voiceResponse.json();
            if (voiceData.running) {
                setVoiceMode(voiceData.mode || 'auto');
                setVoicePhase(String(voiceData.phase || 'idle'));
                setVoiceTranscriptPreview(String(voiceData.transcript_preview || ''));
                setVoiceReplyPreview(String(voiceData.reply_preview || ''));
            } else {
                setVoiceMode('off');
                setVoicePhase('off');
                setVoiceTranscriptPreview('');
                setVoiceReplyPreview('');
            }
        } catch {
            // Ignore errors querying voice status
        }

        return {agents: nextAgents, tasks: nextTasks};
    };

    useEffect(() => {
        void loadPanelData();
        const timer = setInterval(() => {
            void loadPanelData();
        }, 6000);
        return () => clearInterval(timer);
    }, []);

    useEffect(() => {
        const syncStartupSession = async () => {
            try {
                const active = await apiJson('/sessions/active');
                const nextSessionId = String(active?.session_id || 'default');
                const loadedHistory = Array.isArray(active?.history)
                    ? active.history.map((msg: any) => ({
                        role: String(msg.role || 'assistant'),
                        content: String(msg.role || 'assistant') === 'assistant'
                            ? cleanVisibleAssistantText(String(msg.content || ''))
                            : String(msg.content || '')
                    }))
                    : [];
                setSessionId(nextSessionId);
                setHistory(loadedHistory);
            } catch {
                // Keep local defaults if the API is not ready yet.
            }
        };

        void syncStartupSession();
    }, []);

    // Real-time chat + voice sync during voice mode
    useEffect(() => {
        if (voiceMode === 'off') return;
        
        const syncHistory = async () => {
            try {
                // Skip history loading for 3s after voice starts (voice status still updates)
                const skipUntil = voiceJustStartedRef.current;
                const inGracePeriod = skipUntil && Date.now() < skipUntil;
                if (skipUntil && !inGracePeriod) voiceJustStartedRef.current = 0;
                const voiceData = await apiJson('/voice/status').catch(() => null);
                if (voiceData && voiceData.running) {
                    setVoiceMode(voiceData.mode || 'auto');
                    setVoicePhase(String(voiceData.phase || 'idle'));
                    setVoiceTranscriptPreview(String(voiceData.transcript_preview || ''));
                    setVoiceReplyPreview(String(voiceData.reply_preview || ''));
                } else if (voiceData && !voiceData.running) {
                    setVoiceMode('off');
                    setVoicePhase('off');
                    setVoiceTranscriptPreview('');
                    setVoiceReplyPreview('');
                    return;
                }

                // Only fetch history after grace period (prevents old history flash on voice start)
                if (!inGracePeriod) {
                    const loaded = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);
                    if (Array.isArray(loaded)) {
                        const loadedHistory = loaded.map((msg: any) => ({
                            role: msg.role,
                            content: msg.role === 'assistant'
                                ? cleanVisibleAssistantText(String(msg.content || ''))
                                : String(msg.content || '')
                        }));
                        setHistory(prev => {
                            const hasChanged = loadedHistory.length !== prev.length ||
                                loadedHistory.some((msg, i) => !prev[i] || msg.role !== prev[i].role || msg.content !== prev[i].content);
                            return hasChanged ? loadedHistory : prev;
                        });
                    }
                }
            } catch {
                // Ignore history load errors
            }
        };

        void syncHistory();
        const interval = setInterval(syncHistory, 350);
        return () => clearInterval(interval);
    }, [voiceMode, sessionId]);

    const inputTokens = history
        .filter(msg => msg.role === 'user')
        .reduce((total, msg) => total + estimateTokens(msg.content), 0);
    const outputTokens = history
        .filter(msg => msg.role === 'assistant')
        .reduce((total, msg) => total + estimateTokens(msg.content), 0);
    const contextTokens = Math.min(
        CONTEXT_LIMIT,
        inputTokens +
        outputTokens +
        estimateTokens(lastChange) +
        activities.length * 12 +
        touchedFiles.length * 8
    );
    const usage: UsageStats = {
        contextTokens,
        contextLimit: CONTEXT_LIMIT,
        inputTokens,
        outputTokens
    };

    const appendTimeline = (event: TimelineEvent) => {
        setTimeline(prev => [...prev, event].slice(-MAX_TIMELINE_ITEMS));
    };

    const addActivityItem = (activity: Omit<ActivityItem, 'id' | 'number'>) => {
        activityCounter.current += 1;
        const item: ActivityItem = {
            ...activity,
            id: `activity-${activityCounter.current}`,
            number: activityCounter.current
        };

        setActivityItems(prev => [item, ...prev].slice(0, 20));
        setHistory(prev => [...prev, {
            role: 'activity',
            content: item.title,
            activityId: item.id
        }]);
        setSelectedActivityId(item.id);
        setPanelMode('activity');

        return item;
    };

    const completeRunningActivities = (status: 'done' | 'error') => {
        setActivityItems(prev => prev.map(activity => (
            activity.status === 'running' ? {...activity, status} : activity
        )));
    };

    const updateLatestActivityForTool = (toolName: string, result: {output?: string; error?: string}) => {
        setActivityItems(prev => {
            const next = [...prev];
            const index = next.findIndex(activity => activity.toolName === toolName && activity.status === 'running');
            if (index === -1) return prev;

            const output = cleanPreview(result.output || '', 30);
            const error = cleanPreview(result.error || '', 16);
            next[index] = {
                ...next[index],
                output: output || next[index].output,
                error: error || next[index].error,
                status: error || output.toLowerCase().startsWith('[error]') ? 'error' : 'done'
            };
            return next;
        });
    };

    const pushCommand = (content: string) => {
        setHistory(prev => [...prev, {role: 'command', content}]);
    };

    const pushSystem = (content: string) => {
        setHistory(prev => [...prev, {role: 'system', content}]);
    };

    const ensureApiAvailable = async () => {
        try {
            const health = await fetch(`${API_BASE}/health`);
            if (health.ok) return true;
        } catch {
            // Try to start it below.
        }

        startDetached('python', ['-m', 'server'], PROJECT_ROOT);

        for (let attempt = 0; attempt < 20; attempt += 1) {
            await new Promise(resolve => setTimeout(resolve, 400));
            try {
                const health = await fetch(`${API_BASE}/health`);
                if (health.ok) return true;
            } catch {
                // keep polling briefly
            }
        }

        return false;
    };

    const apiJson = async (endpoint: string, init?: RequestInit) => {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            ...init,
            headers: {
                'Content-Type': 'application/json',
                ...(init?.headers || {})
            }
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const detail = data.detail || data.error || response.statusText;
            throw new Error(String(detail));
        }
        return data;
    };

    const postJson = (endpoint: string, body: Record<string, any>) => apiJson(endpoint, {
        method: 'POST',
        body: JSON.stringify(body)
    });

    const formatRows = (rows: string[]) => rows.length > 0 ? rows.join('\n') : 'No results.';
    const manageJson = (action: string, type: string, name = '', value?: any) => postJson('/manage', {action, type, name, value});
    const formatEnabled = (value: boolean | undefined) => value ? 'enabled' : 'disabled';
    const lastAssistantText = () => [...history].reverse().find(msg => msg.role === 'assistant' && msg.content.trim())?.content.trim() || '';
    const conversationText = () => history
        .filter(msg => ['user', 'assistant', 'command'].includes(msg.role) && msg.content.trim())
        .map(msg => `${msg.role.toUpperCase()}: ${msg.content.trim()}`)
        .join('\n\n');
    const usageLines = () => [
        `context: ${formatContextPercent(usage.contextTokens, usage.contextLimit)} (${formatTokens(usage.contextTokens)} / ${formatTokens(usage.contextLimit)})`,
        `input: ${formatTokens(usage.inputTokens)}`,
        `output: ${formatTokens(usage.outputTokens)}`,
        `messages: ${history.filter(msg => msg.role === 'user' || msg.role === 'assistant').length}`,
        `activities: ${activityItems.length}`
    ];
    const contextLines = () => [
        ...usageLines(),
        'recent activity:',
        ...timeline.slice(-12).map(event => `${event.kind} ${formatTokens(event.weight)} - ${event.label}`)
    ];
    const unsupportedCommand = (name: string, reason: string) => {
        pushCommand(formatRows([
            `${name}: not available in this local NEXUS runtime`,
            reason,
            'No fake action was run.'
        ]));
    };
    const formatManageResult = (result: any) => {
        if (result.type === 'config') return `config set: ${result.path} = ${JSON.stringify(result.value)}`;
        if (result.type === 'provider') return `provider ${result.name}: ${result.active ? 'active' : 'inactive'}${result.model ? ` model=${result.model}` : ''}`;
        if (result.type === 'feature') return `feature ${result.name}: ${formatEnabled(result.enabled)}`;
        if (result.type) return `${result.type} ${result.name}: ${formatEnabled(result.enabled ?? result.active)}`;
        if (result.reloaded_loops !== undefined) return `${result.target || 'runtime'} reset/reload: ${result.reloaded_loops} loops cleared`;
        return JSON.stringify(result);
    };

    const parseManageArgs = (args: string) => {
        const [type = '', name = '', ...rest] = args.trim().split(/\s+/).filter(Boolean);
        return {type: type.toLowerCase(), name, rest, value: rest.join(' ')};
    };

    const handlePanelCommand = async (value: string) => {
        const normalized = value.trim().toLowerCase();
        if (!normalized.startsWith('/')) return false;

        if (normalized === '/close' || normalized === '/panel') {
            setPanelMode('workspace');
            setSelectedAgentId(null);
            setSelectedActivityId(null);
            return true;
        }

        if (normalized === '/back') {
            if (panelMode === 'agent') {
                setPanelMode('hive');
                setSelectedAgentId(null);
            } else {
                setPanelMode('workspace');
                setSelectedActivityId(null);
            }
            return true;
        }

        if (normalized.startsWith('/open') || normalized.startsWith('/detail')) {
            const [, rawNumber] = normalized.split(/\s+/, 2);
            const number = rawNumber ? Number(rawNumber) : activityItems[0]?.number;
            const item = activityItems.find(activity => activity.number === number);
            if (item) {
                setSelectedActivityId(item.id);
                setSelectedAgentId(null);
                setPanelMode('activity');
            }
            return true;
        }

        if (normalized.startsWith('/hive')) {
            const {agents: latestAgents} = await loadPanelData();
            const [, rawIndex] = normalized.split(/\s+/, 2);
            const index = rawIndex ? Number(rawIndex) : NaN;
            if (Number.isInteger(index) && index > 0 && latestAgents[index - 1]) {
                setSelectedAgentId(latestAgents[index - 1].id);
                setSelectedActivityId(null);
                setPanelMode('agent');
            } else {
                setSelectedAgentId(null);
                setSelectedActivityId(null);
                setPanelMode('hive');
            }
            return true;
        }

        return false;
    };

    const handleSlashCommand = async (value: string) => {
        if (!value.trim().startsWith('/')) return false;
        if (await handlePanelCommand(value)) return true;

        const trimmed = value.trim();
        const [rawCommand, ...parts] = trimmed.split(/\s+/);
        const typedCommand = rawCommand.toLowerCase();
        const exactCommand = commandDefinitionFor(typedCommand);
        const paletteMatches = commandMatches(typedCommand);
        const paletteCommand = paletteMatches[Math.min(commandIndex, Math.max(0, paletteMatches.length - 1))];
        const matchedCommand = exactCommand && typedCommand !== '/' ? exactCommand : paletteCommand || exactCommand;
        const command = matchedCommand?.name || typedCommand;
        const args = trimmed.slice(rawCommand.length).trim();

        try {
            if (command === '/commands') {
                pushCommand(formatRows([
                    'NEXUS commands',
                    ...COMMANDS.map(item => {
                        const aliases = item.aliases?.length ? ` (${item.aliases.join(', ')})` : '';
                        return `${item.name}${aliases} - ${item.description}`;
                    })
                ]));
                return true;
            }

            if (command === '/clear') {
                setHistory([]);
                return true;
            }

            if (command === '/exit') {
                await stopVoiceIfRunning();
                exit();
                return true;
            }

            if (command === '/usage') {
                pushCommand(formatRows(usageLines()));
                return true;
            }

            if (command === '/context') {
                pushCommand(formatRows(contextLines()));
                return true;
            }

            if (command === '/compact') {
                const keepCount = Math.max(4, Number(parts[0]) || 12);
                const before = history.length;
                setHistory(prev => prev.slice(-keepCount));
                pushCommand(`compacted visible CLI history: kept ${Math.min(before, keepCount)} of ${before} rows`);
                return true;
            }

            if (command === '/copy') {
                const text = args === 'all' ? conversationText() : lastAssistantText();
                if (!text) {
                    pushCommand('nothing to copy yet');
                } else {
                    const tempDir = path.join(PROJECT_ROOT, 'workspace', 'exports');
                    await mkdir(tempDir, {recursive: true});
                    const tempFile = path.join(tempDir, 'clipboard.txt');
                    await writeFile(tempFile, text, 'utf8');
                    await runLocal('powershell.exe', ['-NoProfile', '-Command', `Get-Content -Raw ${JSON.stringify(tempFile)} | Set-Clipboard`], PROJECT_ROOT, 20000);
                    pushCommand(`copied ${args === 'all' ? 'conversation' : 'last assistant response'} to clipboard`);
                }
                return true;
            }

            if (command === '/export') {
                const exportDir = path.join(PROJECT_ROOT, 'workspace', 'exports');
                await mkdir(exportDir, {recursive: true});
                const fileName = args || `${sessionId}-${Date.now()}.txt`;
                const target = safeRelativePath(path.join('workspace', 'exports', fileName));
                await writeFile(target, conversationText() || 'No conversation history.', 'utf8');
                pushCommand(`exported conversation: ${target}`);
                return true;
            }

            if (command === '/enable' || command === '/disable') {
                const action = command === '/enable' ? 'enable' : 'disable';
                const {type, name} = parseManageArgs(args);
                if (!type) {
                    pushCommand(`usage: ${command} <tool|skill|mcp|plugin|provider|hive|evolution|scheduler|reminders|health> [name]`);
                } else {
                    const result = await manageJson(action, type, name);
                    pushCommand(formatManageResult(result));
                }
                return true;
            }

            if (command === '/reset') {
                const target = parts[0]?.toLowerCase() || 'nexus';
                const result = await manageJson('reset', target);
                if (target === 'tasks') setTasks([]);
                if (target === 'nexus' || target === 'runtime' || target === 'all') {
                    setHistory([]);
                    setProvider('');
                    setModel('');
                    setSelectedActivityId(null);
                    setSelectedAgentId(null);
                    setPanelMode('workspace');
                }
                pushCommand(formatManageResult(result));
                return true;
            }

            if (command === '/features') {
                const data = await apiJson('/features');
                pushCommand(formatRows(Object.entries(data.features || {}).map(([key, value]) => `${key}: ${value ? 'enabled' : 'disabled'}`)));
                return true;
            }

            if (command === '/goal') {
                const sub = parts[0]?.toLowerCase();
                if (!args || sub === 'status') {
                    const data = await apiJson('/goal');
                    pushCommand(data.active ? `goal: ${data.goal}` : 'goal: none');
                } else {
                    const result = await postJson('/goal', {goal: args});
                    pushCommand(result.active ? `goal set: ${result.goal}` : 'goal cleared');
                }
                return true;
            }

            if (command === '/health') {
                const [apiHealth, status, features] = await Promise.all([
                    apiJson('/health'),
                    apiJson('/status'),
                    apiJson('/features')
                ]);
                pushCommand(formatRows([
                    `api: ${apiHealth.status}`,
                    `service: ${apiHealth.service}`,
                    `runtime: ${status.health}`,
                    `sessions: ${status.session_count}`,
                    `tasks: ${status.task_count}`,
                    `health feature: ${(features.features || {}).health ? 'enabled' : 'disabled'}`
                ]));
                return true;
            }

            if (command === '/evolution' || command === '/scheduler' || command === '/reminders' || command === '/schedule' || command === '/loop') {
                const featureName = command === '/schedule' || command === '/loop' ? 'scheduler' : command.slice(1);
                const data = await apiJson('/features');
                const enabled = Boolean((data.features || {})[featureName]);
                pushCommand(formatRows([
                    `${featureName}: ${enabled ? 'enabled' : 'disabled'}`,
                    `enable: /enable ${featureName}`,
                    `disable: /disable ${featureName}`,
                    `reload: /reload nexus`
                ]));
                return true;
            }

            if (command === '/pwd') {
                pushCommand(PROJECT_ROOT);
                return true;
            }

            if (command === '/voice') {
                const sub = parts[0]?.toLowerCase();
                const apiReady = await ensureApiAvailable();
                if (!apiReady) {
                    pushSystem('COMMAND_ERROR: voice API did not start in time');
                    return true;
                }
                const ensureCleanVoiceSession = async () => {
                    if (sessionId !== 'default' && history.length === 0) {
                        voiceSessionIdRef.current = sessionId;
                        return sessionId;
                    }
                    if (sessionId !== 'default' && history.length > 0) {
                        voiceSessionIdRef.current = sessionId;
                        return sessionId;
                    }
                    const created = await apiJson('/sessions/new', {method: 'POST'});
                    const nextSessionId = String(created.id || sessionId);
                    setSessionId(nextSessionId);
                    setHistory([]);
                    voiceSessionIdRef.current = nextSessionId;
                    pushCommand(`voice session: ${nextSessionId}`);
                    return nextSessionId;
                };
                if (!sub) {
                    const defaultMode = 'auto';
                    // Toggle: if running stop, if stopped start listening immediately
                    const statusRes = await fetch(`${API_BASE}/voice/status`);
                    const statusData = await statusRes.json();
                    if (statusData.running) {
                        pushCommand('🎙️ stopping voice...');
                        await fetch(`${API_BASE}/voice/stop`, { method: 'POST' });
                        setVoiceMode('off');
                        setVoicePhase('off');
                        setVoiceTranscriptPreview('');
                        setVoiceReplyPreview('');
                        voiceSessionIdRef.current = null;
                        pushCommand('🎙️ voice stopped');
                    } else {
                        const targetSessionId = await ensureCleanVoiceSession();
                        setHistory([]);
                        voiceJustStartedRef.current = Date.now() + 3000;
                        pushCommand(`🎙️ starting voice (${defaultMode})...`);
                        const startRes = await fetch(`${API_BASE}/voice/start`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ mode: defaultMode, session_id: targetSessionId, owner_pid: process.pid })
                        });
                        const startData = await startRes.json();
                        if (startData.status === 'success') {
                            setVoiceMode(defaultMode as any);
                            setVoicePhase(String(startData.phase || 'starting'));
                            pushCommand(`✓ voice active (${defaultMode}) — speak now, NEXUS is listening`);
                        } else {
                            pushCommand(`✗ voice failed: ${startData.detail || 'unknown error'}`);
                            if (defaultMode === 'auto') {
                                pushCommand('retry with /voice manual if your mic driver does not like auto mode');
                            }
                        }
                    }
                } else if (sub === 'status') {
                    const statusRes = await fetch(`${API_BASE}/voice/status`);
                    const statusData = await statusRes.json();
                    if (statusData.running) {
                        pushCommand(`🎙️ voice active — mode: ${statusData.mode}  phase: ${statusData.phase || 'idle'}  pid: ${statusData.pid}`);
                    } else {
                        pushCommand('🎙️ voice off');
                    }
                } else if (sub === 'off' || sub === 'stop') {
                    pushCommand('🎙️ stopping voice...');
                    await fetch(`${API_BASE}/voice/stop`, { method: 'POST' });
                    setVoiceMode('off');
                    setVoicePhase('off');
                    setVoiceTranscriptPreview('');
                    setVoiceReplyPreview('');
                    voiceSessionIdRef.current = null;
                    pushCommand('🎙️ voice stopped');
                } else if (sub === 'auto' || sub === 'manual' || sub === 'text') {
                    const targetSessionId = await ensureCleanVoiceSession();
                    setHistory([]);
                    voiceJustStartedRef.current = Date.now() + 3000;
                    pushCommand(`🎙️ starting voice (${sub})...`);
                    const startRes = await fetch(`${API_BASE}/voice/start`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ mode: sub, session_id: targetSessionId, owner_pid: process.pid })
                    });
                    const startData = await startRes.json();
                    if (startData.status === 'success') {
                        setVoiceMode(sub as any);
                        setVoicePhase(String(startData.phase || 'starting'));
                        pushCommand(`✓ voice active (${sub}) — speak now, NEXUS is listening`);
                    } else {
                        pushCommand(`✗ voice failed: ${startData.detail || 'unknown error'}`);
                    }
                } else {
                    pushCommand('usage: /voice [auto|manual|text|off|status]');
                }
                return true;
            }

            if (command === '/where') {
                pushCommand(formatRows([
                    `project: ${PROJECT_ROOT}`,
                    `cli: ${process.cwd()}`,
                    `session: ${sessionId}`,
                    `extra dirs: ${extraDirs.length ? extraDirs.join(', ') : 'none'}`,
                    `api: ${API_BASE}`,
                    `gui: http://127.0.0.1:5173`
                ]));
                return true;
            }

            if (command === '/add-dir') {
                if (!args) {
                    pushCommand('usage: /add-dir <directory>');
                } else {
                    const result = await postJson('/add-dir', {path: args});
                    setExtraDirs((result.additional_dirs || []).map((item: any) => String(item)));
                    pushCommand(`added working directory: ${result.path}`);
                }
                return true;
            }

            if (command === '/cd') {
                if (!args) {
                    pushCommand(`cwd: ${process.cwd()}`);
                } else {
                    const target = safeRelativePath(args);
                    const info = await stat(target);
                    if (!info.isDirectory()) {
                        pushCommand(`not a directory: ${target}`);
                    } else {
                        process.chdir(target);
                        pushCommand(`cwd: ${process.cwd()}`);
                    }
                }
                return true;
            }

            if (command === '/ls') {
                const target = safeRelativePath(args || '.');
                pushCommand(await listDirectory(target));
                return true;
            }

            if (command === '/tree') {
                const target = safeRelativePath(args || '.');
                const lines = await treeDirectory(target, 2);
                pushCommand(formatRows(lines));
                return true;
            }

            if (command === '/cat') {
                if (!args) {
                    pushCommand('usage: /cat <workspace-file>');
                } else {
                    const target = safeRelativePath(args);
                    const info = await stat(target);
                    if (info.isDirectory()) {
                        pushCommand('Cannot preview a directory.');
                    } else {
                        const content = await readFile(target, 'utf8');
                        pushCommand(cleanPreview(content, 80));
                    }
                }
                return true;
            }

            if (command === '/readme') {
                pushCommand(cleanPreview(await readFile(path.join(PROJECT_ROOT, 'README.md'), 'utf8'), 80));
                return true;
            }

            if (command === '/reload') {
                const target = typedCommand === '/reload-plugins'
                    ? 'plugins'
                    : typedCommand === '/reload-skills'
                        ? 'skills'
                        : parts[0]?.toLowerCase() || 'all';
                if (target === 'session' || target === 'history') {
                    const loaded = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);
                    const loadedHistory = Array.isArray(loaded)
                        ? loaded.map((msg: any) => ({
                            role: String(msg.role || 'assistant'),
                            content: String(msg.role || 'assistant') === 'assistant'
                                ? cleanVisibleAssistantText(String(msg.content || ''))
                                : String(msg.content || '')
                        }))
                        : [];
                    setHistory(loadedHistory);
                    pushCommand(`reloaded session: ${sessionId}`);
                } else if (target === 'tasks' || target === 'todo') {
                    const {tasks: latestTasks} = await loadPanelData();
                    pushCommand(`reloaded tasks: ${latestTasks.length}`);
                } else if (target === 'plugins' || target === 'plugin') {
                    await manageJson('reload', 'plugins');
                    const data = await apiJson('/plugins');
                    pushCommand(formatRows((data.plugins || []).map((plugin: any) => `${plugin.id} - ${plugin.enabled ? 'enabled' : 'disabled'}`)));
                } else if (target === 'skills' || target === 'skill') {
                    await manageJson('reload', 'skills');
                    const data = await apiJson('/skills');
                    pushCommand(formatRows((data.skills || []).map((skill: any) => `${skill.name} - ${skill.enabled ? 'enabled' : 'disabled'} - ${skill.description}`)));
                } else if (target === 'tools' || target === 'tool') {
                    await manageJson('reload', 'tools');
                    const data = await apiJson('/tools');
                    pushCommand(formatRows((data.tools || []).map((tool: any) =>
                        `${tool.name} - ${tool.enabled ? 'enabled' : 'disabled'} - ${tool.description}${tool.read_only ? ' [read]' : ''}${tool.safe ? ' [safe]' : ''}`
                    )));
                } else if (target === 'mcp' || target === 'mcps' || target === 'mpc') {
                    await manageJson('reload', 'mcp');
                    const data = await apiJson('/mcp');
                    pushCommand(formatRows((data.mcp || []).map((item: any) => `${item.id} - ${item.active ? 'active' : 'inactive'} - ${item.description}`)));
                } else if (target === 'providers' || target === 'provider') {
                    await manageJson('reload', 'providers');
                    const data = await apiJson('/providers');
                    pushCommand(formatRows((data.providers || []).map((item: any) => `${item.group}.${item.id} - ${item.active ? 'active' : 'inactive'} - ${item.model || 'no model'}`)));
                } else if (target === 'nexus' || target === 'runtime' || target === 'all') {
                    const result = await manageJson('reload', target);
                    pushCommand(formatManageResult(result));
                } else {
                    const {tasks: latestTasks} = await loadPanelData();
                    const [plugins, skills, tools] = await Promise.all([
                        apiJson('/plugins'),
                        apiJson('/skills'),
                        apiJson('/tools')
                    ]);
                    pushCommand(formatRows([
                        `tasks: ${latestTasks.length}`,
                        `plugins: ${(plugins.plugins || []).length}`,
                        `skills: ${(skills.skills || []).length}`,
                        `tools: ${(tools.tools || []).length}`,
                        `session: ${sessionId}`
                    ]));
                }
                return true;
            }

            if (command === '/docs') {
                const docsDir = path.join(PROJECT_ROOT, 'docs');
                pushCommand(await listDirectory(docsDir, 60));
                return true;
            }

            if (command === '/env') {
                pushCommand(formatRows([
                    `node: ${process.version}`,
                    `platform: ${process.platform}`,
                    `cwd: ${process.cwd()}`,
                    `OPENAI_API_KEY: ${process.env.OPENAI_API_KEY ? 'set' : 'not set'}`,
                    `ANTHROPIC_API_KEY: ${process.env.ANTHROPIC_API_KEY ? 'set' : 'not set'}`,
                    `OPENROUTER_API_KEY: ${process.env.OPENROUTER_API_KEY ? 'set' : 'not set'}`
                ]));
                return true;
            }

            if (command === '/version') {
                const [nodeVersion, npmVersion, pythonVersion, gitVersion] = await Promise.allSettled([
                    runLocal('node', ['--version']),
                    runLocal('npm', ['--version']),
                    runLocal('python', ['--version']),
                    runLocal('git', ['--version'])
                ]);
                const value = (result: PromiseSettledResult<string>) => result.status === 'fulfilled' ? result.value : result.reason.message;
                pushCommand(formatRows([
                    `nexus-cli: 2.0.0`,
                    `node: ${value(nodeVersion)}`,
                    `npm: ${value(npmVersion)}`,
                    `python: ${value(pythonVersion)}`,
                    `git: ${value(gitVersion)}`
                ]));
                return true;
            }

            if (command === '/ide') {
                const action = parts[0]?.toLowerCase() || 'open';
                const targetArg = action === 'open' || action === 'status' ? parts.slice(1).join(' ') : args;
                const target = targetArg ? safeRelativePath(targetArg) : PROJECT_ROOT;
                const hasCode = await commandExists('code');
                if (action === 'status') {
                    pushCommand(formatRows([
                        `vscode cli: ${hasCode ? 'available' : 'missing'}`,
                        `target: ${target}`,
                        `cwd: ${process.cwd()}`
                    ]));
                } else if (hasCode) {
                    startDetached('cmd.exe', ['/c', 'code', target], PROJECT_ROOT);
                    pushCommand(`opened in VS Code: ${target}`);
                } else {
                    pushCommand('VS Code command `code` was not found on PATH.');
                }
                return true;
            }

            if (command === '/init') {
                const claudePath = path.join(PROJECT_ROOT, 'CLAUDE.md');
                const nexusPath = path.join(PROJECT_ROOT, 'NEXUS.md');
                const created: string[] = [];
                if (!existsSync(claudePath)) {
                    await writeFile(claudePath, `# CLAUDE.md\n\nProject guidance for coding agents working in ${path.basename(PROJECT_ROOT)}.\n\n- Prefer real, verified behavior over mock status.\n- Keep changes scoped and test them.\n`, 'utf8');
                    created.push('CLAUDE.md');
                }
                if (!existsSync(nexusPath)) {
                    await writeFile(nexusPath, `# NEXUS.md\n\nNEXUS project memory.\n\n- Workspace: ${PROJECT_ROOT}\n- CLI: Ink + TypeScript\n- API: FastAPI\n`, 'utf8');
                    created.push('NEXUS.md');
                }
                pushCommand(created.length ? `initialized: ${created.join(', ')}` : 'memory files already exist');
                return true;
            }

            if (command === '/memory') {
                const targetName = parts[0]?.toLowerCase() === 'claude' ? 'CLAUDE.md' : parts[0]?.toLowerCase() === 'nexus' ? 'NEXUS.md' : 'NEXUS.md';
                const target = path.join(PROJECT_ROOT, targetName);
                const action = parts[0]?.toLowerCase() === 'open' || parts[1]?.toLowerCase() === 'open' ? 'open' : 'show';
                if (!existsSync(target)) {
                    pushCommand(`${targetName} not found. Run /init first.`);
                } else if (action === 'open' && await commandExists('code')) {
                    startDetached('cmd.exe', ['/c', 'code', target], PROJECT_ROOT);
                    pushCommand(`opened memory: ${target}`);
                } else {
                    pushCommand(cleanPreview(await readFile(target, 'utf8'), 80));
                }
                return true;
            }

            if (command === '/keybindings' || command === '/terminal-setup') {
                pushCommand(formatRows([
                    'NEXUS CLI keybindings',
                    'Tab: accept highlighted slash command',
                    'Up/Down: move slash command selection',
                    'Enter: send message or command',
                    'Ctrl+C: exit terminal process'
                ]));
                return true;
            }

            if (command === '/open-gui') {
                startDetached('powershell.exe', ['-NoProfile', '-Command', 'Start-Process', 'http://127.0.0.1:5173'], PROJECT_ROOT);
                pushCommand('opened GUI: http://127.0.0.1:5173');
                return true;
            }

            if (command === '/api') {
                const action = parts[0]?.toLowerCase() || 'status';
                if (action === 'start') {
                    startDetached('python', ['-m', 'server'], PROJECT_ROOT);
                    pushCommand('started CLI API on http://127.0.0.1:8000');
                } else {
                    const health = await apiJson('/health');
                    pushCommand(`${health.service}: ${health.status}`);
                }
                return true;
            }

            if (command === '/gui') {
                const action = parts[0]?.toLowerCase() || 'status';
                if (action === 'start') {
                    startDetached('powershell.exe', ['-ExecutionPolicy', 'Bypass', '-File', path.join(PROJECT_ROOT, 'scripts', 'run-gui.ps1')], PROJECT_ROOT);
                    pushCommand('starting GUI via scripts/run-gui.ps1');
                } else if (action === 'open') {
                    startDetached('powershell.exe', ['-NoProfile', '-Command', 'Start-Process', 'http://127.0.0.1:5173'], PROJECT_ROOT);
                    pushCommand('opened GUI: http://127.0.0.1:5173');
                } else if (action === 'build') {
                    pushCommand(await runLocal('npm', ['--prefix', 'gui', 'run', 'build'], PROJECT_ROOT, 120000));
                } else if (action === 'logs') {
                    const logsDir = path.join(PROJECT_ROOT, 'logs');
                    const entries = (await readdir(logsDir)).filter(name => name.includes('gui-')).slice(-12);
                    pushCommand(formatRows(entries));
                } else {
                    const [apiState, webState] = await Promise.allSettled([
                        fetch('http://127.0.0.1:8000/api/health').then(res => res.status),
                        fetch('http://127.0.0.1:5173').then(res => res.status)
                    ]);
                    pushCommand(formatRows([
                        `api: ${apiState.status === 'fulfilled' ? apiState.value : 'offline'}`,
                        `web: ${webState.status === 'fulfilled' ? webState.value : 'offline'}`,
                        'usage: /gui start | /gui open | /gui build | /gui logs'
                    ]));
                }
                return true;
            }

            if (command === '/git') {
                const action = parts[0]?.toLowerCase() || 'status';
                const gitArgs = action === 'diff'
                    ? ['diff', '--stat']
                    : action === 'log'
                        ? ['log', '--oneline', '-12']
                        : action === 'branch'
                            ? ['branch', '--show-current']
                            : ['status', '--short'];
                pushCommand(await runLocal('git', gitArgs));
                return true;
            }

            if (command === '/diff') {
                pushCommand(await runLocal('git', ['diff', '--stat']));
                return true;
            }

            if (command === '/branch') {
                pushCommand(await runLocal('git', ['branch', '--show-current']));
                return true;
            }

            if (command === '/log') {
                pushCommand(await runLocal('git', ['log', '--oneline', '-12']));
                return true;
            }

            if (command === '/config' || command === '/settings') {
                const configPath = path.join(PROJECT_ROOT, 'configs', 'nexus_config.yaml');
                if (parts[0]?.toLowerCase() === 'set') {
                    const configPathArg = parts[1];
                    const value = parts.slice(2).join(' ');
                    if (!configPathArg || !value) {
                        pushCommand('usage: /config set <dotted.path> <value>');
                    } else {
                        const result = await manageJson('set', 'config', configPathArg, value);
                        pushCommand(formatManageResult(result));
                    }
                } else if (!args) {
                    pushCommand(formatRows(await readYamlSectionNames(configPath)));
                } else {
                    const content = await readFile(configPath, 'utf8');
                    const lines = content.split(/\r?\n/);
                    const start = lines.findIndex(line => line.trim() === `${args}:`);
                    if (start === -1) {
                        pushCommand(`config section not found: ${args}`);
                    } else {
                        const sectionLines = lines.slice(start, start + 80);
                        pushCommand(sectionLines.join('\n'));
                    }
                }
                return true;
            }

            if (command === '/providers') {
                const data = await apiJson('/providers');
                pushCommand(formatRows((data.providers || []).map((item: any) =>
                    `${item.group}.${item.id} - ${item.active ? 'active' : 'inactive'} - ${item.model || 'no model'}`
                )));
                return true;
            }

            if (command === '/mcp') {
                const sub = parts[0]?.toLowerCase();
                if ((sub === 'enable' || sub === 'disable') && parts[1]) {
                    if (parts[1].toLowerCase() === 'all') {
                        const data = await apiJson('/mcp');
                        const results = await Promise.all((data.mcp || []).map((item: any) => manageJson(sub, 'mcp', item.id)));
                        pushCommand(formatRows(results.map(formatManageResult)));
                    } else {
                        const result = await manageJson(sub, 'mcp', parts[1]);
                        pushCommand(formatManageResult(result));
                    }
                } else if (sub === 'reload' || sub === 'reconnect') {
                    const result = await manageJson('reload', 'mcp');
                    pushCommand(formatManageResult(result));
                } else {
                    const data = await apiJson('/mcp');
                    pushCommand(formatRows((data.mcp || []).map((item: any) =>
                        `${item.id} - ${item.active ? 'active' : 'inactive'} - ${item.command || 'no command'} - ${item.description || ''}`
                    )));
                }
                return true;
            }

            if (command === '/logs') {
                const logsDir = path.join(PROJECT_ROOT, 'logs');
                const entries = (await readdir(logsDir)).slice(-30);
                pushCommand(formatRows(entries));
                return true;
            }

            if (command === '/work') {
                const workDir = path.join(PROJECT_ROOT, 'workspace', 'work_events');
                const file = path.join(workDir, `${sessionId}.jsonl`);
                if (!existsSync(file)) {
                    pushCommand(`No work events for ${sessionId}`);
                } else {
                    const lines = (await readFile(file, 'utf8')).trim().split(/\r?\n/).slice(-12);
                    pushCommand(formatRows(lines.map(line => {
                        try {
                            const event = JSON.parse(line);
                            return `${event.kind || 'event'} ${event.status || ''} ${event.title || event.action || event.path || ''}`.trim();
                        } catch {
                            return line;
                        }
                    })));
                }
                return true;
            }

            if (command === '/check') {
                const target = parts[0]?.toLowerCase() || 'cli';
                if (target === 'cli') {
                    pushCommand(await runLocal('npx', ['tsc', '--noEmit'], path.join(PROJECT_ROOT, 'cli'), 120000));
                } else if (target === 'py' || target === 'python') {
                    pushCommand(await runLocal('python', ['-m', 'py_compile', 'orchestrators\\loop.py'], PROJECT_ROOT, 120000));
                } else if (target === 'gui') {
                    pushCommand(await runLocal('npm', ['--prefix', 'gui', 'run', 'build'], PROJECT_ROOT, 120000));
                } else {
                    pushCommand('usage: /check cli | /check py | /check gui');
                }
                return true;
            }

            if (command === '/build') {
                const target = parts[0]?.toLowerCase() || 'gui';
                if (target === 'cli') {
                    pushCommand(await runLocal('npx', ['tsc', '--noEmit'], path.join(PROJECT_ROOT, 'cli'), 120000));
                } else {
                    pushCommand(await runLocal('npm', ['--prefix', 'gui', 'run', 'build'], PROJECT_ROOT, 120000));
                }
                return true;
            }

            if (command === '/doctor') {
                const checks = await Promise.allSettled([
                    apiJson('/health').then((health: any) => `api: ${health.status}`),
                    runLocal('git', ['status', '--short']).then(output => `git changes:\n${output || 'clean'}`),
                    runLocalResult('npx', ['tsc', '--noEmit'], path.join(PROJECT_ROOT, 'cli'), 120000).then(result =>
                        result.ok ? 'cli ts: ok' : `cli ts: failed\n${result.output}`
                    ),
                    runLocalResult('python', ['-m', 'py_compile', 'orchestrators\\loop.py'], PROJECT_ROOT, 120000).then(result =>
                        result.ok ? 'python compile: ok' : `python compile: failed\n${result.output}`
                    )
                ]);
                pushCommand(formatRows(checks.map(result => result.status === 'fulfilled' ? result.value : `check failed: ${result.reason.message}`)));
                return true;
            }

            if (command === '/debug') {
                const [status, health] = await Promise.all([apiJson('/status'), apiJson('/health')]);
                pushCommand(formatRows([
                    `api: ${health.status}`,
                    `session: ${sessionId}`,
                    `cwd: ${process.cwd()}`,
                    `provider: ${status.provider}`,
                    `model: ${status.model}`,
                    `mode: ${status.mode}`,
                    `goal: ${status.goal || 'none'}`,
                    `extra dirs: ${(status.additional_dirs || []).join(', ') || 'none'}`,
                    `logs: ${path.join(PROJECT_ROOT, 'logs')}`
                ]));
                return true;
            }

            if (command === '/hooks') {
                const settingsPath = path.join(PROJECT_ROOT, '.claude', 'settings.json');
                if (!existsSync(settingsPath)) {
                    pushCommand('No .claude/settings.json found.');
                } else {
                    try {
                        const settings = JSON.parse(await readFile(settingsPath, 'utf8'));
                        pushCommand(formatRows(Object.keys(settings.hooks || {}).map(key => `${key}: ${JSON.stringify(settings.hooks[key]).slice(0, 160)}`)));
                    } catch (error) {
                        pushCommand(`Cannot read hooks because .claude/settings.json is malformed: ${error instanceof Error ? error.message : String(error)}`);
                    }
                }
                return true;
            }

            if (command === '/login') {
                pushCommand(formatRows([
                    `OPENAI_API_KEY: ${process.env.OPENAI_API_KEY ? 'set' : 'not set'}`,
                    `ANTHROPIC_API_KEY: ${process.env.ANTHROPIC_API_KEY ? 'set' : 'not set'}`,
                    `OPENROUTER_API_KEY: ${process.env.OPENROUTER_API_KEY ? 'set' : 'not set'}`,
                    'Use /provider list and /model list to choose configured providers.'
                ]));
                return true;
            }

            if (command === '/logout') {
                setProvider('');
                setModel('');
                await postJson('/provider', {provider: ''});
                pushCommand('cleared local provider/model overrides');
                return true;
            }

            if (command === '/fast') {
                const value = args || 'status';
                if (value === 'status') {
                    pushCommand('fast mode is config-backed. Use /fast on or /fast off.');
                } else {
                    const result = await manageJson('set', 'config', 'runtime.fast', value.toLowerCase() === 'on');
                    pushCommand(formatManageResult(result));
                }
                return true;
            }

            if (command === '/heapdump') {
                const exportDir = path.join(PROJECT_ROOT, 'workspace', 'exports');
                await mkdir(exportDir, {recursive: true});
                const target = path.join(exportDir, `node-memory-${Date.now()}.json`);
                await writeFile(target, JSON.stringify(process.memoryUsage(), null, 2), 'utf8');
                pushCommand(`wrote memory snapshot: ${target}`);
                return true;
            }

            if (command === '/theme' || command === '/color' || command === '/statusline' || command === '/tui' || command === '/output-style') {
                pushCommand(formatRows([
                    `${command}: current NEXUS CLI renderer`,
                    `theme: static dark sovereign`,
                    `background: ${THEME.appBg}`,
                    `panel: ${THEME.panelBg}`,
                    `input: ${THEME.inputBg}`,
                    'Changing these live needs a renderer theme refactor; no fake theme switch was applied.'
                ]));
                return true;
            }

            if (command === '/status') {
                const status = await apiJson('/status');
                pushCommand(formatRows([
                    `health: ${status.health}`,
                    `model: ${status.model}`,
                    `provider: ${status.provider}`,
                    `mode: ${status.mode}`,
                    `agent: ${status.agent || 'none'}`,
                    `goal: ${status.goal || 'none'}`,
                    `sessions: ${status.session_count}`,
                    `agents: ${status.agent_count}`,
                    `tasks: ${status.task_count}`,
                    `version: ${status.version}`
                ]));
                return true;
            }

            if (command === '/model') {
                const sub = parts[0]?.toLowerCase();
                if (!args || sub === 'status') {
                    const status = await apiJson('/status');
                    pushCommand(`model: ${status.model}`);
                } else if (sub === 'list') {
                    const data = await apiJson('/providers');
                    pushCommand(formatRows((data.providers || []).map((item: any) => `${item.id}: ${item.model || 'no model'} ${item.active ? '[active]' : ''}`)));
                } else if (sub === 'set' && parts.length >= 3) {
                    const result = await manageJson('model', 'provider', parts[1], parts.slice(2).join(' '));
                    pushCommand(formatManageResult(result));
                } else {
                    const result = await postJson('/model', {model: args, session_id: sessionId});
                    setModel(result.model);
                    pushCommand(`model set: ${result.model}`);
                }
                return true;
            }

            if (command === '/provider') {
                const sub = parts[0]?.toLowerCase();
                if (!args || sub === 'status') {
                    const status = await apiJson('/status');
                    pushCommand(`provider: ${status.provider}`);
                } else if (sub === 'list') {
                    const data = await apiJson('/providers');
                    pushCommand(formatRows((data.providers || []).map((item: any) => `${item.group}.${item.id} - ${item.active ? 'active' : 'inactive'} - ${item.model || 'no model'}`)));
                } else if ((sub === 'enable' || sub === 'disable') && parts[1]) {
                    const result = await manageJson(sub, 'provider', parts[1]);
                    pushCommand(formatManageResult(result));
                } else if (sub === 'model' && parts.length >= 3) {
                    const result = await manageJson('model', 'provider', parts[1], parts.slice(2).join(' '));
                    pushCommand(formatManageResult(result));
                } else if ((sub === 'add' || sub === 'set') && parts[1]) {
                    const providerName = parts[1];
                    const modelValue = parts.slice(2).join(' ');
                    const value = modelValue ? {active: true, model: modelValue} : {active: true};
                    const result = await manageJson('set', 'provider', providerName, value);
                    pushCommand(formatManageResult(result));
                } else {
                    const result = await postJson('/provider', {provider: args, session_id: sessionId});
                    setProvider(result.provider);
                    pushCommand(result.provider ? `provider set: ${result.provider}` : 'provider override cleared');
                }
                return true;
            }

            if (command === '/mode' || command === '/permissions') {
                if (!args) {
                    const status = await apiJson('/status');
                    pushCommand(`mode: ${status.mode}`);
                } else {
                    const result = await postJson('/mode', {mode: args});
                    pushCommand(`mode set: ${result.mode}`);
                }
                return true;
            }

            if (command === '/plan') {
                const result = await postJson('/mode', {mode: 'plan'});
                pushCommand(args ? `mode set: ${result.mode}\nplan prompt: ${args}` : `mode set: ${result.mode}`);
                return true;
            }

            if (command === '/sandbox') {
                if (!args) {
                    const status = await apiJson('/status');
                    pushCommand(`sandbox/mode: ${status.mode}`);
                } else {
                    const requested = args.toLowerCase() === 'off' ? 'bypass' : args.toLowerCase() === 'on' ? 'auto' : args;
                    const result = await postJson('/mode', {mode: requested});
                    pushCommand(`mode set: ${result.mode}`);
                }
                return true;
            }

            if (command === '/effort') {
                const level = args || 'auto';
                const result = await manageJson('set', 'config', 'runtime.effort', level);
                pushCommand(formatManageResult(result));
                return true;
            }

            if (command === '/agents') {
                if (args) {
                    const result = await postJson('/agent', {agent: args});
                    pushCommand(`agent set: ${result.agent}`);
                } else {
                    const data = await apiJson('/agents');
                    setAgents(data.agents || []);
                    pushCommand(formatRows((data.agents || []).map((agent: any) => `${agent.id} - ${agent.status} - ${agent.description}`)));
                }
                return true;
            }

            if (command === '/new') {
                const created = await apiJson('/sessions/new', {method: 'POST'});
                setSessionId(created.id);
                setHistory([]);
                setSelectedActivityId(null);
                setSelectedAgentId(null);
                setPanelMode('workspace');
                pushCommand(`new conversation: ${created.id}`);
                return true;
            }

            if (command === '/conversations' || command === '/sessions') {
                const sessions = await apiJson('/sessions');
                pushCommand(formatRows((Array.isArray(sessions) ? sessions : []).slice(0, 15).map((item: any, index: number) =>
                    `${index + 1}. ${item.id} - ${item.title}`
                )));
                return true;
            }

            if (command === '/resume' || command === '/load') {
                if (!args) {
                    pushCommand('usage: /resume <conversation-id>');
                } else {
                    const loaded = await postJson('/sessions/load', {id: args});
                    setSessionId(loaded.id);
                    const loadedHistory = Array.isArray(loaded.history)
                        ? loaded.history.map((msg: any) => ({
                            role: String(msg.role || 'assistant'),
                            content: String(msg.role || 'assistant') === 'assistant'
                                ? cleanVisibleAssistantText(String(msg.content || ''))
                                : String(msg.content || '')
                        }))
                        : [];
                    setHistory(loadedHistory);
                    pushCommand(`resumed: ${loaded.id}`);
                }
                return true;
            }

            if (command === '/rename') {
                if (!args) {
                    pushCommand('usage: /rename <new title>');
                } else {
                    const result = await postJson('/sessions/rename', {id: sessionId, title: args});
                    pushCommand(result.status === 'success' ? `renamed: ${args}` : 'rename failed');
                }
                return true;
            }

            if (command === '/delete-session') {
                const target = args || sessionId;
                const result = await apiJson(`/sessions/${encodeURIComponent(target)}`, {method: 'DELETE'});
                pushCommand(`${result.deleted || result.cleared ? 'deleted' : 'not deleted'}: ${target}`);
                return true;
            }

            if (command === '/history') {
                const loaded = await apiJson(`/history?session_id=${encodeURIComponent(sessionId)}`);
                const loadedHistory = Array.isArray(loaded)
                    ? loaded.map((msg: any) => ({
                        role: String(msg.role || 'assistant'),
                        content: String(msg.role || 'assistant') === 'assistant'
                            ? cleanVisibleAssistantText(String(msg.content || ''))
                            : String(msg.content || '')
                    }))
                    : [];
                setHistory(loadedHistory);
                pushCommand(`history loaded: ${sessionId}`);
                return true;
            }

            if (command === '/recap' || command === '/insights' || command === '/team-onboarding') {
                const sessions = await apiJson('/sessions');
                const userCount = history.filter(msg => msg.role === 'user').length;
                const assistantCount = history.filter(msg => msg.role === 'assistant').length;
                const changedFiles = touchedFiles.map(file => `${file.status}:${file.name}`).slice(0, 8);
                pushCommand(formatRows([
                    `session: ${sessionId}`,
                    `messages: ${userCount} user, ${assistantCount} assistant`,
                    `tasks: ${tasks.length}`,
                    `activities: ${activityItems.length}`,
                    `recent sessions: ${(Array.isArray(sessions) ? sessions : []).slice(0, 5).map((item: any) => item.id).join(', ') || 'none'}`,
                    `files: ${changedFiles.length ? changedFiles.join(', ') : 'none'}`
                ]));
                return true;
            }

            if (command === '/skills') {
                const data = await apiJson('/skills');
                const query = args.replace(/^reload\s*/i, '').trim().toLowerCase();
                const rows = (data.skills || [])
                    .filter((skill: any) => !query || String(skill.name).toLowerCase().includes(query))
                    .map((skill: any) => `${skill.name} - ${skill.enabled ? 'enabled' : 'disabled'} - ${skill.description}`);
                pushCommand(formatRows(rows));
                return true;
            }

            if (command === '/tools') {
                const data = await apiJson('/tools');
                const query = args.replace(/^reload\s*/i, '').trim().toLowerCase();
                pushCommand(formatRows((data.tools || [])
                    .filter((tool: any) => !query || String(tool.name).toLowerCase().includes(query))
                    .map((tool: any) =>
                    `${tool.name} - ${tool.enabled ? 'enabled' : 'disabled'} - ${tool.description}${tool.read_only ? ' [read]' : ''}${tool.safe ? ' [safe]' : ''}`
                )));
                return true;
            }

            if (command === '/plugins') {
                const sub = parts[0]?.toLowerCase();
                if ((sub === 'enable' || sub === 'disable' || sub === 'remove') && parts[1]) {
                    const result = await manageJson(sub, 'plugin', parts[1]);
                    pushCommand(formatManageResult(result));
                } else if (sub === 'reload') {
                    const result = await manageJson('reload', 'plugins');
                    pushCommand(formatManageResult(result));
                } else {
                    const data = await apiJson('/plugins');
                    const query = args.replace(/^(reload|list)\s*/i, '').trim().toLowerCase();
                    pushCommand(formatRows((data.plugins || [])
                        .filter((plugin: any) => !query || String(plugin.id).toLowerCase().includes(query) || String(plugin.name || '').toLowerCase().includes(query))
                        .map((plugin: any) => `${plugin.id} - ${plugin.enabled ? 'enabled' : 'disabled'}`)));
                }
                return true;
            }

            if (command === '/tasks') {
                const {tasks: latestTasks} = await loadPanelData();
                pushCommand(formatRows(latestTasks.map(task => `${task.id} - ${task.status} - ${task.subject}`)));
                return true;
            }

            if (command === '/todo') {
                const action = parts[0]?.toLowerCase();
                if (action === 'add') {
                    const subject = args.slice(parts[0].length).trim();
                    if (!subject) {
                        pushCommand('usage: /todo add <text>');
                    } else {
                        const result = await postJson('/tasks', {subject});
                        await loadPanelData();
                        addActivityItem({
                            kind: 'todo',
                            title: 'Updated todo list',
                            summary: subject,
                            status: 'done',
                            detail: `created: ${result.task.id}\n${subject}`,
                            toolName: 'todo'
                        });
                        pushCommand(`todo created: ${result.task.id}`);
                    }
                } else if (action === 'done') {
                    const taskId = parts[1];
                    if (!taskId) {
                        pushCommand('usage: /todo done <task-id>');
                    } else {
                        await apiJson(`/tasks/${encodeURIComponent(taskId)}`, {
                            method: 'PATCH',
                            body: JSON.stringify({status: 'completed'})
                        });
                        await loadPanelData();
                        addActivityItem({
                            kind: 'todo',
                            title: 'Updated todo list',
                            summary: taskId,
                            status: 'done',
                            detail: `completed: ${taskId}`,
                            toolName: 'todo'
                        });
                        pushCommand(`todo completed: ${taskId}`);
                    }
                } else {
                    pushCommand('usage: /todo add <text> | /todo done <task-id>');
                }
                return true;
            }

            if (command === '/review' || command === '/code-review' || command === '/security-review' || command === '/simplify' || command === '/ultrareview') {
                const [statResult, diffResult] = await Promise.all([
                    runLocal('git', ['diff', '--stat'], PROJECT_ROOT, 120000),
                    runLocal('git', ['diff', '--', args || '.'], PROJECT_ROOT, 120000)
                ]);
                const header = command === '/security-review'
                    ? 'security review input'
                    : command === '/simplify'
                        ? 'simplification review input'
                        : 'code review input';
                pushCommand(formatRows([
                    header,
                    statResult || 'No uncommitted diff found.',
                    diffResult ? cleanPreview(diffResult, 60) : 'Nothing to review.'
                ]));
                return true;
            }

            if (command === '/batch' || command === '/fork') {
                if (!args) {
                    pushCommand(`usage: ${command} <instruction>`);
                } else {
                    const result = await postJson('/multi_agent', {command, prompt: args});
                    pushCommand(`${result.status}: ${result.result}`);
                }
                return true;
            }

            if (command === '/files') {
                const data = await apiJson(`/files?q=${encodeURIComponent(args)}`);
                pushCommand(formatRows((data.files || []).map((file: string) => file)));
                return true;
            }

            if (command === '/run') {
                if (!args) {
                    pushCommand('usage: /run <command>');
                } else {
                    const started = addActivityItem({
                        kind: 'run',
                        title: 'Ran command',
                        summary: args,
                        status: 'running',
                        command: args,
                        toolName: 'run'
                    });
                    const result = await postJson('/run', {command: args});
                    const output = cleanPreview(result.output || '', 30);
                    const error = cleanPreview(result.error || '', 16);
                    setActivityItems(prev => prev.map(activity => activity.id === started.id ? {
                        ...activity,
                        status: result.returncode === 0 ? 'done' : 'error',
                        output,
                        error
                    } : activity));
                    setSelectedActivityId(started.id);
                    setPanelMode('activity');
                }
                return true;
            }

            if (command === '/multi-agent' || command === '/multi_agent') {
                const result = await postJson('/multi_agent', {command: parts[0] || '/run', prompt: args});
                pushCommand(`${result.status}: ${result.result}`);
                return true;
            }

            if (command === '/stop') {
                setIsThinking(false);
                completeRunningActivities('error');
                pushCommand('stopped visible working state for this CLI session');
                return true;
            }

            if (command === '/btw') {
                pushCommand(args ? `side note recorded locally: ${args}` : 'usage: /btw <side question>');
                return true;
            }

            if (command === '/advisor' || command === '/focus' || command === '/fewer-permission-prompts') {
                pushCommand(formatRows([
                    `${command}: local status`,
                    `mode: ${(await apiJson('/status')).mode}`,
                    'Use /mode auto, /mode plan, /mode bypass, /permissions, /tools, and /mcp for the real local controls.'
                ]));
                return true;
            }

            if (command === '/background' || command === '/desktop' || command === '/mobile' || command === '/teleport' || command === '/remote-control' || command === '/remote-env') {
                unsupportedCommand(command, 'This command depends on Claude cloud/mobile/remote-control services. NEXUS can keep local sessions with /resume, /conversations, and /new.');
                return true;
            }

            if (command === '/chrome' || command === '/install-github-app' || command === '/install-slack-app') {
                unsupportedCommand(command, 'This needs an external browser/account integration. NEXUS local CLI can still inspect /env, /plugins, /mcp, and /health.');
                return true;
            }

            if (command === '/passes' || command === '/powerup' || command === '/privacy-settings' || command === '/radio' || command === '/stickers' || command === '/upgrade' || command === '/usage-credits') {
                unsupportedCommand(command, 'This is an Anthropic account/product command, not a local NEXUS runtime action.');
                return true;
            }

            if (command === '/claude-api' || command === '/run-skill-generator') {
                unsupportedCommand(command, 'This bundled Claude skill is not installed in this NEXUS workspace. Use /skills and /plugins to inspect what is actually available.');
                return true;
            }

            if (command === '/deep-research' || command === '/ultraplan') {
                pushCommand(args
                    ? `Use normal chat for this prompt so NEXUS can answer with the active provider: ${args}`
                    : `usage: ${command} <prompt>`);
                return true;
            }

            if (command === '/rewind') {
                unsupportedCommand(command, 'Checkpoint rewind is not implemented in this local CLI yet. Use git status/diff/log and /reset tasks or /reset nexus for real available recovery paths.');
                return true;
            }

            if (command === '/scroll-speed') {
                unsupportedCommand(command, 'Scroll speed belongs to the terminal emulator, not the Ink app runtime.');
                return true;
            }

            if (command === '/setup-bedrock' || command === '/setup-vertex') {
                unsupportedCommand(command, 'Provider setup is config-backed here. Use /provider add <name> <model>, /provider enable <name>, and /config set for real NEXUS configuration.');
                return true;
            }

            if (command === '/paste') {
                try {
                    const pastedPath = await saveClipboardImage();
                    const info = await stat(pastedPath);
                    addActivityItem({
                        kind: 'file',
                        title: 'Attached clipboard image',
                        summary: path.basename(pastedPath),
                        status: 'done',
                        files: [pastedPath],
                        detail: `${pastedPath}\n${formatTokens(info.size)}B`,
                        toolName: 'paste'
                    });
                    setInput(current => `${current}${current.trim() ? ' ' : ''}"${pastedPath}"`);
                    pushCommand(`attached clipboard image: ${pastedPath}`);
                } catch {
                    pushSystem('No clipboard image found. Copy an image first, or paste/drag a file path into the chat box.');
                }
                return true;
            }

            pushCommand(`Unknown command: ${rawCommand}. Type /help.`);
            return true;
        } catch (error) {
            pushSystem(`COMMAND_ERROR: ${error instanceof Error ? error.message : String(error)}`);
            return true;
        }
    };

    const handleSubmit = async (value: string) => {
        if (!value) return;
        if (value.toLowerCase() === 'exit' || value.toLowerCase() === 'quit') {
            await stopVoiceIfRunning();
            exit();
            return;
        }

        if (await handleSlashCommand(value)) {
            setInput('');
            return;
        }

        const attachedFiles = await resolveInputAttachments(value);
        const prompt = attachmentPrompt(value, attachedFiles);
        const userMsg: Message = { role: 'user', content: value };
        setHistory(prev => [...prev, userMsg]);
        if (attachedFiles.length > 0) {
            addActivityItem({
                kind: 'file',
                title: `Attached ${attachedFiles.length} file${attachedFiles.length === 1 ? '' : 's'}`,
                summary: attachedFiles.map(file => file.name).join(', '),
                status: 'done',
                files: attachedFiles.map(file => file.path),
                detail: attachedFiles.map(file => `${file.name} (${file.kind}, ${formatTokens(file.size)}B)\n${file.path}`).join('\n\n'),
                toolName: 'attachment'
            });
            appendTimeline({kind: 'read', weight: 40 * attachedFiles.length, label: 'Attached files'});
        }
        appendTimeline({kind: 'text', weight: estimateTokens(value), label: 'User prompt'});
        setInput('');
        setIsThinking(true);
        setWorkingPhase('querying');

        try {
            const response = await fetch(`${API_BASE}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt, session_id: sessionId, provider, model, stream: true })
            });

            if (!response.body) throw new Error("No response body");
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            
            let assistantContent = '';
            let streamBuffer = '';
            setHistory(prev => [...prev, { role: 'assistant', content: '' }]);
            appendTimeline({kind: 'text', weight: 12, label: 'Assistant stream'});

            const processStreamText = (text: string) => {
                if (!text) return;

                const markerQuestion = parseQuestionMarker(text);
                if (markerQuestion) {
                    setPendingQuestion(markerQuestion);
                    setPanelMode('question');
                    appendTimeline({kind: 'step', weight: 20, label: 'Question pending'});
                    text = stripQuestionMarkers(text);
                    if (!text.trim()) return;
                }

                // ── [INTELLIGENCE_EXTRACTION]: Robust marker parsing
                if (text.includes("[TOOL_START:")) {
                    try {
                        const markerMatch = text.match(/\[TOOL_START:([^:]+):(.*)\]/);
                        if (markerMatch) {
                            const [_, toolName, paramsStr] = markerMatch;
                            const params = JSON.parse(paramsStr);
                            setWorkingPhase(inferWorkingPhaseFromTool(toolName, params));
                            const toolKind = classifyTool(toolName);
                            const normalizedToolName = toolName.toLowerCase();
                            appendTimeline({kind: toolKind, weight: 40, label: toolName});
                            addActivityItem(activityFromTool(toolName, params));
                            
                            // Track file changes for sidebar
                            const fileCommand = String(params.command || '').toLowerCase();
                            const isFileMutation = normalizedToolName === 'write_file'
                                || (normalizedToolName === 'file_edit' && fileCommand !== 'view');
                            if (isFileMutation) {
                                const filename = params.filename || params.path;
                                if (filename) {
                                    const fileNameOnly = filename.split(/[/\\]/).pop() || filename;
                                    setTouchedFiles(prev => {
                                        const filtered = prev.filter(f => f.name !== fileNameOnly);
                                        return [{name: fileNameOnly, status: 'MODIFIED'}, ...filtered.slice(0, 2)];
                                    });
                                    setActivities(prev => [`Δ Modifying ${fileNameOnly}`, ...prev.slice(0, 2)]);
                                    appendTimeline({kind: 'write', weight: 90, label: fileNameOnly});
                                    
                                    if (params.new_string || params.content) {
                                        const content = params.new_string || params.content;
                                        setLastChange(content.split('\n').slice(0, 8).join('\n'));
                                    }
                                }
                            } else {
                                setActivities(prev => [`⚙ Executing ${toolName}`, ...prev.slice(0, 2)]);
                            }
                        }
                    } catch(e) {
                        // Silent fail for malformed markers during streaming
                    }
                }

                if (text.includes("[TOOL_RESULT:")) {
                    try {
                        const resultMatch = text.match(/\[TOOL_RESULT:([^:]+):(.*)\]/);
                        if (resultMatch) {
                            const [, toolName, resultStr] = resultMatch;
                            const result = JSON.parse(resultStr);
                            setWorkingPhase(inferWorkingPhaseFromTool(toolName, result));
                            updateLatestActivityForTool(toolName, result);
                        }
                    } catch(e) {
                        // Tool result markers are best-effort UI telemetry.
                    }
                }

                // Append to visible content only if it's not a pure marker chunk
                const visibleChunk = text.trim();
                if (
                    !visibleChunk.startsWith("[TOOL_START:")
                    && !visibleChunk.startsWith("[TOOL_RESULT:")
                    && !visibleChunk.startsWith("[TOOL_END:")
                ) {
                    setWorkingPhase(inferWorkingPhaseFromText(visibleChunk) || 'streaming');
                    assistantContent += text;
                    setHistory(prev => {
                        const newHist = [...prev];
                        newHist[newHist.length - 1] = { role: 'assistant', content: assistantContent };
                        return newHist;
                    });
                }

                setIsThinking(false);
            };

            while (true) {
                const { done, value: chunk } = await reader.read();
                if (done) break;

                streamBuffer += decoder.decode(chunk, {stream: true});
                const frames = streamBuffer.split(/\r?\n\r?\n/);
                streamBuffer = frames.pop() || '';

                for (const frame of frames) {
                    processStreamText(extractSsePayload(frame));
                }
            }

            streamBuffer += decoder.decode();
            if (streamBuffer.trim()) {
                processStreamText(extractSsePayload(streamBuffer));
            }
            const choiceQuestion = detectChoiceQuestion(assistantContent);
            if (choiceQuestion) {
                setPendingQuestion(choiceQuestion);
                setPanelMode('question');
                appendTimeline({kind: 'step', weight: 20, label: 'Question pending'});
            }
            completeRunningActivities('done');
            appendTimeline({kind: 'success', weight: 24, label: 'Turn complete'});
        } catch (err) {
            setHistory(prev => [...prev, { role: 'system', content: "SYSTEM_ERROR: Kernel API unreachable." }]);
            completeRunningActivities('error');
            appendTimeline({kind: 'error', weight: 90, label: 'Kernel API unreachable'});
        } finally {
            void loadPanelData();
            setIsThinking(false);
        }
    };

    return (
        <Box flexDirection="row" width={width} height={height} minHeight={height} backgroundColor={THEME.appBg}>
            <Box
                flexDirection="column"
                width={leftPanelWidth}
                flexShrink={1}
                height={height}
                backgroundColor={THEME.panelAltBg}
            >
                <Banner width={chatContentWidth} frame={motionFrame} />

                <Box flexDirection="column" height={chatViewportHeight} width={chatContentWidth + 2} paddingX={1} backgroundColor={THEME.panelAltBg}>
                    {visibleChatLines.map(line => (
                        <ChatLineView
                            key={line.key}
                            line={line}
                            width={chatContentWidth}
                        />
                    ))}
                    {isThinking && (
                        <WorkingStatus frame={motionFrame} width={chatContentWidth} phase={workingPhase} />
                    )}
                </Box>

                {showCommandPalette && (
                    <CommandPalette
                        matches={slashMatches}
                        selectedIndex={Math.min(commandIndex, slashMatches.length - 1)}
                    />
                )}

                {voiceMode !== 'off' && (
                    <Box paddingX={1} paddingY={0} justifyContent="space-between" backgroundColor={THEME.panelAltBg}>
                        <Box>
                            <Text color={voicePhaseColor(voicePhase)} bold>🎙 {voiceMode} · {voicePhaseLabel(voicePhase)} </Text>
                            <VoiceEqualizer phase={voicePhase} frame={motionFrame} bars={18} />
                        </Box>
                    </Box>
                )}

                {/* PROMPT BOX */}
                <Box height={3} paddingX={1} paddingY={1} marginBottom={0} backgroundColor={THEME.inputBg}>
                    <Box marginRight={1}>
                        <Text color="blueBright" bold>{"> "}</Text>
                    </Box>
                    <TextInput value={input} onChange={setInput} onSubmit={handleSubmit} placeholder="Type your message or @path/to/file" />
                </Box>

                {/* APP FOOTER */}
                <Box justifyContent="space-between" paddingX={1} marginTop={0} marginBottom={0} backgroundColor={THEME.panelSoftBg}>
                    <Text color="blueBright">~\{process.cwd().split(/[/\\]/).pop()}</Text>
                    <Box>
                        <Text color="red">no sandbox </Text>
                        <Text color="grey30">(see /docs)</Text>
                    </Box>
                    <Box>
                        {voiceMode !== 'off' ? (
                            <Text color={voicePhaseColor(voicePhase)} bold>🎙️ voice: {voiceMode} · {voicePhaseLabel(voicePhase)}</Text>
                        ) : (
                            <Text color="grey30">🎙️ voice: off</Text>
                        )}
                    </Box>
                </Box>
            </Box>

            {isWide && (
                <Box width={sidebarWidth} height={height} backgroundColor={THEME.panelBg}>
                    <NexusWorkspacePanel
                        timeline={timeline}
                        usage={usage}
                        mode={panelMode}
                        agents={agents}
                        tasks={tasks}
                        touchedFiles={touchedFiles}
                        activityItems={activityItems}
                        pendingQuestion={pendingQuestion}
                        selectedActivityId={selectedActivityId}
                        selectedAgentId={selectedAgentId}
                        motionFrame={motionFrame}
                        voiceMode={voiceMode}
                        voicePhase={voicePhase}
                        voiceTranscriptPreview={voiceTranscriptPreview}
                        voiceReplyPreview={voiceReplyPreview}
                        width={sidebarWidth}
                        height={height}
                    />
                </Box>
            )}
        </Box>
    );
};

clearTerminalForInk();
render(<App />);
