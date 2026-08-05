import React from 'react';
import {Box, Text} from 'ink';
import {getTheme, activityColor, activityGlyph} from './theme.js';

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
    durationMs?: number;
    logo?: string;
    logoColor?: string;
    number?: number;
}

const SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

const cleanToolName = (raw: unknown): string => String(raw || '')
    .replace(/^mcp_server__/, '')
    .replace(/^mcp__/, '')
    .replace(/^skill__/, '')
    .replace(/^hive__/, '')
    .replace(/^plugin__/, '');

const mcpPair = (toolName: unknown): {server: string; tool: string} => {
    const name = String(toolName || '').trim();
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

const formatCompactDuration = (ms?: number): string => {
    if (!ms || ms < 1000) return '';
    const totalSeconds = Math.round(ms / 1000);
    if (totalSeconds < 60) return `${totalSeconds}s`;
    const minutes = Math.floor(totalSeconds / 60);
    if (minutes < 60) return `${minutes}m${totalSeconds % 60}s`;
    return `${Math.floor(minutes / 60)}h${minutes % 60}m`;
};

const runningLabel = (a: InlineActivityItem): string => {
    const kind = String(a.kind || 'tool');
    const name = cleanToolName(a.toolName);
    const entity = a.summary && String(a.summary) !== name && String(a.summary) !== String(a.toolName)
        ? String(a.summary)
        : name || 'tool';
    switch (kind) {
        case 'run':
        case 'terminal':
            return `Running ${a.command || entity}`;
        case 'file':
            return entity ? `Reading ${entity}` : 'Reading file';
        case 'search':
            return entity ? `Searching "${entity}"` : 'Searching';
        case 'mcp': {
            const {server, tool} = mcpPair(a.toolName);
            return `Calling ${server ? `${server}:${tool}` : tool}`;
        }
        case 'skill':
            return `Running skill ${entity}`;
        case 'plugin':
            return `Loading plugin ${entity}`;
        case 'todo':
            return 'Updating todos';
        case 'compact':
            return 'Compacting context';
        default:
            return `${name}${a.detail ? ` ${String(a.detail).split('\n')[0].trim()}` : ''}`;
    }
};

const doneLabel = (a: InlineActivityItem): string => {
    const kind = String(a.kind || 'tool');
    const name = cleanToolName(a.toolName);
    const summary = String(a.summary || '');
    const command = String(a.command || '');
    switch (kind) {
        case 'run':
        case 'terminal':
            return `$ ${command || summary || name}`;
        case 'file': {
            const op = String(a.operation || '').toLowerCase();
            const entity = summary || name;
            const verb = op.includes('write')
                ? 'Write'
                : op.includes('delete')
                    ? 'Delete'
                    : op.includes('patch') || op.includes('edit') || op.includes('modify')
                        ? 'Edit'
                        : 'Read';
            const extra = Array.isArray(a.files) && a.files.length > 1 ? ` +${a.files.length - 1}` : '';
            return `${verb} ${entity}${extra}`;
        }
        case 'search':
            return summary ? `Search "${summary}"` : 'Search';
        case 'mcp': {
            const {server, tool} = mcpPair(a.toolName);
            return `MCP ${server ? `${server}:${tool}` : tool}`;
        }
        case 'skill':
            return `Skill ${name}`;
        case 'plugin':
            return `Plugin ${name}`;
        case 'todo':
            return 'Todos updated';
        case 'compact':
            return 'Context compacted';
        default: {
            let label = name || 'tool';
            const detailFirst = String(a.detail || '').trim().split('\n')[0];
            if (detailFirst) label += ` ${detailFirst}`;
            return label;
        }
    }
};

const hiveLabel = (a: InlineActivityItem): string => {
    const name = cleanToolName(a.toolName);
    const summary = String(a.summary || '');
    const title = String(a.title || '');
    const agent = name || summary || title || 'worker';
    const desc = summary && summary !== agent ? summary : title && title !== agent ? title : '';
    let label = agent;
    if (desc) label += ` — ${desc}`;
    if (isRunning(String(a.status))) {
        const current = String(a.operation || a.preview || a.detail || '').trim().split('\n')[0];
        if (current) label += `  ↳ ${current}`;
    }
    return label;
};

const InlineActivityBody = ({activity, frame, maxLabel}: {
    activity: InlineActivityItem;
    frame: number;
    maxLabel: number;
}) => {
    const theme = getTheme();
    const kind = String(activity.kind || 'tool');
    const status = String(activity.status || '');
    const running = isRunning(status);
    const error = isError(status);
    const done = !running && !error;
    const icon = activity.logo || activityGlyph(kind);
    const color = activity.logoColor || activityColor(kind);
    const statusChar = error
        ? (isCancelled(status) ? '−' : '×')
        : running
            ? SPINNER_FRAMES[Math.abs(frame) % SPINNER_FRAMES.length]
            : done
                ? '✓'
                : '';
    const statusColor = error
        ? theme.statusError
        : running
            ? theme.statusRunning
            : done
                ? theme.statusDone
                : theme.textDim;
    const baseLabel = kind === 'hive' ? hiveLabel(activity) : running ? runningLabel(activity) : doneLabel(activity);
    const label = isBlocked(status)
        ? `Blocked · ${baseLabel}`
        : isCancelled(status)
            ? `Cancelled · ${baseLabel}`
            : error
                ? `Failed · ${baseLabel}`
                : baseLabel;
    const suffix = done && activity.durationMs ? formatCompactDuration(activity.durationMs) : '';
    const fixedWidth = iconLength(icon) + 1 + (statusChar ? 1 : 0) + (suffix ? suffix.length + 2 : 0);
    let trimmedLabel = label;
    const budget = Math.max(10, maxLabel - fixedWidth);
    if (trimmedLabel.length > budget) {
        trimmedLabel = trimmedLabel.slice(0, Math.max(1, budget - 1)) + '…';
    }

    return (
        <>
            <Text color={color} bold>{icon} </Text>
            {statusChar ? <Text color={statusColor}>{statusChar} </Text> : null}
            <Text
                color={error ? theme.statusError : running ? color : 'grey'}
                bold={running || error}
                wrap="truncate"
            >
                {trimmedLabel}
            </Text>
            {suffix && <Text color="grey30">  {suffix}</Text>}
        </>
    );
};

const iconLength = (icon: string) => {
    for (const char of icon) {
        if (char.charCodeAt(0) > 0x1f000) return 2;
    }
    return icon.length;
};

export const InlineActivity = React.memo(({activity, width, frame}: {
    activity: InlineActivityItem;
    width: number;
    frame: number;
}) => (
    <Box width={width} minWidth={1}>
        <InlineActivityBody activity={activity} frame={frame} maxLabel={width} />
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
