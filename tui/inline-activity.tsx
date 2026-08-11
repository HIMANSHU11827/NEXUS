import React from 'react';
import {Box, Text} from 'ink';
import {getTheme, activityColor, activityGlyph, TRANSCRIPT_SURFACE_BG} from './theme.js';

export interface InlineActivityItem {
    kind?: string;
    title?: string;
    status?: string;
    toolName?: string;
    summary?: string;
    command?: string;
    operation?: string;
    detail?: string;
    preview?: string;
    files?: string[];
    sources?: string[];
    output?: string;
    error?: string;
    startedAt?: number;
    durationMs?: number;
    logo?: string;
    logoColor?: string;
    number?: number;
}

const cleanToolName = (raw: unknown): string => String(raw || '')
    .replace(/^mcp_server__/, '')
    .replace(/^mcp__/, '')
    .replace(/^skill__/, '')
    .replace(/^hive__/, '')
    .replace(/^plugin__/, '');

const humanize = (raw: unknown): string => cleanToolName(raw)
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

const compactTarget = (raw: unknown): string => {
    const value = String(raw || '').trim().replace(/^['"]|['"]$/g, '');
    if (!value) return '';
    try {
        const url = new URL(value.startsWith('www.') ? `https://${value}` : value);
        return url.hostname.replace(/^www\./, '');
    } catch {
        return value;
    }
};

const isGenericSearchTarget = (raw: unknown): boolean =>
    /^(?:web[ _-]?)?search(?:ing)?$/i.test(String(raw || '').trim());

const mcpPair = (toolName: unknown): {server: string; tool: string} => {
    const name = cleanToolName(toolName).trim();
    if (!name) return {server: '', tool: 'mcp'};
    const parts = name.split(/__|::|\/|\|/).filter(Boolean);
    if (parts.length > 1) {
        return {server: parts.slice(0, -1).join('·'), tool: parts[parts.length - 1]};
    }
    const sep = name.search(/[:_]/);
    if (sep > 0) return {server: name.slice(0, sep), tool: name.slice(sep + 1)};
    return {server: '', tool: name};
};

const isRunning = (status?: string) =>
    ['running', 'queued', 'pending', 'in_progress', 'working', 'active'].includes(String(status || '').toLowerCase());

const isError = (status?: string) =>
    ['error', 'failed', 'failure', 'cancelled', 'canceled', 'blocked', 'denied', 'rejected'].includes(String(status || '').toLowerCase());

const isCancelled = (status?: string) =>
    ['cancelled', 'canceled'].includes(String(status || '').toLowerCase());

const isBlocked = (status?: string) =>
    ['blocked', 'denied', 'rejected'].includes(String(status || '').toLowerCase());

export const activityKindLabel = (kind?: string): string => {
    const labels: Record<string, string> = {
        plan: 'PLAN', todo: 'PLAN', terminal: 'TERMINAL', run: 'TERMINAL', command: 'TERMINAL',
        file: 'FILE', test: 'TEST', search: 'SEARCH', browser: 'WEB', hive: 'HIVE',
        agent: 'AGENT', worker: 'AGENT', approval: 'APPROVAL', error: 'ERROR', retry: 'RETRY',
        mcp: 'MCP', skill: 'SKILL', plugin: 'PLUGIN', provider: 'MODEL', rag: 'CONTEXT',
        memory: 'MEMORY', compact: 'CONTEXT', background: 'BACKGROUND', config: 'CONFIG',
        settings: 'SETTINGS', tool: 'TOOL'
    };
    return labels[String(kind || 'tool').toLowerCase()] || 'TOOL';
};

export const activityStatusWord = (status?: string): string => {
    if (isBlocked(status)) return 'WAIT';
    if (isCancelled(status)) return 'STOP';
    if (isError(status)) return 'FAIL';
    if (isRunning(status)) return 'LIVE';
    return 'DONE';
};

const formatCompactDuration = (ms?: number): string => {
    if (!ms || ms <= 0) return '';
    if (ms < 1000) return `${Math.max(1, Math.round(ms))}ms`;
    const totalSeconds = Math.round(ms / 1000);
    if (totalSeconds < 60) return `${totalSeconds}s`;
    const minutes = Math.floor(totalSeconds / 60);
    if (minutes < 60) return `${minutes}m${totalSeconds % 60}s`;
    return `${Math.floor(minutes / 60)}h${minutes % 60}m`;
};

const compactActivityName = (activity: InlineActivityItem): string => {
    if (activity.kind === 'mcp') {
        const {server, tool} = mcpPair(activity.toolName);
        return server ? `${humanize(server)}/${humanize(tool)}` : humanize(tool) || 'mcp';
    }
    return humanize(activity.toolName) || humanize(activity.kind) || 'tool';
};

const compactActivityTarget = (activity: InlineActivityItem, name: string): string => {
    const raw = activity.command || activity.summary || activity.files?.[0] || '';
    if (!raw) return '';
    const target = activity.kind === 'file'
        ? String(raw).split(/[/\\]/).filter(Boolean).pop() || String(raw)
        : compactTarget(raw);
    if (!target || humanize(target).toLowerCase() === humanize(name).toLowerCase()) return '';
    const escapedName = humanize(name).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const withoutRepeatedName = target.replace(new RegExp(`^${escapedName}\\s*(?:[·—:|-])\\s*`, 'i'), '').trim();
    if (activity.kind === 'search' && isGenericSearchTarget(target)) return '';
    return withoutRepeatedName || target;
};

const InlineActivityBody = ({activity, maxLabel}: {
    activity: InlineActivityItem;
    maxLabel: number;
}) => {
    const theme = getTheme();
    const kind = String(activity.kind || 'tool');
    const status = String(activity.status || '');
    const running = isRunning(status);
    const error = isError(status);
    const color = activity.logoColor || activityColor(kind);
    const name = compactActivityName(activity);
    const target = compactActivityTarget(activity, name);
    const duration = formatCompactDuration(
        activity.durationMs ?? (running && activity.startedAt ? Date.now() - activity.startedAt : undefined)
    );
    let label = [name, target, duration].filter(Boolean).join(' · ');
    const budget = Math.max(8, maxLabel - 2);
    if (label.length > budget) label = `${label.slice(0, Math.max(1, budget - 1))}…`;
    // Status is conveyed by the row itself: failed/blocked/cancelled is wholly
    // red, active uses the tool color, and completed work stays quiet grey.
    const rowColor = error ? theme.statusError : running ? color : 'grey';

    return (
        <Text color={rowColor} bold={running || error} wrap="truncate">{label}</Text>
    );
};

export const InlineActivity = React.memo(({activity, width, focused = false, expanded = false}: {
    activity: InlineActivityItem;
    width: number;
    frame: number;
    focused?: boolean;
    expanded?: boolean;
}) => (
    <Box
        width={width}
        minWidth={1}
        backgroundColor={TRANSCRIPT_SURFACE_BG}
    >
        <Text color={isError(activity.status) ? getTheme().statusError : focused ? getTheme().secondary : 'grey'} bold={focused || isError(activity.status)}>{expanded ? 'v' : '›'} </Text>
        <InlineActivityBody activity={activity} maxLabel={Math.max(1, width - 2)} />
    </Box>
));

export interface McpServerItem {
    id: string;
    command?: string;
    args?: string;
    description?: string;
    active?: boolean;
    connected?: boolean;
    status?: string;
}

export const mcpServerActive = (server: McpServerItem): boolean =>
    server.active === true
    || server.connected === true
    || ['active', 'connected', 'running'].includes(String(server.status || '').toLowerCase());

export const MCPPanelBody = React.memo(({servers}: {servers: McpServerItem[]}) => {
    const theme = getTheme();
    if (servers.length === 0) {
        return (
            <Box flexDirection="column">
                <Text color="grey30">No MCP servers configured</Text>
                <Text color="grey30">Add servers to .nexus config · /mcp reload</Text>
            </Box>
        );
    }
    const activeCount = servers.filter(mcpServerActive).length;
    return (
        <Box flexDirection="column" width="100%">
            <Box marginBottom={1}>
                <Text bold color="white">MCP Servers</Text>
                <Text color="grey30">  {activeCount} active · {servers.length - activeCount} inactive</Text>
            </Box>
            {servers.map(server => {
                const active = mcpServerActive(server);
                const dotColor = active ? theme.statusDone : theme.textDim;
                return (
                    <Box key={server.id} flexDirection="column" marginBottom={1}>
                        <Box>
                            <Text color={dotColor}>{active ? '●' : '○'} </Text>
                            <Text color={active ? 'magentaBright' : 'grey30'} bold>{server.id}</Text>
                            <Text color="grey30">  {active ? 'active' : 'inactive'}</Text>
                        </Box>
                        {server.command ? (
                            <Text color="grey30" wrap="truncate">
                                {server.command}{server.args ? ` ${server.args}` : ''}
                            </Text>
                        ) : null}
                        {server.description ? (
                            <Text color="grey30" wrap="truncate">{server.description}</Text>
                        ) : null}
                    </Box>
                );
            })}
        </Box>
    );
});
