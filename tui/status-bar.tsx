/** One-line run footer with readable safety and connection state. */
import React from 'react';
import {Box, Text} from 'ink';
import {getTheme} from './theme.js';
import type {UsageInfo, SandboxTier, PermissionMode} from './types.js';

interface StatusBarProps {
    width?: number;
    usage: UsageInfo;
    sandboxTier: SandboxTier;
    permissionMode: PermissionMode;
    voiceMode: string;
    voicePhase: string;
    mcpCount: number;
    agentCount: number;
    taskCount: number;
    queuePending?: number | null;
    queueWorker?: string;
    activeTool?: string;
    connectionState?: 'connecting' | 'online' | 'offline';
}

const fmtTokens = (tokens?: number): string => {
    if (!tokens) return '0';
    if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
    if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`;
    return String(tokens);
};

export const StatusBar: React.FC<StatusBarProps> = ({
    width = Math.max(20, process.stdout.columns || 100),
    usage,
    sandboxTier,
    permissionMode,
    voiceMode,
    voicePhase,
    mcpCount,
    agentCount,
    taskCount,
    queuePending = null,
    queueWorker = 'unknown',
    activeTool,
    connectionState = 'online'
}) => {
    const theme = getTheme();
    const tokens = usage.tokens ?? 0;
    const contextPercent = usage.contextWindow && usage.contextWindow > 0
        ? Math.min(100, Math.round(tokens / usage.contextWindow * 100))
        : 0;
    const sandboxLabel = sandboxTier === 'no_sandbox' ? 'off' : sandboxTier;
    const sandboxColor = sandboxTier === 'no_sandbox' ? theme.error : sandboxTier === 'docker' ? theme.secondary : theme.success;
    const permissionColor = permissionMode === 'all' ? theme.warning : permissionMode === 'ask' ? theme.info : theme.success;
    const connectionColor = connectionState === 'online' ? theme.success : connectionState === 'connecting' ? theme.warning : theme.error;
    const modelLabel = usage.model || 'selecting';
    const clock = new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', hour12: false});

    if (width < 58) {
        return (
            <Box width={width} paddingX={1} justifyContent="space-between" backgroundColor={theme.panelSoftBg}>
                <Text color={theme.textDim} wrap="truncate">ctx {contextPercent}%  {sandboxLabel}/{permissionMode}</Text>
                <Text color={connectionColor}>{connectionState}</Text>
            </Box>
        );
    }

    if (width < 96) {
        return (
            <Box width={width} paddingX={1} justifyContent="space-between" backgroundColor={theme.panelSoftBg}>
                <Text color={theme.textDim} wrap="truncate">{modelLabel} · ctx {contextPercent}%</Text>
                <Text color={sandboxColor}>{sandboxLabel}</Text>
                <Text color={permissionColor}>{permissionMode}</Text>
                <Text color={connectionColor}>● {connectionState}</Text>
            </Box>
        );
    }

    return (
        <Box width={width} paddingX={1} justifyContent="space-between" backgroundColor={theme.panelSoftBg}>
            <Text color={theme.textDim}><Text color={theme.secondary}>Model: </Text>{modelLabel}</Text>
            <Text color={sandboxColor}><Text color={theme.secondary}>Sandbox: </Text>{sandboxLabel}</Text>
            <Text color={permissionColor}><Text color={theme.secondary}>Permissions: </Text>{permissionMode}</Text>
            <Text color={theme.textDim}><Text color={theme.secondary}>Queue(session): </Text>{queuePending == null ? '—' : `${queuePending} ${queueWorker === 'running' ? 'ready' : queueWorker}`}</Text>
            <Text color={connectionColor}><Text color={theme.secondary}>Connection: </Text>● {connectionState}</Text>
            {width >= 124 && <Text color={theme.textMuted}>{clock}</Text>}
        </Box>
    );
};
