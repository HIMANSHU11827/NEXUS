/**
 * Nexus TUI v3.0 — Status Bar
 * Bottom bar: model, tokens, cost, sandbox, permissions, voice, LSP.
 */
import React from 'react';
import {Box, Text} from 'ink';
import {getTheme} from './theme.js';
import type {UsageInfo, SandboxTier, PermissionMode} from './types.js';

interface StatusBarProps {
    usage: UsageInfo;
    sandboxTier: SandboxTier;
    permissionMode: PermissionMode;
    voiceMode: string;
    voicePhase: string;
    mcpCount: number;
    agentCount: number;
    taskCount: number;
    activeTool?: string;
}

function fmtTokens(tokens?: number): string {
    if (!tokens) return '0';
    if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
    if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(0)}K`;
    return String(tokens);
}

function fmtCost(cost?: number): string {
    if (!cost) return '$0.00';
    return `$${cost.toFixed(2)}`;
}

function voicePhaseLabel(phase: string): string {
    const map: Record<string, string> = {listening:'🎤', processing:'⚙️', speaking:'🔊', off:'off'};
    return map[phase] || phase;
}

export const StatusBar: React.FC<StatusBarProps> = ({
    usage, sandboxTier, permissionMode, voiceMode, voicePhase,
    mcpCount, agentCount, taskCount, activeTool,
}) => {
    const theme = getTheme();
    const tokens = usage.tokens ?? 0;
    const contextWindow = usage.contextWindow ?? 0;
    const sandboxColor = sandboxTier === 'no_sandbox' ? theme.error : sandboxTier === 'docker' ? theme.secondary : theme.success;
    const permColor = permissionMode === 'all' ? theme.warning : permissionMode === 'ask' ? theme.info : permissionMode === 'allowlist' ? theme.secondary : theme.success;

    return (
        <Box justifyContent="space-between" paddingX={1} backgroundColor={theme.panelSoftBg}>
            {/* Left: model + tokens + cost */}
            <Box>
                {usage.model && (
                    <Text color={theme.primary} bold>{usage.model}</Text>
                )}
                {usage.tokens !== undefined && (
                    <Text color={theme.textDim}>  {fmtTokens(tokens)} tok</Text>
                )}
                {usage.cost !== undefined && usage.cost > 0 && (
                    <Text color={theme.textMuted}> · {fmtCost(usage.cost)}</Text>
                )}
                {contextWindow > 0 && tokens > 0 && (
                    <Text color={theme.textMuted}> · {(tokens / contextWindow * 100).toFixed(0)}%</Text>
                )}
            </Box>

            {/* Center: counts + active tool */}
            <Box>
                {activeTool && (
                    <Text color={theme.toolColor}>🔧{activeTool} </Text>
                )}
                {agentCount > 0 && <Text color={theme.hiveColor}>🐝{agentCount} </Text>}
                {taskCount > 0 && <Text color={theme.planColor}>📋{taskCount} </Text>}
                {mcpCount > 0 && <Text color={theme.mcpColor}>🔌{mcpCount} </Text>}
            </Box>

            {/* Right: sandbox + perm + voice */}
            <Box>
                <Text color={sandboxColor}>{sandboxTier === 'no_sandbox' ? '⚡nosandbox' : sandboxTier === 'docker' ? '🐳docker' : '🛡️simple'}</Text>
                <Text color={permColor}>  {permissionMode === 'all' ? '🔓all' : permissionMode === 'ask' ? '❓ask' : permissionMode === 'allowlist' ? '📋list' : '🤖auto'}</Text>
                {voiceMode !== 'off' && (
                    <Text color={theme.info}>  {voicePhaseLabel(voicePhase)} {voiceMode}</Text>
                )}
            </Box>
        </Box>
    );
};
